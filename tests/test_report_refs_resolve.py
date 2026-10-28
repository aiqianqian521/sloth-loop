"""P0 regression: customer REPORT data refs must resolve on disk.

Guards the stress-test finding "7/7 native REPORT had dangling structured-data
references" (report_refs=false): refs used to be written as data/<run_id>/x.json
while the archive actually wrote data/x.json (sibling of REPORT.md).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "sloth_engine"
REPO = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from report_util import build_customer_report, write_customer_report  # noqa: E402

REF_RE = re.compile(r"file:line:\s*(\S+?):(\d+)")


def _summary(**over):
    base = {"run_id": "2026-10-20-refs-001", "task": "demo", "total_rounds": 2,
            "stop_reason": "normal finish", "new_failures": 1, "new_successes": 0,
            "active_exclusion_rules": 0, "problem_queue_total": 0,
            "l2_health_score": 0, "verdict": "OK"}
    base.update(over)
    return base


def _refs(md):
    return REF_RE.findall(md)


def test_data_refs_have_no_run_id_segment():
    md = build_customer_report(task="demo", domain="demo", summary=_summary())
    paths = [p for p, _ in _refs(md)]
    assert "data/rounds.json" in paths, paths
    assert "data/summary.json" in paths, paths
    assert not any("data/2026-" in p for p in paths), paths


def test_write_report_refs_resolve_on_disk(tmp_path):
    run_ts = "20260101-010101"
    data_dir = tmp_path / "projects" / "demo" / "runs" / run_ts / "data"
    data_dir.mkdir(parents=True)
    for name in ("rounds.json", "patterns.json", "summary.json", "problems.json"):
        (data_dir / name).write_text("{}", encoding="utf-8")
    report = write_customer_report(project_root=tmp_path, task="demo", domain="demo",
                                   summary=_summary(), run_ts=run_ts, data_dir=data_dir)
    md = report.read_text(encoding="utf-8")
    checked = 0
    for path, _line in _refs(md):
        if path.startswith("docs/"):
            continue
        checked += 1
        assert (report.parent / path).exists(), "dangling ref %s in %s" % (path, report)
    assert checked >= 5, "expected >=5 data refs, got %d" % checked


def test_risk_refs_point_to_existing_repo_files():
    md = build_customer_report(task="demo", domain="demo", summary=_summary())
    docs = [p for p, _ in _refs(md) if p.startswith("docs/")]
    assert docs, "risk section must cite repo docs"
    for p in docs:
        assert (REPO / p).exists(), "risk ref not on disk: %s" % p
