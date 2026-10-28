"""cycle-17 A: behavioural contract for the local gate (scripts/run_gate.py).

Background: run_gate.py is the project's strongest local green-first guard, but
until now it was verified only by *grepping its own source*.  Two examples of
that weak style still live in the suite:

    assert "check_orphan_mechanisms" in src        # test_orphan_mechanisms_gate
    assert "--all" in src                          # test_p1_failclosed_batch

A grep cannot catch a wiring regression: move a check below the final
``return 0`` (or delete the call) and every test stays green while the gate
silently stops guarding.  These tests import run_gate as a module and exercise
the real functions, with the slow / ambient seams monkeypatched so every branch
is reachable in-process:

  * pure helpers: _triggered, _parse_fail_under, parse_pytest_summary,
    baseline_violations;
  * main() itself, including the cycle-17 "baseline-vs-measured" step added to
    close the "recorded numbers were never compared to the real run" gap.

Self-discipline note: every green-path fixture below derives its numbers from
docs/baseline.json instead of hard-coding them.  The first version of
``test_main_actually_runs_pytest`` hard-coded "1542 passed / 77.58%" and the new
ratchet failed it as soon as the baseline moved -- the very anti-pattern (a
stale recorded number) this cycle exists to prevent.  Helpers now read the
record.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "run_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_gate_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


g = _load()


def _proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["pytest"], returncode=returncode, stdout=stdout, stderr=stderr)


def _baseline() -> dict:
    return json.loads((REPO / "docs" / "baseline.json").read_text(encoding="utf-8"))


def _cov(b) -> str:
    return str(b["coverage"]).rstrip("%")


def _green_stdout(passed: int | None = None, coverage: str | None = None) -> str:
    """A pytest -q summary that the recorded baseline accepts (or a variant)."""
    b = _baseline()
    n = b["passed"] if passed is None else passed
    c = _cov(b) if coverage is None else coverage
    return ("%d passed, 1 xfailed, 1 warning in 232.10s\n"
            "Required test coverage of 70.0%% reached. Total coverage: %s%%\n"
            % (n, c))


def _green_seams(monkeypatch, stdout: str, returncode: int = 0):
    """Patch every ambient seam so main() runs hermetically and instantly."""
    import docs_baseline
    import check_orphan_mechanisms

    monkeypatch.setattr(g, "_import_ok", lambda _m: True)
    monkeypatch.setattr(g, "_head_fail_under", lambda: 70)
    monkeypatch.setattr(g, "_run_pytest", lambda: _proc(returncode, stdout))
    monkeypatch.setattr(docs_baseline, "check", lambda *a, **k: [])
    monkeypatch.setattr(check_orphan_mechanisms, "check", lambda *a, **k: [])


# ---- pure helpers ----------------------------------------------------------

def test_parse_fail_under_reads_the_section_value():
    text = "[tool.coverage.run]\nbranch = true\n[tool.coverage.report]\nfail_under = 70\n"
    assert g._parse_fail_under(text) == 70


def test_parse_fail_under_returns_none_when_absent():
    assert g._parse_fail_under("[tool.coverage.run]\nbranch = true\n") is None


def test_triggered_matches_code_paths_and_ignores_docs_only():
    assert g._triggered(["sloth_engine/x.py"])
    assert g._triggered(["tests/test_x.py"])
    assert g._triggered(["scripts/run_gate.py"])
    assert g._triggered(["pyproject.toml"])
    assert g._triggered(["requirements-dev.txt"])
    assert not g._triggered(["docs/baseline.json", "README.md"])


def test_parse_pytest_summary_reads_passed_and_coverage():
    out = ("1542 passed, 1 xfailed, 1 warning in 231.72s\n"
           "Required test coverage of 70.0% reached. Total coverage: 77.57%")
    assert g.parse_pytest_summary(out) == {"passed": 1542, "coverage": 77.57}


def test_parse_pytest_summary_is_none_safe_on_junk():
    assert g.parse_pytest_summary("") == {"passed": None, "coverage": None}
    assert g.parse_pytest_summary("no tests ran in 0.01s") == {
        "passed": None, "coverage": None}


# ---- cycle-17 baseline-vs-measured (pure) ----------------------------------

def test_baseline_violations_flags_a_test_count_regression():
    problems = g.baseline_violations(
        {"passed": 1500, "coverage": 77.57},
        {"passed": 1542, "coverage": "77.58"})
    assert any("test count regression" in p for p in problems), problems


def test_baseline_violations_flags_a_coverage_regression():
    problems = g.baseline_violations(
        {"passed": 1542, "coverage": 71.0},
        {"passed": 1542, "coverage": "77.58"})
    assert any("coverage regression" in p for p in problems), problems


def test_baseline_violations_accepts_rounding_noise():
    assert g.baseline_violations(
        {"passed": 1542, "coverage": 77.44},
        {"passed": 1542, "coverage": "77.58"}) == []


def test_baseline_violations_allows_more_tests_than_recorded():
    assert g.baseline_violations(
        {"passed": 1600, "coverage": 80.0},
        {"passed": 1542, "coverage": "77.58"}) == []


def test_baseline_violations_fails_closed_on_unparseable_output():
    problems = g.baseline_violations({}, {"passed": 1542, "coverage": "77.58"})
    assert len(problems) == 2, problems


# ---- main() branches -------------------------------------------------------

def test_main_skips_when_nothing_relevant_is_staged(monkeypatch):
    monkeypatch.setattr(g, "_staged", lambda: ["docs/baseline.json", "README.md"])
    assert g.main(all_mode=False) == 0


def test_main_is_fail_closed_when_test_deps_are_missing(monkeypatch):
    monkeypatch.setattr(g, "_staged", lambda: ["tests/test_x.py"])
    monkeypatch.setattr(g, "_import_ok", lambda _m: False)
    assert g.main(all_mode=False) == 1


def test_main_blocks_lowering_the_coverage_ratchet(monkeypatch):
    monkeypatch.setattr(g, "_import_ok", lambda _m: True)
    monkeypatch.setattr(g, "_head_fail_under", lambda: 999)
    assert g.main(all_mode=True) == 1


def test_main_actually_runs_pytest(monkeypatch):
    calls: list[int] = []

    def fake():
        calls.append(1)
        return _proc(0, _green_stdout())

    _green_seams(monkeypatch, stdout="unused")
    monkeypatch.setattr(g, "_run_pytest", fake)
    assert g.main(all_mode=True) == 0
    assert calls == [1]


def test_main_fails_when_pytest_is_red(monkeypatch):
    _green_seams(monkeypatch,
                 stdout="3 failed, 1539 passed\nTotal coverage: 77.57%",
                 returncode=1)
    assert g.main(all_mode=True) == 1


def test_main_fails_when_fewer_tests_pass_than_recorded(monkeypatch):
    b = _baseline()
    _green_seams(monkeypatch, stdout=_green_stdout(passed=max(b["passed"] - 1, 0)))
    assert g.main(all_mode=True) == 1


def test_main_fails_when_coverage_falls_below_the_record(monkeypatch):
    b = _baseline()
    lower = "%.2f" % (float(_cov(b)) - 1.0)
    _green_seams(monkeypatch, stdout=_green_stdout(coverage=lower))
    assert g.main(all_mode=True) == 1


def test_main_fails_when_the_summary_cannot_be_parsed(monkeypatch):
    _green_seams(monkeypatch, stdout="no tests ran in 0.01s\n")
    assert g.main(all_mode=True) == 1


def test_main_fails_on_docs_baseline_drift(monkeypatch):
    import docs_baseline

    _green_seams(monkeypatch, stdout=_green_stdout())
    monkeypatch.setattr(docs_baseline, "check",
                        lambda *a, **k: ["README.md: missing baseline token"])
    assert g.main(all_mode=True) == 1


def test_main_fails_on_an_orphan_mechanism(monkeypatch):
    import check_orphan_mechanisms

    _green_seams(monkeypatch, stdout=_green_stdout())
    monkeypatch.setattr(check_orphan_mechanisms, "check",
                        lambda *a, **k: ["orphan mechanism (no caller): x"])
    assert g.main(all_mode=True) == 1


def test_main_passes_when_every_check_is_green(monkeypatch):
    _green_seams(monkeypatch, stdout=_green_stdout())
    assert g.main(all_mode=True) == 0



def test_the_pass_line_never_contradicts_the_verdict(monkeypatch, capsys):
    """cycle-39 A: the OK line must print a comparison that is actually true.

    With coverage just inside the tolerance the old line printed
    "coverage 79.35% >= 79.47%" -- false -- while main() returned 0.
    The printed floor must be the same expression the verdict uses.
    """
    b = _baseline()
    rec = float(_cov(b))
    inside = "%.2f" % (rec - g.COVERAGE_TOLERANCE + 0.01)
    _green_seams(monkeypatch, stdout=_green_stdout(coverage=inside))
    assert g.main(all_mode=True) == 0
    out = capsys.readouterr().out
    m = re.search(r"coverage ([0-9.]+)% >= floor ([0-9.]+)% "
                  r"\[recorded ([0-9.]+)%, slack ([0-9.]+)\]", out)
    assert m, out
    measured, floor, recorded, slack = (float(x) for x in m.groups())
    assert measured >= floor  # the printed comparison is true
    assert abs((recorded - floor) - slack) < 1e-9
    assert floor == round(recorded - g.COVERAGE_TOLERANCE, 2)


def test_the_failure_line_names_the_floor(monkeypatch, capsys):
    b = _baseline()
    below = "%.2f" % (float(_cov(b)) - g.COVERAGE_TOLERANCE - 0.01)
    _green_seams(monkeypatch, stdout=_green_stdout(coverage=below))
    assert g.main(all_mode=True) == 1
    err = capsys.readouterr().err
    assert "floor" in err and "slack" in err


def test_the_gate_really_reads_the_repo_baseline(monkeypatch):
    """The green path must compare against docs/baseline.json itself, not a stub."""
    b = _baseline()
    _green_seams(monkeypatch, stdout=_green_stdout(passed=1500))
    assert g.main(all_mode=True) == 1
    _green_seams(monkeypatch, stdout=_green_stdout())
    assert g.main(all_mode=True) == 0


def test_the_green_fixture_itself_matches_the_record():
    """Guard the guard: the fixture must satisfy the very ratchet it feeds."""
    measured = g.parse_pytest_summary(_green_stdout())
    assert g.baseline_violations(measured, _baseline()) == []
    assert measured["passed"] == _baseline()["passed"]


# ---------------------------------------------------------------------------
# cycle-24 A: the docs-baseline guard's *scope* was itself unguarded.
#
# docs_baseline.check() reads a hand-written CHECK_FILES list.  The wake
# pointer docs/flow/GRAND-LOOP.md -- the first file a fresh agent reads, and
# the one current-state doc quoting the suite numbers that was NOT in the
# list -- had its "N passed / coverage X%" line verified by nothing: only its
# ``head`` hash is cross-checked (by the wake-pointer guard), never the
# numbers beside it.
#
# Proof (cycle-24 A): rewriting the pointer to "9999 passed / coverage 55.55%"
# left docs_baseline at OK and tests/test_wake_pointer_chain.py at 30 passed.
# A hand-written scope can silently omit an input, so the scope itself must be
# asserted -- same family as cycle-23 ("the verdict was never tested"), one
# layer out ("the set of things judged was never tested").
# ---------------------------------------------------------------------------

WAKE_POINTER = "docs/flow/GRAND-LOOP.md"
HANDOFF_ENTRY = "START.md"
# cycle-42 A: other current-state docs quoting the same numbers were still
# outside the hand-written scope (the quickstart checklist, the engine
# README and the full project introduction); pin them too.
ENTRY_DOCS = (
    WAKE_POINTER,
    HANDOFF_ENTRY,
    "docs/sloth-loop-QUICKSTART.md",
    "sloth_engine/README.md",
    "docs/sloth-loop-\u9879\u76ee\u4ecb\u7ecd\u4e0e\u89c4\u5212.md",
    # 2026-10-28: the future-extension plan quotes the live baseline; pin it
    # in the drift negative control like the other current-state docs.
    "docs/sloth-loop-AI-TEAM-AND-SELF-EVOLUTION.md",
)


def _docs_baseline():
    spec = importlib.util.spec_from_file_location(
        "docs_baseline_under_test", REPO / "scripts" / "docs_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_baseline_guard_covers_the_entry_documents() -> None:
    # cycle-41 A / cycle-42 A: every current-state entry doc must be inside
    # the hand-written scope -- a doc outside it is a number nobody checks
    # (cycle-24), which is how START.md and the quickstart rotted.
    files = _docs_baseline().CHECK_FILES
    for rel in ENTRY_DOCS:
        assert rel in files, rel


def test_the_baseline_guard_flags_entry_document_drift(tmp_path) -> None:
    for rel in ENTRY_DOCS:
        db = _docs_baseline()
        b = _baseline()
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "baseline.json").write_text(
            json.dumps(b), encoding="utf-8")
        live = (REPO / rel).read_text(encoding="utf-8")
        # the pointer quotes the number twice (header + latest-cycle
        # bullet); drift anywhere must be caught, so replace them all.
        token = "%d passed" % b["passed"]
        assert token in live, rel
        doctored = live.replace(token, "%d passed" % (b["passed"] + 1))
        assert doctored != live, rel
        (tmp_path / rel).write_text(doctored, encoding="utf-8")
        db.CHECK_FILES = (rel,)               # narrow the scope: one file
        problems = db.check(tmp_path)
        assert problems and Path(rel).name in problems[0], problems


def test_the_live_current_state_docs_match_the_baseline() -> None:
    # Fail-closed real-repo assertion: the guard's own scope, run for real.
    assert _docs_baseline().check(REPO) == []


# ---------------------------------------------------------------------------
# cycle-26 A: the guard asserted that the baseline number APPEARS in a doc --
# never that the doc's *other* suite counts are labelled.  cycle-24 registered
# that as a "known boundary" (docs/design/2026-10-24-cycle24-A-verifier-scope.md),
# but an old count sitting one line away from the live one and being read as
# today's is exactly the drift the whole guard exists to stop.
#
# Proof: "758 passed" sat under the live 1625 in docs/sloth-loop-AS-BUILT.md, and
# ROADMAP section 4 quoted 734/745/755/758 unlabelled -- docs_baseline stayed OK.
# Closed by: every 3+ digit suite count must be the baseline itself or anchored
# inside its own block (date / cycle-N / the word for "historical").
# ---------------------------------------------------------------------------


def _stale() -> str:
    return str(_baseline()["passed"] - 1)


def _doc_text(extra: str = "") -> str:
    """A minimal current-state doc that satisfies the older baseline rules."""
    b = _baseline()
    head = ("# fake\n\n"
            "baseline " + str(b["passed"]) + " passed / coverage " + _cov(b)
            + "% (fail_under=" + str(b["fail_under"]) + ")\n")
    return head + extra


def _tmp_repo(tmp_path, text: str):
    db = _docs_baseline()
    b = _baseline()
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "baseline.json").write_text(
        json.dumps(b), encoding="utf-8")
    (tmp_path / "DOC.md").write_text(text, encoding="utf-8")
    db.CHECK_FILES = ("DOC.md",)
    return db


def test_unanchored_suite_counts_flags_a_bare_stale_number() -> None:
    db = _docs_baseline()
    stale = _stale()
    found = db.unanchored_suite_counts("- regression: " + stale + " passed\n",
                                       str(_baseline()["passed"]))
    assert found == [("line 1", stale)], found


def test_unanchored_suite_counts_accepts_a_dated_or_cycled_block() -> None:
    db = _docs_baseline()
    base = str(_baseline()["passed"])
    stale = _stale()
    assert db.unanchored_suite_counts(
        "- (2026-09-03) " + stale + " passed\n", base) == []
    assert db.unanchored_suite_counts(
        "- (cycle-2) " + stale + " passed\n", base) == []
    # the anchor may live anywhere in the bullet, not only on the counted line
    bullet = ("- (2026-09-06) cycle-2 snapshot:\n"
              "  full run " + stale + " passed\n")
    assert db.unanchored_suite_counts(bullet, base) == []


def test_unanchored_suite_counts_accepts_the_history_word() -> None:
    db = _docs_baseline()
    base = str(_baseline()["passed"])
    text = "- " + db.HISTORY + " snapshot: " + _stale() + " passed\n"
    assert db.unanchored_suite_counts(text, base) == []


def test_unanchored_suite_counts_ignores_the_baseline_and_step_counters() -> None:
    db = _docs_baseline()
    base = str(_baseline()["passed"])
    assert db.unanchored_suite_counts("live: " + base + " passed\n", base) == []
    assert db.unanchored_suite_counts(
        "- Verify 1/1 passed, 3 passed\n", base) == []


def test_the_baseline_guard_flags_an_unanchored_stale_count(tmp_path) -> None:
    db = _tmp_repo(tmp_path,
                   _doc_text("\n- regression: " + _stale() + " passed\n"))
    problems = db.check(tmp_path)
    assert any(_stale() + " passed" in p for p in problems), problems


def test_the_baseline_guard_exempts_a_labelled_historical_block(tmp_path) -> None:
    db = _tmp_repo(
        tmp_path,
        _doc_text("\n- (2026-09-03) regression: " + _stale() + " passed\n"))
    assert db.check(tmp_path) == []


def test_the_live_docs_quote_no_unanchored_suite_count() -> None:
    # Fail-closed real-repo assertion for the new rule, one file at a time.
    db = _docs_baseline()
    base = str(_baseline()["passed"])
    offenders = []
    for rel in db.CHECK_FILES:
        txt = (REPO / rel).read_text(encoding="utf-8-sig")
        offenders += [(rel, w, t)
                      for w, t in db.unanchored_suite_counts(txt, base)]
    assert offenders == []
