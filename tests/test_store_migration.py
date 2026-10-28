"""W1 storage contract: transaction atomicity and schema migration ledger."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from memory_store import PatternStore  # noqa: E402


def test_transaction_rolls_back_all_statements() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-store-tx-") as td:
        store = PatternStore(Path(td) / "patterns.db")
        try:
            with store.transaction() as conn:
                conn.execute(
                    "INSERT INTO rounds(ts, input_count, excluded_count, passed_count, new_failures, new_successes, notes) "
                    "VALUES ('tx', 1, 0, 1, 0, 0, 'should rollback')"
                )
                conn.execute(
                    "INSERT INTO task_sessions(id, task_name, created_at) VALUES ('tx-session', 'tx', 'now')"
                )
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        with store._connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM rounds WHERE ts='tx'").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM task_sessions WHERE id='tx-session'").fetchone()[0] == 0


def test_transaction_commits_multi_table_unit() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-store-commit-") as td:
        store = PatternStore(Path(td) / "patterns.db")
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO rounds(ts, input_count, excluded_count, passed_count, new_failures, new_successes, notes) "
                "VALUES ('commit', 1, 0, 1, 0, 0, 'committed')"
            )
            conn.execute(
                "INSERT INTO task_sessions(id, task_name, created_at) VALUES ('commit-session', 'commit', 'now')"
            )

        with store._connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM rounds WHERE ts='commit'").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM task_sessions WHERE id='commit-session'").fetchone()[0] == 1


def test_legacy_database_is_upgraded_and_ledger_is_recorded() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-store-migrate-") as td:
        db_path = Path(td) / "legacy.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE failure_patterns (id TEXT PRIMARY KEY, signal_pattern TEXT, market_condition TEXT)"
            )
            conn.commit()
        finally:
            conn.close()

        store = PatternStore(db_path, auto_migrate=True)
        assert store.schema_version() == 6
        with store._connect() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(failure_patterns)")}
            assert {"occurrences", "last_seen", "error_signature", "fix_confidence"}.issubset(columns)
            assert "idempotency_signature" in {row[1] for row in conn.execute("PRAGMA table_info(run_checkpoints)")}
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_sentinel_%'"
            ).fetchone()[0] == 10
            ledger = conn.execute(
                "SELECT version, description, checksum, status FROM schema_versions ORDER BY version"
            ).fetchall()

        assert [row[0] for row in ledger] == [1, 2, 3, 4, 5, 6]
        assert all(row[2] and row[3] == "applied" for row in ledger)


def test_schema_migration_is_idempotent() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-store-idempotent-") as td:
        db_path = Path(td) / "patterns.db"
        first = PatternStore(db_path)
        with first._connect() as conn:
            before = conn.execute("SELECT version, checksum FROM schema_versions ORDER BY version").fetchall()
        second = PatternStore(db_path)
        with second._connect() as conn:
            after = conn.execute("SELECT version, checksum FROM schema_versions ORDER BY version").fetchall()
        assert before == after


if __name__ == "__main__":
    for _test in (
        test_transaction_rolls_back_all_statements,
        test_transaction_commits_multi_table_unit,
        test_legacy_database_is_upgraded_and_ledger_is_recorded,
        test_schema_migration_is_idempotent,
    ):
        _test()
        print(f"PASS {_test.__name__}")
