"""Forward tests for run_ts derivation in _report_context (A1 guard)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from config_util import DEFAULT_CONFIG, deep_merge
from orchestrator import Orchestrator


def _orch(tmp_path):
    pool = tmp_path / "signals.json"
    pool.write_text(json.dumps([{"signal_pattern": "s", "market_condition": "t"}]), encoding="utf-8")
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(tmp_path), "db": "db/patterns.db",
                    "io": "io/_data", "events": "runs", "logs": "logs"},
        "loop": {"max_rounds": 1, "no_progress_stop": 10, "meta_analyze_every": 100,
                 "batch_size": 0, "max_seconds": 0},
        "task": {"name": "rsder", "success_criteria": [], "scope": {"allow": [], "deny": []}},
        "backtest": {"script": "backtest/mock_backtest.py"},
    })
    return Orchestrator(cfg)


def test_report_context_derives_run_ts_from_started_at(tmp_path):
    orch = _orch(tmp_path)
    orch.started_at = 1735678800.0
    orch._run_id = "2025-01-01-rsder-12345"
    ctx = orch._report_context()
    assert ctx.run_ts is not None
    assert len(ctx.run_ts) == 15, ctx.run_ts
    assert ctx.run_ts[8] == "-", ctx.run_ts


def test_report_context_run_ts_none_when_started_at_zero(tmp_path):
    orch = _orch(tmp_path)
    orch.started_at = 0.0
    ctx = orch._report_context()
    assert ctx.run_ts is None
