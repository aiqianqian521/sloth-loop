"""Tools registry center - ported from DSH Plugin/Tool Registry model.

Unified management of script/agent_prompt/mcp execution modes.
New execution modes only need registration, don't change orchestrator core code.

v2.1 port-P2: Add execution pipeline (guard â†' execute â†' post hooks)
Ported from DSH packages/core/tools/ (scoped tool registry + execution pipeline)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable
from permission_levels import PermissionGate, PermissionLevel, PermissionCheckResult
from hook_events import HookEvent

ToolHandler = Callable[..., dict]
HookFunc = Callable[[str, dict], dict | None]  # (tool_name, params) -> modified_params | None=block
GuardFunc = Callable[[str, dict], str | None]   # (tool_name, params) -> None=pass, str=rejection_reason (monotonic deny chain, DSH guard seam)


_log = logging.getLogger("sloth_engine.tool-registry")


@dataclass
class ToolDefinition:
    """Single tool definition - reference DSH ToolDefinition."""
    name: str
    source: str                    # "script" | "agent_prompt" | "backtest" | "mcp"
    handler: ToolHandler
    description: str = ""
    input_schema: dict = field(default_factory=dict)


class ToolRegistry:
    """Tool registry center - reference DSH ToolRegistry + Scoped Context.

    Register â†' discover â†' dispatch. Orchestrator only depends on ToolRegistry,
    not on specific execution modes.

    Execution pipeline (v2.2): pre_hooks â†' execute â†' post_hooks
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._pre_hooks: list[HookFunc] = []
        self._post_hooks: list[HookFunc] = []
        self._guards: list[GuardFunc] = []     # monotonic deny chain (DSH guard seam v2.2)
        self._permission_gate: PermissionGate | None = None  # P3-A3
        self._hook_bus = None  # P3-B2: injected by orchestrator: 7-level permission gate

    
    # ---- P3-A3: permission gate ----
    def set_permission(self, level: PermissionLevel, reason: str = ""):
        """Set permission level. All subsequent dispatch() calls will pass through gate."""
        self._permission_gate = PermissionGate(level=level)
        if reason:
            import logging
            _log = logging.getLogger("sloth_engine.tool-registry")
            _log.info("[permission] set to %s: %s", level.label, reason)

    def get_permission(self) -> PermissionLevel:
        """Get current permission level."""
        if self._permission_gate:
            return self._permission_gate.level
        return PermissionLevel.BYPASS  # default: unrestricted (backward compatible)
    
    def register(self, tool: ToolDefinition):
        """Register a tool. Same-name tools overwrite."""
        self._tools[tool.name] = tool

    def register_script(self, name: str, handler: ToolHandler,
                        description: str = ""):
        """Register script-type tool."""
        self.register(ToolDefinition(
            name=name, source="script", handler=handler,
            description=description,
        ))

    def register_agent(self, name: str, handler: ToolHandler,
                       description: str = ""):
        """Register agent_prompt-type tool."""
        self.register(ToolDefinition(
            name=name, source="agent_prompt", handler=handler,
            description=description,
        ))

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def discover(self, source: str | None = None) -> list[ToolDefinition]:
        """Discover tools. source=None returns all."""
        if source is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.source == source]

    # ---- B2: MCP unarchive - discover_from_mcp ----
    def discover_from_mcp(self, client, namespace: str = "") -> int:
        """Discover tools from an MCP server and register them.

        Args:
            client: MCPClient instance (from mcp_client.py).
            namespace: Optional prefix for tool names (e.g. "mcp/").
                       Empty string means no prefix (direct registration).

        Returns:
            Number of tools discovered and registered.

        Notes:
            - MCP tools are registered with source="mcp".
            - Handler wraps client.call_tool() for lazy dispatch.
            - On any error (connection, discovery), logs warning and returns 0.
        """
        registered = 0
        try:
            tools = client.list_tools()
        except Exception as exc:
            _log.warning("[mcp] list_tools failed: %s", exc)
            return 0

        for mcp_tool in tools:
            tool_name = f"{namespace}{mcp_tool.name}" if namespace else mcp_tool.name

            # Capture mcp_tool in closure to create a handler that calls MCP
            def _make_mcp_handler(_client, _tool_name):
                def _handler(**kwargs):
                    result = _client.call_tool(_tool_name, kwargs)
                    if result.success:
                        return {
                            "status": "ok",
                            "output": result.content,
                            "metrics": {},
                            "trades": [],
                        }
                    else:
                        return {
                            "status": "error",
                            "error": result.error,
                            "metrics": {},
                            "trades": [],
                        }
                return _handler

            self.register(ToolDefinition(
                name=tool_name,
                source="mcp",
                handler=_make_mcp_handler(client, mcp_tool.name),
                description=mcp_tool.description,
                input_schema=mcp_tool.input_schema,
            ))
            registered += 1
            _log.info("[mcp] registered tool: %s (schema keys: %s)",
                      tool_name, list(mcp_tool.input_schema.get("properties", {}).keys()))

        _log.info("[mcp] discovered %d tools from MCP server", registered)
        return registered

    def add_pre_hook(self, hook: HookFunc):
        """Add pre-execution hook. Returns None to block execution."""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: HookFunc):
        """Add post-execution hook."""
        self._post_hooks.append(hook)

    def add_guard(self, guard: GuardFunc):
        """Add monotonic guard. Returns None=pass, returns str=rejection reason.
        Ref: DSH tools.guard() monotonic safety interface.
        Later guards cannot undo earlier deny; all rejection reasons are collected.

        Args:
            guard: (tool_name, params) -> None | rejection_reason_string
        """
        self._guards.append(guard)

    def add_context_tool_policy(self, context_provider):
        """cycle-8 A4-cand-B: 注册「上下文域工具策略门」(AGE-17).

        context_provider: 零参可调用，返回 context_tool_policy.ToolPolicyContext 或
        None（None=不收窄）。策略门骑在既有单调 guard 缝上：被拒调用返回正常的结果级
        blocked 载荷（不抛异常），因此模型可据此自行改道。additive 且 opt-in。
        """
        from context_tool_policy import make_context_guard
        self.add_guard(make_context_guard(context_provider))

    def dispatch(self, name: str, *args, task_input: dict | None = None, **kwargs) -> dict:
        """Dispatch tool execution with full pipeline.

        Pipeline: P3-A3 permission gate â†' pre_hooks â†' guards â†' execute â†' post_hooks

        Returns normalized task_result payload.
        """
        from adapters.task_runner import normalize_task_result, task_result_payload

        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(
                f"Tool not registered: {name}. Available: {list(self._tools.keys())}")

        params = {"name": name, "args": args, "kwargs": kwargs}

        # P3-A3: permission gate check.
        # The seam is shared with tool_pipeline.ToolPipeline step 8, which calls
        # PermissionGate.check_tool_call(name, params).  This call site used the
        # long-gone .check() name, so as soon as set_permission() was used every
        # dispatch() raised AttributeError -- the 7-level gate could never gate
        # anything.  (cycle-16 A)
        if self._permission_gate:
            result = self._permission_gate.check_tool_call(
                tool.name,
                {"source": tool.source, "args": list(args), "kwargs": dict(kwargs)},
            )
            if not result.allowed:
                return {
                    "status": "blocked",
                    "error": result.reason or "Permission denied",
                    "error_code": "permission_denied",
                    "metrics": {"permission_level": self._permission_gate.level.value},
                    "trades": [],
                }

        task_input = task_input if task_input is not None else (
            args[0] if args and hasattr(args[0], "task_type") else None)
        raw_result = None

        # pre_hooks
        for hook in self._pre_hooks:
            try:
                modified = hook(name, params)
            except Exception as exc:
                raw_result = {
                    "status": "error", "error_code": "pre_hook_exception",
                    "error": str(exc), "metrics": {}, "trades": [],
                    "execution": {"status": "failed", "stage": "pre_hook",
                                  "code": "pre_hook_exception"},
                }
                break
            if modified is None:
                raw_result = {
                    "status": "blocked", "error": f"Blocked by pre-hook: {hook.__name__}",
                    "trades": [], "metrics": {},
                }
                break
            params = modified

        # guards: monotonic deny chain (DSH guard seam v2.2)
        # Run AFTER pre_hooks (which can modify params) and BEFORE execute.
        # Collect ALL rejection reasons; a later guard cannot undo an earlier deny.
        if raw_result is None and self._guards:
            guard_reasons: list[str] = []
            for guard in self._guards:
                try:
                    reason = guard(name, params)
                    if reason is not None and isinstance(reason, str):
                        guard_reasons.append(reason)
                except Exception as exc:
                    guard_reasons.append(
                        f"guard {getattr(guard, '__name__', 'unknown')} exception: {exc}"
                    )
            if guard_reasons:
                raw_result = {
                    "status": "blocked",
                    "error": "; ".join(guard_reasons),
                    "blocked_by": [
                        getattr(g, "__name__", "unknown") for g in self._guards
                    ],
                    "trades": [],
                    "metrics": {"guards_triggered": len(guard_reasons)},
                    "execution": {
                        "status": "blocked",
                        "stage": "guard",
                        "code": "guard_denied",
                    },
                }

        # P3-B2: PRE_TOOL event
        if self._hook_bus is not None:
            self._hook_bus.fire_tool(HookEvent.PRE_TOOL, tool_name=name)

        # execute
        if raw_result is None:
            try:
                raw_result = tool.handler(*args, **kwargs)
            except Exception as exc:
                raw_result = {"status": "error", "error_code": "handler_exception",
                              "error": str(exc), "metrics": {}, "trades": [],
                              "execution": {"status": "failed", "stage": "handler",
                                            "code": "handler_exception"}}
        # P3-B2: POST_TOOL or TOOL_ERROR event
        if self._hook_bus is not None:
            is_err = raw_result and isinstance(raw_result, dict) and raw_result.get("status") == "error"
            if is_err:
                self._hook_bus.fire(HookEvent.TOOL_ERROR, data={"tool": name, "error": str(raw_result.get("error", ""))[:100]})
            else:
                self._hook_bus.fire_tool(HookEvent.POST_TOOL, tool_name=name)

        contract = normalize_task_result(raw_result, adapter=tool.source, entry=name,
                                         task_input=task_input)
        result = task_result_payload(contract, raw_result if isinstance(raw_result, dict) else None)

        # Post hooks observe every outcome, including guard blocks. A hook may
        # mutate in place or return a replacement mapping. Its own failure is a
        # pipeline failure and must not escape the result-contract boundary.
        for hook in self._post_hooks:
            try:
                modified = hook(name, result)
                if isinstance(modified, dict):
                    result = modified
            except Exception as exc:
                result = {
                    "status": "error", "error_code": "post_hook_exception",
                    "error": str(exc), "metrics": result.get("metrics", {}),
                    "trades": result.get("trades", []),
                    "execution": {"status": "failed", "stage": "post_hook",
                                  "code": "post_hook_exception"},
                    "output": dict(result.get("output") or {"status": "not_available"}),
                    "business": {"status": "not_evaluated"},
                    "provenance": dict(result.get("provenance") or {}),
                }

        # Re-normalize after hooks so outer fields and the nested task_result
        # snapshot cannot drift apart.
        contract = normalize_task_result(result, adapter=tool.source, entry=name,
                                         task_input=task_input)
        result = task_result_payload(contract, result)

        return result

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
