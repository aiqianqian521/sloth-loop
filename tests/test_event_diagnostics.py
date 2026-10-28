"""测试 EventDiagnostics — P1-N3 诊断层。

验证：盲目重试检测、连续失败检测、失败恢复链、行为信号扫描、工具结果矩阵。
"""

import sys
import tempfile
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from event_log import EventLog, LoopEvent
from event_diagnostics import (
    EventDiagnostics, DiagnosticSummary, FailureRecovery, BehaviorSignal,
    BLIND_RETRY_THRESHOLD, SLOW_CALL_THRESHOLD_MS, CONSECUTIVE_FAILURE_LIMIT,
)


# ── 辅助函数 ──

def _make_log_with_events(events_data: list[dict], task="test") -> EventLog:
    """用给定的 events_data 创建一个内存 EventLog。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "diag.jsonl"
        log = EventLog(path, task_name=task, auto_load=False)
        for ed in events_data:
            log.append(ed.get("event_type", "step/observe/end"),
                       {k: v for k, v in ed.items() if k != "event_type"})
        return log


def _assert_signal(signals: list, signal_name: str, severity: str = None):
    """断言信号列表中存在指定信号。"""
    matching = [s for s in signals if s.signal == signal_name]
    assert matching, f"期望信号 '{signal_name}' 但未找到。现有信号: {[s.signal for s in signals]}"
    if severity:
        assert matching[0].severity == severity, \
            f"期望严重度 {severity} 但实际为 {matching[0].severity}"


# ── 盲目重试检测 ──

def test_blind_retry_detected():
    """连续 ≥3 次同工具调用 → 盲目重试。"""
    events = [
        {"event_type": "round/start", "round": 1},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash"},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash"},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash"},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash"},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    assert s.blind_retries >= BLIND_RETRY_THRESHOLD, \
        f"期望盲目重试 ≥{BLIND_RETRY_THRESHOLD} 但实际 {s.blind_retries}"


def test_no_blind_retry_below_threshold():
    """连续 <3 次同工具调用 → 不应标记为盲目重试。"""
    events = [
        {"event_type": "round/start", "round": 1},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash"},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash"},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    assert s.blind_retries == 0


# ── 连续失败检测 ──

def test_consecutive_failures():
    """连续 ≥3 次 FAIL → 检测到。"""
    events = [
        {"event_type": "act/result", "round": 1, "status": "error"},
        {"event_type": "act/result", "round": 1, "status": "error"},
        {"event_type": "act/result", "round": 1, "status": "error"},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    assert s.consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT, \
        f"期望连续失败 ≥{CONSECUTIVE_FAILURE_LIMIT} 但实际 {s.consecutive_failures}"


def test_no_consecutive_failures():
    """PASS 中断 → 连续失败计数重置。"""
    events = [
        {"event_type": "act/result", "round": 1, "status": "error"},
        {"event_type": "act/result", "round": 1, "status": "ok"},
        {"event_type": "act/result", "round": 1, "status": "error"},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    assert s.consecutive_failures == 1


# ── 失败恢复链 ──

def test_recovery_chains_built():
    """失败后紧接 PASS → 记录恢复链。"""
    events = [
        {"event_type": "act/result", "round": 1, "status": "error", "error": "disk full", "tool": "write"},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "write", "strategy": "换策略恢复"},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    assert len(s.recovery_chains) == 1
    assert s.recovery_chains[0].failed_step == "act:result"
    assert "disk full" in s.recovery_chains[0].error_msg


def test_unrecovered_failure():
    """失败后没有后续事件 → 标记为未恢复。"""
    events = [
        {"event_type": "act/result", "round": 1, "status": "error", "error": "timeout", "tool": "api_call"},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    assert len(s.recovery_chains) == 1
    assert s.recovery_chains[0].recovery_strategy == "未恢复"


# ── 行为信号 ──

def test_signal_blind_retry():
    """盲目重试 → '盲目重试' 信号。"""
    events = [
        {"event_type": "round/start", "round": 1},
        *[{"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash"} for _ in range(5)],
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    _assert_signal(s.signals, "盲目重试", "高")


def test_signal_consecutive_failures():
    """连续失败 ≥3 → '连续失败' 信号。"""
    events = [
        {"event_type": "act/result", "round": 1, "status": "error"} for _ in range(4)
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    _assert_signal(s.signals, "连续失败", "高")


def test_signal_slow_call():
    """耗时 ≥120s → '慢调用' 信号。"""
    events = [
        {"event_type": "act/result", "round": 1, "status": "ok", "elapsed_ms": SLOW_CALL_THRESHOLD_MS + 1},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    _assert_signal(s.signals, "慢调用", "中")


def test_signal_unrecovered():
    """未恢复失败 → '未恢复失败' 信号。"""
    events = [
        {"event_type": "act/result", "round": 1, "status": "error", "error": "boom", "tool": "x"},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    _assert_signal(s.signals, "未恢复失败", "高")


# ── 工具结果矩阵 ──

def test_tool_result_matrix():
    """构建工具结果矩阵。"""
    events = [
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash", "elapsed_ms": 100},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "bash", "elapsed_ms": 200},
        {"event_type": "act/result", "round": 1, "status": "error", "tool": "bash", "elapsed_ms": 300},
        {"event_type": "act/result", "round": 1, "status": "ok", "tool": "read", "elapsed_ms": 50},
    ]
    log = _make_log_with_events(events)
    d = EventDiagnostics(log)
    s = d.diagnose()
    assert "bash" in s.tool_result_matrix
    assert s.tool_result_matrix["bash"]["success"] == 2
    assert s.tool_result_matrix["bash"]["failed"] == 1
    assert s.tool_result_matrix["bash"]["total_calls"] == 3
    assert abs(s.tool_result_matrix["bash"]["success_rate"] - 66.67) < 1
    assert "read" in s.tool_result_matrix
    assert s.tool_result_matrix["read"]["success"] == 1


# ── EventLog.diagnose() 便捷方法 ──

def test_event_log_diagnose_convenience():
    """EventLog.diagnose() 便捷方法可用。"""
    events = [
        {"event_type": "round/start", "round": 1},
    ]
    log = _make_log_with_events(events)
    s = log.diagnose_summary()
    assert s["total_rounds"] >= 0
    assert "recovery_chains" in s
    assert "signals" in s
    assert "tool_result_matrix" in s


# ── 空日志诊断 ──

def test_empty_log_diagnosis():
    """空日志诊断不报错。"""
    log = _make_log_with_events([])
    d = EventDiagnostics(log)
    s = d.diagnose()
    assert s.total_rounds == 0
    assert s.total_failures == 0
    assert s.blind_retries == 0
    assert len(s.recovery_chains) == 0
    assert len(s.signals) == 0


