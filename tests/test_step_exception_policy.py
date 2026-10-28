# -*- coding: utf-8 -*-
"""L3 cycle-9 A4 - step-level exception policy (coze-studio distillation).

Provenance (distilled from coze-studio Go backend):
  backend/domain/workflow/internal/schema/node_schema.go:87-92
    ExceptionConfig{TimeoutMS, MaxRetry, ProcessType, DataOnErr}
  backend/domain/workflow/internal/compose/node_runner.go:616-650
    retry loop -> attempts = MaxRetry + 1; interrupt short-circuits
  backend/domain/workflow/internal/compose/node_runner.go:777-780
    ExceptionBranch/ReturnDefaultData -> output["isSuccess"] = True

Contract under test (behavioural, not source-grep):
  1. default policy -> exactly one attempt, raises on failure.
  2. max_retry=N -> at most N+1 attempts; early success stops retrying.
  3. exhausted + THROW -> re-raises the original error.
  4. exhausted + EXCEPTION_BRANCH -> no raise, route + is_success=True.
  5. exhausted + RETURN_DEFAULT -> data_on_err value + is_success=True.
  6. timeout_ms>0 -> a hanging attempt is cut off and consumes an attempt.
  7. interrupt -> re-raised immediately, retries untouched.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from step_exception_policy import (  # noqa: E402
    ErrorProcessType,
    ExceptionPolicy,
    StepTimeout,
    apply_policy,
)


class Boom(Exception):
    """Deterministic failure used across the tests."""


class Flaky:
    """Fails `fail_times` times, then returns `value` and counts calls."""

    def __init__(self, fail_times=0, value="ok"):
        self.fail_times = fail_times
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise Boom("attempt %d failed" % self.calls)
        return self.value


def test_default_policy_is_one_attempt_and_raises():
    policy = ExceptionPolicy()
    assert policy.max_attempts == 1
    assert policy.has_fallback is False

    ok = apply_policy(policy, lambda: 42)
    assert (ok.ok, ok.value, ok.attempts, ok.is_success) == (True, 42, 1, True)

    flaky = Flaky(fail_times=1)
    with pytest.raises(Boom):
        apply_policy(policy, flaky)
    assert flaky.calls == 1  # no silent retry, no silent swallow


def test_max_retry_bounds_attempts_and_stops_on_success():
    flaky = Flaky(fail_times=2, value="late")
    result = apply_policy(ExceptionPolicy(max_retry=5), flaky)

    assert (result.ok, result.value, result.attempts) == (True, "late", 3)
    assert flaky.calls == 3  # success on the 3rd attempt stops the loop


def test_exhausted_throw_reraises_original_error():
    flaky = Flaky(fail_times=99)
    with pytest.raises(Boom) as excinfo:
        apply_policy(ExceptionPolicy(max_retry=2), flaky)

    assert "attempt 3 failed" in str(excinfo.value)
    assert flaky.calls == 3  # max_retry + 1 attempts, then raise


def test_exhausted_exception_branch_returns_route_with_success_marker():
    result = apply_policy(ExceptionPolicy(max_retry=1,
                                          process_type=ErrorProcessType.EXCEPTION_BRANCH),
                          Flaky(fail_times=99))

    assert result.ok is False
    assert result.route == ErrorProcessType.EXCEPTION_BRANCH
    assert result.is_success is True       # fallback == "node completed"
    assert result.attempts == 2
    assert "Boom" in (result.error or "")

    output = result.as_output()
    assert output["isSuccess"] is True
    assert output["route"] == ErrorProcessType.EXCEPTION_BRANCH


def test_exhausted_return_default_emits_data_on_err():
    result = apply_policy(
        ExceptionPolicy(max_retry=0,
                        process_type=ErrorProcessType.RETURN_DEFAULT,
                        data_on_err={"trades": [], "status": "skipped"}),
        Flaky(fail_times=99),
    )

    assert result.ok is False
    assert result.value == {"trades": [], "status": "skipped"}
    assert result.route == ErrorProcessType.RETURN_DEFAULT
    assert result.is_success is True
    assert result.attempts == 1


def test_timeout_is_cut_off_and_consumes_an_attempt():
    def hang():
        time.sleep(2.0)
        return "never"

    started = time.monotonic()
    with pytest.raises(StepTimeout):
        apply_policy(ExceptionPolicy(timeout_ms=50, max_retry=1), hang)
    elapsed = time.monotonic() - started

    assert elapsed < 1.5  # two cut-off attempts, never the full 2s sleep


def test_timeout_downgrades_to_default_data_when_policy_says_so():
    def hang():
        time.sleep(1.0)
        return "never"

    result = apply_policy(
        ExceptionPolicy(timeout_ms=40, process_type=ErrorProcessType.RETURN_DEFAULT,
                        data_on_err="fallback"),
        hang,
    )
    assert (result.ok, result.value, result.is_success) == (False, "fallback", True)
    assert "StepTimeout" in (result.error or "")


def test_fast_call_is_not_affected_by_timeout_budget():
    result = apply_policy(ExceptionPolicy(timeout_ms=5000), lambda: "quick")
    assert (result.value, result.attempts) == ("quick", 1)


def test_interrupt_is_reraised_without_consuming_retries():
    class Paused(Exception):
        pass

    flaky = Flaky(fail_times=1)

    def interrupt_only(exc):
        return isinstance(exc, Paused)

    with pytest.raises(Paused):
        apply_policy(ExceptionPolicy(max_retry=3,
                                     process_type=ErrorProcessType.RETURN_DEFAULT,
                                     data_on_err="x"),
                     lambda: (_ for _ in ()).throw(Paused("pause")),
                     is_interrupt=interrupt_only)
    assert flaky.calls == 0

    # A non-interrupt error under the same policy still falls back normally.
    result = apply_policy(ExceptionPolicy(max_retry=0,
                                          process_type=ErrorProcessType.RETURN_DEFAULT,
                                          data_on_err="x"),
                          flaky, is_interrupt=interrupt_only)
    assert (result.ok, result.value) == (False, "x")


def test_policy_validation_rejects_bad_config():
    with pytest.raises(ValueError):
        ExceptionPolicy(process_type="nope")
    with pytest.raises(ValueError):
        ExceptionPolicy(timeout_ms=-1)
    with pytest.raises(ValueError):
        ExceptionPolicy(max_retry=-3)
    with pytest.raises(TypeError):
        apply_policy("not-a-policy", lambda: 1)