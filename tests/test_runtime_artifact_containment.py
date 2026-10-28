"""cycle-29 A: runtime artifacts (and the run lock) must obey ``runtime.root``.

O-3 -- the run_ts subtask tree (``projects/<task>/runs/<ts>/data`` plus the
per-run REPORT.md) was pinned to the *repository* root, so a run whose
``runtime.root`` pointed at a sandbox still wrote into the repo.  The 2026-10-25
full stress suite left ~50 leaked task dirs in the repo that way, while
CLAUDE.md section 4 says the opposite (run artifacts are written under
runtime.root only).  The dated customer REPORT tree
(``reports/<date>/REPORT.md``) stays project-norm on purpose (CLAUDE.md 9.4).

O-5 -- D-S1 showed a forensic agent can assert a lock path that is not the one
the code uses.  The lock path is pinned here to ``<runtime.root>/.loop.lock``
for the --once and the continuous entrypoint alike.

O-1 -- --once exit code: 0 means "the round ran", not "criteria met".
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import pytest  # noqa: E402
from cli_router import CliDependencies, CliRouter  # noqa: E402
from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from report_util import write_customer_report  # noqa: E402
from run_reporter import RunReporter, RunReportContext  # noqa: E402

TASK = "o3-contain"


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


def _runtime(tmp_path, name="sandbox-root"):
    root = tmp_path / name
    (root / "events").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(root=root, events_dir=root / "events",
                           io_dir=root / "io", state_file=root / "state" / "STATE.md")


def _ctx(run_ts="20261025-101010"):
    return RunReportContext(
        total_rounds=1, task_cfg={"name": TASK}, enable_ooda=False,
        zones={"green": [], "yellow": [], "red": []},
        consumer={"min_queue_size": 0, "min_same_type": 0, "high_confidence": 0},
        run_id="2026-10-25-o3-contain-1", run_ts=run_ts)


def test_archive_tree_obeys_runtime_root(tmp_path):
    runtime = _runtime(tmp_path)
    reporter = RunReporter(_MemStore(), runtime)
    target = reporter.archive_run(_ctx(), "completed", 1.0)
    assert target.name == "data"
    assert "runs" in target.parts
    assert runtime.root in target.parents, (runtime.root, target)
    assert (target / "summary.json").exists()
    assert not (ROOT / "projects" / TASK).exists(), "O-3: archive leaked into the repo"


def test_per_run_report_obeys_runtime_root(tmp_path):
    runtime = _runtime(tmp_path)
    reporter = RunReporter(_MemStore(), runtime)
    target = reporter.write_customer_report(_ctx())
    assert target.name == "REPORT.md"
    assert "runs" in target.parts
    assert runtime.root in target.parents, (runtime.root, target)
    assert not (ROOT / "projects" / TASK).exists(), "O-3: report leaked into the repo"


def test_report_and_archive_share_one_tree(tmp_path):
    """The report's data/ ref must resolve to the archived JSONs next to it."""
    runtime = _runtime(tmp_path)
    reporter = RunReporter(_MemStore(), runtime)
    data = reporter.archive_run(_ctx(), "completed", 1.0)
    report = reporter.write_customer_report(_ctx())
    assert report.parent == data.parent, (report, data)


def test_runs_root_defaults_to_project_root_for_existing_callers(tmp_path):
    target = write_customer_report(project_root=tmp_path, task="t1", domain="t1",
                                   summary={"verdict": "OK"},
                                   run_ts="20260101-000000")
    rel = target.relative_to(tmp_path).as_posix()
    assert rel == "projects/t1/runs/20260101-000000/REPORT.md", rel


def test_default_runtime_root_is_the_repo_so_layout_is_unchanged(tmp_path):
    """Back-compat: with no ``runtime`` section the tree root *is* the repo."""
    reporter = RunReporter(_MemStore(), SimpleNamespace(events_dir=tmp_path / "e"))
    assert reporter._tree_root() == ROOT, reporter._tree_root()


# -- O-5: the lock path is <runtime.root>/.loop.lock for both entrypoints ------

def _orch(tmp_path, task="o5-lock"):
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(tmp_path), "db": "db/patterns.db",
                    "io": "io/_data", "events": "runs", "logs": "logs",
                    "state": "state/STATE.md", "handoff": "state/handoff.json"},
        "loop": {"max_rounds": 1, "no_progress_stop": 10,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "task": {"name": task,
                 "success_criteria": [{"metric": "trades_count",
                                       "operator": "gt", "threshold": 0}],
                 "scope": {"allow": [], "deny": []}},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "python": str(Path(sys.executable))},
        "ooda": {"enabled": False, "uq_enabled": False, "uq_require_input": False},
    })
    return Orchestrator(cfg)


def _spy_router(orch, seen):
    class _SpyLock:
        def __init__(self, path):
            seen.append(Path(path))

        def __enter__(self):
            raise RuntimeError("stop here: lock path captured")

        def __exit__(self, *exc):
            return False

    logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None,
                             warning=lambda *a, **k: None)
    return CliRouter(CliDependencies(
        build_orchestrator=lambda _cfg: orch,
        inspection_service=lambda _wd: SimpleNamespace(
            inspect_handler=lambda *_: None, trace_handler=lambda *_: None),
        show_history=lambda *_: None, run_lock_cls=_SpyLock,
        tee_cls=lambda stream, _p: stream, logger=logger))


def test_lock_path_is_runtime_root_for_both_entrypoints(tmp_path):
    orch = _orch(tmp_path)
    seen = []
    router = _spy_router(orch, seen)
    assert router.run(["--once"]) == 2      # lock refused -> exit 2
    assert router.run([]) == 2              # continuous entrypoint, same lock
    expected = orch.runtime.root / ".loop.lock"
    assert seen == [expected, expected], (seen, expected)


def test_lock_path_expression_has_one_shape():
    """D-S1 family: the lock path is a constant that must have a single source.
    Both call sites spell it identically so no forensic agent can quote a
    second, wrong path."""
    src = (ENGINE / "cli_router.py").read_text(encoding="utf-8")
    expr = 'lock_path = orch.runtime.root / ".loop.lock"'
    assert src.count(expr) == 2, src.count(expr)


# -- O-1: --once exit code contract is documented in the source ---------------

def test_once_exit_code_contract_is_pinned(tmp_path):
    src = (ENGINE / "cli_router.py").read_text(encoding="utf-8")
    assert "O-1 exit-code contract (cycle-29 A)" in src
    assert 'result.get("status") == "error"' in src
