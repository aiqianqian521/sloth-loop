"""Run-level state/reporting mixin for the Orchestrator (P2.1 slice C4).

Extracted verbatim from orchestrator.py: run-state/reporter wrappers
(_write_state_md, _recover_state, _write_handoff, _read_handoff, _stop_diagnosis,
_archive_run, _report_context, _next_steps), the contract self-check _check_scope,
and the non-idempotent producers _produce_problems / _produce_defect_report /
_classify_defect. Kept as a mixin: self.* stays instance attrs; the test_resume_step
class-level monkeypatch seam (Orchestrator._produce_defect_report = ...) works via
shadow-on-assign and MRO-on-read; _classify_defect keeps its @staticmethod.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from datetime import date, datetime
from enum import Enum

from memory_store import PatternStore
from run_reporter import RunReportContext, claim_run_ts

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_log = logging.getLogger("sloth_engine")

class PersistContext(Enum):
    """Persistence timing context (port of Codex thread-store PersistContext).

    TURN_START      -> deferrable persist (session staging)
    STANDARD        -> synchronous persist (default)
    SUBAGENT_SPAWN  -> deferrable persist (child agent boundary)
    CRITICAL        -> immediate fsync to disk (must not lose)
    """
    TURN_START = "turn_start"
    STANDARD = "standard"
    SUBAGENT_SPAWN = "subagent_spawn"
    CRITICAL = "critical"


class RunState:

    def _write_state_md(self, stop_reason: str = "", elapsed: float = 0,
                        context: PersistContext = PersistContext.STANDARD):
        result = self.reporter.write_state(self._report_context(), stop_reason, elapsed)
        if context == PersistContext.CRITICAL:
            self._flush_sync()
        return result

    def _recover_state(self) -> dict | None:
        return self.reporter.recover_state()

    def _claim_run_ts(self) -> str | None:
        """Atomically claim this run's unique archive dir name (idempotent).

        Called by the artifact writers, NOT by ``_report_context``, so a plain
        context read stays side-effect free. Two runs started in the same second
        previously shared one ``projects/<domain>/<task>/runs/<ts>/`` dir and
        clobbered each other's evidence (F9 same-project concurrency probe).
        """
        cached = getattr(self, "_run_ts", None)
        if cached:
            return cached
        started = getattr(self, "started_at", 0) or 0
        if not started:
            return None
        ts = datetime.fromtimestamp(started).strftime("%Y%m%d-%H%M%S")
        try:
            # O-3 (cycle-29 A): claim the run dir under runtime.root -- the same
            # containment root as db / io / events / logs / state.  Claiming it
            # under the *repository* root leaked run trees into the repo whenever
            # a sandbox root was configured (2026-10-25 full stress suite).
            ts = claim_run_ts(getattr(self, "_project_path", "") or "",
                              self.task_cfg.get("name") or "loop", ts,
                              root=getattr(self.runtime, "root", None))
        except Exception as exc:  # non-fatal: keep the plain timestamp
            _log.warning("[archive] run_ts claim failed: %s", exc)
        self._run_ts = ts
        return ts

    def _write_customer_report(self, stop_reason: str = "", elapsed: float = 0,
                               context: PersistContext = PersistContext.STANDARD):
        self._claim_run_ts()
        result = self.reporter.write_customer_report(self._report_context(), stop_reason, elapsed)
        if context == PersistContext.CRITICAL:
            self._flush_sync()
        return result

    def _write_handoff(self, stop_reason: str,
                       context: PersistContext = PersistContext.STANDARD):
        result = self.reporter.write_handoff(self._report_context(), stop_reason)
        if context == PersistContext.CRITICAL:
            self._flush_sync()
        return result

    def _read_handoff(self) -> dict | None:
        return self.reporter.read_handoff()

    def _stop_diagnosis(self, stop_reason: str, total_rounds: int):
        return self.reporter.diagnose_stop(stop_reason, total_rounds)

    def _archive_run(self, stop_reason: str, elapsed: float,
                     context: PersistContext = PersistContext.STANDARD):
        self._claim_run_ts()
        result = self.reporter.archive_run(self._report_context(), stop_reason, elapsed)
        if context == PersistContext.CRITICAL:
            self._flush_sync()
        return result

    def _flush_sync(self):
        """CRITICAL context: force fsync so state is durable on disk.

        Port of Codex thread-store flush-to-disk behavior. Best-effort and
        non-fatal: missing db_path or missing store just becomes a debug log.
        """
        try:
            db_path = getattr(self, "db_path", None)
            if db_path and Path(db_path).exists():
                store = getattr(self, "store", None)
                if store is not None and hasattr(store, "db"):
                    try:
                        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    except Exception:
                        pass
                fd = os.open(str(db_path), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            _log.debug("[persist] critical fsync completed for run_state")
        except Exception as exc:
            _log.warning("[persist] fsync failed (non-fatal): %s", exc)

    def _report_context(self) -> RunReportContext:
        # D-1: expose the authoritative runtime run_id to the archive path so the
        # run_history row, _index.json entry and circuit filename share one id.
        # run() sets self._run_id; the --once path leaves it empty, so derive the
        # same timestamp-based id from started_at to keep it consistent.
        run_id = getattr(self, "_run_id", None) or ""
        if not run_id:
            run_id = (f"{date.today().isoformat()}-"
                      f"{self._safe_run_component(self.task_cfg.get('name', 'loop'))}-"
                      f"{int(self.started_at)}")
        _pp = getattr(self, "_project_path", "") or ""
        # subtask-instance timestamp: YYYYMMDD-HHMMSS so each run gets its own
        # projects/<task>/runs/<run_ts>/ directory (no overwrite across runs).
        _started = getattr(self, "started_at", 0) or 0
        # F9 fix: prefer the run dir name claimed (atomically, once) by the
        # artifact writers; fall back to the plain timestamp for read-only
        # context users, so a pure read never touches the filesystem.
        run_ts = getattr(self, "_run_ts", None)
        if not run_ts and _started:
            run_ts = datetime.fromtimestamp(_started).strftime("%Y%m%d-%H%M%S")
        return RunReportContext(
            total_rounds=self.total_rounds, task_cfg=self.task_cfg,
            enable_ooda=self.enable_ooda,
            zones={"green": list(self.zone_green), "yellow": list(self.zone_yellow),
                   "red": list(self.zone_red)},
            consumer={"min_queue_size": self.consumer_min_queue,
                      "min_same_type": self.consumer_min_type,
                      "high_confidence": self.consumer_high_conf},
            run_id=run_id,
            project_path=_pp,
            run_ts=run_ts,
        )

    def _next_steps(self):
        return self.reporter.next_steps()

    def _check_scope(self):
        """Validate contract consistency and report warnings."""
        issues = []

        # scope.deny is empty → no safety net
        if not self.scope_deny:
            issues.append("scope.deny is empty — no path-level safety boundaries configured")

        # scope.allow is empty → unclear what the task CAN touch
        if not self.scope_allow:
            issues.append("scope.allow is empty — task boundaries are undefined")

        # backtest script in deny list
        backtest_script = self.bt_settings.get("script", "")
        for denied in self.scope_deny:
            if denied and denied.rstrip("/") in str(backtest_script):
                issues.append(f"Backtest script '{backtest_script}' matches scope.deny '{denied}'")

        # budget.hard vs loop consistency
        if self.budget_hard:
            bh_max = self.budget_hard.get("max_rounds", 0)
            if bh_max and bh_max > self.max_rounds:
                # Contract looser than enforcement: normal case -> info, not WARN.
                _log.info(f"budget.hard.max_rounds ({bh_max}) > loop.max_rounds ({self.max_rounds}) - contract is looser than enforcement")
            if bh_max and bh_max < self.max_rounds:
                # Contract stricter than enforcement: keep warning semantics.
                issues.append(f"budget.hard.max_rounds ({bh_max}) < loop.max_rounds ({self.max_rounds}) - contract is stricter than enforcement")
            bh_fail = self.budget_hard.get("max_consecutive_failures", 0)
            if bh_fail and bh_fail > self.error_stop:
                issues.append(f"budget.hard.max_consecutive_failures ({bh_fail}) > loop.error_stop ({self.error_stop}) — contract is looser than enforcement")

        # stop.safety is empty
        if not self.stop_safety:
            issues.append("stop.safety is empty — no safety stop conditions configured")

        # stop.completion is empty
        if not self.stop_completion:
            issues.append("stop.completion is empty — no completion conditions configured")

        if issues:
            _log.info("[contract] Warnings:")
            for i in issues:
                _log.info(f"  ! {i}")

    def _produce_problems(self, observations: dict, act_result: dict,
                          learned: dict, diagnosis: dict, bar: StatusBar,
                          l1_attempts: list[dict] | None = None):
        """Push anomalies detected this round to the problem_queue."""
        round_num = observations.get("round", self.total_rounds)
        pushed = 0
        now = datetime.now().isoformat()
        l1_attempts = l1_attempts or []

        # 1. Backtest execution error
        if act_result.get("status") == "error" and act_result.get("error"):
            err_msg = str(act_result.get("error", ""))
            self.store.push_problem({
                "id": PatternStore.next_problem_id(),
                "type": "execution_error",
                "severity": "critical",
                "source": "self_diagnose",
                "round": round_num,
                "context": {"error": err_msg[:200]},
                "evidence": f"Backtest execution error: {err_msg[:120]}",
                "suggested_action": "Run --doctor to check backtest script and I/O contract",
                "created_at": now,
                "error_signature": f"backtest|execution|{err_msg[:40].replace(' ', '_')}",
                "task_step": "act",
                "expected_behavior": "Backtest script completes with valid trades output",
                "l1_attempts": l1_attempts,
            })
            pushed += 1

        # 2. Exclusion rate too high (>70%)
        inp = observations.get("signals_input", 0)
        excl = observations.get("signals_excluded", 0)
        if inp > 0 and excl / inp > 0.7:
            self.store.push_problem({
                "id": PatternStore.next_problem_id(),
                "type": "config_tuning",
                "severity": "major",
                "source": "self_diagnose",
                "round": round_num,
                "context": {"metric": "exclusion_rate",
                            "current": round(excl / inp, 2),
                            "threshold": 0.7,
                            "excluded": excl, "input": inp},
                "evidence": f"Exclusion rate {excl/inp:.0%} > 70% — rules may be too aggressive",
                "suggested_action": "Review exclusion rules; consider pausing new rule additions",
                "created_at": now,
                "error_signature": "exclusion|check|rate_high",
                "task_step": "observe",
                "expected_behavior": "Exclusion rate < 70% for healthy signal throughput",
            })
            pushed += 1

        # 3. Consecutive no-progress (stagnation)
        if learned["new_failures"] == 0 and learned["new_successes"] == 0:
            no_prog = self.total_rounds - self.last_progress_round
            if no_prog >= 2:
                self.store.push_problem({
                    "id": PatternStore.next_problem_id(),
                    "type": "stagnation",
                    "severity": "minor" if no_prog < self.no_progress_stop else "major",
                    "source": "self_diagnose",
                    "round": round_num,
                    "context": {"metric": "no_progress_rounds",
                                "current": no_prog,
                                "threshold": self.no_progress_stop},
                    "evidence": f"{no_prog} consecutive rounds with no new patterns",
                    "suggested_action": "Consider expanding signal pool or relaxing exclusion rules",
                    "created_at": now,
                    "error_signature": "loop|stagnation|no_progress",
                    "task_step": "verify",
                    "expected_behavior": f"New patterns found within {self.no_progress_stop} rounds",
                })
                pushed += 1

        # 4. All-excluded event
        if inp > 0 and excl == inp:
            self.store.push_problem({
                "id": PatternStore.next_problem_id(),
                "type": "config_tuning",
                "severity": "major",
                "source": "self_diagnose",
                "round": round_num,
                "context": {"metric": "all_excluded", "input": inp, "excluded": excl},
                "evidence": f"All {inp} candidates blocked by exclusion rules this round",
                "suggested_action": "Review exclusion rules for over-filtering; consider adding new signal sources",
                "created_at": now,
                "error_signature": "exclusion|check|all_blocked",
                "task_step": "observe",
                "expected_behavior": "At least some candidates should pass exclusion to reach backtest",
            })
            pushed += 1

        if pushed and bar:
            bar.add_suggestion(f"Pushed {pushed} problem(s) to queue (P0)")

    def _produce_defect_report(self, learned: dict, act_result: dict,
                                observations: dict):
        """[Improve] 从模式库分析失败根因，生成指向原始任务的缺陷报告。

        参考 DSH 的 Errors and Fixes 压缩段落，将失败的信号模式翻译为
        原始任务（脚本/工具/流程）的具体缺陷和改进建议。

        输出: <workspace 父目录>或 runtime.root/projects/<name>/ 下的 IMPROVEMENTS.md
        （无 workspace 时显式离根，不落仓库根）
        """
        failures = self.store.load_failure_patterns()
        if not failures:
            return

        # 确定项目目录（workspace 的父目录，或使用信号文件所在目录）
        workspace = self.task_cfg.get("workspace")
        if workspace:
            project_dir = Path(workspace)
            if project_dir.name == "workspace":
                project_dir = project_dir.parent
        else:
            # 显式离根：无 workspace 时落 runtime.root 下的 projects/<name>/，
            # 不可直接用 runtime.root 作 project_dir：开发态下 runtime.root 即仓库根，
            # 那会把运行产物撞到仓库根（违反 CLAUDE.md §9.1 根目录 allowlist）。
            task_name = str(self.task_cfg.get("name") or "loop")
            project_dir = Path(self.runtime.root) / "projects" / task_name
        report_path = project_dir / "IMPROVEMENTS.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        # 分析失败模式，按根因分组
        issues = []
        for f in failures[-20:]:  # 最近 20 条
            sp = f.get("signal_pattern", "")
            root_cause = f.get("root_cause", "")
            solution = f.get("solution", "TBD")
            status = f.get("status", "open")
            failure_mode = f.get("failure_mode", "")
            impact = f.get("impact", {})

            # 将失败模式映射为原始任务的缺陷
            defect = self._classify_defect(sp, root_cause, failure_mode)
            if defect:
                defect["status"] = status
                defect["evidence"] = (root_cause or "")[:200]
                defect["suggested_fix"] = solution
                issues.append(defect)

        if not issues:
            return

        # 去重
        seen = set()
        unique = []
        for d in issues:
            key = d["defect"]
            if key not in seen:
                seen.add(key)
                unique.append(d)

        # 生成报告
        lines = [
            "# 缺陷改进报告",
            "",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"模式库失败数: {len(failures)} | 本轮分析: {len(unique)} 个缺陷",
            "",
            "> Loop 自动生成。分析失败模式的根因，映射为原始任务的改进建议。",
            "> 参考 DSH Errors and Fixes 结构：缺陷 → 根因 → 改进方案 → 验证方法。",
            "",
            "---",
            "",
        ]

        for i, d in enumerate(unique, 1):
            sev = d.get("severity", "major")
            icon = {"critical": "🔴", "major": "🟠", "minor": "🟡"}.get(sev, "⚪")
            lines.extend([
                f"### {i}. {icon} {d['defect']}",
                f"",
                f"**严重度**: {sev} | **状态**: {d.get('status', 'open')}",
                f"",
                f"**缺陷位置**: `{d['location']}`",
                f"",
                f"**根因**: {d['root_cause']}",
                f"",
                f"**改进方案**: {d['suggested_fix']}",
                f"",
                f"**验证方法**: {d['verification']}",
                f"",
                f"**证据**: {d['evidence'][:200]}",
                f"",
                "---",
                "",
            ])

        report_path.write_text("\n".join(lines), encoding="utf-8")
        _log.info(f"[improve] Defect report: {report_path} ({len(unique)} issues)")

    @staticmethod
    def _classify_defect(signal_pattern, root_cause, failure_mode):
        """将失败模式分类为原始任务的缺陷类型。"""
        rc_lower = ((root_cause or "") + (failure_mode or "")).lower()

        # 编码问题
        if any(kw in rc_lower for kw in ["gbk", "encode", "decode", "unicode",
                                           "utf", "encoding", "charset"]):
            return {
                "defect": "文本编码兼容性不足",
                "location": "原始脚本/工具的文本读取函数",
                "root_cause": "假设输入文件为 UTF-8 编码，未处理 GBK/GB18030 等中文编码",
                "severity": "critical",
                "verification": "用 10 本中文 txt 书籍测试，全部通过即修复",
            }

        # 格式不支持
        if any(kw in rc_lower for kw in ["mobi", "format", "unsupported",
                                           "not supported", "unknown format"]):
            return {
                "defect": "文件格式支持不完整",
                "location": "原始工具的格式解析器",
                "root_cause": "缺少 mobi/azw 等格式的转换器依赖（如 calibre ebook-convert）",
                "severity": "major",
                "verification": "用 mobi 格式文件测试，能正常提取文本即修复",
            }

        # 依赖缺失
        if any(kw in rc_lower for kw in ["modulenotfound", "importerror",
                                           "no module", "import error"]):
            return {
                "defect": "运行时依赖缺失",
                "location": "原始脚本的 import 语句或 setup.py/requirements.txt",
                "root_cause": "缺少必要的 Python 包或系统工具",
                "severity": "critical",
                "verification": "pip install 缺失依赖后重新执行，import 成功即修复",
            }

        # 输出格式
        if any(kw in rc_lower for kw in ["output", "format", "empty",
                                           "no output", "result"]):
            return {
                "defect": "输出格式不符合预期",
                "location": "原始脚本的输出生成函数",
                "root_cause": "输出缺少结构化格式（如 skill.md、验证问题），无法被下游消费",
                "severity": "major",
                "verification": "检查输出目录是否包含 skill.md + verification.json",
            }

        # 超时
        if any(kw in rc_lower for kw in ["timeout", "timed out"]):
            return {
                "defect": "执行超时",
                "location": "原始脚本的主处理循环",
                "root_cause": "单次处理耗时超过 Loop 配置的 timeout_sec",
                "severity": "major",
                "verification": "减少单次处理量或优化算法，执行时间 < timeout_sec",
            }

        # 通用失败
        return {
            "defect": f"执行异常: {failure_mode or '未知错误'}",
            "location": "原始脚本（需进一步排查）",
            "root_cause": (root_cause or "")[:200],
            "severity": "minor",
            "verification": "查看证据中的错误信息，定位具体代码位置后修复",
        }
