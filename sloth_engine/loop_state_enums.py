"""P0-1: 状态转换枚举 — 对标 Claude Code 10种Terminal + 7种Continue。

设计原则:
- 穷举替代二元 stop/continue
- 每种终止原因提供结构化上下文（reason + detail）
- 向后兼容: 旧的 bool continue_flag 仍可用 TerminalReason.completed == "normal end"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TerminalReason(str, Enum):
    """10种终端状态 — 对标 Claude Code query() Terminal 联合类型。"""

    COMPLETED = "completed"              # 正常完成（无工具调用、预算耗尽、或API错误）
    MAX_TURNS = "max_turns"              # 达到最大轮次上限
    MAX_TOKEN_BUDGET = "max_token_budget" # Token 预算耗尽
    USER_ABORT_STREAMING = "user_abort_streaming"  # 用户中止模型流式响应
    USER_ABORT_TOOLS = "user_abort_tools"          # 用户中止工具执行
    HOOK_PREVENTED = "hook_prevented"    # Stop hook 显式阻止继续
    HOOK_STOPPED = "hook_stopped"        # PreToolUse hook 停止执行
    CONTEXT_EXHAUSTED = "context_exhausted"  # 上下文耗尽（所有恢复路径失败）
    MODEL_ERROR = "model_error"          # 不可恢复的模型/API异常
    SIGNAL_EXHAUSTED = "signal_exhausted" # 信号源耗尽

    @property
    def is_error(self) -> bool:
        """是否属于错误终止。"""
        return self in (
            TerminalReason.CONTEXT_EXHAUSTED,
            TerminalReason.MODEL_ERROR,
        )

    @property
    def is_user_initiated(self) -> bool:
        """是否是用户主动终止。"""
        return self in (
            TerminalReason.USER_ABORT_STREAMING,
            TerminalReason.USER_ABORT_TOOLS,
        )


class ContinueReason(str, Enum):
    """7种继续状态 — 对标 Claude Code query() Continue 联合类型。"""

    NEXT_TURN = "next_turn"                    # 正常工具调用继续
    TOKEN_BUDGET_CONTINUATION = "token_budget_continuation"  # 预算未耗尽，nudge继续
    STOP_HOOK_BLOCKING = "stop_hook_blocking"  # Stop hook 返回阻塞错误，必须重试
    COLLAPSE_DRAIN_RETRY = "collapse_drain_retry"      # Context collapse drain 成功
    REACTIVE_COMPACT_RETRY = "reactive_compact_retry"  # Reactive compact 成功
    MAX_OUTPUT_ESCALATE = "max_output_escalate"  # 8K→64K 升级
    MAX_OUTPUT_RECOVERY = "max_output_recovery"  # 64K仍超限，多轮恢复


@dataclass
class LoopTermination:
    """循环终止结果 — 替代旧的 dict/None 返回值。"""

    reason: TerminalReason
    detail: str = ""
    round: int = 0
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "status": "terminated",
            "reason": self.reason.value,
            "detail": self.detail,
            "final_round": self.round,
            "elapsed_s": round(self.elapsed_seconds, 3),
        }


@dataclass
class LoopContinuation:
    """循环继续信号 — 替代旧的 bool continue_flag。"""

    reason: ContinueReason
    detail: str = ""
    round: int = 0


@dataclass
class RecoveryState:
    """恢复追踪 — 防止无限恢复循环（对标CC 5层死亡螺旋防护）。

    每个恢复路径独立追踪尝试次数，互不干扰。
    一次性标志（has_attempted_*）确保每条路径只尝试一次。
    """

    has_attempted_collapse: bool = False
    has_attempted_reactive_compact: bool = False
    max_output_escalated: bool = False
    max_output_recovery_count: int = 0
    auto_compact_failures: int = 0
    stop_hook_retry_count: int = 0

    MAX_OUTPUT_RECOVERY_LIMIT: int = field(default=3, init=False)
    AUTO_COMPACT_CIRCUIT_BREAKER: int = field(default=3, init=False)

    def reset_for_new_turn(self):
        """每轮开始重置一次性标志。"""
        self.has_attempted_collapse = False
        self.has_attempted_reactive_compact = False

    def collapse_allowed(self) -> bool:
        return not self.has_attempted_collapse

    def reactive_compact_allowed(self) -> bool:
        return not self.has_attempted_reactive_compact

    def max_output_escalate_allowed(self) -> bool:
        if self.max_output_escalated:
            return False
        self.max_output_escalated = True
        return True

    def max_output_recovery_allowed(self) -> bool:
        if self.max_output_recovery_count >= self.MAX_OUTPUT_RECOVERY_LIMIT:
            return False
        self.max_output_recovery_count += 1
        return True

    def auto_compact_circuit_open(self) -> bool:
        """熔断器：连续失败>=3次则开断。"""
        return self.auto_compact_failures >= self.AUTO_COMPACT_CIRCUIT_BREAKER

    def record_auto_compact_failure(self):
        self.auto_compact_failures += 1

    def record_auto_compact_success(self):
        self.auto_compact_failures = 0
