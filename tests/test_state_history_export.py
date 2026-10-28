"""cycle-14: the immutable state-history export was unreachable dead code.

`run()` had the P3-A1 export block *after* its `return {...}`, so
`state-history-<run_id>.jsonl` was never written, and `iter_loop()` never
exported at all. This suite pins the fix:

  1. `run()` writes one JSONL line per in-memory snapshot (reachability proof);
  2. `iter_loop()` (exhausted by the caller) writes the same file;
  3. a zero-round run writes nothing (no-op, not an empty file);
  4. `_export_state_history()` is a no-op without a populated StateHistory;
  5. the source no longer carries the dead block (call precedes the return).

Note: a round can stop *before* its snapshot (e.g. the contract completion
limit breaks on the final round), so the exported line count equals
`orch._state_history.count`, not necessarily `total_rounds`.
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
from immutable_state import LoopState, StateHistory  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from run_loop import RunLoopMixin  # noqa: E402

TASK_NAME = "_q14-state-history"

_ROUND = {
    "record": {"new_failures": 0, "new_successes": 0,
               "bumped_failures": 0, "bumped_successes": 0},
    "backtest": None, "backtest_status": "deferred",
    "execution_failed": True, "error": "store indexing is behind",
    "progressed": False, "all_excluded": False, "round_ctx": None,
}


class _Bare(RunLoopMixin):
    """Minimal host for the export helper (no orchestrator deps)."""

    def __init__(self, history=None):
        if history is not None:
            self._state_history = history


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


@contextlib.contextmanager
def _host(**loop_over):
    d = Path(tempfile.mkdtemp(prefix="q14-state-"))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            orch = Orchestrator(_cfg(d / "p.db", **loop_over))
            orch.run_once = lambda *a, **k: dict(_ROUND)
            pool = d / "pool.json"
            pool.write_text(json.dumps([{"signal_pattern": "s",
                                         "market_condition": "m"}]),
                            encoding="utf-8")
        yield orch, pool
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(ROOT / "projects" / TASK_NAME, ignore_errors=True)


def _history_file(orch: Orchestrator) -> Path:
    return Path(orch.work_dir) / ("state-history-%s.jsonl" % orch._run_id)


def _lines(path: Path) -> list:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---- run() ----------------------------------------------------------------

def test_run_exports_the_in_memory_history():
    with _host() as (orch, pool):
        with contextlib.redirect_stdout(io.StringIO()):
            result = orch.run(str(pool))
        assert result["total_rounds"] == 3
        count = orch._state_history.count
        assert count >= 1, "the run must have produced snapshots"
        path = _history_file(orch)
        assert path.is_file(), "run() must export the state history (was dead code)"
        lines = _lines(path)
        assert len(lines) == count
        rounds = [json.loads(ln)["round_num"] for ln in lines]
        assert rounds == list(range(1, count + 1))


def test_run_with_zero_rounds_writes_nothing():
    with _host(max_rounds=0) as (orch, pool):
        with contextlib.redirect_stdout(io.StringIO()):
            result = orch.run(str(pool))
        assert result["total_rounds"] == 0
        assert orch._state_history.count == 0
        assert not _history_file(orch).exists()


# ---- iter_loop() ----------------------------------------------------------

def test_iter_loop_exports_when_exhausted():
    with _host() as (orch, pool):
        with contextlib.redirect_stdout(io.StringIO()):
            yields = list(orch.iter_loop(str(pool)))
        count = orch._state_history.count
        assert count >= 1
        assert len(yields) == count, "one yield per snapshot"
        path = _history_file(orch)
        assert path.is_file(), "iter_loop() must export the state history"
        assert len(_lines(path)) == count


# ---- helper ---------------------------------------------------------------

def test_export_helper_noop_without_history():
    assert _Bare()._export_state_history() is None
    assert _Bare(StateHistory())._export_state_history() is None


def test_export_helper_writes_and_reports_path():
    host = _Bare(StateHistory())
    host.work_dir = Path(tempfile.mkdtemp(prefix="q14-helper-"))
    host._run_id = "rid"
    host._state_history.append(LoopState(round_num=1))
    try:
        path = host._export_state_history()
        assert path == Path(host.work_dir) / "state-history-rid.jsonl"
        assert path.is_file()
        assert len(_lines(path)) == 1
    finally:
        shutil.rmtree(host.work_dir, ignore_errors=True)


# ---- source tripwire ------------------------------------------------------

def test_dead_export_block_is_gone():
    src = (ENGINE / "run_loop.py").read_text(encoding="utf-8")
    assert src.count("self._export_state_history()") == 2, "run() + iter_loop()"
    assert src.count("history_path = self.work_dir") == 1, "one export helper"
    call_at = src.index("self._export_state_history()")
    ret_at = src.index('"status": "error" if _failed else "ok"')
    assert call_at < ret_at, "the export call must precede run()'s return"