#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""docs baseline-consistency guard (L1 文档口径守护).

Single source of truth: docs/baseline.json (passed/xfailed/coverage/fail_under).
This module asserts that every CURRENT-STATE doc quotes the same baseline
numbers, so "文档说的" and "实测的" can no longer drift silently.

Historical sections (ROADMAP §4, CHANGELOG history, AS-BUILT cycle-2, dated
updates) are intentionally OUT of scope. The guard only checks the files in
CHECK_FILES, and it reads the expected numbers (passed / coverage / fail_under)
from docs/baseline.json instead of hard-coding them here, so this module can no
longer go stale when the baseline moves (cycle-17 A).

cycle-26 A: the guard asserted that the baseline number *appears* in a doc --
never that the doc's *other* suite counts are labelled.  cycle-24 recorded
that as a known boundary: a stale count one line away from the live one
passed verbatim.  A stale number that gets read as today's is exactly the
drift this guard exists to stop, so the boundary is now closed: every suite
count in a checked doc (3+ digits -- shorter tokens are step counters such
as "1/1 passed", not suite sizes) must be either the baseline itself, or
anchored *inside its own block* by a date ("20xx"), a cycle id ("cycle-N")
or the explicit word 历史 ("historical").

A block is a run of non-blank lines that starts at a list item, a heading or
a blockquote -- i.e. the bullet / paragraph the number lives in.  A dated bullet may
quote that era's numbers, but an unlabelled number may not sit next to the
live one.  The escape hatch is deliberately coarse and human: label the
block (usually the section heading) as historical.  The failure mode being
closed is not "someone lied", it is "an old number was never labelled and
got read as today's".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "docs" / "baseline.json"

# Current-state docs that MUST quote the baseline. Historical docs are excluded.
CHECK_FILES = (
    "README.md",
    # cycle-41 A: the handoff entry doc (the file a fresh agent is told to
    # read FIRST, per START.md) quotes the same baseline numbers; it was the
    # one current-state doc left out of this hand-written list, so its numbers
    # rotted from 1159 to 1760 with nothing to catch it -- the cycle-24
    # wake-pointer gap, one file further out (a hand-written scope can
    # silently omit an input).
    "START.md",
    "CLAUDE.md",
    "RUNBOOK.md",
    "ONBOARDING.md",
    "Prompt.md",
    "docs/sloth-loop-AS-BUILT.md",
    "docs/sloth-loop-ROADMAP.md",
    "docs/sloth-loop-DEV-SETUP.md",
    "docs/sloth-loop-USAGE.md",
    # cycle-24 A: the wake pointer is a current-state doc too -- it is
    # the first file a fresh agent reads and it quotes the same numbers.
    "docs/flow/GRAND-LOOP.md",
    # cycle-42 A: three more current-state docs that quote the suite
    # numbers were still outside this hand-written scope -- the quickstart
    # checklist (the "how to verify before you ship" entry point), the
    # sloth_engine README (the component doc a newcomer reads first) and the
    # full project introduction.  Their numbers had rotted (QUICKSTART said
    # "700+ ... coverage>=64%"; the engine README said "v3.4 ... 490 passed";
    # the intro said 1194/72.13%).  Same family as cycle-41 (START.md) and
    # cycle-24 (the wake pointer): a hand-written scope can silently omit an
    # input.  The Chinese path is written escaped so this source stays ASCII.
    "docs/sloth-loop-QUICKSTART.md",
    "sloth_engine/README.md",
    "docs/sloth-loop-\u9879\u76ee\u4ecb\u7ecd\u4e0e\u89c4\u5212.md",
    # 2026-10-28: the project-history narrative states the live baseline
    # too (it is the doc a reader hits right after the rename); cover it.
    "docs/HISTORY.md",
    # 2026-10-28: the future-extension plan (AI Team / 蜂群 + 自主进化) quotes the
    # live baseline too -- cover it the same way ROADMAP is covered.
    "docs/sloth-loop-AI-TEAM-AND-SELF-EVOLUTION.md",
)


def load_baseline(path: Path = BASELINE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- anchors -----------------------------------------------------------------
# A suite count may be quoted as-is only when it *is* the baseline, or when
# the block it lives in is visibly historical.  Machine-recognisable anchors:
# a date (20xx...), a cycle id (cycle-N), or the literal word 历史.
HISTORY = "\u5386\u53f2"   # 历史, written escaped so this source stays ASCII
ANCHOR_RE = re.compile(r"20\d\d|cycle-\d+|" + re.escape(HISTORY))
# Suite counts are 3+ digits: "1/1 passed" is a step counter, not a suite size.
SUITE_COUNT_RE = re.compile(r"(?<!\d)(\d{3,})\s+passed\b")
# A new list item, heading or blockquote starts a fresh anchor block.
BLOCK_START_RE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|>)")


def blocks(text: str) -> list[tuple[int, list[str]]]:
    """Split a document into anchor blocks: runs of non-blank lines, where a
    new list item, heading or blockquote starts a fresh block.

    Returns [(first_line_no, [lines])] with 1-based line numbers, so a
    historical number may borrow its anchor from anywhere in its own bullet.
    """
    out: list[tuple[int, list[str]]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if out and not BLOCK_START_RE.match(line):
            out[-1][1].append(line)
        else:
            out.append((lineno, [line]))
    return out


def unanchored_suite_counts(text: str, passed: str) -> list[tuple[str, str]]:
    """Every suite count that is neither the baseline nor anchored in its block.

    Returns [("line 169", "758")]; callers turn these into violations.
    """
    found: list[tuple[str, str]] = []
    for first, lines in blocks(text):
        anchored = bool(ANCHOR_RE.search("\n".join(lines)))
        for offset, line in enumerate(lines):
            for m in SUITE_COUNT_RE.finditer(line):
                if m.group(1) == passed or anchored:
                    continue
                found.append(("line %d" % (first + offset), m.group(1)))
    return found


def check(repo: Path = REPO) -> list[str]:
    """Return a list of violation strings (empty == OK). Never raises on missing files."""
    b = load_baseline(repo / "docs" / "baseline.json")
    passed = str(b["passed"])
    cov = str(b["coverage"]).rstrip("%")
    fu = str(b["fail_under"])
    passed_re = re.compile(r"\b" + re.escape(passed) + r"\s+passed\b")
    problems: list[str] = []
    for rel in CHECK_FILES:
        p = repo / rel
        if not p.exists():
            problems.append(rel + ": missing file")
            continue
        txt = p.read_text(encoding="utf-8-sig")
        if not passed_re.search(txt):
            problems.append(rel + ": missing baseline token \"" + passed + " passed\"")
        if cov not in txt:
            problems.append(rel + ": missing coverage \"" + cov + "%\"")
        if ("fail_under=" + fu) not in txt and ("fail_under " + fu) not in txt \
           and ("fail_under=" + fu + "%") not in txt:
            problems.append(rel + ": missing fail_under " + fu)
        for where, token in unanchored_suite_counts(txt, passed):
            problems.append(rel + ": " + where + " quotes " + token
                            + " passed without an anchor (add a date, cycle-N or "
                            + HISTORY + ")")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("[docs-baseline] FAIL: current-state docs drift from docs/baseline.json:",)
        for p in problems:
            print("  - " + p)
        return 1
    print("[docs-baseline] OK: current-state docs match docs/baseline.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
