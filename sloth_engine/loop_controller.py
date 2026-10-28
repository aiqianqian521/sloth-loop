"""Small policy boundary for loop continuation and breaker accounting."""

from __future__ import annotations

from circuit_breaker import CircuitBreaker


class LoopController:
    """Own round admission and execution outcome policy.

    Persistence remains the orchestrator's responsibility; this class only
    makes the safety decision deterministic and independently testable.
    """

    def __init__(self, breaker: CircuitBreaker, max_rounds: int,
                 no_progress_stop: int):
        self.breaker = breaker
        self.max_rounds = max(1, int(max_rounds))
        self.no_progress_stop = max(1, int(no_progress_stop))

    def allow_round(self, rounds_completed: int) -> bool:
        return rounds_completed < self.max_rounds and self.breaker.allow_request()

    def record_execution(self, status: str) -> str:
        if status == "error":
            return self.breaker.record_failure()
        self.breaker.record_success()
        return self.breaker.state

