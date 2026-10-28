"""Regression tests for the second batch of fail-closed fixes (P1/D-batch).

Covers:
  D9  purity_check must parse UTF-8-BOM plugin entry files (no false positive)
  D8  signal_pool must not crash on a non-UTF-8 (legacy/GBK) signals file
  D4  load_config(require_exists=True) must raise on a missing file
  D7  verifier._compare must fail closed (not crash) on a non-numeric threshold
  P0D run_gate.py must support --all (run the full gate without git staging)
"""
from __future__ import annotations

import ast
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from config_util import load_config  # noqa: E402
from plugin_loader import PluginHost  # noqa: E402
from signal_pool import SignalPool  # noqa: E402
from tool_registry import ToolRegistry  # noqa: E402
from verifier import Verifier  # noqa: E402


# --------------------------------------------------------------------------
# D9 - purity gate must not flag a UTF-8-BOM entry.py as unparseable
# --------------------------------------------------------------------------
def _make_plugin(root: Path, pid: str, ptype: str, entry_bytes: bytes) -> None:
    d = root / ptype / pid
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"id": pid, "version": "0.1.0", "type": ptype, "entry": "entry.py",
                "extension_points": ["tool"], "inject": [], "lazy": True,
                "description": "example"}
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "entry.py").write_bytes(entry_bytes)


def _host(root: Path):
    from plugin_roster import PluginRoster
    h = PluginHost(root, ToolRegistry(), roster=PluginRoster.from_config({}))
    h.discover()
    return h


def test_purity_check_tolerates_bom_entry(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    body = b"def register(ctx):\n    return None\n"
    _make_plugin(root, "bom-plugin", "backtest", b"\xef\xbb\xbf" + body)  # UTF-8 BOM
    _make_plugin(root, "plain-plugin", "backtest", body)
    host = _host(root)
    violations = host.purity_check()
    # The BOM plugin is valid code; the gate must not call it unparseable.
    assert not any("cannot parse" in v for v in violations), violations


def test_purity_check_still_flags_cross_plugin_import(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _make_plugin(root, "sib", "backtest", b"import plugins.backtest.other.entry\n")
    host = _host(root)
    violations = host.purity_check()
    assert any("cross-plugin import" in v for v in violations), violations


# --------------------------------------------------------------------------
# D8 - non-UTF-8 signals file must be handled (fail closed), not crash
# --------------------------------------------------------------------------
def test_signal_pool_non_utf8_is_handled(tmp_path: Path) -> None:
    bad = tmp_path / "gbk_signals.json"
    bad.write_bytes(b'[{"signal_pattern":"\xd6\xd0\xce\xc4"}]')  # invalid UTF-8
    pool = SignalPool(str(bad), 10, REPO / "sloth_engine")
    result = pool.load()  # must NOT raise UnicodeDecodeError
    assert result == []


def test_signal_pool_valid_still_loads(tmp_path: Path) -> None:
    good = tmp_path / "ok.json"
    good.write_text(json.dumps([{"signal_pattern": "p", "weight": 1}]), encoding="utf-8")
    pool = SignalPool(str(good), 10, REPO / "sloth_engine")
    assert len(pool.load()) == 1


# --------------------------------------------------------------------------
# D4 - load_config require_exists switch
# --------------------------------------------------------------------------
def test_load_config_missing_returns_defaults_by_default(tmp_path: Path) -> None:
    assert load_config(str(tmp_path / "nope.yaml"), defaults={"a": 1}) == {"a": 1}


def test_load_config_missing_raises_when_required(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"), {}, require_exists=True)


def test_load_config_present_ok_with_require_exists(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"k": 1}), encoding="utf-8")
    assert load_config(str(p), {}, require_exists=True) == {"k": 1}


# --------------------------------------------------------------------------
# D7 - verifier fails closed on a non-numeric threshold (no TypeError)
# --------------------------------------------------------------------------
def test_compare_non_numeric_threshold_fails_closed() -> None:
    assert Verifier._compare(5, "gt", "abc") is False  # was TypeError before
    assert Verifier._compare(5, "gte", None) is False


def test_compare_numeric_threshold_unaffected() -> None:
    assert Verifier._compare(5, "gt", 3) is True
    assert Verifier._compare(5, "lt", 3) is False


def test_compare_unknown_operator_still_fails_closed() -> None:
    assert Verifier._compare(5, "gt2", 3) is False


# --------------------------------------------------------------------------
# P0D - run_gate.py supports --all
# --------------------------------------------------------------------------
def test_run_gate_has_all_flag() -> None:
    src = (REPO / "scripts" / "run_gate.py").read_text(encoding="utf-8-sig")
    assert '"--all"' in src
    ast.parse(src)  # still valid python


# --------------------------------------------------------------------------
# P1-3 - corrupt store fails closed with an actionable, file-scoped error
# --------------------------------------------------------------------------
def test_corrupt_db_raises_actionable_error(tmp_path) -> None:
    from memory_store import CorruptDatabaseError, PatternStore
    bad = tmp_path / "corrupt.db"
    bad.write_bytes(bytes(range(0, 64)) * 40)  # not a SQLite file
    with pytest.raises(CorruptDatabaseError) as ei:
        PatternStore(str(bad))
    err = ei.value
    assert err.path.endswith("corrupt.db")
    assert "not a valid SQLite" in str(err)
    assert err.hint  # actionable guidance present
    assert isinstance(err.__cause__, sqlite3.DatabaseError)


def test_empty_existing_db_is_provisioned_not_corrupt(tmp_path) -> None:
    """A zero-length file is 'not existed' -> provisioned, never mistaken
    for corruption (branch: existed=False)."""
    from memory_store import PatternStore
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")  # size 0 -> treated as fresh
    store = PatternStore(str(empty))
    assert empty.stat().st_size > 0  # schema materialised
    assert store.schema_version() >= 1


def test_valid_db_reopens_without_error(tmp_path) -> None:
    """A healthy store reopens cleanly (branch: valid existing file)."""
    from memory_store import PatternStore
    good = tmp_path / "good.db"
    PatternStore(str(good))
    PatternStore(str(good))  # no raise


# ---------------------------------------------------------------------------
# docs baseline consistency guard (scripts/docs_baseline.py + run_gate wiring)
# ---------------------------------------------------------------------------


def _docs_baseline_mod():
    import importlib.util
    p = REPO / "scripts" / "docs_baseline.py"
    spec = importlib.util.spec_from_file_location("docs_baseline_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_docs_baseline_json_is_single_source_and_wellformed() -> None:
    b = json.loads((REPO / "docs" / "baseline.json").read_text(encoding="utf-8"))
    for k in ("passed", "xfailed", "coverage", "fail_under", "head", "updated"):
        assert k in b, "docs/baseline.json 缺字段: " + k
    assert isinstance(b["passed"], int) and b["passed"] > 0
    # fail_under must match pyproject (one floor, two places that must agree)
    pp = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    import re as _re
    m = _re.search(r"fail_under\s*=\s*([0-9]+)", pp)
    assert m and int(m.group(1)) == b["fail_under"], (
        "baseline.json fail_under 与 pyproject 不一致")


def test_docs_baseline_guard_passes_on_repo() -> None:
    """当前库内实测：所有当前态文档口径与 baseline.json 一致。"""
    mod = _docs_baseline_mod()
    problems = mod.check(REPO)
    assert problems == [], "docs 口径漂移: " + repr(problems)


def test_docs_baseline_guard_detects_drift(tmp_path) -> None:
    """负控：若某当前态文档数字被改小，守护必须报出漂移。"""
    mod = _docs_baseline_mod()
    base = json.loads((REPO / "docs" / "baseline.json").read_text(encoding="utf-8"))
    # build a fake repo: copy only the files the guard checks
    d = tmp_path / "docs"; d.mkdir()
    bad_passed = str(base["passed"] - 999)
    (d / "baseline.json").write_text(json.dumps(base), encoding="utf-8")
    for rel in mod.CHECK_FILES:
        p = tmp_path / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("baseline " + bad_passed + " passed coverage 72.13% fail_under=70\n",
                     encoding="utf-8")
    problems = mod.check(tmp_path)
    assert problems, "负控失败：守护未报出刻意漂移。"


def test_run_gate_invokes_docs_baseline_guard() -> None:
    """run_gate.py 已接入 docs-baseline 守护（防漏接）。"""
    src = (REPO / "scripts" / "run_gate.py").read_text(encoding="utf-8-sig")
    assert "docs_baseline" in src and "docs-baseline" in src
