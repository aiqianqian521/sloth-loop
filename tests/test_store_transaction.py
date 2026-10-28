"""W1-STORE-01 R1: PatternStore public API participates in one atomic Learn
unit when called inside ``with store.transaction()``.

The Learn step composes several public helpers (append_failure / bump_failure
/ log_round / problem_queue / L2 records) that previously opened independent
connections; a crash mid-Learn could leave fragmentary patterns with no round
row.  With the bound-connection design these helpers reuse the in-flight
transactional connection so the whole unit commits or rolls back together.
"""
from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import pytest  # noqa: E402
from memory_store import PatternStore  # noqa: E402


def _failure_sample(rid, signal_pattern="alpha"):
    return {
        "id": rid, "date": "20260801",
        "signal_pattern": signal_pattern, "market_condition": "trend",
        "failure_mode": "INSUFFICIENT_EVIDENCE",
        "impact": {"trades": 1, "win_rate": "0%", "total_pnl": "-1"},
        "root_cause": "synthetic", "solution": "TBD", "verification": "TBD",
        "status": "open", "task_type": "backtest",
        "error_signature": f"sig:{signal_pattern}", "fix_recipe": "",
        "fix_confidence": 0.0,
    }


def test_public_writes_rollback_together_on_exception():
    """Multiple store.* writes inside one transaction all roll back when the
    block raises."""
    with tempfile.TemporaryDirectory(prefix="loop-tx-rollback-") as td:
        store = PatternStore(Path(td) / "patterns.db")
        try:
            with store.transaction():
                store.append_failure([_failure_sample("F-TX-001", "alpha")])
                store.bump_failure("F-TX-001")
                store.log_round(1, 0, 1, 1, 0, "should rollback", "error")
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        assert store.load_failure_patterns() == []
        assert store.get_rounds() == []


def test_public_writes_commit_together_on_success():
    """Multiple store.* writes inside one transaction commit together."""
    with tempfile.TemporaryDirectory(prefix="loop-tx-commit-") as td:
        store = PatternStore(Path(td) / "patterns.db")
        with store.transaction():
            store.append_failure([_failure_sample("F-TX-002", "beta")])
            store.bump_failure("F-TX-002")
            store.log_round(1, 0, 1, 1, 0, "should commit", "success")
        patterns = store.load_failure_patterns()
        rounds = store.get_rounds()
        assert len(patterns) == 1 and patterns[0]["id"] == "F-TX-002"
        assert patterns[0]["impact_trades"] >= 1
        assert len(rounds) == 1 and rounds[0]["notes"] == "should commit"


def test_nested_transaction_reuses_bound_connection():
    """bump_failure's own transaction() reuses the outer bound connection
    instead of opening a second writer.  Outer scope still owns commit."""
    with tempfile.TemporaryDirectory(prefix="loop-tx-nested-") as td:
        store = PatternStore(Path(td) / "patterns.db")
        with store.transaction():
            store.append_failure([_failure_sample("F-TX-003", "gamma")])
            store.bump_failure("F-TX-003")  # opens nested transaction()
            assert store._tx_conn is not None, "bound conn must remain during outer tx"
        assert store._tx_conn is None, "bound conn must be released after outer tx"
        assert len(store.load_failure_patterns()) == 1


def test_independent_writes_outside_transaction_remain_idempotent():
    """Smoke check: existing standalone public-API behavior (each call commits
    its own short transaction) still works as before."""
    with tempfile.TemporaryDirectory(prefix="loop-tx-standalone-") as td:
        store = PatternStore(Path(td) / "patterns.db")
        store.append_failure([_failure_sample("F-TX-004", "delta")])
        store.log_round(1, 0, 1, 1, 0, "standalone", "success")
        assert len(store.load_failure_patterns()) == 1
        assert len(store.get_rounds()) == 1


# W1-STORE-01 FIXED: seam unified (migrations/base.py _open: timeout+WAL+busy_timeout) + app-level SQLITE_BUSY retry (memory_store._acquire_immediate). Un-xfailed; must stay green.
def test_concurrent_writers_settle_with_busy_timeout():
    """Two worker threads, each with its own PatternStore on a shared WAL
    database, run independent transactions.  ``BEGIN IMMEDIATE`` plus
    ``busy_timeout=30000`` must serialize lock acquisition so no writer sees an
    unhandled 'database is locked' error and all 60 rows land."""
    with tempfile.TemporaryDirectory(prefix="loop-tx-concurrent-", ignore_cleanup_errors=True) as td:
        db = Path(td) / "patterns.db"
        errors = []
        # Pre-open once to ensure the file + WAL are initialized.
        PatternStore(db)

        def worker(tid, count):
            try:
                local = PatternStore(db)  # thread-private store + connection
                for i in range(count):
                    rid = f"F-{tid:03d}-{i:04d}"
                    with local.transaction():
                        local.append_failure([
                            _failure_sample(rid, f"w{tid}-{i}")
                        ])
                        local.log_round(1, 0, 1, 1, 0, f"w{tid}-{i}", "success")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(1, 30)),
            threading.Thread(target=worker, args=(2, 30)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"concurrent writers raised: {[str(e) for e in errors]}"
        final = PatternStore(db)
        assert len(final.load_failure_patterns()) == 60
        assert len(final.get_rounds()) == 60


if __name__ == "__main__":
    for fn in (
        test_public_writes_rollback_together_on_exception,
        test_public_writes_commit_together_on_success,
        test_nested_transaction_reuses_bound_connection,
        test_independent_writes_outside_transaction_remain_idempotent,
        test_concurrent_writers_settle_with_busy_timeout,
    ):
        fn()
        print(f"PASS {fn.__name__}")
