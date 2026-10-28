"""测试 TaskRunner ABC 插件化适配器抽象 — 移植-P0 模块1"""

import sys
from pathlib import Path
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

import pytest
from adapters.task_runner import TaskInput, TaskResult, TaskRunner, BacktestRunner


# ── 自定义 TaskRunner 子类 — 验证 ABC 可扩展性 ──

class _NoopRunner(TaskRunner):
    """不做任何事的 Runner — 验证默认 validate 方法。"""
    def run(self, input: TaskInput) -> TaskResult:
        return TaskResult(status="completed", metrics={"trades_count": 0})


class _ValidatingRunner(TaskRunner):
    """带自定义验证的 Runner。"""
    def run(self, input: TaskInput) -> TaskResult:
        return TaskResult(status="completed",
                          metrics={"trades_count": len(input.signals or [])})

    def validate_input(self, signals: list[dict]) -> list[dict]:
        return [s for s in signals if s.get("valid", True)]

    def validate_output(self, result: TaskResult) -> bool:
        return result.metrics.get("trades_count", 0) >= 2


class _AlwaysErrorRunner(TaskRunner):
    """总是返回 error 的 Runner。"""
    def run(self, input: TaskInput) -> TaskResult:
        return TaskResult(status="error", errors=[{
            "signature": "always_fails",
            "params_snapshot": {},
            "fix_recipe": "这个 Runner 总是失败",
            "evidence": "测试用",
        }])


# ── ABC 可实例化测试 ──

def test_cannot_instantiate_abc():
    """TaskRunner ABC 不可直接实例化。"""
    with pytest.raises(TypeError):
        TaskRunner()


def test_subclass_instantiable():
    """子类可正常实例化。"""
    runner = _NoopRunner()
    assert isinstance(runner, TaskRunner)


# ── 默认 validate 方法测试 ──

def test_default_validate_input_passthrough():
    """默认 validate_input 透传信号。"""
    runner = _NoopRunner()
    signals = [{"signal_pattern": "test"}]
    assert runner.validate_input(signals) == signals


def test_default_validate_output_completed():
    """默认 validate_output: 未验证 completed 不能提升为业务成功。"""
    runner = _NoopRunner()
    assert not runner.validate_output(TaskResult(status="completed"))
    assert runner.validate_output(TaskResult(
        status="completed", output={"status": "valid"},
        business={"status": "passed"}))
    assert not runner.validate_output(TaskResult(status="error"))


# ── 自定义 validate 测试 ──

def test_custom_validate_input_filters_invalid():
    """自定义 validate_input 过滤 valid=False 的信号。"""
    runner = _ValidatingRunner()
    signals = [
        {"signal_pattern": "a", "valid": True},
        {"signal_pattern": "b", "valid": False},
        {"signal_pattern": "c", "valid": True},
    ]
    result = runner.validate_input(signals)
    assert len(result) == 2
    assert all(s["valid"] for s in result)


def test_custom_validate_output_trades_threshold():
    """自定义 validate_output 检查 trades_count ≥ 2。"""
    runner = _ValidatingRunner()
    assert not runner.validate_output(
        TaskResult(status="completed", metrics={"trades_count": 0}))
    assert not runner.validate_output(
        TaskResult(status="completed", metrics={"trades_count": 1}))
    assert runner.validate_output(
        TaskResult(status="completed", metrics={"trades_count": 2}))


# ── BacktestRunner validate 测试 ──

def test_backtest_runner_validate_input_filters_missing_pattern():
    """BacktestRunner.validate_input 过滤缺少 signal_pattern 的信号。"""
    runner = BacktestRunner()
    signals = [
        {"signal_pattern": "MA_cross"},
        {"no_pattern": "missing"},
        {},
        {"signal_pattern": "Fib_retrace"},
        "not_a_dict",
    ]
    result = runner.validate_input(signals)
    assert len(result) == 2
    assert result[0]["signal_pattern"] == "MA_cross"
    assert result[1]["signal_pattern"] == "Fib_retrace"


def test_backtest_runner_validate_input_empty():
    """空信号列表返回空。"""
    runner = BacktestRunner()
    assert runner.validate_input([]) == []


def test_backtest_runner_validate_output_no_trades():
    """0 trades 时 validate_output 返回 False。"""
    runner = BacktestRunner()
    assert not runner.validate_output(
        TaskResult(status="completed", metrics={"trades_count": 0}))


def test_backtest_runner_validate_output_error_status():
    """error 状态直接返回 False。"""
    runner = BacktestRunner()
    assert not runner.validate_output(
        TaskResult(status="error", metrics={"trades_count": 10}))


def test_backtest_runner_validate_output_valid():
    """completed + trades > 0 → True。"""
    runner = BacktestRunner()
    assert runner.validate_output(
        TaskResult(status="completed", metrics={"trades_count": 5},
                   output={"status": "valid"}, business={"status": "passed"}))


# ── 错误状态处理 ──

def test_error_runner_returns_error():
    """总是失败的 Runner 正确返回 error 状态。"""
    runner = _AlwaysErrorRunner()
    result = runner.run(TaskInput(task_type="test"))
    assert result.status == "error"
    assert len(result.errors) == 1
    assert result.errors[0]["signature"] == "always_fails"


# ── TaskInput / TaskResult dataclass 测试 ──

def test_task_input_defaults():
    """TaskInput 默认字段。"""
    ti = TaskInput(task_type="test")
    assert ti.task_type == "test"
    assert ti.params == {}
    assert ti.signals is None
    assert ti.context == {}


def test_task_result_defaults():
    """TaskResult 默认字段。"""
    tr = TaskResult(status="completed")
    assert tr.status == "completed"
    assert tr.rounds == []
    assert tr.errors == []
    assert tr.metrics == {}
