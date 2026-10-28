"""W1-RESUME-01 Slice 3: step-level checkpoint + resume step-skip.

Three kill-point E2E tests (act / verify / learn) drive run_once through a
crash sentinel, reload the mid-round step checkpoint exactly as run() does,
and resume; plus a normal-round save check and a run()-level resume E2E.

Invariants proven:
  * a crash AFTER Act committed but before Verify -> resume AT act: the
    expensive Act backtest is NOT re-run (the central kill-point value).
  * resume AT learn skips the WHOLE non-idempotent tail (the _produce_problems
    L2 UPSERT would otherwise inflate recurrence_count - the "Problem-producer
    replay dup" gap closed here).
  * no duplicate rounds row / failure re-bump across the crash+resume.

Run: python tests/test_resume_step.py  (custom harness; pytest migration is
plan P3.2). Mirrors the cfg/bt seam used by tests/test_resume.py.
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

import orchestrator  # noqa: E402
from orchestrator import Orchestrator, OODASteps  # noqa: E402
from config_util import deep_merge, DEFAULT_CONFIG  # noqa: E402
import pytest  # noqa: E402

# A deterministic, fast Act result: status=error drives an execution_error
# problem (stable error_signature) whose recurrence_count we can assert on.
ERR_ACT = {"status": "error", "error": "forced-act-error", "trades": [],
           "raw": None, "sharpe": 0, "win_rate": "", "execution_failed": False}
SIG_EXEC = "backtest|execution|forced-act-error"


@pytest.fixture(autouse=True)
def _no_customer_report_write(monkeypatch):
    """Test isolation: block the continuous-loop completion path from writing a
    customer REPORT.md into real projects/<task>/reports/. Those run()/resume
    tests drive a real loop with DEFAULT_CONFIG task name "loop-round", whose
    completed report would overwrite the git-tracked deliverable under
    projects/loop-round/ (P1 test-hygiene fix). Resume/round/provenance
    assertions are unaffected; direct customer-report tests exercise
    reporter/report_util and do not go through Orchestrator._write_customer_report."""
    monkeypatch.setattr("orchestrator.Orchestrator._write_customer_report",
                        lambda self, *a, **k: None)


def _cfg(td: str, *, max_rounds: int = 1):
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


def test_resume_at_act_skips_rerunning_act():
    """Kill-point ACT: crash during Verify (after Act committed) -> resume AT
    act. Assert the Act backtest is NOT re-run and the round completes once."""
    with tempfile.TemporaryDirectory() as td:
        cfg, db = _cfg(td)
        o = Orchestrator(cfg)
        o._run_id = "test-s3-act"
        calls = {"act": 0}

        def fake_act(*a, **k):
            calls["act"] += 1
            return (dict(ERR_ACT), [])

        v = {"n": 0}
        orig_verify = OODASteps._verify

        def crash_verify_once(act_result, criteria, bar=None):
            v["n"] += 1
            if v["n"] == 1:
                raise RuntimeError("boom-verify-after-act")
            return orig_verify(act_result, criteria, bar)

        orig_act = OODASteps._act_with_retry
        OODASteps._act_with_retry = fake_act
        OODASteps._verify = crash_verify_once
        try:
            crashed = False
            try:
                o.run_once(_sigs())
            except RuntimeError:
                crashed = True
            assert crashed, "expected a crash during Verify"
            assert calls["act"] == 1, "Act must run once on the pre-crash pass"
            ck = _resume_from(o, step_expected="act")

            o.run_once(_sigs())  # resume AT act

            assert calls["act"] == 1, f"Act must NOT re-run on resume; calls={calls['act']}"
            rounds = o.store.get_rounds()
            assert len(rounds) == 1, f"expected 1 rounds row, got {len(rounds)}"
            assert o.store.learn_done(o._run_id, 1) is True
            n, rec = _problem_count(db, SIG_EXEC)
            assert n == 1 and rec == 1, f"problem n/rec={n}/{rec}; dedup expects 1/1"
        finally:
            OODASteps._act_with_retry = orig_act
            OODASteps._verify = orig_verify


def test_resume_at_verify_skips_to_learn():
    """Kill-point VERIFY: crash during Learn (after Verify committed) -> resume
    AT verify. Act is skipped, Learn commits exactly once."""
    with tempfile.TemporaryDirectory() as td:
        cfg, db = _cfg(td)
        o = Orchestrator(cfg)
        o._run_id = "test-s3-verify"
        calls = {"act": 0}

        def fake_act(*a, **k):
            calls["act"] += 1
            return (dict(ERR_ACT), [])

        l = {"n": 0}
        orig_learn = OODASteps._learn

        def crash_learn_once(act_result, verified, store):
            l["n"] += 1
            if l["n"] == 1:
                raise RuntimeError("boom-learn")
            return orig_learn(act_result, verified, store)

        orig_act = OODASteps._act_with_retry
        OODASteps._act_with_retry = fake_act
        OODASteps._learn = crash_learn_once
        try:
            crashed = False
            try:
                o.run_once(_sigs())
            except RuntimeError:
                crashed = True
            assert crashed and calls["act"] == 1
            ck = _resume_from(o, step_expected="verify")

            o.run_once(_sigs())  # resume AT verify -> execute Learn

            assert calls["act"] == 1, f"Act not re-run; calls={calls['act']}"
            assert len(o.store.get_rounds()) == 1, "Learn commits exactly one round"
            assert o.store.learn_done(o._run_id, 1) is True
        finally:
            OODASteps._act_with_retry = orig_act
            OODASteps._learn = orig_learn


def test_resume_at_learn_skips_non_idempotent_producers():
    """Kill-point LEARN: crash during _produce_defect_report (after Learn
    committed + saved + pushed its problem) -> resume AT learn. The whole
    non-idempotent tail is skipped: no re-log_round, no recurrence inflation.
    A witness producer replay confirms the L2 UPSERT would otherwise bump
    recurrence_count (the gap Slice 3 closes)."""
    with tempfile.TemporaryDirectory() as td:
        cfg, db = _cfg(td)
        o = Orchestrator(cfg)
        o._run_id = "test-s3-learn"
        calls = {"act": 0}

        def fake_act(*a, **k):
            calls["act"] += 1
            return (dict(ERR_ACT), [])

        d = {"n": 0}
        orig_defect = Orchestrator._produce_defect_report

        def crash_defect_once(self, learned, act_result, observations):
            d["n"] += 1
            if d["n"] == 1:
                raise RuntimeError("boom-defect")
            return orig_defect(self, learned, act_result, observations)

        orig_act = OODASteps._act_with_retry
        OODASteps._act_with_retry = fake_act
        Orchestrator._produce_defect_report = crash_defect_once
        try:
            crashed = False
            try:
                o.run_once(_sigs())
            except RuntimeError:
                crashed = True
            assert crashed and calls["act"] == 1
            # Pre-crash: Learn committed one round + one problem.
            assert len(o.store.get_rounds()) == 1
            assert o.store.learn_done(o._run_id, 1) is True
            n0, rec0 = _problem_count(db, SIG_EXEC)
            assert n0 == 1 and rec0 == 1, f"pre-crash problem n/rec={n0}/{rec0}"
            ck = _resume_from(o, step_expected="learn")

            o.run_once(_sigs())  # resume AT learn -> skip the WHOLE tail

            assert calls["act"] == 1, f"Act not re-run; calls={calls['act']}"
            assert len(o.store.get_rounds()) == 1, "no re-log_round on learn-resume"
            n1, rec1 = _problem_count(db, SIG_EXEC)
            assert n1 == 1 and rec1 == 1, \
                f"recurrence must NOT inflate on resume; got n/rec={n1}/{rec1}"

            # Witness: a SECOND producer pass on the SAME artifacts WOULD bump
            # recurrence_count (proving the gap the skip just avoided is real).
            arts = (ck.get("payload") or {}).get("artifacts") or {}
            obs = arts.get("observe", {}).get("observations")
            ar = arts.get("act", {}).get("act_result")
            lr = arts.get("learn", {}).get("learned")
            dg = arts.get("orient", {}).get("diagnosis")
            la = arts.get("act", {}).get("l1_attempts")
            o._produce_problems(obs, ar, lr, dg, None, l1_attempts=la)
            n2, rec2 = _problem_count(db, SIG_EXEC)
            assert n2 == 1 and rec2 == 2, \
                f"2nd producer pass should bump recurrence to 2; got n/rec={n2}/{rec2}"
        finally:
            OODASteps._act_with_retry = orig_act
            Orchestrator._produce_defect_report = orig_defect


def test_normal_round_saves_all_step_checkpoints():
    """A normal (non-resume) round saves a cumulative step checkpoint per OODA
    step; the latest is the learn checkpoint carrying all 7 artifacts, stored
    with the pre-consume cursor (so resume reproduces the same signal batch)."""
    with tempfile.TemporaryDirectory() as td:
        cfg, db = _cfg(td)
        o = Orchestrator(cfg)
        o._run_id = "test-s3-normal"
        calls = {"act": 0}

        def fake_act(*a, **k):
            calls["act"] += 1
            return (dict(ERR_ACT), [])

        orig_act = OODASteps._act_with_retry
        OODASteps._act_with_retry = fake_act
        try:
            o.run_once(_sigs())
            ck = o.store.load_latest_checkpoint("sandbox")
            assert ck is not None
            assert ck["step"] == "learn", ck["step"]
            arts = (ck.get("payload") or {}).get("artifacts") or {}
            assert set(arts.keys()) == {
                "understand", "observe", "orient", "decide",
                "act", "verify", "learn"}, set(arts.keys())
            assert ck["signal_cursor"] == 0  # pre-consume cursor for a step token
        finally:
            OODASteps._act_with_retry = orig_act
            del calls  # noqa


def test_run_level_resume_after_act_crash():
    """End-to-end through run(): crash during round-1 Verify, then resume in a
    fresh orchestrator reusing the DB. Act runs once total across both passes
    and exactly one round completes."""
    with tempfile.TemporaryDirectory() as td:
        cfg, db = _cfg(td, max_rounds=2)  # contract trips max_rounds_reached BEFORE a round runs,
        # so with N rounds configured only N-1 actually execute; use 2 so round 1 runs.
        calls = {"act": 0}

        def fake_act(*a, **k):
            calls["act"] += 1
            return (dict(ERR_ACT), [])

        v = {"n": 0}
        orig_verify = OODASteps._verify

        def crash_verify_once(act_result, criteria, bar=None):
            v["n"] += 1
            if v["n"] == 1:
                raise RuntimeError("boom-verify-run")
            return orig_verify(act_result, criteria, bar)

        orig_act = OODASteps._act_with_retry
        OODASteps._act_with_retry = fake_act
        OODASteps._verify = crash_verify_once
        o1_run_id = {"id": None}
        try:
            o1 = Orchestrator(cfg)
            o1.resume_requested = True
            crashed = False
            try:
                o1.run()
            except RuntimeError:
                crashed = True
            assert crashed, "expected a crash during round 1 Verify"
            assert calls["act"] == 1
            o1_run_id["id"] = o1._run_id

            OODASteps._verify = orig_verify  # resumed Verify must run normally
            o2 = Orchestrator(cfg)
            o2.resume_requested = True
            o2.run()

            assert calls["act"] == 1, f"Act not re-run across resume; calls={calls['act']}"
            assert len(o2.store.get_rounds()) == 1, "exactly one round completed"
            assert o2.store.learn_done(o2._run_id, 1) is True
        finally:
            OODASteps._act_with_retry = orig_act
            OODASteps._verify = orig_verify


def test_run_resume_resets_on_pool_mismatch():
    """W1-RESUME-01 Slice 4 (pool_hash gate): crash mid-round stores a checkpoint with pool_hash(A); rewriting the seed file to pool B then resuming makes pool_matches(A,B) False, so the gate resets and drops the mid-round step-resume -> Act RE-RUNS on B (the saved act_result was for the old pool) plus a warning. Inverse of test_run_level_resume_after_act_crash (pool unchanged -> Act skipped)."""
    with tempfile.TemporaryDirectory() as td:
        cfg, db = _cfg(td, max_rounds=2)
        sig_path = cfg["loop"]["signals"]
        calls = {"act": 0}

        def fake_act(*a, **k):
            calls["act"] += 1
            return (dict(ERR_ACT), [])

        v = {"n": 0}
        orig_verify = OODASteps._verify

        def crash_verify_once(act_result, criteria, bar=None):
            v["n"] += 1
            if v["n"] == 1:
                raise RuntimeError("boom-pool")
            return orig_verify(act_result, criteria, bar)

        orig_act = OODASteps._act_with_retry
        OODASteps._act_with_retry = fake_act
        OODASteps._verify = crash_verify_once

        import logging
        captured = []

        class _Cap(logging.Handler):
            def emit(self, rec):
                if "pool_hash mismatch" in rec.getMessage():
                    captured.append(rec.getMessage())

        cap = _Cap()
        cap.setLevel(logging.WARNING)
        prev_level = orchestrator._log.level
        orchestrator._log.addHandler(cap)
        orchestrator._log.setLevel(logging.WARNING)
        try:
            o1 = Orchestrator(cfg)
            o1.resume_requested = True
            crashed = False
            try:
                o1.run()
            except RuntimeError:
                crashed = True
            assert crashed and calls["act"] == 1, ("pre-crash Act must run once; calls=" + str(calls["act"]))
            rid = o1._run_id

            Path(sig_path).write_text(json.dumps([{"signal_pattern": "changed-pattern", "market_condition": "z"}]), encoding="utf-8")

            OODASteps._verify = orig_verify
            o2 = Orchestrator(cfg)
            o2.resume_requested = True
            o2.run()

            assert calls["act"] == 2, ("pool-change gate must drop step-resume and re-run Act; calls=" + str(calls["act"]))
            assert captured, "gate must log a pool_hash-mismatch warning"
            assert len(o2.store.get_rounds()) == 1
            assert o2.store.learn_done(rid, 1) is True
        finally:
            OODASteps._act_with_retry = orig_act
            OODASteps._verify = orig_verify
            orchestrator._log.removeHandler(cap)
            orchestrator._log.setLevel(prev_level)


def test_checkpoint_payload_records_idempotency_signature_and_attempt():
    """W1-RESUME-01 Slice 6: checkpoint records the protocol idempotency key.

    Asserts the v005 idempotency columns are written by _checkpoint_payload and
    round-trip through the store:
      * attempt == 0 on a first pass and == 1 on a resume pass;
      * idempotency_signature is deterministic (same inputs -> same signature,
        changed artifacts -> changed signature) and attempt-independent;
      * both columns persist across save_checkpoint / load_latest_checkpoint.
    """
    with tempfile.TemporaryDirectory(prefix="loop-resume-sig-") as td:
        cfg, db = _cfg(td)
        o = Orchestrator(cfg)
        o._resume_pass = False  # explicit first pass
        o._run_id = "loop-resume-sig-run"
        arts = {"artifacts": {"trade_id": "t1"}}
        ck0 = o._checkpoint_payload("act", arts)
        assert ck0["attempt"] == 0, "first pass -> attempt=0"
        sig0 = ck0["idempotency_signature"]
        assert sig0, "first-pass signature must be non-empty"
        # Determinism: same inputs -> identical signature.
        ck1 = o._checkpoint_payload("act", arts)
        assert ck1["attempt"] == 0
        assert ck1["idempotency_signature"] == sig0, "same inputs -> same signature"
        # Resume pass flips attempt only; signature stays attempt-independent.
        o._resume_pass = True
        ck2 = o._checkpoint_payload("act", arts)
        assert ck2["attempt"] == 1, "resume pass -> attempt=1"
        assert ck2["idempotency_signature"] == sig0, "signature is attempt-independent"
        # Changed artifacts -> changed signature.
        ck3 = o._checkpoint_payload("act", {"artifacts": {"trade_id": "t2"}})
        assert ck3["idempotency_signature"] != sig0, "changed artifacts -> changed signature"
        # Persist both columns across save/load roundtrip on the v5 table.
        o.store.save_checkpoint(ck0)
        loaded = o.store.load_latest_checkpoint(ck0["task_name"])
        assert loaded is not None, "checkpoint must persist across save/load"
        assert loaded["attempt"] == ck0["attempt"], "attempt column must persist"
        assert loaded["idempotency_signature"] == ck0["idempotency_signature"], "signature column must persist"


if __name__ == "__main__":
    for fn in (
        test_checkpoint_payload_records_idempotency_signature_and_attempt,
        test_resume_at_act_skips_rerunning_act,
        test_resume_at_verify_skips_to_learn,
        test_resume_at_learn_skips_non_idempotent_producers,
        test_normal_round_saves_all_step_checkpoints,
        test_run_level_resume_after_act_crash,
        test_run_resume_resets_on_pool_mismatch,
    ):
        fn()
        print(f"PASS {fn.__name__}")
