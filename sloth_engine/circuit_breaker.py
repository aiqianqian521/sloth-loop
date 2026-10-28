"""Three-state circuit breaker used by the Loop controller (W1).

The old controller only counted consecutive failures in a local integer.  This
module makes the safety semantics explicit and testable without coupling them
to SQLite or the OODA implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic, time
from typing import Any, Callable, Literal, Mapping

CircuitState = Literal["CLOSED", "OPEN", "HALF_OPEN"]

OnTransition = Callable[[CircuitState, CircuitState, Mapping[str, Any]], None]

_log = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    """Failure gate with CLOSED -> OPEN -> HALF_OPEN transitions."""

    failure_threshold: int = 2
    cooldown_seconds: float = 60.0
    state: CircuitState = "CLOSED"
    consecutive_failures: int = 0
    opened_at: float | None = None
    opened_at_wall: float | None = None
    _probe_in_flight: bool = False
    # W1-CB-01 Slice 2: HALF_OPEN closes only after N consecutive probe
    # successes (default 1 keeps the legacy single-probe close); the counter
    # resets on any failure and persists via snapshot/restore.
    probe_success_threshold: int = 1
    consecutive_probe_success: int = 0
    on_transition: OnTransition | None = None

    def __post_init__(self) -> None:
        self.failure_threshold = max(1, int(self.failure_threshold))
        self.cooldown_seconds = max(0.0, float(self.cooldown_seconds))
        self.probe_success_threshold = max(1, int(self.probe_success_threshold))
        self.consecutive_probe_success = max(
            0, int(self.consecutive_probe_success))

    def _notify(self, old: CircuitState, new: CircuitState, *, trigger: str) -> None:
        """Emit a transition via the outbound port. No I/O here.

        The binding (set at composition root) is an append-only sink; its I/O
        failures must never pierce this safety-decision primitive, so the call
        is wrapped defensively (the staged-slot binding itself does no I/O).
        """
        if self.on_transition is None or old == new:
            return
        try:
            self.on_transition(old, new, {
                "trigger": trigger,
                "consecutive_failures": self.consecutive_failures,
                "failure_threshold": self.failure_threshold,
                "opened_at_wall": self.opened_at_wall,
                "consecutive_probe_success": self.consecutive_probe_success,
            })
        except Exception:
            _log.warning("circuit on_transition callback raised (trigger=%s)",
                         trigger, exc_info=True)

    def allow_request(self, now: float | None = None) -> bool:
        """Return whether a task may execute, advancing OPEN if cooled down."""
        explicit_clock = now is not None
        now = monotonic() if now is None else now
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.opened_at_wall is not None and not explicit_clock:
                elapsed = time() - self.opened_at_wall
            else:
                elapsed = now - (self.opened_at or now)
            if self.opened_at is None or elapsed < self.cooldown_seconds:
                return False
            old = self.state
            self.state = "HALF_OPEN"
            self._probe_in_flight = True
            self._notify(old, "HALF_OPEN", trigger="allow_request")
            return True
        # HALF_OPEN admits exactly one probe until it records a result.
        if self._probe_in_flight:
            return False
        self._probe_in_flight = True
        return True

    def record_failure(self, now: float | None = None) -> CircuitState:
        """Record a failed execution and return the resulting state."""
        now = monotonic() if now is None else now
        self._probe_in_flight = False
        # W1-CB-01 Slice 2: any failure resets the probe-success counter so the
        # N-close must restart from a fresh probe sequence.
        self.consecutive_probe_success = 0
        old = self.state
        if self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.opened_at = now
            self.opened_at_wall = time()
            self.consecutive_failures = self.failure_threshold
            self._notify(old, "OPEN", trigger="record_failure")
            return self.state
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "OPEN"
            self.opened_at = now
            self.opened_at_wall = time()
            self._notify(old, "OPEN", trigger="record_failure")
        return self.state

    def record_success(self) -> CircuitState:
        """Record a successful execution; close only after N HALF_OPEN probes.

        A bare record_success on an OPEN breaker is fail-closed: the breaker
        stays OPEN (it must admit a probe via allow_request after cooldown
        first). In HALF_OPEN each success increments the probe-success counter;
        on reaching probe_success_threshold the breaker closes via the port.
        Intermediate successes keep the state HALF_OPEN (old==new) so no audit
        noise is emitted, and _probe_in_flight is cleared so allow_request
        admits the next probe.
        """
        old = self.state
        if self.state == "HALF_OPEN":
            self.consecutive_probe_success += 1
            self._probe_in_flight = False
            if self.consecutive_probe_success >= self.probe_success_threshold:
                self.state = "CLOSED"
                self.consecutive_failures = 0
                self.opened_at = None
                self.opened_at_wall = None
                # _notify BEFORE the counter reset so the close audit event
                # records the N that actually closed (not the post-reset 0).
                self._notify(old, "CLOSED", trigger="record_success")
                self.consecutive_probe_success = 0
            return self.state
        if self.state == "CLOSED":
            self.consecutive_failures = 0
            self.consecutive_probe_success = 0
            return self.state
        return self.state

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "opened_at": self.opened_at,
            "opened_at_wall": self.opened_at_wall,
            "probe_in_flight": self._probe_in_flight,
            "probe_success_threshold": self.probe_success_threshold,
            "consecutive_probe_success": self.consecutive_probe_success,
        }

    def restore(self, snapshot: dict) -> None:
        """Restore durable state from a checkpoint/event snapshot."""
        state = snapshot.get("state", "CLOSED")
        if state not in {"CLOSED", "OPEN", "HALF_OPEN"}:
            raise ValueError(f"invalid circuit state: {state}")
        self.state = state
        self.consecutive_failures = max(0, int(snapshot.get("consecutive_failures", 0)))
        self.failure_threshold = max(1, int(snapshot.get("failure_threshold", self.failure_threshold)))
        self.cooldown_seconds = max(0.0, float(snapshot.get("cooldown_seconds", self.cooldown_seconds)))
        self.opened_at_wall = snapshot.get("opened_at_wall")
        if self.opened_at_wall is not None:
            elapsed = max(0.0, time() - float(self.opened_at_wall))
            self.opened_at = monotonic() - elapsed
        else:
            self.opened_at = snapshot.get("opened_at")
        self._probe_in_flight = bool(snapshot.get("probe_in_flight", False))
        self.probe_success_threshold = max(
            1, int(snapshot.get("probe_success_threshold", self.probe_success_threshold)))
        self.consecutive_probe_success = max(
            0, int(snapshot.get("consecutive_probe_success", 0)))
