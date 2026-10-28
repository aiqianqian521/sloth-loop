"""测试 Hook 协议标准化 — 移植-P0 模块2"""

import sys
import itertools
import tempfile
from pathlib import Path
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

import pytest
from hook_protocol import (
    GuardPort, HookOutput, InMemoryGuardPort, merge_hook_outputs,
    make_allow, make_ask, make_warn, make_block, Decision,
    _DECISION_ORDER,
)


# ── HookOutput 基本测试 ──

def test_hook_output_defaults():
    ho = HookOutput(decision="allow", reason="ok")
    assert ho.decision == "allow"
    assert ho.reason == "ok"
    assert ho.rule_id == ""
    assert ho.additional_context == {}


def test_hook_output_is_blocking():
    assert HookOutput(decision="block", reason="").is_blocking()
    assert not HookOutput(decision="warn", reason="").is_blocking()
    assert not HookOutput(decision="allow", reason="").is_blocking()


def test_hook_output_is_warning():
    assert HookOutput(decision="warn", reason="").is_warning()
    assert not HookOutput(decision="block", reason="").is_warning()
    assert not HookOutput(decision="allow", reason="").is_warning()


# ── 快捷构造器测试 ──

def test_make_allow():
    ho = make_allow("all good", "R1")
    assert ho.decision == "allow"
    assert ho.reason == "all good"
    assert ho.rule_id == "R1"


def test_make_warn():
    ho = make_warn("be careful", "R2", detail="check this")
    assert ho.decision == "warn"
    assert ho.reason == "be careful"
    assert ho.rule_id == "R2"
    assert ho.additional_context == {"detail": "check this"}


def test_make_block():
    ho = make_block("stop now", "R3")
    assert ho.decision == "block"
    assert ho.reason == "stop now"
    assert ho.rule_id == "R3"


def test_make_ask_is_human_gate_output():
    ho = make_ask("needs approval", "R-ASK", scope="pattern_edit")
    assert ho.decision == "ask"
    assert ho.requires_input()
    assert ho.additional_context == {"scope": "pattern_edit"}


def test_in_memory_guard_routes_without_prompt_or_checkpoint():
    port: GuardPort = InMemoryGuardPort()
    output = make_ask("approve this", "R-ASK")
    assert port.route(output) is output
    assert port.pending == [output]


def test_decision_order_is_not_configurable():
    with pytest.raises(TypeError):
        _DECISION_ORDER["block"] = 0


def test_invalid_decision_fails_closed_at_boundary():
    with pytest.raises(ValueError, match="unsupported hook decision"):
        HookOutput(decision="invalid", reason="bad")


@pytest.mark.parametrize(
    "decisions", list(itertools.product(("block", "ask", "warn", "allow"), repeat=4)))
def test_merge_all_four_dimensions_have_fixed_winner(decisions):
    outputs = [HookOutput(decision=d, reason=f"{d}-{i}", rule_id=f"R{i}")
               for i, d in enumerate(decisions)]
    result = merge_hook_outputs(outputs)
    expected = min(decisions, key=lambda d: -_DECISION_ORDER[d])
    assert result.decision == expected


def test_merge_same_level_ask_combines_reason_and_rule():
    result = merge_hook_outputs([
        make_ask("approval A", "A", source="one"),
        make_ask("approval B", "B", source="two"),
        make_warn("lower priority", "W"),
    ])
    assert result.decision == "ask"
    assert "approval A" in result.reason and "approval B" in result.reason
    assert result.rule_id == "A+B"
    assert result.additional_context == {"source": "two"}


# ── merge_hook_outputs 测试 ──

def test_merge_empty_returns_allow():
    result = merge_hook_outputs([])
    assert result.decision == "allow"


def test_merge_single():
    ho = make_warn("test")
    result = merge_hook_outputs([ho])
    assert result.decision == "warn"
    assert result.reason == "test"


def test_merge_block_wins_over_warn():
    result = merge_hook_outputs([
        make_warn("warning"),
        make_block("blocking"),
        make_allow("ok"),
    ])
    assert result.decision == "block"
    assert "blocking" in result.reason


def test_merge_warn_wins_over_allow():
    result = merge_hook_outputs([
        make_allow("ok"),
        make_warn("warning"),
    ])
    assert result.decision == "warn"


def test_merge_all_allow():
    result = merge_hook_outputs([
        make_allow("a"),
        make_allow("b"),
    ])
    assert result.decision == "allow"


def test_merge_same_level_combines_reasons():
    result = merge_hook_outputs([
        make_warn("issue A", "R1"),
        make_warn("issue B", "R2"),
    ])
    assert result.decision == "warn"
    assert "issue A" in result.reason
    assert "issue B" in result.reason
    assert "R1" in result.rule_id
    assert "R2" in result.rule_id


def test_merge_mixed_levels_only_top_reasons():
    result = merge_hook_outputs([
        make_block("critical", "R1"),
        make_warn("warning A", "R2"),
        make_warn("warning B", "R3"),
        make_allow("ok", "R4"),
    ])
    assert result.decision == "block"
    assert result.reason == "critical"
    assert result.rule_id == "R1"
    # warn 和 allow 的原因不应出现（被 block 覆盖）


# ── hooks_check 集成测试 ──

def test_hooks_check_enforce_returns_hook_output():
    import os as _os
    old = _os.environ.get("CLAUDE_TOOL_INPUT", "")
    try:
        _os.environ["CLAUDE_TOOL_INPUT"] = "some_other_command"
        from hooks_check import enforce_before_backtest
        result = enforce_before_backtest()
        assert isinstance(result, HookOutput)
        assert result.decision == "allow"
    finally:
        if old:
            _os.environ["CLAUDE_TOOL_INPUT"] = old
        elif "CLAUDE_TOOL_INPUT" in _os.environ:
            del _os.environ["CLAUDE_TOOL_INPUT"]


def test_hooks_check_backtest_triggers_warn():
    import os as _os
    old = _os.environ.get("CLAUDE_TOOL_INPUT", "")
    try:
        _os.environ["CLAUDE_TOOL_INPUT"] = "backtest"
        from hooks_check import enforce_before_backtest
        result = enforce_before_backtest()
        assert isinstance(result, HookOutput)
        assert result.decision == "warn"
        assert "回测前" in result.reason
    finally:
        if old:
            _os.environ["CLAUDE_TOOL_INPUT"] = old
        elif "CLAUDE_TOOL_INPUT" in _os.environ:
            del _os.environ["CLAUDE_TOOL_INPUT"]


def test_hooks_check_run_all_returns_merged():
    import os as _os
    old = _os.environ.get("CLAUDE_TOOL_INPUT", "")
    try:
        _os.environ["CLAUDE_TOOL_INPUT"] = "backtest"
        from hooks_check import run_all_checks
        result = run_all_checks()
        assert isinstance(result, HookOutput)
        # backtest 触发两个 warn → 合并为 warn
        assert result.decision == "warn"
    finally:
        if old:
            _os.environ["CLAUDE_TOOL_INPUT"] = old
        elif "CLAUDE_TOOL_INPUT" in _os.environ:
            del _os.environ["CLAUDE_TOOL_INPUT"]


def test_hooks_check_real_pattern_edit_produces_ask_and_routes():
    import os as _os
    old = _os.environ.get("CLAUDE_TOOL_INPUT", "")
    try:
        _os.environ["CLAUDE_TOOL_INPUT"] = "直接编辑成功信号模式库.md"
        from hooks_check import guard_pattern_edit, run_all_checks
        result = guard_pattern_edit()
        assert result.decision == "ask"
        port = InMemoryGuardPort()
        routed = run_all_checks(guard=port)
        assert routed.decision == "ask"
        assert len(port.pending) == 1
    finally:
        if old:
            _os.environ["CLAUDE_TOOL_INPUT"] = old
        elif "CLAUDE_TOOL_INPUT" in _os.environ:
            del _os.environ["CLAUDE_TOOL_INPUT"]


def test_pre_check_pending_context_routes_ask_without_input():
    from corrections.pre_check import _result_to_hook, run_all_hooks
    direct = _result_to_hook(("R4-参数扫描(待验证)", None, "needs values"))
    assert direct.decision == "ask"
    with tempfile.TemporaryDirectory(prefix="loop-pre-check-ask-") as td:
        work_dir = Path(td)
        (work_dir / "00-purpose.md").write_text("goal\nboundary\nsuccess_criteria\n", encoding="utf-8")
        (work_dir / "state.md").write_text("state\n", encoding="utf-8")
        (work_dir / "01-round-1.md").write_text("round\n", encoding="utf-8")
        port = InMemoryGuardPort()
        merged = run_all_hooks(work_dir=str(work_dir), task_context=None, guard=port)
        assert merged.decision == "ask"
        assert len(port.pending) == 1


def test_hooks_check_cli_cp936_does_not_crash_on_unicode_diagnostics():
    import os as _os
    import subprocess
    env = dict(_os.environ)
    env["CLAUDE_TOOL_INPUT"] = "直接编辑成功信号模式库.md"
    env["PYTHONIOENCODING"] = "cp936"
    result = subprocess.run(
        [sys.executable, str(_ENGINE / "hooks_check.py"), "guard_pattern_edit"],
        cwd=str(_ENGINE), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 2
    assert "UnicodeEncodeError" not in result.stderr
    assert "ASK queued for human gate" in result.stdout


def test_pre_check_cli_routes_ask_and_block_exit_codes():
    import subprocess
    ask = subprocess.run(
        [sys.executable, str(_ENGINE / "corrections" / "pre_check.py"), "--rule", "R4"],
        cwd=str(_ENGINE), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert ask.returncode == 2
    assert "ASK queued for human gate" in ask.stdout
    blocked = subprocess.run(
        [sys.executable, str(_ENGINE / "corrections" / "pre_check.py"),
         "--rule", "R4", "--param-values", "1"],
        cwd=str(_ENGINE), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert blocked.returncode == 1
