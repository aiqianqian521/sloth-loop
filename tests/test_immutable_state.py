"""Tests for immutable_state.py — P2-N6 Immutable State Transitions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure sloth_engine is importable
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import pytest
from immutable_state import (
    LoopState,
    StateReducer,
    StateDiff,
    StateHistory,
    compute_diff,
)


class TestLoopState:
    """LoopState 不可变数据类测试。"""

    def test_create_default(self):
        s = LoopState()
        assert s.round_num == 0
        assert s.run_id == ""
        assert isinstance(s.created_at, str)

    def test_from_config(self):
        cfg = {
            "max_rounds": 100,
            "no_progress_stop": 10,
            "max_seconds": 3600,
            "error_stop": 5,
            "meta_every": 20,
            "enable_ooda": True,
            "budget_hard": {"max_rounds": 100, "max_consecutive_failures": 3},
        }
        s = LoopState.from_config(cfg)
        assert s.max_rounds == 100
        assert s.no_progress_stop == 10
        assert s.max_seconds == 3600
        assert s.error_stop == 5
        assert s.meta_every == 20
        assert s.enable_ooda is True
        assert s.budget_hard == {"max_rounds": 100, "max_consecutive_failures": 3}
        # 来源标注
        assert s._sources.get("max_rounds") == "init"

    def test_is_frozen(self):
        """LoopState 必须是不可变的。"""
        s = LoopState(round_num=1)
        with pytest.raises(Exception):
            s.round_num = 2  # type: ignore

    def test_with_update_creates_new_instance(self):
        s1 = LoopState(round_num=1, run_id="r1")
        s2 = s1.with_update(round_num=2)

        # 新实例
        assert s2 is not s1
        assert s1.round_num == 1
        assert s2.round_num == 2
        # 未被覆盖的字段继承
        assert s2.run_id == "r1"
        # 来源标注
        assert s2._sources["round_num"] == "calc"
        assert s2._sources["run_id"] == "prev"

    def test_with_update_partial(self):
        s1 = LoopState(max_rounds=50, no_progress_stop=5)
        s2 = s1.with_update(decision="apply", new_failures=3)

        assert s2.decision == "apply"
        assert s2.new_failures == 3
        assert s2.max_rounds == 50  # 继承
        assert s2.no_progress_stop == 5  # 继承

    def test_trace_changes(self):
        s1 = LoopState(round_num=1, consecutive_errors=0, decision="")
        s2 = s1.with_update(round_num=2, consecutive_errors=1, decision="apply")

        diffs = s2.trace_changes(s1)
        assert len(diffs) == 3
        assert diffs["round_num"] == (1, 2, "calc")
        assert diffs["consecutive_errors"] == (0, 1, "calc")
        assert diffs["decision"] == ("", "apply", "calc")

    def test_trace_changes_no_diff(self):
        s1 = LoopState(round_num=1)
        s2 = s1.with_update()
        diffs = s2.trace_changes(s1)
        assert len(diffs) == 0

    def test_to_dict(self):
        s = LoopState(
            run_id="test-001",
            round_num=5,
            decision="apply",
            new_failures=2,
            new_successes=8,
        )
        d = s.to_dict()
        assert d["run_id"] == "test-001"
        assert d["round_num"] == 5
        assert d["decision"] == "apply"
        assert d["new_failures"] == 2
        assert d["new_successes"] == 8
        assert "_sources" not in d  # 内部字段不入序列化


class TestStateReducer:
    """StateReducer 测试。"""

    def test_reduce_identity(self):
        """不传任何覆盖 -> 状态继承。"""
        prev = LoopState.from_config({
            "max_rounds": 100,
            "no_progress_stop": 10,
            "error_stop": 5,
            "enable_ooda": True,
        }).with_update(run_id="r1", started_at=1000.0)

        nxt = StateReducer.reduce(prev)
        assert nxt.max_rounds == 100
        assert nxt.no_progress_stop == 10
        assert nxt.run_id == "r1"
        assert nxt.started_at == 1000.0
        assert nxt.round_num == 0  # 默认值

    def test_reduce_round_progress(self):
        """折叠一轮结果。"""
        prev = LoopState.from_config({
            "max_rounds": 100,
            "no_progress_stop": 10,
            "error_stop": 5,
        }).with_update(
            run_id="r1",
            started_at=1000.0,
            round_num=1,
            total_rounds=1,
            cursor=50,
        )

        # 模拟第2轮结果
        nxt = StateReducer.reduce(
            prev,
            round_num=2,
            cursor=100,
            signals_input=10,
            signals_excluded=3,
            decision="apply",
            progressed=True,
            new_failures=1,
            new_successes=3,
            last_progress_round=2,
            consecutive_errors=0,
        )

        assert nxt.round_num == 2
        assert nxt.total_rounds == 2
        assert nxt.cursor == 100
        assert nxt.signals_input == 10
        assert nxt.signals_excluded == 3
        assert nxt.decision == "apply"
        assert nxt.progressed is True
        assert nxt.new_failures == 1
        assert nxt.new_successes == 3
        assert nxt.last_progress_round == 2
        assert nxt.consecutive_errors == 0
        # 配置继承
        assert nxt.max_rounds == 100
        assert nxt.run_id == "r1"

    def test_reduce_error_accumulation(self):
        """错误轮 → consecutive_errors 累加。"""
        prev = LoopState.from_config({
            "max_rounds": 100,
            "no_progress_stop": 10,
            "error_stop": 5,
        }).with_update(
            run_id="r1",
            started_at=1000.0,
            round_num=3,
            consecutive_errors=5,
        )

        nxt = StateReducer.reduce(
            prev,
            round_num=4,
            execution_failed=True,
            backtest_status="error",
            backtest_error="division by zero",
            consecutive_errors=6,
        )

        assert nxt.round_num == 4
        assert nxt.consecutive_errors == 6
        assert nxt.execution_failed is True
        assert nxt.backtest_status == "error"

    def test_reduce_stop_conditions(self):
        """停止条件正确传递。"""
        prev = LoopState.from_config({
            "max_rounds": 100,
            "no_progress_stop": 10,
            "error_stop": 5,
        }).with_update(run_id="r1", round_num=5)

        nxt = StateReducer.reduce(
            prev,
            round_num=6,
            stop_reason="circuit breaker OPEN",
            circuit_open=True,
            l2_health_score=0.1,
            l2_stop_signal="escalate",
        )

        assert nxt.stop_reason == "circuit breaker OPEN"
        assert nxt.circuit_open is True
        assert nxt.l2_health_score == 0.1
        assert nxt.l2_stop_signal == "escalate"

    def test_reduce_prev_round_context(self):
        """跨轮上下文传递。"""
        prev = LoopState.from_config({
            "max_rounds": 100,
            "no_progress_stop": 10,
            "error_stop": 5,
        }).with_update(run_id="r1")

        ctx = {"prev_act_status": "error", "prev_act_error": "timeout"}
        nxt = StateReducer.reduce(prev, round_num=1, prev_round_ctx=ctx)
        assert nxt.prev_round_ctx == ctx

    def test_init_from_config(self):
        """init 快捷方法。"""
        cfg = {
            "max_rounds": 200,
            "no_progress_stop": 20,
            "enable_ooda": False,
        }
        s = StateReducer.init(cfg, run_id="init-001", started_at=500.0)
        assert s.max_rounds == 200
        assert s.run_id == "init-001"
        assert s.started_at == 500.0
        assert s.enable_ooda is False


class TestComputeDiff:
    """compute_diff 差异分析测试。"""

    def test_single_field_diff(self):
        s1 = LoopState(round_num=1)
        s2 = s1.with_update(round_num=2)

        diffs = compute_diff(s1, s2)
        assert len(diffs) == 1
        d = diffs[0]
        assert d.field_name == "round_num"
        assert d.prev_value == 1
        assert d.curr_value == 2
        assert d.source == "calc"

    def test_multiple_field_diff(self):
        s1 = LoopState.from_config({"max_rounds": 100, "no_progress_stop": 10})
        s2 = StateReducer.reduce(
            s1,
            round_num=3,
            decision="apply",
            new_failures=5,
            new_successes=10,
            progressed=True,
        )

        diffs = compute_diff(s1, s2)
        # round_num, total_rounds, decision, new_failures, new_successes, progressed, +sources
        diff_names = {d.field_name for d in diffs}
        assert "round_num" in diff_names
        assert "decision" in diff_names
        assert "new_failures" in diff_names
        assert "new_successes" in diff_names
        assert "progressed" in diff_names

    def test_no_diff(self):
        s1 = LoopState(round_num=1)
        s2 = LoopState(round_num=1)
        diffs = compute_diff(s1, s2)
        assert len(diffs) == 0

    def test_round_increment_diff(self):
        """逐轮增量测试。"""
        states = []
        cfg = {"max_rounds": 100, "no_progress_stop": 10, "error_stop": 5}
        prev = StateReducer.init(cfg, run_id="chain-test", started_at=0)

        for r in range(1, 6):
            curr = StateReducer.reduce(
                prev,
                round_num=r,
                cursor=r * 10,
                signals_input=r * 5,
                decision="apply" if r % 2 == 0 else "reject",
                progressed=r % 2 == 0,
                new_failures=1 if r == 3 else 0,
                new_successes=3,
            )
            diffs = compute_diff(prev, curr)
            # 每轮至少有 round_num / cursor / signals_input / decision / progressed 变化
            assert len(diffs) >= 3, f"Round {r} diffs too few: {len(diffs)}"
            states.append(curr)
            prev = curr

        assert len(states) == 5
        # 最后一轮
        assert states[-1].round_num == 5
        assert states[-1].cursor == 50


class TestStateHistory:
    """StateHistory 状态历史管理器测试。"""

    def test_append_and_latest(self):
        hist = StateHistory(max_size=100)
        s1 = LoopState(round_num=1)
        s2 = LoopState(round_num=2)

        hist.append(s1)
        hist.append(s2)

        assert hist.count == 2
        assert hist.latest.round_num == 2

    def test_max_size_truncation(self):
        hist = StateHistory(max_size=3)
        for i in range(10):
            hist.append(LoopState(round_num=i))

        assert hist.count == 3
        assert hist.latest.round_num == 9

    def test_replay(self):
        hist = StateHistory()
        for i in range(5):
            hist.append(LoopState(round_num=i))

        replay = hist.replay(1, 4)
        assert len(replay) == 3
        assert [s.round_num for s in replay] == [1, 2, 3]

    def test_field_trace(self):
        hist = StateHistory()
        for i in range(5):
            hist.append(LoopState(round_num=i, decision="apply" if i % 2 == 0 else "reject"))

        trace = hist.field_trace("decision")
        assert len(trace) == 5
        assert trace[0] == (0, "apply")
        assert trace[1] == (1, "reject")

    def test_find_first_where(self):
        hist = StateHistory()
        hist.append(LoopState(round_num=0, decision="reject"))
        hist.append(LoopState(round_num=1, decision="reject"))
        hist.append(LoopState(round_num=2, decision="apply"))

        found = hist.find_first_where("decision", "apply")
        assert found is not None
        assert found.round_num == 2

    def test_find_first_where_not_found(self):
        hist = StateHistory()
        hist.append(LoopState(round_num=0))
        found = hist.find_first_where("decision", "nonexistent")
        assert found is None

    def test_iteration(self):
        hist = StateHistory()
        for i in range(3):
            hist.append(LoopState(round_num=i))

        rounds = [s.round_num for s in hist]
        assert rounds == [0, 1, 2]

    def test_indexing(self):
        hist = StateHistory()
        for i in range(5):
            hist.append(LoopState(round_num=i))

        assert hist[0].round_num == 0
        assert hist[-1].round_num == 4


    def test_to_jsonl_is_valid_json_even_with_quotes(self, tmp_path):
        """cycle-14: to_jsonl 必须产出真 JSON（旧实现 str(dict).replace 会破行）。"""
        import json

        hist = StateHistory()
        hist.append(LoopState(round_num=1, decision="it's fine — 中文"))
        out = tmp_path / "h.jsonl"
        hist.to_jsonl(out)

        lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["round_num"] == 1
        assert payload["decision"] == "it's fine — 中文"


class TestIntegration:
    """集成测试：模拟一个完整的 loop 周期。"""

    def test_full_loop_cycle(self):
        """模拟 3 轮 loop 的状态流转。"""
        cfg = {
            "max_rounds": 100,
            "no_progress_stop": 10,
            "max_seconds": 3600,
            "error_stop": 5,
            "meta_every": 10,
            "enable_ooda": True,
            "budget_hard": {"max_rounds": 100, "max_consecutive_failures": 3},
        }

        # 初始化
        state = StateReducer.init(cfg, run_id="full-cycle-001", started_at=0)
        hist = StateHistory()
        hist.append(state)

        # 模拟 3 轮
        import time
        for r in range(1, 4):
            started = time.time()

            # 本轮计算（模拟）
            signals_input = r * 5
            signals_excluded = max(0, r - 1)
            decision = "apply"
            progressed = True
            new_failures = 0
            new_successes = signals_input - signals_excluded
            backtest_status = "completed"

            state = StateReducer.reduce(
                state,
                round_num=r,
                cursor=r * 10,
                signals_input=signals_input,
                signals_excluded=signals_excluded,
                decision=decision,
                progressed=progressed,
                new_failures=new_failures,
                new_successes=new_successes,
                backtest_status=backtest_status,
            )

            # 验证每轮状态独立（不可变）
            if r >= 2:
                prev_state = hist[r - 1]
                # 前一轮的状态不应该被修改
                assert prev_state.round_num == r - 1
                # 当前状态是新实例
                assert state.round_num == r

            hist.append(state)

        # 最终验证
        assert hist.count == 4  # init + 3 rounds
        assert state.round_num == 3
        assert state.total_rounds == 3
        # 最后1轮：signals_input=15, signals_excluded=2, signals_generated=0（未设）
        assert state.signals_input == 15
        assert state.signals_excluded == 2

        # 回溯检查：第2轮状态未被后续修改
        round1_state = hist[1]
        assert round1_state.round_num == 1
        assert round1_state.signals_input == 5  # 仍然是第1轮的数据

    def test_state_isolation_across_rounds(self):
        """验证跨轮状态隔离——修改一轮不影响历史。"""
        cfg = {"max_rounds": 100, "no_progress_stop": 10, "error_stop": 5}
        state = StateReducer.init(cfg, run_id="iso-test")

        round1 = StateReducer.reduce(
            state, round_num=1, decision="apply", new_failures=0, progressed=True
        )

        round2 = StateReducer.reduce(
            round1, round_num=2, decision="reject", new_failures=1, progressed=False
        )

        # round1 不应被 round2 影响（不可变性验证）
        assert round1.decision == "apply"
        assert round1.new_failures == 0
        assert round1.progressed is True
        assert round1.round_num == 1

        # round2 有自己独立的值
        assert round2.decision == "reject"
        assert round2.new_failures == 1
        assert round2.progressed is False
        assert round2.round_num == 2

    def test_round_context_persistence(self):
        """跨轮上下文持续传递。"""
        cfg = {"max_rounds": 100, "no_progress_stop": 10, "error_stop": 5}
        state = StateReducer.init(cfg, run_id="ctx-test")

        # 第1轮：有错误
        ctx1 = {"prev_act_status": "error", "prev_act_error": "timeout"}
        state = StateReducer.reduce(state, round_num=1, prev_round_ctx=ctx1)
        assert state.prev_round_ctx == ctx1

        # 第2轮：错误恢复
        ctx2 = {"prev_act_status": "completed", "prev_act_error": ""}
        state = StateReducer.reduce(state, round_num=2, prev_round_ctx=ctx2)
        assert state.prev_round_ctx == ctx2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

