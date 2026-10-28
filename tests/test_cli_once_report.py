"""End-to-end --once / --once --fast path: archive + customer report.

Worker B todo 3: --once / --once --fast must run the same tail chain as the
continuous loop (_archive_run + _write_customer_report), so a single manual
round is archived and emits a customer completion REPORT.md instead of only
writing state.

Drives the actual CliRouter._run_once with a real Orchestrator (mock backtest),
for both fast=False (full OODA) and fast=True (skip OODA).
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import pytest  # noqa: E402
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


def _build_orchestrator(tmp_path, task_name, fast):
    """A real Orchestrator whose mutable runtime artifacts live in tmp_path.

    Task-relative artifacts follow runtime.root (O-3, cycle-29 A): the per-run
    REPORT.md lands under <tmp_path>/projects/<task>/runs/<run_ts>/.  The dated
    customer tree (projects/<task>/reports/<date>/REPORT.md) still targets the
    repo project-norm dir, so we use a unique task_name for both.
    """
    pool = tmp_path / "signals.json"
    pool.write_text(json.dumps(
        [{"signal_pattern": "worker_b_signal", "market_condition": "trend"}],
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
    cfg["ooda"] = {"enabled": not fast, "uq_enabled": False, "uq_require_input": False}
    return Orchestrator(cfg), pool


def _run_once_end_to_end(tmp_path, task_name, fast):
    orch, pool = _build_orchestrator(tmp_path, task_name, fast)
    router = _make_router(orch)
    args = SimpleNamespace(signals=str(pool), fast=fast)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = router._run_once(orch, args)
    return orch, rc


def _report_path(tree_root, task_name):
    # subtask-tree reports: <runtime.root>/projects/<task>/runs/<run_ts>/REPORT.md
    # (one per run, no overwrite; O-3: the run tree follows runtime.root).  Pick
    # the latest run_ts if present; else surface a missing path.
    base = Path(tree_root) / "projects" / task_name / "runs"
    if base.exists():
        cands = sorted(base.glob("*/REPORT.md"))
        if cands:
            return cands[-1]
    return base / "MISSING" / "REPORT.md"


@pytest.mark.parametrize("fast", [False, True])
def test_once_archives_and_emits_customer_report(tmp_path, fast):
    task_name = "once-report-wb"
    orch, rc = _run_once_end_to_end(tmp_path, task_name, fast)

    assert rc == 0
    # Archive ran: run_history has at least one snapshot.
    assert len(orch.store.get_run_history()) >= 1

    # Customer report emitted into the project-norm dir and carries the run_id.
    report = _report_path(tmp_path, task_name)
    assert report.exists(), f"REPORT.md missing at {report}"
    text = report.read_text(encoding="utf-8")
    run_id = orch.store.get_run_history(limit=1)[0]["id"]
    assert run_id in text, f"run_id {run_id} not in REPORT.md"
    assert "--once completed" in text  # the stop reason is rendered
