"""Failure-scope classification for two-level circuit breaking.

Distilled from TencentCloud/Octop v1.0.2
``src/octop/infra/agents/providers/health.py`` (``classify_model_failure`` +
``ModelHealthRegistry``): a failed model call is classified into a *failure
scope* so the controller can quarantine just the model, the whole provider, or
nothing at all.  This module keeps that idea framework-free: a pure classifier
here, and the stateful two-level breaker in ``circuit_breaker.py``.

Truth anchors (Octop v1.0.2, local mirror):
  providers/health.py:24-27   FailureScope(StrEnum) NONE/MODEL/PROVIDER
  providers/health.py:44-50   _PROVIDER_FAILURES / _MODEL_FAILURES sets
  providers/health.py:51-57   _MODEL_NOT_FOUND_MARKERS
  providers/health.py:60-84   classify_model_failure
  providers/health.py:148-153 exponential cooldown (base -> 5x -> max)
  providers/health.py:155-179 record_failure scope routing

loop has no provider-i18n error taxonomy, so classification works off the
exception type/name plus a small set of substring markers (same mechanism,
loop-local vocabulary).  Everything is pure and deterministic: no I/O, no
clock, no globals.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

__all__ = [
    "FailureScope",
    "FailureDecision",
    "PROVIDER_FAILURE_MARKERS",
    "MODEL_FAILURE_MARKERS",
    "MODEL_NOT_FOUND_MARKERS",
    "classify_failure",
    "provider_of",
]


class FailureScope(str, Enum):
    """How far a failure should quarantine the routing space.

    ``NONE``  the endpoint answered; retrying/other models will not help the
              *health* state, so nothing is opened (a policy/input error).
    ``MODEL`` only the concrete model ref is unhealthy.
    ``PROVIDER`` every model behind the provider prefix is unhealthy.
    """

    NONE = "none"
    MODEL = "model"
    PROVIDER = "provider"


@dataclass(frozen=True)
class FailureDecision:
    """Result of :func:`classify_failure`: may we fail over, how, how wide."""

    failover: bool
    kind: str
    scope: FailureScope


# Substring markers, lower-cased.  Kept as module constants so callers/tests can
# assert against a single source of truth (Octop used error-code enums; loop
# has no such taxonomy yet, so markers are the portable equivalent).
PROVIDER_FAILURE_MARKERS: Final[tuple[str, ...]] = (
    "auth",
    "unauthorized",
    "authentication",
    "invalid api key",
    "insufficient balance",
    "quota exceeded",
    "rate limit",
    "ratelimit",
    "429",
    "billing",
)
MODEL_FAILURE_MARKERS: Final[tuple[str, ...]] = (
    "model call failed",
    "provider unavailable",
    "stream stall",
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "502",
    "503",
    "504",
)
MODEL_NOT_FOUND_MARKERS: Final[tuple[str, ...]] = (
    "model not found",
    "model_not_found",
    "unknown model",
    "does not exist",
    "no such model",
)


def provider_of(ref: str) -> str:
    """Return the provider prefix of a model ref (``provider/model`` -> provider).

    A ref with no ``/`` is its own provider, mirroring Octop's
    ``ModelHealthRegistry._provider`` (``ref.partition("/")[0]``).
    """
    return str(ref).partition("/")[0]


def _matches(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(n in haystack for n in needles)


def classify_failure(
    exc: BaseException | None = None,
    *,
    detail: str | None = None,
) -> FailureDecision:
    """Classify a failed model call into a :class:`FailureScope`.

    Parameters
    ----------
    exc:
        The raised exception (optional).  Its type name and ``str()`` feed the
        classification.
    detail:
        Explicit detail text.  When given it is authoritative for marker
        matching (lets a caller classify a message that was already unwrapped);
        the exception's ``str()`` is only used when ``detail`` is ``None``.

    Ordering (mirrors Octop ``classify_model_failure``):
      1. an explicit "model not found" marker -> MODEL (fail over to another
         model; the provider itself is fine);
      2. a provider-scope marker -> PROVIDER;
      3. a model-scope marker -> MODEL;
      4. a bare ``TimeoutError`` / ``ConnectionError`` -> MODEL;
      5. anything else -> NONE, ``failover=False``.
    """
    explicit = detail is not None
    raw = detail if explicit else ("" if exc is None else str(exc))
    lower = raw.lower()

    if _matches(lower, MODEL_NOT_FOUND_MARKERS):
        return FailureDecision(True, "model_not_found", FailureScope.MODEL)
    if _matches(lower, PROVIDER_FAILURE_MARKERS):
        return FailureDecision(True, "provider_error", FailureScope.PROVIDER)
    if _matches(lower, MODEL_FAILURE_MARKERS):
        return FailureDecision(True, "model_error", FailureScope.MODEL)
    # The exception *type* is only consulted when no explicit detail was given;
    # an explicit detail string is authoritative (it may be an already-unwrapped
    # message that legitimately says "bad request body" even for a TimeoutError).
    if not explicit and isinstance(exc, (TimeoutError, ConnectionError)):
        return FailureDecision(True, type(exc).__name__.lower(), FailureScope.MODEL)
    return FailureDecision(False, "request_error", FailureScope.NONE)
