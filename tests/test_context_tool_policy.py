# -*- coding: utf-8 -*-
"""cycle-8 A4-cand-B: 上下文域工具策略门（AGE-17）测试.

Provenance: 真值源 qwen-code packages/core/src/agents/runtime/subagent-plan-tool-policy.ts
（只读白名单 :19-34 / 上下文判定 :43-45 / 参数级认领 :107-130 / 结果级阻断 :139-153）。
覆盖：常量保真、无上下文放行（契约不变）、名单收窄、计划态只读、计划生命周期工具、
计划待批准域白名单 + task_update 参数级认领、裸/包装两种 params 形状、guard 工厂、
结果级阻断载荷、ToolRegistry 集成（结果级 blocked -> skipped 且不调 handler）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from context_tool_policy import (  # noqa: E402
    PLAN_REQUIRED_PRE_APPROVAL_TOOLS,
    POLICY_REASON_PREFIX,
    READ_ONLY_INSPECTION_TOOLS,
    ToolPolicyContext,
    build_policy_blocked_result,
    evaluate_tool_policy,
    is_plan_lifecycle_tool_unavailable,
    is_pre_approval_claim_only_task_update,
    make_context_guard,
)
from sub_agent import AgentContext  # noqa: E402
from tool_registry import ToolRegistry  # noqa: E402


def _wrap(**kw):
    """loop dispatch 包装形态的 params。"""
    return {"name": "task_update", "args": (), "kwargs": kw}


def _approval_ctx(agent_name="w1"):
    return ToolPolicyContext(
        in_subagent=True, plan_required_teammate=True,
        awaiting_plan_approval=True, agent_name=agent_name,
    )


# ── 常量保真（真值源 ts:19-34） ─────────────────────────────────────────────

def test_truth_constants_faithful_to_source():
    assert READ_ONLY_INSPECTION_TOOLS == frozenset({
        "read_file", "grep", "glob", "ls", "lsp", "tool_search", "read_mcp_resource",
    })
    assert PLAN_REQUIRED_PRE_APPROVAL_TOOLS == (
        READ_ONLY_INSPECTION_TOOLS | {"exit_plan_mode", "task_list"})


# ── 无上下文 = 不收窄（契约不变） ───────────────────────────────────────────

def test_no_context_is_noop():
    assert evaluate_tool_policy(None, "write_file", {}) is None
    assert evaluate_tool_policy(ToolPolicyContext(), "write_file", {}) is None
    assert evaluate_tool_policy(ToolPolicyContext(), "shell_command", _wrap()) is None


# ── 显式名单收窄 ───────────────────────────────────────────────────────────

def test_disallowed_and_allowed_lists():
    ctx = ToolPolicyContext(disallowed_tools=("rm_rf",))
    assert evaluate_tool_policy(ctx, "rm_rf", {}) is not None
    assert evaluate_tool_policy(ctx, "read_file", {}) is None

    ctx2 = ToolPolicyContext(allowed_tools=("read_file",))
    assert evaluate_tool_policy(ctx2, "read_file", {}) is None
    blocked = evaluate_tool_policy(ctx2, "write_file", {})
    assert blocked is not None and blocked.startswith(POLICY_REASON_PREFIX)


def test_plan_permission_mode_is_read_only():
    ctx = ToolPolicyContext(permission_mode="plan")
    assert evaluate_tool_policy(ctx, "grep", {}) is None
    assert evaluate_tool_policy(ctx, "write_file", {}) is not None
    # 非 plan 模式不做只读收窄
    assert evaluate_tool_policy(ToolPolicyContext(permission_mode="default"),
                               "write_file", {}) is None


# ── 计划生命周期工具（ts:57-66） ───────────────────────────────────────────

def test_plan_lifecycle_tool_unavailable_matrix():
    assert is_plan_lifecycle_tool_unavailable("enter_plan_mode", True, False) is True
    assert is_plan_lifecycle_tool_unavailable("exit_plan_mode", True, False) is True
    assert is_plan_lifecycle_tool_unavailable("exit_plan_mode", True, True) is False
    assert is_plan_lifecycle_tool_unavailable("read_file", True, False) is False
    assert is_plan_lifecycle_tool_unavailable("enter_plan_mode", False, False) is False


def test_subagent_plan_lifecycle_blocked_in_gate():
    ctx = ToolPolicyContext(in_subagent=True)
    assert evaluate_tool_policy(ctx, "enter_plan_mode", {}) is not None
    assert evaluate_tool_policy(ctx, "exit_plan_mode", {}) is not None
    ok = ToolPolicyContext(in_subagent=True, plan_required_teammate=True)
    assert evaluate_tool_policy(ok, "exit_plan_mode", {}) is None


# ── 计划待批准域（ts:94-105） ──────────────────────────────────────────────

def test_pre_approval_whitelist_allows_only_inspection_plus_exit_and_tasklist():
    ctx = _approval_ctx()
    for tool in ("read_file", "grep", "glob", "ls", "lsp", "tool_search",
                 "read_mcp_resource", "exit_plan_mode", "task_list"):
        assert evaluate_tool_policy(ctx, tool, {}) is None, tool
    assert evaluate_tool_policy(ctx, "write_file", {}) is not None
    assert evaluate_tool_policy(ctx, "shell_command", {}) is not None
    assert evaluate_tool_policy(ctx, "enter_plan_mode", {}) is not None


def test_claim_only_task_update_allowed():
    ctx = _approval_ctx()
    assert evaluate_tool_policy(ctx, "task_update", _wrap(taskId="t1", status="in_progress")) is None
    assert evaluate_tool_policy(
        ctx, "task_update", _wrap(taskId="t1", status="in_progress", owner="w1")) is None
    assert evaluate_tool_policy(
        ctx, "task_update", _wrap(taskId="t1", status="in_progress", addBlocks=[])) is None


def test_task_update_denied_variants():
    ctx = _approval_ctx()
    assert evaluate_tool_policy(
        ctx, "task_update", _wrap(taskId="t1", status="done")) is not None
    assert evaluate_tool_policy(
        ctx, "task_update", _wrap(taskId="t1", status="in_progress", description="x")) is not None
    assert evaluate_tool_policy(
        ctx, "task_update", _wrap(taskId="t1", status="in_progress", owner="other")) is not None
    assert evaluate_tool_policy(
        ctx, "task_update", _wrap(taskId="t1", status="in_progress", addBlocks=["x"])) is not None
    assert evaluate_tool_policy(
        ctx, "task_update", _wrap(taskId="t1", status="in_progress", addBlockedBy=["y"])) is not None
    assert evaluate_tool_policy(ctx, "task_update", _wrap(status="in_progress")) is not None
    assert evaluate_tool_policy(ctx, "task_update", {}) is not None


# ── params 形状兼容 ────────────────────────────────────────────────────────

def test_claim_only_accepts_raw_named_params():
    assert is_pre_approval_claim_only_task_update(
        {"taskId": "t", "status": "in_progress"}) is True
    assert is_pre_approval_claim_only_task_update(
        {"taskId": "t", "status": "in_progress", "owner": "w1"}, "w1") is True
    assert is_pre_approval_claim_only_task_update(
        {"taskId": "t", "status": "in_progress", "owner": "w1"}, "w2") is False


def test_claim_only_from_positional_dict_arg():
    params = {"name": "task_update",
              "args": ({"taskId": "t", "status": "in_progress"},),
              "kwargs": {}}
    assert is_pre_approval_claim_only_task_update(params) is True


def test_claim_only_rejects_non_mapping_params():
    assert is_pre_approval_claim_only_task_update("nope") is False
    assert is_pre_approval_claim_only_task_update(None) is False


# ── guard 工厂 + 结果级阻断载荷 ────────────────────────────────────────────

def test_make_context_guard_name_and_behavior():
    gate = make_context_guard(lambda: ToolPolicyContext(disallowed_tools=("x",)))
    assert gate.__name__ == "context_tool_policy_gate"
    assert gate("x", {}) is not None
    assert gate("y", {}) is None

    assert make_context_guard(lambda: None)("x", {}) is None
    assert make_context_guard(lambda: None, guard_name="my_gate").__name__ == "my_gate"


def test_build_policy_blocked_result_shape():
    r = build_policy_blocked_result("write_file", "nope")
    assert r["status"] == "blocked"
    assert r["error_code"] == "tool_policy_denied"
    assert r["error"].startswith(POLICY_REASON_PREFIX)
    assert r["execution"] == {"status": "blocked", "stage": "policy",
                              "code": "tool_policy_denied"}
    assert r["policy"]["tool"] == "write_file"
    # 已带前缀的不重复叠加
    r2 = build_policy_blocked_result("x", POLICY_REASON_PREFIX + "dup")
    assert r2["error"].count(POLICY_REASON_PREFIX) == 1


# ── from_agent_context 映射 ────────────────────────────────────────────────

def test_from_agent_context_real_and_ducktyped():
    ctx = AgentContext(agent_id="w1", plan_required_teammate=True, permission_mode="plan",
                       allowed_tools=["read_file"], disallowed_tools=["rm"],
                       teammate_name="T")
    p = ToolPolicyContext.from_agent_context(ctx)
    assert p.in_subagent is True
    assert p.plan_required_teammate is True
    assert p.awaiting_plan_approval is True
    assert p.agent_name == "T"
    assert p.allowed_tools == ("read_file",)
    assert p.disallowed_tools == ("rm",)
    assert p.permission_mode == "plan"

    p2 = ToolPolicyContext.from_agent_context(AgentContext())
    assert p2.in_subagent is False and p2.awaiting_plan_approval is False and p2.agent_name == ""

    p3 = ToolPolicyContext.from_agent_context(SimpleNamespace(agent_id="d"))
    assert p3.in_subagent is True and p3.agent_name == "d"


# ── ToolRegistry 集成（结果级阻断，不抛异常） ──────────────────────────────

def test_registry_gate_blocks_at_result_level():
    reg = ToolRegistry()
    calls = []
    reg.register_script("write_file", lambda *a, **k: calls.append(1) or {"status": "ok"})
    reg.add_context_tool_policy(
        lambda: ToolPolicyContext(in_subagent=True, permission_mode="plan"))

    res = reg.dispatch("write_file")
    assert res["status"] == "skipped"          # 结果级阻断（guard 缝的既有语义）
    assert POLICY_REASON_PREFIX in res.get("error", "")
    assert calls == []                          # handler 未被调用


def test_registry_gate_allows_whitelisted_and_default_unchanged():
    reg = ToolRegistry()
    reg.register_script("read_file", lambda *a, **k: {"status": "ok", "out": 1})
    assert reg.dispatch("read_file")["status"] == "completed"   # 未注册策略门：契约不变

    reg.add_context_tool_policy(
        lambda: ToolPolicyContext(in_subagent=True, permission_mode="plan"))
    assert reg.dispatch("read_file")["status"] == "completed"   # 只读白名单内仍放行


def test_registry_gate_provider_none_is_noop():
    reg = ToolRegistry()
    reg.register_script("write_file", lambda *a, **k: {"status": "ok"})
    reg.add_context_tool_policy(lambda: None)
    assert reg.dispatch("write_file")["status"] == "completed"


# ── AgentContext 新字段：默认值 + 相等性 + to_dict 不外泄 ──────────────────

def test_agentcontext_new_fields_default_and_equality():
    a = AgentContext(agent_id="x")
    b = AgentContext(agent_id="x")
    assert a == b
    assert a.plan_required_teammate is False
    assert a.teammate_name == ""
    d = a.to_dict()
    assert isinstance(d, dict)
    assert "plan_required_teammate" not in d   # to_dict 显式枚举，不泄漏新字段
    assert "teammate_name" not in d


def test_agentcontext_watchdog_still_excluded_from_repr():
    a = AgentContext(agent_id="x")
    a.watchdog = object()
    assert "watchdog" not in repr(a)