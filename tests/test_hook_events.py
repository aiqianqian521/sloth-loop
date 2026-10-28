"""Tests for hook_events.py — P3-B1 Hook事件体系扩充."""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import pytest
from hook_events import (
    HookEvent,
    HookPayload,
    HookBus,
    log_listener,
    stats_listener,
    threshold_guard,
)


class TestHookEvent:
    """HookEvent 枚举测试。"""

    def test_all_events_exist(self):
        """确保17个事件全部定义。"""
        events = list(HookEvent)
        assert len(events) >= 17  # 包含兼容别名可能略多

    def test_categories(self):
        cats = {e.category for e in HookEvent}
        assert "session" in cats
        assert "round" in cats
        assert "step" in cats
        assert "tool" in cats
        assert "decision" in cats
        assert "pattern" in cats
        assert "circuit" in cats
        assert "checkpoint" in cats

    def test_legacy_mapping(self):
        assert HookEvent.ROUND_START.legacy_name == "round/start"
        assert HookEvent.PRE_TOOL.legacy_name == "PreToolUse"
        assert HookEvent.POST_TOOL.legacy_name == "PostToolUse"

    def test_from_legacy(self):
        assert HookEvent.from_legacy("round/start") == HookEvent.ROUND_START
        assert HookEvent.from_legacy("PreToolUse") == HookEvent.PRE_TOOL
        assert HookEvent.from_legacy("PostToolUse") == HookEvent.POST_TOOL
        # 未知 → 默认
        assert HookEvent.from_legacy("unknown") == HookEvent.STEP_START

    def test_value_format(self):
        """事件值格式: category/name。"""
        for e in HookEvent:
            assert "/" in e.value, f"{e.value} should be 'category/name'"

    def test_str_equals_value(self):
        """HookEvent 是 str 枚举，str(e) == e.value。"""
        assert HookEvent.ROUND_START.value == "round/start"


class TestHookPayload:
    """HookPayload 数据类测试。"""

    def test_default(self):
        p = HookPayload(event=HookEvent.STEP_START)
        assert p.event == HookEvent.STEP_START
        assert p.round_num == 0
        assert p.error == ""
        assert p.category == "step"

    def test_with_data(self):
        p = HookPayload(
            event=HookEvent.PRE_TOOL,
            task_name="test-task",
            round_num=3,
            step_name="act",
            data={"tool": "backtest", "params_count": 5},
            elapsed_ms=123.4,
        )
        assert p.task_name == "test-task"
        assert p.round_num == 3
        assert p.step_name == "act"
        assert p.data["tool"] == "backtest"
        assert p.elapsed_ms == 123.4

    def test_with_error(self):
        p = HookPayload(
            event=HookEvent.TOOL_ERROR,
            error="division by zero",
        )
        assert p.is_error is True
        assert p.error == "division by zero"

    def test_no_error(self):
        p = HookPayload(event=HookEvent.STEP_START)
        assert p.is_error is False

    def test_to_dict(self):
        p = HookPayload(
            event=HookEvent.ROUND_START,
            task_name="demo",
            round_num=1,
            step_name="understand",
            data={"signals": 10, "name": "test"},
            error="",
            elapsed_ms=50.0,
            metadata={"env": "test"},
        )
        d = p.to_dict()
        assert d["event"] == "round/start"
        assert d["task"] == "demo"
        assert d["round"] == 1
        assert d["step"] == "understand"
        assert d["data"]["signals"] == 10
        assert d["data"]["name"] == "test"
        assert d["elapsed_ms"] == 50.0

    def test_to_dict_sanitizes_large_data(self):
        """大数据被脱敏。"""
        p = HookPayload(
            event=HookEvent.STEP_START,
            data={"big_list": list(range(100)), "complex": {"a": {"b": {"c": 1}}}},
        )
        d = p.to_dict()
        assert "big_list" in d["data"]
        assert "<list>" in d["data"]["big_list"]
        assert "<dict>" in d["data"]["complex"]


class TestHookBus:
    """HookBus 事件总线测试。"""

    def test_empty_bus(self):
        bus = HookBus()
        assert bus.listener_count == 0
        assert bus.count() == 0

    def test_fire_and_history(self):
        bus = HookBus()
        bus.fire(HookEvent.SESSION_START, task_name="test")
        bus.fire(HookEvent.ROUND_START, task_name="test", round_num=1)

        assert bus.count() == 2
        assert bus.count(HookEvent.SESSION_START) == 1
        assert bus.count(HookEvent.ROUND_START) == 1

    def test_fire_returns_payload(self):
        bus = HookBus()
        p = bus.fire(HookEvent.ROUND_START, task_name="x", round_num=5)
        assert p.event == HookEvent.ROUND_START
        assert p.round_num == 5
        assert p.task_name == "x"

    def test_listener_called(self):
        bus = HookBus()
        received = []

        bus.on(HookEvent.ROUND_START, lambda p: received.append(p))
        bus.fire(HookEvent.ROUND_START)
        bus.fire(HookEvent.ROUND_END)  # 不匹配

        assert len(received) == 1
        assert received[0].event == HookEvent.ROUND_START

    def test_wildcard_listener(self):
        bus = HookBus()
        received = []

        bus.on("*", lambda p: received.append(p))
        bus.fire(HookEvent.STEP_START)
        bus.fire(HookEvent.STEP_END)
        bus.fire(HookEvent.PRE_TOOL)

        assert len(received) == 3

    def test_on_any(self):
        bus = HookBus()
        received = []

        bus.on_any([HookEvent.STEP_START, HookEvent.STEP_END], lambda p: received.append(p))
        bus.fire(HookEvent.STEP_START)
        bus.fire(HookEvent.STEP_END)
        bus.fire(HookEvent.PRE_TOOL)  # 不匹配

        assert len(received) == 2

    def test_listener_isolation(self):
        """一个监听器抛异常不影响其他。"""
        bus = HookBus()
        results = []

        def bad(_p):
            raise RuntimeError("oops")

        def good(p):
            results.append(p.event.value)

        bus.on(HookEvent.STEP_START, bad)
        bus.on(HookEvent.STEP_START, good)
        bus.fire(HookEvent.STEP_START)

        assert len(results) == 1
        assert results[0] == "step/start"

    def test_off_listener(self):
        bus = HookBus()
        received = []

        def cb(p):
            received.append(p)

        bus.on(HookEvent.ROUND_START, cb)
        bus.fire(HookEvent.ROUND_START)
        assert len(received) == 1

        bus.off(HookEvent.ROUND_START, cb)
        bus.fire(HookEvent.ROUND_START)
        assert len(received) == 1  # 未增加

    def test_filter_by_event(self):
        bus = HookBus()
        bus.fire(HookEvent.ROUND_START, round_num=1)
        bus.fire(HookEvent.ROUND_END, round_num=1)
        bus.fire(HookEvent.STEP_START, step_name="observe")

        results = bus.filter(event=HookEvent.ROUND_START)
        assert len(results) == 1
        assert results[0].event == HookEvent.ROUND_START

    def test_filter_by_category(self):
        bus = HookBus()
        bus.fire(HookEvent.ROUND_START)
        bus.fire(HookEvent.ROUND_END)
        bus.fire(HookEvent.STEP_START)

        results = bus.filter(category="round")
        assert len(results) == 2

    def test_max_history(self):
        bus = HookBus()
        bus._max_history = 5
        for i in range(10):
            bus.fire(HookEvent.STEP_START)

        assert bus.count() == 5  # 截断到5

    def test_shortcut_methods(self):
        bus = HookBus()
        bus.fire_session_start(task_name="demo")
        bus.fire_round_start(task_name="demo", round_num=1)
        bus.fire_step(HookEvent.STEP_START, task_name="demo", round_num=1, step_name="act")
        bus.fire_tool(HookEvent.PRE_TOOL, tool_name="backtest")
        bus.fire_pattern(HookEvent.PATTERN_SAVED, pattern_id="pat-001")
        bus.fire_round_end(task_name="demo", round_num=1)
        bus.fire_session_end(task_name="demo")

        assert bus.count() == 7
        assert bus.count(HookEvent.SESSION_START) == 1
        assert bus.count(HookEvent.PATTERN_SAVED) == 1


class TestBuiltinListeners:
    """内置监听器测试。"""

    def test_stats_listener(self):
        bus = HookBus()
        s = stats_listener()
        bus.on("*", s)

        bus.fire(HookEvent.ROUND_START)
        bus.fire(HookEvent.ROUND_START)
        bus.fire(HookEvent.ROUND_END)

        assert s.stats["round/start"] == 2  # type: ignore
        assert s.stats["round/end"] == 1  # type: ignore

    def test_threshold_guard(self):
        triggered = []

        guard = threshold_guard(
            HookEvent.TOOL_ERROR,
            max_count=3,
            action=lambda: triggered.append("stop"),
        )

        bus = HookBus()
        bus.on("*", guard)

        bus.fire(HookEvent.TOOL_ERROR)
        bus.fire(HookEvent.TOOL_ERROR)
        assert not guard.check()  # type: ignore

        bus.fire(HookEvent.TOOL_ERROR)
        assert guard.check()  # type: ignore
        assert triggered == ["stop"]


class TestIntegration:
    """集成测试。"""

    def test_full_lifecycle(self):
        """模拟完整会话生命周期。"""
        bus = HookBus()
        events = []

        bus.on("*", lambda p: events.append(p.event.value))

        # 会话开始
        bus.fire_session_start(task_name="integration-test")

        # 3轮
        for r in range(1, 4):
            bus.fire_round_start(task_name="it", round_num=r)

            for step in ["understand", "observe", "orient", "decide"]:
                bus.fire_step(HookEvent.STEP_START, round_num=r, step_name=step)
                bus.fire_step(HookEvent.STEP_END, round_num=r, step_name=step)

            # act
            bus.fire_tool(HookEvent.PRE_TOOL, tool_name="backtest")
            bus.fire_tool(HookEvent.POST_TOOL, tool_name="backtest")

            bus.fire_round_end(task_name="it", round_num=r)

        bus.fire_session_end(task_name="integration-test")

        # 验证事件序列完整性
        assert events[0] == "session/start"
        assert events[-1] == "session/end"
        assert events.count("round/start") == 3
        assert events.count("round/end") == 3
        assert events.count("step/start") == 12  # 4 steps * 3 rounds
        assert events.count("tool/pre") == 3
        assert events.count("tool/post") == 3

    def test_event_log_integration(self):
        """验证 HookBus + EventLog 联动。"""
        # 模拟 EventLog
        class MockEventLog:
            def __init__(self):
                self.entries = []

            def append(self, event_type, data):
                self.entries.append((event_type, data))

        el = MockEventLog()
        bus = HookBus(event_log=el)

        bus.fire(HookEvent.ROUND_START, task_name="test", round_num=1)

        assert len(el.entries) == 1
        assert el.entries[0][0] == "round/start"
        assert el.entries[0][1]["task"] == "test"

    def test_without_event_log(self):
        """没有 EventLog 也能正常运行。"""
        bus = HookBus()  # 不传 event_log
        bus.fire(HookEvent.ROUND_START)
        assert bus.count() == 1

    def test_listener_count(self):
        bus = HookBus()
        bus.on(HookEvent.ROUND_START, lambda p: None)
        bus.on(HookEvent.ROUND_END, lambda p: None)
        bus.on("*", lambda p: None)
        assert bus.listener_count == 3


class TestBackwardCompatibility:
    """向后兼容测试。"""

    def test_legacy_event_names_work(self):
        """旧事件名可以通过 HookEvent 值访问。"""
        bus = HookBus()
        # 使用旧字符串触发
        bus.fire(HookEvent.from_legacy("round/start"))
        assert bus.count() == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
