"""Circuit-breaker transition + checkpoint/state-machine mixin for the Orchestrator (P2.1 slice C2).

Extracted verbatim from orchestrator.py: the on_transition stage port, post-checkpoint
flush, checkpoint payload builder, and contract/scope/criteria guards. Kept as a mixin:
self.* wiring (self.circuit, self.store, self._breaker_log, self._pending_circuit_transition,
self._run_id) and the on_transition/_flush call sites stay in Orchestrator; the methods here
read and flush via self only, matching the W1-CB-01 test seams (test_circuit_breaker
monkeypatches instance attributes, not the methods).
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from resume_guard import (compute_pool_hash, compute_config_hash,
                          compute_signature, extract_provenance_digest)

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Step tokens duplicated from orchestrator (the OODA 7-step protocol order) so this
# mixin stays import-cycle-free: orchestrator imports circuit_state, so circuit_state
# must NOT import orchestrator. Tokens are protocol-stable (event_log step events).
_STEP_ORDER = ("understand", "observe", "orient", "decide", "act", "verify", "learn")
_STEP_INDEX = {name: idx for idx, name in enumerate(_STEP_ORDER)}

_log = logging.getLogger("sloth_engine")

class CircuitState:

    def _stage_circuit_transition(self, old, new, info):
        """Stage a transition as a pending slot only (no I/O in the decision path).

        Bound as the CircuitBreaker on_transition port at composition root so the
        breaker stays a pure state machine with zero import of the audit sink.
        The slot is flushed to disk only after save_checkpoint, making the emit
        contingent on the post-transition state being durable.
        """
        self._pending_circuit_transition = (old, new, info)

    def _flush_circuit_transition(self, round_num):
        """Append the pending transition to the run-level breaker EventLog.

        Called after every save_checkpoint. Writing after the state-durable
        checkpoint means a crash leaves (state, event) durable or (state,
        event-gap) - never (old-state, event-durable): resume restores the
        durable new state so the same path does not re-transition and no
        duplicate is written (W1-RESUME-01). I/O failures drop the event
        (gap) and never raise into the run loop (production-decision-unchanged).
        """
        pending = self._pending_circuit_transition
        if pending is None or self._breaker_log is None:
            return
        self._pending_circuit_transition = None
        old, new, info = pending
        try:
            self._breaker_log.append("circuit/transition", {
                "round": round_num,
                "flushed_after": "checkpoint",
                "state_from": old,
                "state_to": new,
                "trigger": info.get("trigger", ""),
                "consecutive_failures": info.get("consecutive_failures"),
                "failure_threshold": info.get("failure_threshold"),
                "opened_at_wall": info.get("opened_at_wall"),
                "consecutive_probe_success": info.get("consecutive_probe_success"),
            })
        except Exception:
            _log.warning("circuit transition event flush failed (round=%s)",
                         round_num, exc_info=True)
        if self._run_id:
            self.store.clear_checkpoint(self._run_id)
        self._next_steps()

    def _checkpoint_payload(self, step: str,
                             extra: dict | None = None) -> dict:
        """Build a compact, deterministic checkpoint record for W1 resume.

        payload is opaque JSON, so an OODA step checkpoint can stash its
        artifacts under payload.artifacts without a schema migration; a
        mid-round (run_id-stable) step cursor is restored to the pre-consume
        position so resume reproduces the same signal batch.
        """
        pool = self._pool or []
        pool_hash = compute_pool_hash(pool)
        config_hash = compute_config_hash(self.cfg)
        cursor = self._round_start_cursor if step in _STEP_INDEX else self._cursor
        payload = {"runtime_root": str(self.runtime.root),
                   "breaker": self.circuit.snapshot(),
                   "schema_version": self.store.schema_version()}
        if extra:
            payload.update(extra)
        provenance_digest = (
            getattr(self, "_provenance_digest", "")
            or extract_provenance_digest(extra or {})
            or str((self.cfg.get("backtest") or {}).get("provenance_digest", ""))
        )
        if provenance_digest:
            # Keep the derived identity authoritative over opaque extras.
            payload["provenance_digest"] = provenance_digest
        # W1-RESUME-01 Slice 6: protocol-level idempotency signature - single
        # source resume_guard.compute_signature (same _sha as config_hash /
        # pool_hash) so the signature is auditable & replayable: any input
        # change (step/round/cursor/artifacts) flips the signature.
        signature = compute_signature({
            "step": step,
            "round": self.total_rounds,
            "cursor": int(cursor or 0),
            "artifacts": extra or {},
        })
        return {
            "run_id": self._run_id,
            "task_name": self.task_cfg.get("name", "loop"),
            "round": self.total_rounds,
            "step": step,
            "attempt": 1 if getattr(self, "_resume_pass", False) else 0,
            "signal_cursor": cursor,
            "pool_hash": pool_hash,
            "config_hash": config_hash,
            "idempotency_signature": signature,
            "last_event_seq": 0,
            "consecutive_failures": self._consecutive_errors,
            "payload": payload,
        }

    def _check_contract_limits(self) -> str | None:
        """检查合同预算/停止条件是否被违反。返回违规原因，或 None（通过）。"""
        # budget.hard.max_runtime_minutes → 墙钟时间检查
        runtime_min = self.budget_hard.get("max_runtime_minutes", 0)
        if runtime_min and self.started_at:
            elapsed_min = (time.time() - self.started_at) / 60
            if elapsed_min >= runtime_min:
                return f"budget.hard.max_runtime_minutes ({runtime_min}min) exceeded ({elapsed_min:.1f}min)"

        # budget.hard.max_rounds → 使用更严格的限制
        contract_max = self.budget_hard.get("max_rounds", 0)
        effective_max = min(self.max_rounds, contract_max) if contract_max else self.max_rounds
        if self.total_rounds > effective_max:
            return f"budget.hard.max_rounds ({effective_max}) reached"

        # stop.completion: max_rounds_reached
        for cond in self.stop_completion:
            if cond == "max_rounds_reached" and self.total_rounds >= effective_max:
                return f"stop.completion: max_rounds_reached ({effective_max})"
            if cond == "all_criteria_met" and self._all_criteria_met():
                return "stop.completion: all_criteria_met"

        # stop.safety checks
        for cond in self.stop_safety:
            if cond == "budget_exhausted":
                if self.tokens_used >= self.token_budget:
                    return "stop.safety: budget_exhausted (tokens)"
            if cond == "consecutive_failures":
                max_fail = min(self.error_stop,
                               self.budget_hard.get("max_consecutive_failures", self.error_stop))
                if self._consecutive_errors >= max_fail:
                    return f"stop.safety: consecutive_failures ({self._consecutive_errors})"
        return None

    def _check_scope_violation(self, signals: list[dict]) -> str | None:
        """检查任务是否触碰 scope.deny 路径。"""
        if not self.scope_deny:
            return None
        for sig in signals:
            sp = str(sig.get("signal_pattern", ""))
            for denied in self.scope_deny:
                if denied and denied.lower() in sp.lower():
                    return f"signal_pattern '{sp[:60]}' matches scope.deny '{denied}'"
        return None

    def _all_criteria_met(self) -> bool:
        """检查是否所有成功标准已满足（基于最近一轮结果）。"""
        rounds = self.store.get_rounds()
        if not rounds:
            return False
        last = rounds[-1]
        # 最近一轮有新发现 → 未完成
        if last.get("new_failures", 0) > 0 or last.get("new_successes", 0) > 0:
            return False
        # 所有活跃 failure 已 resolved → 完成
        active = [f for f in self.store.load_failure_patterns()
                  if f.get("status") not in ("resolved", "deprecated")]
        return len(active) == 0
