"""Worker 3 — WebUI slicing fix + WRAPPER_METRICS alignment tests.

Covers:
 a) no Python slicing E.g. ``[:N]`` remnants in the front-end (now a static file).
 b) WRAPPER_METRICS aligned with verifier/task_runner actual outputs.
 c) strict signal validation no longer mis-rejects valid total_pnl criteria.
"""
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBUI = REPO_ROOT / "sloth_engine" / "webui.py"
SCHEMA = REPO_ROOT / "sloth_engine" / "signal_schema.py"
STATIC_HTML = REPO_ROOT / "sloth_engine" / "webui" / "static" / "index.html"

sys.path.insert(0, str(REPO_ROOT / "sloth_engine"))


def _embedded_js_html() -> str:
    """Return the front-end HTML/JS content now living in webui/static/index.html."""
    return STATIC_HTML.read_text(encoding="utf-8")


# ---- a) WebUI embedded JS slicing -----------------------------------------

def test_webui_has_no_python_slice_syntax():
    """No ``${expr[:N]}`` Python slice remnants should survive in embedded JS."""
    js_html = _embedded_js_html()
    bad = re.findall(r"\[:\s*\d+\s*\]", js_html)
    assert not bad, f"Python slice syntax remnants in embedded JS: {bad}"


def test_webui_uses_js_slice():
    """Embedded JS should use JS-friendly .slice(0,N) truncation instead."""
    js_html = _embedded_js_html()
    assert ".slice(0," in js_html


def test_webui_docstring_mentions_dependencies():
    """webui.py docstring should note fastapi/uvicorn install + startup."""
    src = WEBUI.read_text(encoding="utf-8")
    for token in ("fastapi", "uvicorn"):
        assert token.lower() in src.lower(), f"webui.py docstring missing '{token}'"


# ---- b) WRAPPER_METRICS alignment -----------------------------------------

def test_wrapper_metrics_aligned_with_actual_outputs():
    from signal_schema import WRAPPER_METRICS
    # ghost field removed
    assert "filtered_count" not in WRAPPER_METRICS
    # every metric the verifier/task_runner actually emits must be allowed
    expected = {"signals_tested", "total_pnl", "trades_count", "win_rate", "sharpe"}
    assert expected <= WRAPPER_METRICS


# ---- c) strict validation regression --------------------------------------

def test_strict_total_pnl_criteria_not_misrejected():
    from signal_schema import validate_signals
    result = validate_signals(
        [{"signal_pattern": "s", "market_condition": "unknown"}],
        {"success_criteria": [{"metric": "total_pnl"}]},
        strict=True,
    )
    # total_pnl is now a wrapper metric -> no SIG_CRITERIA_METRIC rejection
    codes = [r.get("code") for r in result.get("rejected", [])]
    assert "SIG_CRITERIA_METRIC" not in codes
    assert result["valid"] is True
