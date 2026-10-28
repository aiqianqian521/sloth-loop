# -*- coding: utf-8 -*-
"""inv-2/A2 behavioural regression: token_budget MUST be a LIVE stop condition.

先测后写 (RED->GREEN): the static detector test_contract_invariants.py
::test_invariant_2 only asserts a tokens_used accrual *site exists*; this file
adds behavioural evidence --
 A. an accrual line that actually runs one round and proves tokens_used grows
    (covers the new run_once_pipeline accrual line, defeating the A2 dead knob
    at orchestrator.py:224 where tokens_used is only ever initialised to 0);
 B. a tiny token_budget that stops the loop strictly earlier than no budget,
    exercising the live trigger path run_loop.py:244 / circuit_state.py:154.
Loop identity is preserved: a deterministic mock backtest is used; no LLM/model
billing interface is ever invoked (E4/E5 decision A).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import pytest  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from config_util import deep_merge, DEFAULT_CONFIG  # noqa: E402


@pytest.fixture(autouse=True)
def _block_customer_report(monkeypatch):
    """Isolation: stop the run() completion path from writing REPORT.md."""
    monkeypatch.setattr("orchestrator.Orchestrator._write_customer_report",
                        lambda self, *a, **k: None)


def _cfg(td: Path, *, max_rounds=5, token_budget=500000) -> dict:
    db = td / "p.db"
    (td / "signals.json").write_text(
        json.dumps([{"signal_pattern": "test-signal", "market_condition": "m"}]),
        encoding="utf-8")
    return deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(td), "db": str(db)},
        "memory": {"sqlite_path": str(db)},
        "loop": {
            "max_rounds": max_rounds,
            "no_progress_stop": 999,    # disable stagnation early-stop (isolate budget)
            "meta_analyze_every": 100,
            "batch_size": 0, "max_seconds": 0,
            "error_stop": 999,          # disable circuit breaker early-stop
            "token_budget": token_budget,
            "signals": str(td / "signals.json"),
        },
        "backtest": {"script": str(ROOT / "backtest" / "mock_backtest.py"),
                     "extra_args": "--seed test --win-bias 0.5"},
        "task": {"name": "inv2-budget-test",
                 # never-satisfied threshold -> disable completion early-stop
                 "success_criteria": [
                    {"metric": "win_rate", "operator": "gte", "threshold": 0.999}]},
    })


def test_tokens_used_accrues_across_a_round(tmp_path):
    """A: tokens_used must really accrue after one round (covers accrual line)."""
    # run_loop checks max_rounds at loop TOP before run_once: max_rounds=2 lets
    # exactly one round execute (covers the accrual line); max_rounds=1 trips first.
    cfg = _cfg(tmp_path, max_rounds=2, token_budget=500000)
    o = Orchestrator(cfg)
    assert o.tokens_used == 0
    o.run()
    assert o.tokens_used > 0, "A2: tokens_used must accrue each round (work-volume>0)"


def test_token_budget_is_a_live_stop(tmp_path):
    """B: token_budget=1 must stop the loop strictly earlier than no budget."""
    big_dir = tmp_path / "big"
    big_dir.mkdir()
    o_big = Orchestrator(_cfg(big_dir, max_rounds=5, token_budget=500000))
    o_big.run()

    small_dir = tmp_path / "small"
    small_dir.mkdir()
    o_small = Orchestrator(_cfg(small_dir, max_rounds=5, token_budget=1))
    o_small.run()

    assert o_small.tokens_used >= o_small.token_budget, "A2: small budget must be crossed"
    assert o_small.total_rounds < o_big.total_rounds, \
        "A2: token_budget=1 must stop earlier than no budget (live trigger run_loop:244/circuit_state:154)"
    assert o_big.total_rounds >= 2, "baseline: without budget limit should run near max_rounds"
