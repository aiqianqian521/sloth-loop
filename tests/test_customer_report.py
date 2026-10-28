"""Tests for the customer completion report (--report) generators.

Coverage:
- report_util.build_customer_report: frontmatter + 4-piece structure present.
- report_util.write_customer_report: writes to projects/<task>/reports/<date>/REPORT.md
  (no duplicated path segments when domain == task).
- RunReporter.write_customer_report: wires store snapshot -> project report dir.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ENGINE = Path(__file__).resolve().parents[1] / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import report_util
import pytest
from report_util import build_customer_report, write_customer_report, validate_risk_evidence
from run_reporter import RunReporter, RunReportContext, classify_stop


def _summary(**over):
    base = {
        "run_id": "2026-09-02-customer-report-001",
        "task": "demo",
        "total_rounds": 5,
        "stop_reason": "max_rounds reached",
        "new_failures": 2,
        "new_successes": 1,
        "active_exclusion_rules": 3,
        "problem_queue_total": 4,
        "l2_health_score": 66,
        "verdict": "WARN",
    }
    base.update(over)
    return base


class _FakeStore:
    def __init__(self, summary, failures):
        self._summary = summary
        self._failures = failures

    def get_run_history(self, limit=1):
        return [self._summary]

    def load_failure_patterns(self):
        return list(self._failures)


def test_build_customer_report_has_all_sections():
    md = build_customer_report(task="demo", domain="demo", summary=_summary(),
                               failure_modes={"EXEC_ERROR": 1})
    assert md.startswith("---\n")
    assert "skill_family: demo" in md
    for heading in ["## 1. 结论", "## 2. 关键发现", "## 4. 加固建议", "## 5. 下一步"]:
        assert heading in md, "missing " + heading
    assert "有警告" in md  # WARN -> 有警告


def test_write_customer_report_no_dup_path(tmp_path):
    target = write_customer_report(
        project_root=tmp_path, task="demo", domain="demo", summary=_summary())
    rel = target.relative_to(tmp_path).as_posix()
    assert rel.startswith("projects/demo/reports/"), rel
    assert "demo/demo" not in rel, rel
    assert target.exists()
    assert "input_ref: projects/demo/data/loop_backtest_input.json" in target.read_text(encoding="utf-8")


def test_runreporter_write_customer_report(tmp_path, monkeypatch):
    store = _FakeStore(_summary(), [{"failure_mode": "EXEC_ERROR"}])
    runtime = SimpleNamespace(state_file=tmp_path / "STATE.md")
    reporter = RunReporter(store, runtime)
    ctx = RunReportContext(
        total_rounds=5, task_cfg={"name": "demo"}, enable_ooda=True,
        zones={"green": [], "yellow": [], "red": []},
        consumer={"min_queue_size": 3, "min_same_type": 3, "high_confidence": 5})

    original = report_util.write_customer_report

    def _probe(project_root=None, task=None, domain=None, summary=None,
               failure_modes=None, input_ref=None, run_ts=None):
        return original(project_root=tmp_path, task=task, domain=domain,
                        summary=summary, failure_modes=failure_modes,
                        input_ref=input_ref)

    monkeypatch.setattr(report_util, "write_customer_report", _probe)
    try:
        out = reporter.write_customer_report(ctx)
    finally:
        monkeypatch.setattr(report_util, "write_customer_report", original)
    assert out.exists()
    assert "## 1. 结论" in out.read_text(encoding="utf-8")


def test_runreporter_uses_id_column_for_real_run(tmp_path, monkeypatch):
    """run_history stores the id under 'id'; report must render it as run_id."""
    store = _FakeStore({"id": "2026-09-02-real-001",
                        "total_rounds": 2, "stop_reason": "done",
                        "new_failures": 0, "new_successes": 1,
                        "verdict": "OK"}, [])
    runtime = SimpleNamespace(state_file=tmp_path / "STATE.md")
    reporter = RunReporter(store, runtime)
    ctx = RunReportContext(
        total_rounds=2, task_cfg={"name": "demo"}, enable_ooda=True,
        zones={"green": [], "yellow": [], "red": []},
        consumer={"min_queue_size": 3, "min_same_type": 3, "high_confidence": 5})

    import report_util as _ru
    original = _ru.write_customer_report

    def _probe(project_root=None, task=None, domain=None, summary=None,
               failure_modes=None, input_ref=None, run_ts=None):
        return original(project_root=tmp_path, task=task, domain=domain,
                        summary=summary, failure_modes=failure_modes,
                        input_ref=input_ref)

    monkeypatch.setattr(_ru, "write_customer_report", _probe)
    try:
        out = reporter.write_customer_report(ctx)
    finally:
        monkeypatch.setattr(_ru, "write_customer_report", original)
    text = out.read_text(encoding="utf-8")
    assert "2026-09-02-real-001" in text
    assert "demo-manual" not in text


def test_ensure_understand_needs_input_when_placeholder(tmp_path):
    """未传: 00-purpose.md 只有占位符 + require_input -> needs_input=True (强提醒)."""
    from ooda_pipeline import OODASteps
    purpose = tmp_path / "00-purpose.md"
    purpose.write_text("# purpose\\n## Goal\\n[Describe the task goal in one sentence]\\n## Success Criteria\\n\\n## Boundary\\n- In scope: [What this task covers]\\n", encoding="utf-8")
    task_work_dir = tmp_path / "loop-2026-09-02"
    task_work_dir.mkdir(parents=True, exist_ok=True)
    purpose2 = task_work_dir / "00-purpose.md"
    purpose2.write_text(purpose.read_text(encoding="utf-8"), encoding="utf-8")
    res = OODASteps._ensure_understand(None, {}, task_work_dir, require_input=True)
    assert res["fields_ok"] is False
    assert res["needs_input"] is True
    assert res["has_goal"] is False or res["has_success"] is False


def test_ensure_understand_config_provided_is_satisfied(tmp_path):
    """已传: config 提供 name/success_criteria/scope -> 判定已满足, 不触发 needs_input."""
    from ooda_pipeline import OODASteps
    task_work_dir = tmp_path / "loop-2026-09-02"
    task_work_dir.mkdir(parents=True, exist_ok=True)
    purpose = task_work_dir / "00-purpose.md"
    purpose.write_text("# purpose\\n## Goal\\n[done]\\n", encoding="utf-8")
    task_cfg = {"name": "demo", "success_criteria": [{"metric": "trades_count", "operator": "gt", "threshold": 0}], "scope": {"allow": [], "deny": []}}
    res = OODASteps._ensure_understand(None, task_cfg, task_work_dir, require_input=True)
    assert res["fields_ok"] is True
    assert res.get("needs_input") is False


# ---- Todo 4: failure-mode CN labels + verdict/stop_reason alignment ----

def test_findings_section_mode_cn():
    md = build_customer_report(
        task="demo", domain="demo", summary=_summary(),
        failure_modes={"INSUFFICIENT_EVIDENCE": 2, "EXTREME_CHASE": 1})
    assert "证据不足" in md
    assert "极端位置追单" in md
    assert "绝对位置盲区" not in md  # mode not present -> not rendered


@pytest.mark.parametrize("stop,expected", [
    ("No new patterns in this round", "WARN"),
    ("no progress across rounds", "WARN"),
    ("no new patterns reached", "WARN"),
    ("stop.completion reached", "STOP"),
    ("completed after max rounds", "STOP"),
    ("time limit exceeded", "STOP"),
    ("token budget exhausted", "STOP"),
    ("error in backtest contract", "ERR"),
    ("normal finish", "OK"),
])
def test_classify_stop_no_new_maps_warn(stop, expected):
    assert classify_stop(stop) == expected


@pytest.mark.parametrize("stop,expected", [
    ("stop.completion", "STOP"),
    ("completed", "STOP"),
])
def test_classify_stop_stop_completion_maps_stop(stop, expected):
    assert classify_stop(stop) == expected


# ---- Todo 7: risk/evidence ref & file:line self-validation ----

def test_validate_risk_evidence():
    bad = (
        "## 3. 风险分级（引用 scheme）\n\n"
        "| 项 | 等级 | 触发条件 | 响应 |\n"
        "|----|------|----------|------|\n"
        "| 语义验收缺失 | high | 结构报告不覆盖任务成功判定 | 7d |\n"
    )
    warns = validate_risk_evidence(bad)
    assert warns, "expected WARN for rows missing ref:/file:line:"

    good = (
        "## 3. 风险分级（引用 scheme）\n\n"
        "| 项 | 等级 | ref: | file:line: |\n"
        "|----|------|------|------------|\n"
        "| 语义验收缺失 | high | ref: scheme | file:line: report_util.py:128 |\n"
    )
    assert validate_risk_evidence(good) == []


def test_validate_risk_evidence_report_self_valid():
    md = build_customer_report(
        task="demo", domain="demo", summary=_summary(),
        failure_modes={"INSUFFICIENT_EVIDENCE": 2})
    assert validate_risk_evidence(md) == []


def test_input_ref_defaults_to_domain_aware_io_path():
    """P2-1: input_ref must be domain-aware and point at the io input,
    not the historical literal projects/<task>/data/signals.json."""
    md = build_customer_report(task="demo", domain="pm", summary=_summary())
    assert "input_ref: projects/pm/demo/data/loop_backtest_input.json" in md
    assert "input_ref: projects/demo/data/signals.json" not in md


def test_input_ref_accepts_explicit_override():
    """An explicit input_ref (e.g. resolved runtime io path) wins over the
    computed default so the real archived input is cited."""
    md = build_customer_report(task="demo", domain="demo", summary=_summary(),
                               input_ref="_data/loop_backtest_input.json")
    assert "input_ref: _data/loop_backtest_input.json" in md


def test_runreporter_resolves_input_ref_from_io_dir(tmp_path):
    """P2-1: RunReporter._resolve_input_ref returns the project-relative io
    input when the runtime io_dir materialises it; otherwise the conventional
    fallback (branch coverage for both paths)."""
    io_dir = tmp_path / "_data"
    io_dir.mkdir(parents=True)
    (io_dir / "loop_backtest_input.json").write_text("[]", encoding="utf-8")
    runtime = SimpleNamespace(io_dir=io_dir)
    reporter = RunReporter(_FakeStore(_summary(), []), runtime)
    assert reporter._resolve_input_ref(tmp_path) == "_data/loop_backtest_input.json"

    # io_dir absent and nothing on disk -> conventional fallback ref.
    bare = tmp_path / "bare"
    bare.mkdir()
    reporter2 = RunReporter(_FakeStore(_summary(), []), SimpleNamespace())
    assert reporter2._resolve_input_ref(bare) == "_data/loop_backtest_input.json"

    # io_dir points outside project_root -> relative_to raises; must not crash.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "loop_backtest_input.json").write_text("[]", encoding="utf-8")
    reporter3 = RunReporter(_FakeStore(_summary(), []), SimpleNamespace(io_dir=outside))
    ref = reporter3._resolve_input_ref(outside)
    assert isinstance(ref, str)
