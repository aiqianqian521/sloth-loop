"""v3: add fields required by L2 suggestion verification."""
from __future__ import annotations

import sqlite3

from .base import Migration

_COLUMNS = (
    ("target_param", "TEXT DEFAULT ''"),
    ("old_value", "TEXT DEFAULT ''"),
    ("new_value", "TEXT DEFAULT ''"),
    ("confidence", "REAL DEFAULT 0.5"),
    ("verify_result", "TEXT DEFAULT ''"),
)


def _up(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(l2_suggestions)")}
    for name, declaration in _COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE l2_suggestions ADD COLUMN {name} {declaration}")


def _down(conn: sqlite3.Connection) -> None:
    # Rebuild instead of relying on SQLite DROP COLUMN version support. This is
    # intentionally destructive and therefore only invoked explicitly.
    secondary_objects = [row[0] for row in conn.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name='l2_suggestions' "
        "AND type IN ('index','trigger') AND sql IS NOT NULL")]
    conn.execute("ALTER TABLE l2_suggestions RENAME TO l2_suggestions_v3_old")
    conn.execute("""
        CREATE TABLE l2_suggestions (
            id TEXT PRIMARY KEY,
            analysis_id INTEGER,
            category TEXT,
            priority TEXT,
            suggestion TEXT,
            auto_applicable INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            applied_at TEXT
        )
    """)
    conn.execute("""
        INSERT INTO l2_suggestions
          (id, analysis_id, category, priority, suggestion, auto_applicable, status, created_at, applied_at)
        SELECT id, analysis_id, category, priority, suggestion, auto_applicable, status, created_at, applied_at
        FROM l2_suggestions_v3_old
    """)
    conn.execute("DROP TABLE l2_suggestions_v3_old")
    for sql in secondary_objects:
        conn.execute(sql)


MIGRATION = Migration(
    version=3,
    description="L2 suggestion result-contract metadata",
    up=_up,
    down=_down,
    fingerprint="add target_param,old_value,new_value,confidence,verify_result; down rebuild base table",
)
