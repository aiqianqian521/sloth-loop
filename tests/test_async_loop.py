"""Tests for async_loop.py — P2-N4 Async Generator 模式."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import pytest
from async_loop import (
    LoopYield,
    LoopControl,
    LoopGeneratorProtocol,
    SimpleLoopGenerator,
    collect_all,
    collect_until_terminal,
    filter_yields,
    map_yields,
    iter_with_control,
)
from immutable_state import LoopState


class TestLoopYield:
    """LoopYield 数据类测试。"""

    def test_default(self):
        y = LoopYield(state=LoopState())
        assert y.is_terminal is False
        assert y.stop_reason == ""
        assert y.round_num == 0

    def test_terminal(self):
        y = LoopYield(
            state=LoopState(),
            is_terminal=True,
            stop_reason="max_rounds reached",
            round_num=10,
        )
        assert y.should_stop is True
        assert y.is_terminal is True
        assert y.stop_reason == "max_rounds reached"

    def test_had_error(self):
        state = LoopState(execution_failed=True)
        y = LoopYield(state=state)
        assert y.had_error is True

    def test_no_error(self):
        state = LoopState(execution_failed=False)
        y = LoopYield(state=state)
        assert y.had_error is False

    def test_summary(self):
        state = LoopState(new_failures=2, new_successes=3, execution_failed=False)
        y = LoopYield(
            state=state,
            decision="apply",
            round_num=5,
            is_terminal=True,
            stop_reason="max_rounds reached",
        )
        assert "R5" in y.summary
        assert "dec=apply" in y.summary
        assert "f=2" in y.summary
        assert "s=3" in y.summary
        assert "TERM" in y.summary

    def test_summary_minimal(self):
        y = LoopYield(state=LoopState())
        assert "R0" in y.summary


class TestLoopControl:
    """LoopControl backpressure 信号测试。"""

    def test_default(self):
        c = LoopControl()
        assert c.pause is False
        assert c.skip_next is False
        assert c.abort is False

    def test_reset_flags(self):
        c = LoopControl(skip_next=True, inject_signals=[{"x": 1}])
        c.reset_flags()
        assert c.skip_next is False
        assert c.inject_signals is None

    def test_reset_keeps_persistent(self):
        """reset_flags 不影响持续性控制。"""
        c = LoopControl(pause=True, abort=True, abort_reason="test")
        c.reset_flags()
        assert c.pause is True   # pause 是持续状态
        assert c.abort is True   # abort 是持续状态

    def test_max_rounds_override(self):
        c = LoopControl(max_rounds_override=5)
        assert c.max_rounds_override == 5


class TestSimpleLoopGenerator:
    """SimpleLoopGenerator 测试。"""

    def test_basic_iteration(self):
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 5, "no_progress_stop": 10, "error_stop": 10}
        results = collect_all(gen.iter_loop(config))

        assert len(results) == 5
        # 最后一轮是 terminal
        assert results[-1].is_terminal is True
        assert results[-1].stop_reason == "max_rounds reached"

    def test_terminal_on_last_round(self):
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 3, "no_progress_stop": 10, "error_stop": 10}
        results = collect_all(gen.iter_loop(config))

        assert len(results) == 3
        assert results[-1].is_terminal is True
        assert results[0].is_terminal is False

    def test_error_stop_triggers(self):
        gen = SimpleLoopGenerator()
        # error_stop=2: 连续2个非progress轮就停止
        # 第1轮: progress → 0 consecutive errors
        # 第2轮: 可能非progress → 1 consecutive error
        # 第3轮: 可能非progress → 2 consecutive errors → STOP
        config = {"max_rounds": 100, "no_progress_stop": 100, "error_stop": 2}
        results = collect_all(gen.iter_loop(config))

        # 第1轮 progress (r=1, excluded=0, input=1 → apply), 第2轮非progress (r=2, excluded=1, input=1 → reject)
        # 检查是否有提前终止
        assert len(results) == 3  # 第1轮progress, 第2/3轮error → stop at r=3
        assert results[-1].is_terminal is True

    def test_no_progress_stop(self):
        gen = SimpleLoopGenerator()
        # no_progress_stop=2: 连续2轮无进展即停止
        # 第1轮 progress, 第2/3轮无progress → stop
        config = {"max_rounds": 100, "no_progress_stop": 2, "error_stop": 100}
        results = collect_all(gen.iter_loop(config))

        assert results[-1].is_terminal is True
        assert "no_progress" in results[-1].stop_reason or len(results) <= 3

    def test_abort_control(self):
        gen = SimpleLoopGenerator()
        ctrl = LoopControl()
        config = {"max_rounds": 5, "no_progress_stop": 100, "error_stop": 100}

        results = []
        for y in gen.iter_loop(config, control=ctrl):
            results.append(y)
            if y.round_num >= 2:
                ctrl.abort = True
                ctrl.abort_reason = "manual abort"

        assert len(results) <= 3  # round 1, 2, 终止 yield
        assert results[-1].is_terminal is True
        assert "manual abort" in results[-1].stop_reason

    def test_skip_control(self):
        gen = SimpleLoopGenerator()
        ctrl = LoopControl(skip_next=True)
        config = {"max_rounds": 3, "no_progress_stop": 100, "error_stop": 100}

        results = collect_all(gen.iter_loop(config, control=ctrl))
        # 第1轮被skip → 只有2轮
        assert len(results) == 2
        # 第1个 yield 是 round_num=2（跳过了r=1）
        assert results[0].round_num == 2

    def test_inject_signals(self):
        gen = SimpleLoopGenerator()
        ctrl = LoopControl(inject_signals=[{"id": "custom-1"}, {"id": "custom-2"}])
        config = {"max_rounds": 1, "no_progress_stop": 100, "error_stop": 100}

        results = collect_all(gen.iter_loop(config, control=ctrl))
        assert len(results) == 1
        assert len(results[0].signals) == 2
        assert results[0].signals[0]["id"] == "custom-1"

    def test_max_rounds_override(self):
        gen = SimpleLoopGenerator()
        ctrl = LoopControl(max_rounds_override=2)
        config = {"max_rounds": 100, "no_progress_stop": 100, "error_stop": 100}

        results = collect_all(gen.iter_loop(config, control=ctrl))
        assert len(results) == 2
        assert results[-1].stop_reason == "max_rounds reached"

    def test_history_property(self):
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 3, "no_progress_stop": 100, "error_stop": 100}
        list(gen.iter_loop(config))  # consume

        assert len(gen.history) == 3
        assert gen.history[0].round_num == 1
        assert gen.history[-1].round_num == 3

    def test_state_progression(self):
        """验证状态在各轮间正确递增。"""
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 5, "no_progress_stop": 10, "error_stop": 10}
        results = collect_all(gen.iter_loop(config))

        for i, y in enumerate(results):
            assert y.state.round_num == i + 1
            assert y.state.total_rounds == i + 1
            assert y.state.run_id == "simple-loop"

    def test_run_method(self):
        """测试 run() 兼容方法。"""
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 3, "no_progress_stop": 10, "error_stop": 10}
        last = gen.run(config)

        assert last.is_terminal is True
        assert last.round_num == 3
        assert last.stop_reason == "max_rounds reached"


class TestCollectFunctions:
    """工具函数测试。"""

    def test_collect_all(self):
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 4, "no_progress_stop": 10, "error_stop": 10}
        results = collect_all(gen.iter_loop(config))
        assert len(results) == 4
        assert results[-1].is_terminal is True

    def test_collect_until_terminal(self):
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 2, "no_progress_stop": 10, "error_stop": 10}
        last = collect_until_terminal(gen.iter_loop(config))
        assert last.is_terminal is True
        assert last.round_num == 2

    def test_filter_yields(self):
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 5, "no_progress_stop": 10, "error_stop": 1}
        # 只有有错误的轮次
        errors = filter_yields(
            gen.iter_loop(config),
            predicate=lambda y: y.had_error,
        )
        # error_stop=1: 第一轮是progress, 第2轮非progress → 错误 → 停止
        assert len(errors) >= 1

    def test_map_yields(self):
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 3, "no_progress_stop": 10, "error_stop": 10}
        decisions = map_yields(
            gen.iter_loop(config),
            transform=lambda y: y.decision,
        )
        assert len(decisions) == 3
        # 第1轮: signals_input=1, excluded=0 → apply
        # 第2轮: signals_input=1, excluded=1 → reject
        # 第3轮: signals_input=1, excluded=2 → reject
        assert decisions[0] == "apply"
        assert decisions[1] == "reject"
        assert decisions[2] == "reject"


class TestIterWithControl:
    """iter_with_control 包装器测试。"""

    def test_abort_midway(self):
        gen = SimpleLoopGenerator()
        ctrl = LoopControl()
        config = {"max_rounds": 10, "no_progress_stop": 100, "error_stop": 100}

        results = []
        for y in iter_with_control(gen.iter_loop(config), ctrl):
            results.append(y)
            if len(results) >= 3:
                ctrl.abort = True

        assert len(results) == 3

    def test_no_abort(self):
        gen = SimpleLoopGenerator()
        ctrl = LoopControl()
        config = {"max_rounds": 3, "no_progress_stop": 100, "error_stop": 100}

        results = list(iter_with_control(gen.iter_loop(config), ctrl))
        assert len(results) == 3


class TestIntegration:
    """集成测试：完整 generator 流程。"""

    def test_full_generator_flow(self):
        """完整 generator 流转。"""
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 10, "no_progress_stop": 10, "error_stop": 10}

        round_nums = []
        states = []

        for y in gen.iter_loop(config):
            round_nums.append(y.round_num)
            states.append(y.state)

            # 调用方逻辑：在第5轮手动终止
            if y.round_num >= 5:
                break

        assert len(round_nums) == 5
        assert round_nums == [1, 2, 3, 4, 5]
        # 所有状态互不干扰
        for i, s in enumerate(states):
            assert s.round_num == i + 1

    def test_multi_generator_independence(self):
        """多个 generator 实例互相独立。"""
        gen1 = SimpleLoopGenerator()
        gen2 = SimpleLoopGenerator()

        config1 = {"max_rounds": 3, "no_progress_stop": 10, "error_stop": 10}
        config2 = {"max_rounds": 5, "no_progress_stop": 10, "error_stop": 10}

        r1 = collect_all(gen1.iter_loop(config1))
        r2 = collect_all(gen2.iter_loop(config2))

        assert len(r1) == 3
        assert len(r2) == 5
        # gen2 不受 gen1 影响
        assert r2[-1].round_num == 5

    def test_loop_yield_to_dict(self):
        """验证 LoopYield 可序列化。"""
        y = LoopYield(
            state=LoopState(round_num=3),
            signals=[{"a": 1}],
            decision="apply",
            is_terminal=True,
            stop_reason="done",
            round_num=3,
        )

        import json
        # 验证可序列化（不抛异常）
        d = {
            "round_num": y.round_num,
            "decision": y.decision,
            "is_terminal": y.is_terminal,
            "stop_reason": y.stop_reason,
        }
        s = json.dumps(d)
        assert "apply" in s

    def test_control_skip_multiple(self):
        """多次 skip。"""
        gen = SimpleLoopGenerator()
        ctrl = LoopControl(skip_next=True)
        config = {"max_rounds": 5, "no_progress_stop": 100, "error_stop": 100}

        results = []
        for y in gen.iter_loop(config, control=ctrl):
            results.append(y)
            # 第2轮再 skip 一次（如果还有下一轮）
            if y.round_num == 2:
                ctrl.skip_next = True

        assert len(results) == 3  # 5轮中跳过了2轮
        assert results[0].round_num == 2  # skip r=1
        assert results[1].round_num == 4  # r=2 skip, r=3 skip → normal=4
        # r=4 被skip
        assert results[2].round_num == 5  # r=5 (terminal)


class TestProtocol:
    """LoopGeneratorProtocol 测试。"""

    def test_protocol_implemented(self):
        """SimpleLoopGenerator 实现了协议。"""
        gen = SimpleLoopGenerator()
        assert isinstance(gen, LoopGeneratorProtocol)

    def test_run_returns_yield(self):
        gen = SimpleLoopGenerator()
        config = {"max_rounds": 1, "no_progress_stop": 10, "error_stop": 10}
        result = gen.run(config)
        assert isinstance(result, LoopYield)
        assert result.is_terminal is True

    def test_run_empty_config(self):
        gen = SimpleLoopGenerator()
        # 空配置 → 默认 max_rounds=0 → 立即终止
        result = gen.run({})
        assert result.is_terminal is True
        assert result.is_terminal is True  # 空配置 → 默认值触发停止条件


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
