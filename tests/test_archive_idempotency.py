"""D-1 / D-2 fixes: archive run_id consistency + idempotency.

Worker 1 scope (data consistency + idempotency):
  - D-1: the archive must use the authoritative runtime run_id (run_loop
    _run_id) instead of a derived date-task-rounds-seq id, so the run_history
    row, _index.json entry and circuit filename share one identity.
  - D-2: re-archiving the same run_id must be idempotent: run_history stays one
    row (INSERT OR REPLACE) and _index.json keeps one entry (dedup by run_id).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from cli_router import CliDependencies, CliRouter  # noqa: E402


class _Logger:
    def info(self, *_a, **_kw):
        pass

    def error(self, *_a, **_kw):
        pass


class _NoopLock:
    """R1 (cycle-10): CliRouter now locks --once as well; this stub keeps the
    unit tests hermetic (no on-disk lock) while satisfying the CM protocol."""

    def __init__(self, _path):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _make_router(orch):
    return CliRouter(CliDependencies(
        build_orchestrator=lambda _cfg: orch,
        inspection_service=lambda _wd: SimpleNamespace(
            inspect_handler=lambda *_: None, trace_handler=lambda *_: None),
        show_history=lambda *_: None,
        run_lock_cls=_NoopLock,
        tee_cls=lambda stream, _path: stream,
        logger=_Logger()))


def _build_orchestrator(tmp_path, task_name="_wb1_arch"):
    """A real Orchestrator whose mutable runtime artifacts live in tmp_path."""
    pool = tmp_path / "signals.json"
    pool.write_text(json.dumps(
        [{"signal_pattern": "worker1_signal", "market_condition": "trend"}],
        ensure_ascii=False), encoding="utf-8")
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(tmp_path), "db": "db/patterns.db",
                    "io": "io/_data", "events": "runs", "logs": "logs",
                    "state": "state/STATE.md", "handoff": "state/handoff.json"},
        "loop": {"max_rounds": 1, "no_progress_stop": 10,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "task": {"name": task_name,
                 "success_criteria": [{"metric": "trades_count",
                                       "operator": "gt", "threshold": 0}],
                 "scope": {"allow": [], "deny": []}},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "python": str(Path(sys.executable))},
    })
    return Orchestrator(cfg), pool


def _run_once(orch, pool, fast=True):
    router = _make_router(orch)
    import contextlib
    import io
    args = SimpleNamespace(signals=str(pool), fast=fast)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = router._run_once(orch, args)
    return rc


def _index(orch):
    p = orch.runtime.events_dir / "_index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def test_once_archive_id_matches_runtime_run_id(tmp_path):
    """D-1: --once archive run_history id equals the authoritative run_id.

    The --once path leaves orch._run_id empty, so _report_context derives the
    same timestamp-based id from started_at. The archive must store exactly that
    id, and it must appear in _index.json.
    """
    orch, pool = _build_orchestrator(tmp_path)
    rc = _run_once(orch, pool)
    assert rc == 0

    run_id = orch._report_context().run_id
    assert run_id, "authoritative run_id must be non-empty"
    hist = orch.store.get_run_history(limit=5)
    assert len(hist) >= 1
    assert hist[0]["id"] == run_id
    runs = _index(orch).get("runs", [])
    assert any(r.get("run_id") == run_id for r in runs)


def test_archive_uses_set_run_id_when_provided(tmp_path):
    """D-1: when the orchestrator already set _run_id (continuous-loop case)
    the archive keeps it verbatim, both in run_history and the index."""
    orch, _pool = _build_orchestrator(tmp_path)
    run_id = "2026-09-03-some-task-1234567"
    orch._run_id = run_id
    orch.total_rounds = 3
    orch.started_at = 1234567.0
    target = orch.reporter.archive_run(orch._report_context(), "completed", 1.5)

    # subtask-tree behavior: nonzero started_at -> run_ts derived, so the
    # snapshot lands under projects/<task>/runs/<run_ts>/data/. The authoritative
    # run_id is still preserved in run_history and the index below.
    assert target.name == "data", target
    assert "runs" in target.parts, target
    assert len(target.parts) >= 3, target
    hist = orch.store.get_run_history(limit=5)
    assert hist[0]["id"] == run_id
    runs = _index(orch).get("runs", [])
    assert [r for r in runs if r.get("run_id") == run_id]


def test_rearchive_same_run_id_is_idempotent(tmp_path):
    """D-2: archiving the same run_id twice keeps one run_history row and one
    index entry."""
    orch, _pool = _build_orchestrator(tmp_path)
    run_id = "2026-09-03-idem-task-42"
    orch._run_id = run_id
    orch.total_rounds = 2
    orch.started_at = 42.0
    ctx = orch._report_context()

    orch.reporter.archive_run(ctx, "completed", 1.5)
    orch.reporter.archive_run(ctx, "completed", 1.5)

    hist = [r for r in orch.store.get_run_history(limit=1000)
            if r["id"] == run_id]
    assert len(hist) == 1
    index_entries = [r for r in _index(orch).get("runs", [])
                     if r.get("run_id") == run_id]
    assert len(index_entries) == 1


def test_archive_backward_compat_without_run_id(tmp_path):
    """D-2 / back-compat: a bare RunReportContext (run_id=None) still archives
    and falls back to a derived date-task-rounds-seq id."""
    orch, _pool = _build_orchestrator(tmp_path)
    from run_reporter import RunReportContext
    ctx = RunReportContext(
        total_rounds=2, task_cfg={"name": "legacy-task"},
        enable_ooda=False,
        zones={"green": [], "yellow": [], "red": []},
        consumer={"min_queue_size": 0, "min_same_type": 0, "high_confidence": 0},
    )
    target = orch.reporter.archive_run(ctx, "completed", 1.5)
    assert target.is_dir()  # archive dir created
    hist = orch.store.get_run_history(limit=5)
    assert len(hist) >= 1
    rid = hist[0]["id"]
    assert rid.startswith(date.today().isoformat()), rid
    runs = _index(orch).get("runs", [])
    assert runs and any(r.get("run_id") == rid for r in runs)
