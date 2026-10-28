#!/usr/bin/env python
"""P2-B: run_parallel Windows multiprocessing real-parallel tests.

Verifies the fix for "Can't pickle local object": the worker target is now a
module-level picklable function passed via functools.partial, so Windows spawn
can execute real multiprocessing and the results match the serial semantics.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from config_util import deep_merge, DEFAULT_CONFIG  # noqa: E402
from memory_store import PatternStore  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from orchestrator import _parallel_exclusion_check  # noqa: E402 sync helper


def base_cfg(tmp_path):
    cfg = deep_merge(DEFAULT_CONFIG, {
        "memory": {"sqlite_path": str(tmp_path / "patterns.db")},
        "loop": {"max_rounds": 3, "no_progress_stop": 3,
                 "meta_analyze_every": 100, "batch_size": 0},
        "backtest": {"script": str(ROOT / "backtest" / "mock_backtest.py"),
                     "extra_args": "--seed test --win-bias 0.5"},
        "ooda": {"enabled": True},
        "task": {"name": "p2b-parallel", "success_criteria": [
            {"metric": "trades_count", "operator": "gt", "threshold": 0}]},
    })
    return cfg


def _seed_exclusion(store: PatternStore, pid: str, pattern: str, mkt: str = "H240Trend",
                    rule: str | None = None):
    """Insert a resolved failure with an active exclusion rule."""
    store.append_failure([{
        "id": pid,
        "date": "2026-09-03",
        "signal_pattern": pattern,
        "market_condition": mkt,
        "failure_mode": "repeated_loss",
        "impact": {"trades": 5, "win_rate": 0.2, "total_pnl": -3.5},
        "root_cause": "test seed",
        "solution": "avoid",
        "verification": "done",
        "status": "resolved",
        "exclusion_rule": rule or pattern,
        "rule_type": "signal",
    }])


def test_run_parallel_really_multiprocesses_and_matches_serial(tmp_path):
    cfg = base_cfg(tmp_path)
    orch = Orchestrator(cfg)

    # Seed an exclusion so at least one window reports excluded > 0.
    _seed_exclusion(orch.store, "fp-excl-1", "ExtremeChase", rule="ExtremeChase")

    windows = [
        {"name": "w1", "signals": [
            {"signal_pattern": "ExtremeChase", "market_condition": "H240Trend"}]},
        {"name": "w2", "signals": [
            {"signal_pattern": "CoolHead", "market_condition": "H8Trend"}]},
        {"name": "w3", "signals": [
            {"signal_pattern": "Breakout", "market_condition": "D1Range"}]},
    ]

    results = orch.run_parallel(windows)

    assert isinstance(results, list)
    assert len(results) == len(windows), f"expected {len(windows)} results, got {len(results)}"

    by_name = {r["name"]: r for r in results}
    for name in ("w1", "w2", "w3"):
        assert name in by_name, f"missing result for {name}"

    # w1 should be excluded (ExtremeChase rule active); others passed.
    assert by_name["w1"]["excluded"] == 1, by_name["w1"]
    assert by_name["w1"]["passed"] == 0
    assert by_name["w2"]["excluded"] == 0
    assert by_name["w2"]["passed"] == 1
    assert by_name["w3"]["excluded"] == 0
    assert by_name["w3"]["passed"] == 1
    for r in results:
        for key in ("name", "excluded", "passed", "error"):
            assert key in r, f"missing key {key!r} in {r}"


def test_run_parallel_matches_serial_helper(tmp_path):
    """Parallel output for each window equals the module-level helper (serial)."""
    cfg = base_cfg(tmp_path)
    orch = Orchestrator(cfg)
    _seed_exclusion(orch.store, "fp-excl-2", "GapFade", rule="GapFade")

    windows = [
        {"name": "a", "signals": [{"signal_pattern": "GapFade", "market_condition": "H1Trend"}]},
        {"name": "b", "signals": [{"signal_pattern": "NewsSpike", "market_condition": "M5"}]},
    ]
    results = orch.run_parallel(windows)
    for win, res in zip(windows, results):
        ser = _parallel_exclusion_check(win, orch.db_path)
        assert res["excluded"] == ser["excluded"], (win, res, ser)
        assert res["passed"] == ser["passed"], (win, res, ser)
        assert res["error"] == ser["error"], (win, res, ser)


def test_run_parallel_empty_windows_returns_empty(tmp_path):
    cfg = base_cfg(tmp_path)
    orch = Orchestrator(cfg)
    assert orch.run_parallel([]) == []
