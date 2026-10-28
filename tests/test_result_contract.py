"""Direct W1 result-contract checks without pytest dependency."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from adapters.backtest_adapter import BacktestInput, configure, run_backtest  # noqa: E402
from adapters.task_runner import BacktestRunner, TaskInput, TaskResult  # noqa: E402
from runtime_exec import local_exec_gate  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-contract-") as td:
        io_dir = Path(td) / "io"
        settings = configure({"script": "backtest/mock_backtest.py"}, ROOT, io_dir=io_dir)
        result = run_backtest(BacktestInput(signals=[{"signal_pattern": "contract"}]), settings,
                              exec_gate=local_exec_gate())
        assert result.status == "completed"
        assert result.execution["status"] == "succeeded"
        assert result.output["status"] == "valid"
        assert result.output["schema"] == "backtest.v1"
        assert result.business["status"] == "pending"
        assert result.provenance["script"].endswith("mock_backtest.py")

        runner = BacktestRunner({"script": settings.script, "python": settings.python,
                                 "cwd": settings.cwd, "input_path": settings.input_path,
                                 "output_path": settings.output_path},
                                exec_gate=local_exec_gate())
        task = runner.run(TaskInput(task_type="backtest", signals=[{"signal_pattern": "contract"}]))
        assert task.status == "completed"
        assert task.execution["status"] == "succeeded"
        assert task.output["status"] == "valid"
        assert task.business["status"] == "passed"
        assert runner.validate_output(task)
        serialized = task.to_dict()
        assert {"execution", "output", "business", "provenance"}.issubset(serialized)
        json.dumps(serialized)

        missing = configure({"script": "does-not-exist.py"}, ROOT, io_dir=io_dir / "missing")
        failed = run_backtest(BacktestInput(signals=[{"signal_pattern": "contract"}]), missing,
                              exec_gate=local_exec_gate())
        assert failed.status == "error"
        assert failed.execution["code"] == "script_missing"
        assert failed.output["status"] == "not_run"
        assert failed.provenance["component"] == "backtest_adapter"

        skipped = TaskResult(status="skipped")
        assert skipped.execution == {}
        assert skipped.output == {}

    print("PASS result contract execution/output/business/provenance")


def test_contract():
    """Pytest entry (cycle-16 A): keep these assertions inside the gate.

    This file used to be a manual script (``python tests/<file>``): pytest
    collected zero tests from it, so its assertions were never enforced by
    ``run_gate.py``.  The body is unchanged -- this wrapper only makes the very
    same checks run under pytest.
    """
    main()


if __name__ == "__main__":
    main()
