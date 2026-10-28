"""测试剩余 5 项修复 — 结构化CLI、PM脚本、场景级复用、MCP Client、压缩"""

import json, sys, tempfile
from pathlib import Path
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))
sys.path.insert(0, str(_ENGINE / "_archive"))  # archived legacy modules

import pytest


# ════════════════════════════════════════════════
# 1. 结构化 CLI
# ════════════════════════════════════════════════

def test_structured_cli_run_success():
    from structured_cli import run
    result = run(["python", "-c", "print('hello')"])
    assert result.status == "completed"
    assert "hello" in result.stdout
    assert result.returncode == 0


def test_structured_cli_run_error():
    from structured_cli import run
    result = run(["python", "-c", "import sys; sys.exit(1)"])
    assert result.status == "error"
    assert result.returncode == 1


def test_structured_cli_run_timeout():
    from structured_cli import run
    result = run(["python", "-c", "import time; time.sleep(10)"], timeout_sec=1)
    assert result.status == "timeout"


def test_structured_cli_with_env():
    from structured_cli import run
    result = run(["python", "-c", "import os; print(os.environ.get('LOOP_TEST'))"],
                 env={"LOOP_TEST": "pass123"})
    assert "pass123" in result.stdout


def test_structured_cli_with_retry():
    from structured_cli import run_with_retry
    result, attempts = run_with_retry(
        ["python", "-c", "import sys; sys.exit(0)"], max_retries=1)
    assert result.status == "completed"
    assert len(attempts) == 1


# ════════════════════════════════════════════════
# 2. PM 脚本接入
# ════════════════════════════════════════════════

def test_pm_tasks_in_config():
    """PM tasks removed from config; verify no legacy PM entries."""
    from config_util import load_config
    cfg = load_config(_ENGINE / "config.yaml")
    pm = cfg.get("pm_tasks")
    assert pm is None, "pm_tasks should not exist in config"


# ════════════════════════════════════════════════
# 3. 场景级经验复用
# ════════════════════════════════════════════════

def test_scene_rules_fib_in_ranging():
    tmp = tempfile.mkdtemp()
    from memory_store import PatternStore
    store = PatternStore(Path(tmp) / "test.db")
    store.append_failure([{
        "id": "F-scene-001",
        "signal_pattern": "fib_ranging_error",
        "market_condition": "ranging",
        "failure_mode": "RANGING_FAKEOUT",
        "status": "resolved",
        "exclusion_rule": "scene:fib_in_ranging",
        "rule_type": "scene",
        "root_cause": "Fib 过滤器在震荡场景下无效",
    }])
    result = store.check_scene_rules("ranging", "Fib")
    assert result["applicable"]
    assert any("无效" in w for w in result["warnings"])


def test_scene_rules_no_match():
    tmp = tempfile.mkdtemp()
    from memory_store import PatternStore
    store = PatternStore(Path(tmp) / "test.db")
    result = store.check_scene_rules("趋势", "MA")
    assert not result["applicable"]


def test_scene_rules_smc_trend():
    tmp = tempfile.mkdtemp()
    from memory_store import PatternStore
    store = PatternStore(Path(tmp) / "test.db")
    store.append_failure([{
        "id": "F-scene-002",
        "signal_pattern": "smc_trend",
        "market_condition": "trend",
        "failure_mode": "EXTREME_CHASE",
        "status": "monitoring",
        "exclusion_rule": "scene:smc_in_trend",
        "rule_type": "scene",
        "root_cause": "SMC 在趋势市中覆盖率高但精度一般",
    }])
    result = store.check_scene_rules("trend", "SMC")
    assert result["applicable"]


# ════════════════════════════════════════════════
# 4. MCP Client
# ════════════════════════════════════════════════

def test_mcp_client_import():
    from mcp_client import MCPClient, MCPTool, MCPResult
    assert MCPClient is not None


def test_mcp_tool_creation():
    from mcp_client import MCPTool
    t = MCPTool(name="test_tool", description="a test")
    assert t.name == "test_tool"
    assert t.input_schema == {}


def test_mcp_result():
    from mcp_client import MCPResult
    r = MCPResult(success=True, content=[{"text": "ok"}])
    assert r.success
    assert r.content[0]["text"] == "ok"


# ════════════════════════════════════════════════
# 5. 上下文压缩
# ════════════════════════════════════════════════

def test_compact_small_no_change():
    from pattern_compactor import compact_patterns
    patterns = [{"signal_pattern": "a", "failure_mode": "X", "impact_trades": 1}]
    result = compact_patterns(patterns, max_summary=30)
    assert not result["compacted"]
    assert result["total"] == 1


def test_compact_large_condenses():
    from pattern_compactor import compact_patterns
    patterns = [
        {"signal_pattern": f"p{i}", "failure_mode": "X" if i % 2 == 0 else "Y",
         "impact_trades": i, "occurrences": i}
        for i in range(50)
    ]
    result = compact_patterns(patterns, max_summary=10)
    assert result["compacted"]
    assert result["total"] == 50
    assert len(result["top"]) <= 10
    assert "by_group" in result


def test_compact_for_prompt():
    tmp = tempfile.mkdtemp()
    from memory_store import PatternStore
    from pattern_compactor import compact_for_prompt
    store = PatternStore(Path(tmp) / "test.db")
    store.append_failure([{
        "id": f"F-{i:03d}",
        "signal_pattern": f"signal_{i}",
        "market_condition": "any",
        "failure_mode": "EXTREME_CHASE" if i < 3 else "RANGING_FAKEOUT",
        "impact_trades": i,
        "exclusion_rule": f"rule_{i}",
    } for i in range(5)])
    text = compact_for_prompt(store, max_patterns=3)
    assert "signal_0" in text
    assert "Pattern library" in text