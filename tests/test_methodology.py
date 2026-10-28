"""测试方法级经验复用 — 增强-P2"""

import sys, tempfile
from pathlib import Path
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from memory_store import PatternStore


def make_store():
    tmp = tempfile.mkdtemp()
    return PatternStore(Path(tmp) / "test.db"), tmp


def test_rule_type_defaults_to_signal():
    store, tmp = make_store()
    store.append_failure([{
        "id": "F-001", "signal_pattern": "test",
        "market_condition": "any", "failure_mode": "EXTREME_CHASE",
        "status": "open",
    }])
    f = store.find_failure("test", "any")
    assert f is not None


def test_methodology_rule_added():
    store, tmp = make_store()
    store.append_failure([{
        "id": "F-002", "signal_pattern": "single_window_methodology",
        "market_condition": "any", "failure_mode": "EXTREME_CHASE",
        "status": "resolved",
        "exclusion_rule": "methodology:single_window",
        "rule_type": "methodology",
        "root_cause": "单窗口结论不可信",
    }])
    rules = store.get_methodology_rules()
    assert len(rules) >= 1
    assert any("single_window" in r.get("exclusion_rule", "") for r in rules)


def test_check_methodology_single_window_violation():
    store, tmp = make_store()
    store.append_failure([{
        "id": "F-003", "signal_pattern": "method_error",
        "market_condition": "any", "failure_mode": "EXTREME_CHASE",
        "status": "resolved",
        "exclusion_rule": "methodology:single_window",
        "rule_type": "methodology",
        "root_cause": "只测了3M窗口",
    }])
    result = store.check_methodology({"windows": 1})
    assert not result["passed"]
    assert len(result["violations"]) >= 1


def test_check_methodology_passes_with_5_windows():
    store, tmp = make_store()
    store.append_failure([{
        "id": "F-004", "signal_pattern": "method_error",
        "market_condition": "any", "failure_mode": "EXTREME_CHASE",
        "status": "resolved",
        "exclusion_rule": "methodology:single_window",
        "rule_type": "methodology",
    }])
    result = store.check_methodology({"windows": 5})
    assert result["passed"]


def test_check_methodology_no_param_scan():
    store, tmp = make_store()
    store.append_failure([{
        "id": "F-005", "signal_pattern": "no_scan_error",
        "market_condition": "any", "failure_mode": "EXTREME_CHASE",
        "status": "resolved",
        "exclusion_rule": "methodology:no_param_scan",
        "rule_type": "methodology",
    }])
    result = store.check_methodology({"param_values": 0})
    assert not result["passed"]


def test_check_methodology_mixed_scenarios():
    store, tmp = make_store()
    store.append_failure([{
        "id": "F-006", "signal_pattern": "mixed_error",
        "market_condition": "any", "failure_mode": "EXTREME_CHASE",
        "status": "resolved",
        "exclusion_rule": "methodology:mixed_scenarios",
        "rule_type": "methodology",
    }])
    result = store.check_methodology({"scenario": "all"})
    assert not result["passed"]
    result2 = store.check_methodology({"scenario": "震荡"})
    assert result2["passed"]


def test_check_methodology_no_rules_passes():
    store, tmp = make_store()
    result = store.check_methodology({"windows": 1})
    assert result["passed"]