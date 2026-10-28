"""Hook 协议标准化 — 移植自 DeepSeek Harness 的 hook 输出模型。

提供统一的 HookOutput 结构和合并逻辑，使 hooks_check.py 和
corrections/pre_check.py 的输出可叠加、可程序化消费。

移植自 DSH packages/hooks/hook-protocol/src/codec.ts + merge.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping, Protocol

Decision = Literal["block", "ask", "warn", "allow"]

# 决策严重度排序（用于合并）
# W2 deterministic merge order.  ``ask`` is intentionally stronger than a
# warning: the caller must pause for an explicit decision, but it is not a
# hard denial like ``block``.
_DECISION_ORDER: Mapping[Decision, int] = MappingProxyType({
    "block": 4, "ask": 3, "warn": 2, "allow": 1,
})


class GuardPort(Protocol):
    """Outbound seam for human-gated hook decisions.

    Implementations enqueue or publish an ``ask`` without prompting in the
    hook process.  The port is deliberately absent from checkpoint payloads:
    it represents a pending decision, not loop execution state.
    """

    def route(self, output: "HookOutput") -> "HookOutput":
        """Route a hook result without synchronously collecting input."""
        ...


@dataclass
class InMemoryGuardPort:
    """Small default adapter used by CLI/tests until durable approval exists."""

    pending: list["HookOutput"] = field(default_factory=list)

    def route(self, output: "HookOutput") -> "HookOutput":
        if output.requires_input():
            self.pending.append(output)
        return output


@dataclass
class HookOutput:
    """单条 hook 检查的标准化输出。

    对应 DSH 的 HookOutput 结构：decision + reason + additional_context。
    """
    decision: Decision
    reason: str
    rule_id: str = ""
    additional_context: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision not in _DECISION_ORDER:
            raise ValueError(f"unsupported hook decision: {self.decision!r}")

    def is_blocking(self) -> bool:
        return self.decision == "block"

    def is_warning(self) -> bool:
        return self.decision == "warn"

    def requires_input(self) -> bool:
        return self.decision == "ask"


def merge_hook_outputs(outputs: list[HookOutput]) -> HookOutput:
    """合并多条 hook 输出，取最严格决策。

    规则: block > ask > warn > allow。
    多条同级别 → 合并 reason 和 context。

    对应 DSH 的 mergeHookOutputs()。
    """
    if not outputs:
        return HookOutput(decision="allow", reason="无检查规则")

    # 找最严重级别
    max_level = max(_DECISION_ORDER[o.decision] for o in outputs)

    # 收集最严重级别的所有输出
    top = [o for o in outputs if _DECISION_ORDER[o.decision] == max_level]

    if len(top) == 1:
        return top[0]

    # 合并同级别输出
    reasons = [o.reason for o in top if o.reason]
    rule_ids = [o.rule_id for o in top if o.rule_id]
    merged_context = {}
    for o in top:
        merged_context.update(o.additional_context)

    return HookOutput(
        decision=top[0].decision,
        reason="; ".join(reasons) if reasons else top[0].reason,
        rule_id="+".join(rule_ids) if rule_ids else "",
        additional_context=merged_context,
    )


def make_allow(reason: str = "", rule_id: str = "") -> HookOutput:
    """快捷构造 allow 决策。"""
    return HookOutput(decision="allow", reason=reason, rule_id=rule_id)


def make_warn(reason: str, rule_id: str = "", **ctx) -> HookOutput:
    """快捷构造 warn 决策。"""
    return HookOutput(decision="warn", reason=reason, rule_id=rule_id,
                      additional_context=ctx)


def make_ask(reason: str, rule_id: str = "", **ctx) -> HookOutput:
    """Construct an explicit human-input gate."""
    return HookOutput(decision="ask", reason=reason, rule_id=rule_id,
                      additional_context=ctx)


def make_block(reason: str, rule_id: str = "", **ctx) -> HookOutput:
    """快捷构造 block 决策。"""
    return HookOutput(decision="block", reason=reason, rule_id=rule_id,
                      additional_context=ctx)
