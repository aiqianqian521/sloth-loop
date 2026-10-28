"""Dual-window quota snapshot + fail-soft fetch + idempotent credit consume.

Distilled from lobehub-canary (TypeScript desktop app) -- see
docs/knowledge-distillation/agent-orchestration/
2026-10-22-lobehub-codex-dual-window-quota-snapshot-and-idempotent-consume.md

Source design (apps/desktop/src/main/modules/heterogeneousAgent/codexQuota.ts):
- :18-20   CODEX_PRIMARY_WINDOW_MINUTES = 5 * 60 (5h burst window),
           CODEX_SECONDARY_WINDOW_MINUTES = 7 * 24 * 60 (7d sustained window),
           RESET_CONSUME_TIMEOUT_MS = 30_000
- :115-122 errorSnapshot(): a failed fetch returns
           {status:'error', error, updatedAt, provider, session:null, weekly:null}
           instead of throwing into the caller.
- :348-364 mapRpcWindow(): a window is dropped when usedPercent is missing or
           non-finite; otherwise usedPercent = Math.min(100, Math.max(0, raw))
           and windowDurationMins falls back to the nominal duration.
- :372-374 both windows unusable -> the whole snapshot is null (no fake zeros).
- :596-600 the outer fetch wraps everything in try/catch -> error snapshot.
- :613-641 consume(): the idempotency key is mandatory (blank -> throw), is sent
           as redeem_request_id, is reused verbatim when the RPC path fails and
           the HTTP fallback runs, and the call carries its own 30s timeout.

Transferable core: budget control as a *snapshot over two nested windows*
(short burst window + long sustained window), with (a) clamping so a
misreported percentage can never exceed the cap, (b) degrade-to-error-snapshot
instead of raising, and (c) an idempotent consume path keyed by a
caller-supplied idempotency key with its own timeout.

Contract invariants (asserted in tests/test_quota_window.py):
1. used_percent is clamped into [0, 100]; a non-finite/missing value drops the
   window instead of silently reading as 0.
2. resets_at normalises seconds vs milliseconds (< 1e10 -> *1000), like
   parseCreditTimestamp; ISO-8601 strings are accepted too.
3. both windows unusable -> from_raw() returns None (never a fake 0% snapshot).
4. fetch failure -> last-known snapshot (degraded=True) or an error snapshot;
   resolve_snapshot() never raises.
5. exhausted/next_reset_at read off the per-window percentages.
6. CreditLedger.consume(): blank key rejected; same key -> fn called once;
   timeout -> status "timeout" and the key is NOT cached (the caller-supplied
   key stays the durable guard, so a retry is server-side idempotent).
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

__all__ = [
    "PRIMARY_WINDOW_MINUTES",
    "SECONDARY_WINDOW_MINUTES",
    "RESET_CONSUME_TIMEOUT_MS",
    "QuotaWindow",
    "QuotaSnapshot",
    "ConsumeOutcome",
    "CreditLedger",
    "map_window",
    "from_raw",
    "error_snapshot",
    "resolve_snapshot",
]

PRIMARY_WINDOW_MINUTES = 5 * 60          # 5h burst window
SECONDARY_WINDOW_MINUTES = 7 * 24 * 60   # 7d sustained window
RESET_CONSUME_TIMEOUT_MS = 30_000

STATUS_OK = "ok"
STATUS_ERROR = "error"

_SECONDS_CUTOFF = 10_000_000_000


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Normalise seconds / milliseconds / ISO-8601 into epoch milliseconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return int(number * 1000) if number < _SECONDS_CUTOFF else int(number)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            number = None
        if number is not None:
            if not math.isfinite(number):
                return None
            return int(number * 1000) if number < _SECONDS_CUTOFF else int(number)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    return None


def _pick(raw: dict, *names: str) -> Any:
    for name in names:
        if name in raw:
            return raw[name]
    return None


@dataclass(frozen=True)
class QuotaWindow:
    """One quota window of a provider snapshot."""

    label: str
    duration_minutes: int
    used_percent: float
    resets_at: Optional[int] = None  # epoch ms

    @property
    def exhausted(self) -> bool:
        return self.used_percent >= 100.0

    @property
    def remaining_percent(self) -> float:
        return max(0.0, 100.0 - self.used_percent)


def map_window(
    raw: Any,
    *,
    label: str,
    default_duration_minutes: int,
) -> Optional[QuotaWindow]:
    """Map one raw window; return None when it carries no usable percentage."""
    if not isinstance(raw, dict):
        return None
    used = _pick(raw, "usedPercent", "used_percent")
    if isinstance(used, bool) or not isinstance(used, (int, float)):
        return None
    used = float(used)
    if not math.isfinite(used):
        return None
    duration = _pick(raw, "windowDurationMins", "window_duration_minutes")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) \
            or not math.isfinite(float(duration)) or float(duration) <= 0:
        duration = default_duration_minutes
    return QuotaWindow(
        label=label,
        duration_minutes=int(duration),
        used_percent=min(100.0, max(0.0, used)),
        resets_at=_to_epoch_ms(_pick(raw, "resetsAt", "resets_at")),
    )


@dataclass(frozen=True)
class QuotaSnapshot:
    """Provider budget snapshot (status "ok" or "error")."""

    provider: str
    status: str
    updated_at: int
    windows: tuple = ()
    error: Optional[str] = None
    degraded: bool = False

    def window(self, label: str) -> Optional[QuotaWindow]:
        for item in self.windows:
            if item.label == label:
                return item
        return None

    @property
    def exhausted(self) -> bool:
        return any(item.exhausted for item in self.windows)

    def next_reset_at(self) -> Optional[int]:
        """Earliest reset among *exhausted* windows -> when the block lifts."""
        candidates = [item.resets_at for item in self.windows
                      if item.exhausted and item.resets_at is not None]
        return min(candidates) if candidates else None


def error_snapshot(provider: str, message: str, *,
                   now: Optional[int] = None, degraded: bool = True) -> QuotaSnapshot:
    """Fail-soft fallback: an error snapshot instead of raising."""
    return QuotaSnapshot(
        provider=provider,
        status=STATUS_ERROR,
        updated_at=int(now if now is not None else 0),
        error=str(message),
        degraded=degraded,
    )


def from_raw(
    provider: str,
    raw: Any,
    *,
    now: Optional[int] = None,
    primary_minutes: int = PRIMARY_WINDOW_MINUTES,
    secondary_minutes: int = SECONDARY_WINDOW_MINUTES,
) -> Optional[QuotaSnapshot]:
    """Build a snapshot from a {"primary": {...}, "secondary": {...}} payload.

    Returns None when neither window is usable (mirrors the TS `if (!primary &&
    !secondary) return null`), so a broken payload can never masquerade as 0%.
    """
    if not isinstance(raw, dict):
        return None
    primary = map_window(raw.get("primary"), label="primary",
                         default_duration_minutes=primary_minutes)
    secondary = map_window(raw.get("secondary"), label="secondary",
                           default_duration_minutes=secondary_minutes)
    windows = tuple(item for item in (primary, secondary) if item is not None)
    if not windows:
        return None
    return QuotaSnapshot(
        provider=provider,
        status=STATUS_OK,
        updated_at=int(now if now is not None else 0),
        windows=windows,
    )


def resolve_snapshot(
    fetch: Callable[[], Any],
    *,
    provider: str,
    now: Optional[int] = None,
    cache: Optional[QuotaSnapshot] = None,
    primary_minutes: int = PRIMARY_WINDOW_MINUTES,
    secondary_minutes: int = SECONDARY_WINDOW_MINUTES,
) -> QuotaSnapshot:
    """Fetch a snapshot without ever raising.

    A fetch that raises or yields no usable window degrades to ``cache``
    (marked degraded=True) or, with no cache, to an error snapshot.
    """
    try:
        raw = fetch()
    except Exception as exc:  # noqa: BLE001 - degrade-to-snapshot is the contract
        if cache is not None:
            return QuotaSnapshot(
                provider=cache.provider, status=cache.status,
                updated_at=cache.updated_at, windows=cache.windows,
                error="%s: %s" % (type(exc).__name__, exc), degraded=True,
            )
        return error_snapshot(provider, "%s: %s" % (type(exc).__name__, exc), now=now)

    if raw is None:
        if cache is not None:
            return QuotaSnapshot(
                provider=cache.provider, status=cache.status,
                updated_at=cache.updated_at, windows=cache.windows,
                error="fetch returned no usable window", degraded=True,
            )
        return error_snapshot(provider, "fetch returned no usable window", now=now)

    if isinstance(raw, QuotaSnapshot):
        return raw

    snapshot = from_raw(provider, raw, now=now, primary_minutes=primary_minutes,
                        secondary_minutes=secondary_minutes)
    if snapshot is None:
        if cache is not None:
            return QuotaSnapshot(
                provider=cache.provider, status=cache.status,
                updated_at=cache.updated_at, windows=cache.windows,
                error="fetch returned no usable window", degraded=True,
            )
        return error_snapshot(provider, "fetch returned no usable window", now=now)
    return snapshot


@dataclass
class ConsumeOutcome:
    """Result of one idempotent credit-consume attempt."""

    key: str
    status: str                       # "consumed" | "timeout" | "error"
    outcome: Any = None
    detail: Optional[str] = None
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "consumed"


_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quota-consume")


class CreditLedger:
    """Idempotent reset-credit consumption keyed by a caller idempotency key.

    Mirrors codexQuota.ts:613-641 -- the key is mandatory, the same key is
    reused across transport fallbacks, and a timeout leaves the outcome unknown
    so the key is NOT cached (the server-side key stays the durable guard).
    """

    def __init__(self, timeout_ms: int = RESET_CONSUME_TIMEOUT_MS) -> None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms < 0:
            raise ValueError("timeout_ms must be a non-negative int")
        self.timeout_ms = timeout_ms
        self._results: dict = {}

    def known(self, key: str) -> bool:
        return key in self._results

    def consume(self, key: str, fn: Callable[[str], Any]) -> ConsumeOutcome:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("quota reset idempotency key is required")
        key = key.strip()
        if key in self._results:
            return ConsumeOutcome(key=key, status="consumed",
                                  outcome=self._results[key], cached=True)

        call = lambda: fn(key)  # noqa: E731 - keep the key flowing to the transport
        try:
            if self.timeout_ms <= 0:
                outcome = call()
            else:
                future = _POOL.submit(call)
                outcome = future.result(timeout=self.timeout_ms / 1000.0)
        except _FutureTimeout:
            return ConsumeOutcome(key=key, status="timeout",
                                  detail="consume exceeded %dms" % self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 - surfaced as a status, not raised
            return ConsumeOutcome(key=key, status="error",
                                  detail="%s: %s" % (type(exc).__name__, exc))

        self._results[key] = outcome
        return ConsumeOutcome(key=key, status="consumed", outcome=outcome)