"""SystemPrompt 段注册表 — P2-N1: 对标 DSH skill SystemPrompt 有序段。

当前 prompt_renderer.py 只是简单的字符串拼接。
升级为有序段注册表：每个段有 priority/condition/content，
render 时按 priority 排序后拼接。

对标: DSH packages/skill (SystemPrompt ordered-section registry)
设计:
  - PromptSection: name + priority + condition + render_fn
  - PromptRegistry: 注册多个段 → render() 按 priority 拼接
  - condition: 动态控制段是否生效（如 "only in backtest mode"）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ============================================================================
# PromptSection
# ============================================================================

@dataclass
class PromptSection:
    """系统提示中的一个有序段。

    Attributes:
        name:      段名 (用于调试/覆盖)
        priority:   排序优先级 (数字越小越靠前)
        content:    静态文本内容 (与 render_fn 二选一)
        render_fn:  动态渲染函数 () → str (与 content 二选一)
        condition:  条件函数 () → bool, 返回 True 时该段才生效
        category:   分类标签: "system"|"task"|"rules"|"context"|"memory"|"tool"
    """
    name: str
    priority: int = 100
    content: str = ""
    render_fn: Optional[Callable[[], str]] = None
    condition: Optional[Callable[[], bool]] = None
    category: str = "system"


# ============================================================================
# PromptRegistry
# ============================================================================

class PromptRegistry:
    """有序系统提示段注册表。

    使用方式:
        reg = PromptRegistry()
        reg.add(PromptSection("identity", priority=10, content="You are a code agent."))
        reg.add(PromptSection("rules", priority=50,
                render_fn=lambda: f"Today is {datetime.now()}"))
        reg.add(PromptSection("tools", priority=200,
                content="Available tools:\n{tools}"))
        prompt = reg.render({"tools": "bash, read, write"})
        # → "You are a code agent.\n\nToday is 2026-10-08\n\nAvailable tools:\nbash, read, write"
    """

    # 默认段
    HEADER = "system"
    BODY = "task"
    TOOLS = "tool"
    RULES = "rules"
    CONTEXT = "context"
    MEMORY = "memory"

    def __init__(self):
        self._sections: list[PromptSection] = []

    # ── 注册/管理 ──

    def add(self, section: PromptSection) -> None:
        """添加一个段。同名覆盖。"""
        self.remove(section.name)
        self._sections.append(section)

    def add_many(self, sections: list[PromptSection]) -> None:
        """批量添加。"""
        for s in sections:
            self.add(s)

    def remove(self, name: str) -> bool:
        """按名称移除段。返回是否找到。"""
        before = len(self._sections)
        self._sections = [s for s in self._sections if s.name != name]
        return len(self._sections) < before

    def clear(self) -> None:
        """清空所有段。"""
        self._sections.clear()

    # ── 渲染 ──

    def render(self, template_vars: dict[str, Any] | None = None,
               separator: str = "\n\n") -> str:
        """渲染所有生效的段，按 priority 排序拼接。

        Args:
            template_vars: 模板变量，用于 {var} 替换
            separator: 段间分隔符

        Returns:
            渲染后的完整系统提示文本
        """
        template_vars = template_vars or {}

        # 按 priority 排序
        sorted_sections = sorted(self._sections, key=lambda s: s.priority)

        rendered: list[str] = []
        for section in sorted_sections:
            # 条件检查
            if section.condition and not section.condition():
                continue

            # 获取内容
            if section.render_fn:
                try:
                    text = section.render_fn()
                except Exception:
                    text = ""  # 渲染失败跳过
            else:
                text = section.content

            if not text:
                continue

            # 模板变量替换
            for key, value in template_vars.items():
                text = text.replace(f"{{{key}}}", str(value))

            rendered.append(text)

        return separator.join(rendered)

    def render_by_category(self, category: str,
                           template_vars: dict[str, Any] | None = None,
                           separator: str = "\n\n") -> str:
        """只渲染指定 category 的段。"""
        template_vars = template_vars or {}
        sections = sorted(
            [s for s in self._sections if s.category == category],
            key=lambda s: s.priority,
        )

        rendered: list[str] = []
        for section in sections:
            if section.condition and not section.condition():
                continue

            text = section.render_fn() if section.render_fn else section.content
            if not text:
                continue

            for key, value in template_vars.items():
                text = text.replace(f"{{{key}}}", str(value))

            rendered.append(text)

        return separator.join(rendered)

    # ── 查询 ──

    @property
    def section_names(self) -> list[str]:
        return [s.name for s in self._sections]

    @property
    def section_count(self) -> int:
        return len(self._sections)

    def get(self, name: str) -> PromptSection | None:
        for s in self._sections:
            if s.name == name:
                return s
        return None

    def list_by_category(self, category: str) -> list[PromptSection]:
        return sorted(
            [s for s in self._sections if s.category == category],
            key=lambda s: s.priority,
        )

    def summary(self) -> str:
        lines = [f"PromptRegistry: {self.section_count} sections"]
        for s in sorted(self._sections, key=lambda x: x.priority):
            has_cond = " [cond]" if s.condition else ""
            has_dyn = " [dyn]" if s.render_fn else ""
            lines.append(f"  p{s.priority:03d} {s.name} ({s.category}){has_cond}{has_dyn}")
        return "\n".join(lines)


# ============================================================================
# 预置段工厂
# ============================================================================

def create_default_registry() -> PromptRegistry:
    """创建带预置段的 PromptRegistry。"""
    reg = PromptRegistry()

    reg.add_many([
        PromptSection(
            name="identity",
            priority=10,
            category=PromptRegistry.HEADER,
            content="You are an OODA loop agent. Your task is to Observe→Orient→Decide→Act→Verify→Learn.",
        ),
        PromptSection(
            name="safety_rules",
            priority=20,
            category=PromptRegistry.RULES,
            content="""SAFETY RULES:
1. Never delete files without explicit confirmation.
2. Never execute destructive commands (rm -rf, format, etc).
3. Always verify tool results before declaring success.
4. Record all failures for pattern learning.""",
        ),
        PromptSection(
            name="task_place",
            priority=100,
            category=PromptRegistry.BODY,
            content="{task_description}",
        ),
        PromptSection(
            name="tools_available",
            priority=200,
            category=PromptRegistry.TOOLS,
            content="Available tools:\n{tools_list}",
        ),
        PromptSection(
            name="context_info",
            priority=50,
            category=PromptRegistry.CONTEXT,
            content="{context_info}",
        ),
        PromptSection(
            name="memory_hint",
            priority=30,
            category=PromptRegistry.MEMORY,
            content="{memory_context}",
        ),
    ])

    return reg
