"""PatternStore corrections mixin - H1-P1g godfile split (behavior-preserving).

upsert_correction / load_corrections / record_correction_hit /
find_failure_by_signature / bump_fix_confidence moved from
memory_store.PatternStore to this mixin; PatternStore inherits it.
Depends on json/sqlite3/datetime + self._connect (resolved at runtime via MRO).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime


class PatternStoreCorrections:
    """Phase 0 correction-rule persistence + failure lookup. Inherited by PatternStore."""

    # ── Phase 0: corrections 持久化 ──────────────────────────────

    def upsert_correction(self, correction: dict):
        """写入或更新一条矫正规则。"""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO corrections
                   (id, task_type, severity, trigger_signature, condition_params,
                    action_type, fix_template, source_problem_id, created_at,
                    last_hit_at, hit_count, confidence, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (correction["id"], correction.get("task_type", "*"),
                 correction.get("severity", "warn"),
                 correction.get("trigger_signature", ""),
                 json.dumps(correction.get("condition_params", {}), ensure_ascii=False),
                 correction.get("action_type", "suggest"),
                 correction.get("fix_template", ""),
                 correction.get("source_problem_id", ""),
                 correction.get("created_at", datetime.now().isoformat()),
                 correction.get("last_hit_at"), correction.get("hit_count", 0),
                 correction.get("confidence", 0.0), correction.get("status", "active")))

    def load_corrections(self, task_type: str | None = None) -> list[dict]:
        """加载矫正规则。task_type=None 返回全部。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if task_type:
                rows = conn.execute(
                    "SELECT * FROM corrections WHERE status='active' AND (task_type=? OR task_type='*')",
                    (task_type,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM corrections WHERE status='active'").fetchall()
        return [dict(r) for r in rows]

    def record_correction_hit(self, correction_id: str):
        """记录规则被命中。"""
        with self._connect() as conn:
            conn.execute(
                """UPDATE corrections SET hit_count=COALESCE(hit_count,0)+1,
                   last_hit_at=? WHERE id=?""",
                (datetime.now().isoformat(), correction_id))

    def find_failure_by_signature(self, task_type: str, error_signature: str) -> dict | None:
        """按 task_type + error_signature 查已有失败记录。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM failure_patterns
                   WHERE task_type=? AND error_signature=? LIMIT 1""",
                (task_type, error_signature)).fetchone()
        return dict(row) if row else None

    def bump_fix_confidence(self, pid: str):
        """修复方案验证通过一次：累加 fix_confidence。"""
        with self._connect() as conn:
            conn.execute(
                """UPDATE failure_patterns
                   SET fix_confidence = MIN(COALESCE(fix_confidence, 0) + 0.1, 1.0)
                   WHERE id = ?""", (pid,))

