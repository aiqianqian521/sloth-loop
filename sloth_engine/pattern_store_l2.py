"""PatternStore L2 analysis/suggestion mixin - H1-P1f godfile split (behavior-preserving).

insert_l2_analysis / get_last_l2_analysis / get_l2_analysis /
insert_l2_suggestion / get_pending_suggestions / update_suggestion_status
moved from memory_store.PatternStore to this mixin; PatternStore inherits it.
Depends on sqlite3 / datetime + self._connect (resolved at runtime via MRO).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime


class PatternStoreL2:
    """L2 health-analysis + improvement-suggestion persistence. Inherited by PatternStore."""

    # ── L2: 健康分析持久化 ──────────────────────────────────────

    def insert_l2_analysis(self, analysis: dict) -> int:
        """写入一条 L2 分析快照，返回自增 ID。"""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO l2_analysis (ts, trigger_type, health_score,
                   progress_speed, error_recurrence, fix_effectiveness,
                   pattern_diversity, stop_signal, summary)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(), analysis.get("trigger_type"),
                 analysis.get("health_score"), analysis.get("progress_speed"),
                 analysis.get("error_recurrence"), analysis.get("fix_effectiveness"),
                 analysis.get("pattern_diversity"), analysis.get("stop_signal"),
                 analysis.get("summary")))
            return cur.lastrowid

    def get_last_l2_analysis(self) -> dict | None:
        """获取最近一次 L2 分析。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM l2_analysis ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def get_l2_analysis(self, limit: int = 10) -> list[dict]:
        """获取最近 N 次 L2 分析。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM l2_analysis ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── L2: 改进建议 ──────────────────────────────────────────

    def insert_l2_suggestion(self, suggestion: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO l2_suggestions
                   (id, analysis_id, category, priority, suggestion,
                    auto_applicable, status, created_at, target_param,
                    old_value, new_value, confidence, verify_result)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (suggestion["id"], suggestion.get("analysis_id"),
                 suggestion.get("category"), suggestion.get("priority", "medium"),
                 suggestion.get("suggestion"), suggestion.get("auto_applicable", 0),
                 suggestion.get("status", "pending"), datetime.now().isoformat(),
                 suggestion.get("target_param", ""), suggestion.get("old_value", ""),
                 suggestion.get("new_value", ""), suggestion.get("confidence", 0.5),
                 suggestion.get("verify_result", "")))

    def get_pending_suggestions(self) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM l2_suggestions WHERE status='pending' "
                "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_suggestion_status(self, sid: str, status: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE l2_suggestions SET status=?, applied_at=? WHERE id=?",
                (status, datetime.now().isoformat() if status == 'applied' else None, sid))

