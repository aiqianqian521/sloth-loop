"""模式库持久化抽象层 — 移植自 DSH 的 SessionPersistence 抽象模式。

定义 PatternStore 的抽象接口，SQLite 和 JSON 两种后端可切换。
测试用 JSON（无需 SQLite 文件），生产用 SQLite，未来可扩展远程后端。

移植自 DSH packages/session/ (SessionPersistence abstract class)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# 6 种失败模式 + 5 种成功模式（与 memory_store.py 保持一致）
FAILURE_MODES = [
    "EXTREME_CHASE", "ABSOLUTE_BLINDSPOT", "STOPPED_OUT_FIRST",
    "DIRECTION_BIAS", "RANGING_FAKEOUT", "INSUFFICIENT_EVIDENCE",
]
SUCCESS_MODES = [
    "TREND_FOLLOWING", "MEAN_REVERSION", "BREAKOUT_CONFIRMED",
    "RANGING_REVERSAL", "EVENT_DRIVEN",
]


class BasePatternStore(ABC):
    """模式库持久化抽象基类。

    子类只需实现 5 个 abstract 方法即可获得完整的模式库能力。
    业务逻辑（check_exclusion, make_rule 等）由子类自行实现，
    因为不同后端的实现差异较大。
    """

    # ── Abstract: backend-specific CRUD ──

    @abstractmethod
    def append_failure(self, patterns: list[dict]):
        """写入失败模式。"""
        ...

    @abstractmethod
    def append_success(self, patterns: list[dict]):
        """写入成功模式。"""
        ...

    @abstractmethod
    def find_failure(self, signal_pattern: str, market_condition: str,
                     failure_mode: str | None = None) -> dict | None:
        """三元组查找失败模式。"""
        ...

    @abstractmethod
    def find_success(self, signal_pattern: str, market_condition: str) -> dict | None:
        """二元组查找成功模式。"""
        ...

    @abstractmethod
    def load_failure_patterns(self) -> list[dict]:
        """加载全部失败模式。"""
        ...

    @abstractmethod
    def load_success_patterns(self) -> list[dict]:
        """加载全部成功模式。"""
        ...

    @abstractmethod
    def check_exclusion(self, signals: list[dict],
                        task_type: str | None = None) -> dict:
        """批量排除检查。返回 {passed, excluded, rule_hits}。"""
        ...

    @abstractmethod
    def get_active_exclusion_rules(self) -> list[dict]:
        """获取活跃排除规则。"""
        ...

    @abstractmethod
    def log_round(self, input_count: int, excluded_count: int,
                  passed_count: int, new_failures: int,
                  new_successes: int, error: str = ""):
        """记录一轮执行。"""
        ...

    @abstractmethod
    def bump_failure(self, pid: str, extra_trades: int = 1):
        """累加失败计数。"""
        ...

    @abstractmethod
    def update_failure_status(self, pid: str, status: str,
                               exclusion_rule: str | None = None):
        """更新失败模式状态。"""
        ...

    @abstractmethod
    def push_problem(self, problem: dict):
        """推入问题队列。"""
        ...

    @abstractmethod
    def pull_problems(self, status: str | list[str] = "queued",
                       min_count: int = 0,
                       group_by: str | None = None) -> list[dict]:
        """拉取问题队列。"""
        ...

    @abstractmethod
    def get_queue_stats(self) -> dict:
        """问题队列统计。"""
        ...

    @abstractmethod
    def next_id(self, kind: str, day: str | None = None) -> str:
        """分配不冲突的 ID。"""
        ...