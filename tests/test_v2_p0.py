"""
v2.0 P0 features tests:
  - P0-1: PatternStore.classify_failure / classify_success 
  - P0-2: Delta comparison in _observe()
  - P0-3: Inference annotation in StatusBar._tag()
  - P1: 5W1H scan in _ensure_understand() template
"""

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent / "sloth_engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from memory_store import PatternStore, FAILURE_MODES
from orchestrator import StatusBar, OODASteps


# ── P0-1: classify_failure ──────────────────────────────

def test_classify_failure_extreme_chase():
    assert PatternStore.classify_failure({"failure_reason": "extreme chase entry"}) == "EXTREME_CHASE"

def test_classify_failure_blindspot():
    assert PatternStore.classify_failure({"failure_reason": "absolute blindspot area"}) == "ABSOLUTE_BLINDSPOT"

def test_classify_failure_stopped_out():
    assert PatternStore.classify_failure({"failure_reason": "stop loss hit before tp reached"}) == "STOPPED_OUT_FIRST"

def test_classify_failure_direction_bias():
    assert PatternStore.classify_failure({"failure_reason": "direction bias detected"}) == "DIRECTION_BIAS"

def test_classify_failure_ranging():
    assert PatternStore.classify_failure({"failure_reason": "ranging fakeout signal"}) == "RANGING_FAKEOUT"

def test_classify_failure_default():
    assert PatternStore.classify_failure({"failure_reason": "unknown reason"}) == "INSUFFICIENT_EVIDENCE"

def test_classify_failure_empty_reason():
    assert PatternStore.classify_failure({}) == "INSUFFICIENT_EVIDENCE"


# ── P0-1: classify_success ──────────────────────────────

def test_classify_success_trend():
    assert PatternStore.classify_success({"signal_pattern": "trend following signal"}) == "TREND_FOLLOWING"

def test_classify_success_mean_reversion():
    assert PatternStore.classify_success({"signal_pattern": "mean reversion setup"}) == "MEAN_REVERSION"

def test_classify_success_breakout():
    assert PatternStore.classify_success({"signal_pattern": "breakout confirmed pattern"}) == "BREAKOUT_CONFIRMED"

def test_classify_success_ranging():
    assert PatternStore.classify_success({"signal_pattern": "range bound signal"}) == "RANGING_REVERSAL"

def test_classify_success_default():
    assert PatternStore.classify_success({"signal_pattern": "something else"}) == "EVENT_DRIVEN"

def test_classify_success_empty():
    assert PatternStore.classify_success({}) == "EVENT_DRIVEN"


# ── P0-1: FAILURE_MODES ─────────────────────────────────

def test_failure_modes_count():
    assert len(FAILURE_MODES) == 6

def test_failure_modes_contains():
    assert "EXTREME_CHASE" in FAILURE_MODES
    assert "RANGING_FAKEOUT" in FAILURE_MODES
    assert "INSUFFICIENT_EVIDENCE" in FAILURE_MODES


# ── P0-1: _match (alias support) ─────────────────────────

def test_match_exact():
    rule = {"exclusion_rule": "ExtremeChase @ H240Trend"}
    sig = {"signal_pattern": "ExtremeChase pattern", "market_condition": "H240Trend upward"}
    assert PatternStore._match(sig, rule) is True

def test_match_alias():
    rule = {"exclusion_rule": "old_label"}
    sig = {"signal_pattern": "new_label", "aliases": ["old_label"]}
    assert PatternStore._match(sig, rule) is True

def test_match_no_match():
    rule = {"exclusion_rule": "XyzPattern"}
    sig = {"signal_pattern": "AbcSignal"}
    assert PatternStore._match(sig, rule) is False

def test_match_empty_rule():
    rule = {"exclusion_rule": ""}
    sig = {"signal_pattern": "anything"}
    assert PatternStore._match(sig, rule) is False


# ── P0-2: Delta comparison ───────────────────────────────

def test_observe_returns_delta_field():
    import tempfile, os
    db = Path(tempfile.gettempdir()) / "test_v2_delta.db"
    # Stale v0 DB from a prior run trips the migration gate
    # (auto_migrate defaults to False). Clear it so PatternStore builds a
    # fresh v5 store; the fail-closed gate is not weakened.
    db.unlink(missing_ok=True)
    store = PatternStore(str(db))
    obs = OODASteps._observe(store, 1, [], Path(tempfile.gettempdir()), None)
    assert "delta" in obs
    assert obs["delta"] == {}  # round 1 has no prior data
    try:
        os.unlink(db)
    except OSError:
        pass


# ── P0-3: Inference annotation ───────────────────────────

def test_annotation_disabled():
    bar = StatusBar(1, "test", annotation_enabled=False)
    assert bar._tag("data", "hello") == "hello"
    assert bar._tag("conclusion", "world") == "world"

def test_annotation_enabled_data():
    bar = StatusBar(1, "test", annotation_enabled=True)
    assert bar._tag("data", "hello") == "[数据] hello"

def test_annotation_enabled_inference():
    bar = StatusBar(1, "test", annotation_enabled=True)
    assert bar._tag("inference", "maybe") == "[推理] maybe"

def test_annotation_enabled_conclusion():
    bar = StatusBar(1, "test", annotation_enabled=True)
    assert bar._tag("conclusion", "done") == "[结论] done"

def test_annotation_unknown_passthrough():
    bar = StatusBar(1, "test", annotation_enabled=True)
    assert bar._tag("nonexistent", "x") == "x"


# ── P1: 5W1H in template ─────────────────────────────────

def test_ensure_understand_template_has_5w1h():
    import tempfile, os
    td = tempfile.mkdtemp()
    try:
        work_dir = Path(td)
        task_cfg = {"name": "test-task", "success_criteria": [{"metric": "trades", "operator": "gt", "threshold": 0}]}
        result = OODASteps._ensure_understand(None, task_cfg, work_dir)
        assert result["template_created"] is True

        content = (work_dir / "00-purpose.md").read_text(encoding="utf-8")
        assert "5W1H" in content
        assert "Who:" in content
        assert "What:" in content
        assert "Where:" in content
        assert "When:" in content
        assert "Why:" in content
        assert "How:" in content
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# Run
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed, failed = 0, []
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed.append(f"{t.__name__}: {e}")
    print(f"v2.0 P0-P1 Tests: {passed}/{len(tests)} passed")
    for f in failed:
        print(f"  FAIL {f}")
    if not failed:
        print("ALL PASSED")