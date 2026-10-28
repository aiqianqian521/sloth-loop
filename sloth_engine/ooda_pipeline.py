"""OODA 7-step pipeline handlers.

Extracted from orchestrator.py as part of P2.1 Slice B1 (god-file split).
OODASteps is re-exported by orchestrator.py for back-compat. Behavior unchanged.
Per-method deferred imports (adapters.task_runner / verifier / subprocess / ...) resolve
via sloth_engine on sys.path. PROJECT_ROOT recomputed locally (matches orchestrator._HERE.parent).
"""
from __future__ import annotations

import sys
import os
import json
import time
from datetime import date, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

PROJECT_ROOT = _HERE.parent

from status_bar import StatusBar
from runtime_paths import RuntimePaths, ContainmentError
from memory_store import PatternStore
from tool_registry import ToolRegistry
from round_context import RoundContext
from ooda_steps_learn import OODAStepsLearn  # H1-P2a: _learn mixin


# ============================================================================
# OODA 7-Step Methods (extracted; re-exported as OODASteps by orchestrator.py)
# ============================================================================

class OODASteps(OODAStepsLearn):
    """Implementation logic for the 7 OODA steps. Extracted from Orchestrator
    to keep the class focused on orchestration concerns."""

    @staticmethod
    def _ensure_understand(store, task_cfg: dict, work_dir: Path,
                            require_input: bool = False) -> dict:
        """[U] Understand — ensure task understanding is explicitly written.

        Checks for 00-purpose.md in work_ooda/; creates template if missing.
        Returns {"complete", "path", "fields_ok", ...}
        """
        purpose_file = work_dir / "00-purpose.md"
        # config-provided UQ inputs count as satisfied ("已传直达").
        cfg_goal = bool((task_cfg or {}).get("name"))
        cfg_success = bool((task_cfg or {}).get("success_criteria"))
        cfg_boundary = bool((task_cfg or {}).get("scope"))
        if purpose_file.exists():
            content = purpose_file.read_text(encoding="utf-8")
            # config-provided fields take precedence（已传直达）: even if the
            # template placeholder is present, a config-supplied goal/boundary/
            # success_criteria counts as filled.
            has_goal = cfg_goal or ("[Describe the task goal" not in content
                                    and "goal" in content.lower())
            has_boundary = cfg_boundary or ("[What this task covers" not in content
                                            and ("boundary" in content.lower()
                                                 or "scope" in content.lower()))
            has_success = cfg_success or ("[Describe" not in content
                                          and "success" in content.lower())
            fields_ok = has_goal and has_boundary and has_success
            return {"complete": fields_ok, "path": str(purpose_file),
                    "fields_ok": fields_ok,
                    "has_goal": has_goal, "has_boundary": has_boundary,
                    "has_success": has_success,
                    "needs_input": require_input and not fields_ok}
        # Create template
        work_dir.mkdir(parents=True, exist_ok=True)
        task_name = (task_cfg or {}).get("name", "unknown")
        sc_criteria = (task_cfg or {}).get("success_criteria") or []
        sc_lines = "\n".join(
            f'- {c.get("metric", "?")} {c.get("operator", "?")} {c.get("threshold", "?")}'
            for c in sc_criteria)
        constraints = (task_cfg or {}).get("constraints", {})
        template = f"""# 00-purpose — {task_name}

## Goal
[Describe the task goal in one sentence]

## Success Criteria
{sc_lines}

## Boundary
- In scope: [What this task covers]
- Out of scope: [What this task does NOT cover]

## 5W1H Scan (v2.0)
- Who:   [Who is affected? Who decides? Who depends on this?]
- What:  [What exactly to produce? Scope boundaries?]
- Where: [Which system/module/layer does this touch?]
- When:  [Time constraints? Dependency ordering?]
- Why:   [Why solve this now? What is the root problem?]
- How:   [What viable paths exist? Tools/methods?]

## Constraints
- max_rounds: {constraints.get("max_rounds", "N/A")}
- no_progress_stop: {constraints.get("no_progress_stop", "N/A")}
"""
        purpose_file.write_text(template, encoding="utf-8")
        # fresh template: config-provided fields still satisfy UQ ("已传直达").
        fields_ok = (cfg_goal or False) and (cfg_success or False) and (cfg_boundary or False)
        return {"complete": fields_ok, "path": str(purpose_file),
                "fields_ok": fields_ok, "template_created": True,
                "has_goal": cfg_goal, "has_boundary": cfg_boundary, "has_success": cfg_success,
                "needs_input": require_input and not fields_ok}

    @staticmethod
    def _observe(store, round_num: int, signals: list[dict],
                 work_dir: Path, prev_state: dict | None,
                 warn_namespace: bool = True) -> dict:
        """[O] Observe — load previous round state, experience library, candidate data.

        v2.0 P0-2: Delta 对比 — 本轮 vs 上轮关键指标变化。
        """
        failures = store.load_failure_patterns()
        successes = store.load_success_patterns()
        active_rules = store.get_active_exclusion_rules()
        chk = store.check_exclusion(signals, warn_namespace=warn_namespace)

        # P0-2: Delta 对比 —— 从 rounds 表读取上轮数据
        prev_rounds = store.get_rounds()
        delta = {}
        if prev_rounds and round_num > 1:
            prev = prev_rounds[-1]
            excl_rate_prev = (prev.get("excluded_count", 0) / max(prev.get("input_count", 1), 1))
            excl_rate_curr = chk["excluded_count"] / max(chk["input_count"], 1)
            delta = {
                "exclusion_rate": {
                    "prev": round(excl_rate_prev, 3),
                    "curr": round(excl_rate_curr, 3),
                    "change": round(excl_rate_curr - excl_rate_prev, 3),
                },
                "new_patterns_prev": prev.get("new_failures", 0) + prev.get("new_successes", 0),
                "active_rules_prev": prev.get("excluded_count", 0),  # approximation
                "active_rules_curr": len(active_rules),
            }

        return {
            "round": round_num,
            "signals_input": len(signals),
            "signals_passed": chk["passed_count"],
            "signals_excluded": chk["excluded_count"],
            "exclusion_rules_active": len(active_rules),
            "failure_patterns_loaded": len(failures),
            "success_patterns_loaded": len(successes),
            "prev_state": prev_state,
            "check_result": chk,
            "delta": delta,  # v2.0 P0-2
        }

    @staticmethod
    def _orient(observations: dict, bar: StatusBar | None = None,
                prev_ctx: RoundContext | None = None) -> dict:
        """[O] Orient — diagnose current state, identify issues and severity.

        Structural analysis + 上轮错误回流分析（v2.2 P0）。
        Agent-level reasoning is supplemented by the external OODA skill in Claude Code.
        """
        issues = []
        severity = "normal"

        # ── 当前信号分析 ─────────────────────────────
        if observations["signals_passed"] == 0 and observations["signals_input"] > 0:
            issues.append({"severity": "major", "rule": "ALL_EXCLUDED",
                           "msg": f"All {observations['signals_input']} candidates blocked by exclusion rules"})
            severity = "major"

        if observations["signals_input"] == 0:
            issues.append({"severity": "critical", "rule": "NO_SIGNALS",
                           "msg": "No candidate signals. Check --signals path or signal generation logic"})
            severity = "critical"

        if observations["signals_input"] > 0:
            excl_rate = observations["signals_excluded"] / observations["signals_input"]
            if excl_rate > 0.7:
                issues.append({"severity": "major", "rule": "HIGH_EXCLUSION",
                               "msg": f"Exclusion rate {excl_rate:.0%} > 70% — rules may be too aggressive"})

        # ── 上轮遗留问题 ─────────────────────────────
        prev = observations.get("prev_state") or {}
        remained = prev.get("remaining_issues", [])
        for ri in remained[:3]:
            issues.append({"severity": ri.get("severity", "minor"),
                           "rule": "PREV_REMAIN",
                           "msg": f"Previous round leftover: {ri.get('issue', str(ri))[:80]}"})

        # ── v2.2 P0: 上轮 Act 错误回流分析 ───────────
        if prev_ctx is not None:
            # Act 执行错误
            if prev_ctx.had_act_error:
                issues.append({"severity": "major", "rule": "PREV_ACT_ERROR",
                               "msg": f"上轮 Act 失败: {prev_ctx.prev_act_error[:150]}"})
                if severity != "critical":
                    severity = "major"

            # Act 被跳过
            if prev_ctx.had_act_skip and prev_ctx.prev_act_status != "":
                issues.append({"severity": "minor", "rule": "PREV_ACT_SKIPPED",
                               "msg": f"上轮 Act 跳过: status={prev_ctx.prev_act_status}"})

            # L1 重试失败分析
            if prev_ctx.l1_all_failed:
                strategies = [a.get("strategy", "?") for a in prev_ctx.l1_history]
                issues.append({"severity": "major", "rule": "L1_ALL_RETRIES_FAILED",
                               "msg": f"L1 三级重试全部失败: {strategies}"})
            elif prev_ctx.l1_retry_count > 0:
                failed_attempts = [a for a in prev_ctx.l1_history if not a.get("ok")]
                if failed_attempts:
                    issues.append({"severity": "minor", "rule": "L1_PARTIAL_RETRY",
                                   "msg": f"L1 部分重试失败: {len(failed_attempts)}/{prev_ctx.l1_retry_count} 次"})

            # Verify 验证失败
            if prev_ctx.has_verify_failures:
                fail_details = []
                for f in prev_ctx.prev_verify_failures[:3]:
                    fail_details.append(f"{f.get('metric')}={f.get('actual')} "
                                        f"(需要 {f.get('operator')} {f.get('threshold')})")
                issues.append({"severity": "major", "rule": "PREV_VERIFY_FAILED",
                               "msg": f"上轮验证未通过: {'; '.join(fail_details)}"})

            # 连续错误累积
            if prev_ctx.consecutive_errors >= 2:
                issues.append({"severity": "critical", "rule": "CONSECUTIVE_ERRORS",
                               "msg": f"连续 {prev_ctx.consecutive_errors} 轮执行错误"})

        if bar:
            for iss in issues:
                bar.add_issue(iss["severity"], iss["rule"], iss["msg"])

        return {"severity": severity, "issue_count": len(issues),
                "issues": issues, "observations": observations}

    @staticmethod
    def _decide(diagnosis: dict, round_num: int, task_cfg: dict,
                zones: dict | None = None) -> dict:
        """[D] Decide — choose this round's action based on diagnosis.

        Framework-level decisions: skip round, use defaults, request human intervention.
        Business-level decisions are supplemented by Agent via OODA skill.

        Phase 1 zones: green=auto-approve, yellow=warn, red=block.
        """
        issues = diagnosis.get("issues", [])

        criticals = [i for i in issues if i["severity"] == "critical"]
        if criticals:
            return {"action": "skip", "reason": criticals[0]["msg"],
                    "approach": "skip_on_critical"}

        if any(i["rule"] == "ALL_EXCLUDED" for i in issues):
            return {"action": "skip_backtest", "reason": "All candidates excluded",
                    "approach": "record_only"}

        # Phase 1: zone classification
        zone_tag = "green"
        if zones:
            red_hits = [i for i in issues if i.get("rule", "") in zones.get("red", set())]
            yellow_hits = [i for i in issues if i.get("rule", "") in zones.get("yellow", set())]
            if red_hits:
                zone_tag = "red"
            elif yellow_hits:
                zone_tag = "yellow"

        return {"action": "execute", "reason": "Execute task",
                "approach": "standard_backtest", "round": round_num,
                "zone": zone_tag}

    @staticmethod
    def _act_with_retry(decision: dict, passed_signals: list[dict],
                        bt_settings: dict, store, task_cfg: dict | None = None,
                        max_retries: int = 2,
                        registry: ToolRegistry | None = None,
                        exec_gate=None) -> tuple[dict, list[dict]]:
        """[A] Act with L1 retry — 3-strategy escalation.

        Strategy 1: standard execution (timeout=300s)
        Strategy 2: longer timeout (timeout=600s)
        Strategy 3: graceful skip

        Returns (act_result, l1_attempts) where l1_attempts records each attempt.
        """
        l1_attempts = []
        task_cfg = dict(task_cfg or {})

        for attempt in range(max_retries + 1):
            if attempt == 0:
                strategy = "standard"
            elif attempt == 1:
                strategy = "longer_timeout"
                task_cfg["_retry_timeout"] = 600
            else:
                strategy = "graceful_skip"

            if strategy == "graceful_skip":
                # 保留最后一次失败的原始错误信息
                last_error = l1_attempts[-1].get("error", "") if l1_attempts else ""
                last_task = l1_attempts[-1].get("task_result") if l1_attempts else None
                l1_attempts.append({"strategy": strategy, "ok": True,
                                    "note": f"skipped after retries exhausted: {last_error[:100]}"})
                return ({"status": "skipped", "execution_failed": True,
                         "trades": [],
                         "error": last_error or "retries_exhausted",
                         "signals_tested": 0,
                         "task_result": last_task}, l1_attempts)

            result = OODASteps._act(decision, passed_signals, bt_settings,
                                    store, task_cfg, registry=registry,
                                    exec_gate=exec_gate)
            ok = result.get("status") != "error"
            err_detail = result.get("error", "")
            l1_attempts.append({"strategy": strategy, "ok": ok,
                                "error": err_detail[:200] if not ok else "",
                                "task_result": result.get("task_result") if not ok else None})
            if ok:
                return (result, l1_attempts)
            # Failure recorded, escalate to next strategy

        # Should not reach here (graceful_skip handles last attempt)
        return ({"status": "skipped", "execution_failed": True,
                 "trades": [], "error": "retries_exhausted",
                 "signals_tested": 0, "task_result": None}, l1_attempts)

    @staticmethod
    def _act(decision: dict, passed_signals: list[dict],
             bt_settings: dict, store, task_cfg: dict | None = None,
             registry: ToolRegistry | None = None,
             exec_gate=None) -> dict:
        """[A] Act — 通过 ToolRegistry 统一调度执行 (v2.1 移植-P2)。

        execution.type:
          "script"       → subprocess 执行 shell 命令
          "agent_prompt" → importlib 动态加载 Python 模块
          "mcp" / "cli"  → 通过 ToolRegistry 扩展
          未定义          → 回退 BacktestRunner (兼容旧回测任务)
        """
        if decision["action"] == "skip":
            return {"status": "skipped", "trades": [], "error": decision.get("reason"),
                    "signals_tested": 0}
        if decision["action"] == "skip_backtest":
            return {"status": "skipped", "trades": [], "error": "all_excluded",
                    "signals_tested": 0}

        execution = (task_cfg or {}).get("execution", {})
        exec_type = execution.get("type", "")
        exec_entry = execution.get("entry", "")
        from adapters.task_runner import TaskInput, TaskResult, normalize_task_result

        # v2.1 移植-P2: ToolRegistry 优先 — 注册过的工具走统一调度
        if registry is not None and registry.get(exec_type):
            task_input = TaskInput(
                task_type=(task_cfg or {}).get("name", exec_type),
                signals=passed_signals,
                params={"entry": exec_entry},
            )
            result = registry.dispatch(exec_type, task_input, bt_settings, store)
            contract = normalize_task_result(
                result, adapter=exec_type, entry=exec_entry or exec_type,
                task_input=task_input,
            )
            return {"status": result.get("status", "completed"),
                    "trades": result.get("trades", []),
                    "error": result.get("error", ""),
                    "sharpe": result.get("metrics", {}).get("sharpe", 0),
                    "win_rate": result.get("metrics", {}).get("win_rate", ""),
                    "signals_tested": len(passed_signals),
                    "metrics": contract.metrics,
                    "raw": contract.raw_output,
                    "task_result": contract}

        # 模式 1: subprocess 执行外部命令
        if exec_type == "script" and exec_entry:
            import shlex
            try:
                _argv = shlex.split(exec_entry)
            except ValueError as _shlex_err:
                return {"status": "error", "trades": [], "signals_tested": len(passed_signals),
                        "error": f"invalid command (de-shell parse): {_shlex_err}",
                        "task_result": TaskResult(status="error",
                            execution={"status": "failed", "stage": "execution", "code": "invalid_command"},
                            output={"status": "not_run", "present": False, "parseable": False, "schema_valid": False},
                            business={"status": "not_evaluated"},
                            provenance={"adapter": "script", "entry": exec_entry},
                            errors=[{"signature": "invalid_command", "params_snapshot": {"cmd": exec_entry},
                                     "fix_recipe": "Fix the command string (de-shell requires valid shlex syntax)",
                                     "evidence": str(_shlex_err)}])}
            # F1 fix: route through ExecGate (single sanctioned spawn chokepoint).
            # exec_gate is None -> fail-closed (bare subprocess.run is forbidden).
            if exec_gate is None:
                return {"status": "error", "trades": [], "signals_tested": len(passed_signals),
                        "error": "exec_gate missing: script execution blocked (fail-closed, F1)",
                        "task_result": TaskResult(status="error",
                            execution={"status": "failed", "stage": "execution", "code": "exec_gate_missing"},
                            output={"status": "not_run", "present": False, "parseable": False, "schema_valid": False},
                            business={"status": "not_evaluated"},
                            provenance={"adapter": "script", "entry": exec_entry},
                            errors=[{"signature": "exec_gate_missing", "params_snapshot": {"cmd": exec_entry},
                                     "fix_recipe": "Provide an ExecGate in the OODA act call (orchestrator wires one)",
                                     "evidence": "script branch requires ExecGate; bare subprocess.run is forbidden (F1)"}])}
            try:
                _proc = exec_gate.run(_argv, cwd=str(Path(__file__).resolve().parent.parent), timeout=300)
            except Exception as _gate_err:
                return {"status": "error", "trades": [], "signals_tested": len(passed_signals),
                        "error": f"exec_gate error: {_gate_err}",
                        "task_result": TaskResult(status="error",
                            execution={"status": "failed", "stage": "execution", "code": "exec_gate_exception"},
                            output={"status": "not_run", "present": False, "parseable": False, "schema_valid": False},
                            business={"status": "not_evaluated"},
                            provenance={"adapter": "script", "entry": exec_entry},
                            errors=[{"signature": "exec_gate_exception", "params_snapshot": {"cmd": exec_entry},
                                     "fix_recipe": "Check ExecGate wiring and interpreter allow-list",
                                     "evidence": str(_gate_err)}])}
            _rc = _proc.returncode
            if getattr(_proc, "timed_out", False):
                return {"status": "error", "trades": [], "error": f"Command timeout: {exec_entry[:100]}",
                        "task_result": TaskResult(status="error",
                            execution={"status": "timeout", "stage": "execution", "code": "timeout", "timed_out": True},
                            output={"status": "not_run", "present": False, "parseable": False, "schema_valid": False},
                            business={"status": "not_evaluated"},
                            provenance={"adapter": "script", "entry": exec_entry}, errors=[{
                            "signature": "timeout", "params_snapshot": {"cmd": exec_entry},
                            "fix_recipe": "Increase timeout or optimize the command",
                            "evidence": f"Command timed out after 300s: {exec_entry[:100]}",
                        }])}
            errors = []
            if _rc != 0:
                errors.append({
                    "signature": f"exit_code:{_rc}",
                    "params_snapshot": {"cmd": exec_entry},
                    "fix_recipe": "Check command output and fix errors",
                    "evidence": ((_proc.stderr or "") or (_proc.stdout or ""))[:500],
                })
            return {"status": "completed" if _rc == 0 else "error",
                    "trades": [], "signals_tested": len(passed_signals),
                    "error": ((_proc.stderr or "")[:200]) if _rc != 0 else "",
                    "sharpe": 0, "win_rate": "",
                    "raw": _proc,
                    "task_result": TaskResult(
                        status="completed" if _rc == 0 else "error",
                        execution={"status": "succeeded" if _rc == 0 else "failed",
                                   "stage": "execution", "code": "ok" if _rc == 0 else "process_nonzero_exit",
                                   "exit_code": _rc, "timed_out": False},
                        output={"status": "not_verified", "present": False, "parseable": False, "schema_valid": False},
                        business={"status": "not_evaluated"},
                        provenance={"adapter": "script", "entry": exec_entry},
                        errors=errors,
                        metrics={"exit_code": _rc},
                        raw_output=_proc,
                    )}


        # 模式 2: importlib 动态加载 Python 模块
        if exec_type == "agent_prompt" and exec_entry:
            import importlib
            try:
                mod_path, _, cls_name = exec_entry.rpartition(".")
                mod = importlib.import_module(mod_path)
                runner_cls = getattr(mod, cls_name)
            except (ImportError, AttributeError) as e:
                return {"status": "error", "trades": [], "error": str(e),
                        "task_result": TaskResult(status="error",
                            execution={"status": "failed", "stage": "load", "code": "import_error"},
                            output={"status": "not_run", "present": False, "parseable": False, "schema_valid": False},
                            business={"status": "not_evaluated"},
                            provenance={"adapter": "agent_prompt", "entry": exec_entry}, errors=[{
                            "signature": "import_error",
                            "params_snapshot": {"module": exec_entry},
                            "fix_recipe": "Check module path and class name",
                            "evidence": str(e),
                        }])}
            except Exception as e:
                return {"status": "error", "trades": [], "error": str(e),
                        "task_result": TaskResult(status="error",
                            execution={"status": "failed", "stage": "load",
                                       "code": "import_execution_exception"},
                            output={"status": "not_run"}, business={"status": "not_evaluated"},
                            provenance={"adapter": "agent_prompt", "entry": exec_entry}, errors=[{
                            "signature": "import_execution_exception",
                            "params_snapshot": {"module": exec_entry},
                            "fix_recipe": "Fix module top-level initialization",
                            "evidence": str(e),
                        }])}
            try:
                runner = runner_cls(bt_settings)
            except Exception as e:
                return {"status": "error", "trades": [], "error": str(e),
                        "task_result": TaskResult(status="error",
                            execution={"status": "failed", "stage": "load", "code": "runner_init_exception"},
                            output={"status": "not_run", "present": False, "parseable": False, "schema_valid": False},
                            business={"status": "not_evaluated"},
                            provenance={"adapter": "agent_prompt", "entry": exec_entry}, errors=[{
                            "signature": "runner_init_exception",
                            "params_snapshot": {"module": exec_entry},
                            "fix_recipe": "Check runner constructor and injected settings",
                            "evidence": str(e),
                        }])}
        else:
            # 模式 0: 回退 BacktestRunner (无 execution 定义的旧任务)
            from adapters.task_runner import BacktestRunner
            runner = BacktestRunner(bt_settings, exec_gate=exec_gate)

        success_starts = [s for s in store.load_success_patterns()
                          if s.get("status") == "confirmed"][:3]
        # v2.1 移植-P0: 通过 TaskRunner ABC 做输入验证
        try:
            validated_signals = runner.validate_input(passed_signals)
        except Exception as e:
            return {"status": "error", "trades": [], "error": str(e),
                    "task_result": TaskResult(status="error",
                        execution={"status": "failed", "stage": "input_validation",
                                   "code": "input_validation_exception"},
                        output={"status": "not_run"}, business={"status": "not_evaluated"},
                        provenance={"adapter": "agent_prompt" if exec_type == "agent_prompt" else "backtest",
                                    "entry": exec_entry or "BacktestRunner"}, errors=[{
                        "signature": "input_validation_exception", "params_snapshot": {},
                        "fix_recipe": "Fix runner.validate_input",
                        "evidence": str(e),
                    }])}
        runner_input = TaskInput(
            task_type=(task_cfg or {}).get("name", "backtest"),
            signals=validated_signals,
            params={"success_starts": success_starts},
        )
        try:
            raw_task_result = runner.run(runner_input)
        except Exception as e:
            return {"status": "error", "trades": [], "error": str(e),
                    "task_result": TaskResult(status="error",
                        execution={"status": "failed", "stage": "runner",
                                   "code": "runner_exception"},
                        output={"status": "not_available"}, business={"status": "not_evaluated"},
                        provenance={"adapter": "agent_prompt" if exec_type == "agent_prompt" else "backtest",
                                    "entry": exec_entry or "BacktestRunner"}, errors=[{
                        "signature": "runner_exception", "params_snapshot": {},
                        "fix_recipe": "Fix runner.run and return a contract result",
                        "evidence": str(e),
                    }])}
        task_result = normalize_task_result(
            raw_task_result,
            adapter="agent_prompt" if exec_type == "agent_prompt" else "backtest",
            entry=exec_entry or "BacktestRunner",
            task_input=runner_input,
        )
        # v2.1 移植-P0: 输出验证 — 无效结果标记 skipped
        output_valid = True
        if task_result.status == "completed":
            try:
                output_valid = runner.validate_output(task_result)
            except Exception as e:
                task_result.status = "error"
                task_result.execution.update({"status": "failed", "stage": "output_validation",
                                              "code": "output_validation_exception"})
                task_result.business["status"] = "not_evaluated"
                task_result.errors.append({
                    "signature": "output_validation_exception",
                    "params_snapshot": {"signal_count": len(validated_signals)},
                    "fix_recipe": "Fix runner.validate_output",
                    "evidence": str(e),
                })
                output_valid = True
        if task_result.status == "completed" and not output_valid:
            task_result.status = "skipped"
            task_result.errors.append({
                "signature": "invalid_output",
                "params_snapshot": {"signal_count": len(validated_signals)},
                "fix_recipe": "检查回测输出是否满足任务要求",
                "evidence": f"validate_output 返回 False: trades_count={task_result.metrics.get('trades_count', 0)}",
            })
        raw_output = task_result.raw_output
        result_trades = (raw_output.trades if hasattr(raw_output, "trades")
                         else list(raw_output.get("trades") or []) if isinstance(raw_output, dict)
                         else [])
        return {"status": task_result.status,
                "trades": result_trades,
                "error": task_result.errors[0]["evidence"] if task_result.errors else "",
                "sharpe": task_result.metrics.get("sharpe", 0),
                "win_rate": task_result.metrics.get("win_rate", ""),
                "metrics": task_result.metrics,
                "signals_tested": len(passed_signals),
                "raw": task_result.raw_output,
                "task_result": task_result}

    @staticmethod
    def _verify(act_result: dict, success_criteria: list[dict],
                bar: StatusBar | None = None) -> dict:
        from verifier import Verifier
        result = Verifier.verify(act_result, success_criteria)
        if bar:
            for item in result["details"]:
                if item["passed"] is False:
                    bar.add_issue("warn", f"CRITERIA-{item['metric']}",
                                  f"{item['metric']}: actual={item['actual']} vs threshold "
                                  f"{item['operator']} {item['threshold']} -> FAIL")
        return result

    @staticmethod
    def _verify_assertions(act_result: dict, assertions: list[dict],
                           bar: StatusBar | None = None,
                           mode: str = "single",
                           runtime: RuntimePaths | None = None) -> dict:
        """[V2] 验证断言 — 检查输出结果是否满足语义约束。

        断言类型:
          equals/min_size/range/regex/exists/callback
        mode: "single" (串行) | "swarm" (并行)
        """
        results = []
        trades = act_result.get("trades", [])
        raw_output = act_result.get("raw_output") or act_result.get("raw")

        def run_one(a):
            atype = a.get("type", "equals")
            field = a.get("field", "")
            passed, detail = None, ""
            try:
                value = OODASteps._resolve_field(act_result, trades, raw_output, field)
                if atype == "equals":
                    expected, tol = a.get("expected"), a.get("tolerance", 0)
                    passed, detail = (abs(value - expected) <= tol, f"expected={expected}, actual={value}") if isinstance(value, (int,float)) and isinstance(expected, (int,float)) else ((value == expected), f"expected={expected}, actual={value}")
                elif atype == "range":
                    vmin, vmax = a.get("min", float("-inf")), a.get("max", float("inf"))
                    passed, detail = vmin <= value <= vmax, f"min={vmin}, max={vmax}, actual={value}"
                elif atype == "regex":
                    import re
                    p = a.get("pattern", "")
                    passed, detail = bool(re.search(p, str(value))), f"pattern={p}, actual={str(value)[:80]}"
                elif atype == "exists":
                    passed, detail = (value is not None and value != "" and value != 0), f"field={field}, exists={passed}"
                elif atype == "min_size":
                    threshold = a.get("threshold", 100)
                    fp = str(value) if value else ""
                    if fp and Path(fp).exists():
                        sz = Path(fp).stat().st_size
                        passed, detail = sz >= threshold, f"threshold={threshold}B, actual={sz}B"
                    else:
                        passed, detail = False, f"file not found: {fp}"
                elif atype == "callback":
                    script = a.get("script", "")
                    passed, detail = OODASteps._run_callback(script, act_result, runtime)
                else:
                    passed, detail = None, f"unknown assertion type: {atype}"
            except (KeyError, IndexError, AttributeError, TypeError) as e:
                passed, detail = False, f"resolve error: {e}"
            except Exception as e:
                passed, detail = False, f"assertion error: {e}"
            return {"type": atype, "field": field, "passed": passed, "detail": detail}

        if mode == "swarm" and len(assertions) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(len(assertions), 8)) as ex:
                futures = {ex.submit(run_one, a): i for i, a in enumerate(assertions)}
                results = [None] * len(assertions)
                for f in as_completed(futures):
                    results[futures[f]] = f.result()
        else:
            results = [run_one(a) for a in assertions]

        for r in results:
            if bar and r["passed"] is False:
                bar.add_issue("warn", f"ASSERT-{r['type']}",
                              f"{r['field']}: {r['detail']} -> FAIL")

        pass_count = sum(1 for r in results if r["passed"] is True)
        fail_count = sum(1 for r in results if r["passed"] is False)
        return {"pass_count": pass_count, "fail_count": fail_count,
                "total": len(results), "details": results,
                "mode": mode}

    @staticmethod
    def _run_callback(script_ref, act_result, runtime: RuntimePaths | None = None,
                      *, exec_gate=None):
        """P2: 回调断言 — 调用外部脚本验证结果。"""
        script_path = Path(script_ref)
        if runtime is not None:
            # W2-BOUNDARY-01 / H2 Slice 1-PATH: fail-closed containment.
            try:
                script_path = runtime.assert_under(
                    script_path, PROJECT_ROOT, kind="callback-script")
                runtime.assert_interpreter(
                    sys.executable, kind="callback-interpreter")
            except ContainmentError as e:
                return False, f"callback denied: {e}"
        # cycle-36 A: the spawn goes through an ExecGate (fail-closed).  Prefer the
        # caller's gate; else bind one to the same RuntimePaths the containment
        # check above already used.  With neither there is no gate and no spawn.
        gate = exec_gate
        if gate is None and runtime is not None:
            from runtime_exec import ExecGate
            gate = ExecGate(runtime)
        if gate is None:
            return False, "callback denied: no exec gate (fail-closed)"
        if not script_path.exists():
            return False, f"callback script not found: {script_ref}"
        cwd_path = str(runtime.root) if runtime is not None else None
        try:
            res = gate.run(
                [sys.executable, str(script_path)],
                input=json.dumps(act_result.get("trades", [])),
                cwd=cwd_path, timeout=30, assert_interpreter=True,
            )
            if res.timed_out:
                return False, "callback timeout (30s)"
            if res.returncode == 0:
                return True, res.stdout.strip()[:200] or "callback passed"
            return False, (res.stderr or res.stdout or f"exit={res.returncode}")[:200]
        except ContainmentError as e:
            return False, f"callback denied: {e}"
        except Exception as e:
            return False, f"callback error: {e}"

    @staticmethod
    def _verify_regression(regression_cfg: dict, bar: StatusBar | None = None,
                           runtime: RuntimePaths | None = None, *, exec_gate=None) -> dict:
        """P2: 回归测试 — 运行 pytest 用例验证结果。"""
        tests = regression_cfg.get("tests", [])
        if not tests:
            return {"pass_count": 0, "fail_count": 0, "total": 0, "details": []}
        pytest_args = regression_cfg.get("pytest_args", "-q --tb=short")
        # W2-BOUNDARY-01 / H2 Slice 1-PATH: fail-closed containment.
        # Regression tests live in the repo; cwd stays at the repo root
        # so repo-relative nodeids resolve regardless of the runtime sandbox.
        cwd_path = str(Path(__file__).resolve().parent.parent)
        # cycle-36 A: spawn through an ExecGate (fail-closed); no gate -> no spawn.
        gate = exec_gate
        if gate is None and runtime is not None:
            from runtime_exec import ExecGate
            gate = ExecGate(runtime)
        results = []
        for test in tests:
            test_path_str = str(test).split("::", 1)[0]
            if runtime is not None:
                try:
                    runtime.assert_under(test_path_str, PROJECT_ROOT, kind="regression-test")
                    runtime.assert_interpreter(
                        sys.executable, kind="regression-interpreter")
                except ContainmentError as e:
                    results.append({"type": "regression", "field": test,
                                    "passed": False,
                                    "detail": f"regression denied: {e}"})
                    if bar:
                        bar.add_issue("warn", f"REGRESS-{test}",
                                      f"denied -> FAIL")
                    continue
            if gate is None:
                results.append({"type": "regression", "field": test, "passed": False,
                                "detail": "regression denied: no exec gate (fail-closed)"})
                if bar:
                    bar.add_issue("warn", f"REGRESS-{test}", "denied -> FAIL")
                continue
            try:
                res = gate.run(
                    [sys.executable, "-m", "pytest"] + pytest_args.split() + [test],
                    cwd=cwd_path, timeout=60, assert_interpreter=True,
                )
                if res.timed_out:
                    passed, detail = False, "regression timeout (60s)"
                else:
                    passed = res.returncode == 0
                    detail = (res.stdout or res.stderr or "")[:200]
            except ContainmentError as e:
                passed, detail = False, f"regression denied: {e}"
            except Exception as e:
                passed, detail = False, f"regression error: {e}"
            results.append({"type": "regression", "field": test, "passed": passed, "detail": detail})
            if bar and not passed:
                bar.add_issue("warn", f"REGRESS-{test}", f"{detail[:100]} -> FAIL")
        return {"pass_count": sum(1 for r in results if r["passed"]),
                "fail_count": sum(1 for r in results if not r["passed"]),
                "total": len(results), "details": results}

    @staticmethod
    def _resolve_field(act_result, trades, raw_output, field):
        """解析 field 路径，从 act_result/trades/raw_output 中取值。

        路径格式:
          trades.0.pnl     → trades[0]["pnl"]
          trades.0.meta.pages → trades[0]["meta"]["pages"]
          _meta.passed     → act_result["_meta"]["passed"]
        """
        value = act_result
        parts = field.split(".")
        for p in parts:
            if p.startswith("_"):
                # _meta, _raw 等顶层特殊字段
                if p == "_meta" and "_meta" in act_result:
                    value = act_result["_meta"]
                elif p == "_raw" and raw_output:
                    value = raw_output
                else:
                    raise KeyError(f"unknown special field: {p}")
            elif isinstance(value, dict):
                value = value[p]
            elif isinstance(value, list):
                value = value[int(p)]
            elif hasattr(value, p):
                value = getattr(value, p)
            else:
                raise KeyError(f"cannot resolve {p} on {type(value)}")
        return value
# P0-1: _classify_failure / _classify_success 已移入 PatternStore static methods
# (memory_store.py:PatternStore.classify_failure / classify_success)
# 调用处已改为 PatternStore.classify_failure(t)


