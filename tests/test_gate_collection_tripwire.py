"""cycle-16 A + cycle-17 A: every test module must contribute tests to the gate.

Background: six files named ``test_*.py`` were actually manual scripts
(``def main(): ...`` + ``if __name__ == "__main__"``).  pytest collected **zero**
tests from them, so ``run_gate.py`` never enforced the ~630 lines of assertions
they contain -- a "contract file that exists but is not in the gate".

This tripwire makes that class of regression impossible to reintroduce: adding a
collectable-looking test file with no collectable test fails the suite.

cycle-17 A widened the scan: the first version used ``glob("test_*.py")``, i.e.
non-recursive and ``test_``-prefix only, so a ``tests/<sub>/test_x.py`` or a
pytest-collectable ``foo_test.py`` slipped past the tripwire.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("tests", "sloth_engine/tests")


def _collectable_names(tree: ast.Module) -> list[str]:
    """Names pytest would collect at module level (test_*/Test*)."""
    found: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                found.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            found.append(node.name)
    return found


def _iter_test_files(root: Path):
    """Every module pytest would try to collect, recursively.

    pytest's default python_files is ``test_*.py`` **or** ``*_test.py``; both
    are scanned, at any depth (cycle-17 A).
    """
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            name = path.name
            if name.startswith("test_") or name.endswith("_test.py"):
                yield path


def test_every_test_module_has_collectable_tests():
    offenders: list[str] = []
    for path in _iter_test_files(ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        if not _collectable_names(tree):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == [], (
        "these test files define no collectable test, so pytest silently "
        "collects zero tests from them and run_gate.py never enforces their "
        "assertions. Add a `def test_<name>():` entry (a thin wrapper around the "
        "existing main() is enough): %s" % offenders
    )


def test_the_tripwire_covers_every_pytest_collectable_name(tmp_path):
    """Guard the guard: the scanner must see test_*.py, *_test.py and subdirs."""
    t = tmp_path / "tests"
    (t / "sub").mkdir(parents=True)
    (t / "test_a.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (t / "b_test.py").write_text("def test_y():\n    pass\n", encoding="utf-8")
    (t / "sub" / "test_c.py").write_text("def test_z():\n    pass\n", encoding="utf-8")
    (t / "helper.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    (t / "notes.md").write_text("not python\n", encoding="utf-8")
    found = sorted(p.name for p in _iter_test_files(tmp_path))
    assert found == ["b_test.py", "test_a.py", "test_c.py"], found


def test_the_tripwire_flags_a_subdir_script_style_file(tmp_path):
    """The widened scan must actually catch what the old glob missed."""
    t = tmp_path / "tests" / "deep"
    t.mkdir(parents=True)
    bad = t / "test_script.py"
    bad.write_text("def main():\n    assert True\n", encoding="utf-8")
    offenders = []
    for path in _iter_test_files(tmp_path):
        if not _collectable_names(ast.parse(path.read_text(encoding="utf-8-sig"))):
            offenders.append(path.name)
    assert offenders == ["test_script.py"]


def test_the_tripwire_itself_is_collectable():
    """Guard against the guard: the checker must recognise its own test."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8-sig"))
    names = _collectable_names(tree)
    assert "test_every_test_module_has_collectable_tests" in names
