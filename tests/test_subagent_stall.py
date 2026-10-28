# -*- coding: utf-8 -*-
"""cycle-8 A4-cand-A: stall watchdog wired into sub_agent.run_subagent.

Provenance: distilled from qwen-code packages/core/src/agents/runtime/workflow-stall.ts
(attachStallWatchdog / runStallResilient); loop mechanism lives in
sloth_engine/stall_watchdog.py (cycle-8 A4, commit 549fb8c). This test covers the
additive wiring: stall_ms defaults to 0 (legacy single call, contract unchanged);
when stall_ms>0 a wall-clock no-progress watchdog guards the executor, the handle
is exposed as context.watchdog for cooperative activity()/hold(), exhausted
stalls map to status="stalled", and deterministic failures keep their old
mapping (error/timeout).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from types import SimpleNamespace  # noqa: E402

from sub_agent import AgentContext, run_subagent, run_subagents_parallel  # noqa: E402


# --------------------------------------------------------------------------
# legacy path (stall_ms = 0): contract unchanged
# --------------------------------------------------------------------------
def test_default_off_completes_without_watchdog():
    ctx = AgentContext(agent_id="a0")

    def executor(c):
        assert c.watchdog is None  # nothing injected on the legacy path
        return SimpleNamespace(iterations=3)

    res = run_subagent(ctx, executor)
    assert res.status == "completed"
    assert res.iterations == 3
    assert res.output.iterations == 3
    assert ctx.watchdog is None


def test_timeout_maps_to_timeout_status():
    ctx = AgentContext(agent_id="a1")

    def executor(c):
        raise TimeoutError("boom")

    assert run_subagent(ctx, executor).status == "timeout"


def test_deterministic_error_maps_to_error_status():
    ctx = AgentContext(agent_id="a2")

    def executor(c):
        raise ValueError("deterministic")

    res = run_subagent(ctx, executor)
    assert res.status == "error"
    assert "deterministic" in (res.error or "")


# --------------------------------------------------------------------------
# stall-guarded path (stall_ms > 0)
# --------------------------------------------------------------------------
def test_exhausted_stall_maps_to_stalled_status():
    ctx = AgentContext(agent_id="a3")
    attempts = []

    def executor(c):
        attempts.append(1)
        wd = c.watchdog
        assert wd is not None
        if not wd.abort_event.wait(2.0):
            return "no-abort"  # should not happen with a live watchdog
        raise RuntimeError("aborted by watchdog")  # cooperative unwind

    res = run_subagent(ctx, executor, stall_ms=40)
    assert res.status == "stalled"
    assert "stalled on all" in (res.error or "")
    assert len(attempts) == 3  # MAX_STALL_ATTEMPTS
    assert ctx.watchdog is None  # handle cleared in finally


def test_activity_resets_timer_and_completes():
    ctx = AgentContext(agent_id="a4")

    def executor(c):
        wd = c.watchdog
        assert wd is not None
        for _ in range(4):
            time.sleep(0.05)
            wd.activity()  # observable progress
        return SimpleNamespace(iterations=2)

    res = run_subagent(ctx, executor, stall_ms=200)
    assert res.status == "completed"
    assert res.iterations == 2
    assert res.output.iterations == 2


def test_tool_in_flight_hold_suspends_stall():
    ctx = AgentContext(agent_id="a5")

    def executor(c):
        wd = c.watchdog
        assert wd is not None
        with wd.hold():          # a long tool call is not a stall
            time.sleep(0.25)
        return "done"

    assert run_subagent(ctx, executor, stall_ms=60).status == "completed"


def test_parallel_passes_stall_ms_through():
    contexts = [AgentContext(agent_id=f"p{i}") for i in range(2)]

    def executor(c):
        c.watchdog.abort_event.wait(2.0)
        raise RuntimeError("aborted by watchdog")

    results = run_subagents_parallel(contexts, executor, max_workers=2, stall_ms=40)
    assert set(results) == {"p0", "p1"}
    assert all(r.status == "stalled" for r in results.values())


def test_watchdog_does_not_affect_dataclass_equality():
    a = AgentContext(agent_id="x")
    b = AgentContext(agent_id="x")
    a.watchdog = object()  # compare=False -> still equal
    assert a == b
    assert "watchdog" not in repr(b)