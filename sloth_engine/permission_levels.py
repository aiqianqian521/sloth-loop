"""
Permission Levels — P2-N5: 7级权限模式分层
===========================================
对标 Claude Code 7级权限系统：
bypassPermissions → dontAsk → auto → acceptEdits → default → plan → acceptEditsWithPlan

Claude Code 的权限模型：
- 每个权限级别定义了工具调用是否需要显式审批
- Agent 可以动态升级/降级权限（通过 CLI flags 或者 session state）
- 7级的梯度让用户从"完全信任"到"必须审核"逐级放松

sloth-loop 对标实现：
- PermissionLevel: Enum 含 7 级
- PermissionGate: 工具调用门禁
- PermissionPolicy: 可插拔策略（按任务/轮次/信号自动升降级）
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger("sloth_engine.permission")

# ---------------------------------------------------------------------------
# 1. 7级权限枚举
# ---------------------------------------------------------------------------

class PermissionLevel(enum.IntEnum):
    """权限级别（从严格到宽松）。

    对标 Claude Code:
    - ACCEPT_EDITS_WITH_PLAN (1) = acceptEditsWithPlan: 先审计划再执行
    - PLAN_ONLY (2)              = plan: 只允许规划/read-only
    - DEFAULT (3)                = default: 标准模式（写操作需审批）
    - ACCEPT_EDITS (4)           = acceptEdits: 自动接受编辑（仍审查工具调用）
    - AUTO (5)                   = auto: 自动执行大多数操作
    - DONT_ASK (6)               = dontAsk: 几乎不打扰
    - BYPASS (7)                 = bypassPermissions: 完全绕过权限（最高风险）
    """

    # 最严格 → 最宽松
    ACCEPT_EDITS_WITH_PLAN = 1   # 先审计划再执行
    PLAN_ONLY = 2                 # 只读/规划模式
    DEFAULT = 3                   # 标准模式
    ACCEPT_EDITS = 4             # 自动接受编辑
    AUTO = 5                      # 自动执行
    DONT_ASK = 6                  # 极少打断
    BYPASS = 7                    # 完全绕过（最高风险）

    @property
    def label(self) -> str:
        labels = {
            1: "acceptEditsWithPlan",
            2: "plan",
            3: "default",
            4: "acceptEdits",
            5: "auto",
            6: "dontAsk",
            7: "bypassPermissions",
        }
        return labels.get(self.value, f"unknown({self.value})")

    @property
    def is_write_allowed(self) -> bool:
        """写操作是否允许。"""
        return self.value >= PermissionLevel.ACCEPT_EDITS.value

    @property
    def needs_plan_review(self) -> bool:
        """是否需要计划审查。"""
        return self.value <= PermissionLevel.ACCEPT_EDITS_WITH_PLAN.value

    @property
    def needs_tool_approval(self) -> bool:
        """工具调用是否需要审批。"""
        return self.value <= PermissionLevel.DEFAULT.value

    @classmethod
    def from_label(cls, label: str) -> "PermissionLevel":
        """从字符串标签反查。"""
        mapping = {
            "acceptEditsWithPlan": cls.ACCEPT_EDITS_WITH_PLAN,
            "plan": cls.PLAN_ONLY,
            "default": cls.DEFAULT,
            "acceptEdits": cls.ACCEPT_EDITS,
            "auto": cls.AUTO,
            "dontAsk": cls.DONT_ASK,
            "bypassPermissions": cls.BYPASS,
        }
        return mapping.get(label, cls.DEFAULT)


# ---------------------------------------------------------------------------
# 2. 权限门禁 (PermissionGate)
# ---------------------------------------------------------------------------

@dataclass
class PermissionCheckResult:
    """权限检查结果。"""
    allowed: bool
    level: PermissionLevel
    reason: str = ""
    requires_approval: bool = False
    requires_plan: bool = False
    metadata: dict = field(default_factory=dict)


class PermissionGate:
    """工具调用门禁 —— 对标 Claude Code 的 PermissionRequest 流。

    决策链（从宽松到严格）：
    1. BYPASS → 全部放行，无日志
    2. DONT_ASK → 放行，仅记日志
    3. AUTO → 放行，记审计日志
    4. ACCEPT_EDITS → 写操作放行，读操作无限制
    5. DEFAULT → 写操作需审批
    6. PLAN_ONLY → 只允许只读工具
    7. ACCEPT_EDITS_WITH_PLAN → 先审计划，再逐tool审批
    """

    # 敏感操作关键词（在这些路径/操作上写需要审批）
    SENSITIVE_PATTERNS: tuple[str, ...] = (
        "rm", "remove", "delete", "unlink",
        "git push", "git force",
        "deploy", "restart", "stop", "kill",
        "chmod 777", "chown",
        "pip install", "pip uninstall",
        "DROP", "DELETE FROM", "TRUNCATE",
    )

    # 只读工具白名单（PLAN_ONLY 下允许）
    READ_ONLY_TOOLS: tuple[str, ...] = (
        "read", "cat", "ls", "list", "find", "grep", "search",
        "head", "tail", "wc", "stat", "file", "which", "type",
        "Get-ChildItem", "Select-String",
        "git log", "git status", "git diff", "git show",
        "echo", "print", "help", "man",
    )

    def __init__(self, level: PermissionLevel = PermissionLevel.DEFAULT):
        self.level = level

    # ── 主入口 ──
    def check_tool_call(
        self,
        tool_name: str,
        tool_args: dict | None = None,
        *,
        level: Optional[PermissionLevel] = None,
    ) -> PermissionCheckResult:
        """检查工具调用是否被当前权限允许。

        Args:
            tool_name: 工具名（如 "shell_command", "write_file"）
            tool_args: 工具参数（用于敏感操作检测）
            level: 覆盖级别（None 则使用实例默认）

        Returns:
            PermissionCheckResult
        """
        effective_level = level or self.level

        # BYPASS: 全部放行
        if effective_level >= PermissionLevel.BYPASS:
            return PermissionCheckResult(
                allowed=True,
                level=effective_level,
                reason="BYPASS: all operations allowed",
            )

        # DONT_ASK: 放行但审计
        if effective_level >= PermissionLevel.DONT_ASK:
            _log.info("[permission] DONT_ASK: allowing %s (audited)", tool_name)
            return PermissionCheckResult(
                allowed=True,
                level=effective_level,
                reason="DONT_ASK: allowed with audit log",
            )

        # AUTO: 放行，审计敏感操作
        if effective_level >= PermissionLevel.AUTO:
            if self._is_sensitive(tool_name, tool_args):
                _log.warning("[permission] AUTO: sensitive tool %s flagged", tool_name)
                return PermissionCheckResult(
                    allowed=True,
                    level=effective_level,
                    reason="AUTO: allowed, sensitive flagged for audit",
                    metadata={"sensitive": True},
                )
            return PermissionCheckResult(
                allowed=True,
                level=effective_level,
                reason="AUTO: allowed",
            )

        # ACCEPT_EDITS: 只审查写操作
        if effective_level >= PermissionLevel.ACCEPT_EDITS:
            if self._is_write_operation(tool_name, tool_args):
                if self._is_sensitive(tool_name, tool_args):
                    return PermissionCheckResult(
                        allowed=False,
                        level=effective_level,
                        reason="ACCEPT_EDITS: sensitive write blocked",
                        requires_approval=True,
                    )
                # 普通写操作放行
                return PermissionCheckResult(
                    allowed=True,
                    level=effective_level,
                    reason="ACCEPT_EDITS: write allowed, read unrestricted",
                )
            return PermissionCheckResult(
                allowed=True,
                level=effective_level,
                reason="ACCEPT_EDITS: read unrestricted",
            )

        # DEFAULT: 写操作需审批
        if effective_level >= PermissionLevel.DEFAULT:
            if self._is_write_operation(tool_name, tool_args):
                return PermissionCheckResult(
                    allowed=False,
                    level=effective_level,
                    reason="DEFAULT: write requires approval",
                    requires_approval=True,
                )
            return PermissionCheckResult(
                allowed=True,
                level=effective_level,
                reason="DEFAULT: read allowed",
            )

        # PLAN_ONLY: 只允许只读工具
        if effective_level >= PermissionLevel.PLAN_ONLY:
            if self._is_write_operation(tool_name, tool_args):
                return PermissionCheckResult(
                    allowed=False,
                    level=effective_level,
                    reason="PLAN_ONLY: write/execute blocked",
                    requires_approval=True,
                )
            if self._is_read_only(tool_name):
                return PermissionCheckResult(
                    allowed=True,
                    level=effective_level,
                    reason="PLAN_ONLY: read-only tool allowed",
                )
            return PermissionCheckResult(
                allowed=False,
                level=effective_level,
                reason="PLAN_ONLY: write/execute blocked",
                requires_approval=True,
            )

        # ACCEPT_EDITS_WITH_PLAN: 先审计划
        return PermissionCheckResult(
            allowed=False,
            level=effective_level,
            reason="ACCEPT_EDITS_WITH_PLAN: plan review required first",
            requires_plan=True,
            requires_approval=True,
        )

    # ── 辅助方法 ──
    def _is_write_operation(self, tool_name: str, tool_args: dict | None = None) -> bool:
        """判断是否为写操作。"""
        write_tools = (
            "shell_command", "write", "write_file", "append", "create",
            "remove", "rename", "move", "copy", "mkdir",
            "git commit", "git push", "git merge",
            "pip install", "pip uninstall",
            "Set-Content", "New-Item", "Remove-Item", "Move-Item",
        )
        tool_lower = tool_name.lower()
        for wt in write_tools:
            if wt.lower() in tool_lower:
                return True

        # 检查参数
        if tool_args:
            cmd = str(tool_args.get("command", tool_args.get("cmd", ""))).lower()
            if any(kw in cmd for kw in ("> ", ">> ", "tee ", "Set-Content", "New-Item")):
                return True

        return False

    def _is_sensitive(self, tool_name: str, tool_args: dict | None = None) -> bool:
        """检测敏感操作。"""
        cmd = str(tool_name).lower()
        if tool_args:
            cmd += " " + str(tool_args.get("command", tool_args.get("cmd", ""))).lower()

        for pattern in self.SENSITIVE_PATTERNS:
            if pattern.lower() in cmd:
                return True
        return False

    def _is_read_only(self, tool_name: str) -> bool:
        """检测是否只读工具。"""
        tool_lower = tool_name.lower()
        for ro in self.READ_ONLY_TOOLS:
            if ro.lower() in tool_lower:
                return True
        return False

    # ── 升级/降级 ──
    def escalate(self, new_level: PermissionLevel, reason: str = "") -> "PermissionGate":
        """升级权限（更严格）。"""
        if new_level > self.level:
            _log.warning("[permission] Cannot escalate to looser level %s from %s", new_level.label, self.level.label)
            return self
        _log.info("[permission] Escalated: %s → %s (%s)", self.level.label, new_level.label, reason)
        return PermissionGate(level=new_level)

    def deescalate(self, new_level: PermissionLevel, reason: str = "") -> "PermissionGate":
        """降级权限（更宽松）。"""
        if new_level < self.level:
            _log.warning("[permission] Cannot deescalate to stricter level %s from %s", new_level.label, self.level.label)
            return self
        _log.info("[permission] Deescalated: %s → %s (%s)", self.level.label, new_level.label, reason)
        return PermissionGate(level=new_level)

    @classmethod
    def from_config(cls, cfg: dict) -> "PermissionGate":
        """从配置创建。"""
        level_label = cfg.get("permission_level", "default")
        level = PermissionLevel.from_label(level_label)
        return cls(level=level)


# ---------------------------------------------------------------------------
# 3. 权限策略 (PermissionPolicy) — 可插拔自动升降级
# ---------------------------------------------------------------------------

class PermissionPolicy:
    """可插拔权限策略。

    对标 Claude Code: 权限可通过 session flags 动态变更。
    sloth-loop 扩展：基于任务轮次/信号/错误率自动升降级。
    """

    def __init__(self):
        self._policies: list[Callable[[PermissionContext], Optional[PermissionLevel]]] = []

    def register(self, policy_fn: Callable[["PermissionContext"], Optional[PermissionLevel]]):
        """注册一个策略函数。

        策略函数签名: (PermissionContext) → Optional[PermissionLevel]
        - 返回 PermissionLevel: 覆盖当前级别
        - 返回 None: 不改变
        """
        self._policies.append(policy_fn)

    def evaluate(self, ctx: "PermissionContext") -> PermissionLevel:
        """按优先级评估所有策略，返回最终级别。

        优先级: 后注册的策略可以覆盖前面的（叠加模式）。
        第一个返回非 None 的策略生效。
        """
        for policy in self._policies:
            result = policy(ctx)
            if result is not None:
                _log.debug("[permission-policy] %s → %s", policy.__name__, result.label)
                return result
        return ctx.current_level


@dataclass
class PermissionContext:
    """权限上下文 —— 策略函数输入。"""
    current_level: PermissionLevel
    round_num: int = 0
    total_rounds: int = 0
    consecutive_errors: int = 0
    error_stop: int = 5
    signal_count: int = 0
    excluded_count: int = 0
    task_name: str = ""
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 4. 内置策略
# ---------------------------------------------------------------------------

def policy_error_escalation(ctx: PermissionContext) -> Optional[PermissionLevel]:
    """连续错误超过阈值 → 升级到 PLAN_ONLY（阻止写操作）。"""
    if ctx.consecutive_errors >= ctx.error_stop:
        return PermissionLevel.PLAN_ONLY
    if ctx.consecutive_errors >= max(1, ctx.error_stop // 2):
        return PermissionLevel.ACCEPT_EDITS_WITH_PLAN
    return None


def policy_late_round_deescalation(ctx: PermissionContext) -> Optional[PermissionLevel]:
    """后期轮次 → 可适当放松（前 30% 严格，后 70% 放松）。"""
    if ctx.total_rounds > 0 and ctx.round_num / ctx.total_rounds > 0.7:
        # 后 30% 轮次：放松到 AUTO
        return PermissionLevel.AUTO
    return None


def policy_empty_batch_upgrade(ctx: PermissionContext) -> Optional[PermissionLevel]:
    """信号全被排除 → 降级到 DEFAULT（禁止写，等待新信号源）。"""
    if ctx.signal_count > 0 and ctx.excluded_count == ctx.signal_count:
        return PermissionLevel.DEFAULT
    return None


# 默认策略集
DEFAULT_POLICIES = [
    policy_error_escalation,
    policy_late_round_deescalation,
    policy_empty_batch_upgrade,
]
