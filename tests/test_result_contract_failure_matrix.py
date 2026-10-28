"""Dependency-free failure matrix for the adapter result contract."""
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sloth_engine"))
from adapters.backtest_adapter import BacktestInput, configure, run_backtest
from runtime_exec import local_exec_gate


ROOT = Path(__file__).resolve().parents[1]
PYTHON = __import__("sys").executable


def _run(script: str, payload: str | None = None):
    with tempfile.TemporaryDirectory(prefix="loop-contract-matrix-") as td:
        root = Path(td)
        script_path = root / "case.py"
        script_path.write_text(script, encoding="utf-8")
        if payload is not None:
            (root / "payload.json").write_text(payload, encoding="utf-8")
        settings = configure({"script": str(script_path), "python": PYTHON}, ROOT,
                             io_dir=root / "io")
        return run_backtest(BacktestInput(signals=[{"signal_pattern": "matrix"}]), settings,
                            exec_gate=local_exec_gate(root))


def main() -> None:
    cases = {
        "script_missing": ("missing.py", "script_missing"),
    }
    with tempfile.TemporaryDirectory(prefix="loop-contract-missing-") as td:
        root = Path(td)
        result = run_backtest(BacktestInput(signals=[]), configure({"script": str(root / "missing.py")}, ROOT, io_dir=root / "io"))
        assert result.execution["code"] == cases["script_missing"][1]
        assert result.output["schema_valid"] is False

    checks = [
        ("import sys; sys.exit(3)", "process_nonzero_exit"),
        ("pass", "output_missing"),
        ("from pathlib import Path; import sys; Path(sys.argv[sys.argv.index('--output')+1]).write_text('{bad', encoding='utf-8')", "output_invalid_json"),
        ("from pathlib import Path; import sys; Path(sys.argv[sys.argv.index('--output')+1]).write_text('[]', encoding='utf-8')", "output_schema_invalid"),
        ("from pathlib import Path; import sys; Path(sys.argv[sys.argv.index('--output')+1]).write_text('{\"trades\":[{}]}', encoding='utf-8')", "trade_missing_signal_pattern"),
        ("from pathlib import Path; import sys; Path(sys.argv[sys.argv.index('--output')+1]).write_text('{\"trades\":[{\"signal_pattern\":\"x\",\"pnl\":\"bad\"}]}', encoding='utf-8')", "trade_invalid_pnl"),
    ]
    for script, expected in checks:
        result = _run(script)
        assert result.status == "error", expected
        assert result.execution["code"] == expected, (expected, result.to_dict())
        assert "status" in result.output and "status" in result.business

    with tempfile.TemporaryDirectory(prefix="loop-contract-partial-") as td:
        root = Path(td)
        settings = configure({"script": str(ROOT / "backtest" / "mock_backtest.py")}, ROOT, io_dir=root / "io")
        result = run_backtest(BacktestInput(signals=[{"signal_pattern": "matrix"}]),
                              {"script": settings.script}, exec_gate=local_exec_gate(root))
        assert result.provenance["adapter"] == "backtest"

    print("PASS result contract failure matrix (8 cases)")


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
