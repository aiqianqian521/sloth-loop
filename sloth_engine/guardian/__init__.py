"""GuardianLight —— 分层安全审查系统 (Phase 1 任务B)

为 sloth-loop 在 ExecGate 之上叠加 Codex Guardian 风格的分层审批 +
审查预算 + 操作链分析。三层审查：AUTO（自动通过）→ REVIEW（规则扫描）→
escalate（人工/LLM升级）。

模块:
- permission_matrix: 工具权限矩阵定义（RiskLevel + ToolPermission）
- review_session: 审查会话/预算/上下文/决策数据模型
- risk_assessor: 核心风险评估引擎（模式检测 + 操作链分析）
"""
