"""W1-RESUME-01: resume compatibility guard pure-function tests.

These exercise the 4-tuple check (schema_version / task scope / config_hash /
pool_hash) at the resume_guard seam — without booting the full Orchestrator
(architect-test: test at the boundary, don't mock internals). These are the
prerequisites of the kill-point matrix; step-level checkpointing shifts to a
follow-up slice. Run: python tests/test_resume.py  (custom harness; pytest
migration is plan P3.2).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from resume_guard import (compute_config_hash, compute_pool_hash,
                          check_compatibility, pool_matches)  # noqa: E402


def _ck(cfg=None, task="loop", schema=3, pool_hash="", payload=None):
    return {
        "run_id": "r1",
        "task_name": task,
        "config_hash": compute_config_hash(cfg or {}),
        "pool_hash": pool_hash,
        "payload": payload if payload is not None else {"schema_version": schema},
    }


def test_empty_checkpoint_allows_fresh():
    ok, reason = check_compatibility(None, current_cfg={},
                                      current_task_name="loop",
                                      current_schema_version=3)
    assert ok is True, reason


def test_matching_checkpoint_is_compatible():
    cfg = {"task": {"name": "loop"}, "loop": {"max_rounds": 5}}
    ck = _ck(cfg, task="loop", schema=3)
    ok, reason = check_compatibility(ck, current_cfg=cfg,
                                     current_task_name="loop",
                                     current_schema_version=3)
    assert ok, reason


def test_config_drift_is_refused():
    cfg_old = {"loop": {"max_rounds": 5}}
    cfg_new = {"loop": {"max_rounds": 9}}   # changed between crash and resume
    ck = _ck(cfg_old, task="loop", schema=3)
    ok, reason = check_compatibility(ck, current_cfg=cfg_new,
                                     current_task_name="loop",
                                     current_schema_version=3)
    assert ok is False and "config_hash" in reason, reason


def test_task_scope_mismatch_is_refused():
    ck = _ck({"task": {"name": "loop"}}, task="loop", schema=3)
    ok, reason = check_compatibility(ck, current_cfg={},
                                     current_task_name="other-task",
                                     current_schema_version=3)
    assert ok is False and "task_name" in reason, reason


def test_schema_version_mismatch_is_refused():
    ck = _ck({}, task="loop", schema=3)
    ok, reason = check_compatibility(ck, current_cfg={},
                                     current_task_name="loop",
                                     current_schema_version=4)
    assert ok is False and "schema_version" in reason, reason


def test_pool_matches_after_rebuild():
    pool = [{"s": "a"}, {"s": "b"}]
    h = compute_pool_hash(pool)
    assert pool_matches(h, pool) is True
    assert pool_matches(h, [{"s": "a"}, {"s": "DIFFERENT"}]) is False
    assert pool_matches("", pool) is True   # blank stored -> cannot disagree


def test_payload_string_is_decoded_for_schema_check():
    ck = {"task_name": "loop",
          "config_hash": compute_config_hash({}),
          "pool_hash": "",
          "payload": json.dumps({"schema_version": 3})}
    ok, reason = check_compatibility(ck, current_cfg={},
                                     current_task_name="loop",
                                     current_schema_version=4)
    assert ok is False and "schema_version" in reason, reason


def test_store_checkpoint_roundtrip_then_compatibility_refuses_drift():
    import tempfile
    from memory_store import PatternStore  # light seam: no Orchestrator boot
    with tempfile.TemporaryDirectory() as td:
        store = PatternStore(Path(td) / "patterns.db")
        cfg = {"task": {"name": "loop"}, "loop": {"max_rounds": 5}}
        ck = {"run_id": "r1", "task_name": "loop", "round": 1, "step": "round_end",
              "attempt": 0, "signal_cursor": 7, "pool_hash": "x",
              "config_hash": compute_config_hash(cfg), "last_event_seq": 0,
              "consecutive_failures": 0,
              "payload": {"runtime_root": "/x", "breaker": None,
                          "schema_version": store.schema_version()}}
        store.save_checkpoint(ck)
        loaded = store.load_checkpoint("r1")
        assert loaded is not None and loaded["signal_cursor"] == 7
        ok, _ = check_compatibility(loaded, current_cfg=cfg,
                                 current_task_name="loop",
                                 current_schema_version=store.schema_version())
        assert ok, "same-config resume must be compatible"
        cfg2 = {"loop": {"max_rounds": 9}}   # drifted config
        ok2, reason = check_compatibility(loaded, current_cfg=cfg2,
                                     current_task_name="loop",
                                     current_schema_version=store.schema_version())
        assert ok2 is False and "config_hash" in reason, reason
        store.clear_checkpoint("r1")
        assert store.load_checkpoint("r1") is None


def test_learn_idempotent_on_replay():
    """W1-RESUME-01 Slice 2: a replayed (run_id, round) must not double Learn.

    Drives the Learn unit twice with an explicit run_id while total_rounds
    stays 0, so both passes resolve learn_round = 1 (mirroring run()'s
    round_start->replay path). Pass 1 commits patterns + a rounds row + a
    ledger row; pass 2 is a replay-skip (learn_done -> zeros, no log_round).
    This closes critical③ at the round level: no duplicate rounds row, no
    re-bumped occurrences. The data layer is then checked directly to prove
    the v4 migration surfaced the run_learns ledger idempotently.
    """
    import tempfile
    from orchestrator import Orchestrator
    from config_util import deep_merge, DEFAULT_CONFIG
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "p.db"
        cfg = deep_merge(DEFAULT_CONFIG, {
            "runtime": {"root": td, "db": str(db)},
            "memory": {"sqlite_path": str(db)},
            "loop": {"max_rounds": 5, "no_progress_stop": 3,
                     "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
            "backtest": {"script": "backtest/mock_backtest.py",
                         "extra_args": "--seed test --win-bias 0.5"},
        })
        o = Orchestrator(cfg)
        o._run_id = "test-replay-run"        # activate the run-id-keyed ledger
        sigs = [{"signal_pattern": "fail-me-please", "market_condition": "m"}]
        o.run_once(sigs)                      # pass 1: learn commits + ledger row
        o.run_once(sigs)                      # pass 2: same (run_id, round=1) -> skip
        rounds = o.store.get_rounds()
        assert len(rounds) == 1, f"expected 1 rounds row, got {len(rounds)}: {rounds}"
        assert o.store.learn_done("test-replay-run", 1) is True
        assert o.store.learn_done("other-run", 1) is False
        assert o.store.learn_done("test-replay-run", 2) is False
    with tempfile.TemporaryDirectory() as td:
        from memory_store import PatternStore
        st = PatternStore(Path(td) / "p2.db")
        assert st.learn_done("any", 1) is False
        st.mark_learn_done("any", 1)
        assert st.learn_done("any", 1) is True
        st.mark_learn_done("any", 1)         # idempotent insert (same row, no error)
        assert st.learn_done("any", 1) is True
        assert st.learn_done("any", 2) is False


def test_checkpoint_hash_is_single_source():
    """W1-RESUME-01 Slice 2: _checkpoint_payload must use resume_guard hashes.

    Storing config_hash/pool_hash from the SAME helpers resume compares with
    guarantees a checkpoint saved by the orchestrator recomputes identically
    at resume via resume_guard - no second inline implementation can drift
    apart (scheme high② single-source hazard, closed).
    """
    import tempfile
    from orchestrator import Orchestrator
    from config_util import deep_merge, DEFAULT_CONFIG
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "p.db"
        cfg = deep_merge(DEFAULT_CONFIG, {
            "runtime": {"root": td, "db": str(db)},
            "memory": {"sqlite_path": str(db)},
            "loop": {"max_rounds": 3, "no_progress_stop": 3,
                     "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
            "backtest": {"script": "backtest/mock_backtest.py",
                         "extra_args": "--seed test --win-bias 0.5"},
        })
        o = Orchestrator(cfg)
        o._run_id = "r-hash-source"
        payload = o._checkpoint_payload("round_end")
        assert payload["config_hash"] == compute_config_hash(o.cfg), \
            "config_hash not single-source"
        assert payload["pool_hash"] == compute_pool_hash(o._pool or []), \
            "pool_hash not single-source"


if __name__ == "__main__":
    for fn in (
        test_empty_checkpoint_allows_fresh,
        test_matching_checkpoint_is_compatible,
        test_config_drift_is_refused,
        test_task_scope_mismatch_is_refused,
        test_schema_version_mismatch_is_refused,
        test_pool_matches_after_rebuild,
        test_payload_string_is_decoded_for_schema_check,
        test_store_checkpoint_roundtrip_then_compatibility_refuses_drift,
        test_learn_idempotent_on_replay,
        test_checkpoint_hash_is_single_source,
    ):
        fn()
        print(f"PASS {fn.__name__}")
