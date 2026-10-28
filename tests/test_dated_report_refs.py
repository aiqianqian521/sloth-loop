"""cycle-30 A: a produced report must not assert an evidence ref that is not there.

D-R1 -- the dated customer report (``--report`` / ``write_customer_report`` with
``run_ts=None``) rendered its findings table as ``file:line: data/<name>.json:1``
while no ``data/`` directory is ever written next to it: every ref dangled, and
the in-report self-check ``validate_risk_evidence`` was blind to it (it only
grepped for the literal ``ref:``/``file:line:`` tags).  Same family as D-S1
(asserted path that never exists) -- a fabricated pointer an evidence-chasing
agent would follow into nothing.

Fix: (1) the self-check now verifies the ref *exists*; (2) the producer never
emits a ``data/<x>.json`` it cannot back -- it cites the newest archived
snapshot (relative, or absolute across drives) or self-cites REPORT.md.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import report_util  # noqa: E402
from report_util import (SELF_CITE, build_customer_report, validate_risk_evidence,
                         write_customer_report)  # noqa: E402
from run_reporter import RunReporter, RunReportContext  # noqa: E402

REF_RE = re.compile(r"file:line:\s*(\S+?):(\d+)")


def _summary(**over):
    base = {"run_id": "2026-10-25-dated-001", "task": "demo", "total_rounds": 1,
            "stop_reason": "normal finish", "new_failures": 0, "new_successes": 1,
            "active_exclusion_rules": 0, "problem_queue_total": 0,
            "l2_health_score": 0, "verdict": "OK"}
    base.update(over)
    return base


def _dangling_refs(md, base_dir):
    out = []
    for path, _ in REF_RE.findall(md):
        p = Path(path)
        if p.is_absolute():
            ok = p.exists()
        else:
            ok = (Path(base_dir) / p).exists() or (report_util.REPO_ROOT / p).exists()
        if not ok:
            out.append(path)
    return out


# -- the self-check must actually check ---------------------------------------

def test_validate_flags_dangling_ref():
    md = ("## 2. 关键发现\n\n"
          "| 指标 | 值 | ref: | file:line: |\n"
          "|------|----|------|------------|\n"
          "| x | 1 | ref: rounds.json | file:line: data/rounds.json:1 |\n")
    warns = validate_risk_evidence(md, base_dir="/nonexistent-root-zzz")
    assert warns and "dangling" in warns[0], warns


def test_validate_accepts_existing_ref(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "rounds.json").write_text("{}", encoding="utf-8")
    md = ("## 2. 关键发现\n\n"
          "| 指标 | 值 | ref: | file:line: |\n"
          "|------|----|------|------------|\n"
          "| x | 1 | ref: rounds.json | file:line: data/rounds.json:1 |\n")
    assert validate_risk_evidence(md, base_dir=tmp_path) == []


def test_validate_without_anchor_skips_existence():
    """Back-compat: no anchor -> only the tag check (callers that write must anchor)."""
    md = ("## 2. 关键发现\n\n"
          "| 指标 | 值 | ref: | file:line: |\n"
          "|------|----|------|------------|\n"
          "| x | 1 | ref: rounds.json | file:line: data/rounds.json:1 |\n")
    assert validate_risk_evidence(md) == []


# -- the producer must not lie -------------------------------------------------

def test_dated_report_refs_resolve_with_no_snapshot(tmp_path):
    """--report before any run: no data/ dir -> self-cite, never a dangling ref."""
    target = write_customer_report(project_root=tmp_path, task="demo", domain="demo",
                                   summary=_summary())
    md = target.read_text(encoding="utf-8")
    assert not (target.parent / "data").exists()
    assert _dangling_refs(md, target.parent) == []
    assert "file:line: REPORT.md:1" in md
    assert "data/rounds.json" not in md
    assert "+ `data/`" not in md


def test_dated_report_cites_snapshot_when_given(tmp_path):
    snap = tmp_path / "rt" / "projects" / "demo" / "runs" / "20261025-000000" / "data"
    snap.mkdir(parents=True)
    for name in ("rounds.json", "patterns.json", "summary.json", "problems.json"):
        (snap / name).write_text("{}", encoding="utf-8")
    reportdir = tmp_path / "projects" / "demo" / "reports" / "2026-10-25"
    reportdir.mkdir(parents=True)
    md = build_customer_report(task="demo", domain="demo", summary=_summary(),
                               data_ref=snap.resolve().as_posix(),
                               base_dir=reportdir)
    assert _dangling_refs(md, reportdir) == []


def test_cross_drive_snapshot_falls_back_to_absolute(tmp_path, monkeypatch):
    """relpath impossible (foreign drive) -> absolute, not the old fib 'data'."""
    snap = tmp_path / "rt" / "projects" / "demo" / "runs" / "20261025-000000" / "data"
    snap.mkdir(parents=True)
    for name in ("rounds.json", "patterns.json", "summary.json", "problems.json"):
        (snap / name).write_text("{}", encoding="utf-8")

    def _boom(*_a, **_k):
        raise ValueError("path is on mount 'C:', start on mount 'E:'")

    monkeypatch.setattr(report_util.os.path, "relpath", _boom)
    target = write_customer_report(project_root=tmp_path / "repo", task="demo",
                                   summary=_summary(), data_dir=snap)
    md = target.read_text(encoding="utf-8")
    assert snap.resolve().as_posix() in md
    assert _dangling_refs(md, target.parent) == []


# -- RunReporter wires the dated branch to a real snapshot ---------------------

class _Store:
    def get_run_history(self, limit=1):
        return [_summary()]

    def load_failure_patterns(self):
        return []


def _ctx():
    return RunReportContext(total_rounds=1, task_cfg={"name": "demo"}, enable_ooda=False,
                            zones={"green": [], "yellow": [], "red": []},
                            consumer={"min_queue_size": 0, "min_same_type": 0,
                                      "high_confidence": 0})


def test_latest_archive_data_dir_picks_newest(tmp_path):
    runs = tmp_path / "projects" / "demo" / "runs"
    for ts in ("20261025-000000", "20261025-120000"):
        (runs / ts / "data").mkdir(parents=True)
    rep = RunReporter(_Store(), SimpleNamespace(root=tmp_path, events_dir=tmp_path / "runs"))
    got = rep._latest_archive_data_dir(tmp_path, "demo")
    assert got == runs / "20261025-120000" / "data", got


def test_runreporter_dated_report_cites_archive(tmp_path, monkeypatch):
    """Without a run in-process the report must cite the newest archived data."""
    snap = tmp_path / "projects" / "demo" / "runs" / "20261025-120000" / "data"
    snap.mkdir(parents=True)
    captured = {}

    def _capture(**kw):
        captured.update(kw)
        return tmp_path / "REPORT.md"

    monkeypatch.setattr(report_util, "write_customer_report", _capture)
    rep = RunReporter(_Store(), SimpleNamespace(root=tmp_path, events_dir=tmp_path / "runs"))
    rep.write_customer_report(_ctx())
    assert captured.get("data_dir") == snap, captured


def test_runreporter_dated_report_omits_data_dir_when_no_archive(tmp_path, monkeypatch):
    captured = {}

    def _capture(**kw):
        captured.update(kw)
        return tmp_path / "REPORT.md"

    monkeypatch.setattr(report_util, "write_customer_report", _capture)
    rep = RunReporter(_Store(), SimpleNamespace(root=tmp_path, events_dir=tmp_path / "runs"))
    rep.write_customer_report(_ctx())
    assert "data_dir" not in captured, captured


def test_self_cite_sentinel_is_not_a_data_dir_name():
    assert SELF_CITE == "REPORT.md"
