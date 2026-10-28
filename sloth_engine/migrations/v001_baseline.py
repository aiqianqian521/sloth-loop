"""v1: create the original Loop persistence schema."""
from __future__ import annotations

import sqlite3

from .base import Migration


def _up(conn: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS failure_patterns (
          id TEXT PRIMARY KEY, date TEXT, signal_pattern TEXT, market_condition TEXT,
          failure_mode TEXT, impact_trades INTEGER DEFAULT 0, impact_win_rate TEXT,
          impact_total_pnl TEXT, root_cause TEXT, solution TEXT, verification TEXT,
          status TEXT, exclusion_rule TEXT)""",
        """CREATE TABLE IF NOT EXISTS success_patterns (
          id TEXT PRIMARY KEY, date TEXT, signal_pattern TEXT, market_condition TEXT,
          entry TEXT, stop_loss TEXT, take_profit TEXT, position_size TEXT,
          quarters_tested INTEGER DEFAULT 0, quarters_positive INTEGER DEFAULT 0,
          avg_sharpe REAL DEFAULT 0, avg_annual_excess TEXT, status TEXT, reuse_rule TEXT)""",
        """CREATE TABLE IF NOT EXISTS rounds (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, input_count INTEGER,
          excluded_count INTEGER, passed_count INTEGER, new_failures INTEGER,
          new_successes INTEGER, notes TEXT)""",
        """CREATE TABLE IF NOT EXISTS problem_queue (
          id TEXT PRIMARY KEY, type TEXT NOT NULL, severity TEXT NOT NULL, source TEXT,
          round INTEGER, context TEXT, evidence TEXT, suggested_action TEXT,
          status TEXT DEFAULT 'queued', created_at TEXT, resolved_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS run_history (
          id TEXT PRIMARY KEY, task TEXT, total_rounds INTEGER, elapsed_seconds REAL,
          stop_reason TEXT, new_failures INTEGER, new_successes INTEGER,
          active_rules INTEGER DEFAULT 0, problems_queued INTEGER DEFAULT 0,
          verdict TEXT, created_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS l2_analysis (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, trigger_type TEXT,
          health_score REAL, progress_speed REAL, error_recurrence REAL,
          fix_effectiveness REAL, pattern_diversity REAL, stop_signal TEXT, summary TEXT)""",
        """CREATE TABLE IF NOT EXISTS l2_suggestions (
          id TEXT PRIMARY KEY, analysis_id INTEGER, category TEXT, priority TEXT,
          suggestion TEXT, auto_applicable INTEGER DEFAULT 0,
          status TEXT DEFAULT 'pending', created_at TEXT, applied_at TEXT)""",
    )
    for statement in statements:
        conn.execute(statement)


def _down(conn: sqlite3.Connection) -> None:
    for table in ("l2_suggestions", "l2_analysis", "run_history", "problem_queue",
                  "rounds", "success_patterns", "failure_patterns"):
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')


MIGRATION = Migration(
    version=1, description="baseline schema", up=_up, down=_down,
    fingerprint="create failure/success/round/problem/history/l2 baseline tables",
)
