"""G-6 (cycle-10): the provider-quota probe wired into the run-loop stop gate.

The gate is strictly opt-in: with no probe the loop behaves exactly as before.
With a probe the loop stops cleanly (status "ok", no failure) before starting a
round the budget can no longer fund; a probe that raises degrades to an error
snapshot and must never stop the run by itself.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from run_loop import RunLoopMixin  # noqa: E402

TASK_NAME = "_g6-quota"


class _Stub(RunLoopMixin):
    """Minimal host: the gate only reads quota_probe / _provider / _cache."""

    def __init__(self, probe, provider="test"):
        self.quota_probe = probe
        self.quota_provider = provider
        self.quota_cache = None


def _raise(exc):
    def _r():
        raise exc

    return _r


# ---- unit: resolve + reason ----------------------------------------------

def test_no_probe_is_a_noop():
    stub = _Stub(None)
    assert stub._quota_snapshot() is None
    assert stub._quota_stop_reason() is None


def test_headroom_does_not_stop():
    stub = _Stub(lambda: {"primary": {"usedPercent": 42.5},
                          "secondary": {"usedPercent": 10}})
    assert stub._quota_stop_reason() is None


def test_exhausted_window_stops_with_reason_and_reset():
    stub = _Stub(lambda: {"primary": {"usedPercent": 100,
                                      "resetsAt": 1700000000}})
    reason = stub._quota_stop_reason()
    assert reason is not None
    assert reason.startswith("Quota exhausted (provider=test")
    assert "next_reset_at=1700000000000" in reason


def test_raising_probe_degrades_and_does_not_stop():
    stub = _Stub(_raise(ConnectionError("provider down")))
    assert stub._quota_stop_reason() is None
    assert stub.quota_cache is not None
    assert stub.quota_cache.status == "error"
    assert stub.quota_cache.degraded is True


def test_last_known_snapshot_survives_a_later_raise():
    stub = _Stub(lambda: {"primary": {"usedPercent": 100}})
    assert stub._quota_stop_reason() is not None      # fresh fetch: exhausted
    assert stub.quota_cache.degraded is False
    stub.quota_probe = _raise(OSError("provider gone"))
    reason = stub._quota_stop_reason()                 # cache hit, still exhausted
    assert reason is not None
    assert "Quota exhausted" in reason
    assert stub.quota_cache.degraded is True


def test_unusable_payload_never_reads_as_zero_percent():
    stub = _Stub(lambda: {"primary": {}, "secondary": {}})
    assert stub._quota_stop_reason() is None
    assert stub.quota_cache.status == "error"


# ---- integration: the real run loop --------------------------------------

_ROUND = {
    "record": {"new_failures": 0, "new_successes": 0,
               "bumped_failures": 0, "bumped_successes": 0},
    "backtest": None, "backtest_status": "deferred",
    "execution_failed": True, "error": "store indexing is behind",
    "progressed": False, "all_excluded": False, "round_ctx": None,
}


def _cfg(db_path: Path, **loop_over) -> dict:
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(db_path.parent), "db": str(db_path)},
        "memory": {"sqlite_path": str(db_path)},
        "loop": {"max_rounds": 3, "no_progress_stop": 10, "meta_analyze_every": 100,
                 "batch_size": 0, "max_seconds": 0, "error_stop": 2},
        "backtest": {"script": "backtest/mock_backtest.py"},
        "task": {"name": TASK_NAME},
        "ooda": {"enabled": False},
    })
    cfg["loop"].update(loop_over)
    return cfg


def _drive(probe):
    d = Path(tempfile.mkdtemp(prefix="g6-quota-"))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            orch = Orchestrator(_cfg(d / "p.db"))
            orch.run_once = lambda *a, **k: dict(_ROUND)
            orch.quota_probe = probe
            orch.quota_provider = "openai"
            pool = d / "pool.json"
            pool.write_text(json.dumps([{"signal_pattern": "s",
                                         "market_condition": "m"}]),
                            encoding="utf-8")
            result = orch.run(str(pool))
        return orch, result
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(ROOT / "projects" / TASK_NAME, ignore_errors=True)


def test_run_stops_before_round_one_when_quota_exhausted():
    orch, result = _drive(lambda: {"primary": {"usedPercent": 100}})
    assert result["status"] == "ok"            # a clean stop, not a failure
    assert result["total_rounds"] == 0         # no round was started
    assert "Quota exhausted" in result["stop_reason"]
    assert "provider=openai" in result["stop_reason"]
    assert orch.circuit.state == "CLOSED"


def test_run_is_unchanged_without_a_probe():
    orch, result = _drive(None)
    assert result["total_rounds"] == 3
    assert "Quota" not in result["stop_reason"]


def test_run_continues_with_quota_headroom():
    orch, result = _drive(lambda: {"primary": {"usedPercent": 5}})
    assert result["total_rounds"] == 3
    assert "Quota exhausted" not in result["stop_reason"]


def test_run_survives_a_broken_probe():
    orch, result = _drive(_raise(RuntimeError("no quota endpoint")))
    assert result["total_rounds"] == 3
    assert "Quota exhausted" not in result["stop_reason"]