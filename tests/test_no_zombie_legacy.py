"""Fail-closed guard: dead *_legacy methods stay purged (P2.1 Slice D).

Locks the state produced by P2.1 Slice D: the *_legacy methods proven dead
must not resurrect. The former _run_once_legacy was renamed to run_fast (the
live fast-mode implementation) and is asserted to exist + be callable, while
OODASteps._verify_legacy must stay gone while live _verify remains.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_SLOTH_ENGINE = _HERE.parent / "sloth_engine"
if str(_SLOTH_ENGINE) not in sys.path:
    sys.path.insert(0, str(_SLOTH_ENGINE))

import orchestrator  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402


def test_no_zombie_orchestrator_legacy_methods():
    # _run_once_legacy was renamed to run_fast (the live fast-mode implementation);
    # no *_legacy method may survive anywhere on Orchestrator.
    zombies = [n for n in dir(Orchestrator) if n.endswith("_legacy")]
    assert not zombies, f"zombie _legacy methods resurrected: {zombies}"
    assert hasattr(Orchestrator, "run_once")
    assert hasattr(Orchestrator, "run_fast")
    assert callable(Orchestrator.run_fast)


def test_ooda_verify_legacy_stays_purged():
    import ooda_pipeline  # noqa: E402
    assert hasattr(ooda_pipeline.OODASteps, "_verify"), "live _verify must remain"
    assert not hasattr(ooda_pipeline.OODASteps, "_verify_legacy"), "_verify_legacy zombie resurrected"


def test_run_fast_smoke():
    """run_once(signals, fast=True) must route to run_fast and return a dict
    with the fast-mode result keys ({check, backtest, record, progressed, ...})."""
    import tempfile
    from config_util import deep_merge, DEFAULT_CONFIG

    d = pathlib.Path(tempfile.mkdtemp(prefix="loop-fast-smoke-"))
    db = d / "p.db"
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(d), "db": str(db)},
        "memory": {"sqlite_path": str(db)},
        "loop": {"max_rounds": 1, "no_progress_stop": 3,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "extra_args": "--seed fast-smoke --win-bias 0.5"},
    })
    o = Orchestrator(cfg)
    sigs = [{"signal_pattern": "test_signal", "market_condition": "trend following"}]
    result = o.run_once(sigs, round_num=1, fast=True)
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    for key in ("check", "backtest", "record", "progressed"):
        assert key in result, f"missing fast-result key {key!r} in {sorted(result)}"
    assert isinstance(result["check"], dict)
    assert isinstance(result["record"], dict)
