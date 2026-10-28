"""v6: business commit sentinel for time-point RPO.

The rehearsal used to report RPO as a ``row_count_proxy``: "the restored copy
has as many rows as the source".  That is not a recovery point in time -- it
cannot answer "up to which committed business unit did we recover".

v6 adds an append-only ``commit_sentinel`` watermark.  Rows are written by
SQLite **triggers** on the Learn/Pattern business tables, so the marker is
produced by the database itself inside the *same transaction* as the business
write.  No application call site can forget it, no write path can bypass it,
and a rolled-back business write can never leave a sentinel behind.

``committed_at`` is a UTC ISO-8601 string with millisecond precision
(``YYYY-MM-DDTHH:MM:SS.sssZ``), lexicographically sortable.  ``seq`` is the
AUTOINCREMENT ordering key and disambiguates writes that share a millisecond.

Rows that already existed when the sentinel was introduced are backfilled once
with the migration timestamp, i.e. "known committed when the sentinel was
created" -- the honest watermark for historical rows.
"""
from __future__ import annotations

import sqlite3

from .base import Migration

# Business tables that represent a committed Learn/Pattern unit -> scope label.
_SCOPE_BY_TABLE = (
    ("rounds", "round"),
    ("run_learns", "learn"),
    ("failure_patterns", "failure_pattern"),
    ("success_patterns", "success_pattern"),
    ("l2_suggestions", "l2_suggestion"),
)

# INSERT == a new unit; UPDATE == a committed mutation of an existing unit.
_EVENTS = ("INSERT", "UPDATE")

_NOW_UTC = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS commit_sentinel (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    committed_at TEXT NOT NULL
)"""

_CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_commit_sentinel_seq_at "
    "ON commit_sentinel(committed_at, seq)"
)


def _trigger_name(table: str, event: str) -> str:
    return f"trg_sentinel_{table}_{event.lower()}"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _drop_triggers(conn: sqlite3.Connection) -> None:
    for table, _scope in _SCOPE_BY_TABLE:
        for event in _EVENTS:
            conn.execute(f"DROP TRIGGER IF EXISTS {_trigger_name(table, event)}")


def _up(conn: sqlite3.Connection) -> None:
    fresh = not _table_exists(conn, "commit_sentinel")
    conn.execute(_CREATE_TABLE)
    conn.execute(_CREATE_INDEX)
    if fresh:
        # Backfill exactly once, when the sentinel is introduced.  SQLite fixes
        # 'now' for the duration of one statement, so every backfilled row of a
        # table shares one timestamp and is ordered by seq.
        for table, scope in _SCOPE_BY_TABLE:
            if _table_exists(conn, table):
                conn.execute(
                    f"INSERT INTO commit_sentinel(scope, committed_at) "
                    f"SELECT '{scope}', {_NOW_UTC} FROM \"{table}\""
                )
    for table, scope in _SCOPE_BY_TABLE:
        if not _table_exists(conn, table):
            continue
        for event in _EVENTS:
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {_trigger_name(table, event)} "
                f"AFTER {event} ON \"{table}\" BEGIN "
                f"INSERT INTO commit_sentinel(scope, committed_at) "
                f"VALUES('{scope}', {_NOW_UTC}); END"
            )


def _down(conn: sqlite3.Connection) -> None:
    # Rehearsal-only: the sentinel is derived from the business tables and can be
    # rebuilt (backfilled) by re-applying v6, so down just drops it.
    _drop_triggers(conn)
    conn.execute("DROP TABLE IF EXISTS commit_sentinel")


MIGRATION = Migration(
    version=6,
    description="business commit sentinel for time-point RPO",
    up=_up,
    down=_down,
    fingerprint="add commit_sentinel + triggers on rounds/run_learns/patterns/l2_suggestions",
)
