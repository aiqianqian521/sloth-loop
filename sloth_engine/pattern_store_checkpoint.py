"""PatternStore checkpoint/resume mixin - H1-P1e godfile split (behavior-preserving).

save_checkpoint / load_checkpoint / load_latest_checkpoint / clear_checkpoint /
learn_done / mark_learn_done moved from memory_store.PatternStore to this mixin;
PatternStore inherits it. Depends on json/sqlite3/datetime + self._connect /
self.transaction (resolved at runtime via MRO). Zero module-level deps on memory_store.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime


class PatternStoreCheckpoint:
    """W1: checkpoint/resume persistence. Inherited by PatternStore."""

    # W1: checkpoint/resume -------------------------------------------------

    def save_checkpoint(self, checkpoint: dict) -> None:
        """Atomically upsert the latest resumable loop position.

        The payload is intentionally opaque JSON so adding controller fields
        does not require a schema migration for every new OODA step.
        """
        required = ("run_id", "task_name")
        missing = [k for k in required if not checkpoint.get(k)]
        if missing:
            raise ValueError(f"checkpoint missing required fields: {missing}")
        payload = checkpoint.get("payload", {})
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO run_checkpoints
                   (run_id, task_name, round, step, attempt, signal_cursor,
                    pool_hash, config_hash, last_event_seq,
                    consecutive_failures, payload, idempotency_signature, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET
                     task_name=excluded.task_name, round=excluded.round,
                     step=excluded.step, attempt=excluded.attempt,
                     signal_cursor=excluded.signal_cursor,
                     pool_hash=excluded.pool_hash,
                     config_hash=excluded.config_hash,
                     last_event_seq=excluded.last_event_seq,
                     consecutive_failures=excluded.consecutive_failures,
                     payload=excluded.payload,
                     idempotency_signature=excluded.idempotency_signature,
                     updated_at=excluded.updated_at""",
                (checkpoint["run_id"], checkpoint["task_name"],
                 int(checkpoint.get("round", 0)), checkpoint.get("step", ""),
                 int(checkpoint.get("attempt", 0)),
                 int(checkpoint.get("signal_cursor", 0)),
                 checkpoint.get("pool_hash", ""), checkpoint.get("config_hash", ""),
                 int(checkpoint.get("last_event_seq", 0)),
                 int(checkpoint.get("consecutive_failures", 0)), payload,
                                  checkpoint.get("idempotency_signature", ""),
                 checkpoint.get("updated_at", datetime.now().isoformat())))

    def load_checkpoint(self, run_id: str) -> dict | None:
        """Return a checkpoint with its JSON payload decoded."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM run_checkpoints WHERE run_id=?", (run_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["payload"] = json.loads(result.get("payload") or "{}")
        except (TypeError, json.JSONDecodeError):
            result["payload"] = {}
        return result

    def load_latest_checkpoint(self, task_name: str) -> dict | None:
        """Load the newest unfinished checkpoint for a task."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM run_checkpoints WHERE task_name=?
                   ORDER BY updated_at DESC LIMIT 1""", (task_name,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["payload"] = json.loads(result.get("payload") or "{}")
        except (TypeError, json.JSONDecodeError):
            result["payload"] = {}
        return result

    def clear_checkpoint(self, run_id: str) -> None:
        """Remove a completed/aborted checkpoint."""
        with self._connect() as conn:
            conn.execute("DELETE FROM run_checkpoints WHERE run_id=?", (run_id,))

    def learn_done(self, run_id: str, round: int) -> bool:
        """Has the Learn unit for (run_id, round) already committed?

        W1-RESUME-01 Slice 2: the run_learns ledger records each (run_id, round)
        pair whose Learn unit (patterns + rounds row) committed atomically;
        this read lets the Learn unit skip a replayed round instead of
        duplicating patterns/rounds (critical③). Reads join any active
        transaction via the bound connection.
        """
        if not run_id or round is None:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM run_learns WHERE run_id=? AND round=? LIMIT 1",
                (run_id, int(round)),
            ).fetchone()
        return row is not None

    def mark_learn_done(self, run_id: str, round: int) -> None:
        """Record that (run_id, round) committed its Learn unit (idempotent)."""
        if not run_id or round is None:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO run_learns (run_id, round, learned_at) "
                "VALUES (?, ?, ?)",
                (run_id, int(round), datetime.now().isoformat()),
            )
