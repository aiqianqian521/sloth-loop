"""W1-RESUME-01 Slice 5: the 7-kill-point idempotency matrix (plan B P1.1 验收 §273).

The 7 OODA-loop step checkpoints persisted by Slice 3 (_STEP_ORDER =
understand/observe/orient/decide/act/verify/learn) are the 7 resume positions.
For each: crash the NEXT step on the pre-crash pass so the latest persisted
checkpoint lands AT that resume position, reload it from the DB exactly as
run()'s resume branch does (cross-process channel; the in-memory _resume_at is
re-seeded from the persisted record, not carried across), and resume. Assert:

  (a) at most the current step is re-run -- no pre-crash side effect replays
      (the Act backtest commits exactly once across the whole crash+resume).
  (b) Pattern/Problem table row counts equal a single uninterrupted run
      (one rounds row; one exec-error problem with recurrence_count=1;
      learn_done(run_id, 1) True).

The act/verify/learn kill-points are also asserted individually in
tests/test_resume_step.py (Slice 3/4); this file is the canonical 7-point
matrix regression that closes plan B P1.1's acceptance gate across ALL
step-resume positions + the cross-process idempotency claim.

Run: python tests/test_resume_idempotency.py  (custom harness; pytest migration
is plan P3.2). Mirrors the _cfg/_sigs/_resume_from seams in test_resume_step.py.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from orchestrator import Orchestrator, OODASteps  # noqa: E402
from config_util import deep_merge, DEFAULT_CONFIG  # noqa: E402

# A deterministic, fast Act result: status=error drives an execution_error
# problem (stable error_signature) whose recurrence_count we can assert on.
ERR_ACT = {"status": "error", "error": "forced-act-error", "trades": [],
           "raw": None, "sharpe": 0, "win_rate": "", "execution_failed": False}
SIG_EXEC = "backtest|execution|forced-act-error"

# 7 resume positions -> the step to CRASH during on the pre-crash pass (its
# next step), so the latest persisted checkpoint is AT that resume position.
# learn's "next" is the post-Learn producers (_produce_defect_report); the
# checkpoint saved there is AT learn.
_RESUME_AT_NEXT = {
    "understand": "observe",
    "observe":    "orient",
    "orient":     "decide",
    "decide":     "act",
    "act":        "verify",
    "verify":     "learn",
    "learn":      "producers",
}
_CRASH_TARGETS = {
    "observe":   (OODASteps, "_observe"),
    "orient":    (OODASteps, "_orient"),
    "decide":    (OODASteps, "_decide"),
    "verify":    (OODASteps, "_verify"),
    "learn":     (OODASteps, "_learn"),
    "producers": (Orchestrator, "_produce_defect_report"),
}


def _cfg(td, *, max_rounds=1):
    db = Path(td) / "p.db"
    sig = Path(td) / "signals.json"
    sig.write_text(json.dumps(
        [{"signal_pattern": "fail-me-please", "market_condition": "m"}]),
        encoding="utf-8")
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": td, "db": str(db)},
        "memory": {"sqlite_path": str(db)},
        "loop": {"max_rounds": max_rounds, "no_progress_stop": 3,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0,
                 "signals": str(sig)},
        "backtest": {"script": "backtest/does_not_exist.py", "extra_args": ""},
    })
    return cfg, db


def _sigs():
    return [{"signal_pattern": "fail-me-please", "market_condition": "m"}]


def _resume_from(o, task_name="sandbox", step_expected=None):
    """Mirror run()'s resume branch: load the latest checkpoint and seed
    _resume_at + cursor from it. Returns the checkpoint dict."""
    ck = o.store.load_latest_checkpoint(task_name)
    assert ck is not None, "checkpoint must persist across the pre-crash pass"
    if step_expected is not None:
        assert ck["step"] == step_expected, f"step={ck['step']} want={step_expected}"
    o._cursor = int(ck.get("signal_cursor", 0))
    o._round_start_cursor = o._cursor
    o._resume_at = {
        "step": ck["step"],
        "artifacts": (ck.get("payload") or {}).get("artifacts") or {},
    }
    return ck


def _problem_count(db, sig=None):
    con = sqlite3.connect(str(db)); con.row_factory = sqlite3.Row
    n = con.execute("SELECT COUNT(*) AS n FROM problem_queue").fetchone()["n"]
    rec = None
    if sig is not None:
        row = con.execute(
            "SELECT recurrence_count AS r FROM problem_queue WHERE error_signature=?",
            (sig,)).fetchone()
        rec = row["r"] if row else None
    con.close()
    return n, rec


def _crash_once(target):
    """Patch cls.name to raise on the first call, then forward to the original.
    Returns (cls, name, original) for restore."""
    cls, name = target
    orig = getattr(cls, name)
    box = {"n": 0}

    def wrapper(*a, **k):
        box["n"] += 1
        if box["n"] == 1:
            raise RuntimeError(f"boom-{name}")
        return orig(*a, **k)

    setattr(cls, name, wrapper)
    return cls, name, orig


def _matrix(resume_at, run_id):
    """One row of the 7-point matrix: crash the next step, resume AT resume_at,
    and assert invariants (a)+(b)."""
    assert resume_at in _RESUME_AT_NEXT
    next_step = _RESUME_AT_NEXT[resume_at]
    with tempfile.TemporaryDirectory() as td:
        cfg, db = _cfg(td, max_rounds=1)
        o = Orchestrator(cfg)
        o._run_id = run_id
        calls = {"act": 0}
        _acted = {"crashed": False}
        # Crash DURING act only when resuming AT decide (otherwise act succeeds).
        crash_during_act = (resume_at == "decide")

        def fake_act(*a, **k):
            if crash_during_act and not _acted["crashed"]:
                _acted["crashed"] = True
                raise RuntimeError("boom-act")
            calls["act"] += 1
            return (dict(ERR_ACT), [])

        orig_act = OODASteps._act_with_retry
        OODASteps._act_with_retry = fake_act
        # "act" is the kill target for resume AT decide and is handled by
        # fake_act raising once; every other step gets a dedicated patch.
        patch = (_crash_once(_CRASH_TARGETS[next_step])
                 if next_step != "act" else None)
        try:
            crashed = False
            try:
                o.run_once(_sigs())
            except RuntimeError:
                crashed = True
            assert crashed, f"expected a crash during {next_step}"
            _resume_from(o, step_expected=resume_at)  # reload checkpoint AT resume_at
            o.run_once(_sigs())  # resume
        finally:
            OODASteps._act_with_retry = orig_act
            if patch is not None:
                cls, name, orig = patch
                setattr(cls, name, orig)

        # (a) at most the current step re-ran: Act committed exactly once total
        assert calls["act"] == 1, (
            f"Act committed once across crash+resume; got {calls['act']}")
        # (b) Pattern/Problem counts == a single uninterrupted round
        rounds = o.store.get_rounds()
        assert len(rounds) == 1, f"one rounds row (== uninterrupted); got {len(rounds)}"
        assert o.store.learn_done(o._run_id, 1) is True, "Learn committed exactly once"
        n, rec = _problem_count(db, SIG_EXEC)
        assert n == 1 and rec == 1, (
            f"exec problem once / recurrence 1; got n/rec={n}/{rec}")


def test_uninterrupted_round_baseline():
    """A single uninterrupted round (no crash) pins the (b) invariant: exactly
    one rounds row, one exec-error problem with recurrence_count=1, and one
    committed Act. The 7 matrix tests below assert the SAME counts after a
    crash+resume."""
    with tempfile.TemporaryDirectory() as td:
        cfg, db = _cfg(td, max_rounds=1)
        o = Orchestrator(cfg)
        o._run_id = "test-mx-baseline"
        calls = {"act": 0}

        def fake_act(*a, **k):
            calls["act"] += 1
            return (dict(ERR_ACT), [])

        orig_act = OODASteps._act_with_retry
        OODASteps._act_with_retry = fake_act
        try:
            o.run_once(_sigs())
        finally:
            OODASteps._act_with_retry = orig_act
        assert calls["act"] == 1, "baseline Act commits exactly once"
        assert len(o.store.get_rounds()) == 1, "baseline one rounds row"
        assert o.store.learn_done(o._run_id, 1) is True, "baseline learn_done"
        n, rec = _problem_count(db, SIG_EXEC)
        assert n == 1 and rec == 1, f"baseline problem n/rec={n}/{rec}"


def test_resume_matrix_understand():
    """Kill-point Observe (crash during Observe) -> resume AT Understand.
    understand restored; Observe..Learn run once. One round, one problem
    (rec=1), Act committed once across the whole crash+resume."""
    _matrix("understand", "test-mx-u")


def test_resume_matrix_observe():
    """Kill-point Orient (crash during Orient) -> resume AT Observe.
    understand+observe restored; Orient..Learn run once."""
    _matrix("observe", "test-mx-o1")


def test_resume_matrix_orient():
    """Kill-point Decide (crash during Decide) -> resume AT Orient.
    understand..orient restored; Decide..Learn run once."""
    _matrix("orient", "test-mx-o2")


def test_resume_matrix_decide():
    """Kill-point Act (crash during Act, before it commits) -> resume AT
    Decide. understand..decide restored; Act re-runs once (the only re-done
    step) then Verify/Learn commit once."""
    _matrix("decide", "test-mx-d")


def test_resume_matrix_act():
    """Kill-point Verify (crash during Verify) -> resume AT Act. Act restored
    (NOT re-run); Verify+Learn commit once."""
    _matrix("act", "test-mx-a")


def test_resume_matrix_verify():
    """Kill-point Learn (crash during Learn, before it commits) -> resume AT
    Verify. understand..verify restored; Learn commits exactly once."""
    _matrix("verify", "test-mx-v")


def test_resume_matrix_learn():
    """Kill-point producers (crash during _produce_defect_report, AFTER Learn
    committed + pushed its problem) -> resume AT Learn. The whole
    non-idempotent tail is skipped: no re-log_round, no recurrence inflation."""
    _matrix("learn", "test-mx-l")


if __name__ == "__main__":
    for fn in (
        test_uninterrupted_round_baseline,
        test_resume_matrix_understand,
        test_resume_matrix_observe,
        test_resume_matrix_orient,
        test_resume_matrix_decide,
        test_resume_matrix_act,
        test_resume_matrix_verify,
        test_resume_matrix_learn,
    ):
        fn()
        print(f"PASS {fn.__name__}")
