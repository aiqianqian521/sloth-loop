"""v4: W1 learn-idempotency ledger - one row per (run_id, round) that committed a Learn unit.

Closes critical③ (scheme §一③): a round that crashes AFTER its Learn unit
committed (patterns + rounds row) but BEFORE the round_end checkpoint is
persisted leaves only the round_start checkpoint; resume replays the whole
round and would re-run Learn - duplicating the rounds row and re-bumping
failure-pattern occurrences, polluting PatternStore. The run_learns ledger
makes the Learn unit idempotent per (run_id, round): on replay, if the row
already exists the Orchestrator skips _learn and log_round (returns zeros),
and the ledger row commits in the SAME atomic transaction as the patterns +
rounds row so a mid-unit crash still leaves no partial state for the next
replay to double-count.
"""
from __future__ import annotations

import sqlite3

from .base import Migration


def _up(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS run_learns (
            run_id TEXT NOT NULL,
            round INTEGER NOT NULL,
            learned_at TEXT NOT NULL,
            PRIMARY KEY (run_id, round)
        )"""
    )


def _down(conn: sqlite3.Connection) -> None:
    # Rehearsal-only: the ledger is derived from rounds/PatternStore and can be
    # rebuilt by replaying the Learn contract, so the down migration simply
    # drops the table (gated behind explicit allow_destructive by the runner).
    conn.execute("DROP TABLE IF EXISTS run_learns")


MIGRATION = Migration(
    version=4,
    description="W1 learn idempotency ledger (run_learns per run_id,round)",
    up=_up,
    down=_down,
    fingerprint="add run_learns(run_id,round,learned_at) idempotency ledger; down drops table",
)
