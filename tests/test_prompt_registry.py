"""测试 SystemPrompt 段注册表 — P2-N1。"""

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from prompt_registry import (
    PromptSection, PromptRegistry, create_default_registry,
)


# ── 基本注册/渲染 ──

def test_add_and_render():
    reg = PromptRegistry()
    reg.add(PromptSection("s1", priority=10, content="First"))
    reg.add(PromptSection("s2", priority=20, content="Second"))
    result = reg.render()
    assert result == "First\n\nSecond"


def test_priority_sorting():
    """高 priority 值排后面。"""
    reg = PromptRegistry()
    reg.add(PromptSection("last", priority=999, content="Z"))
    reg.add(PromptSection("first", priority=1, content="A"))
    reg.add(PromptSection("mid", priority=100, content="M"))
    result = reg.render(separator="|")
    assert result == "A|M|Z"


def test_empty_registry():
    reg = PromptRegistry()
    result = reg.render()
    assert result == ""


def test_custom_separator():
    reg = PromptRegistry()
    reg.add(PromptSection("a", priority=1, content="A"))
    reg.add(PromptSection("b", priority=2, content="B"))
    result = reg.render(separator="---")
    assert result == "A---B"


# ── 条件渲染 ──

def test_condition_true():
    reg = PromptRegistry()
    reg.add(PromptSection("a", priority=1, content="included",
                          condition=lambda: True))
    result = reg.render()
    assert "included" in result


def test_condition_false():
    reg = PromptRegistry()
    reg.add(PromptSection("a", priority=1, content="excluded",
                          condition=lambda: False))
    reg.add(PromptSection("b", priority=2, content="visible"))
    result = reg.render()
    assert "excluded" not in result
    assert "visible" in result


def test_condition_dynamic():
    """条件可动态切换。"""
    flag = [True]
    reg = PromptRegistry()
    reg.add(PromptSection("a", priority=1, content="ON",
                          condition=lambda: flag[0]))
    
    assert "ON" in reg.render()
    flag[0] = False
    assert "ON" not in reg.render()


# ── 动态渲染 ──

def test_render_fn():
    reg = PromptRegistry()
    counter = [0]
    reg.add(PromptSection("dyn", priority=1,
                          render_fn=lambda: f"count={counter[0]}"))
    counter[0] = 5
    result = reg.render()
    assert "count=5" in result


def test_render_fn_error_handled():
    """render_fn 抛异常 → 跳过该段。"""
    reg = PromptRegistry()
    reg.add(PromptSection("bad", priority=1,
                          render_fn=lambda: 1/0))
    reg.add(PromptSection("good", priority=2, content="ok"))
    result = reg.render()
    assert "ok" in result
    assert "bad" not in result  # render_fn 抛异常被吞


# ── 模板变量 ──

def test_template_vars():
    reg = PromptRegistry()
    reg.add(PromptSection("t", priority=1,
                          content="Task: {task_name}, Round: {round}"))
    result = reg.render({"task_name": "demo", "round": "3"})
    assert "Task: demo" in result
    assert "Round: 3" in result


def test_template_vars_no_match():
    reg = PromptRegistry()
    reg.add(PromptSection("t", priority=1, content="Hello {name}"))
    result = reg.render({})  # 没有 name → 原样保留
    assert "Hello {name}" in result


# ── 按 category 渲染 ──

def test_render_by_category():
    reg = PromptRegistry()
    reg.add(PromptSection("h", priority=1, content="HEADER",
                          category=PromptRegistry.HEADER))
    reg.add(PromptSection("b", priority=1, content="BODY",
                          category=PromptRegistry.BODY))
    reg.add(PromptSection("t", priority=1, content="TOOLS",
                          category=PromptRegistry.TOOLS))

    header = reg.render_by_category(PromptRegistry.HEADER)
    assert header == "HEADER"
    tools = reg.render_by_category(PromptRegistry.TOOLS)
    assert tools == "TOOLS"


# ── 管理 ──

def test_remove():
    reg = PromptRegistry()
    reg.add(PromptSection("a", priority=1, content="A"))
    reg.add(PromptSection("b", priority=2, content="B"))
    assert reg.remove("a") is True
    assert reg.remove("nonexistent") is False
    assert reg.section_count == 1


def test_clear():
    reg = PromptRegistry()
    reg.add(PromptSection("a", priority=1, content="A"))
    reg.clear()
    assert reg.section_count == 0
    assert reg.render() == ""


def test_get():
    reg = PromptRegistry()
    reg.add(PromptSection("found", priority=1, content="yes"))
    assert reg.get("found") is not None
    assert reg.get("notfound") is None


def test_list_by_category():
    reg = PromptRegistry()
    reg.add(PromptSection("a1", priority=10, content="A1",
                          category=PromptRegistry.HEADER))
    reg.add(PromptSection("a2", priority=5, content="A2",
                          category=PromptRegistry.HEADER))
    reg.add(PromptSection("b1", priority=1, content="B1",
                          category=PromptRegistry.BODY))
    
    headers = reg.list_by_category(PromptRegistry.HEADER)
    assert len(headers) == 2
    assert headers[0].priority == 5  # sorted by priority


# ── 预置注册表 ──

def test_default_registry():
    reg = create_default_registry()
    assert reg.section_count == 6
    names = reg.section_names
    assert "identity" in names
    assert "safety_rules" in names
    assert "task_place" in names
    assert "tools_available" in names
    
    result = reg.render({
        "task_description": "Run backtest",
        "tools_list": "bash, read",
        "context_info": "Round 1/10",
        "memory_context": "",
    })
    assert "OODA loop agent" in result
    assert "Run backtest" in result
    assert "bash, read" in result
    assert "SAFETY RULES" in result


def test_default_registry_render_by_category():
    reg = create_default_registry()
    rules = reg.render_by_category(PromptRegistry.RULES)
    assert "SAFETY RULES" in rules
    assert "Never delete files" in rules


# ── summary ──

def test_summary():
    reg = PromptRegistry()
    reg.add(PromptSection("a", priority=5, content="A",
                          render_fn=lambda: "dyn"))
    s = reg.summary()
    assert "PromptRegistry" in s
    assert "a" in s
    assert "[dyn]" in s
