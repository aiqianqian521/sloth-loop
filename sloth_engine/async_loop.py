"""
Async Loop Generator — P2-N4: Async Generator 模式改造
========================================================
对标 Claude Code query() generator：
- query() 是 async generator，每轮产生 (State, ToolCalls, Terminal | None)
- 支持 backpressure（调用方通过消费速度控制生产速度）
- 支持提前终止（调用方检测到 Terminal 后停止消费）

sloth-loop 对标实现（同步 generator）：
- iter_loop(): generator，每次 yield LoopYield
- LoopYield: 本轮完整上下文（LoopState + signals + decision + round_ctx）
- 支持: backpressure / 预提前终止 / 逐轮消费
- 协程兼容: yield 模式直接兼容 asyncio.run() 集成

设计原则:
1. 不改动现有 run() 行为（向后兼容）
2. iter_loop() 是 run() 的超集，run() 内部调用 iter_loop() 并自动消费
3. 每个 yield point 都是调用方可以插入逻辑的挂载点
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from immutable_state import LoopState, StateReducer

_log = logging.getLogger("sloth_engine.async-loop")

# ---------------------------------------------------------------------------
# 1. LoopYield — 每轮的产物
# ---------------------------------------------------------------------------

@dataclass
class LoopYield:
    """每轮 generator 的 yield 产物。

    对标 Claude Code: query() 的 yield (State, ToolCalls, Terminal | None)。
    """
    # 本轮状态快照
    state: LoopState

    # 本轮计算结果
    signals: list[dict] = field(default_factory=list)
    decision: str = ""           # "apply" | "reject" | "skip"
    act_result: dict = field(default_factory=dict)
    verify_result: dict = field(default_factory=dict)
    learned: dict = field(default_factory=dict)

    # 停止条件
    is_terminal: bool = False
    stop_reason: str = ""

    # 元数据
    round_num: int = 0
    elapsed_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    # 额外信息
    progress: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @property
    def should_stop(self) -> bool:
        """调用方应该停止消费吗？"""
        return self.is_terminal

    @property
    def had_error(self) -> bool:
        """本轮是否有错误？"""
        return self.state.execution_failed

    @property
    def summary(self) -> str:
        """人类可读的本轮摘要。"""
        parts = [f"R{self.round_num}"]
        if self.decision:
            parts.append(f"dec={self.decision}")
        if self.state.new_failures:
            parts.append(f"f={self.state.new_failures}")
        if self.state.new_successes:
            parts.append(f"s={self.state.new_successes}")
        if self.is_terminal:
            parts.append(f"TERM:{self.stop_reason[:30]}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# 2. LoopControl — 调用方控制信号（backpressure 接口）
# ---------------------------------------------------------------------------

@dataclass
class LoopControl:
    """调用方通过此结构向 generator 发送控制信号。

    对标 Claude Code: backpressure 机制 —— 调用方可以暂停/跳过/提前终止。
    generator 每轮开始时读取此结构。
    """
    pause: bool = False          # 暂停生产（generator 内部轮询等待）
    skip_next: bool = False      # 跳过下一轮
    max_rounds_override: Optional[int] = None  # 动态覆盖最大轮数
    inject_signals: Optional[list[dict]] = None  # 注入外部信号
    abort: bool = False          # 立即终止
    abort_reason: str = ""

    def reset_flags(self):
        """重置一次性标志（每轮消费后调用）。"""
        self.skip_next = False
        self.inject_signals = None


# ---------------------------------------------------------------------------
# 3. LoopGeneratorProtocol — generator 协议抽象
# ---------------------------------------------------------------------------

class LoopGeneratorProtocol:
    """Loop generator 协议 —— 可被多种引擎实现。

    对标 Claude Code: query() 是抽象接口，多种 ToolExecutor 实现。
    """

    def iter_loop(
        self,
        config: dict,
        *,
        seed_path: str | None = None,
        control: Optional[LoopControl] = None,
    ) -> Iterator[LoopYield]:
        """主 generator 接口。

        Args:
            config: 运行配置（max_rounds, error_stop 等）
            seed_path: 信号种子路径
            control: 调用方控制信号（可选，不传则自动运行）

        Yields:
            LoopYield: 每轮产物
        """
        raise NotImplementedError

    def run(
        self,
        config: dict,
        *,
        seed_path: str | None = None,
    ) -> LoopYield:
        """同步消费所有轮次（兼容旧 run() 接口）。

        Returns: 最后一轮的 LoopYield（含终止状态）。
        """
        last_yield = None
        for y in self.iter_loop(config, seed_path=seed_path):
            last_yield = y
            if y.is_terminal:
                break
        return last_yield or LoopYield(
            state=LoopState(), is_terminal=True, stop_reason="no rounds executed"
        )


# ---------------------------------------------------------------------------
# 4. 简版 LoopGenerator（独立于 Orchestrator，纯逻辑验证）
# ---------------------------------------------------------------------------

class SimpleLoopGenerator(LoopGeneratorProtocol):
    """简版 Loop generator —— 纯逻辑实现，不依赖 Orchestrator。

    用于单元测试 + 作为参照实现。
    每轮模拟：生成信号 → 决策 → 计算 → yield。
    """

    def __init__(self):
        self._history: list[LoopYield] = []

    def iter_loop(
        self,
        config: dict,
        *,
        seed_path: str | None = None,
        control: Optional[LoopControl] = None,
    ) -> Iterator[LoopYield]:
        """简版 generator：每轮递增 round_num，yield LoopYield。"""
        ctrl = control or LoopControl()
        max_rounds = ctrl.max_rounds_override or config.get("max_rounds", 10)
        no_progress_stop = config.get("no_progress_stop", 3)
        error_stop = config.get("error_stop", 5)

        state = StateReducer.init(config, run_id="simple-loop", started_at=time.time())
        last_progress_round = 0
        consecutive_errors = 0

        for r in range(1, max_rounds + 1):
            # 检查 backpressure
            if ctrl.abort:
                y = LoopYield(
                    state=state,
                    is_terminal=True,
                    stop_reason=f"aborted: {ctrl.abort_reason}",
                    round_num=r,
                )
                self._history.append(y)
                yield y
                return

            # 暂停循环
            while ctrl.pause:
                time.sleep(0.1)

            # 跳过
            if ctrl.skip_next:
                ctrl.reset_flags()
                continue

            # 模拟本轮计算
            signals = ctrl.inject_signals or [{"id": f"sig-{r}"}]
            ctrl.reset_flags()

            signals_input = len(signals)
            # 模拟: 第1轮全部通过，第2轮1个排除，后续逐步增加排除
            signals_excluded = max(0, r - 1)  # r=1: 0排除, r=2: 1排除, r=3: 2排除
            decision = "apply" if signals_input > signals_excluded else "reject"
            progressed = decision == "apply"
            new_failures = 0 if progressed else 1
            new_successes = 1 if progressed else 0

            if not progressed:
                consecutive_errors += 1
            else:
                consecutive_errors = 0
                last_progress_round = r

            # 折叠状态
            state = StateReducer.reduce(
                state,
                round_num=r,
                cursor=r,
                signals_input=signals_input,
                signals_excluded=signals_excluded,
                decision=decision,
                progressed=progressed,
                new_failures=new_failures,
                new_successes=new_successes,
                last_progress_round=last_progress_round,
                consecutive_errors=consecutive_errors,
                execution_failed=new_failures > 0,
                backtest_status="error" if new_failures > 0 else "completed",
            )

            # 停止条件检查
            is_terminal = False
            stop_reason = ""

            if r >= max_rounds:
                is_terminal = True
                stop_reason = "max_rounds reached"
            elif consecutive_errors >= error_stop:
                is_terminal = True
                stop_reason = f"error_stop: {consecutive_errors} consecutive errors"
            elif r - last_progress_round >= no_progress_stop:
                is_terminal = True
                stop_reason = f"no_progress_stop: {no_progress_stop} rounds without progress"

            # yield
            y = LoopYield(
                state=state,
                signals=signals,
                decision=decision,
                is_terminal=is_terminal,
                stop_reason=stop_reason,
                round_num=r,
                elapsed_ms=0.0,
                progress={
                    "consecutive_errors": consecutive_errors,
                    "last_progress_round": last_progress_round,
                },
            )
            self._history.append(y)
            yield y

            if is_terminal:
                return

    @property
    def history(self) -> list[LoopYield]:
        return self._history


# ---------------------------------------------------------------------------
# 5. 工具函数
# ---------------------------------------------------------------------------

def collect_all(generator: Iterator[LoopYield]) -> list[LoopYield]:
    """消费整个 generator 并返回所有 yields。"""
    results = []
    for y in generator:
        results.append(y)
        if y.is_terminal:
            break
    return results


def collect_until_terminal(generator: Iterator[LoopYield]) -> LoopYield:
    """消费 generator 直到终止，返回最后一个 yield。"""
    last = None
    for y in generator:
        last = y
        if y.is_terminal:
            return y
    return last or LoopYield(
        state=LoopState(), is_terminal=True, stop_reason="generator exhausted without terminal"
    )


def filter_yields(
    generator: Iterator[LoopYield],
    predicate: callable = lambda y: y.had_error,
) -> list[LoopYield]:
    """过滤 generator 输出（用于审计/调试）。"""
    return [y for y in generator if predicate(y)]


def map_yields(
    generator: Iterator[LoopYield],
    transform: callable,
) -> list[Any]:
    """映射 generator 输出。"""
    return [transform(y) for y in generator]


def iter_with_control(
    generator: Iterator[LoopYield],
    control: LoopControl,
) -> Iterator[LoopYield]:
    """包装 generator 添加外部控制能力。

    这是一个装饰器模式：在 generator 和调用方之间插入控制层。
    调用方修改 control 对象，generator 每轮读取。
    """
    for y in generator:
        if control.abort:
            break
        yield y
