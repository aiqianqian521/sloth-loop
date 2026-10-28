# -*- coding: utf-8 -*-
"""cycle-8 A4: wall-clock stall watchdog + stall-only retry (adopted candidate).

Provenance (distilled from qwen-code packages/core/src/agents/runtime/workflow-stall.ts):
  :DEFAULT_STALL_MS / :MAX_STALL_ATTEMPTS / :resolveStallMs
  :attachStallWatchdog   (timer SUSPENDED while a tool is in flight)
  :runStallResilient     (retry on stall only; deterministic errors propagate)

Contract under test: a delegated attempt that makes no observable progress for
``stall_ms`` is aborted; a slow-but-running tool must NOT be flagged; retries are
bounded and stall-only; ``stall_ms <= 0`` disables the watchdog. These are
behavioural guards, not source-grep checks.
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

from stall_watchdog import (  # noqa: E402
    DEFAULT_STALL_SECONDS,
    MAX_STALL_ATTEMPTS,
    StallWatchdog,
    resolve_stall_ms,
    run_stall_resilient,
)


# --------------------------------------------------------------------------
# resolve_stall_ms precedence
# --------------------------------------------------------------------------
def test_resolve_default_ms():
    assert resolve_stall_ms(None, env={}) == int(DEFAULT_STALL_SECONDS * 1000)


def test_resolve_per_call_wins():
    assert resolve_stall_ms(1234, env={"LOOP_STALL_SECONDS": "9"}) == 1234


def test_resolve_per_call_zero_disables():
    assert resolve_stall_ms(0, env={"LOOP_STALL_SECONDS": "9"}) == 0


def test_resolve_negative_falls_through_to_env():
    assert resolve_stall_ms(-5, env={"LOOP_STALL_SECONDS": "2"}) == 2000


def test_resolve_env_zero_disables():
    assert resolve_stall_ms(None, env={"LOOP_STALL_SECONDS": "0"}) == 0


def test_resolve_env_seconds_and_invalid():
    assert resolve_stall_ms(None, env={"LOOP_STALL_SECONDS": "1.5"}) == 1500
    # an unparsable env value falls back to the default
    assert resolve_stall_ms(None, env={"LOOP_STALL_SECONDS": "abc"}) == int(
        DEFAULT_STALL_SECONDS * 1000
    )


# --------------------------------------------------------------------------
# watchdog lifecycle
# --------------------------------------------------------------------------
def test_fires_without_activity():
    wd = StallWatchdog(50)
    wd.start()
    assert wd.abort_event.wait(2.0) is True
    assert wd.stalled is True
    wd.dispose()


def test_activity_resets_timer():
    wd = StallWatchdog(120)
    wd.start()
    for _ in range(6):
        time.sleep(0.05)
        wd.activity()
    assert wd.stalled is False
    wd.dispose()


def test_tool_in_flight_suspends_timer():
    wd = StallWatchdog(60)
    wd.start()
    wd.tool_started()
    time.sleep(0.25)  # far longer than the stall window
    assert wd.stalled is False
    assert wd.in_flight == 1
    wd.tool_finished()
    assert wd.abort_event.wait(2.0) is True
    wd.dispose()


def test_hold_context_manager_releases():
    wd = StallWatchdog(60)
    wd.start()
    with wd.hold():
        time.sleep(0.2)
        assert wd.stalled is False
    assert wd.in_flight == 0
    assert wd.abort_event.wait(2.0) is True
    wd.dispose()


def test_on_stall_hook_invoked_once():
    calls = []
    wd = StallWatchdog(40, on_stall=lambda: calls.append(1))
    wd.start()
    assert wd.abort_event.wait(2.0) is True
    time.sleep(0.1)
    assert calls == [1]
    wd.dispose()


def test_disabled_watchdog_is_inert():
    wd = StallWatchdog(0)
    wd.start()
    wd.activity()
    wd.tool_started()
    wd.tool_finished()
    time.sleep(0.15)
    assert wd.stalled is False
    assert wd.abort_event.is_set() is False
    wd.dispose()


def test_dispose_is_idempotent_and_prevents_fire():
    wd = StallWatchdog(50)
    wd.start()
    wd.dispose()
    wd.dispose()
    time.sleep(0.2)
    assert wd.stalled is False


# --------------------------------------------------------------------------
# run_stall_resilient
# --------------------------------------------------------------------------
def test_success_returns_first_attempt():
    calls = []

    def attempt(wd):
        calls.append(1)
        return "ok"

    assert run_stall_resilient(attempt, stall_ms=0, label="t") == "ok"
    assert run_stall_resilient(attempt, stall_ms=1000, label="t") == "ok"
    assert len(calls) == 2


def test_retries_on_stall_then_succeeds():
    calls = []

    def attempt(wd):
        calls.append(wd.stall_ms)
        if len(calls) < 3:
            # simulate a hung attempt that only ends when the watchdog aborts it
            wd.abort_event.wait(2.0)
            raise RuntimeError("attempt aborted by stall watchdog")
        return "recovered"

    assert run_stall_resilient(attempt, stall_ms=50, label="t") == "recovered"
    assert len(calls) == 3


def test_raises_after_max_stall_attempts():
    calls = []

    def attempt(wd):
        calls.append(1)
        wd.abort_event.wait(2.0)
        raise RuntimeError("aborted")

    with pytest.raises(RuntimeError) as ei:
        run_stall_resilient(attempt, stall_ms=40, max_attempts=3, label="wf")
    assert "stalled on all 3 attempts" in str(ei.value)
    assert len(calls) == 3 == MAX_STALL_ATTEMPTS


def test_non_stall_error_propagates_without_retry():
    calls = []

    def attempt(wd):
        calls.append(1)
        raise ValueError("deterministic failure")

    with pytest.raises(ValueError):
        run_stall_resilient(attempt, stall_ms=1000, label="t")
    assert len(calls) == 1


def test_parent_cancellation_has_priority_over_retry():
    calls = []

    def attempt(wd):
        calls.append(1)
        wd.abort_event.wait(2.0)
        raise RuntimeError("aborted")

    with pytest.raises(RuntimeError, match="aborted"):
        run_stall_resilient(
            attempt, stall_ms=40, label="t", is_parent_cancelled=lambda: True
        )
    assert len(calls) == 1