"""测试工具执行管线 — 移植-P2"""

import sys; from pathlib import Path
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from tool_registry import ToolRegistry


def test_pre_hook_allows():
    reg = ToolRegistry()
    reg.register_script("echo", lambda x: {"result": x})
    reg.add_pre_hook(lambda name, params: params)
    result = reg.dispatch("echo", "hello")
    assert result["status"] == "completed"
    assert result["result"] == "hello"
    assert result["output"]["status"] == "not_verified"


def test_pre_hook_blocks():
    reg = ToolRegistry()
    reg.register_script("danger", lambda: {"result": "ran"})
    reg.add_pre_hook(lambda name, params: None)  # block everything
    result = reg.dispatch("danger")
    assert result["status"] == "skipped"
    assert result["execution"]["code"] == "pre_hook_blocked"


def test_post_hook_runs():
    side_effects = []
    reg = ToolRegistry()
    reg.register_script("echo", lambda x: {"result": x})
    reg.add_post_hook(lambda name, result: side_effects.append(result["result"]))
    reg.dispatch("echo", "test")
    assert side_effects == ["test"]


def test_pipeline_order():
    log = []
    reg = ToolRegistry()
    reg.register_script("pipe", lambda x: {"out": x})
    reg.add_pre_hook(lambda n, p: (log.append("pre"), p)[1])
    reg.add_post_hook(lambda n, r: log.append("post"))
    reg.dispatch("pipe", 42)
    assert log == ["pre", "post"]


def test_multiple_pre_hooks_first_blocks():
    reg = ToolRegistry()
    reg.register_script("test", lambda: {"ran": True})
    reg.add_pre_hook(lambda n, p: None)  # block
    reg.add_pre_hook(lambda n, p: p)     # never reached
    result = reg.dispatch("test")
    assert result["status"] == "skipped"


def test_hooks_dont_affect_registered_tools():
    reg = ToolRegistry()
    reg.register_script("clean", lambda: {"ok": True})
    reg.add_pre_hook(lambda n, p: p)
    assert reg.get("clean") is not None
    assert reg.get("clean").source == "script"
