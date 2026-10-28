"""cycle-16 A: tool_concurrency contract (the zero-coverage EXEMPT module).

``sloth_engine/tool_concurrency.py`` is an explicit orphan-gate exemption: it is
an opt-in batch scheduler with no production caller (the OODA Act step
dispatches exactly one tool per round), so it stays exempt until a multi-tool
Act model lands.  Exempt from *wiring* is not exempt from *testing*: the module
shipped with 0% coverage, i.e. nobody had ever executed the barrier splitting,
the bounded pool, the ordered-result mapping or the sibling cancellation.
These cases pin all of them.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from tool_concurrency import (  # noqa: E402
    DEFAULT_MAX_PARALLEL,
    ConcurrencyConfig,
    ConcurrentResult,
    execute_all_batches,
    execute_batch_parallel,
    partition_tool_calls,
)


def _calls(*names):
    return [{"name": n, "params": {}} for n in names]


# ---- ConcurrencyConfig (fail-closed) ---------------------------------------

def test_default_config_is_fail_closed():
    cfg = ConcurrencyConfig()
    assert cfg.is_concurrency_safe is False
    assert cfg.check() is False
    assert cfg.check({"anything": 1}) is False


def test_static_flag_allows_concurrency():
    assert ConcurrencyConfig(is_concurrency_safe=True).check() is True


def test_per_input_function_wins_over_the_static_flag():
    cfg = ConcurrencyConfig(is_concurrency_safe=False,
                            is_concurrency_safe_fn=lambda p: p.get("readonly", False))
    assert cfg.check({"readonly": True}) is True
    assert cfg.check({"readonly": False}) is False


def test_per_input_function_exception_is_fail_closed():
    def boom(_params):
        raise RuntimeError("policy blew up")

    cfg = ConcurrencyConfig(is_concurrency_safe=True, is_concurrency_safe_fn=boom)
    assert cfg.check({"x": 1}) is False


def test_per_input_function_needs_params_else_falls_back_to_static_flag():
    cfg = ConcurrencyConfig(is_concurrency_safe=True,
                            is_concurrency_safe_fn=lambda p: False)
    assert cfg.check(None) is True       # no input -> static flag


# ---- partition_tool_calls (exclusive barriers) -----------------------------

def test_partition_of_nothing_is_nothing():
    assert partition_tool_calls([], {}) == []


def test_all_parallel_safe_calls_collapse_into_one_batch():
    cmap = {n: ConcurrencyConfig(is_concurrency_safe=True) for n in ("a", "b", "c")}
    batches = partition_tool_calls(_calls("a", "b", "c"), cmap)
    assert [[c["name"] for c in b] for b in batches] == [["a", "b", "c"]]


def test_a_serial_call_flushes_the_pool_and_becomes_its_own_batch():
    cmap = {"a": ConcurrencyConfig(is_concurrency_safe=True),
            "x": ConcurrencyConfig(is_concurrency_safe=False)}
    batches = partition_tool_calls(_calls("a", "a", "x", "a"), cmap)
    assert [[c["name"] for c in b] for b in batches] == [["a", "a"], ["x"], ["a"]]


def test_a_serial_call_opening_the_list_does_not_create_an_empty_batch():
    cmap = {"a": ConcurrencyConfig(is_concurrency_safe=True),
            "x": ConcurrencyConfig(is_concurrency_safe=False)}
    batches = partition_tool_calls(_calls("x", "a"), cmap)
    assert [[c["name"] for c in b] for b in batches] == [["x"], ["a"]]


def test_unknown_tool_is_treated_as_serial():
    cmap = {"a": ConcurrencyConfig(is_concurrency_safe=True)}
    batches = partition_tool_calls(_calls("a", "mystery", "a"), cmap)
    assert [[c["name"] for c in b] for b in batches] == [["a"], ["mystery"], ["a"]]


def test_partition_keeps_the_original_call_objects():
    calls = _calls("a")
    batches = partition_tool_calls(calls, {"a": ConcurrencyConfig(is_concurrency_safe=True)})
    assert batches[0][0] is calls[0]


def test_partition_uses_per_call_params_for_the_safety_decision():
    cmap = {"t": ConcurrencyConfig(
        is_concurrency_safe_fn=lambda p: p.get("mode") == "read")}
    calls = [{"name": "t", "params": {"mode": "read"}},
             {"name": "t", "params": {"mode": "write"}},
             {"name": "t", "params": {"mode": "read"}}]
    batches = partition_tool_calls(calls, cmap)
    assert [[c["params"]["mode"] for c in b] for b in batches] == [
        ["read"], ["write"], ["read"]]


# ---- execute_batch_parallel -------------------------------------------------

def test_single_call_takes_the_fast_path():
    res = execute_batch_parallel(_calls("solo"), lambda call: call["name"])
    assert len(res) == 1
    assert res[0].ok and res[0].result == "solo"
    assert res[0].error is None and res[0].elapsed_ms >= 0


def test_single_call_exception_is_captured_not_raised():
    def boom(_call):
        raise RuntimeError("solo boom")

    res = execute_batch_parallel(_calls("solo"), boom)
    assert res[0].ok is False
    assert res[0].result is None
    assert "solo boom" in res[0].error


def test_parallel_results_follow_submission_order_not_completion_order():
    def executor(call):
        time.sleep(0.15 if call["name"] == "slow" else 0.0)
        return call["name"]

    res = execute_batch_parallel(_calls("slow", "fast1", "fast2"), executor,
                                 max_workers=3)
    assert [r.call["name"] for r in res] == ["slow", "fast1", "fast2"]
    assert all(r.ok for r in res)


def test_error_results_are_reported_per_call_without_aborting():
    def executor(call):
        if call["name"] == "boom":
            raise ValueError("boom")
        return call["name"]

    res = execute_batch_parallel(_calls("ok1", "boom", "ok2"), executor,
                                 max_workers=DEFAULT_MAX_PARALLEL)
    assert [r.ok for r in res] == [True, False, True]
    assert "boom" in res[1].error


def test_abort_on_first_error_cancels_queued_siblings():
    ran = []

    def executor(call):
        ran.append(call["name"])
        if call["name"] == "boom":
            raise RuntimeError("boom")
        return call["name"]

    # max_workers=1 keeps the scheduling deterministic: boom runs first, the
    # remaining calls are still queued and therefore cancellable.
    res = execute_batch_parallel(_calls("boom", "a", "b"), executor,
                                 max_workers=1, abort_on_first_error=True)
    assert res[0].ok is False and "boom" in res[0].error
    assert [r.error for r in res[1:]] == ["cancelled (sibling error)"] * 2
    assert ran == ["boom"]


# ---- execute_all_batches (batch barrier + abort) ---------------------------

def test_batches_run_in_order_and_results_concatenate():
    batches = partition_tool_calls(
        _calls("a", "a", "x", "a"),
        {"a": ConcurrencyConfig(is_concurrency_safe=True),
         "x": ConcurrencyConfig(is_concurrency_safe=False)})
    res = execute_all_batches(batches, lambda call: call["name"])
    assert [r.call["name"] for r in res] == ["a", "a", "x", "a"]
    assert all(r.ok for r in res)


def test_abort_on_first_error_stops_later_batches():
    ran = []

    def executor(call):
        ran.append(call["name"])
        if call["name"] == "boom":
            raise RuntimeError("boom")
        return call["name"]

    batches = [[{"name": "ok1", "params": {}}],
               [{"name": "boom", "params": {}}],
               [{"name": "never", "params": {}}]]
    res = execute_all_batches(batches, executor, abort_on_first_error=True)
    assert [r.call["name"] for r in res] == ["ok1", "boom"]
    assert ran == ["ok1", "boom"]           # the third batch never ran


def test_without_abort_every_batch_runs_even_after_an_error():
    def executor(call):
        if call["name"] == "boom":
            raise RuntimeError("boom")
        return call["name"]

    batches = [[{"name": "boom", "params": {}}], [{"name": "after", "params": {}}]]
    res = execute_all_batches(batches, executor)
    assert [r.call["name"] for r in res] == ["boom", "after"]
    assert res[1].ok and res[1].result == "after"


def test_concurrent_result_ok_property():
    assert ConcurrentResult(call={}, result=1).ok is True
    assert ConcurrentResult(call={}, result=None, error="x").ok is False