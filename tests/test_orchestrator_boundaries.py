"""W2 boundary checks for SignalPool and Verifier."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from signal_pool import SignalPool  # noqa: E402
from verifier import Verifier  # noqa: E402
from circuit_breaker import CircuitBreaker  # noqa: E402
from loop_controller import LoopController  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-boundary-") as td:
        seed = Path(td) / "signals.json"
        seed.write_text(json.dumps([
            {"signal_pattern": "a"},
            {"signal_pattern": "b", "market_condition": "trend"},
            {"bad": True},
            "invalid",
        ]), encoding="utf-8")
        pool = SignalPool(str(seed), batch_size=2, fallback_root=ROOT)
        assert [item["signal_pattern"] for item in pool.next_batch()] == ["a", "b"]
        assert [item["signal_pattern"] for item in pool.next_batch()] == ["a", "b"]
        assert pool.load()[0]["market_condition"] == "unknown"

    verified = Verifier.verify(
        {"status": "completed", "signals_tested": 2,
         "trades": [{"pnl": 1}, {"pnl": -0.5}], "sharpe": 1.2},
        [{"metric": "trades_count", "operator": "gte", "threshold": 2},
         {"metric": "win_rate", "operator": "gte", "threshold": 0.5},
         {"metric": "sharpe", "operator": "gt", "threshold": 1.0}],
    )
    assert verified["pass_count"] == 3
    assert verified["fail_count"] == 0
    failed = Verifier.verify({"status": "error", "error": "timeout", "trades": []}, [])
    assert failed["fail_count"] == 1 and failed["details"][0]["metric"] == "execution"
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
    controller = LoopController(breaker, max_rounds=3, no_progress_stop=2)
    assert controller.allow_round(0)
    controller.record_execution("error")
    assert controller.record_execution("error") == "OPEN"
    assert not controller.allow_round(2)
    print("PASS SignalPool boundary and Verifier contract")


def test_contract():
    """Pytest entry (cycle-16 A): keep these assertions inside the gate.

    This file used to be a manual script (``python tests/<file>``): pytest
    collected zero tests from it, so its assertions were never enforced by
    ``run_gate.py``.  The body is unchanged -- this wrapper only makes the very
    same checks run under pytest.
    """
    main()


if __name__ == "__main__":
    main()
