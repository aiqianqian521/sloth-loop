"""Forward tests for the run_ts subtask tree (A1+A2 regression guard)."""
from __future__ import annotations
import sys
from pathlib import Path
from types import SimpleNamespace

ENGINE = Path(__file__).resolve().parents[1] / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import pytest
from report_util import write_customer_report
import run_reporter  # noqa: E402  (cycle-40 A: module handle for monkeypatch)
from run_reporter import RunReporter, RunReportContext


def _summary(**over):
    base = {
        "run_id": "2026-09-28-subtask-001", "task": "subt",
        "total_rounds": 2, "stop_reason": "completed",
        "new_failures": 0, "new_successes": 0,
        "active_exclusion_rules": 0, "problem_queue_total": 0,
        "l2_health_score": 80, "verdict": "OK",
    }
    base.update(over)
    return base


def test_write_with_run_ts_lands_in_runs_dir(tmp_path):
    target = write_customer_report(
        project_root=tmp_path, task="subt", domain="dom",
        summary=_summary(), run_ts="20260928-120000")
    rel = target.relative_to(tmp_path).as_posix()
    assert rel == "projects/dom/subt/runs/20260928-120000/REPORT.md", rel
    assert target.exists()


def test_diff_run_ts_do_not_collide(tmp_path):
    a = write_customer_report(project_root=tmp_path, task="subt", domain="dom",
                              summary=_summary(), run_ts="20260928-120000")
    b = write_customer_report(project_root=tmp_path, task="subt", domain="dom",
                              summary=_summary(), run_ts="20260928-130000")
    assert a.parent != b.parent
    assert a.exists() and b.exists()


def test_write_without_run_ts_back_compat(tmp_path):
    target = write_customer_report(
        project_root=tmp_path, task="subt", domain="dom", summary=_summary())
    rel = target.relative_to(tmp_path).as_posix()
    assert rel.startswith("projects/dom/subt/reports/"), rel
    assert rel.endswith("/REPORT.md")


def test_runreporter_forwards_run_ts_to_util(tmp_path, monkeypatch):
    import report_util as _ru
    captured = {}
    def _probe(*, project_root, task, domain, summary, failure_modes,
               run_ts=None, input_ref=None, data_dir=None, runs_root=None):
        captured["run_ts"] = run_ts
        captured["runs_root"] = runs_root
        return tmp_path / "probe.md"
    monkeypatch.setattr(_ru, "write_customer_report", _probe)
    store = SimpleNamespace(get_run_history=lambda limit=1: [_summary()],
                           load_failure_patterns=lambda: [])
    runtime = SimpleNamespace(state_file=tmp_path / "STATE.md")
    reporter = RunReporter(store, runtime)
    ctx = RunReportContext(total_rounds=2, task_cfg={"name": "subt"},
                         enable_ooda=True, zones={"green": [], "yellow": [], "red": []},
                         consumer={"min_queue_size": 0, "min_same_type": 0, "high_confidence": 0},
                         run_id="r1", run_ts="20260928-140000")
    reporter.write_customer_report(ctx)
    assert captured["run_ts"] == "20260928-140000"
    # O-3: when run_ts is present the tree root travels with it (runtime.root)
    assert captured["runs_root"] is not None


def test_runreporter_omits_run_ts_when_none(tmp_path, monkeypatch):
    import report_util as _ru2
    seen = []
    def _probe(*, project_root, task, domain, summary, failure_modes, **kw):
        seen.append(kw)
        return tmp_path / "probe2.md"
    monkeypatch.setattr(_ru2, "write_customer_report", _probe)
    store = SimpleNamespace(get_run_history=lambda limit=1: [_summary()],
                           load_failure_patterns=lambda: [])
    runtime = SimpleNamespace(state_file=tmp_path / "STATE.md")
    reporter = RunReporter(store, runtime)
    ctx = RunReportContext(total_rounds=2, task_cfg={"name": "subt"},
                         enable_ooda=True, zones={"green": [], "yellow": [], "red": []},
                         consumer={"min_queue_size": 0, "min_same_type": 0, "high_confidence": 0})
    reporter.write_customer_report(ctx)
    assert "run_ts" not in seen[0]


class _MemStore:
    def __init__(self):
        self.hist = []
    def get_run_history(self, limit=1000):
        return self.hist
    def load_failure_patterns(self):
        return []
    def load_success_patterns(self):
        return []
    def get_rounds(self):
        return []
    def pull_problems(self, status=None):
        return []
    def get_queue_stats(self):
        return {"total": 0, "by_status": {}, "by_type": {}}
    def get_last_l2_analysis(self):
        return None
    def get_active_exclusion_rules(self):
        return []
    def save_run_history(self, row):
        self.hist.append(row)


def test_archive_snapshot_lands_in_same_subtask_tree(tmp_path):
    (tmp_path / "events").mkdir(parents=True, exist_ok=True)
    runtime = SimpleNamespace(events_dir=tmp_path / "events")
    store = _MemStore()
    reporter = RunReporter(store, runtime)
    ctx = RunReportContext(total_rounds=1, task_cfg={"name": "subt"},
                         enable_ooda=True, zones={"green": [], "yellow": [], "red": []},
                         consumer={"min_queue_size": 0, "min_same_type": 0, "high_confidence": 0},
                         run_id="r1", run_ts="20260928-150000")
    target = reporter.archive_run(ctx, "completed", 1.0)
    assert target.name == "data", target
    assert "runs" in target.parts
    assert (target / "summary.json").exists()


def test_archive_copies_raw_io_from_runtime_io_dir(tmp_path):
    """P1-6: archive_run must copy loop_backtest_{input,output}.json from the
    runtime io_dir into the run data/ dir (byte-identical)."""
    (tmp_path / "events").mkdir(parents=True, exist_ok=True)
    io_dir = tmp_path / "io"
    io_dir.mkdir()
    (io_dir / "loop_backtest_input.json").write_bytes(b'{"signals": [1, 2]}')
    (io_dir / "loop_backtest_output.json").write_bytes(b'{"trades": [{"pnl": 3}]}')
    runtime = SimpleNamespace(events_dir=tmp_path / "events", io_dir=io_dir)
    reporter = RunReporter(_MemStore(), runtime)
    ctx = RunReportContext(total_rounds=1, task_cfg={"name": "subt"},
                         enable_ooda=True, zones={"green": [], "yellow": [], "red": []},
                         consumer={"min_queue_size": 0, "min_same_type": 0, "high_confidence": 0},
                         run_id="r1", run_ts="20260928-160000")
    target = reporter.archive_run(ctx, "completed", 1.0)
    for name in ("loop_backtest_input.json", "loop_backtest_output.json"):
        assert (target / name).exists(), name
    assert (target / "loop_backtest_input.json").read_bytes() == b'{"signals": [1, 2]}'
    assert (target / "loop_backtest_output.json").read_bytes() == b'{"trades": [{"pnl": 3}]}'


def test_archive_raw_io_missing_is_non_fatal(tmp_path, monkeypatch):
    """No io_dir and no _data files anywhere -> archive still succeeds with
    only the summary artifacts (branch: no raw I/O found).

    cycle-40 A: the repo-root `_data` fallback is pinned to an empty tmp dir
    so the branch is deterministic. A warm checkout has a gitignored `_data/`
    that a clean clone lacks, which used to flip this branch (and drift the
    recorded coverage by ~0.01pp) with no source change."""
    monkeypatch.setattr(run_reporter, "_data_root", lambda: tmp_path / "_data")
    (tmp_path / "events").mkdir(parents=True, exist_ok=True)
    runtime = SimpleNamespace(events_dir=tmp_path / "events")
    reporter = RunReporter(_MemStore(), runtime)
    ctx = RunReportContext(total_rounds=1, task_cfg={"name": "subt"},
                         enable_ooda=True, zones={"green": [], "yellow": [], "red": []},
                         consumer={"min_queue_size": 0, "min_same_type": 0, "high_confidence": 0},
                         run_id="r2", run_ts="20260928-160001")
    target = reporter.archive_run(ctx, "completed", 1.0)
    assert (target / "summary.json").exists()
    # Missing io_dir must NOT crash the archive. The repo-root _data fallback
    # is pinned to an empty tmp dir above, so this is the deterministic
    # "no raw I/O found" path; the helper returns a list either way and never
    # raises (branch: no io_dir).
    copied = reporter._archive_raw_io(ctx, target)
    assert isinstance(copied, list)
    for name in copied:
        assert (target / name).exists()
