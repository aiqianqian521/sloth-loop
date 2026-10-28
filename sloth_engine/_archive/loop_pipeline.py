"""P1-2: Backpressure + P1-4: Circuit Breaker + P2-1: 三段式状态分离。

三个模块合并为一个文件，减少文件碎片:
1. BackpressureQueue: 消费者驱动拉取 + max_pending 上限
2. CircuitBreaker: 熔断器抽象基类 (对标CC 5个熔断器)
3. LoopConfig/LoopState/LoopDeps: 三段式状态分离 (对标CC QueryConfig+State+QueryDeps)
"""

# ARCHIVED cycle-11 (N-1, 2026-10-22): superseded duplicates of live modules --
# BackpressureQueue -> backpressure.py (DeferOperation), CircuitBreaker ->
# circuit_breaker.py, LoopConfig/State/Deps -> run_state.py + round_context.py.
# Kept read-only as evidence; no caller existed at archive time (see
# scripts/check_orphan_mechanisms.py, which found it orphaned).
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Iterator, Optional, TypeVar

_log = logging.getLogger("sloth_engine.pipeline")

# ═══════════════════════════════════════════════════════════════
# P1-2: Backpressure Queue — 对标 CC async generator backpressure
# ═══════════════════════════════════════════════════════════════

T = TypeVar("T")

@dataclass
class BackpressureQueue(Generic[T]):
    """消费者驱动的有界队列。

    对标 CC async generator backpressure:
    - 消费者 .next() 驱动生产
    - max_pending 上限防止生产过快
    - 队列满时生产者等待 (简化: sleep则丢弃)

    Args:
        max_pending: 最大待处理项数
        on_overflow: "drop_oldest" | "drop_newest" | "block"
    """

    max_pending: int = 100
    on_overflow: str = "drop_oldest"
    _queue: deque = field(default_factory=deque)
    _produced: int = 0
    _consumed: int = 0

    def push(self, item: T) -> bool:
        """生产者推送。返回 True 表示入队成功。"""
        if len(self._queue) >= self.max_pending:
            if self.on_overflow == "drop_newest":
                _log.warning("[backpressure] queue full (%d), dropping newest", self.max_pending)
                return False
            elif self.on_overflow == "drop_oldest":
                self._queue.popleft()
                _log.warning("[backpressure] queue full (%d), dropped oldest", self.max_pending)
            # "block" 模式简化: 直接入队（调用方控制速率）
        self._queue.append(item)
        self._produced += 1
        return True

    def pull(self) -> Optional[T]:
        """消费者拉取。None 表示队列空。"""
        if not self._queue:
            return None
        self._consumed += 1
        return self._queue.popleft()

    def pull_all(self) -> list[T]:
        """消费者批量拉取。"""
        items = list(self._queue)
        self._consumed += len(items)
        self._queue.clear()
        return items

    def __iter__(self) -> Iterator[T]:
        """生成器接口 — 消费者用 `for item in queue:` 持续拉取。"""
        while True:
            item = self.pull()
            if item is None:
                return
            yield item

    @property
    def pending(self) -> int:
        return len(self._queue)

    @property
    def pressure(self) -> float:
        """队列压力 0.0~1.0。"""
        if self.max_pending <= 0:
            return 0.0
        return min(1.0, len(self._queue) / self.max_pending)

    def stats(self) -> dict:
        return {
            "produced": self._produced,
            "consumed": self._consumed,
            "pending": self.pending,
            "pressure": round(self.pressure, 3),
        }


# ═══════════════════════════════════════════════════════════════
# P1-4: Circuit Breaker — 对标 CC 5个熔断器
# ═══════════════════════════════════════════════════════════════

@dataclass
class CircuitBreaker:
    """熔断器抽象基类。

    对标 CC 各个恢复路径的熔断器:
    - auto-compact: 3次连续失败 → 永久断开
    - reactive-compact: 一次性标志
    - stop-hook-blocking: 重试计数
    - token-budget-continuation: 衰减检测

    状态机: CLOSED → (failures >= threshold) → OPEN → (optional reset timeout) → HALF_OPEN
    """

    name: str
    max_failures: int = 3
    reset_timeout_seconds: float = 0.0  # 0 = never auto-reset

    _failures: int = field(default=0, init=False)
    _successes: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _state: str = field(default="CLOSED", init=False)  # CLOSED | OPEN | HALF_OPEN

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_open(self) -> bool:
        """熔断器是否断开。"""
        if self._state == "CLOSED":
            return False
        if self._state == "OPEN":
            if self.reset_timeout_seconds > 0:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.reset_timeout_seconds:
                    self._state = "HALF_OPEN"
                    _log.info("[circuit-breaker] %s: OPEN → HALF_OPEN (timeout %.1fs)",
                              self.name, elapsed)
                    return False
            return True
        # HALF_OPEN
        return False

    def record_failure(self):
        """记录失败。"""
        self._failures += 1
        self._last_failure_time = time.time()
        if self._state != "OPEN" and self._failures >= self.max_failures:
            self._state = "OPEN"
            _log.warning("[circuit-breaker] %s: CLOSED → OPEN (%d/%d failures)",
                         self.name, self._failures, self.max_failures)

    def record_success(self):
        """记录成功。"""
        self._successes += 1
        if self._state == "HALF_OPEN":
            self._state = "CLOSED"
            self._failures = 0
            _log.info("[circuit-breaker] %s: HALF_OPEN → CLOSED", self.name)
        # CLOSED 态重置计数器
        if self._state == "CLOSED":
            self._failures = 0

    def reset(self):
        """手动重置。"""
        self._failures = 0
        self._state = "CLOSED"
        _log.info("[circuit-breaker] %s: manually reset → CLOSED", self.name)

    def stats(self) -> dict:
        return {
            "name": self.name,
            "state": self._state,
            "failures": self._failures,
            "successes": self._successes,
            "max_failures": self.max_failures,
        }


# ═══════════════════════════════════════════════════════════════
# P2-1: 三段式状态分离 — 对标 CC QueryConfig + State + QueryDeps
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LoopConfig:
    """不可变配置 — 对标 CC QueryConfig。

    循环入口时快照一次，循环内部永不修改。
    包含：特性开关、模型配置、上下文窗口、预算上限等。
    """

    task_name: str = "loop"
    max_rounds: int = 1000
    max_token_budget: int = 1_000_000
    effective_context_window: int = 128_000
    model_max_output: int = 16_000
    error_stop: bool = True
    feature_auto_compact: bool = True
    feature_concurrent_tools: bool = False
    feature_backpressure: bool = True

    @property
    def auto_compact_threshold(self) -> int:
        """对标 CC: effectiveWindow - AUTOCOMPACT_BUFFER_TOKENS(13000)。"""
        return max(0, self.effective_context_window - 13_000)

    @property
    def blocking_threshold(self) -> int:
        """对标 CC: effectiveWindow - MANUAL_COMPACT_BUFFER_TOKENS(3000)。"""
        return max(0, self.effective_context_window - 3_000)


@dataclass
class LoopState:
    """可变状态 — 对标 CC State (mutable during a turn)。

    包含：消息历史、工具结果、上下文追踪、回合计数器。
    循环内部修改，每次 turn 开始时从 LoopConfig 推导初始值。
    """

    round_num: int = 0
    messages: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    estimated_tokens: int = 0
    started_at: float = 0.0
    last_error: Optional[dict] = None

    def snapshot(self) -> dict:
        return {
            "round": self.round_num,
            "messages_count": len(self.messages),
            "tool_results_count": len(self.tool_results),
            "estimated_tokens": self.estimated_tokens,
            "elapsed_s": time.time() - self.started_at if self.started_at else 0,
        }


@dataclass
class LoopDeps:
    """可注入依赖 — 对标 CC QueryDeps (4个依赖，不是40个)。

    保持最小化: 只有模型调用器、压缩器、UUID生成器、时钟。
    对标 CC: 4 deps not 40 — 可测试性的关键。
    """

    model_caller: Optional[Callable] = None    # (messages, tools) -> response
    compactor: Optional[Callable] = None       # (messages) -> (summary, freed_tokens)
    uuid_generator: Callable = field(default=lambda: __import__("uuid").uuid4().hex[:8])
    clock: Callable = field(default=time.time)

    @classmethod
    def minimal(cls) -> "LoopDeps":
        """创建最小依赖（用于测试）。"""
        return cls()
