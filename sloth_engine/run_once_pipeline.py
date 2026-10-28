"""Run-once OODA pipeline mixin for the Orchestrator (P2.2 slice E1).

Extracted verbatim from orchestrator.py: the single-round U-O-O-D-A-V-L 7-step
pipeline run_once, with W1-RESUME-01 step-level checkpoint/resume. Kept as a
mixin so self.* stays instance attrs and the MRO-resolved helpers
(_checkpoint_payload) and producers (_produce_problems/_produce_defect_report)
still bind. Bare-name lookups (time/date, StatusBar, EventLog, OODASteps,
RoundContext, step_start_event/step_end_event, EVT_*, build_context_snapshot,
_log, _STEP_INDEX) resolve against this module globals; _STEP_ORDER/_STEP_INDEX
are verbatim copies equal by value (equality smoke guarded).
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date
from pathlib import Path

from status_bar import StatusBar
from event_log import (
    EventLog,
    step_start_event,
    step_end_event,
    EVT_ROUND_START,
    EVT_ACT_RESULT,
    EVT_ACT_RETRY,
    EVT_VERIFY_RESULT,
    EVT_LEARN_RECORD,
    EVT_ROUND_END,
    build_context_snapshot,
)
from hook_events import HookEvent
from ooda_pipeline import OODASteps
from round_context import RoundContext
from resume_guard import extract_provenance_digest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_log = logging.getLogger("sloth_engine")

_STEP_ORDER = ("understand", "observe", "orient", "decide", "act", "verify", "learn")
_STEP_INDEX = {name: idx for idx, name in enumerate(_STEP_ORDER)}


def _compact_provenance_ref(task_result) -> dict:
    """Return a grep-friendly provenance reference without full host paths."""
    provenance = getattr(task_result, "provenance", None)
    if not isinstance(provenance, dict):
        return {}
    source = provenance.get("source")
    if not isinstance(source, dict):
        source = provenance
    runtime = source.get("runtime") if isinstance(source.get("runtime"), dict) else {}
    data = source.get("data") if isinstance(source.get("data"), dict) else {}
    ref = {
        "schema": source.get("schema", "loop.provenance.v1"),
        "resolver": source.get("resolver", ""),
        "provenance_digest": source.get("provenance_digest", ""),
        "runtime_sha256": runtime.get("manifest_sha256") or runtime.get("sha256", ""),
        "data_sha256": data.get("sha256", ""),
    }
    if data.get("path"):
        ref["data_name"] = Path(str(data["path"])).name
    return {key: value for key, value in ref.items() if value not in (None, "")}

class RunOnceMixin:

    def run_once(self, signals: list[dict], round_num: int = 0,
                 fast: bool = False, prev_ctx: RoundContext | None = None) -> dict:
        """U-O-O-D-A-V-L 7-step cycle (OODA embedded in Loop).

        v2.2 P0: prev_ctx 参数接收上轮 RoundContext，用于 Act→Orient 错误回流。
        返回值新增 round_ctx 字段。
        """
        task_name = self.task_cfg.get("name", "sandbox")
        _hook = getattr(self, "hook_bus", None)
        bar = StatusBar(round_num or self.total_rounds + 1, task_name, self.max_rounds,
                     annotation_enabled=self.enable_annotation)

        # v2.1 移植-P1: 事件溯源会话 — 每步追加不可变事件
        run_dir = self.work_dir / f"runs-{date.today().isoformat()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        elog = EventLog(run_dir / f"events-{int(time.time())}.jsonl",
                        task_name=task_name)
        elog.append(EVT_ROUND_START, {"round": round_num or self.total_rounds + 1,
                                       "task": task_name, "signals_input": len(signals)})
        if _hook is not None:
            _hook.fire_round_start(task_name=task_name, round_num=round_num or self.total_rounds + 1)

        # [Schema] opt-in strict input-signal gate (fail-closed when invalid).
        _sig = self._validate_signal_batch(signals)
        if _sig.get("enabled") and not _sig.get("valid"):
            codes = ", ".join(r.get("code", "?") for r in _sig["rejected"])
            _log.error("[schema] input signals rejected: %s", codes)
            for r in _sig["rejected"]:
                _log.error("  #%s %s: %s", r.get("index"), r.get("code"),
                           r.get("reason"))
            return {"status": "error", "error_code": "SIG_INVALID_SIGNALS",
                    "error": f"信号 schema 校验失败: {codes}",
                    "signal_validation": _sig, "accepted": _sig["accepted"],
                    "progressed": False, "signals_tested": 0}
        if fast:
            return self.run_fast(signals)

        # W1-RESUME-01 Slice 3: step-level checkpoint/resume. run() loads a
        # mid-round step checkpoint and sets _resume_at; consume it once here.
        # _done_idx = index of the LAST step already committed on the pre-crash
        # pass; steps at idx <= _done_idx are skipped and their artifacts restored
        # from the cumulative checkpoint payload.artifacts, while steps at
        # idx > _done_idx execute and save a fresh cumulative step checkpoint.
        _resume_hint = self._resume_at
        self._resume_at = None
        _done_idx = -1
        self._step_arts = {}
        if isinstance(_resume_hint, dict) and _resume_hint.get("step") in _STEP_INDEX:
            _done_idx = _STEP_INDEX[_resume_hint["step"]]
            self._step_arts = dict(_resume_hint.get("artifacts") or {})

        def _save_step(_token, **_arts):
            self._step_arts[_token] = _arts
            try:
                self.store.save_checkpoint(self._checkpoint_payload(
                    _token, {"artifacts": dict(self._step_arts)}))
            except Exception:
                _log.debug("[resume] step checkpoint save failed (%s)",
                           _token, exc_info=True)

        task_work_dir = self.work_dir / f"loop-{date.today().isoformat()}"

        # [U] Understand
        if _STEP_INDEX["understand"] <= _done_idx:
            pass  # restored: task_work_dir recomputed above
        else:
            bar.begin_step("Understand", "Confirm task understanding")
            elog.append(step_start_event("understand"), {"round": round_num or self.total_rounds + 1})
            task_work_dir = self.work_dir / f"loop-{date.today().isoformat()}"
            require_input = bool((self.cfg or {}).get("ooda", {}).get("uq_require_input", False))
            u_result = OODASteps._ensure_understand(
                self.store, self.task_cfg, task_work_dir, require_input=require_input)
            if not u_result["complete"] or not u_result["fields_ok"]:
                missing = []
                if not u_result.get("has_goal"): missing.append("goal")
                if not u_result.get("has_boundary"): missing.append("boundary")
                if not u_result.get("has_success"): missing.append("success_criteria")
                if u_result.get("template_created"):
                    bar.add_issue("warn", "U-UNDERSTAND",
                                  f"Template created: {u_result['path']}, fill in: {missing}")
                    bar.add_suggestion(f"Edit {u_result['path']} to complete task understanding, then re-run")
                else:
                    bar.add_issue("error" if u_result.get("needs_input") else "warn",
                                  "U-UNDERSTAND",
                                  f"缺输入: {missing} (未传则此处强提醒; 已传/agent执行可跳过)")
                # 未传且要求必填 -> 强提醒; 交互+TTY 下请求补填，否则(agent/非交互)标记后继续
                if u_result.get("needs_input"):
                    if getattr(self, "interactive", True):
                        try:
                            ans = input("      [U&Q] 填写 goal/boundary/success_criteria，或空以跳过: ").strip()
                        except (EOFError, KeyboardInterrupt):
                            ans = ""
                        bar.add_issue(("warn" if ans else "error"), "U-UNDERSTAND",
                                      ("已人工补填" if ans else "未补填，按 agent 模式继续"))
                bar.end_step("Understand", "warn: incomplete")
                elog.append(step_end_event("understand"), {"complete": False, "missing": missing, "round": round_num or self.total_rounds + 1})
            else:
                bar.end_step("Understand", "ok")
                elog.append(step_end_event("understand"), {"complete": True,
                    "goal": u_result.get("goal", ""),
                    "boundary": u_result.get("boundary", ""),
                    "success": u_result.get("success", ""),
                    "round": round_num or self.total_rounds + 1})
            _save_step("understand")

        # [O] Observe
        if _STEP_INDEX["observe"] <= _done_idx:
            observations = self._step_arts.get("observe", {}).get("observations")
            prev_state = None  # consumed only inside Observe on execute path
        else:
            bar.begin_step("Observe", "Load state and experience library")
            elog.append(step_start_event("observe"), {"round": round_num or self.total_rounds + 1})
            prev_state = None
            if round_num > 1 or self.total_rounds > 0:
                state_file = task_work_dir / "state.md"
                if state_file.exists():
                    prev_state = {"file": str(state_file), "size": state_file.stat().st_size}
            observations = OODASteps._observe(
                self.store, round_num or self.total_rounds + 1, signals,
                task_work_dir, prev_state,
                warn_namespace=not self._warned_namespace)
            self._warned_namespace = True
            bar.end_step("Observe", bar._tag("data", f"in={observations['signals_input']} "
                         f"excl={observations['signals_excluded']} "
                         f"lib={observations['failure_patterns_loaded']} failures"))
            elog.append(step_end_event("observe"), {"round": round_num or self.total_rounds + 1,
                          "signals_input": observations["signals_input"],
                          "signals_excluded": observations["signals_excluded"],
                          "signals_passed": observations["signals_passed"],
                          "patterns_loaded": observations["failure_patterns_loaded"],
                          "ctx": build_context_snapshot(
                              context_type="observe",
                              input_data={"signals_input": observations["signals_input"],
                                           "excluded": observations["signals_excluded"],
                                           "passed": observations["signals_passed"]},
                              config=self.task_cfg,
                              pattern_ids=["fp:%d" % i for i in range(observations["failure_patterns_loaded"])],
                              summary=("observe in=%d excl=%d pass=%d rules=%d" % (
                                  observations["signals_input"], observations["signals_excluded"],
                                  observations["signals_passed"], observations["exclusion_rules_active"])),
                          ).to_dict()})
            _save_step("observe", observations=observations, prev_state=prev_state)

        # [O] Orient
        if _STEP_INDEX["orient"] <= _done_idx:
            diagnosis = self._step_arts.get("orient", {}).get("diagnosis")
        else:
            bar.begin_step("Orient", "Diagnose state and root cause")
            elog.append(step_start_event("orient"), {"round": round_num or self.total_rounds + 1})
            diagnosis = OODASteps._orient(observations, bar, prev_ctx=prev_ctx)
            bar.end_step("Orient", bar._tag("conclusion", f"{diagnosis['severity']} | {diagnosis['issue_count']} issues"))
            elog.append(step_end_event("orient"), {"round": round_num or self.total_rounds + 1,
                          "severity": diagnosis["severity"],
                          "issue_count": diagnosis["issue_count"],
                          "stop_signal": diagnosis.get("stop_signal", False),
                          "ctx": build_context_snapshot(
                              context_type="orient",
                              input_data=observations.get("check_result") or {},
                              pattern_ids=[r.get("rule") for r in diagnosis.get("issues", [])
                                           if isinstance(r, dict)],
                              summary="orient severity=%s issues=%d stop=%s" % (
                                  diagnosis["severity"], diagnosis["issue_count"],
                                  diagnosis.get("stop_signal", False)),
                          ).to_dict()})
            _save_step("orient", diagnosis=diagnosis)

        # [D] Decide
        if _STEP_INDEX["decide"] <= _done_idx:
            decision = self._step_arts.get("decide", {}).get("decision")
        else:
            bar.begin_step("Decide", "Formulate action plan")
            elog.append(step_start_event("decide"), {"round": round_num or self.total_rounds + 1})
            zones = {"green": self.zone_green, "yellow": self.zone_yellow, "red": self.zone_red}
            decision = OODASteps._decide(diagnosis, round_num or self.total_rounds + 1,
                                         self.task_cfg, zones)
            if decision["action"] == "skip":
                bar.add_issue("critical", "D-SKIP", decision["reason"])
            bar.end_step("Decide", decision["approach"])
            elog.append(step_end_event("decide"), {"round": round_num or self.total_rounds + 1,
                          "action": decision["action"],
                          "approach": decision["approach"],
                          "reason": decision.get("reason", ""),
                          "ctx": build_context_snapshot(
                              context_type="decide",
                              input_data={"action": decision.get("action", ""),
                                           "approach": decision.get("approach", "")},
                              sources=[{"kind": "diagnosis", "summary": diagnosis.get("severity", "")}],
                              summary=decision.get("reason", "")[:200],
                          ).to_dict()})
            bar.set_decision(decision["approach"].replace("standard_backtest", "execute")
                             .replace("skip_on_critical", "SKIP").replace("record_only", "NO-OP"))
            _save_step("decide", decision=decision)

        # [A] Act
        if _STEP_INDEX["act"] <= _done_idx:
            _a = self._step_arts.get("act", {})
            act_result = _a.get("act_result")
            l1_attempts = _a.get("l1_attempts", [])
            act_error = _a.get("act_error", "")
            _act_elapsed = _a.get("act_elapsed", 0.0)
        else:
            bar.begin_step("Act", decision.get("reason", "Execute task"))
            elog.append(step_start_event("act"), {"round": round_num or self.total_rounds + 1,
                           "action": decision.get("action", ""),
                           "approach": decision.get("approach", "")})
            import time as _time
            _act_start = _time.time()
            act_result, l1_attempts = OODASteps._act_with_retry(
                decision, observations["check_result"]["passed"],
                self.bt_settings, self.store, self.task_cfg,
                registry=self.tool_registry,
                exec_gate=self._exec_gate)
            _act_elapsed = (_time.time() - _act_start) * 1000
            if act_result["status"] == "error":
                bar.add_issue("major", "A-ERROR",
                              str(act_result.get("error", "unknown"))[:100])
                bar.add_suggestion("Check task runner and I/O contract")
            bar.end_step("Act", bar._tag("data", f"status={act_result['status']} "
                         f"items={len(act_result.get('trades', []))}"
                         + (f" retries={len([a for a in l1_attempts if not a['ok']])}"
                            if any(not a['ok'] for a in l1_attempts) else "")))
            # v2.2 P0: 结构化 Act 事件
            act_error = act_result.get("error", "")
            elog.append(EVT_ACT_RESULT, {"status": act_result["status"],
                          "round": round_num or self.total_rounds + 1,
                          "trades": len(act_result.get("trades", [])),
                          "error": act_error[:500],
                          "elapsed_ms": round(_act_elapsed, 1),
                          "sharpe": act_result.get("sharpe", 0),
                          "win_rate": str(act_result.get("win_rate", "")),
                          "provenance_ref": _compact_provenance_ref(
                              act_result.get("task_result")),
                          "ctx": build_context_snapshot(
                              context_type="act",
                              input_data={"status": act_result.get("status"),
                                           "trades_count": len(act_result.get("trades", []))},
                              summary="act status=%s trades=%d" % (
                                  act_result.get("status"), len(act_result.get("trades", []))),
                          ).to_dict()})
            for a in l1_attempts:
                elog.append(EVT_ACT_RETRY, {"round": round_num or self.total_rounds + 1,
                              "strategy": a.get("strategy", ""),
                              "ok": a.get("ok", False),
                              "note": a.get("note", "")})
            # Persist the content identity outside opaque TaskResult objects;
            # checkpoint JSON uses default=str and must not lose this gate.
            self._provenance_digest = extract_provenance_digest(act_result)
            _save_step("act", act_result=act_result, l1_attempts=l1_attempts, act_error=act_error, act_elapsed=_act_elapsed)

        # On a resume path Act may be restored from checkpoint artifacts; keep
        # the digest available for the next checkpoint without re-running Act.
        self._provenance_digest = (
            extract_provenance_digest(act_result) or
            getattr(self, "_provenance_digest", "")
        )

        # [V] Verify
        if _STEP_INDEX["verify"] <= _done_idx:
            verified = self._step_arts.get("verify", {}).get("verified")
        else:
            bar.begin_step("Verify", "Compare against success criteria")
            elog.append(step_start_event("verify"), {"round": round_num or self.total_rounds + 1})
            criteria = self.task_cfg.get("success_criteria", [])
            # P1-D5: a missing/empty success_criteria used to be replaced by a
            # silent trades_count>0 default, so a run could report 'verified'
            # without ever declaring a real success bar. Keep the fallback for
            # back-compat, but make it loud (status-bar warning) and auditable
            # (implicit_criteria flag on the verify result) so it is never a
            # silent PASS.
            implicit_criteria = not criteria
            if implicit_criteria:
                criteria = [{"metric": "trades_count", "operator": "gt", "threshold": 0}]
                if bar is not None:
                    bar.add_issue("warn", "CRITERIA-IMPLICIT",
                                  "task.success_criteria is empty; fell back to implicit "
                                  "trades_count>0 - declare explicit criteria for a real "
                                  "success bar")
            verified = OODASteps._verify(act_result, criteria, bar)
            if implicit_criteria:
                verified["implicit_criteria"] = True

            # [V2] 断言 + 回归验证（可选，verification 字段配置）
            verification_cfg = self.task_cfg.get("verification", {})
            assertions = verification_cfg.get("assertions", [])
            if assertions:
                mode = verification_cfg.get("mode", "single")
                verified_assert = OODASteps._verify_assertions(act_result, assertions, bar, mode, self.runtime)
                verified["pass_count"] += verified_assert["pass_count"]
                verified["fail_count"] += verified_assert.get("fail_count", 0)
                verified["total"] += verified_assert["total"]
                verified["assertions"] = verified_assert["details"]

            # P2: 回归测试
            regression_cfg = verification_cfg.get("regression", {})
            if regression_cfg.get("tests"):
                verified_reg = OODASteps._verify_regression(regression_cfg, bar, self.runtime)
                verified["pass_count"] += verified_reg["pass_count"]
                verified["fail_count"] += verified_reg.get("fail_count", 0)
                verified["total"] += verified_reg["total"]

            # P3: 风险等级强制检查
            risk_level = self.task_cfg.get("risk_level", "low")
            if risk_level == "high" and not assertions:
                bar.add_issue("critical", "RISK-HIGH",
                              "risk_level=high but no verification configured — task blocked")
                verified["blocked"] = True

            bar.end_step("Verify", f"{verified['pass_count']}/{verified['total']} passed"
                         + (f" {verified['fail_count']} failed" if verified['fail_count'] else ""))
            elog.append(EVT_VERIFY_RESULT, {"round": round_num or self.total_rounds + 1,
                          "pass_count": verified["pass_count"],
                          "total": verified["total"],
                          "fail_count": verified.get("fail_count", 0),
                          "details": verified.get("details", []),
                          "ctx": build_context_snapshot(
                              context_type="verify",
                              input_data={"criteria": criteria},
                              summary="verify %d/%d (%d failed)" % (
                                  verified["pass_count"], verified["total"],
                                  verified.get("fail_count", 0)),
                          ).to_dict()})
            _save_step("verify", verified=verified)

        # [L] Learn
        if _STEP_INDEX["learn"] <= _done_idx:
            learned = self._step_arts.get("learn", {}).get("learned")
        else:
            bar.begin_step("Learn", "Record lessons")
            learn_round = round_num or self.total_rounds + 1
            elog.append(step_start_event("learn"), {"round": learn_round})
            # W1-RESUME-01 Slice 2: make the Learn unit idempotent per (run_id,
            # round). A crash AFTER Learn committed (patterns + rounds row) but
            # BEFORE the round_end checkpoint is persisted leaves only the
            # round_start checkpoint; resume replays the whole round and would
            # re-run Learn - duplicating the rounds row and re-bumping failure
            # occurrences (critical③, scheme §一③; learn_round stays stable
            # across the replay because run() re-increments total_rounds to the
            # same value). The run_learns ledger gates the unit inside the SAME
            # atomic transaction: if (run_id, learn_round) already committed, this
            # pass is a replay-skip (no _learn, no log_round) returning zeros, and
            # the ledger row + patterns commit together so a mid-unit crash still
            # leaves no partial state for the next replay to double-count.
            with self.store.transaction():
                if self._run_id and self.store.learn_done(self._run_id, learn_round):
                    learned = {"new_failures": 0, "new_successes": 0,
                               "bumped_failures": 0, "bumped_successes": 0}
                else:
                    learned = OODASteps._learn(act_result, verified, self.store)
                    self.store.log_round(
                        observations["signals_input"], observations["signals_excluded"],
                        observations["signals_passed"], learned["new_failures"],
                        learned["new_successes"],
                        act_result.get("error") or "ok")
                    if self._run_id:
                        self.store.mark_learn_done(self._run_id, learn_round)
            bar.end_step("Learn", f"+{learned['new_failures']} failures "
                         f"+{learned['new_successes']} successes"
                         + (f" rebump {learned['bumped_failures']} old"
                            if learned['bumped_failures'] else ""))
            elog.append(EVT_LEARN_RECORD, {"round": round_num or self.total_rounds + 1,
                          "new_failures": learned["new_failures"],
                          "new_successes": learned["new_successes"],
                          "bumped_failures": learned.get("bumped_failures", 0)})
            elog.append(EVT_ROUND_END, {"round": round_num or self.total_rounds + 1,
                          "status": "ok", "total_events": elog.count})
            _save_step("learn", learned=learned)

            # P0: Producer — push anomalies to problem queue
            self._produce_problems(observations, act_result, learned, diagnosis, bar,
                                  l1_attempts=l1_attempts)

            # [Improve] 生成缺陷改进报告（每 5 轮或首次发现问题时）
            if (learned["new_failures"] > 0
                    or self.total_rounds % 5 == 0
                    or self.total_rounds == 1):
                self._produce_defect_report(learned, act_result, observations)

        bar.final(verified, learned)

        progressed = (learned["new_failures"] > 0 or learned["new_successes"] > 0) \
            and not (act_result.get("error") and not act_result.get("trades"))
        all_excluded = (decision["action"] == "skip_backtest")

        # ── v2.2 P0: 构建 RoundContext 传递到下一轮 ─────
        verify_failures_detail = []
        for d in verified.get("details", []):
            if d.get("passed") is False:
                verify_failures_detail.append({
                    "metric": d.get("metric", ""),
                    "actual": d.get("actual"),
                    "threshold": d.get("threshold"),
                    "operator": d.get("operator", ""),
                })
        round_ctx = RoundContext(
            round_num=round_num or self.total_rounds + 1,
            prev_act_status=act_result["status"],
            prev_act_error=act_error[:500],
            prev_act_trades_count=len(act_result.get("trades", [])),
            prev_act_elapsed_ms=round(_act_elapsed, 1),
            l1_history=l1_attempts,
            prev_verify_pass=verified["pass_count"],
            prev_verify_total=verified["total"],
            prev_verify_failures=verify_failures_detail,
            prev_severity=diagnosis["severity"],
            prev_issue_count=diagnosis["issue_count"],
            consecutive_errors=self._consecutive_errors,
            error_chain=(prev_ctx.error_chain if prev_ctx else [])
                        + ([act_error[:200]] if act_error else []),
        )

        # - A2/inv-2: make token_budget a LIVE stop condition (not a dead knob) ---
        # loop has no LLM (E4/E5 decision A = deterministic rule-state backtest);
        # config.yaml marks tokens as budget.soft 'intent, agent cannot precisely
        # measure', yet stop.safety still treats budget_exhausted as a HARD stop
        # hanging on an always-0 tokens_used -> dead condition (run_loop.py:244 /
        # circuit_state.py:154). Accrue a deterministic, agent-self-measurable
        # work-volume (bytes of this round's OODA event-log) so the soft intent
        # becomes a measurable hard trigger. Preserves no-LLM identity: no model
        # billing interface is ever invoked.
        try:
            _round_work = int(Path(elog._path).stat().st_size)
        except Exception:
            _round_work = max(1, elog.count * 64)
        self.tokens_used += max(1, _round_work)

        # P0-FIX: an Act-level failure (adapter returned status=error, e.g.
        # wrapper non-zero exit / invalid JSON / missing script) must propagate
        # into the run envelope so the CLI exits non-zero, instead of being
        # masked as a generic "ok" completion.
        act_failed = (act_result.get("status") == "error"
                      or act_result.get("execution_failed") is True)
        run_status = "error" if act_failed else "ok"
        run_error = None
        if act_failed:
            run_error = act_result.get("error") or "act failed (no error detail)"
        return {
            "check": observations["check_result"],
            "diagnosis": {"severity": diagnosis["severity"],
                          "issues": len(diagnosis["issues"])},
            "decision": decision["approach"],
            "backtest": act_result.get("raw"),
            "backtest_status": act_result["status"],
            "execution_failed": act_result.get("execution_failed", False),
            "trades": len(act_result.get("trades", [])),
            "record": learned,
            "verified": verified,
            "progressed": progressed,
            "all_excluded": all_excluded,
            "status": run_status,
            "error": run_error,
            "status_bar": bar,
            "round_ctx": round_ctx,  # v2.2 P0: 跨轮上下文
        }
