"""风险评估引擎 —— 分层安全审查核心逻辑.

RiskAssessor 实现 Codex Guardian 风格的三层审查管道：
1. AUTO 层:    RiskLevel.AUTO/BLOCK → 直接通过/阻断
2. REVIEW 层:  高风险命令模式检测 + 操作链分析 + 风险评分计算
3. ESCALATE 层: 超出规则覆盖范围时升级到人工或 LLM 审查

预留 LLM 审查升级路径（当前 raise NotImplementedError）。
"""

from __future__ import annotations

import re
from typing import ClassVar, Optional

from .permission_matrix import (
    RiskLevel,
    ToolPermission,
    DEFAULT_PERMISSIONS,
    get_permission,
)
from .review_session import ReviewBudget, ReviewContext, ReviewDecision

# ── 高风险命令模式 ──────────────────────────────────────────
# (正则模式, 风险增量, 描述)
_HIGH_RISK_PATTERNS: list[tuple[re.Pattern[str], float, str]] = [
    # 文件系统破坏
    (re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|[rf-]*rf)\s+/", re.IGNORECASE),
     1.0, "Recursive force-remove from root"),
    (re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|[rf-]*rf)\s+~", re.IGNORECASE),
     0.95, "Recursive force-remove from home"),
    (re.compile(r"rm\s+-rf\b", re.IGNORECASE),
     0.7, "Generic rm -rf"),
    (re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),
     1.0, "Write directly to block device"),

    # 权限提升
    (re.compile(r"\bsudo\b", re.IGNORECASE),
     0.9, "Privilege escalation via sudo"),
    (re.compile(r"\bsu\s+-", re.IGNORECASE),
     0.9, "Switch user with environment preservation"),
    (re.compile(r"\bdoas\b", re.IGNORECASE),
     0.85, "Privilege escalation via doas"),

    # 管道执行（curl/wget 输出直接执行）
    (re.compile(r"(curl|wget)\s+.*\|\s*(ba)?sh", re.IGNORECASE),
     1.0, "curl/wget piped to shell"),
    (re.compile(r"(curl|wget)\s+.*\|\s*(perl|python|ruby|node)", re.IGNORECASE),
     0.95, "curl/wget piped to interpreter"),

    # 权限修改
    (re.compile(r"chmod\s+777\b", re.IGNORECASE),
     0.8, "World-writable permissions"),
    (re.compile(r"chmod\s+-R\s+777\b", re.IGNORECASE),
     0.95, "Recursive world-writable permissions"),
    (re.compile(r"chown\s+-R\b", re.IGNORECASE),
     0.7, "Recursive ownership change"),

    # 网络监听 / 后门
    (re.compile(r"\bnc\s+-[lL]\b", re.IGNORECASE),
     0.85, "Netcat listener (potential backdoor)"),
    (re.compile(r"\bncat\s+-[lL]\b", re.IGNORECASE),
     0.85, "Ncat listener (potential backdoor)"),

    # 代码执行 / 动态加载
    (re.compile(r"\beval\b", re.IGNORECASE),
     0.6, "Dynamic code evaluation"),
    (re.compile(r"\bexec\s+[>|]", re.IGNORECASE),
     0.7, "exec with redirection"),

    # Fork bomb
    (re.compile(r":\(\)\s*\{", re.IGNORECASE),
     1.0, "Fork bomb pattern"),
    (re.compile(r"\bwhile\s*\(\s*1\s*\)", re.IGNORECASE),
     0.6, "Infinite loop pattern"),

    # 危险磁盘操作
    (re.compile(r"\bdd\s+if=", re.IGNORECASE),
     0.7, "Raw disk I/O via dd"),
    (re.compile(r"\bmkfs\.", re.IGNORECASE),
     0.96, "Filesystem creation (destructive)"),
    (re.compile(r"\bmke2fs\b", re.IGNORECASE),
     0.96, "ext filesystem creation"),

    # 系统配置修改
    (re.compile(r"\biptables\s+-F\b", re.IGNORECASE),
     0.9, "Flush firewall rules"),
    (re.compile(r"\bsystemctl\s+disable\b", re.IGNORECASE),
     0.7, "Disable systemd service"),
    (re.compile(r"\bsystemctl\s+mask\b", re.IGNORECASE),
     0.85, "Mask systemd unit"),
]

def _is_intermediate_path_segment(combined: str, match) -> bool:
    """True when ``match`` sits inside a non-final segment of a path-like token.

    ``_HIGH_RISK_PATTERNS`` are word-boundary keywords (``eval``, ``sudo``,
    ``nc`` ...).  Searching them in the raw joined command string also matches
    *directory names*: ``C:/tmp/loop-eval-2026/data/in.json`` contains a
    word-boundary ``eval`` although nothing is ever evaluated.  A command may
    legitimately live at the END of a path token (``/usr/bin/sudo``), so a match
    is suppressed only when it lies in an earlier segment.

    Found by the 2026-10-25 full stress suite (D-G1): the entire run was denied
    in round 1 because the runtime root was named ``loop-eval-...``.

    Known boundary (cycle-29 A): the token is delimited by *spaces*, so a
    keyword whose own pattern spans a space (``nc -l``) still matches when it
    sits inside a path that contains a space (``E:/x/nc -l/y/in.json``).  The
    only way to suppress that is to join across whitespace, which would equally
    suppress a *real* ``nc -l /tmp/sock`` listener -- a hole, not a fix, so the
    boundary is documented instead of "fixed".
    """
    start, end = match.span()
    tok_start = combined.rfind(" ", 0, start) + 1
    tok_end = combined.find(" ", start)
    if tok_end == -1:
        tok_end = len(combined)
    token = combined[tok_start:tok_end]
    if "/" not in token and "\\" not in token:
        return False
    cut = max(token.rfind("/"), token.rfind("\\"))
    basename_start = tok_start + cut + 1
    return end <= basename_start


# ── 高风险命令风险评估阈值 ──────────────────────────────────
AUTO_THRESHOLD = 0.25     # 风险评分 < 阈值时自动通过
ESCALATE_THRESHOLD = 0.80  # 风险评分 >= 阈值时升级审查


class RiskAssessor:
    """分层安全风险评估引擎。

    审查管道:
    1. 权限矩阵查询 → BLOCK 直接拒绝，AUTO 直接通过
    2. 命令模式扫描 → 累加风险评分
    3. 操作链分析 → 检测连续写文件+执行命令等可疑模式
    4. 风险评分阈值判断 → 决定 allow/deny/escalate

    使用示例:
        assessor = RiskAssessor()
        ctx = ReviewContext(
            session_id="sess-1",
            tool_name="shell_command",
            tool_args={"command": "rm -rf /tmp/cache"},
            operation_chain=["write_file:script.py", "shell_command:python script.py"],
        )
        budget = ReviewBudget()
        decision = assessor.assess(ctx, budget)
        if decision.is_denied:
            raise ContainmentError(f"Guardian: {decision.reason}")
    """

    # 操作链危险模式定义
    _CHAIN_DANGER_PATTERNS: ClassVar[list[tuple[str, str, float]]] = [
        # (前序操作模式, 当前操作模式, 风险增量)
        ("write_file", "shell_command", 0.25),   # 写文件后立即执行命令
        ("write_file", "execute_code", 0.30),
        ("http_request", "shell_command", 0.20),  # 网络请求后执行命令
        ("http_request", "write_file", 0.15),
        ("delete_file", "write_file", 0.10),      # 删除后立即写入（可能替换关键文件）
        ("shell_command", "shell_command", 0.05),  # 连续执行命令
    ]

    def __init__(self, permissions: dict[str, ToolPermission] | None = None):
        """初始化风险评估器。

        Args:
            permissions: 自定义权限矩阵（默认使用 DEFAULT_PERMISSIONS）
        """
        self._permissions = permissions or dict(DEFAULT_PERMISSIONS)

    # ── 主审查入口 ───────────────────────────────────────────
    def assess(
        self,
        ctx: ReviewContext,
        budget: ReviewBudget | None = None,
    ) -> ReviewDecision:
        """执行分层安全审查。

        Args:
            ctx:    审查上下文
            budget: 审查预算（None 时创建默认预算）

        Returns:
            ReviewDecision（allow/deny/escalate）
        """
        budget = budget or ReviewBudget()

        # 预算检查
        if not budget.can_review():
            return self._escalate(
                ctx, budget,
                reason="Review budget exhausted",
                risk_score=0.5,
            )

        # 1. 权限矩阵查询
        perm = self._permissions.get(ctx.tool_name)
        if perm is None:
            # 未知工具 → 默认 REVIEW
            perm = ToolPermission(ctx.tool_name, RiskLevel.REVIEW)

        # 细粒度参数规则解析
        effective_level = perm.resolve_risk(ctx.tool_args)

        if effective_level == RiskLevel.AUTO:
            budget.consume()
            return ReviewDecision(
                decision="allow",
                reason=f"Auto-approved: {ctx.tool_name} at AUTO level",
                risk_score=0.0,
                budget_remaining=budget.remaining_requests,
            )

        if effective_level == RiskLevel.BLOCK:
            budget.consume()
            return ReviewDecision(
                decision="deny",
                reason=f"Blocked: {ctx.tool_name} at BLOCK level",
                risk_score=1.0,
                budget_remaining=budget.remaining_requests,
            )

        # 2. REVIEW 层：规则扫描
        risk_score, reasons = self._scan_risk(ctx)

        # 3. 操作链分析
        chain_score, chain_reasons = self._analyze_operation_chain(ctx)
        risk_score = min(1.0, risk_score + chain_score)
        reasons.extend(chain_reasons)

        budget.consume()

        # 4. 阈值判断
        if risk_score < AUTO_THRESHOLD:
            return ReviewDecision(
                decision="allow",
                reason="; ".join(reasons) if reasons else "No risk detected",
                risk_score=risk_score,
                budget_remaining=budget.remaining_requests,
                metadata={"patterns_matched": reasons},
            )

        # O-2 (cycle-29 A): escalate is *fail-closed*, i.e. it has the same
        # effect as deny, because no review channel is wired yet -- the outbound
        # port (``llm_review``) is deliberately left NotImplementedError.  The
        # decision still carries ``metadata.escalation_level`` so a human/LLM
        # reviewer can be plugged in later without touching this classifier;
        # see ExecGate._guardian_check for the enforcement side.
        if risk_score >= ESCALATE_THRESHOLD:
            return self._escalate(
                ctx, budget,
                reason="; ".join(reasons),
                risk_score=risk_score,
            )

        # 中等风险 → deny
        return ReviewDecision(
            decision="deny",
            reason="; ".join(reasons),
            risk_score=risk_score,
            budget_remaining=budget.remaining_requests,
            metadata={"patterns_matched": reasons},
        )

    # ── 风险扫描：高危命令模式 ─────────────────────────────
    def _scan_risk(self, ctx: ReviewContext) -> tuple[float, list[str]]:
        """扫描工具参数中的高风险模式。

        Args:
            ctx: 审查上下文

        Returns:
            (累计风险评分, 匹配模式描述列表)
        """
        score = 0.0
        reasons: list[str] = []

        # 提取所有字符串参数
        text_to_scan: list[str] = []
        for key, value in ctx.tool_args.items():
            if isinstance(value, str):
                text_to_scan.append(value)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, str):
                        text_to_scan.append(item)

        combined = " ".join(text_to_scan)

        if not combined.strip():
            return 0.0, []

        for pattern, risk_delta, description in _HIGH_RISK_PATTERNS:
            m = pattern.search(combined)
            if m is None:
                continue
            if _is_intermediate_path_segment(combined, m):
                # A path segment is not a command (D-G1).
                continue
            score += risk_delta
            reasons.append(description)

        return min(1.0, score), reasons

    # ── 操作链分析 ─────────────────────────────────────────
    def _analyze_operation_chain(self, ctx: ReviewContext) -> tuple[float, list[str]]:
        """分析操作链中是否存在危险模式组合。

        检测例如：
        - 连续写文件后执行命令 → 可能注入恶意脚本
        - 网络请求后执行命令 → 可能下载执行 payload
        - 删除后写入 → 可能替换关键文件

        Args:
            ctx: 审查上下文

        Returns:
            (操作链风险增量, 匹配描述列表)
        """
        if not ctx.operation_chain:
            return 0.0, []

        score = 0.0
        reasons: list[str] = []

        current_op = f"{ctx.tool_name}"
        recent = ctx.recent_chain(5)

        for prev_op_prefix, cur_op_prefix, delta in self._CHAIN_DANGER_PATTERNS:
            if not current_op.startswith(cur_op_prefix):
                continue
            for prev_op in recent:
                if prev_op.startswith(prev_op_prefix):
                    score += delta
                    reasons.append(
                        f"Suspicious chain: {prev_op} → {current_op}"
                    )
                    break  # 每种模式只匹配一次

        # 如果 chains 中有多个危险组合，额外加分
        if len(reasons) >= 2:
            score = min(1.0, score + 0.10)

        return score, reasons

    # ── 升级审查 ────────────────────────────────────────────
    def _escalate(
        self,
        ctx: ReviewContext,
        budget: ReviewBudget,
        *,
        reason: str,
        risk_score: float,
    ) -> ReviewDecision:
        """生成升级审查决策。

        当前版本仅返回 escalate 决策，LLM 升级路径预留。

        Args:
            ctx:        审查上下文
            budget:     审查预算
            reason:     升级原因
            risk_score: 风险评分

        Returns:
            escalate 决策
        """
        return ReviewDecision(
            decision="escalate",
            reason=reason,
            risk_score=risk_score,
            budget_remaining=budget.remaining_requests,
            metadata={
                "tool_name": ctx.tool_name,
                "operation_chain": ctx.recent_chain(),
                "escalation_level": "human" if risk_score >= 0.95 else "llm",
            },
        )

    # ── LLM 审查升级路径（预留） ────────────────────────────
    def llm_review(
        self,
        ctx: ReviewContext,
        budget: ReviewBudget,
    ) -> ReviewDecision:
        """LLM 辅助审查 —— 预留接口。

        当前未实现，调用将抛出 NotImplementedError。
        未来可用于:
        - 将高风险上下文发送给 LLM 进行语义分析
        - 在操作链分析中引入 LLM 判断
        - 对 escalate 的决策进行二次确认

        Args:
            ctx:    审查上下文
            budget: 审查预算

        Returns:
            LLM 审查决策

        Raises:
            NotImplementedError: 当前未实现
        """
        raise NotImplementedError(
            "LLM review is not yet implemented. "
            "Use RiskAssessor.assess() for rule-based review."
        )

    # ── 批量评估（实用工具） ────────────────────────────────
    def assess_batch(
        self,
        contexts: list[ReviewContext],
        budget: ReviewBudget | None = None,
    ) -> list[ReviewDecision]:
        """批量审查多个操作。

        Args:
            contexts: 审查上下文列表
            budget:   共享的审查预算

        Returns:
            审查决策列表（与输入顺序一致）
        """
        b = budget or ReviewBudget()
        return [self.assess(ctx, b) for ctx in contexts]
