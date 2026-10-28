"""G-5 (cycle-10): step-exception-policy wiring contract.

The distilled policy (sloth_engine/step_exception_policy.py) must be reachable
from a REAL single-step call point, and the wiring must be additive: the
documented default (a single attempt that re-raises) has to leave the legacy
result contract byte-identical, while an injected policy actually delivers
retry / timeout / fallback semantics.

Wiring points under test:
  * adapters.task_runner.BacktestRunner.run  (the Act call point used by
    orchestrator.py and ooda_pipeline.py)
  * tool_pipeline.ToolPipeline.execute step 10 (tool execution)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import adapters.backtest_adapter as bt  # noqa: E402
from adapters.backtest_adapter import configure  # noqa: E402
from adapters.task_runner import BacktestRunner, TaskInput  # noqa: E402
from step_exception_policy import ErrorProcessType, ExceptionPolicy  # noqa: E402
from runtime_exec import local_exec_gate  # noqa: E402
from tool_pipeline import ToolPipeline  # noqa: E402

SIGNALS = [{"signal_pattern": "g5-step"}]


@pytest.fixture()
def bt_settings(tmp_path):
    return configure({"script": "backtest/mock_backtest.py"}, ROOT,
                     io_dir=tmp_path / "io")


def _settings_dict(settings):
    return {"script": settings.script, "python": settings.python,
            "cwd": settings.cwd, "input_path": settings.input_path,
            "output_path": settings.output_path}


def _boom(exc):
    def _raise(*_a, **_kw):
        raise exc

    return _raise


# ---- BacktestRunner wiring -------------------------------------------------

def test_default_policy_object_is_single_attempt_throw():
    assert BacktestRunner(None).policy == ExceptionPolicy()
    assert BacktestRunner(None).policy.max_attempts == 1


def test_default_policy_keeps_legacy_success_result_shape(bt_settings):
    runner = BacktestRunner(_settings_dict(bt_settings), exec_gate=local_exec_gate())
    res = runner.run(TaskInput(task_type="backtest", signals=SIGNALS))
    assert res.status == "completed"
    assert res.execution["status"] == "succeeded"
    assert res.output["status"] == "valid"
    # Only a genuine retry records the observability key, so the single-attempt
    # default stays byte-identical to the pre-G-5 contract.
    assert "step_attempts" not in res.provenance


def test_default_policy_still_reraises_as_error_result(bt_settings, monkeypatch):
    calls = {"n": 0}

    def boom(*_a, **_kw):
        calls["n"] += 1
        raise RuntimeError("g5 boom")

    monkeypatch.setattr(bt, "run_backtest", boom)
    runner = BacktestRunner(_settings_dict(bt_settings))
    res = runner.run(TaskInput(task_type="backtest", signals=SIGNALS))
    assert calls["n"] == 1
    assert res.status == "error"
    assert res.execution["status"] == "failed"
    assert res.errors[0]["signature"] == "backtest_exception"


def test_retry_policy_recovers_and_records_attempts(bt_settings, monkeypatch):
    real = bt.run_backtest
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("g5 transient")
        return real(*a, **k)

    monkeypatch.setattr(bt, "run_backtest", flaky)
    runner = BacktestRunner(_settings_dict(bt_settings),
                            policy=ExceptionPolicy(max_retry=1),
                            exec_gate=local_exec_gate())
    res = runner.run(TaskInput(task_type="backtest", signals=SIGNALS))
    assert calls["n"] == 2
    assert res.status == "completed"
    assert res.provenance["step_attempts"] == 2


def test_exhausted_throw_policy_still_raises_into_error_result(bt_settings, monkeypatch):
    calls = {"n": 0}

    def boom(*_a, **_kw):
        calls["n"] += 1
        raise ValueError("g5 always")

    monkeypatch.setattr(bt, "run_backtest", boom)
    runner = BacktestRunner(_settings_dict(bt_settings),
                            policy=ExceptionPolicy(max_retry=2))
    res = runner.run(TaskInput(task_type="backtest", signals=SIGNALS))
    assert calls["n"] == 3                      # max_retry + 1 attempts
    assert res.status == "error"


def test_return_default_fallback_marks_success_without_business_success(
        bt_settings, monkeypatch):
    monkeypatch.setattr(bt, "run_backtest", _boom(ValueError("g5 hard fail")))
    runner = BacktestRunner(
        _settings_dict(bt_settings),
        policy=ExceptionPolicy(max_retry=1,
                               process_type=ErrorProcessType.RETURN_DEFAULT,
                               data_on_err={"trades": []}))
    res = runner.run(TaskInput(task_type="backtest", signals=SIGNALS))
    assert res.status == "completed"                    # coze isSuccess marker
    assert res.execution["code"] == "step_policy_fallback"
    assert res.execution["route"] == "return_default"
    assert res.execution["attempts"] == 2
    assert res.execution["is_success"] is True
    assert res.output["status"] == "not_verified"
    assert res.business["status"] == "not_evaluated"
    assert res.errors[0]["signature"] == "backtest_step_policy_fallback:return_default"
    assert res.raw_output == {"trades": []}
    assert runner.validate_output(res) is False         # never a business success


def test_exception_branch_fallback_keeps_empty_value(bt_settings, monkeypatch):
    monkeypatch.setattr(bt, "run_backtest", _boom(RuntimeError("g5 branch")))
    runner = BacktestRunner(
        _settings_dict(bt_settings),
        policy=ExceptionPolicy(process_type=ErrorProcessType.EXCEPTION_BRANCH))
    res = runner.run(TaskInput(task_type="backtest", signals=SIGNALS))
    assert res.status == "completed"
    assert res.execution["route"] == "exception_branch"
    assert res.execution["attempts"] == 1
    assert res.raw_output is None
    assert runner.validate_output(res) is False


# ---- ToolPipeline step-10 wiring ------------------------------------------

class _Tool:
    input_schema = {"required": []}

    def __init__(self, handler):
        self.handler = handler


class _Registry:
    def __init__(self, tool):
        self._tools = {"t": tool}


def _pipeline(handler):
    return ToolPipeline(_Registry(_Tool(handler)))


def test_tool_pipeline_default_policy_is_single_attempt():
    def boom(_params):
        raise RuntimeError("g5 tool boom")

    res = _pipeline(boom).execute("t", {})
    assert res.status == "error"
    assert res.attempts == 1
    assert res.route == ""
    assert res.to_dict()["attempts"] == 1
    assert res.to_dict()["route"] == ""


def test_tool_pipeline_retries_then_succeeds():
    calls = {"n": 0}

    def flaky(_params):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("g5 tool transient")
        return {"ok": True}

    res = _pipeline(flaky).execute("t", {},
                                   policy=ExceptionPolicy(max_retry=2))
    assert calls["n"] == 3
    assert res.status == "completed"
    assert res.result == {"ok": True}
    assert res.attempts == 3
    assert next(s for s in res.steps if s.step == 10).status == "passed"


def test_tool_pipeline_return_default_fallback():
    def boom(_params):
        raise ValueError("g5 tool hard fail")

    res = _pipeline(boom).execute(
        "t", {},
        policy=ExceptionPolicy(process_type=ErrorProcessType.RETURN_DEFAULT,
                               data_on_err={"fallback": True}))
    assert res.status == "completed"
    assert res.route == "return_default"
    assert res.result == {"fallback": True}
    assert res.error.startswith("ValueError: g5 tool hard fail")
    assert next(s for s in res.steps if s.step == 10).status == "fallback"


def test_tool_pipeline_timeout_cuts_off_a_hanging_attempt():
    def hang(_params):
        time.sleep(0.5)
        return {"late": True}

    res = _pipeline(hang).execute("t", {}, policy=ExceptionPolicy(timeout_ms=50))
    assert res.status == "error"
    assert "exceeded 50ms" in (res.error or "")