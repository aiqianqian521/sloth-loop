"""JSON 文件模式库 — 轻量级 PatternStore 实现，用于测试。

移植自 DSH 的 JSONL session persistence 概念。
无需 SQLite，所有数据以 JSON 文件存储。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memory_store_abc import BasePatternStore, FAILURE_MODES


class JSONPatternStore(BasePatternStore):
    """JSON 文件后端 — 适合测试和轻量级场景。

    所有数据存储在单个 JSON 文件中。
    不支持 SQLite 的高级查询（JOIN、聚合），但覆盖核心的 CRUD + 排除检查。
    """

    def __init__(self, file_path: str | Path):
        self._path = Path(file_path)
        self._data: dict[str, list[dict]] = {
            "failures": [],
            "successes": [],
            "rounds": [],
            "problems": [],
        }
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    # ── Failure patterns ──

    def append_failure(self, patterns: list[dict]):
        for p in patterns:
            p["_seq"] = len(self._data["failures"]) + 1
            self._data["failures"].append(p)
        self._save()

    def find_failure(self, signal_pattern: str, market_condition: str,
                     failure_mode: str | None = None) -> dict | None:
        for f in self._data["failures"]:
            if (f.get("signal_pattern") == signal_pattern and
                f.get("market_condition") == market_condition):
                if failure_mode is None or f.get("failure_mode") == failure_mode:
                    return f
        return None

    def load_failure_patterns(self) -> list[dict]:
        return list(self._data["failures"])

    def bump_failure(self, pid: str, extra_trades: int = 1):
        for f in self._data["failures"]:
            if f.get("id") == pid:
                f["impact_trades"] = f.get("impact_trades", 0) + extra_trades
                f["last_seen"] = json.dumps(str(Path(self._path).stat().st_mtime))
                self._save()
                return

    def update_failure_status(self, pid: str, status: str,
                               exclusion_rule: str | None = None):
        for f in self._data["failures"]:
            if f.get("id") == pid:
                f["status"] = status
                if exclusion_rule is not None:
                    f["exclusion_rule"] = exclusion_rule
                self._save()
                return

    # ── Success patterns ──

    def append_success(self, patterns: list[dict]):
        for p in patterns:
            p["_seq"] = len(self._data["successes"]) + 1
            self._data["successes"].append(p)
        self._save()

    def find_success(self, signal_pattern: str, market_condition: str) -> dict | None:
        for s in self._data["successes"]:
            if (s.get("signal_pattern") == signal_pattern and
                s.get("market_condition") == market_condition):
                return s
        return None

    def load_success_patterns(self) -> list[dict]:
        return list(self._data["successes"])

    # ── Exclusion check ──

    def get_active_exclusion_rules(self) -> list[dict]:
        return [f for f in self._data["failures"]
                if f.get("status") in ("resolved", "monitoring")
                and f.get("exclusion_rule")]

    def check_exclusion(self, signals: list[dict],
                        task_type: str | None = None) -> dict:
        rules = self.get_active_exclusion_rules()
        passed, excluded, rule_hits = [], [], []
        for sig in signals:
            sig_sp = sig.get("signal_pattern", "")
            sig_mc = sig.get("market_condition", "")
            # simple string matching (same as SQLite version)
            is_excluded = False
            for rule in rules:
                er = rule.get("exclusion_rule", "")
                if not er:
                    continue
                # simple substring match on pattern
                if sig_sp and sig_sp in er:
                    excluded.append(sig)
                    rule_hits.append({
                        "signal_pattern": sig_sp,
                        "rule_id": rule.get("id", ""),
                        "reason": er,
                    })
                    is_excluded = True
                    break
            if not is_excluded:
                passed.append(sig)
        return {"passed": passed, "excluded": excluded, "rule_hits": rule_hits}

    # ── Rounds ──

    def log_round(self, input_count: int, excluded_count: int,
                  passed_count: int, new_failures: int,
                  new_successes: int, error: str = ""):
        import time
        self._data["rounds"].append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "input_count": input_count,
            "excluded_count": excluded_count,
            "passed_count": passed_count,
            "new_failures": new_failures,
            "new_successes": new_successes,
            "status": "error" if error else "success",
        })
        self._save()

    # ── Problems ──

    def push_problem(self, problem: dict):
        self._data["problems"].append(problem)
        self._save()

    def pull_problems(self, status: str | list[str] = "queued",
                       min_count: int = 0,
                       group_by: str | None = None) -> list[dict]:
        statuses = [status] if isinstance(status, str) else status
        return [p for p in self._data["problems"]
                if p.get("status") in statuses]

    def get_queue_stats(self) -> dict:
        problems = self._data["problems"]
        by_status = {}
        for p in problems:
            s = p.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        return {"total": len(problems), "by_status": by_status}

    def next_id(self, kind: str, day: str | None = None) -> str:
        from datetime import date
        day = day or date.today().isoformat()
        prefix = "F" if kind == "failure" else "S" if kind == "success" else "P"
        pool = (self._data["failures"] if kind == "failure"
                else self._data["successes"] if kind == "success"
                else self._data["problems"])
        return f"{prefix}-{day}-{len(pool) + 1:03d}"