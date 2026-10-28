#!/usr/bin/env python
"""F9: run_ts uniqueness under same-second concurrency.

Regression guard for the F9 same-project concurrency probe (2026-10-22):
4 concurrent `--once` runs on one project all exited 0 but produced a SINGLE
archive directory, i.e. three runs' evidence was silently overwritten.

Fix: the archive dir name is claimed atomically (``mkdir(exist_ok=False)``) and
suffixed ``-2``, ``-3`` ... on collision; the first claim keeps the historical
15-char ``YYYYMMDD-HHMMSS`` form.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import run_reporter  # noqa: E402
from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from run_reporter import claim_run_ts  # noqa: E402

TS_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?$")


def _orch(tmp_path, name="f9conc"):
    """Real Orchestrator with all writable runtime artifacts under tmp_path."""
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(tmp_path), "db": "db/patterns.db",
                    "io": "io/_data", "events": "runs", "logs": "logs"},
        "loop": {"max_rounds": 1, "no_progress_stop": 10,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "task": {"name": name,
                 "success_criteria": [{"metric": "trades_count",
                                       "operator": "gt", "threshold": 0}],
                 "scope": {"allow": [], "deny": []}},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "python": str(Path(sys.executable))},
    })
    return Orchestrator(cfg)


def _redirect_base(tmp_path, monkeypatch):
    """Point the projects/<task> tree at tmp_path instead of the real repo."""
    monkeypatch.setattr(
        run_reporter, "run_base_dir",
        lambda pp, tn, root=None: tmp_path / "projects" / (tn or "loop"))


def test_claim_run_ts_keeps_format_then_suffixes(tmp_path):
    a = claim_run_ts("f9conc", "f9conc", "20261022-110500", root=tmp_path)
    b = claim_run_ts("f9conc", "f9conc", "20261022-110500", root=tmp_path)
    c = claim_run_ts("f9conc", "f9conc", "20261022-110500", root=tmp_path)
    assert a == "20261022-110500"
    assert b == "20261022-110500-2"
    assert c == "20261022-110500-3"
    assert (tmp_path / "projects" / "f9conc" / "runs" / a).is_dir()


def test_claim_run_ts_is_atomic_across_processes(tmp_path):
    """Four real OS processes claiming the same timestamp get four names."""
    env = dict(os.environ)
    env["F9_ENG"] = str(ENGINE)
    env["F9_ROOT"] = str(tmp_path)
    code = (
        "import os, sys; sys.path.insert(0, os.environ['F9_ENG']);"
        "from run_reporter import claim_run_ts;"
        "print(claim_run_ts('f9conc', 'f9conc', '20261022-110500',"
        " root=os.environ['F9_ROOT']))"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) for _ in range(4)]
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=180)
        assert p.returncode == 0, err
        outs.append(out.strip())
    assert len(set(outs)) == 4, outs
    assert all(TS_RE.match(o) for o in outs), outs
    runs = tmp_path / "projects" / "f9conc" / "runs"
    assert len([p for p in runs.iterdir() if p.is_dir()]) == 4


def test_report_context_read_has_no_filesystem_side_effect(tmp_path, monkeypatch):
    _redirect_base(tmp_path, monkeypatch)
    orch = _orch(tmp_path)
    orch.started_at = 1735678800.0
    ts = orch._report_context().run_ts
    assert ts and TS_RE.match(ts), ts
    assert len(ts) == 15, "read-only context must keep the legacy 15-char form"
    assert not (tmp_path / "projects").exists(), "pure read must not create dirs"


def test_claim_run_ts_is_per_instance_and_unique(tmp_path, monkeypatch):
    _redirect_base(tmp_path, monkeypatch)
    a = _orch(tmp_path)
    a.started_at = 1735678800.0
    b = _orch(tmp_path)
    b.started_at = 1735678800.0
    t1 = a._claim_run_ts()
    t2 = b._claim_run_ts()
    assert t1 and t2 and t1 != t2
    assert t2.startswith(t1)
    assert a._claim_run_ts() == t1, "claim must be idempotent per instance"
    assert a._report_context().run_ts == t1, "context must reuse the claim"
    assert (tmp_path / "projects" / "f9conc" / "runs" / t1).is_dir()


def test_archive_run_uses_the_claimed_run_ts(tmp_path, monkeypatch):
    _redirect_base(tmp_path, monkeypatch)
    orch = _orch(tmp_path)
    orch.started_at = 1735678800.0
    orch.total_rounds = 1
    claimed = orch._claim_run_ts()
    target = orch._archive_run("--once completed", 1.0)
    assert target is not None
    assert orch._report_context().run_ts == claimed
    assert str(target).endswith(os.path.join("runs", claimed, "data")), target