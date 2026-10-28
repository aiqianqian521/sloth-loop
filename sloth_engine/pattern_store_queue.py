"""PatternStore 问题队列 mixin — H1-P1c godfile 拆分（行为保持）。

problem_queue CRUD（push/pull/update_status/transition/_get_signature_status/get_queue_stats
+ next_problem_id/_deserialize_problem 静态）原为 memory_store.PatternStore 方法，
移至本 mixin；PatternStore 继承后公共 API 不变。方法经 self._connect + self.* 运行时可用。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime


class PatternStoreQueue:
    """问题队列（P0 problem_queue 表）CRUD。由 PatternStore 继承。"""

    def push_problem(self, problem: dict):
        """写入一条问题到 problem_queue。

        L2: 按 error_signature 去重 UPSERT。
        - 无 sig: 走 INSERT OR IGNORE 直通路径（向后兼容旧调用方）
        - 有 sig: 同 sig 更新 recurrence_count，合并 l1_attempts，status queued→recurring
        """
        sig = problem.get("error_signature", "")
        now = datetime.now().isoformat()
        with self._connect() as conn:
            if sig:
                existing = conn.execute(
                    "SELECT id, recurrence_count, l1_attempts, status FROM problem_queue "
                    "WHERE error_signature = ? LIMIT 1", (sig,)
                ).fetchone()
                if existing:
                    existing_id, rc, old_attempts_str, old_status = existing
                    rc = (rc or 1) + 1
                    attempts = []
                    if old_attempts_str:
                        try:
                            attempts = json.loads(old_attempts_str)
                        except json.JSONDecodeError:
                            attempts = []
                    new_attempts = problem.get("l1_attempts")
                    if new_attempts:
                        if isinstance(new_attempts, str):
                            try:
                                new_attempts = json.loads(new_attempts)
                            except json.JSONDecodeError:
                                new_attempts = [new_attempts]
                        if isinstance(new_attempts, list):
                            attempts.extend(new_attempts)
                    new_status = "recurring" if old_status == "queued" else old_status
                    conn.execute(
                        """UPDATE problem_queue SET recurrence_count = ?, l1_attempts = ?,
                           status = ?, evidence = COALESCE(?, evidence),
                           context = COALESCE(?, context), created_at = COALESCE(?, created_at)
                           WHERE id = ?""",
                        (rc, json.dumps(attempts, ensure_ascii=False), new_status,
                         problem.get("evidence") or None,
                         json.dumps(problem.get("context", {}), ensure_ascii=False) if problem.get("context") else None,
                         problem.get("created_at") or now, existing_id))
                    return
            conn.execute(
                """INSERT OR IGNORE INTO problem_queue
                   (id, type, severity, source, round, context, evidence,
                    suggested_action, status, created_at,
                    error_signature, recurrence_count, l1_attempts,
                    task_step, expected_behavior, env_snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?)""",
                (problem["id"], problem["type"], problem["severity"],
                 problem.get("source", ""), problem.get("round", 0),
                 json.dumps(problem.get("context", {}), ensure_ascii=False),
                 problem.get("evidence", ""),
                 problem.get("suggested_action", ""),
                 problem.get("status", "queued"),
                 problem.get("created_at", now),
                 sig or None,
                 problem.get("recurrence_count", 1),
                 json.dumps(problem.get("l1_attempts", []), ensure_ascii=False) if problem.get("l1_attempts") else None,
                 problem.get("task_step", ""),
                 problem.get("expected_behavior", ""),
                 json.dumps(problem.get("env_snapshot", {}), ensure_ascii=False) if problem.get("env_snapshot") else None))

    def pull_problems(self, status: str | list[str] = "queued",
                      min_count: int = 0, group_by: str | None = None) -> list[dict]:
        """拉取指定状态的问题。status 支持单个字符串或列表。
        min_count: 最少累积数量才返回 (消费者阈值)。
        group_by: 按 type 分组统计数量。"""
        statuses = [status] if isinstance(status, str) else status
        placeholders = ",".join("?" * len(statuses))
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if group_by:
                rows = conn.execute(
                    f"""SELECT type, COUNT(*) as cnt FROM problem_queue
                       WHERE status IN ({placeholders})
                       GROUP BY type HAVING cnt >= ?""",
                    (*statuses, min_count)).fetchall()
                return [{"type": r["type"], "count": r["cnt"]} for r in rows]
            rows = conn.execute(
                f"SELECT * FROM problem_queue WHERE status IN ({placeholders})",
                statuses).fetchall()
            if min_count and len(rows) < min_count:
                return []
            return [self._deserialize_problem(dict(r)) for r in rows]

    def update_problem_status(self, problem_id: str, status: str,
                              resolved_at: str | None = None):
        """更新问题状态。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE problem_queue SET status = ?, resolved_at = ? WHERE id = ?",
                (status, resolved_at or datetime.now().isoformat(), problem_id))

    # ── L2: 错误状态机 ──────────────────────────────────────────

    def transition_problem_status(self, error_signature: str,
                                   new_status: str) -> bool:
        """按 error_signature 转换问题状态。

        状态机规则:
          recurring → l2_pending (手动触发，表示 L2 已关注)
          l2_pending → resolved (问题已修复) | escalated (需人工介入)

        返回 True 表示至少 1 条记录被转换。
        """
        allowed = {
            "recurring": ["l2_pending"],
            "l2_pending": ["resolved", "escalated"],
            "queued": ["resolved"],  # 直接关闭未重复出现的问题
        }
        if new_status not in allowed.get(self._get_signature_status(error_signature), []):
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE problem_queue SET status = ?, resolved_at = ? "
                "WHERE error_signature = ? AND status != ?",
                (new_status, datetime.now().isoformat(), error_signature, new_status))
            return cur.rowcount > 0

    def _get_signature_status(self, error_signature: str) -> str:
        """获取指定 error_signature 的当前状态（取最新一条）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM problem_queue WHERE error_signature = ? "
                "ORDER BY created_at DESC LIMIT 1", (error_signature,)
            ).fetchone()
        return row[0] if row else ""

    def get_queue_stats(self) -> dict:
        """获取队列统计。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) as n FROM problem_queue").fetchone()["n"]
            by_status = conn.execute(
                "SELECT status, COUNT(*) as n FROM problem_queue GROUP BY status"
            ).fetchall()
            by_type = conn.execute(
                "SELECT type, COUNT(*) as n FROM problem_queue GROUP BY type"
            ).fetchall()
            return {
                "total": total,
                "by_status": {r["status"]: r["n"] for r in by_status},
                "by_type": {r["type"]: r["n"] for r in by_type},
            }

    @staticmethod
    def next_problem_id() -> str:
        """生成问题 ID: P-YYYYMMDD-NNN。时间戳+递增，调用方负责去重。"""
        today = date.today().isoformat()
        return f"P-{today}-{int(datetime.now().timestamp() * 1000) % 100000:05d}"

    @staticmethod
    def _deserialize_problem(p: dict) -> dict:
        """将 SQLite row 反序列化：context/l1_attempts/env_snapshot JSON → dict/list。"""
        for field in ("context", "env_snapshot"):
            val = p.get(field, "{}")
            if isinstance(val, str):
                try:
                    p[field] = json.loads(val) if val else {}
                except json.JSONDecodeError:
                    p[field] = {} if field != "l1_attempts" else []
        attempts = p.get("l1_attempts", "[]")
        if isinstance(attempts, str):
            try:
                p["l1_attempts"] = json.loads(attempts) if attempts else []
            except json.JSONDecodeError:
                p["l1_attempts"] = []
        return p
