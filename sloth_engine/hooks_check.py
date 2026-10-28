"""
Hooks 检查脚本 (软约束执行器)

被 hooks.json 调用，按阶段执行轻量检查。
v2.1 移植-P0: 引入 HookOutput 标准化输出，支持多规则结果合并。

阶段:
  enforce_before_backtest  - 回测命令执行前，提醒先 check_exclusion
  enforce_after_backtest   - 回测命令执行后，提醒调用 record_result 写入库
  guard_pattern_edit       - Agent 直接写模式库 .md 时，提醒走工具而非直接改

说明: 软约束不阻断，只打印。硬约束由 MCP 工具接口保证。
"""

import os
import sys

from hook_protocol import (GuardPort, HookOutput, InMemoryGuardPort,
                           merge_hook_outputs, make_ask, make_warn, make_allow)


def _safe_hook_print(message: str) -> None:
    """Print hook diagnostics without crashing on a cp936 Windows console."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        fallback = message.encode(encoding, errors="replace").decode(encoding,
                                                                       errors="replace")
        print(fallback)


def _is_backtest_cmd(cmd: str) -> bool:
    return "backtest" in cmd.lower() or "audit" in cmd.lower() or "回测" in cmd


def enforce_before_backtest() -> HookOutput:
    """回测前检查：提醒读取失败模式库。"""
    cmd = os.environ.get("CLAUDE_TOOL_INPUT", "")
    if _is_backtest_cmd(cmd):
        msg = ("回测前请先读取失败信号模式库并排除已知失败模式"
               "（check_exclusion / agent-prompts/pre-backtest.md）")
        _safe_hook_print(f"[HOOK] ⚠️ {msg}")
        return make_warn(msg, rule_id="enforce_before_backtest")
    return make_allow(rule_id="enforce_before_backtest")


def enforce_after_backtest() -> HookOutput:
    """回测后检查：提醒写入模式库。"""
    cmd = os.environ.get("CLAUDE_TOOL_INPUT", "")
    if _is_backtest_cmd(cmd):
        msg = ("回测已完成，请调用 record_result 将结果写入模式库"
               "（agent-prompts/post-backtest.md），亏损→失败库，盈利→成功库")
        _safe_hook_print(f"[HOOK] ✅ {msg}")
        return make_warn(msg, rule_id="enforce_after_backtest")
    return make_allow(rule_id="enforce_after_backtest")


def guard_pattern_edit() -> HookOutput:
    """模式库编辑检查：提醒走工具而非直接编辑。"""
    path = os.environ.get("CLAUDE_TOOL_INPUT", "")
    if "失败信号模式库" in path or "成功信号模式库" in path:
        msg = ("检测到直接编辑模式库。请通过 MCP record_result 或"
               " sloth_engine 编排器写入，保持追加不覆盖、status 变更走人工审批")
        _safe_hook_print(f"[HOOK] ⚠️ {msg}")
        return make_ask(msg, rule_id="guard_pattern_edit",
                        gate="pattern_edit", requires_input=True)
    return make_allow(rule_id="guard_pattern_edit")


def run_all_checks(guard: GuardPort | None = None) -> HookOutput:
    """运行全部 hook 检查，返回合并结果。"""
    outputs = [
        enforce_before_backtest(),
        enforce_after_backtest(),
        guard_pattern_edit(),
    ]
    merged = merge_hook_outputs(outputs)
    return guard.route(merged) if guard is not None else merged


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    handlers = {
        "enforce_before_backtest": enforce_before_backtest,
        "enforce_after_backtest": enforce_after_backtest,
        "guard_pattern_edit": guard_pattern_edit,
    }
    guard = InMemoryGuardPort()
    result = handlers.get(stage, lambda: run_all_checks())()
    result = guard.route(result)
    if result.requires_input():
        _safe_hook_print(f"[HOOK] ASK queued for human gate: {result.reason}")
    # CLI semantics: block=1, ask=2 (fail-closed human gate), warn/allow=0.
    sys.exit(1 if result.is_blocking() else 2 if result.requires_input() else 0)
