"""审查会话与预算数据模型.

定义 Guardian 审查系统所需的会话上下文、预算控制、审查决策等核心数据类。
不包含任何业务逻辑——纯数据容器。

关键设计:
- ReviewBudget:    令牌/请求预算控制，防止审查系统自身成为资源消耗漏洞
- ReviewContext:   单次审查的上下文快照（工具、参数、操作链、时间戳）
- ReviewDecision:  审查结果（allow/deny/escalate + 风险评分 + 预算剩余）
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

# ── 审查预算常量 ─────────────────────────────────────────────
GUARDIAN_MAX_ROOT_TOKENS = 900
GUARDIAN_MAX_TOOL_RESULT_TOKENS = 6000
GUARDIAN_MAX_REVIEW_REQUESTS = 20  # 单会话最大审查次数


@dataclass
class ReviewBudget:
    """审查预算追踪器。

    限制 Guardian 自身的资源消耗，防止无限审查循环耗尽 token 预算。

    Attributes:
        max_input_tokens:     最大输入令牌数
        max_tool_result_tokens: 最大工具结果令牌数
        consumed_input:       已消耗输入令牌
        consumed_requests:    已审查请求数
        max_requests:         单会话最大审查次数
        _token_est_f:         令牌估算函数（可选注入，用于 LLM 集成）
    """

    max_input_tokens: int = GUARDIAN_MAX_ROOT_TOKENS
    max_tool_result_tokens: int = GUARDIAN_MAX_TOOL_RESULT_TOKENS
    consumed_input: int = 0
    consumed_requests: int = 0
    max_requests: int = GUARDIAN_MAX_REVIEW_REQUESTS

    def can_review(self, estimated_tokens: int = 0) -> bool:
        """检查是否还有审查预算。

        Args:
            estimated_tokens: 本次审查预计消耗的令牌数（默认 0 表示不检查令牌预算）

        Returns:
            True 如果预算充足，False 如果已耗尽
        """
        if self.consumed_requests >= self.max_requests:
            return False
        if estimated_tokens > 0 and (
            self.consumed_input + estimated_tokens > self.max_input_tokens
        ):
            return False
        return True

    def consume(self, tokens: int = 0) -> None:
        """记录一次审查消耗。

        Args:
            tokens: 本次审查实际消耗令牌数
        """
        self.consumed_requests += 1
        self.consumed_input += tokens

    @property
    def remaining_requests(self) -> int:
        """剩余可用审查次数。"""
        return max(0, self.max_requests - self.consumed_requests)

    @property
    def remaining_input_tokens(self) -> int:
        """剩余输入令牌预算。"""
        return max(0, self.max_input_tokens - self.consumed_input)


@dataclass
class ReviewContext:
    """单次审查的上下文快照。

    Attributes:
        session_id:       会话 ID（关联 ExecGate 的 session_id）
        tool_name:        工具名称
        tool_args:        工具调用参数
        parent_operation: 父操作名称（用于操作链追踪）
        operation_chain:  操作链历史（按时间排序的工具调用序列）
        timestamp:        审查触发时间
        request_id:       请求唯一标识
    """

    session_id: str
    tool_name: str
    tool_args: dict
    parent_operation: Optional[str] = None
    operation_chain: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def add_to_chain(self, operation: str) -> None:
        """向操作链追加一条记录。

        Args:
            operation: 操作描述（如 "shell_command:ls"）
        """
        self.operation_chain.append(operation)

    def recent_chain(self, n: int = 5) -> list[str]:
        """返回最近 n 条操作链记录。

        Args:
            n: 返回条数

        Returns:
            最近 n 条操作记录
        """
        return self.operation_chain[-n:] if self.operation_chain else []


@dataclass
class ReviewDecision:
    """审查决策结果。

    Attributes:
        decision:         决策结果: "allow" | "deny" | "escalate"
        reason:           决策理由（人类可读）
        risk_score:       风险评分 0.0（安全）~ 1.0（高危）
        budget_remaining: 剩余审查预算（次数）
        metadata:         附加元数据（可选，用于审计追踪）
    """

    decision: str       # "allow" | "deny" | "escalate"
    reason: str
    risk_score: float   # 0.0 ~ 1.0
    budget_remaining: int
    metadata: dict | None = field(default=None)

    def __post_init__(self) -> None:
        """构造后校验。"""
        if self.decision not in ("allow", "deny", "escalate"):
            raise ValueError(
                f"decision must be 'allow', 'deny', or 'escalate', got {self.decision!r}"
            )
        if not 0.0 <= self.risk_score <= 1.0:
            raise ValueError(
                f"risk_score must be in [0.0, 1.0], got {self.risk_score}"
            )

    @property
    def is_allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def is_denied(self) -> bool:
        return self.decision == "deny"

    @property
    def is_escalated(self) -> bool:
        return self.decision == "escalate"
