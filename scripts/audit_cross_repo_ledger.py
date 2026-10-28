#!/usr/bin/env python
"""Cross-repo ledger sweep (cycle-22 A2).

tests/test_wake_pointer_chain.py guards *this* repo's ledger: every commit hash
its docs name must resolve in a known repo, and a name that resolves nowhere is
a failure.  Point that same rule set at a sibling corpus and it reports values
that are not defects at all -- dataset fingerprints, container ids, commits the
ledger itself records as amended away, foreign-repo baselines.

This tool applies the rules to such corpora and classifies every finding with
the shared classifier, so the sweep is reproducible instead of a one-off.

Exit 0 when every finding is explained; exit 1 when an unexplained "phantom"
remains.  It is a forensic reporter, NOT part of the pytest gate: the gate must
never depend on a sibling checkout's contents.

Usage:
  python scripts/audit_cross_repo_ledger.py [--json] [--repo NAME=PATH]...
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "tests" / "test_wake_pointer_chain.py"

# Sibling corpora the ledger cites; an absent checkout is skipped, not
# invented.  Defaults are DERIVED from this checkout's own location (siblings
# <workspace>/loop-dev and <workspace>/../skill/wend/...), so no source
# machine's absolute path is baked in; SLOTH_LEGACY_REPO / SLOTH_ARCH_REPO
# override them when the siblings live elsewhere.
DEFAULT_TARGETS = (
    ("sloth-loop",
     os.environ.get("SLOTH_LEGACY_REPO") or str(ROOT.parent / "loop-dev")),
    ("architect-skills",
     os.environ.get("SLOTH_ARCH_REPO")
     or str(ROOT.parent.parent / "skill" / "wend"
            / "architect-skills-offline-bundle" / "architect-skills")),
)


def load_guard():
    """Import the guard module by path (tests/ is not a package)."""
    spec = importlib.util.spec_from_file_location("_wake_pointer_guard", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shipped_markdown(root: pathlib.Path) -> list:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others",
         "--exclude-standard"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [f for f in out.stdout.splitlines() if f.lower().endswith(".md")]


def sweep(guard, repos, targets) -> list:
    report = []
    for name, raw_root in targets:
        root = pathlib.Path(raw_root)
        if not (root / ".git").exists():
            report.append({"repo": name, "path": str(root), "present": False})
            continue
        files = shipped_markdown(root)
        findings = []
        for rel in files:
            try:
                text = (root / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line, token, klass in guard.classify_document(rel, text, repos):
                findings.append({"file": rel, "line": line,
                                 "token": token, "class": klass})
        counts: dict = {}
        for f in findings:
            counts[f["class"]] = counts.get(f["class"], 0) + 1
        report.append({"repo": name, "path": str(root), "present": True,
                       "files": len(files), "counts": counts,
                       "findings": findings})
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="cross-repo ledger sweep")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--repo", action="append", default=[], metavar="NAME=PATH",
                        help="extra corpus to sweep (repeatable)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    guard = load_guard()
    repos = guard._known_repos()
    targets = list(DEFAULT_TARGETS)
    for item in args.repo:
        name, _, path = item.partition("=")
        targets.append((name or path, path))

    report = sweep(guard, repos, targets)
    unexplained = [f for r in report if r.get("present")
                   for f in r["findings"] if f["class"] == "phantom"]

    if args.json:
        print(json.dumps({"known_repos": [n for n, _ in repos],
                          "report": report, "unexplained": unexplained}, indent=2))
    else:
        print("known repos: %s" % ", ".join(n for n, _ in repos))
        for r in report:
            if not r.get("present"):
                print("== %s: no checkout at %s (skipped)" % (r["repo"], r["path"]))
                continue
            print("== %s: %d shipped .md, %d finding(s) %s"
                  % (r["repo"], r["files"], len(r["findings"]), r["counts"]))
            for f in r["findings"]:
                print("   %s:%d [%s] %s"
                      % (f["file"], f["line"], f["class"], f["token"]))
        print("unexplained: %d" % len(unexplained))
        for f in unexplained:
            print("   PHANTOM %s:%d %s" % (f["file"], f["line"], f["token"]))
    return 1 if unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
