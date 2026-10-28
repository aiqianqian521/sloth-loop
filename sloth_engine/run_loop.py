"""Run-loop controller mixin for the Orchestrator (P2.2 slice E2).

Extracted verbatim from orchestrator.py: the continuous-round controller run()
(resume load, circuit.restore, round iteration, stop diagnosis, contract/scope
limits, round_start/round_end save->flush order). Kept as a mixin so self.*
(run_once, _checkpoint_payload, _flush_circuit_transition, _check_contract_limits,
_check_scope_violation, _stop_diagnosis, _safe_run_component) resolve via MRO.
Bare-name lookups (time/date, EventLog, RoundContext, check_compatibility,
compute_pool_hash, pool_matches, _log, _STEP_INDEX) resolve against this module
globals; _STEP_ORDER/_STEP_INDEX are verbatim copies equal by value.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date
from pathlib import Path

from event_log import EventLog
from round_context import RoundContext
from resume_guard import check_compatibility, compute_pool_hash, pool_matches
from adapters.backtest_adapter import probe_provenance
from immutable_state import LoopState, StateReducer, StateHistory
from async_loop import LoopYield, LoopControl
from hook_events import HookEvent
from backpressure import DEFER_STATUS, classify_round

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_log = logging.getLogger("sloth_engine")

_STEP_ORDER = ("understand", "observe", "orient", "decide", "act", "verify", "learn")
_STEP_INDEX = {name: idx for idx, name in enumerate(_STEP_ORDER)}

class RunLoopMixin:

    # cycle-10 G-6: provider quota gate
    def _quota_snapshot(self):
        """Resolve the opt-in provider quota snapshot (fail-soft).

        Returns None when no probe is configured (the default, so the run loop
        behaves exactly as before).  Any probe failure degrades to the cached /
        error snapshot inside ``quota_window.resolve_snapshot`` instead of
        raising, so an unreachable provider can never stop a run by itself.
        """
        probe = getattr(self, "quota_probe", None)
        if probe is None:
            return None
        from quota_window import resolve_snapshot
        snapshot = resolve_snapshot(
            probe,
            provider=getattr(self, "quota_provider", "") or "loop",
            now=int(time.time() * 1000),
            cache=getattr(self, "quota_cache", None),
        )
        self.quota_cache = snapshot
        return snapshot

    def _quota_stop_reason(self):
        """A stop reason when any provider quota window is exhausted, else None."""
        snapshot = self._quota_snapshot()
        if snapshot is None or not snapshot.exhausted:
            return None
        detail = "provider=%s" % snapshot.provider
        reset = snapshot.next_reset_at()
        if reset:
            detail += ", next_reset_at=%s" % reset
        return "Quota exhausted (%s)" % detail

    def _export_state_history(self):
        """P3-A1 / cycle-14: 导出本轮不可变状态历史（无快照时 no-op）。

        该导出块原先写死在 ``run()`` 的 ``return`` **之后**，是不可达死代码
        ——``_state_history`` 只在内存里增长，从不落盘。本轮提取为方法，并在
        ``run()`` 返回前与 ``iter_loop()`` 收尾处各调用一次（行为等价：仅在
        真有快照时多写一个 ``state-history-<run_id>.jsonl``）。
        """
        history = getattr(self, "_state_history", None)
        if history is None or history.count <= 0:
            return None
        history_path = self.work_dir / f"state-history-{self._run_id}.jsonl"
        history.to_jsonl(history_path)
        _log.info("[state-history] exported %d rounds to %s", history.count, history_path)
        return history_path

    def run(self, seed_path: str | None = None):
        self.started_at = time.time()
        resume_checkpoint = None
        if self.resume_requested:
            resume_checkpoint = self.store.load_latest_checkpoint(
                self.task_cfg.get("name", "loop"))
            if resume_checkpoint:
                current_provenance_digest = (
                    getattr(self, "_provenance_digest", "")
                    or str((self.cfg.get("backtest") or {}).get("provenance_digest", ""))
                )
                if not current_provenance_digest:
                    current_source = probe_provenance(self.bt_settings, exec_gate=self._exec_gate)
                    current_provenance_digest = str(
                        (current_source or {}).get("provenance_digest", ""))
                ok, reason = check_compatibility(
                    resume_checkpoint,
                    current_cfg=self.cfg,
                    current_task_name=self.task_cfg.get("name", "loop"),
                    current_schema_version=self.store.schema_version(),
                    current_provenance_digest=current_provenance_digest)
                if not ok:
                    if reason.startswith("resume_provenance_mismatch"):
                        self._resume_error = {
                            "status": "error",
                            "error_code": "resume_provenance_mismatch",
                            "error": reason,
                            "run_id": resume_checkpoint.get("run_id", ""),
                        }
                        _log.error("[resume] refusing checkpoint: %s", reason)
                        return self._resume_error
                    _log.warning("[resume] refusing stale/incompatible "
                                 "checkpoint (run_id=%s): %s; starting fresh",
                                 resume_checkpoint.get("run_id"), reason)
                    self.store.clear_checkpoint(resume_checkpoint["run_id"])
                    resume_checkpoint = None
        if resume_checkpoint:
            self._run_id = resume_checkpoint["run_id"]
            # W1-RESUME-01 Slice 6: this is a resume pass, so checkpoints
            # emitted here record attempt=1 (the idempotency-key attempt
            # component) instead of the first-pass attempt=0.
            self._resume_pass = True
            self._cursor = int(resume_checkpoint.get("signal_cursor", 0))
            self._consecutive_errors = int(
                resume_checkpoint.get("consecutive_failures", 0))
            breaker_snapshot = (resume_checkpoint.get("payload") or {}).get("breaker")
            if breaker_snapshot:
                self.circuit.restore(breaker_snapshot)
            else:
                self.circuit.consecutive_failures = self._consecutive_errors
            step = resume_checkpoint.get("step", "round_start")
            checkpoint_round = int(resume_checkpoint.get("round", 0))
            if step in _STEP_INDEX:
                # W1-RESUME-01 Slice 3: mid-round step checkpoint. Re-run the
                # SAME round (the loop re-increments total_rounds) but skip
                # through the already-committed step. The pre-consume cursor
                # restored above lets generate_signals reproduce the same
                # signal batch deterministically.
                self.total_rounds = max(0, checkpoint_round - 1)
                self._resume_at = {
                    "step": step,
                    "artifacts": (resume_checkpoint.get("payload") or {}).get("artifacts") or {},
                }
            else:
                # A round_start checkpoint means the round was interrupted and
                # should be retried; round_end means it completed successfully.
                self.total_rounds = max(
                    0, checkpoint_round - 1 if step == "round_start" else checkpoint_round)
            _log.info("[resume] checkpoint=%s round=%s step=%s cursor=%s",
                      self._run_id, checkpoint_round, step, self._cursor)
            # W1-RESUME-01 Slice 4 (pool_hash gate): the pre-consume cursor
            # restored above only reproduces the same signal batch if the
            # rebuilt pool is identical to checkpoint time. pool_matches is
            # inert for a blank stored hash; a real mismatch means the seed
            # pool changed under the cursor -> index a different pool. Skip
            # when stored == the empty-pool digest (round-1 round_start saved
            # before the pool is built, so no pool identity was recorded). On
            # mismatch, reset to a fresh round and drop any mid-round
            # step-resume. Slice 2 (run_id, round) run_learns ledger keeps the
            # repeated round from double-Learning.
            _stored_pool_hash = (resume_checkpoint.get("pool_hash") or "")
            if _stored_pool_hash and _stored_pool_hash != compute_pool_hash([]):
                _cur_pool = self._load_pool(seed_path)
                if not pool_matches(_stored_pool_hash, _cur_pool or []):
                    _log.warning(
                        "[resume] pool_hash mismatch (run_id=%s): signal pool "
                        "changed since checkpoint -> reset cursor to 0 and "
                        "drop step-resume (re-run round from fresh batch).",
                        self._run_id)
                    self._cursor = 0
                    self._resume_at = None
                    self.total_rounds = max(0, checkpoint_round - 1)
        else:
            self._run_id = (f"{date.today().isoformat()}-"
                            f"{self._safe_run_component(self.task_cfg.get('name', 'loop'))}-"
                            f"{int(self.started_at)}")
        # W1-CB-01 Slice 1: run-level append-only audit for circuit transitions.
        # Stable across resume: keyed only by run_id (the checkpoint reuses the
        # same run_id on resume), so a resumed pass appends to the SAME file.
        # on_transition stages each transition as a pending slot (no I/O in the
        # decision path); _flush_circuit_transition appends AFTER save_checkpoint
        # so a crash before the post-transition state is durable cannot duplicate
        # the event (W1-RESUME-01: accept gap, reject duplicate).
        self._pending_circuit_transition = None
        self._breaker_log = EventLog(
            self.work_dir / f"circuit-{self._run_id}.jsonl",
            task_name=self.task_cfg.get("name", "loop"))
        prev = self._recover_state()
        handoff = self._read_handoff()
        prev_ctx: RoundContext | None = None  # v2.2 P0: 跨轮上下文
        # P3-A1: 不可变状态追踪层（纯附加，不改现有 self.* 行为）
        self._state_history = StateHistory()
        # P3-B2: session start
        if hasattr(self, "hook_bus") and self.hook_bus is not None:
            self.hook_bus.fire_session_start(
                task_name=self.task_cfg.get("name", "loop"))
        self._last_loop_state: LoopState | None = None
        _log.info(f" Starting | max_rounds={self.max_rounds} "
              f"no_progress_stop={self.no_progress_stop} "
              f"max_seconds={self.max_seconds or 'unlimited'} "
              f"ooda={'ON' if self.enable_ooda else 'OFF'}"
              + (f" | prev_rounds={prev['prev_rounds']}" if prev else ""))
        _log.info(f" Backtest script: {self.bt_settings['script']}")
        stop_reason = "max_rounds reached"

        while self.total_rounds < self.max_rounds:
            if not self.controller.allow_round(self.total_rounds):
                stop_reason = (f"circuit breaker OPEN "
                               f"(failures={self.circuit.consecutive_failures})")
                break
            # cycle-10 G-6: stop before starting a round the provider budget
            # can no longer fund (no-op unless a quota probe was injected).
            quota_stop = self._quota_stop_reason()
            if quota_stop:
                stop_reason = quota_stop
                _log.info(f" {self.total_rounds}] {stop_reason}")
                break
            self.total_rounds += 1
            # 每轮重置 Guardian 审查预算：长循环中按轮限流，避免单会话预算
            # (20) 被多轮 spawn 耗尽后误拦合法回测（否则熔断停机）。
            _eg = getattr(self, '_exec_gate', None)
            if _eg is not None and hasattr(_eg, 'reset_review_budget'):
                try:
                    _eg.reset_review_budget()
                except Exception:
                    pass
            # AGE-13 / CTX-01: reset recovery state per-turn flags
            if hasattr(self, 'compactor') and self.compactor is not None:
                self.compactor.rs.reset_for_new_turn()
            # P3-B2: 生命周期事件
            if hasattr(self, "hook_bus") and self.hook_bus is not None:
                self.hook_bus.fire_round_start(
                    task_name=self.task_cfg.get("name", "loop"),
                    round_num=self.total_rounds)
            self._round_start_cursor = self._cursor  # W1-RESUME-01 Slice 3

            # W1 checkpoint: persist before executing a round so an
            # interrupted process can be resumed without guessing its cursor.
            self.store.save_checkpoint(self._checkpoint_payload("round_start"))
            self._flush_circuit_transition(self.total_rounds)

            # Phase 1: 合同执行 — 预算/停止/安全边界检查
            contract_breach = self._check_contract_limits()
            if contract_breach:
                stop_reason = contract_breach
                break

            signals = self.generate_signals(seed_path)
            if not signals:
                stop_reason = "No candidate signals (check --signals path and file content)"
                _log.info(f" {self.total_rounds}] {stop_reason}")
                self.total_rounds -= 1
                break

            # Phase 1: scope.deny 检查 — 任务不能触碰被禁路径
            scope_violation = self._check_scope_violation(signals)
            if scope_violation:
                stop_reason = f"Scope violation: {scope_violation}"
                break


            # CTX-01: run context compaction pipeline before each round
            if hasattr(self, 'compactor') and self.compactor is not None:
                compact_result = self.compactor.run_pipeline(pre_api_call=True)
                if compact_result.get('actions_taken'):
                    _log.info('[compact] pipeline actions: %s', compact_result['actions_taken'])

            res = self.run_once(signals, self.total_rounds,
                                fast=not self.enable_ooda,
                                prev_ctx=prev_ctx)  # v2.2 P0
            r = res["record"]
            extra = ""
            if r["bumped_failures"] or r["bumped_successes"]:
                extra = f" | rebump f={r['bumped_failures']} s={r['bumped_successes']}"
            chk = res.get("check", {})
            summary = chk.get("summary", f"in={chk.get('input_count','?')}")
            _log.info(f" {self.total_rounds}] {summary} | "
                  f"decision={res.get('decision','?')} "
                  f"new_f={r['new_failures']} new_s={r['new_successes']}{extra}")
            if res.get("backtest") is not None and hasattr(res["backtest"], "error"):
                bt_err = res["backtest"].error
                if bt_err:
                    _log.info(f"    [backtest error] {bt_err[:180]}")
            if res.get("all_excluded"):
                _log.info("    All candidates blocked by exclusion rules — need new signal source")

            # Circuit breaker (contract-aligned: 双上限取更严格者)
            bt = res.get("backtest")
            execution_failed = ((bt is not None and getattr(bt, "status", None) == "error")
                                or res.get("backtest_status") == "error"
                                or res.get("execution_failed") is True)
            circuit_open = False
            deferral = classify_round(
                status=res.get("backtest_status"),
                execution_failed=execution_failed,
                error=res.get("error"),
                text=getattr(bt, "error", None) if bt is not None else None)
            if deferral.deferred and getattr(self, "enable_backpressure_defer", True):
                # Backpressure, not failure: a deferred op must not consume the
                # consecutive-error budget (hindsight DeferOperation semantics).
                # Deliberately do NOT call record_execution and do NOT touch
                # self._consecutive_errors / the circuit breaker.
                _log.info("round deferred (backpressure: %s) - not counted as failure",
                          deferral.reason)
                if hasattr(self, "hook_bus") and self.hook_bus is not None:
                    self.hook_bus.fire(HookEvent.CIRCUIT_OPEN,
                        task_name=self.task_cfg.get("name", "loop"),
                        round_num=self.total_rounds,
                        data={"deferred": True, "reason": deferral.reason,
                              "retry_after": deferral.retry_after})
            elif execution_failed:
                max_fail = min(self.error_stop,
                               self.budget_hard.get("max_consecutive_failures", self.error_stop))
                self.circuit.failure_threshold = max(1, int(max_fail or self.error_stop))
                state = self.controller.record_execution("error")
                self._consecutive_errors = self.circuit.consecutive_failures
                if state == "OPEN":
                    stop_reason = (f"{self._consecutive_errors} consecutive errors, "
                                   f"circuit breaker (limit={max_fail})")
                    circuit_open = True
            elif bt is not None:
                self.controller.record_execution("completed")
                self._consecutive_errors = 0

            # Persist the post-accounting state.  Saving before breaker
            # bookkeeping loses one failure if the process resumes between
            # round_end and the next round_start.
            prev_ctx = res.get("round_ctx")  # v2.2 P0: 传递到下一轮
            if prev_ctx is not None:
                prev_ctx.consecutive_errors = self._consecutive_errors
            self.store.save_checkpoint(self._checkpoint_payload("round_end"))
            self._flush_circuit_transition(self.total_rounds)
            # P3-B2: 熔断器事件
            if hasattr(self, "hook_bus") and self.hook_bus is not None:
                if execution_failed:
                    self.hook_bus.fire(HookEvent.CIRCUIT_OPEN,
                        task_name=self.task_cfg.get("name", "loop"),
                        round_num=self.total_rounds,
                        data={"consecutive_errors": self._consecutive_errors})
                elif bt is not None:
                    self.hook_bus.fire(HookEvent.CIRCUIT_CLOSE,
                        task_name=self.task_cfg.get("name", "loop"),
                        round_num=self.total_rounds)

            if circuit_open:
                break

            if res["progressed"]:
                self.last_progress_round = self.total_rounds

            if self.total_rounds - self.last_progress_round >= self.no_progress_stop:
                stop_reason = f"No new patterns for {self.no_progress_stop} consecutive rounds"
                if hasattr(self, "hook_bus") and self.hook_bus is not None:
                    self.hook_bus.fire_round_end(task_name=self.task_cfg.get("name", "loop"), round_num=self.total_rounds, data={"stop_reason": stop_reason})
                break
            if self.max_seconds and (time.time() - self.started_at) >= self.max_seconds:
                stop_reason = f"Time limit reached ({self.max_seconds}s)"
                if hasattr(self, "hook_bus") and self.hook_bus is not None:
                    self.hook_bus.fire_round_end(task_name=self.task_cfg.get("name", "loop"), round_num=self.total_rounds, data={"stop_reason": stop_reason})
                break
            if self.token_budget and self.tokens_used >= self.token_budget:
                stop_reason = "Token budget exhausted"
                if hasattr(self, "hook_bus") and self.hook_bus is not None:
                    self.hook_bus.fire_round_end(task_name=self.task_cfg.get("name", "loop"), round_num=self.total_rounds, data={"stop_reason": stop_reason})
                break
            # L2: 进度感知触发 + 健康评分 (替代简单 meta_every)
            l2_progress = self._l2_read_progress()
            trigger_type = self._l2_check_triggers(l2_progress)
            if trigger_type:
                rep = self.meta_analyze(trigger_type=trigger_type,
                                        progress_data=l2_progress)
                health = self._l2_health_check(l2_progress, trigger_type)
                _log.info(f":{trigger_type}] health={health['health_score']} "
                      f"Frequencies: {rep['failure_mode_frequency']}")
                for rc in rep["recommendations"]:
                    _log.info(f"    Recommendation: {rc}")

                    _log.info(f":stop] {health['stop_signal']} — health={health['health_score']}")
                    if health["stop_signal"] == "escalate":
                        stop_reason = f"L2 health critical ({health['health_score']})"
                        break
            elif self.meta_every and self.total_rounds % self.meta_every == 0:
                rep = self.meta_analyze()
                _log.info(f" Frequencies: {rep['failure_mode_frequency']}")
                for rc in rep["recommendations"]:
                    _log.info(f"    Recommendation: {rc}")

            # P3-A1: 每轮结尾生成不可变快照
            self._snapshot_loop_state(res, signals)

        elapsed = time.time() - self.started_at
        _log.info(f" Finished: {self.total_rounds} rounds, "
              f"{elapsed:.1f}s, reason: {stop_reason}")
        self._write_state_md(stop_reason, elapsed)
        self._write_handoff(stop_reason)
        self._stop_diagnosis(stop_reason, self.total_rounds)
        self._archive_run(stop_reason, elapsed)
        self._write_customer_report(stop_reason, elapsed)
        # P3-B2: session end
        if hasattr(self, "hook_bus") and self.hook_bus is not None:
            self.hook_bus.fire_session_end(
                task_name=self.task_cfg.get("name", "loop"),
                data={"total_rounds": self.total_rounds, "elapsed": elapsed, "stop_reason": stop_reason})

        # P3-A1: 导出不可变状态历史（cycle-14 修复：原块落在 return 之后，不可达）
        self._export_state_history()

        # P0-FIX: propagate a terminal execution failure to the caller so the
        # CLI/continuous entry returns a non-zero exit code. A stop caused by a
        # circuit breaker / consecutive execution errors is a failure, not a
        # clean max_rounds / no-progress completion.

        _failed = ("circuit breaker" in stop_reason
                   or "consecutive errors" in stop_reason)
        return {
            "status": "error" if _failed else "ok",
            "stop_reason": stop_reason,
            "total_rounds": self.total_rounds,
            "error": stop_reason if _failed else None,
        }


    # ── P3-A1: 不可变状态快照 ──────────────────────────────
    def _fire_round_end(self, stop_reason: str = "", round_num: int = 0):
        """P3-B2: fire round/end event."""
        if hasattr(self, "hook_bus") and self.hook_bus is not None:
            self.hook_bus.fire_round_end(
                task_name=self.task_cfg.get("name", "loop"),
                round_num=round_num or self.total_rounds,
                data={"stop_reason": stop_reason} if stop_reason else {})

    def _snapshot_loop_state(self, res: dict, signals: list[dict]):
        """从当前 self.* 构建不可变 LoopState 快照并追加到历史。

        纯附加层：不修改任何 self.* 属性，不改变现有行为。
        每次调用从 self.* 读取当前值，通过 StateReducer 生成快照。
        """
        bt = res.get("backtest")
        execution_failed = ((bt is not None and getattr(bt, "status", None) == "error")
                            or res.get("backtest_status") == "error"
                            or res.get("execution_failed") is True)
        deferral = classify_round(
            status=res.get("backtest_status"),
            execution_failed=execution_failed,
            error=res.get("error"),
            text=getattr(bt, "error", None) if bt is not None else None)

        prev_state = self._last_loop_state or LoopState()

        state = StateReducer.reduce(
            prev_state,
            run_id=getattr(self, "_run_id", ""),
            started_at=getattr(self, "started_at", 0.0),
            round_num=self.total_rounds,
            cursor=getattr(self, "_cursor", 0),
            signals_input=res.get("check", {}).get("input_count", len(signals)),
            signals_excluded=res.get("check", {}).get("excluded_count", 0),
            decision=str(res.get("decision", "")),
            progressed=bool(res.get("progressed", False)),
            new_failures=int(res.get("record", {}).get("new_failures", 0)),
            new_successes=int(res.get("record", {}).get("new_successes", 0)),
            bumped_failures=int(res.get("record", {}).get("bumped_failures", 0)),
            bumped_successes=int(res.get("record", {}).get("bumped_successes", 0)),
            backtest_status=str(getattr(bt, "status", "") if bt else ""),
            backtest_error=str(getattr(bt, "error", "") if bt and hasattr(bt, "error") else ""),
            execution_failed=execution_failed,
            deferred=deferral.deferred,
            all_excluded=bool(res.get("all_excluded", False)),
            last_progress_round=getattr(self, "last_progress_round", 0),
            consecutive_errors=getattr(self, "_consecutive_errors", 0),
        )
        self._last_loop_state = state
        self._state_history.append(state)

    # ── P3-A2: Generator 接口 — iter_loop() ─────────────────
    def iter_loop(self, seed_path: str | None = None, control: LoopControl | None = None):
        """"run() 的 generator 版本。每轮 yield LoopYield。

        对标 Claude Code query() generator:
        - 调用方可以逐轮消费 (backpressure)
        - 调用方可以通过 LoopControl 暂停/跳过/终止
        - 每轮 yield 包含完整的 LoopState + signals + decision

        用法:
            for y in orchestrator.iter_loop(config, control=ctrl):
                if y.is_terminal:
                    break
                # 调用方处理每轮结果
        """
        ctrl = control or LoopControl()
        self.started_at = time.time()

        # 初始化（与 run() 相同的前置逻辑，但不执行 while 循环）
        resume_checkpoint = None
        if self.resume_requested:
            resume_checkpoint = self.store.load_latest_checkpoint(
                self.task_cfg.get("name", "loop"))
            if resume_checkpoint:
                current_provenance_digest = (
                    getattr(self, "_provenance_digest", "")
                    or str((self.cfg.get("backtest") or {}).get("provenance_digest", ""))
                )
                if not current_provenance_digest:
                    current_source = probe_provenance(self.bt_settings, exec_gate=self._exec_gate)
                    current_provenance_digest = str(
                        (current_source or {}).get("provenance_digest", ""))
                ok, reason = check_compatibility(
                    resume_checkpoint, current_cfg=self.cfg,
                    current_task_name=self.task_cfg.get("name", "loop"),
                    current_schema_version=self.store.schema_version(),
                    current_provenance_digest=current_provenance_digest)
                if not ok:
                    if reason.startswith("resume_provenance_mismatch"):
                        self._resume_error = {
                            "status": "error", "error_code": "resume_provenance_mismatch",
                            "error": reason, "run_id": resume_checkpoint.get("run_id", ""),
                        }
                        _log.error("[resume] refusing checkpoint: %s", reason)
                        yield LoopYield(
                            state=LoopState(),
                            is_terminal=True,
                            stop_reason=f"resume_provenance_mismatch: {reason}",
                        )
                        return
                    _log.warning("[resume] refusing stale checkpoint: %s; starting fresh", reason)
                    self.store.clear_checkpoint(resume_checkpoint["run_id"])
                    resume_checkpoint = None
        if resume_checkpoint:
            self._run_id = resume_checkpoint["run_id"]
            self._resume_pass = True
            self._cursor = int(resume_checkpoint.get("signal_cursor", 0))
            self._consecutive_errors = int(
                resume_checkpoint.get("consecutive_failures", 0))
            breaker_snapshot = (resume_checkpoint.get("payload") or {}).get("breaker")
            if breaker_snapshot:
                self.circuit.restore(breaker_snapshot)
            else:
                self.circuit.consecutive_failures = self._consecutive_errors
            step = resume_checkpoint.get("step", "round_start")
            checkpoint_round = int(resume_checkpoint.get("round", 0))
            if step in _STEP_INDEX:
                self.total_rounds = max(0, checkpoint_round - 1)
                self._resume_at = {"step": step,
                    "artifacts": (resume_checkpoint.get("payload") or {}).get("artifacts") or {}}
            else:
                self.total_rounds = max(
                    0, checkpoint_round - 1 if step == "round_start" else checkpoint_round)
            _stored_pool_hash = (resume_checkpoint.get("pool_hash") or "")
            if _stored_pool_hash and _stored_pool_hash != compute_pool_hash([]):
                _cur_pool = self._load_pool(seed_path)
                if not pool_matches(_stored_pool_hash, _cur_pool or []):
                    _log.warning("[resume] pool_hash mismatch -> reset cursor")
                    self._cursor = 0
                    self._resume_at = None
                    self.total_rounds = max(0, checkpoint_round - 1)
        else:
            self._run_id = (f"{date.today().isoformat()}-"
                            f"{self._safe_run_component(self.task_cfg.get('name', 'loop'))}-"
                            f"{int(self.started_at)}")

        self._pending_circuit_transition = None
        self._breaker_log = EventLog(
            self.work_dir / f"circuit-{self._run_id}.jsonl",
            task_name=self.task_cfg.get("name", "loop"))
        self._state_history = StateHistory()
        self._last_loop_state = None

        prev_ctx = None
        stop_reason = "max_rounds reached"
        _log.info(" Starting iter_loop | max_rounds=%s", self.max_rounds)

        # ── Generator 核心循环 ──
        while self.total_rounds < self.max_rounds:
            if ctrl.abort:
                yield LoopYield(
                    state=LoopState(),
                    is_terminal=True,
                    stop_reason=f"aborted: {ctrl.abort_reason}",
                )
                return

            # 暂停
            while ctrl.pause:
                time.sleep(0.1)

            if not self.controller.allow_round(self.total_rounds):
                stop_reason = f"circuit breaker OPEN (failures={self.circuit.consecutive_failures})"
                break
            quota_stop = self._quota_stop_reason()
            if quota_stop:
                stop_reason = quota_stop
                break
            self.total_rounds += 1
            # P3-B2: 生命周期事件
            if hasattr(self, "hook_bus") and self.hook_bus is not None:
                self.hook_bus.fire_round_start(
                    task_name=self.task_cfg.get("name", "loop"),
                    round_num=self.total_rounds)
            self._round_start_cursor = self._cursor

            self.store.save_checkpoint(self._checkpoint_payload("round_start"))
            self._flush_circuit_transition(self.total_rounds)

            contract_breach = self._check_contract_limits()
            if contract_breach:
                stop_reason = contract_breach
                break

            signals = self.generate_signals(seed_path)
            if not signals:
                stop_reason = "No candidate signals"
                self.total_rounds -= 1
                break

            scope_violation = self._check_scope_violation(signals)
            if scope_violation:
                stop_reason = f"Scope violation: {scope_violation}"
                break

            res = self.run_once(signals, self.total_rounds,
                                fast=not self.enable_ooda, prev_ctx=prev_ctx)
            r = res["record"]

            # Circuit breaker
            bt = res.get("backtest")
            execution_failed = ((bt is not None and getattr(bt, "status", None) == "error")
                                or res.get("backtest_status") == "error"
                                or res.get("execution_failed") is True)
            circuit_open = False
            deferral = classify_round(
                status=res.get("backtest_status"),
                execution_failed=execution_failed,
                error=res.get("error"),
                text=getattr(bt, "error", None) if bt is not None else None)
            if deferral.deferred and getattr(self, "enable_backpressure_defer", True):
                # Backpressure, not failure (same policy as run(); iter_loop
                # shares one classifier so the two entrypoints cannot drift).
                _log.info("round deferred (backpressure: %s) - not counted as failure",
                          deferral.reason)
                if hasattr(self, "hook_bus") and self.hook_bus is not None:
                    self.hook_bus.fire(HookEvent.CIRCUIT_OPEN,
                        task_name=self.task_cfg.get("name", "loop"),
                        round_num=self.total_rounds,
                        data={"deferred": True, "reason": deferral.reason,
                              "retry_after": deferral.retry_after})
            elif execution_failed:
                max_fail = min(self.error_stop,
                               self.budget_hard.get("max_consecutive_failures", self.error_stop))
                self.circuit.failure_threshold = max(1, int(max_fail or self.error_stop))
                state = self.controller.record_execution("error")
                self._consecutive_errors = self.circuit.consecutive_failures
                if state == "OPEN":
                    stop_reason = f"{self._consecutive_errors} consecutive errors, circuit breaker"
                    circuit_open = True
            elif bt is not None:
                self.controller.record_execution("completed")
                self._consecutive_errors = 0

            prev_ctx = res.get("round_ctx")
            if prev_ctx is not None:
                prev_ctx.consecutive_errors = self._consecutive_errors

            self.store.save_checkpoint(self._checkpoint_payload("round_end"))
            self._flush_circuit_transition(self.total_rounds)

            if res["progressed"]:
                self.last_progress_round = self.total_rounds

            # ── 停止条件检查 ──
            is_terminal = False
            # P3-B2: 熔断器事件
            if hasattr(self, "hook_bus") and self.hook_bus is not None:
                if execution_failed:
                    self.hook_bus.fire(HookEvent.CIRCUIT_OPEN,
                        task_name=self.task_cfg.get("name", "loop"),
                        round_num=self.total_rounds,
                        data={"consecutive_errors": self._consecutive_errors})
                elif bt is not None:
                    self.hook_bus.fire(HookEvent.CIRCUIT_CLOSE,
                        task_name=self.task_cfg.get("name", "loop"),
                        round_num=self.total_rounds)

            if circuit_open:
                is_terminal = True
            elif self.total_rounds - self.last_progress_round >= self.no_progress_stop:
                stop_reason = f"No new patterns for {self.no_progress_stop} consecutive rounds"
                is_terminal = True
            elif self.max_seconds and (time.time() - self.started_at) >= self.max_seconds:
                stop_reason = f"Time limit reached ({self.max_seconds}s)"
                is_terminal = True
            elif self.token_budget and self.tokens_used >= self.token_budget:
                stop_reason = "Token budget exhausted"
                is_terminal = True

            # ── 构建不可变快照 ──
            self._snapshot_loop_state(res, signals)

            # ── Yield ──
            yield LoopYield(
                state=self._last_loop_state or LoopState(),
                signals=signals,
                decision=str(res.get("decision", "")),
                act_result=res.get("backtest_result", {}),
                verify_result=res.get("check", {}),
                learned=res.get("record", {}),
                is_terminal=is_terminal,
                stop_reason=stop_reason if is_terminal else "",
                round_num=self.total_rounds,
                elapsed_ms=0.0,
                progress={
                    "consecutive_errors": self._consecutive_errors,
                    "last_progress_round": self.last_progress_round,
                },
            )

            if is_terminal:
                break

        elapsed = time.time() - self.started_at
        _log.info(" iter_loop finished: %s rounds, %.1fs, reason: %s",
                  self.total_rounds, elapsed, stop_reason)
        self._write_state_md(stop_reason, elapsed)
        self._write_handoff(stop_reason)
        self._stop_diagnosis(stop_reason, self.total_rounds)
        self._archive_run(stop_reason, elapsed)
        self._write_customer_report(stop_reason, elapsed)
        # P3-B2: session end
        if hasattr(self, "hook_bus") and self.hook_bus is not None:
            self.hook_bus.fire_session_end(
                task_name=self.task_cfg.get("name", "loop"),
                data={"total_rounds": self.total_rounds, "elapsed": elapsed, "stop_reason": stop_reason})

        # P3-A1: 导出不可变状态历史（cycle-14：iter_loop 此前完全没有导出）
        self._export_state_history()