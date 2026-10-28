"""D-C1: a concurrent first-init of a brand-new pattern DB must not be reported
as a legacy database that needs an explicit migration.

``PatternStore.__init__`` decides "new vs legacy" from
``db_path.exists() and size > 0``.  A *racing* process creates the SQLite file
before committing the schema ledger, so an observer could read v0/v2/v3 and fail
closed with "database migration required ... run the explicit migration command"
-- on a database that was one second old.  Found by the 2026-10-25 stress suite
(3 of 4 concurrent ``--once`` runs died this way).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import pytest  # noqa: E402

from memory_store import PatternStore  # noqa: E402
from migrations import MigrationRunner  # noqa: E402


def _make_legacy_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE failure_patterns (id TEXT PRIMARY KEY, signal_pattern TEXT)")
        conn.commit()
    finally:
        conn.close()


def test_concurrent_first_init_converges_instead_of_failing(tmp_path, monkeypatch):
    db = tmp_path / "patterns.db"
    PatternStore(db)  # real current-version database on disk

    real = MigrationRunner.inspect_current_version
    seen = {"n": 0}

    def flaky(self):
        seen["n"] += 1
        if seen["n"] == 1:
            return 0  # the instant after a racing writer touched the file
        return real(self)

    monkeypatch.setattr(MigrationRunner, "inspect_current_version", flaky)

    store = PatternStore(db)  # must NOT raise
    assert seen["n"] >= 2, "must re-inspect after the first stale read"
    assert store.schema_version() == 6


def test_old_legacy_db_still_fails_closed(tmp_path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db)
    old = time.time() - 3600
    os.utime(db, (old, old))  # old file: no grace period, fail fast

    with pytest.raises(RuntimeError, match="migration required"):
        PatternStore(db)


def test_fresh_unversioned_db_still_fails_closed_after_grace(tmp_path, monkeypatch):
    monkeypatch.setattr(PatternStore, "_FIRST_INIT_GRACE_SECONDS", 0.3)
    db = tmp_path / "legacy-fresh.db"
    _make_legacy_db(db)  # v0, freshly written -> waits, then still refuses

    with pytest.raises(RuntimeError, match="migration required"):
        PatternStore(db)


def test_auto_migrate_path_is_unchanged(tmp_path):
    db = tmp_path / "legacy-auto.db"
    _make_legacy_db(db)
    old = time.time() - 3600
    os.utime(db, (old, old))

    store = PatternStore(db, auto_migrate=True)
    assert store.schema_version() == 6
