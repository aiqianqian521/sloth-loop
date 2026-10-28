#!/usr/bin/env python
"""Orphan-mechanism gate (cycle-11 N-1): a sloth_engine mechanism with no caller.

Why: cycle-9/10 landed mechanism modules whose wiring was never closed
(G-5 `step_exception_policy`, G-6 `quota_window`) and the gap was only caught
by a hand-run `git grep`. This gate turns "mechanism landed but not wired" into
a machine verdict, so a regression fails in run_gate.py instead of being
rediscovered by a human.

Rule (deliberately narrow, to stay false-positive free):
  * candidates are top-level ``sloth_engine/*.py`` modules only;
  * a candidate must look like a reusable mechanism: at least one top-level
    def / async def / class (pure tooling scripts such as ``_strip_bom.py`` are
    therefore skipped);
  * ``__init__``/dunder modules, ``sloth_engine/tests/``, ``sloth_engine/_archive/``,
    ``scripts/tmp/`` (gitignored scratch) and ``__pycache__`` are out of scope;
  * an edge is any static import (AST, utf-8-sig / BOM tolerant), any literal
    ``import_module("x")`` / ``__import__("x")`` call, or any quoted string
    literal ``"x"`` / ``'x'`` in production code (a conservative catch-all for
    config-driven dynamic loaders);
  * classification:
      wired      - referenced by >=1 non-test .py     -> OK
      test_only  - referenced only from tests/        -> reported, NOT a failure
                   (these are the documented "reference implementations")
      orphan     - referenced by nobody               -> FAIL unless exempt
  * EXEMPT entries carry a reason + a tracking ref and must stay live: an
    exemption whose module is missing or already wired is itself a failure
    (stale exemption), so the list cannot silently rot.

Stdlib-only; imports nothing from sloth_engine, so it is safe to run from the
pre-commit gate and from isolated tests.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings
from pathlib import Path

# Exemptions: module -> reason. Every entry MUST justify itself and name a
# tracking item. Re-review each cycle: a stale entry fails the gate.
EXEMPT = {
    "tool_concurrency": (
        "P1-1 batch tool scheduler (DSH tool-calls.ts analogue). No production "
        "call site exists: the OODA Act step dispatches exactly one tool per "
        "round (ooda_pipeline._act -> registry.dispatch(exec_type, ...)), so a "
        "batch scheduler has no producer yet. Kept as an opt-in reference "
        "mechanism; re-evaluate when a multi-tool Act model lands. "
        "Tracking: cycle-11 N-2 / I-2."
    ),
}

_SCAN_DIRS = ("sloth_engine", "tests", "scripts")
_DYNAMIC_CALL_NAMES = ("import_module", "__import__")
# This scanner quotes exempt module names, which would look like a caller edge;
# skip its own source so EXEMPT cannot mask a real orphan.
_SELF_STEM = Path(__file__).stem


def _parse(path: Path):
    try:
        with warnings.catch_warnings():
            # An invalid escape in a docstring (e.g. a Windows path or a regex
            # sample) makes compile() emit a DeprecationWarning; a scanner must
            # not spam it. The real pytest run still surfaces such warnings.
            warnings.simplefilter("ignore")
            return ast.parse(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _edges(tree) -> set[str]:
    """Module names referenced by one parsed file (static, dynamic, quoted)."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else None)
            if name in _DYNAMIC_CALL_NAMES and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    found.add(a0.value.split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            head = node.value.split(".")[0]
            if head:
                found.add(head)
    return found


def _is_mechanism(tree) -> bool:
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               for n in tree.body)


def _iter_py(root: Path):
    out = []
    for d in _SCAN_DIRS:
        base = root / d
        if base.is_dir():
            out.extend(sorted(base.rglob("*.py")))
    out.extend(sorted(root.glob("*.py")))
    return out


def _is_test(rel: str) -> bool:
    return rel.startswith("tests/") or rel.startswith("sloth_engine/tests/")


def _out_of_scope(rel: str) -> bool:
    return ("__pycache__" in rel or rel.startswith("sloth_engine/_archive/")
            or rel.startswith("_archive/") or rel.startswith("scripts/tmp/"))


def scan(root, exempt=None) -> dict:
    """Classify sloth_engine mechanism modules. Returns a findings dict."""
    root = Path(root).resolve()
    engine = root / "sloth_engine"
    exempt = dict(EXEMPT if exempt is None else exempt)

    prod_refs: dict[str, set[str]] = {}
    test_refs: dict[str, set[str]] = {}
    trees: dict[str, object] = {}
    for p in _iter_py(root):
        rel = p.relative_to(root).as_posix()
        if _out_of_scope(rel) or p.stem == _SELF_STEM:
            continue
        tree = _parse(p)
        if tree is None:
            continue
        trees[rel] = tree
        bucket = test_refs if _is_test(rel) else prod_refs
        for name in _edges(tree):
            bucket.setdefault(name, set()).add(rel)

    names = set(exempt)
    for p in sorted(engine.glob("*.py")):
        if p.name.startswith("__"):
            continue
        tree = trees.get("sloth_engine/" + p.name)
        if tree is None:
            tree = _parse(p)
        if tree is not None and _is_mechanism(tree):
            names.add(p.stem)

    findings = {"wired": [], "test_only": [], "orphan": [],
                "exempt": [], "stale_exempt": []}
    for mod in sorted(names):
        self_rel = "sloth_engine/%s.py" % mod
        prod = {q for q in prod_refs.get(mod, ()) if q != self_rel}
        test = {q for q in test_refs.get(mod, ()) if q != self_rel}
        exists = (engine / (mod + ".py")).is_file()
        if mod in exempt:
            if not exists or prod:
                findings["stale_exempt"].append(mod)
            else:
                findings["exempt"].append(mod)
            continue
        if not exists:
            continue
        if prod:
            findings["wired"].append(mod)
        elif test:
            findings["test_only"].append(mod)
        else:
            findings["orphan"].append(mod)
    return findings


def check(root=None, exempt=None) -> list[str]:
    """Return violation strings (empty == OK). Never raises on a missing tree."""
    if root is None:
        root = Path(__file__).resolve().parent.parent
    findings = scan(root, exempt)
    problems: list[str] = []
    for mod in findings["orphan"]:
        problems.append(
            "orphan mechanism (no caller): sloth_engine/%s.py - wire it or add "
            "an EXEMPT entry with a reason + tracking ref." % mod)
    for mod in findings["stale_exempt"]:
        problems.append(
            "stale exemption (module missing or already wired): %s - remove it "
            "from EXEMPT." % mod)
    return problems


def _report(findings: dict) -> None:
    for key in ("wired", "test_only", "exempt", "orphan", "stale_exempt"):
        items = findings.get(key, [])
        print("  %-13s %d %s" % (key + ":", len(items), ", ".join(items)))
    print("  test_only is informational: a mechanism exercised only by tests "
          "(a documented reference implementation) does not fail the gate.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="sloth_engine orphan-mechanism gate")
    ap.add_argument("--root", default=None, help="repo root (default: this repo)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--list-exempt", action="store_true", help="show EXEMPT reasons")
    args = ap.parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    findings = scan(root)
    if args.json:
        print(json.dumps(findings, indent=2, sort_keys=True))
    if args.list_exempt:
        for mod, reason in sorted(EXEMPT.items()):
            print("EXEMPT %s: %s" % (mod, reason))
        return 0
    print("[orphan-mechanisms] scan root: %s" % root)
    _report(findings)
    problems = check(root)
    if problems:
        for p in problems:
            print("[orphan-mechanisms] FAIL: " + p, file=sys.stderr)
        return 1
    print("[orphan-mechanisms] OK: every sloth_engine mechanism has a caller "
          "(or an explicit, live exemption).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())