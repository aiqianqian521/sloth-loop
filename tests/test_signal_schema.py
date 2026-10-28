"""Tests for strict input-signal schema validation (signal_schema.py)."""
from __future__ import annotations

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from signal_schema import validate_signals  # noqa: E402


def _valid_signals():
    return [
        {"signal_pattern": "a", "market_condition": "up"},
        {"signal_pattern": "b"},
    ]


def test_valid_signals_accept():
    r = validate_signals(_valid_signals(), {}, strict=True)
    assert r["valid"] is True
    assert len(r["accepted"]) == 2
    assert r["accepted"][1]["market_condition"] == "unknown"  # default applied


def test_missing_pattern_rejected():
    r = validate_signals([{"signal_pattern": "x"}, {"foo": 1}], {}, strict=True)
    # second entry missing signal_pattern
    assert r["valid"] is False
    assert any(x["index"] == 1 and x["code"] == "SIG_SCHEMA_FIELD"
               for x in r["rejected"])


def test_non_string_pattern_rejected():
    r = validate_signals([{"signal_pattern": ""}, {"signal_pattern": 12}], {}, strict=True)
    assert r["valid"] is False
    assert len(r["rejected"]) == 2


def test_strict_false_does_not_fail_whole_batch():
    # strict=False: lenient (backward compat), still reports rejected
    r = validate_signals([{"signal_pattern": "ok"}, {"bad": 1}], {}, strict=False)
    assert r["accepted"] and r["rejected"]


def test_task_schema_required_field():
    task_cfg = {"signal_schema": {"fields": {
        "doc_type": {"required": True, "type": "string"}}}}
    ok = validate_signals([{"signal_pattern": "a", "doc_type": "novel"}],
                          task_cfg, strict=True)
    assert ok["valid"] is True
    bad = validate_signals([{"signal_pattern": "a"}], task_cfg, strict=True)
    assert bad["valid"] is False


def test_criteria_metric_warning_vs_strict():
    task = {"success_criteria": [{"metric": "vol", "operator": "gt", "threshold": 1}]}
    # lenient -> warning only
    r = validate_signals(_valid_signals(), task, strict=False)
    assert any("vol" in w for w in r["warnings"])
    # strict -> rejected
    rs = validate_signals(_valid_signals(), task, strict=True)
    assert rs["valid"] is False
