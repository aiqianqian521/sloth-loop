"""Business commit sentinel (schema v6): the RPO watermark is written by the database.

These tests pin the *mechanism*, not the rehearsal script.  The marker must be
written by SQLite inside the same transaction as the business write, must not
exist when that write rolls back, must be rebuilt by the migration itself, and
must backfill exactly once for rows that predate it.  This is what makes the
rehearsal's time-point RPO a fact rather than an app-level convention.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from memory_store import PatternStore  # noqa: E402
from migrations import MIGRATIONS, MigrationRunner  # noqa: E402


def _fetch(path: Path, sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _execute(path: Path, sql: str, params: tuple = ()) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _sentinel_count(path: Path, scope: str | None = None) -> int:
    if scope is None:
        return _fetch(path, "SELECT COUNT(*) FROM commit_sentinel")[0][0]
    return _fetch(path, "SELECT COUNT(*) FROM commit_sentinel WHERE scope=?", (scope,))[0][0]


def _scopes(path: Path) -> set[str]:
    return {row[0] for row in _fetch(path, "SELECT DISTINCT scope FROM commit_sentinel")}


def _object_count(path: Path, like: str) -> int:
    return _fetch(
        path, "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE ?", (like,))[0][0]


def test_business_writes_emit_scoped_sentinels() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-sentinel-") as td:
        store = PatternStore(Path(td) / "patterns.db")
        store.insert_l2_suggestion({"id": "s-1", "category": "c", "suggestion": "x"})
        store.log_round(1, 0, 1, 0, 0, notes="sentinel")
        store.append_failure([{
            "id": "F-1", "date": "2026-10-26", "signal_pattern": "sp",
            "market_condition": "mc", "failure_mode": "fm",
        }])
        db = store.db_path
        assert _scopes(db) >= {"l2_suggestion", "round", "failure_pattern"}
        assert _sentinel_count(db, "l2_suggestion") == 1
        assert _sentinel_count(db, "round") == 1
        assert _sentinel_count(db, "failure_pattern") == 1
        rows = _fetch(db, "SELECT seq, committed_at FROM commit_sentinel ORDER BY seq")
        # Auto-increment ordering is monotonic and the timestamp is a sortable
        # UTC instant, so (committed_at, seq) is a total order over commits.
        assert [row[0] for row in rows] == sorted(row[0] for row in rows)
        assert all(len(row[1]) == 24 and row[1].endswith("Z") for row in rows)


def test_rolled_back_write_leaves_no_sentinel() -> None:
    """The sentinel shares the business transaction; a crash cannot create one."""
    with tempfile.TemporaryDirectory(prefix="loop-sentinel-tx-") as td:
        store = PatternStore(Path(td) / "patterns.db")
        before = _sentinel_count(store.db_path)
        try:
            with store.transaction():
                store.insert_l2_suggestion({"id": "s-rollback", "category": "c"})
                store.log_round(2, 0, 1, 0, 0, notes="must roll back")
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        assert _sentinel_count(store.db_path) == before
        assert _fetch(
            store.db_path, "SELECT COUNT(*) FROM l2_suggestions WHERE id='s-rollback'")[0][0] == 0


def test_sentinel_is_rebuilt_by_the_migration_and_dropped_by_down() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-sentinel-mig-") as td:
        db = Path(td) / "patterns.db"
        runner = MigrationRunner(db, MIGRATIONS)
        runner.apply()
        assert runner.current_version() == 6
        _execute(db, "INSERT INTO l2_suggestions(id, category, suggestion) VALUES ('legacy','c','x')")
        assert _sentinel_count(db) == 1  # written by the trigger, not by a caller
        assert runner.rollback(5, allow_destructive=True) == [6]
        assert _object_count(db, "commit_sentinel") == 0
        assert _object_count(db, "trg_sentinel_%") == 0
        assert runner.apply() == [6]
        assert _sentinel_count(db) == 1  # backfilled from the surviving legacy row
        assert _scopes(db) == {"l2_suggestion"}


def test_legacy_rows_are_backfilled_once_at_migration_time() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-sentinel-backfill-") as td:
        db = Path(td) / "patterns.db"
        runner = MigrationRunner(db, MIGRATIONS)
        runner.apply(target_version=5)
        _execute(db, "INSERT INTO l2_suggestions(id, category, suggestion) VALUES ('a','c','x')")
        _execute(db, "INSERT INTO l2_suggestions(id, category, suggestion) VALUES ('b','c','x')")
        _execute(db, "INSERT INTO rounds(ts, input_count, excluded_count, passed_count,"
                     " new_failures, new_successes) VALUES ('t',1,0,1,0,0)")
        assert runner.apply() == [6]
        assert _sentinel_count(db, "l2_suggestion") == 2
        assert _sentinel_count(db, "round") == 1
        # Re-validating an already-applied ledger must not backfill a second time.
        assert runner.apply() == []
        assert _sentinel_count(db) == 3


def test_rehearsal_fails_closed_without_the_sentinel(tmp_path: Path) -> None:
    """No sentinel table == no time point: the rehearsal must refuse, not guess."""
    import pytest

    scripts_dir = str(ROOT / "scripts")
    sys.path.insert(0, scripts_dir)
    try:
        spec = importlib.util.spec_from_file_location(
            "migration_rehearsal_under_test", ROOT / "scripts" / "migration_rehearsal.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_dir)

    database = tmp_path / "patterns.db"
    store = PatternStore(database)
    store.insert_l2_suggestion({"id": "s", "category": "c"})

    original = module._sentinel_present
    module._sentinel_present = lambda path: False
    try:
        with pytest.raises(RuntimeError, match="commit_sentinel missing"):
            module.run_rehearsal(database, tmp_path / "work")
    finally:
        module._sentinel_present = original
