"""cycle-16 A: ToolRegistry.dispatch full-pipeline contract.

Why: tool_registry.dispatch() is the single dispatch path used by the OODA Act
step, but its branches were only partly asserted (64% module coverage).  In
particular the P3-A3 permission seam was dead *and broken*: the call site used
``self._permission_gate.check(...)`` while PermissionGate actually exposes
``check_tool_call(...)``, so the moment ``set_permission()`` was used every
dispatch raised AttributeError -- the 7-level gate could never gate anything.
This file pins the fixed seam plus every other branch of the pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from context_tool_policy import POLICY_REASON_PREFIX, ToolPolicyContext  # noqa: E402
from hook_events import HookBus, HookEvent  # noqa: E402
from permission_levels import PermissionLevel  # noqa: E402
from tool_registry import ToolDefinition, ToolRegistry  # noqa: E402

_ = pytest  # keep the import meaningful even if a case is skipped later


def _ok(**_kwargs):
    return {"status": "completed", "trades": [], "metrics": {}, "output": {"status": "ok"}}


def _reg(**handlers):
    reg = ToolRegistry()
    for name, fn in (handlers or {"t": _ok}).items():
        reg.register_script(name, fn)
    return reg


# ---- registration surface --------------------------------------------------

def test_dispatch_unknown_tool_raises_keyerror_listing_available():
    reg = _reg()
    with pytest.raises(KeyError) as excinfo:
        reg.dispatch("nope")
    msg = str(excinfo.value)
    assert "Tool not registered: nope" in msg
    assert "'t'" in msg


def test_register_script_and_agent_set_their_sources():
    reg = ToolRegistry()
    reg.register_script("s", _ok, description="script tool")
    reg.register_agent("a", _ok, description="agent tool")
    assert reg.get("s").source == "script"
    assert reg.get("a").source == "agent_prompt"
    assert reg.get("s").description == "script tool"
    assert reg.get("missing") is None


def test_register_same_name_overwrites():
    calls = []
    reg = _reg(t=lambda **_k: calls.append("first") or {"status": "completed"})
    reg.register_script("t", lambda **_k: calls.append("second") or {"status": "completed"})
    assert reg.dispatch("t")["status"] == "completed"
    assert calls == ["second"]


def test_discover_all_and_filtered_and_tool_names():
    reg = ToolRegistry()
    reg.register_script("s1", _ok)
    reg.register_agent("a1", _ok)
    reg.register(ToolDefinition(name="m1", source="mcp", handler=_ok))
    assert reg.tool_names == ["s1", "a1", "m1"]
    assert {t.name for t in reg.discover()} == {"s1", "a1", "m1"}
    assert [t.name for t in reg.discover("mcp")] == ["m1"]
    assert reg.discover("backtest") == []


# ---- P3-A3 permission seam (the fixed bug) ---------------------------------

def test_get_permission_defaults_to_bypass_without_a_gate():
    assert _reg().get_permission() is PermissionLevel.BYPASS


def test_set_permission_installs_a_gate_and_get_permission_reflects_it():
    reg = _reg()
    reg.set_permission(PermissionLevel.PLAN_ONLY, "cycle-16 regression")
    assert reg.get_permission() is PermissionLevel.PLAN_ONLY
    assert reg._permission_gate.level is PermissionLevel.PLAN_ONLY


def test_permission_gate_used_to_raise_attribute_error_but_now_blocks():
    """The original defect: .check() did not exist -> AttributeError."""
    reg = _reg()
    reg.register_script("write_file", lambda **_k: {"status": "completed",
                                                    "trades": [], "metrics": {}})
    reg.set_permission(PermissionLevel.DEFAULT, "default blocks writes")
    res = reg.dispatch("write_file")            # used to raise AttributeError
    assert res["status"] == "blocked"
    assert res["error_code"] == "permission_denied"
    assert res["metrics"]["permission_level"] == PermissionLevel.DEFAULT.value
    assert res["trades"] == []
    assert "write requires approval" in res["error"]


def test_permission_gate_allows_reads_at_default_level():
    reg = _reg()
    reg.register_script("read_file", lambda **_k: {"status": "completed",
                                                   "trades": [], "metrics": {}})
    reg.set_permission(PermissionLevel.DEFAULT)
    assert reg.dispatch("read_file")["status"] == "completed"


def test_permission_gate_bypass_allows_writes():
    reg = _reg()
    reg.register_script("write_file", _ok)
    reg.set_permission(PermissionLevel.BYPASS)
    assert reg.dispatch("write_file")["status"] == "completed"


def test_permission_gate_plan_only_blocks_execute_but_allows_read_only():
    reg = _reg()
    reg.register_script("write_file", _ok)
    reg.register_script("ls", _ok)
    reg.set_permission(PermissionLevel.PLAN_ONLY)
    assert reg.dispatch("write_file")["status"] == "blocked"   # write/execute
    assert reg.dispatch("ls")["status"] == "completed"         # read-only


# ---- pre hooks -------------------------------------------------------------

def test_pre_hook_param_rewrite_feeds_the_guard_view_not_the_call_args():
    """Pinned current semantics (registered as an observation in cycle-16).

    A pre-hook's returned mapping replaces the ``{name, args, kwargs}`` view
    that guards see, but the handler is still invoked with the *original*
    ``*args/**kwargs``.  So a hook can narrow or block a call but cannot rewrite
    the arguments actually handed to the tool.
    """
    to_handler = {}
    to_guard = {}

    def handler(**kwargs):
        to_handler.update(kwargs)
        return {"status": "completed", "trades": [], "metrics": {}}

    def rewrite(name, _params):
        return {"name": name, "args": (), "kwargs": {"injected": True}}

    def guard(_name, params):
        to_guard.update(params["kwargs"])
        return None

    reg = _reg(t=handler)
    reg.add_pre_hook(rewrite)
    reg.add_guard(guard)
    assert reg.dispatch("t")["status"] == "completed"
    assert to_guard == {"injected": True}     # guard sees the rewrite
    assert to_handler == {}                   # handler still gets the original


def test_pre_hook_returning_none_blocks_execution():
    calls = []
    reg = _reg(t=lambda **_k: calls.append(1) or {"status": "completed"})
    reg.add_pre_hook(lambda _n, _p: None)
    res = reg.dispatch("t")
    assert res["status"] == "skipped"
    assert res["execution"]["code"] == "pre_hook_blocked"
    assert calls == []


def test_pre_hook_exception_is_captured_as_pipeline_error():
    calls = []
    reg = _reg(t=lambda **_k: calls.append(1) or {"status": "completed"})

    def boom(_n, _p):
        raise RuntimeError("pre hooks exploded")

    reg.add_pre_hook(boom)
    res = reg.dispatch("t")
    assert res["status"] == "error"
    assert res["execution"]["code"] == "pre_hook_exception"
    assert "pre hooks exploded" in res["error"]
    assert calls == []


# ---- guards (monotonic deny chain) -----------------------------------------

def test_guard_reasons_are_all_collected_and_later_guard_cannot_undo():
    calls = []
    reg = _reg(t=lambda **_k: calls.append(1) or {"status": "completed"})
    reg.add_guard(lambda _n, _p: "first denial")
    reg.add_guard(lambda _n, _p: "second denial")
    res = reg.dispatch("t")
    assert res["execution"]["code"] == "guard_denied"
    assert "first denial" in res["error"] and "second denial" in res["error"]
    assert res["metrics"]["guards_triggered"] == 2
    assert calls == []


def test_guard_exception_is_recorded_as_a_reason():
    reg = _reg()

    def boom(_n, _p):
        raise RuntimeError("guard blew up")

    reg.add_guard(boom)
    reg.add_guard(lambda _n, _p: None)          # passes, cannot undo
    res = reg.dispatch("t")
    assert res["execution"]["code"] == "guard_denied"
    assert "guard blew up" in res["error"]


def test_guards_see_params_rewritten_by_pre_hooks():
    seen = {}
    reg = _reg()

    def rewrite(name, _params):
        return {"name": name, "args": (), "kwargs": {"tag": "rewritten"}}

    def guard(_name, params):
        seen.update(params["kwargs"])
        return None

    reg.add_pre_hook(rewrite)
    reg.add_guard(guard)
    assert reg.dispatch("t")["status"] == "completed"
    assert seen == {"tag": "rewritten"}


# ---- execution / post hooks ------------------------------------------------

def test_handler_exception_is_captured():
    def boom(**_k):
        raise RuntimeError("handler blew up")

    res = _reg(t=boom).dispatch("t")
    assert res["status"] == "error"
    assert res["execution"]["code"] == "handler_exception"
    assert "handler blew up" in res["error"]


def test_post_hook_can_replace_the_result_mapping():
    reg = _reg()
    reg.add_post_hook(lambda _n, _r: {"status": "completed", "replaced": True})
    assert reg.dispatch("t")["replaced"] is True


def test_post_hook_may_mutate_in_place():
    reg = _reg()
    reg.add_post_hook(lambda _n, result: result["provenance"].update({"hook": "seen"}))
    res = reg.dispatch("t")
    assert res["provenance"]["hook"] == "seen"
    assert res["task_result"]["provenance"]["hook"] == "seen"


def test_post_hook_exception_is_contained():
    reg = _reg()

    def boom(_n, _r):
        raise RuntimeError("post hooks exploded")

    reg.add_post_hook(boom)
    res = reg.dispatch("t")
    assert res["status"] == "error"
    assert res["execution"]["code"] == "post_hook_exception"
    assert res["task_result"]["execution"] == res["execution"]


def test_post_hooks_observe_a_guard_block():
    seen = []
    reg = _reg()
    reg.add_guard(lambda _n, _p: "denied")
    reg.add_post_hook(lambda _n, result: seen.append(result["status"]))
    assert reg.dispatch("t")["status"] == "skipped"
    assert seen == ["skipped"]


# ---- hook bus --------------------------------------------------------------

def test_hook_bus_receives_pre_and_post_tool_events():
    bus = HookBus()
    events = []
    bus.on("*", lambda payload: events.append(payload.event))
    reg = _reg()
    reg._hook_bus = bus
    assert reg.dispatch("t")["status"] == "completed"
    assert events == [HookEvent.PRE_TOOL, HookEvent.POST_TOOL]


def test_hook_bus_receives_tool_error_for_error_results():
    bus = HookBus()
    events = []
    bus.on("*", lambda payload: events.append(payload.event))

    def boom(**_k):
        raise RuntimeError("boom")

    reg = _reg(t=boom)
    reg._hook_bus = bus
    assert reg.dispatch("t")["status"] == "error"
    assert events == [HookEvent.PRE_TOOL, HookEvent.TOOL_ERROR]


# ---- MCP discovery ---------------------------------------------------------

class _McpTool:
    def __init__(self, name):
        self.name = name
        self.description = "mcp tool " + name
        self.input_schema = {"properties": {"x": {"type": "string"}}}


class _McpResult:
    def __init__(self, success, content=None, error=None):
        self.success = success
        self.content = content
        self.error = error


class _McpClient:
    def __init__(self, tools=None, raise_on_list=False):
        self._tools = tools if tools is not None else [_McpTool("alpha")]
        self._raise = raise_on_list
        self.calls = []

    def list_tools(self):
        if self._raise:
            raise RuntimeError("connection refused")
        return self._tools

    def call_tool(self, name, kwargs):
        self.calls.append((name, kwargs))
        if name == "bad":
            return _McpResult(False, error="remote failure")
        return _McpResult(True, content={"echo": kwargs})


def test_discover_from_mcp_registers_namespaced_tools_and_dispatches():
    client = _McpClient()
    reg = ToolRegistry()
    assert reg.discover_from_mcp(client, namespace="mcp/") == 1
    assert reg.tool_names == ["mcp/alpha"]
    tool = reg.get("mcp/alpha")
    assert tool.source == "mcp"
    assert tool.input_schema == {"properties": {"x": {"type": "string"}}}
    res = reg.dispatch("mcp/alpha", x=1)
    assert res["status"] == "completed"
    assert client.calls == [("alpha", {"x": 1})]        # un-namespaced to the server


def test_discover_from_mcp_reports_remote_failure_as_error_result():
    client = _McpClient(tools=[_McpTool("bad")])
    reg = ToolRegistry()
    reg.discover_from_mcp(client)
    res = reg.dispatch("bad")
    assert res["status"] == "error"
    assert "remote failure" in res["error"]


def test_discover_from_mcp_list_tools_failure_returns_zero():
    reg = ToolRegistry()
    assert reg.discover_from_mcp(_McpClient(raise_on_list=True)) == 0
    assert reg.tool_names == []


# ---- context tool policy seam ---------------------------------------------

def test_add_context_tool_policy_installs_a_guard():
    calls = []
    reg = ToolRegistry()
    reg.register_script("write_file", lambda **_k: calls.append(1) or {"status": "ok"})
    reg.add_context_tool_policy(
        lambda: ToolPolicyContext(in_subagent=True, permission_mode="plan"))
    res = reg.dispatch("write_file")
    assert res["status"] == "skipped"
    assert POLICY_REASON_PREFIX in res["error"]
    assert calls == []


def test_add_context_tool_policy_is_opt_in_and_never_blocks_when_absent():
    reg = _reg()
    assert reg.dispatch("t")["status"] == "completed"