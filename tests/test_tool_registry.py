"""测试工具注册中心 — 移植-P2 模块1"""

import sys
from pathlib import Path
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

import pytest
from tool_registry import ToolRegistry, ToolDefinition


# ── 基本注册/获取 ──

def test_register_and_get():
    reg = ToolRegistry()
    reg.register(ToolDefinition(name="test", source="script",
                  handler=lambda *a, **kw: {"status": "ok"}))
    t = reg.get("test")
    assert t is not None
    assert t.name == "test"
    assert t.source == "script"


def test_get_nonexistent():
    reg = ToolRegistry()
    assert reg.get("nonexistent") is None


# ── 快捷注册 ──

def test_register_script():
    reg = ToolRegistry()
    reg.register_script("backtest", lambda *a, **kw: {"status": "ok"})
    t = reg.get("backtest")
    assert t.source == "script"


def test_register_agent():
    reg = ToolRegistry()
    reg.register_agent("my_task", lambda *a, **kw: {"status": "ok"})
    t = reg.get("my_task")
    assert t.source == "agent_prompt"


# ── 同名覆盖 ──

def test_register_overwrites():
    reg = ToolRegistry()
    reg.register_script("tool", lambda: {"v": 1})
    reg.register_script("tool", lambda: {"v": 2})
    assert reg.dispatch("tool")["v"] == 2


# ── 发现 ──

def test_discover_all():
    reg = ToolRegistry()
    reg.register_script("a", lambda: {})
    reg.register_agent("b", lambda: {})
    all_tools = reg.discover()
    assert len(all_tools) == 2


def test_discover_by_source():
    reg = ToolRegistry()
    reg.register_script("a", lambda: {})
    reg.register_agent("b", lambda: {})
    scripts = reg.discover("script")
    assert len(scripts) == 1
    assert scripts[0].name == "a"


# ── 调度 ──

def test_dispatch_passes_args():
    reg = ToolRegistry()
    reg.register_script("echo", lambda x, y, z=0: {"x": x, "y": y, "z": z})
    result = reg.dispatch("echo", 1, 2, z=3)
    # dispatch wraps handler output in the TaskResult contract
    # (status/execution/output/business/provenance). The handler raw
    # return is retained at the top level, proving positional + keyword
    # args were passed through unchanged.
    assert result["x"] == 1
    assert result["y"] == 2
    assert result["z"] == 3


def test_dispatch_unknown_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError, match="Tool not registered"):
        reg.dispatch("unknown")


# ── 工具名称列表 ──

def test_tool_names():
    reg = ToolRegistry()
    reg.register_script("a", lambda: {})
    reg.register_agent("b", lambda: {})
    assert set(reg.tool_names) == {"a", "b"}


# ── 描述和 schema ──

def test_tool_definition_fields():
    t = ToolDefinition(name="test", source="script", handler=lambda: {},
                       description="a test tool",
                       input_schema={"type": "object"})
    assert t.description == "a test tool"
    assert t.input_schema == {"type": "object"}

# ── Guard 层测试 ──

def test_guard_allows():
    """无 guard 拒绝时 dispatch 正常执行"""
    reg = ToolRegistry()
    reg.register_script("safe", lambda: {"v": 42})

    reg.add_guard(lambda name, params: None)
    result = reg.dispatch("safe")
    assert result["v"] == 42


def test_guard_single_reject():
    """单个 guard 拒绝时 dispatch 返回 skipped 状态"""
    reg = ToolRegistry()
    reg.register_script("danger", lambda: {"v": 99})

    reg.add_guard(lambda name, params: "sandbox denied" if name == "danger" else None)
    result = reg.dispatch("danger")
    assert result["status"] == "skipped"
    assert "sandbox denied" in result.get("error", "")


def test_guard_multiple_reject():
    """多个 guard 都拒绝时收集所有拒绝理由"""
    reg = ToolRegistry()
    reg.register_script("danger", lambda: {"v": 99})

    reg.add_guard(lambda name, params: "rule A violated" if name == "danger" else None)
    reg.add_guard(lambda name, params: "rule B violated" if name == "danger" else None)
    result = reg.dispatch("danger")
    assert result["status"] == "skipped"
    assert "rule A violated" in result.get("error", "")
    assert "rule B violated" in result.get("error", "")


def test_guard_partial_reject():
    """多个 guard 中部分拒绝时只收集拒绝理由，其余放行但整体 blocked"""
    reg = ToolRegistry()
    reg.register_script("edge", lambda x=0: {"x": x})

    reg.add_guard(lambda name, params: "no params" if not params.get("args") else None)
    reg.add_guard(lambda name, params: None)
    reg.add_guard(lambda name, params: "extra check" if name == "edge" else None)
    result = reg.dispatch("edge", x=0)
    assert result["status"] == "skipped"
    assert "extra check" in result.get("error", "")


def test_guard_inspect_params():
    """guard 可以检查 params 并据此决策（params 是 {"name":...,"args":..., "kwargs":...}）"""
    reg = ToolRegistry()
    reg.register_script("write", lambda path, content: {"path": path})

    reg.add_guard(lambda name, params: "bad path" if ".." in str(params.get("args", ())) else None)
    # 合法路径放行
    result_ok = reg.dispatch("write", "data/out.txt", "hello")
    assert result_ok["status"] == "completed"

    # 危险路径拒绝
    result_bad = reg.dispatch("write", "../etc/passwd", "hack")
    assert result_bad["status"] == "skipped"
    assert "bad path" in result_bad.get("error", "")


def test_guard_no_guard_installed():
    """没有安装 guard 时 dispatch 正常执行"""
    reg = ToolRegistry()
    reg.register_script("normal", lambda: {"ok": True})
    result = reg.dispatch("normal")
    assert result["status"] == "completed"
    assert result["ok"] is True


