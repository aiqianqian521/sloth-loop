"""sloth_engine stall watchdog (cycle-8 A4, distilled from qwen-code workflow-stall.ts).

Wall-clock no-progress watchdog for a delegated attempt (subagent / model round /
tool batch). A watchdog aborts an attempt that produces no observable progress
for ``stall_ms``; the timer is SUSPENDED while a tool is in flight so a
legitimately slow tool (a 90s build, a slow MCP call) is not misread as a stall.

``run_stall_resilient`` retries ONLY on a stall (bounded by ``max_attempts``);
every other failure (``MAX_TURNS``/``TIMEOUT``/``ERROR``/deterministic errors)
propagates immediately, since a retry cannot fix a deterministic outcome.

Contract notes (additive, contract-neutral):
- ``stall_ms <= 0`` disables the watchdog (inert handle + a single raw attempt).
- Arm-on-first-activity: ``start()`` / ``activity()`` arm the timer; the timer is
  reset on every activity; ``tool_started`` / ``tool_finished`` hold then re-arm.
- The fire path sets ``abort_event`` and calls the optional ``on_stall`` hook; the
  attempt function observes ``abort_event`` to unwind (or the wrapper raises on
  ``stalled`` after the attempt returns/throws).

Source of the design (V2 file:行段 evidence lives in the distillation entry):
  qwen-code packages/core/src/agents/runtime/workflow-stall.ts
    :DEFAULT_STALL_MS / :attachStallWatchdog / :runStallResilient
"""
from __future__ import annotations

import contextlib
import os
import threading
from typing import Callable, Optional

DEFAULT_STALL_SECONDS = 180.0
MAX_STALL_ATTEMPTS = 3
STALL_SECONDS_ENV = "LOOP_STALL_SECONDS"


def resolve_stall_ms(
    per_call=None,
    env=None,
    default_ms: Optional[int] = None,
) -> int:
    """Resolve the effective stall timeout, in milliseconds.

    Precedence: per-call override (>0 wins; explicit 0 disables) -> env
    ``LOOP_STALL_SECONDS`` (seconds; ``"0"`` disables) -> ``default_ms``
    (falling back to ``DEFAULT_STALL_SECONDS * 1000``). A non-finite or negative
    per-call value falls through to the next source (a negative is a caller bug).
    """
    if env is None:
        env = os.environ
    if per_call is not None:
        try:
            v = float(per_call)
        except (TypeError, ValueError):
            v = None
        if v is not None and v == v and abs(v) != float("inf"):
            if v == 0:
                return 0
            if v > 0:
                return int(v)
    raw = (env.get(STALL_SECONDS_ENV) or "").strip()
    if raw:
        if raw == "0":
            return 0
        try:
            sec = float(raw)
        except ValueError:
            sec = 0.0
        if sec > 0:
            return int(sec * 1000)
    if default_ms is None:
        default_ms = int(DEFAULT_STALL_SECONDS * 1000)
    return int(default_ms)


class StallWatchdog:
    """A wall-clock no-progress watchdog with tool-in-flight suspension."""

    def __init__(
        self,
        stall_ms,
        on_stall: Optional[Callable[[], None]] = None,
        timer_factory: Optional[Callable[[float, Callable[[], None]], object]] = None,
    ) -> None:
        self._stall_ms = int(stall_ms or 0)
        self._on_stall = on_stall
        self._timer_factory = timer_factory
        self._lock = threading.RLock()
        self._timer = None
        self._in_flight = 0
        self._fired = False
        self._disposed = False
        self.abort_event = threading.Event()

    # ---- introspection -------------------------------------------------
    @property
    def stall_ms(self) -> int:
        return self._stall_ms

    @property
    def stalled(self) -> bool:
        with self._lock:
            return self._fired

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    # ---- lifecycle -----------------------------------------------------
    def start(self) -> "StallWatchdog":
        """Arm the watchdog (no-op when disabled/fired/disposed)."""
        self._arm()
        return self

    def activity(self) -> None:
        """Record observable progress: reset (re-arm) the stall timer."""
        self._arm()

    def tool_started(self) -> None:
        """Hold the timer: a tool is now in flight (never a stall while held)."""
        with self._lock:
            self._in_flight += 1
            self._clear()

    def tool_finished(self) -> None:
        """Release one in-flight tool; re-arm once the count returns to zero."""
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
        self._arm()

    @contextlib.contextmanager
    def hold(self):
        """Context manager wrapping ``tool_started`` / ``tool_finished``."""
        self.tool_started()
        try:
            yield self
        finally:
            self.tool_finished()

    def dispose(self) -> None:
        """Clear the timer and detach. Idempotent; safe in a ``finally``."""
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            self._clear()

    # ---- internals -----------------------------------------------------
    def _clear(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.cancel()

    def _make_timer(self):
        if self._timer_factory is not None:
            return self._timer_factory(self._stall_ms / 1000.0, self._fire)
        timer = threading.Timer(self._stall_ms / 1000.0, self._fire)
        timer.daemon = True
        return timer

    def _arm(self) -> None:
        with self._lock:
            if self._disposed or self._fired or self._stall_ms <= 0:
                return
            self._clear()
            if self._in_flight > 0:
                return
            timer = self._make_timer()
            self._timer = timer
            timer.start()

    def _fire(self) -> None:
        with self._lock:
            if self._disposed or self._fired:
                return
            self._fired = True
            self._timer = None
        self.abort_event.set()
        if self._on_stall is not None:
            self._on_stall()


def run_stall_resilient(
    attempt_fn: Callable[[StallWatchdog], object],
    stall_ms: int,
    max_attempts: int = MAX_STALL_ATTEMPTS,
    label: Optional[str] = None,
    is_parent_cancelled: Optional[Callable[[], bool]] = None,
    watchdog_factory: Optional[Callable[[int], StallWatchdog]] = None,
):
    """Run ``attempt_fn(watchdog)`` under a stall watchdog, retrying on stall only.

    - ``stall_ms <= 0`` -> a single raw attempt with an inert watchdog.
    - A stall is retried up to ``max_attempts``; persistent stall raises
      ``RuntimeError`` (chained from the last attempt's exception).
    - ``is_parent_cancelled()`` (checked on failure) takes priority over retry.
    - Any non-stall failure propagates immediately, unretried.
    """
    if stall_ms <= 0:
        return attempt_fn(StallWatchdog(0))

    factory = watchdog_factory or (lambda ms: StallWatchdog(ms))
    attempt = 0
    while True:
        attempt += 1
        watchdog = factory(stall_ms)
        watchdog.start()
        try:
            return attempt_fn(watchdog)
        except BaseException as err:
            if is_parent_cancelled is not None and is_parent_cancelled():
                raise
            if watchdog.stalled:
                if attempt < max_attempts:
                    continue
                raise RuntimeError(
                    "attempt %r stalled on all %d attempts "
                    "(no progress for %dms each)"
                    % (label or "attempt", max_attempts, stall_ms)
                ) from err
            raise
        finally:
            watchdog.dispose()