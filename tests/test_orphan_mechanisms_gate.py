"""Contract tests for the cycle-11 N-1 orphan-mechanism gate.

The gate (scripts/check_orphan_mechanisms.py) fails when a top-level
sloth_engine module that looks like a reusable mechanism (>=1 top-level
def/class) has no caller. These tests pin the classification rules and the
run_gate wiring so the gate cannot silently rot.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_orphan_mechanisms.py"


def _load():
    spec = importlib.util.spec_from_file_location("orphan_gate_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _mk(root: Path, rel: str, text: str, *, bom: bool = False) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8-sig" if bom else "utf-8")
    return p


# ---- the real repo is clean -------------------------------------------------

def test_real_repo_has_no_orphan_or_stale_exemption() -> None:
    problems = mod.check(REPO)
    assert problems == [], "orphan-mechanism gate must be green on HEAD: %r" % problems


def test_every_exemption_carries_a_reason_and_tracking_ref() -> None:
    for name, reason in mod.EXEMPT.items():
        assert name and isinstance(reason, str) and len(reason) > 20
        assert "Tracking:" in reason, "EXEMPT[%s] must name a tracking item" % name


def test_run_gate_invokes_the_orphan_gate() -> None:
    src = (REPO / "scripts" / "run_gate.py").read_text(encoding="utf-8-sig")
    assert "check_orphan_mechanisms" in src
    assert "orphan" in src


# ---- classification rules (synthetic trees pass exempt={} so the repo-wide
# ---- EXEMPT list does not leak into the fixture) ----------------------------

def test_orphan_mechanism_is_flagged(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/ghost.py", "def f():\n    return 1\n")
    problems = mod.check(tmp_path, {})
    assert any("ghost" in p for p in problems)
    assert mod.scan(tmp_path, {})["orphan"] == ["ghost"]


def test_mechanism_imported_by_production_is_wired(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/lib.py", "class L:\n    pass\n")
    _mk(tmp_path, "sloth_engine/consumer.py", "import lib\n")
    findings = mod.scan(tmp_path, {})
    assert findings["wired"] == ["lib"]
    assert mod.check(tmp_path, {}) == []


def test_module_imported_only_by_tests_is_informational(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/refonly.py", "class R:\n    pass\n")
    _mk(tmp_path, "tests/test_refonly.py", "import refonly\n")
    findings = mod.scan(tmp_path, {})
    assert findings["test_only"] == ["refonly"]
    assert findings["orphan"] == []
    assert mod.check(tmp_path, {}) == []


def test_tooling_script_without_defs_is_out_of_scope(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/_tool.py", "print('strip')\n")
    assert mod.scan(tmp_path, {})["orphan"] == []
    assert mod.check(tmp_path, {}) == []


def test_bom_encoded_importer_is_detected(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/lib2.py", "class L:\n    pass\n")
    _mk(tmp_path, "sloth_engine/consumer2.py", "import lib2\n", bom=True)
    assert mod.scan(tmp_path, {})["wired"] == ["lib2"]


def test_dynamic_import_literal_is_detected(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/lib3.py", "class L:\n    pass\n")
    _mk(tmp_path, "sloth_engine/loader.py",
        "import importlib\n\n\ndef go():\n"
        "    return importlib.import_module('lib3')\n")
    assert mod.scan(tmp_path, {})["wired"] == ["lib3"]


# ---- exemption lifecycle ----------------------------------------------------

def test_live_exemption_suppresses_orphan(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/keep.py", "def f():\n    return 1\n")
    exempt = {"keep": "reason text long enough; Tracking: cycle-11"}
    assert mod.check(tmp_path, exempt) == []
    assert mod.scan(tmp_path, exempt)["exempt"] == ["keep"]


def test_missing_exemption_target_is_stale(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/keep.py", "def f():\n    return 1\n")
    exempt = {"keep": "ok; Tracking: x", "not_there": "ok; Tracking: x"}
    problems = mod.check(tmp_path, exempt)
    assert any("not_there" in p and "stale" in p for p in problems)
    assert not any("sloth_engine/keep.py" in p for p in problems)


def test_exemption_for_wired_module_is_stale(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/dup.py", "def f():\n    return 1\n")
    _mk(tmp_path, "sloth_engine/user.py", "import dup\n")
    problems = mod.check(tmp_path, {"dup": "old; Tracking: x"})
    assert any("dup" in p and "stale" in p for p in problems)


def test_dunder_and_archive_modules_are_out_of_scope(tmp_path: Path) -> None:
    _mk(tmp_path, "sloth_engine/__init__.py", "def f():\n    return 1\n")
    _mk(tmp_path, "sloth_engine/_archive/old.py", "def f():\n    return 1\n")
    assert mod.check(tmp_path, {}) == []