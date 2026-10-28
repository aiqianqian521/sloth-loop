"""Backpressure vs failure separation (distilled from vectorize-io/hindsight).

Provenance (L3 cycle-4 A4, adopted candidate C2):
  source: <WORKSPACE_ROOT>/other_project/999-hindsight-core
  evidence:
    - hindsight-api-slim/hindsight_api/worker/exceptions.py:25-38
      (DeferOperation: "requeue ... without counting as a retry";
       "this is not a failure: retry_count is not incremented and
        error_message is not written")
    - hindsight-api-slim/hindsight_api/worker/backpressure.py:36-50
      (is_store_backpressure: walk __cause__/__context__ chain, match
       the store's own rejection text)
    - hindsight-api-slim/hindsight_api/worker/poller.py:1228-1244
      (backpressure reroute branch sits BEFORE the failure path)

Why loop needs it: run_loop treated every non-ok round as a failure and
fed it to the circuit breaker (run_loop.py:243-252 / 553-561). A transient
"come back later" (a deferred op) therefore consumed the consecutive-error
budget and could open the breaker: a false failure eats a real retry budget.

Design (minimal slice, additive, no new runtime dependency):
  - DeferOperation: a NON-failure signal carrying a retry_after hint.
    Raising it (or returning DEFER_STATUS) never increments the breaker.
  - is_backpressure(): the whole classification policy lives here as one
    pure function; the loop only feeds it the round status + error text.
    Keeping it central means the pre-commit backpressure surface is the
    same surface the ingestion tests exercise.
  - Fail-closed: only an EXPLICIT defer signal is treated as backpressure.
    Nothing is inferred from a bare status; a generic "error" stays a
    failure. A string-classified defer is opt-in.

This module imports nothing from sloth_engine and does no I/O, so it stays
safe to import from the checkpoint/write path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The status a round yields when it is merely deferred (not failed).
DEFER_STATUS = "deferred"

# Classifier verdicts (string constants, stable for event/log payloads).
DEFER = "defer"
FAIL = "fail"

# Substrings (lower-cased) that mark a store/service telling us to come
# back later rather than a genuine failure. Mirrors hindsight's
# is_store_backpressure text set + loop's API-ish failure surface.
_BACKPRESSURE_MARKERS = (
    "backpressure",
    "back-pressure",
    "come back later",
    "try again later",
    "retry later",
    "requeue",
    "indexing is behind",
    "indexing behind",
    "fold behind",
    "write bound",
    "writes are shed",
    "shed",
    "unavailable",
    "429",
    "rate limit",
    "rate-limit",
    "too many requests",
    "temporarily unavailable",
    "temporarily overloaded",
    "overloaded",
    "throttl",
    "slow down",
)

_RETRY_AFTER_RE = re.compile(r"retry[_\- ]?after[:= ]+([0-9]+(?:\.[0-9]+)?)")


class DeferOperation(Exception):
    """Raised by an execution adapter to defer a round instead of failing it.

    Raising this (or returning a result whose status is ``DEFER_STATUS``)
    signals backpressure: the work should be retried later and must NOT be
    counted as a failure by the circuit breaker (cf. hindsight
    DeferOperation, worker/exceptions.py:25-38).

    ``retry_after`` is an optional seconds hint; ``reason`` is a short label
    for the audit trail. Neither mutates any failure budget.
    """

    def __init__(self, reason: str = "deferred", retry_after: float | None = None):
        super().__init__(reason)
        self.reason = reason or "deferred"
        self.retry_after = retry_after


@dataclass(frozen=True)
class BackpressureVerdict:
    """Result of classifying one round outcome."""

    deferred: bool          # True => backpressure (do NOT count as failure)
    reason: str = ""        # short machine reason for the defer
    retry_after: float | None = None
    source: str = ""        # "status" | "exception" | "text" | ""

    @property
    def is_failure(self) -> bool:
        return not self.deferred


def is_backpressure(value, *, text: str | None = None) -> BackpressureVerdict:
    """Classify ``value`` (+ optional ``text``) as defer vs fail.

    Accepted inputs (any one is enough to defer):
      * ``DeferOperation`` exception (or subclass)
      * a status string equal to :data:`DEFER_STATUS`
      * ``text`` containing a backpressure marker (e.g. a store's
        "indexing is behind"); this mirrors hindsight's
        ``is_store_backpressure`` string match.

    Fail-closed contract: anything not explicitly recognised is a failure.
    The function never raises and never does I/O.
    """
    if isinstance(value, DeferOperation):
        return BackpressureVerdict(
            True, reason=value.reason, retry_after=value.retry_after,
            source="exception")

    if isinstance(value, str) and value.strip().lower() == DEFER_STATUS:
        return BackpressureVerdict(True, reason="status=deferred", source="status")

    blob = ""
    if isinstance(text, str):
        blob = text
    elif isinstance(value, BaseException) and not isinstance(value, DeferOperation):
        blob = str(value)
    if blob:
        low = blob.lower()
        for marker in _BACKPRESSURE_MARKERS:
            if marker in low:
                m = _RETRY_AFTER_RE.search(low)
                ra = float(m.group(1)) if m else None
                return BackpressureVerdict(
                    True, reason="marker=%s" % marker, retry_after=ra, source="text")

    return BackpressureVerdict(False)


def classify_round(*, status=None, execution_failed: bool | None = None,
                   error=None, text: str | None = None) -> BackpressureVerdict:
    """Classify a round's outcome for breaker accounting.

    A round is DEFERRED (non-failure) iff an explicit defer signal is present.
    ``execution_failed`` only means "the adapter reported a non-ok status";
    it does NOT by itself decide defer vs fail -- the string/exception signal
    does. That is the fail-closed split later adopted by the loop.
    """
    verdict = is_backpressure(status, text=text)
    if verdict.deferred:
        return verdict
    if isinstance(error, DeferOperation):
        return is_backpressure(error)
    if error is not None and not isinstance(error, BaseException):
        return is_backpressure(status, text=str(error))
    if error is not None:
        return is_backpressure(error)
    if isinstance(text, str):
        return is_backpressure(status, text=text)
    return BackpressureVerdict(False)
