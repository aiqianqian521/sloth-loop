"""Two-level (model + provider) circuit registry with exponential cooldown.

Distilled from TencentCloud/Octop v1.0.2 src/octop/infra/agents/providers/health.py
ModelHealthRegistry (lines 87-200): a model circuit and a provider circuit per
provider, exponential cooldown (base -> 5x -> max), half-open single-flight probe at
BOTH levels, and scope-routed failure recording. The upstream middleware
(middleware/model_failover.py) then only attempts a ref when is_routable is true
and begin_attempt reserves a slot.

This is the reliability-layer counterpart to the existing per-controller
CircuitBreaker (circuit_breaker.py): that breaker guards the loop controller;
this registry guards the outbound model fleet. They coexist; neither wraps the other.

Truth anchors (Octop v1.0.2, local mirror):
  providers/health.py:95-106  two dicts + base/max cooldown ctor
  providers/health.py:108-110 provider prefix
  providers/health.py:112-118 _active (expiry check)
  providers/health.py:120-126 is_routable (provider AND model)
  providers/health.py:128-146 begin_attempt (half-open single-flight x2)
  providers/health.py:148-153 _cooldown (<=1 base, ==2 5x, else max)
  providers/health.py:155-179 record_failure (scope routing)
  providers/health.py:181-185 record_success (close both levels)
  middleware/model_failover.py:99-116 candidate filtering + recording
  middleware/model_failover.py:118-145 attempt loop

Design notes:
* Pure in-process, injectable time_fn (default time.monotonic) for determinism.
* No I/O, no logging side-channels. Restart clears all circuits (upstream behaviour).
* NONE scope releases an expired half-open reservation but opens nothing
  (the endpoint answered -> a policy error must not quarantine it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Callable

from failure_scope import FailureScope, provider_of

__all__ = ["OpenCircuit", "ModelHealthRegistry"]


@dataclass
class OpenCircuit:
    """One circuit state: consecutive failures + an absolute open-until."""

    failures: int = 0
    open_until: float = 0.0
    half_open_in_flight: bool = False


@dataclass
class ModelHealthRegistry:
    """Process-local two-level circuit state, keyed by model ref / provider.

    Model refs are provider/model; provider_of extracts the prefix. time_fn is
    injected for determinism (default monotonic).
    """

    base_cooldown_s: float = 60.0
    max_cooldown_s: float = 900.0
    time_fn: Callable[[], float] = monotonic
    _models: dict = field(default_factory=dict)
    _providers: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.base_cooldown_s = max(0.0, float(self.base_cooldown_s))
        self.max_cooldown_s = max(self.base_cooldown_s, float(self.max_cooldown_s))

    # -- internals ---------------------------------------------------------

    def _active(self, circuits, key):
        """Return the circuit iff it is currently open (clock < open_until)."""
        circuit = circuits.get(key)
        if circuit is None:
            return None
        if self.time_fn() < circuit.open_until:
            return circuit
        return None

    def cooldown_for(self, failures: int) -> float:
        """Exponential backoff: <=1 -> base, ==2 -> 5x base (capped), else max."""
        if failures <= 1:
            return self.base_cooldown_s
        if failures == 2:
            return min(self.base_cooldown_s * 5.0, self.max_cooldown_s)
        return self.max_cooldown_s

    # -- routing -----------------------------------------------------------

    def is_routable(self, ref: str) -> bool:
        """True iff NEITHER the provider NOR the model circuit is open."""
        provider = provider_of(ref)
        return (
            self._active(self._providers, provider) is None
            and self._active(self._models, ref) is None
        )

    def begin_attempt(self, ref: str) -> bool:
        """Reserve a healthy or half-open slot for one attempt.

        Returns False when the provider/model circuit is open, or when a
        half-open probe is already in flight at either level (single-flight).
        On success, marks both levels half-open reservations in-flight when a
        circuit exists, so a concurrent caller cannot double-probe.
        """
        provider = provider_of(ref)
        if self._active(self._providers, provider) is not None:
            return False
        provider_circuit = self._providers.get(provider)
        if provider_circuit is not None and provider_circuit.half_open_in_flight:
            return False

        model_circuit = self._models.get(ref)
        if self._active(self._models, ref) is not None:
            return False
        if model_circuit is not None:
            if model_circuit.half_open_in_flight:
                return False
            model_circuit.half_open_in_flight = True
        if provider_circuit is not None:
            provider_circuit.half_open_in_flight = True
        return True

    # -- outcome recording -------------------------------------------------

    def record_failure(self, ref: str, *, scope: FailureScope, kind: str = "") -> None:
        """Open the model or provider circuit after an exhausted call.

        NONE scope records a success instead (the endpoint answered). A
        MODEL-scope failure clears a stale provider circuit; a PROVIDER-scope
        failure releases the model half-open reservation.
        """
        provider = provider_of(ref)
        if scope is FailureScope.NONE:
            self.record_success(ref)
            return
        if scope is FailureScope.MODEL:
            provider_circuit = self._providers.get(provider)
            if provider_circuit is not None and self.time_fn() >= provider_circuit.open_until:
                self._providers.pop(provider, None)
        else:  # PROVIDER
            model_circuit = self._models.get(ref)
            if model_circuit is not None:
                model_circuit.half_open_in_flight = False
        circuits = self._providers if scope is FailureScope.PROVIDER else self._models
        key = provider if scope is FailureScope.PROVIDER else ref
        previous = circuits.get(key)
        failures = (previous.failures if previous is not None else 0) + 1
        circuits[key] = OpenCircuit(
            failures=failures,
            open_until=self.time_fn() + self.cooldown_for(failures),
            half_open_in_flight=False,
        )

    def record_success(self, ref: str) -> None:
        """Close model AND provider health state after a successful call."""
        self._models.pop(ref, None)
        self._providers.pop(provider_of(ref), None)

    # -- introspection -----------------------------------------------------

    def snapshot(self, ref: str) -> dict:
        """Return a small, JSON-safe health snapshot for logs/UI."""
        provider = provider_of(ref)
        scope = FailureScope.NONE
        failures = 0
        open_for = 0.0
        if self._active(self._providers, provider) is not None:
            scope = FailureScope.PROVIDER
            failures = self._providers[provider].failures
            open_for = max(0.0, self._providers[provider].open_until - self.time_fn())
        elif self._active(self._models, ref) is not None:
            scope = FailureScope.MODEL
            failures = self._models[ref].failures
            open_for = max(0.0, self._models[ref].open_until - self.time_fn())
        return {
            "ref": ref,
            "provider": provider,
            "healthy": self.is_routable(ref),
            "open_scope": scope.value,
            "failures": failures,
            "open_for_s": round(open_for, 3),
        }
