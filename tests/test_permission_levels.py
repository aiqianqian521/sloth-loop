"""Tests for permission_levels.py — P2-N5 7级权限模式分层."""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import pytest
from permission_levels import (
    PermissionLevel,
    PermissionGate,
    PermissionCheckResult,
    PermissionPolicy,
    PermissionContext,
    policy_error_escalation,
    policy_late_round_deescalation,
    policy_empty_batch_upgrade,
    DEFAULT_POLICIES,
)


class TestPermissionLevel:
    """PermissionLevel 枚举测试。"""

    def test_values_order(self):
        """验证从严格到宽松的顺序。"""
        assert PermissionLevel.ACCEPT_EDITS_WITH_PLAN.value == 1
        assert PermissionLevel.PLAN_ONLY.value == 2
        assert PermissionLevel.DEFAULT.value == 3
        assert PermissionLevel.ACCEPT_EDITS.value == 4
        assert PermissionLevel.AUTO.value == 5
        assert PermissionLevel.DONT_ASK.value == 6
        assert PermissionLevel.BYPASS.value == 7

    def test_labels(self):
        assert PermissionLevel.BYPASS.label == "bypassPermissions"
        assert PermissionLevel.DONT_ASK.label == "dontAsk"
        assert PermissionLevel.AUTO.label == "auto"
        assert PermissionLevel.ACCEPT_EDITS.label == "acceptEdits"
        assert PermissionLevel.DEFAULT.label == "default"
        assert PermissionLevel.PLAN_ONLY.label == "plan"
        assert PermissionLevel.ACCEPT_EDITS_WITH_PLAN.label == "acceptEditsWithPlan"

    def test_is_write_allowed(self):
        """写操作只在 ACCEPT_EDITS 及以上允许。"""
        assert PermissionLevel.PLAN_ONLY.is_write_allowed is False
        assert PermissionLevel.DEFAULT.is_write_allowed is False
        assert PermissionLevel.ACCEPT_EDITS.is_write_allowed is True
        assert PermissionLevel.AUTO.is_write_allowed is True
        assert PermissionLevel.DONT_ASK.is_write_allowed is True
        assert PermissionLevel.BYPASS.is_write_allowed is True

    def test_needs_plan_review(self):
        """只有最低级别需要计划审查。"""
        assert PermissionLevel.ACCEPT_EDITS_WITH_PLAN.needs_plan_review is True
        assert PermissionLevel.PLAN_ONLY.needs_plan_review is False
        assert PermissionLevel.DEFAULT.needs_plan_review is False

    def test_needs_tool_approval(self):
        """DEFAULT 及以下需要工具审批。"""
        assert PermissionLevel.ACCEPT_EDITS_WITH_PLAN.needs_tool_approval is True
        assert PermissionLevel.PLAN_ONLY.needs_tool_approval is True
        assert PermissionLevel.DEFAULT.needs_tool_approval is True
        assert PermissionLevel.ACCEPT_EDITS.needs_tool_approval is False
        assert PermissionLevel.AUTO.needs_tool_approval is False

    def test_from_label(self):
        assert PermissionLevel.from_label("bypassPermissions") == PermissionLevel.BYPASS
        assert PermissionLevel.from_label("default") == PermissionLevel.DEFAULT
        assert PermissionLevel.from_label("nonexistent") == PermissionLevel.DEFAULT

    def test_from_label_all(self):
        """往返测试：每个 label → enum → label。"""
        for level in PermissionLevel:
            assert PermissionLevel.from_label(level.label) == level


class TestPermissionGate:
    """PermissionGate 门禁测试。"""

    def test_bypass_allows_everything(self):
        gate = PermissionGate(level=PermissionLevel.BYPASS)
        result = gate.check_tool_call("rm -rf /")
        assert result.allowed is True
        assert "BYPASS" in result.reason

    def test_dont_ask_allows_with_audit(self):
        gate = PermissionGate(level=PermissionLevel.DONT_ASK)
        result = gate.check_tool_call("git push --force")
        assert result.allowed is True
        assert "DONT_ASK" in result.reason

    def test_auto_flags_sensitive(self):
        gate = PermissionGate(level=PermissionLevel.AUTO)
        result = gate.check_tool_call("shell_command", {"command": "rm -rf /tmp/test"})
        assert result.allowed is True
        assert result.metadata.get("sensitive") is True

    def test_auto_allows_normal(self):
        gate = PermissionGate(level=PermissionLevel.AUTO)
        result = gate.check_tool_call("echo hello")
        assert result.allowed is True

    def test_accept_edits_blocks_sensitive_write(self):
        gate = PermissionGate(level=PermissionLevel.ACCEPT_EDITS)
        result = gate.check_tool_call("shell_command", {"command": "rm -rf /tmp/test"})
        assert result.allowed is False
        assert result.requires_approval is True

    def test_accept_edits_allows_read(self):
        gate = PermissionGate(level=PermissionLevel.ACCEPT_EDITS)
        result = gate.check_tool_call("ls -la")
        assert result.allowed is True

    def test_default_blocks_write(self):
        gate = PermissionGate(level=PermissionLevel.DEFAULT)
        # write_file is a write tool
        result = gate.check_tool_call("write_file")
        assert result.allowed is False
        assert result.requires_approval is True

    def test_default_allows_read(self):
        gate = PermissionGate(level=PermissionLevel.DEFAULT)
        result = gate.check_tool_call("grep pattern file")
        assert result.allowed is True

    def test_plan_only_allows_read_only(self):
        gate = PermissionGate(level=PermissionLevel.PLAN_ONLY)
        assert gate.check_tool_call("grep pattern file").allowed is True
        assert gate.check_tool_call("cat file.txt").allowed is True
        assert gate.check_tool_call("git log").allowed is True

    def test_plan_only_blocks_write(self):
        gate = PermissionGate(level=PermissionLevel.PLAN_ONLY)
        result = gate.check_tool_call("git push")
        assert result.allowed is False

    def test_accept_edits_with_plan_requires_plan(self):
        gate = PermissionGate(level=PermissionLevel.ACCEPT_EDITS_WITH_PLAN)
        result = gate.check_tool_call("ls")
        assert result.allowed is False
        assert result.requires_plan is True
        assert result.requires_approval is True

    def test_override_level_per_call(self):
        """每次调用可覆盖级别。"""
        gate = PermissionGate(level=PermissionLevel.DEFAULT)
        # DEFAULT blocks write
        assert gate.check_tool_call("write_file").allowed is False
        # 单次覆盖为 BYPASS
        assert gate.check_tool_call("write_file", level=PermissionLevel.BYPASS).allowed is True

    def test_sensitive_detection(self):
        gate = PermissionGate(level=PermissionLevel.DEFAULT)
        # rm is sensitive
        assert gate._is_sensitive("shell_command", {"command": "rm -rf /tmp"}) is True
        # echo is not
        assert gate._is_sensitive("echo hello") is False

    def test_write_detection(self):
        gate = PermissionGate(level=PermissionLevel.DEFAULT)
        assert gate._is_write_operation("write_file") is True
        assert gate._is_write_operation("mkdir") is True
        assert gate._is_write_operation("grep") is False

    def test_escalate_to_stricter(self):
        gate = PermissionGate(level=PermissionLevel.AUTO)
        new_gate = gate.escalate(PermissionLevel.PLAN_ONLY, "too many errors")
        assert new_gate.level == PermissionLevel.PLAN_ONLY
        # 原 gate 不变
        assert gate.level == PermissionLevel.AUTO

    def test_escalate_refuses_looser(self):
        """不能升级到更宽松的级别。"""
        gate = PermissionGate(level=PermissionLevel.PLAN_ONLY)
        new_gate = gate.escalate(PermissionLevel.AUTO, "try to loosen")
        assert new_gate.level == PermissionLevel.PLAN_ONLY  # 未变

    def test_deescalate_to_looser(self):
        gate = PermissionGate(level=PermissionLevel.PLAN_ONLY)
        new_gate = gate.deescalate(PermissionLevel.AUTO, "errors resolved")
        assert new_gate.level == PermissionLevel.AUTO

    def test_deescalate_refuses_stricter(self):
        """不能降级到更严格的级别。"""
        gate = PermissionGate(level=PermissionLevel.AUTO)
        new_gate = gate.deescalate(PermissionLevel.PLAN_ONLY, "try to tighten")
        assert new_gate.level == PermissionLevel.AUTO  # 未变

    def test_from_config(self):
        cfg = {"permission_level": "auto"}
        gate = PermissionGate.from_config(cfg)
        assert gate.level == PermissionLevel.AUTO

    def test_from_config_default(self):
        cfg = {}
        gate = PermissionGate.from_config(cfg)
        assert gate.level == PermissionLevel.DEFAULT


class TestPermissionPolicy:
    """PermissionPolicy 策略引擎测试。"""

    def test_empty_policy_returns_current(self):
        policy = PermissionPolicy()
        ctx = PermissionContext(current_level=PermissionLevel.AUTO, round_num=1)
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.AUTO

    def test_error_escalation_at_threshold(self):
        policy = PermissionPolicy()
        policy.register(policy_error_escalation)

        ctx = PermissionContext(
            current_level=PermissionLevel.AUTO,
            consecutive_errors=5,
            error_stop=5,
        )
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.PLAN_ONLY

    def test_error_escalation_half_threshold(self):
        policy = PermissionPolicy()
        policy.register(policy_error_escalation)

        ctx = PermissionContext(
            current_level=PermissionLevel.AUTO,
            consecutive_errors=3,
            error_stop=5,
        )
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.ACCEPT_EDITS_WITH_PLAN

    def test_error_escalation_no_error(self):
        policy = PermissionPolicy()
        policy.register(policy_error_escalation)

        ctx = PermissionContext(
            current_level=PermissionLevel.AUTO,
            consecutive_errors=0,
            error_stop=5,
        )
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.AUTO  # 不变

    def test_late_round_deescalation(self):
        policy = PermissionPolicy()
        policy.register(policy_late_round_deescalation)

        ctx = PermissionContext(
            current_level=PermissionLevel.DEFAULT,
            round_num=80,
            total_rounds=100,
        )
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.AUTO  # 后30%放松

    def test_late_round_no_deescalation_early(self):
        policy = PermissionPolicy()
        policy.register(policy_late_round_deescalation)

        ctx = PermissionContext(
            current_level=PermissionLevel.DEFAULT,
            round_num=30,
            total_rounds=100,
        )
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.DEFAULT  # 不变

    def test_empty_batch_upgrade(self):
        policy = PermissionPolicy()
        policy.register(policy_empty_batch_upgrade)

        ctx = PermissionContext(
            current_level=PermissionLevel.AUTO,
            signal_count=10,
            excluded_count=10,
        )
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.DEFAULT  # 全部排除 → 降级到DEFAULT

    def test_empty_batch_no_upgrade(self):
        policy = PermissionPolicy()
        policy.register(policy_empty_batch_upgrade)

        ctx = PermissionContext(
            current_level=PermissionLevel.AUTO,
            signal_count=10,
            excluded_count=5,
        )
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.AUTO  # 不变

    def test_multiple_policies_first_wins(self):
        """第一个拦截的策略生效。"""
        policy = PermissionPolicy()
        # 先注册错误升级
        policy.register(policy_error_escalation)
        # 后注册晚轮放松
        policy.register(policy_late_round_deescalation)

        # 场景：晚轮但有错误 → 错误升级应该优先
        ctx = PermissionContext(
            current_level=PermissionLevel.AUTO,
            round_num=80,
            total_rounds=100,
            consecutive_errors=5,
            error_stop=5,
        )
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.PLAN_ONLY  # 错误策略先触发

    def test_default_policies(self):
        """默认策略集包含3个策略。"""
        assert len(DEFAULT_POLICIES) == 3

    def test_full_policy_chain(self):
        """完整策略链测试。"""
        policy = PermissionPolicy()
        for p in DEFAULT_POLICIES:
            policy.register(p)

        # 正常轮次
        ctx = PermissionContext(
            current_level=PermissionLevel.DEFAULT,
            round_num=5,
            total_rounds=50,
            consecutive_errors=0,
            error_stop=10,
        )
        assert policy.evaluate(ctx) == PermissionLevel.DEFAULT


class TestPermissionContext:
    """PermissionContext 数据类测试。"""

    def test_defaults(self):
        ctx = PermissionContext(current_level=PermissionLevel.DEFAULT)
        assert ctx.current_level == PermissionLevel.DEFAULT
        assert ctx.round_num == 0
        assert ctx.consecutive_errors == 0
        assert ctx.error_stop == 5

    def test_custom_values(self):
        ctx = PermissionContext(
            current_level=PermissionLevel.AUTO,
            round_num=42,
            consecutive_errors=3,
            error_stop=10,
            task_name="test-task",
        )
        assert ctx.current_level == PermissionLevel.AUTO
        assert ctx.round_num == 42
        assert ctx.consecutive_errors == 3
        assert ctx.task_name == "test-task"


class TestIntegration:
    """集成测试：权限门禁 + 策略联动。"""

    def test_full_permission_flow(self):
        """模拟完整的权限流转：DEFAULT → 错误升级 → 恢复。"""
        # 初始：DEFAULT
        gate = PermissionGate.from_config({})

        # 正常工具调用
        assert gate.check_tool_call("grep").allowed is True
        assert gate.check_tool_call("write_file").allowed is False

        # 错误累积 → 策略升级
        policy = PermissionPolicy()
        policy.register(policy_error_escalation)
        policy.register(policy_late_round_deescalation)

        ctx = PermissionContext(
            current_level=PermissionLevel.DEFAULT,
            consecutive_errors=5,
            error_stop=5,
        )
        new_level = policy.evaluate(ctx)
        assert new_level == PermissionLevel.PLAN_ONLY

        # 升级后的门禁
        gate2 = PermissionGate(level=new_level)
        assert gate2.check_tool_call("grep").allowed is True  # 只读仍允许
        assert gate2.check_tool_call("write_file").allowed is False  # 写被阻止

        # 错误恢复后
        ctx2 = PermissionContext(
            current_level=PermissionLevel.PLAN_ONLY,
            consecutive_errors=0,
            error_stop=5,
        )
        restored = policy.evaluate(ctx2)
        assert restored == PermissionLevel.PLAN_ONLY  # 策略不自动恢复（需手动降级）

    def test_policy_chain_with_gate(self):
        """策略链 + 门禁联动。"""
        policy = PermissionPolicy()
        for p in DEFAULT_POLICIES:
            policy.register(p)

        # 场景：有错误 + 信号全排除
        ctx = PermissionContext(
            current_level=PermissionLevel.AUTO,
            round_num=80,
            total_rounds=100,
            consecutive_errors=3,
            error_stop=5,
            signal_count=5,
            excluded_count=5,
        )
        # 错误策略先触发
        result = policy.evaluate(ctx)
        assert result == PermissionLevel.ACCEPT_EDITS_WITH_PLAN  # 半阈值触发

        gate = PermissionGate(level=result)
        assert gate.check_tool_call("grep").allowed is False  # 需要先审计划

    def test_seven_level_coverage(self):
        """确保所有7级都有对应的行为。"""
        for level in PermissionLevel:
            gate = PermissionGate(level=level)
            # 每个级别至少可以调用 check_tool_call
            result = gate.check_tool_call("echo test")
            assert isinstance(result, PermissionCheckResult)
            assert result.level == level


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
