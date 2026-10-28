"""Step-level exception policy: timeout + bounded retry + 3-state error strategy.

Distilled from coze-studio (Go backend) -- see
docs/knowledge-distillation/agent-orchestration/
2026-10-22-coze-studio-step-exception-policy-three-state-and-success-marker.md

Source design:
- backend/domain/workflow/internal/schema/node_schema.go:87-92
    type ExceptionConfig struct {
        TimeoutMS   int64                `json:"timeout_ms,omitempty"`
        MaxRetry    int64                `json:"max_retry,omitempty"`
        ProcessType *vo.ErrorProcessType `json:"process_type,omitempty"`
        DataOnErr   string               `json:"data_on_err,omitempty"`
    }
- backend/domain/workflow/internal/compose/node_runner.go:616-650
    for { invoke; if err != nil { if interrupt -> rethrow immediately;
          if r.maxRetry > n { n++; exeCtx.CurrentRetryCount++; continue };
          return nil, err } }
  => attempts = MaxRetry + 1, and the attempt counter is mirrored into the
     execution context so a checkpoint/resume sees the same retry count.
- backend/domain/workflow/internal/compose/node_runner.go:777-780
    if r.errProcessType == ExceptionBranch || ReturnDefaultData {
        output["isSuccess"] = true }
  => a fallback (branch or default data) marks the node output as *successful*
     for downstream branching while the raw error is still logged.

Transferable core: ONE policy tuple decides, per step, (1) how long a single
attempt may run, (2) how many extra attempts follow, (3) what happens when the
attempts are exhausted -- raise / route to an exception branch / return default
data -- and (4) a single ``is_success`` marker the caller branches on.

Contract invariants (asserted in tests/test_step_exception_policy.py):
1. default policy == one attempt, raises on failure (never a silent swallow).
2. max_retry=N -> at most N+1 attempts, and an early success stops retrying.
3. exhausted + THROW -> re-raises the original error, attempts == N+1.
4. exhausted + EXCEPTION_BRANCH -> no raise, route="exception_branch",
   is_success=True (a fallback counts as "node completed").
5. exhausted + RETURN_DEFAULT -> value is data_on_err, is_success=True, error kept.
6. timeout_ms>0 -> a hanging attempt is cut off and counts as a failed attempt.
7. interrupted steps are re-raised immediately and do NOT consume retries.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Optional

__all__ = [
    "ErrorProcessType",
    "StepTimeout",
    "ExceptionPolicy",
    "PolicyResult",
    "apply_policy",
]


class ErrorProcessType:
    """Three-state error strategy (mirrors vo.ErrorProcessType)."""

    THROW = "throw"                      # process_type 0: fail the node
    EXCEPTION_BRANCH = "exception_branch"  # route to the node's error branch
    RETURN_DEFAULT = "return_default"      # emit data_on_err and continue

    ALL = (THROW, EXCEPTION_BRANCH, RETURN_DEFAULT)


class StepTimeout(Exception):
    """A single attempt exceeded ``ExceptionPolicy.timeout_ms``."""


@dataclass(frozen=True)
class ExceptionPolicy:
    """Per-step exception policy tuple (TimeoutMS/MaxRetry/ProcessType/DataOnErr)."""

    timeout_ms: int = 0
    max_retry: int = 0
    process_type: str = ErrorProcessType.THROW
    data_on_err: Any = None

    def __post_init__(self) -> None:
        if self.process_type not in ErrorProcessType.ALL:
            raise ValueError("unknown process_type: %r" % (self.process_type,))
        for name in ("timeout_ms", "max_retry"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("%s must be a non-negative int" % name)

    @property
    def max_attempts(self) -> int:
        """Total attempts = retries + 1 (coze: `maxRetry > n` guard)."""
        return self.max_retry + 1

    @property
    def has_fallback(self) -> bool:
        """True when exhaustion must NOT raise (branch / default-data)."""
        return self.process_type != ErrorProcessType.THROW


@dataclass
class PolicyResult:
    """Outcome of one ``apply_policy`` call."""

    ok: bool
    value: Any = None
    attempts: int = 0
    error: Optional[str] = None
    route: str = ""
    is_success: bool = False

    def as_output(self) -> dict:
        """Node-shaped output carrying the coze ``isSuccess`` marker."""
        out: dict = {"isSuccess": self.is_success, "attempts": self.attempts}
        if self.route:
            out["route"] = self.route
        if not self.ok and self.error:
            out["error"] = self.error
        return out


_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="step-timeout")


def _call_once(fn: Callable[[], Any], timeout_ms: int) -> Any:
    """Run ``fn`` once, honouring an optional wall-clock budget.

    timeout_ms <= 0 means "no timeout" and calls ``fn`` inline (no thread hop).
    A timed-out attempt is abandoned in the worker thread: CPython cannot
    preempt it, exactly like the Go side cannot force-kill a stuck goroutine.
    """
    if timeout_ms <= 0:
        return fn()
    future = _POOL.submit(fn)
    try:
        return future.result(timeout=timeout_ms / 1000.0)
    except _FutureTimeout:
        raise StepTimeout("attempt exceeded %dms" % timeout_ms) from None


def apply_policy(
    policy: ExceptionPolicy,
    fn: Callable[[], Any],
    *,
    is_interrupt: Optional[Callable[[BaseException], bool]] = None,
) -> PolicyResult:
    """Run ``fn`` under ``policy`` and return a ``PolicyResult`` (never silent).

    ``is_interrupt`` (optional) classifies an exception as a pause/resume
    signal: those are re-raised at once and do not consume retries, matching
    coze's ``IsInterruptRerunError`` short-circuit in node_runner.go:630-633.
    """
    if not isinstance(policy, ExceptionPolicy):
        raise TypeError("policy must be an ExceptionPolicy")

    attempts = 0
    last_error: Optional[BaseException] = None

    while attempts < policy.max_attempts:
        attempts += 1
        try:
            return PolicyResult(
                ok=True,
                value=_call_once(fn, policy.timeout_ms),
                attempts=attempts,
                is_success=True,
            )
        except BaseException as exc:  # noqa: BLE001 - mirrored re-raise below
            if is_interrupt is not None and is_interrupt(exc):
                raise
            last_error = exc

    detail = "%s: %s" % (type(last_error).__name__, last_error)
    if not policy.has_fallback:
        assert last_error is not None
        raise last_error

    if policy.process_type == ErrorProcessType.EXCEPTION_BRANCH:
        return PolicyResult(
            ok=False, value=None, attempts=attempts, error=detail,
            route=ErrorProcessType.EXCEPTION_BRANCH, is_success=True,
        )
    return PolicyResult(
        ok=False, value=policy.data_on_err, attempts=attempts, error=detail,
        route=ErrorProcessType.RETURN_DEFAULT, is_success=True,
    )