"""v2: generic task fields, corrections, sessions and resumable checkpoints."""
from __future__ import annotations

import sqlite3

from .base import Migration

_COLUMNS = {
    "failure_patterns": (
        ("occurrences", "INTEGER DEFAULT 1"), ("last_seen", "TEXT"),
        ("task_type", "TEXT DEFAULT 'backtest'"), ("error_signature", "TEXT"),
        ("error_params", "TEXT"), ("fix_recipe", "TEXT"),
        ("fix_confidence", "REAL DEFAULT 0.0"), ("rule_type", "TEXT DEFAULT 'signal'")),
    "success_patterns": (("occurrences", "INTEGER DEFAULT 1"), ("last_seen", "TEXT")),
    "problem_queue": (
        ("error_signature", "TEXT"), ("recurrence_count", "INTEGER DEFAULT 1"),
        ("l1_attempts", "TEXT"), ("task_step", "TEXT"),
        ("expected_behavior", "TEXT"), ("env_snapshot", "TEXT")),
    "rounds": (("status", "TEXT DEFAULT 'success'"),),
    "run_history": (
        ("l2_health_score", "REAL DEFAULT 0"), ("l2_trigger_type", "TEXT"),
        ("problem_summary", "TEXT"), ("decision_context", "TEXT")),
}


def _up(conn: sqlite3.Connection) -> None:
    for table, columns in _COLUMNS.items():
        existing = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        for name, declaration in columns:
            if name not in existing:
                conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}')
    statements = (
        """CREATE TABLE IF NOT EXISTS corrections (
          id TEXT PRIMARY KEY, task_type TEXT NOT NULL DEFAULT '*',
          severity TEXT NOT NULL DEFAULT 'warn', trigger_signature TEXT NOT NULL,
          condition_params TEXT, action_type TEXT NOT NULL DEFAULT 'suggest',
          fix_template TEXT, source_problem_id TEXT, created_at TEXT, last_hit_at TEXT,
          hit_count INTEGER DEFAULT 0, confidence REAL DEFAULT 0.0,
          status TEXT DEFAULT 'active')""",
        """CREATE TABLE IF NOT EXISTS task_sessions (
          id TEXT PRIMARY KEY, task_name TEXT NOT NULL, status TEXT DEFAULT 'pending',
          user_input TEXT, understanding TEXT, signals_count INTEGER DEFAULT 0,
          verification_cfg TEXT, created_at TEXT, confirmed_at TEXT, started_at TEXT,
          finished_at TEXT, total_rounds INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0,
          failure_count INTEGER DEFAULT 0, stop_reason TEXT, defect_report_path TEXT)""",
        """CREATE TABLE IF NOT EXISTS run_checkpoints (
          run_id TEXT PRIMARY KEY, task_name TEXT NOT NULL, round INTEGER DEFAULT 0,
          step TEXT DEFAULT '', attempt INTEGER DEFAULT 0, signal_cursor INTEGER DEFAULT 0,
          pool_hash TEXT DEFAULT '', config_hash TEXT DEFAULT '', last_event_seq INTEGER DEFAULT 0,
          consecutive_failures INTEGER DEFAULT 0, payload TEXT DEFAULT '{}', updated_at TEXT NOT NULL)""",
    )
    for statement in statements:
        conn.execute(statement)


def _down(conn: sqlite3.Connection) -> None:
    # Column removal is deliberately implemented as table rebuilds so the
    # rehearsal works on every supported SQLite version.
    for table in ("run_checkpoints", "task_sessions", "corrections"):
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    definitions = {
        "failure_patterns": "id TEXT PRIMARY KEY,date TEXT,signal_pattern TEXT,market_condition TEXT,failure_mode TEXT,impact_trades INTEGER DEFAULT 0,impact_win_rate TEXT,impact_total_pnl TEXT,root_cause TEXT,solution TEXT,verification TEXT,status TEXT,exclusion_rule TEXT",
        "success_patterns": "id TEXT PRIMARY KEY,date TEXT,signal_pattern TEXT,market_condition TEXT,entry TEXT,stop_loss TEXT,take_profit TEXT,position_size TEXT,quarters_tested INTEGER DEFAULT 0,quarters_positive INTEGER DEFAULT 0,avg_sharpe REAL DEFAULT 0,avg_annual_excess TEXT,status TEXT,reuse_rule TEXT",
        "problem_queue": "id TEXT PRIMARY KEY,type TEXT NOT NULL,severity TEXT NOT NULL,source TEXT,round INTEGER,context TEXT,evidence TEXT,suggested_action TEXT,status TEXT DEFAULT 'queued',created_at TEXT,resolved_at TEXT",
        "rounds": "id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,input_count INTEGER,excluded_count INTEGER,passed_count INTEGER,new_failures INTEGER,new_successes INTEGER,notes TEXT",
        "run_history": "id TEXT PRIMARY KEY,task TEXT,total_rounds INTEGER,elapsed_seconds REAL,stop_reason TEXT,new_failures INTEGER,new_successes INTEGER,active_rules INTEGER DEFAULT 0,problems_queued INTEGER DEFAULT 0,verdict TEXT,created_at TEXT",
    }
    for table, definition in definitions.items():
        keep = [part.strip().split()[0] for part in definition.split(",")]
        old = f"{table}_v2_old"
        conn.execute(f'ALTER TABLE "{table}" RENAME TO "{old}"')
        conn.execute(f'CREATE TABLE "{table}" ({definition})')
        columns = ",".join(f'"{name}"' for name in keep)
        conn.execute(f'INSERT INTO "{table}" ({columns}) SELECT {columns} FROM "{old}"')
        conn.execute(f'DROP TABLE "{old}"')


MIGRATION = Migration(
    version=2, description="W1 checkpoints + connection policy", up=_up, down=_down,
    fingerprint="add generic fields and corrections/task_sessions/run_checkpoints",
)
