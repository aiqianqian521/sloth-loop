# -*- coding: utf-8 -*-
"""L3 cycle-6 A4 - context compaction checkpoint: proportional retention +
previous-summary chaining (C6).

Provenance (distilled from open-webui@0.11.3):
  utils/context_compaction.py:51-67   (apply latest summary -> boundary -> split)
  utils/context_compaction.py:328-333 (keep_count from retention_percentage)
  utils/context_compaction.py:300-312 (latest summary checkpoint chaining)
  utils/context_compaction.py:224-229 (retention clamped to [10, 50])

Contract under test (behavioural, not source-grep):
  1. retention_boundary keeps a proportional recent window (>= 2).
  2. compact_with_checkpoint PRESERVES the recent window (does not wipe it).
  3. previous_summary is chained into the next compaction.
  4. failed summarizer degrades to a trimming marker (never raises).
  5. reactive_compact / auto_compact now record previous_summary too.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from context_compactor import ContextCompactor  # noqa: E402


def _mk(n, window=100000):
    c = ContextCompactor(effective_window=window)
    c.append_messages(["m%d" % i for i in range(n)])
    return c


# -- invariant 1: proportional retention -----------------------------------
def test_retention_boundary_is_proportional():
    c = _mk(10)
    # 40% of 10 = 4 kept -> boundary 6
    assert c.retention_boundary(40) == 6
    # clamp: 5% -> 10% ; 90% -> 50%
    c10 = _mk(10)
    assert c10.retention_boundary(5) == c10.retention_boundary(10)
    c90 = _mk(10)
    assert c90.retention_boundary(90) == c90.retention_boundary(50)


def test_retention_boundary_keeps_at_least_two():
    c = _mk(3)
    # max(2, 3*40//100=1) = 2 kept -> boundary 1
    assert c.retention_boundary(40) == 1
    empty = ContextCompactor(effective_window=1000)
    assert empty.retention_boundary(40) == 0


# -- invariant 2: recent window preserved (vs wipe) ------------------------
def test_checkpoint_preserves_recent_window():
    c = _mk(10)
    calls = {}

    def summarizer(to_compact, prev):
        calls["n"] = len(to_compact)
        calls["prev"] = prev
        return "SUM1", 0

    result = c.compact_with_checkpoint(summarizer, retention_percentage=40)
    assert result["action"] == "checkpoint"
    assert result["compacted"] == 6
    assert result["kept"] == 4
    # history is now [summary] + last 4 originals -> not wiped
    assert c._history[0] == "SUM1"
    assert c._history[1:] == ["m6", "m7", "m8", "m9"]
    assert calls["prev"] is None


def test_checkpoint_noop_when_nothing_to_compact():
    c = _mk(2)
    r = c.compact_with_checkpoint(lambda tc, p: ("S", 0), retention_percentage=40)
    assert r["action"] == "skip"
    assert c._history == ["m0", "m1"]


# -- invariant 3: previous summary chaining --------------------------------
def test_previous_summary_is_chained_across_compactions():
    c = _mk(10)
    seen = []

    def summarizer(to_compact, prev):
        seen.append(prev)
        return "SUM-%d" % len(seen), 0

    c.compact_with_checkpoint(summarizer, retention_percentage=40)
    assert c.previous_summary == "SUM-1"
    # grow and compact again
    c.append_messages(["m%d" % i for i in range(10, 20)])
    c.compact_with_checkpoint(summarizer, retention_percentage=40)
    assert seen == [None, "SUM-1"]           # second call saw the first summary
    assert c.previous_summary == "SUM-2"


# -- invariant 4: failure degrades, never raises ---------------------------
def test_checkpoint_degrades_on_summarizer_failure():
    c = _mk(10)

    def boom(to_compact, prev):
        raise RuntimeError("llm down")

    r = c.compact_with_checkpoint(boom, retention_percentage=40)
    assert r["action"] == "checkpoint"
    assert r["summary"].startswith("[6 older messages trimmed]")
    assert c._history[0] == "[6 older messages trimmed]"


def test_checkpoint_without_summarizer_still_keeps_window():
    c = _mk(10)
    r = c.compact_with_checkpoint(None, retention_percentage=40)
    assert r["kept"] == 4
    assert c._history[1:] == ["m6", "m7", "m8", "m9"]


# -- invariant 5: reactive/auto carry summary forward ----------------------
def test_reactive_compact_records_previous_summary():
    c = _mk(5)

    def fn(history):
        return "RSUM", 0

    c.compact_fn = fn
    c.reactive_compact()
    assert c.previous_summary == "RSUM"


def test_auto_compact_records_previous_summary():
    c = ContextCompactor(effective_window=20)  # tiny window -> threshold ~0
    c.compact_fn = lambda history: ("ASUM", 0)
    c.append_messages(["a", "b", "c"])
    assert c.needs_compaction() is True
    c.auto_compact()
    assert c.previous_summary == "ASUM"
