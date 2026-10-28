#!/usr/bin/env python
"""Pre-commit gate for sloth_engine (P3.2 green umbrella).

Enforces green-first discipline locally before a commit lands:
  * fail-closed on missing test deps (reject + bootstrap, never exit 0);
  * ratchet: pyproject coverage fail_under must not drop below HEAD, and the
    measured coverage must meet the committed floor (the latter is enforced by
    pytest-cov via pyproject addopts);
  * baseline-vs-measured (cycle-17 A): the pytest summary must not fall behind
    the recorded snapshot in docs/baseline.json (test count and coverage).
    Nothing else compares the record to the real run, so without this an edit
    that deletes tests could stay green as long as docs/baseline.json and the
    current-state docs were hand-edited in lockstep;
  * orphan-mechanism: a sloth_engine/ mechanism module with no caller fails the
    gate (scripts/check_orphan_mechanisms.py; explicit, live exemptions only);
  * path-scoped: only runs when staged changes touch sloth_engine/, tests/,
    scripts/, pyproject.toml, or requirements-dev.txt (docs-only commits skip).
  * --all: force the full gate regardless of git/staged state (for
    delivery/acceptance where .git may be absent or nothing is staged;
    without --all a no-staged-change run still SKIPs to keep pre-commit fast).

Pure precondition: this script never imports sloth_engine modules (orchestrator,
memory_store, event_log, PatternStore, ...). It only reads pyproject.toml and
docs/baseline.json, runs pytest as a subprocess, and inspects git. The guard
stays out of the checkpoint/write path on purpose.

Soft-constraint disclaimer: a local pre-commit hook is bypassable (--no-verify,
core.hooksPath override, or a fresh clone with no hooks installed). This is the
strongest LOCAL enforcement available. The fail-closed half is delivered
separately as a server-side pre-receive gate (scripts/pre-receive +
scripts/push_gate.py, installed by scripts/install_push_gate.py): install it on
the receiving repository. This script alone is NOT fail-closed CI -- do not
represent it as such.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
PYPROJECT = REPO / "pyproject.toml"
BASELINE = REPO / "docs" / "baseline.json"
TRIGGER_PREFIXES = ("sloth_engine/", "tests/", "scripts/")
TRIGGER_EXACT = ("pyproject.toml", "requirements-dev.txt")
# Recorded-vs-measured coverage slack: absorbs float/rounding noise (the record
# keeps two decimals) without hiding a real drop.
COVERAGE_TOLERANCE = 0.15


def _import_ok(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def _staged() -> list[str]:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def _triggered(staged: list[str]) -> bool:
    for f in staged:
        if f in TRIGGER_EXACT:
            return True
        for p in TRIGGER_PREFIXES:
            if f.startswith(p):
                return True
    return False


def _parse_fail_under(text: str):
    m = re.search(
        r"\[tool\.coverage\.report\][^\[]*?fail_under\s*=\s*([0-9]+)",
        text, re.S,
    )
    return int(m.group(1)) if m else None


def _head_fail_under():
    r = subprocess.run(
        ["git", "show", "HEAD:pyproject.toml"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        return None
    return _parse_fail_under(r.stdout or "")


def parse_pytest_summary(text: str) -> dict:
    """Extract the two numbers the baseline records from `pytest -q` output.

    Returns {"passed": int|None, "coverage": float|None}.  Pure and locale-proof
    (only ASCII digits are parsed) so it is directly unit-testable; an
    unparseable summary is a violation downstream, not a silent pass.
    """
    passed = re.search(r"(\d+)\s+passed", text or "")
    cov = re.search(r"Total coverage:\s*([0-9]+(?:\.[0-9]+)?)\s*%", text or "")
    return {
        "passed": int(passed.group(1)) if passed else None,
        "coverage": float(cov.group(1)) if cov else None,
    }


def coverage_floor(recorded: float,
                   tolerance: float = COVERAGE_TOLERANCE) -> float:
    """The measured coverage under which the run counts as a regression.

    Single source for the ratchet's judgment and its message: the gate
    fails iff ``measured < coverage_floor(recorded)`` and the pass line
    prints exactly ``measured >= coverage_floor(recorded)``.  Keeping both
    on the same expression means the printed comparison can never
    contradict the verdict (cycle-39 A: the pass line used to print
    "79.35% >= 79.47%" -- false -- while the real judgment carried the
    0.15 slack).
    """
    return recorded - tolerance


def baseline_violations(measured: dict, baseline: dict,
                        tolerance: float = COVERAGE_TOLERANCE) -> list[str]:
    """Return violations where the measured run fell behind the recorded baseline.

    The ratchet is one-directional: a run may exceed the record (tests were
    added) but must never drop below it (tests or a module were removed).
    """
    problems: list[str] = []
    rec_passed = int(baseline.get("passed", 0) or 0)
    if measured.get("passed") is None:
        problems.append("could not parse 'N passed' from the pytest output")
    elif measured["passed"] < rec_passed:
        problems.append(
            "test count regression: measured %d passed < recorded %d in "
            "docs/baseline.json" % (measured["passed"], rec_passed))
    rec_cov = float(str(baseline.get("coverage", 0) or 0).rstrip("%"))
    floor = coverage_floor(rec_cov, tolerance)
    if measured.get("coverage") is None:
        problems.append("could not parse 'Total coverage: X%' from the pytest output")
    elif measured["coverage"] < floor:
        problems.append(
            "coverage regression: measured %.2f%% < floor %.2f%% "
            "(recorded %.2f%%, slack %.2f)"
            % (measured["coverage"], floor, rec_cov, tolerance))
    return problems


def _run_pytest() -> "subprocess.CompletedProcess":
    """Run the documented full-regression scope (Prompt.md section 3): both roots.

    pyproject testpaths=["tests"] alone yields < fail_under at HEAD, which made
    the gate unconditionally red; the canonical command is `tests` +
    `sloth_engine/tests`.  Output is captured (cycle-17 A) so the -q summary can
    be parsed against docs/baseline.json; it is re-printed verbatim afterwards.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "sloth_engine/tests",
         "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env,
    )


def _fail(msg: str) -> int:
    print("[gate] FAIL: " + msg, file=sys.stderr)
    return 1


def main(all_mode: bool = False) -> int:
    if all_mode:
        print("[gate] --all: running full gate (git state ignored).")
    staged = [] if all_mode else _staged()
    if not all_mode and not _triggered(staged):
        print("[gate] SKIP: no sloth_engine/ | tests/ | scripts/ | pyproject.toml changes staged.")
        return 0
    print("[gate] triggered; staged top: " + repr(staged[:6]))

    missing = [m for m in ("pytest", "pytest_cov", "coverage") if not _import_ok(m)]
    if missing:
        print("[gate] FAIL: missing test deps: " + ", ".join(missing), file=sys.stderr)
        print("[gate] bootstrap: python -m pip install -r requirements-dev.txt", file=sys.stderr)
        print("[gate] gate is fail-closed on missing deps; commit rejected.", file=sys.stderr)
        return 1

    committed = _parse_fail_under(PYPROJECT.read_text(encoding="utf-8"))
    if committed is None:
        return _fail("no fail_under found in pyproject.toml [tool.coverage.report].")
    head = _head_fail_under()
    if head is not None and committed < head:
        return _fail(
            "ratchet: fail_under " + str(committed) + " < HEAD " + str(head)
            + "; lowering the coverage floor in-commit is blocked. Revert the "
            "lower or raise coverage first."
        )
    print("[gate] ratchet: committed fail_under=" + str(committed)
          + ", HEAD=" + (str(head) if head is not None else "none(new)") + " -> ok")

    r = _run_pytest()
    sys.stdout.write(r.stdout or "")
    sys.stderr.write(r.stderr or "")
    if r.returncode != 0:
        return _fail(
            "pytest+coverage exited " + str(r.returncode)
            + " (tests red or coverage < fail_under=" + str(committed)
            + "). Fix before committing."
        )

    measured = parse_pytest_summary(r.stdout or "")
    try:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    except Exception as exc:  # fail-closed: an unreadable record is a failure
        return _fail("docs/baseline.json unreadable: " + repr(exc))
    problems = baseline_violations(measured, baseline)
    if problems:
        for p in problems:
            print("[gate] baseline-vs-measured: " + p, file=sys.stderr)
        return _fail(
            "the measured run is behind docs/baseline.json, the recorded "
            "snapshot the current-state docs quote. Restore the tests/coverage "
            "or re-record the baseline deliberately."
        )
    _rec_cov = float(str(baseline.get("coverage", 0) or 0).rstrip("%"))
    print("[gate] baseline-vs-measured: OK (passed " + str(measured["passed"])
          + " >= " + str(baseline.get("passed"))
          + ", coverage " + ("%.2f" % measured["coverage"]) + "% >= floor "
          + ("%.2f" % coverage_floor(_rec_cov))
          + "% [recorded " + str(baseline.get("coverage"))
          + "%, slack " + ("%.2f" % COVERAGE_TOLERANCE) + "])")

    # Docs baseline consistency (single source: docs/baseline.json).
    # Guards "what the docs say" == "what the record says", so current-state
    # docs cannot drift silently (enrolled after the 2026-10-17 fix).
    try:
        import docs_baseline
        drift = docs_baseline.check()
    except Exception as exc:  # guard is fail-closed: an error is a failure
        return _fail("docs-baseline guard error: " + repr(exc))
    if drift:
        for d in drift:
            print("[gate] docs-baseline drift: " + d, file=sys.stderr)
        return _fail(
            "current-state docs drift from docs/baseline.json (update the docs "
            "and/or baseline.json).")
    print("[gate] docs-baseline: OK")

    # Orphan-mechanism gate (cycle-11 N-1): a mechanism module landed in
    # sloth_engine/ with no caller is a "wiring not closed" regression
    # (G-5/G-6 class). Exemptions live in scripts/check_orphan_mechanisms.py.
    try:
        import check_orphan_mechanisms
        orphans = check_orphan_mechanisms.check(REPO)
    except Exception as exc:  # fail-closed: an error is a failure
        return _fail("orphan-mechanism guard error: " + repr(exc))
    if orphans:
        for o in orphans:
            print("[gate] orphan-mechanism: " + o, file=sys.stderr)
        return _fail(
            "sloth_engine mechanism module(s) without a caller (wire them or "
            "register a live exemption in scripts/check_orphan_mechanisms.py).")
    print("[gate] orphan-mechanisms: OK")

    print("[gate] PASS: tests green, coverage >= " + str(committed) + "%.")
    print("[gate] soft-constraint: this LOCAL hook is still bypassable "
          "(--no-verify / core.hooksPath / fresh clone). Install the "
          "fail-closed push gate on the receiving repo: "
          "python scripts/install_push_gate.py --repo <origin>.")
    return 0


if __name__ == "__main__":
    _all = "--all" in sys.argv[1:]
    sys.exit(main(all_mode=_all))
