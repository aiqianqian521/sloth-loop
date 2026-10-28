# -*- coding: utf-8 -*-
"""L3 cycle-4 A4 - backpressure/defer is NOT a failure (adopted candidate C2).

Provenance (distilled from vectorize-io/hindsight):
  worker/exceptions.py:25-38  (DeferOperation: requeue without counting a retry)
  worker/backpressure.py:36-50 (is_store_backpressure: match the store text)
  worker/poller.py:1228-1244   (defer reroute sits BEFORE the failure path)

Contract under test: an explicitly deferred round is backpressure, not a
failure. It must NOT increment the circuit breaker's consecutive-failure
counter, must NOT open the breaker, and must NOT abort a run that would
otherwise stop on "consecutive_failures". A genuine error must still fail
closed (one error is still counted).

These are behavioural + contract-invariant guards, not source-grep checks.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from backpressure import (  # noqa: E402
    DEFER_STATUS,
    BackpressureVerdict,
    DeferOperation,
    classify_round,
    is_backpressure,
)
from circuit_breaker import CircuitBreaker  # noqa: E402
from immutable_state import LoopState, StateReducer  # noqa: E402
from loop_controller import LoopController  # noqa: E402


# ---------------------------------------------------------------------------
# 1. classifier unit contract (fail-closed)
# ---------------------------------------------------------------------------
def test_defer_operation_is_backpressure():
    v = is_backpressure(DeferOperation("store busy", retry_after=4.0))
    assert v.deferred and v.is_failure is False
    assert v.retry_after == 4.0 and v.source == "exception"


def test_defer_status_string():
    assert is_backpressure(DEFER_STATUS).deferred is True
    assert is_backpressure("  DEFERRED ").deferred is True


def test_text_marker_recognised_with_retry_after():
    v = is_backpressure("error", text="store indexing is behind; retry_after 2.5")
    assert v.deferred and v.retry_after == 2.5


def test_generic_error_is_failure_fail_closed():
    assert is_backpressure("error").deferred is False
    assert classify_round(status="error", execution_failed=True,
                          error="invalid JSON").deferred is False


def test_execution_failed_alone_does_not_defer():
    # An adapter reporting non-ok is NOT enough; only an explicit defer signal is.
    v = classify_round(status="error", execution_failed=True, error="boom")
    assert v == BackpressureVerdict(False)


def test_classify_round_prefers_status_then_error():
    assert classify_round(status=DEFER_STATUS).deferred is True
    assert classify_round(status="error", error=DeferOperation("later")).deferred is True
    assert classify_round(status="error", error="429 too many requests").deferred is True


# ---------------------------------------------------------------------------
# 2. controller accounting: defer leaves the breaker untouched
# ---------------------------------------------------------------------------
def test_deferred_round_does_not_trip_breaker():
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
    controller = LoopController(breaker, max_rounds=5, no_progress_stop=3)
    # Even many deferrals must not accumulate consecutive failures.
    for _ in range(10):
        verdict = classify_round(status=DEFER_STATUS)
        if not verdict.deferred:           # the loop only records non-defers
            controller.record_execution("error")
        assert controller.record_execution("completed") == "CLOSED"
    assert breaker.consecutive_failures == 0
    assert breaker.state == "CLOSED"


def test_genuine_errors_still_trip_breaker():
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
    controller = LoopController(breaker, max_rounds=5, no_progress_stop=3)
    assert classifier_defer("error", "invalid JSON") is False
    controller.record_execution("error")
    assert controller.record_execution("error") == "OPEN"


def classifier_defer(status, err):
    return classify_round(status=status, execution_failed=True, error=err).deferred


# ---------------------------------------------------------------------------
# 3. immutable state carries the defer flag (observability)
# ---------------------------------------------------------------------------
def test_reducer_threads_deferred_flag():
    s = StateReducer.reduce(LoopState(), round_num=1, backtest_status=DEFER_STATUS,
                            execution_failed=True, deferred=True)
    assert s.deferred is True and s.execution_failed is True
    assert s._sources["deferred"] == "calc"


def test_reducer_default_is_not_deferred():
    assert StateReducer.reduce(LoopState(), round_num=1).deferred is False


# ---------------------------------------------------------------------------
# 4. contract invariant: the loop's defer branch precedes the failure branch
#    and never calls record_execution on the deferred path.
# ---------------------------------------------------------------------------
def test_run_loop_defer_branch_is_before_failure_and_non_counting():
    src = (ENGINE / "run_loop.py").read_text(encoding="utf-8")
    # two entrypoints (run + iter_loop) must both route through the classifier
    assert src.count("classify_round(") >= 2, "both run() and iter_loop() must classify"
    guard = 'if deferral.deferred and getattr(self, "enable_backpressure_defer", True):'
    assert src.count(guard) == 2, "both run() and iter_loop() need the guarded defer branch"
    cursor = 0
    for _ in range(2):
        i = src.index(guard, cursor)
        nxt = src.index("elif execution_failed:", i)
        # ignore comments: only executable lines may not touch accounting
        code_lines = [ln.split("#", 1)[0] for ln in src[i:nxt].splitlines()]
        defer_code = "\n".join(code_lines)
        assert "record_execution" not in defer_code, (
            "the deferred branch must not touch the failure-accounting path")
        assert i < nxt and nxt < src.index("elif bt is not None:", i)
        cursor = nxt + 1


def test_config_default_enables_backpressure_defer():
    from config_util import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["loop"]["backpressure_defer_enabled"] is True
    yml = (ENGINE / "config.yaml").read_text(encoding="utf-8")
    assert "backpressure_defer_enabled: true" in yml


def test_backpressure_module_has_no_io_or_engine_imports():
    """Classifier stays pure: no engine imports, no file/socket I/O."""
    src = (ENGINE / "backpressure.py").read_text(encoding="utf-8")
    for token in ("import io", "import os", "import socket", "subprocess.",
                  "from orchestrator", "import orchestrator", "from run_loop",
                  "from immutable_state", "from event_log"):
        assert token not in src, f"backpressure.py must stay pure, found {token!r}"


# ---------------------------------------------------------------------------
# 5. end-to-end: a deferred round must NOT trip the breaker, a real error must.
#    Drives the real Orchestrator.run() with a stubbed run_once so the test
#    stays deterministic and offline.
# ---------------------------------------------------------------------------
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import tempfile  # noqa: E402

from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402


def _cfg(db_path: Path, **loop_over) -> dict:
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(db_path.parent), "db": str(db_path)},
        "memory": {"sqlite_path": str(db_path)},
        "loop": {"max_rounds": 6, "no_progress_stop": 10, "meta_analyze_every": 100,
                 "batch_size": 0, "max_seconds": 0, "error_stop": 2},
        "backtest": {"script": "backtest/mock_backtest.py"},
        "task": {"name": "_bp-test"},
        "ooda": {"enabled": False},
    })
    cfg["loop"].update(loop_over)
    return cfg


def _drive_run(cfg, round_res):
    """Run Orchestrator.run() with a stub run_once; return (orch, log_text)."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setLevel(logging.INFO)
    logging.getLogger().addHandler(h)
    try:
        with contextlib.redirect_stdout(buf):
            o = Orchestrator(cfg)
            o.run_once = lambda *a, **k: dict(round_res)
            ck = o.store.load_checkpoint  # keep signature
            o.store.clear_checkpoint = lambda _run_id: None
            pool = Path(cfg["runtime"]["root"]) / "pool.json"
            pool.write_text(json.dumps([{"signal_pattern": "s", "market_condition": "m"}]),
                            encoding="utf-8")
            o.run(str(pool))
    finally:
        logging.getLogger().removeHandler(h)
    return o, buf.getvalue()


def _sweep_repo_task_dir():
    """O-3 (cycle-29 A): assert the run tree obeyed ``runtime.root``.

    Until cycle-29 the continuous-loop reporter pinned projects/<task>/runs/ to
    the *repo* root regardless of runtime.root, so this helper existed only to
    clean up the leak afterwards.  The tree now follows runtime.root (a temp dir
    in this test), so a repo copy is a regression: wipe it -- keeping the suite
    clean, projects/ is gitignored -- and fail."""
    import shutil
    leaked = ROOT / "projects" / "_bp-test"
    if leaked.exists():
        shutil.rmtree(leaked, ignore_errors=True)
        raise AssertionError(f"O-3: runtime run tree leaked into the repo: {leaked}")


def test_deferred_rounds_do_not_open_breaker_end_to_end():
    d = Path(tempfile.mkdtemp(prefix="bp-defer-"))
    try:
        # every round reports a store backpressure signal -> must never trip
        deferred = {
            "record": {"new_failures": 0, "new_successes": 0,
                       "bumped_failures": 0, "bumped_successes": 0},
            "backtest": None, "backtest_status": "deferred",
            "execution_failed": True, "error": "store indexing is behind",
            "progressed": False, "all_excluded": False, "round_ctx": None,
        }
        o, _ = _drive_run(_cfg(d / "p.db"), deferred)
        assert o.total_rounds == 6, f"deferrals must not stop the run, ran {o.total_rounds}"
        assert o.circuit.consecutive_failures == 0
        assert o.circuit.state == "CLOSED"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        _sweep_repo_task_dir()


def test_genuine_error_still_trips_breaker_end_to_end():
    d = Path(tempfile.mkdtemp(prefix="bp-fail-"))
    try:
        failed = {
            "record": {"new_failures": 0, "new_successes": 0,
                       "bumped_failures": 0, "bumped_successes": 0},
            "backtest": None, "backtest_status": "error",
            "execution_failed": True, "error": "invalid JSON from wrapper",
            "progressed": False, "all_excluded": False, "round_ctx": None,
        }
        o, _ = _drive_run(_cfg(d / "p.db"), failed)
        assert o.total_rounds == 2, f"real errors must trip at error_stop=2, ran {o.total_rounds}"
        assert o.circuit.state == "OPEN"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        _sweep_repo_task_dir()


def test_flag_off_restores_legacy_counting():
    d = Path(tempfile.mkdtemp(prefix="bp-off-"))
    try:
        deferred = {
            "record": {"new_failures": 0, "new_successes": 0,
                       "bumped_failures": 0, "bumped_successes": 0},
            "backtest": None, "backtest_status": "deferred",
            "execution_failed": True, "error": "store indexing is behind",
            "progressed": False, "all_excluded": False, "round_ctx": None,
        }
        o, _ = _drive_run(_cfg(d / "p.db", backpressure_defer_enabled=False), deferred)
        # legacy: execution_failed still counted -> breaker trips at 2
        assert o.total_rounds == 2, f"flag off must count as failure, ran {o.total_rounds}"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        _sweep_repo_task_dir()
