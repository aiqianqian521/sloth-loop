"""cycle-8 A4-cand-B: 上下文域工具策略门（context-scoped tool policy gate, AGE-17）.

Provenance / 真值源（A2，file:line 已核验）:
  qwen-code packages/core/src/agents/runtime/subagent-plan-tool-policy.ts
    READ_ONLY_INSPECTION_TOOLS .................... :19-27
    PLAN_REQUIRED_TEAMMATE_PRE_APPROVAL_TOOLS ..... :29-34
    PRE_APPROVAL_TASK_CLAIM_KEYS .................. :35-41
    isSubagentLikeExecutionContext() .............. :43-45
    isPlanLifecycleToolUnavailableInSubagent() .... :57-66
    isPlanRequiredTeammatePreApprovalAllowedTool()  :94-105
    isPreApprovalClaimOnlyTaskUpdate() ............ :107-130
    buildSubagentPlanToolBlockedResult() .......... :139-153

移植语义（在 loop 契约允许处 1:1）:
  1. 工具可见性不是「全局注册表一刀切」，而是按**执行上下文**（子 agent / 计划待批准队友）收窄。
  2. 计划待批准期只放行只读检视白名单 + exit_plan_mode / task_list；task_update 走参数级
     「仅认领」放行；其余一律阻断。
  3. 阻断是**结果级**的：策略门骑在既有单调 guard 缝（ToolRegistry.add_guard）上，其 blocked
     载荷是正常的 dispatch 结果（不是抛异常），因此模型可据此自行改道。

可加性 / 可选性（契约不变）: 无上下文（provider 返回 None）时策略门是 no-op，
既有 dispatch 行为逐字节不变。

loop 映射说明:
  - loop 的 dispatch 把调用包成 params = {"name","args","kwargs"}；_extract_named_params()
    还原工具自身的具名参数（对应 TS 的 params 对象），兼容 kwargs 与「首个位置参数为 dict」两种形状。
  - AgentContext.agent_id 扮演 TS 队友 agentName；agent_id 非空视为「子 agent 执行域」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# ── 真值常量（qwen-code subagent-plan-tool-policy.ts:19-41） ────────────────

ENTER_PLAN_MODE = "enter_plan_mode"
EXIT_PLAN_MODE = "exit_plan_mode"
TASK_LIST = "task_list"
TASK_UPDATE = "task_update"

#: ts:19-27 —— 只读检视白名单
READ_ONLY_INSPECTION_TOOLS: frozenset[str] = frozenset({
    "read_file", "grep", "glob", "ls", "lsp", "tool_search", "read_mcp_resource",
})

#: ts:29-34 —— 计划待批准队友可用的工具集
PLAN_REQUIRED_PRE_APPROVAL_TOOLS: frozenset[str] = frozenset({
    EXIT_PLAN_MODE, TASK_LIST, *READ_ONLY_INSPECTION_TOOLS,
})

#: ts:35-41 —— 计划待批准的 task_update「认领」只允许这些键
PRE_APPROVAL_TASK_CLAIM_KEYS: frozenset[str] = frozenset({
    "taskId", "status", "owner", "addBlocks", "addBlockedBy",
})

#: 计划态权限标签（对齐 permission_levels.PermissionLevel.PLAN_ONLY.label）
PLAN_PERMISSION_MODE = "plan"

#: 阻断理由前缀，便于日志 / 结果里 grep 出「上下文域策略门」的拒绝
POLICY_REASON_PREFIX = "context_tool_policy: "


def _extract_named_params(params: Any) -> dict:
    """还原工具自身的具名参数（对应 TS 的 params 对象）。

    loop 的 guard 收到的是包装形态 {"name", "args", "kwargs"}；真值源推理的是工具自身的
    params，故此处兼容两种形状：
      - 包装形态（含 "args"/"kwargs" 键）：合并 kwargs，再并入首个映射类位置参数；
      - 裸形态（本身就是具名参数）：原样返回。
    不可识别形状退化为 {}（放行给其余上下文检查）。
    """
    if not isinstance(params, dict):
        return {}
    if "args" in params or "kwargs" in params:
        named: dict = {}
        args = params.get("args")
        if isinstance(args, (tuple, list)) and args and isinstance(args[0], dict):
            named.update(args[0])
        kwargs = params.get("kwargs")
        if isinstance(kwargs, dict):
            named.update(kwargs)
        return named
    return dict(params)


def _is_absent_or_empty_array(value: Any) -> bool:
    """ts:132-134 —— 缺省或空数组。"""
    return value is None or (isinstance(value, (list, tuple)) and len(value) == 0)


def is_pre_approval_claim_only_task_update(params: Any, agent_name: str = "") -> bool:
    """ts:107-130 —— 仅当 task_update 是「纯认领」时返回 True。"""
    named = _extract_named_params(params)
    if not named:
        return False
    for key in named:
        if key not in PRE_APPROVAL_TASK_CLAIM_KEYS:
            return False
    owner = named.get("owner")
    return (
        isinstance(named.get("taskId"), str)
        and named.get("status") == "in_progress"
        and (owner is None or owner == agent_name)
        and _is_absent_or_empty_array(named.get("addBlocks"))
        and _is_absent_or_empty_array(named.get("addBlockedBy"))
    )


def is_plan_required_pre_approval_allowed_tool(
    tool_name: str, params: Any, agent_name: str = ""
) -> bool:
    """ts:94-105 —— 计划待批准期的放行判定。"""
    if tool_name in PLAN_REQUIRED_PRE_APPROVAL_TOOLS:
        return True
    if tool_name != TASK_UPDATE:
        return False
    return is_pre_approval_claim_only_task_update(params, agent_name)


def is_plan_lifecycle_tool_unavailable(
    tool_name: str, in_subagent: bool, plan_required_teammate: bool
) -> bool:
    """ts:57-66 —— 子 agent 里计划生命周期工具的可用性。

    - enter_plan_mode：任何子 agent 域都不可用（计划模式归调用方所有）；
    - exit_plan_mode：仅「计划待批准队友」可用，否则不可用。
    """
    if not in_subagent:
        return False
    if tool_name == ENTER_PLAN_MODE:
        return True
    if tool_name == EXIT_PLAN_MODE:
        return not plan_required_teammate
    return False


# ── 上下文域 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolPolicyContext:
    """执行上下文域 —— 决定工具面收窄。

    默认全 False/空 => 不收窄（等价于「无上下文」）。
    """

    in_subagent: bool = False
    plan_required_teammate: bool = False
    awaiting_plan_approval: bool = False
    agent_name: str = ""
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    permission_mode: str = ""

    @classmethod
    def from_agent_context(cls, ctx: Any) -> "ToolPolicyContext":
        """从 sub_agent.AgentContext 构造（鸭子类型，避免硬 import）。

        映射:
          in_subagent            <- bool(agent_id)（有 agent_id 即子 agent 执行域）
          plan_required_teammate <- ctx.plan_required_teammate
          awaiting_plan_approval <- plan_required_teammate and permission_mode == "plan"
          agent_name             <- teammate_name or agent_id
          allowed/disallowed     <- ctx.allowed_tools / ctx.disallowed_tools
          permission_mode        <- ctx.permission_mode
        """
        agent_id = getattr(ctx, "agent_id", "") or ""
        plan_required = bool(getattr(ctx, "plan_required_teammate", False))
        mode = getattr(ctx, "permission_mode", "") or ""
        return cls(
            in_subagent=bool(agent_id),
            plan_required_teammate=plan_required,
            awaiting_plan_approval=(plan_required and mode == PLAN_PERMISSION_MODE),
            agent_name=(getattr(ctx, "teammate_name", "") or agent_id),
            allowed_tools=tuple(getattr(ctx, "allowed_tools", None) or ()),
            disallowed_tools=tuple(getattr(ctx, "disallowed_tools", None) or ()),
            permission_mode=mode,
        )


def evaluate_tool_policy(
    ctx: "ToolPolicyContext | None", tool_name: str, params: Any
) -> str | None:
    """上下文域策略门主判定：None=放行，str=拒绝理由（结果级阻断）。

    判定顺序（先显式名单 / 计划态，再 AGE-17 计划待批准域）:
      1. disallowed_tools 命中 -> 拒；
      2. allowed_tools 非空且不在其中 -> 拒；
      3. permission_mode == "plan" 且非只读检视工具 -> 拒；
      4. 计划生命周期工具在子 agent 域不可用 -> 拒；
      5. 计划待批准域 -> AGE-17 白名单/参数级放行，否则拒。
    """
    if ctx is None:
        return None

    if tool_name in ctx.disallowed_tools:
        return POLICY_REASON_PREFIX + (
            f"{tool_name} is disallowed in this execution context"
        )

    if ctx.allowed_tools and tool_name not in ctx.allowed_tools:
        return POLICY_REASON_PREFIX + (
            f"{tool_name} is not in the allowed tool set for this execution context"
        )

    if (ctx.permission_mode == PLAN_PERMISSION_MODE
            and tool_name not in READ_ONLY_INSPECTION_TOOLS):
        return POLICY_REASON_PREFIX + (
            f"{tool_name} is blocked in plan mode (read-only inspection only)"
        )

    if is_plan_lifecycle_tool_unavailable(
            tool_name, ctx.in_subagent, ctx.plan_required_teammate):
        return POLICY_REASON_PREFIX + (
            f"{tool_name} is not available inside subagents; plan mode is owned by the caller"
        )

    if ctx.awaiting_plan_approval and not is_plan_required_pre_approval_allowed_tool(
            tool_name, params, ctx.agent_name):
        return POLICY_REASON_PREFIX + (
            f"{tool_name} is not available while this plan-required teammate is awaiting "
            f"leader approval; finish investigation and call exit_plan_mode with the plan"
        )

    return None


def make_context_guard(
    context_provider: Callable[[], "ToolPolicyContext | None"],
    guard_name: str = "context_tool_policy_gate",
) -> Callable[[str, Any], "str | None"]:
    """构造 guard 函数，供 ToolRegistry.add_guard 使用（复用既有单调 deny 缝）。

    Args:
        context_provider: 零参可调用，返回 ToolPolicyContext 或 None（None=不收窄）。
    """
    def _guard(tool_name: str, params: Any) -> "str | None":
        return evaluate_tool_policy(context_provider(), tool_name, params)

    _guard.__name__ = guard_name
    return _guard


def build_policy_blocked_result(tool_name: str, reason: str) -> dict:
    """ts:139-153 —— 结果级阻断载荷（不抛错），供需要显式结构化拒绝的调用方使用。"""
    message = reason if reason.startswith(POLICY_REASON_PREFIX) else POLICY_REASON_PREFIX + reason
    return {
        "status": "blocked",
        "error_code": "tool_policy_denied",
        "error": message,
        "trades": [],
        "metrics": {"policy": "context_tool_policy"},
        "execution": {"status": "blocked", "stage": "policy", "code": "tool_policy_denied"},
        "policy": {"tool": tool_name, "reason": message},
    }