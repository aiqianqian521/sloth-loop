"""轻量 MCP 客户端 — 移植自 DSH mcp 包。

通过 JSON-RPC over stdio 连接外部 MCP Server，发现并调用工具。
零外部依赖，纯 Python 标准库实现。

MCP 协议参考: https://spec.modelcontextprotocol.io/
移植自 DSH packages/mcp/ (MCP client bridge)
"""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MCPTool:
    """MCP 工具描述。"""
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)


@dataclass
class MCPResult:
    """MCP 工具调用结果。"""
    success: bool
    content: list[dict] = field(default_factory=list)
    error: str = ""


class MCPClient:
    """轻量 MCP 客户端 — JSON-RPC over stdio。

    cycle-35 A: the server subprocess is started through the ExecGate
    (``gate.popen``), so it is subject to the same guardian check, interpreter
    allow-list, environment scrubbing and output cap as every other spawn
    (invariant-1 / F1, the single business-spawn chokepoint).  A client without
    a gate refuses to connect -- fail-closed, never an ungated spawn.

    用法:
        client = MCPClient(exec_gate)   # gate is REQUIRED (cycle-35 A)
        client.connect("python my_mcp_server.py")
        tools = client.list_tools()
        result = client.call_tool("tool_name", {"arg": "value"})
        client.disconnect()
    """

    def __init__(self, gate=None):
        self._gate = gate
        self._proc: subprocess.Popen | None = None
        self._request_id = 0

    def connect(self, server_command: str | list[str],
                timeout_start: float = 10.0):
        """启动 MCP Server 子进程并完成初始化握手。

        Args:
            server_command: 启动命令（字符串 shell 模式或列表）
            timeout_start: 初始化超时秒数
        """
        if isinstance(server_command, str):
            import shlex
            cmd = shlex.split(server_command)
        else:
            cmd = server_command

        if self._gate is None:
            raise RuntimeError(
                "MCPClient requires an ExecGate: an ungated server spawn would "
                "bypass the single business-spawn chokepoint (invariant-1 / F1)")
        self._proc = self._gate.popen(cmd, encoding="utf-8")

        # 初始化握手: initialize → initialized
        deadline = time.time() + timeout_start
        self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "loop-mcp-client", "version": "2.1"},
        })
        # 等待响应
        while time.time() < deadline:
            resp = self._read_response()
            if resp and resp.get("result"):
                break
        self._send_notification("notifications/initialized", {})

    def disconnect(self):
        """关闭 MCP Server 连接。"""
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.stdout.close()
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
            self._proc = None

    def list_tools(self) -> list[MCPTool]:
        """发现 MCP Server 提供的工具列表。"""
        resp = self._send_request("tools/list", {})
        tools_data = resp.get("result", {}).get("tools", [])
        return [MCPTool(
            name=t.get("name", ""),
            description=t.get("description", ""),
            input_schema=t.get("inputSchema", {}),
        ) for t in tools_data]

    def call_tool(self, name: str, arguments: dict | None = None) -> MCPResult:
        """调用 MCP 工具。

        Args:
            name: 工具名称
            arguments: 工具参数
        Returns:
            MCPResult — success 表示调用是否成功
        """
        try:
            resp = self._send_request("tools/call", {
                "name": name,
                "arguments": arguments or {},
            })
            if "error" in resp:
                return MCPResult(
                    success=False,
                    error=resp["error"].get("message", str(resp["error"])),
                )
            result = resp.get("result", {})
            content = result.get("content", [])
            return MCPResult(success=True, content=content)
        except (OSError, json.JSONDecodeError) as e:
            return MCPResult(success=False, error=str(e))

    # ── JSON-RPC 内部实现 ──

    def _send_request(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        self._request_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        self._write(req)
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self._read_response()
            if resp and resp.get("id") == self._request_id:
                return resp
        raise TimeoutError(f"MCP request timeout: {method}")

    def _send_notification(self, method: str, params: dict):
        self._write({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })

    def _write(self, data: dict):
        if self._proc and self._proc.stdin:
            line = json.dumps(data, ensure_ascii=False) + "\n"
            self._proc.stdin.write(line)
            self._proc.stdin.flush()

    def _read_response(self) -> dict | None:
        if self._proc and self._proc.stdout:
            line = self._proc.stdout.readline()
            if line.strip():
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    return None
        return None