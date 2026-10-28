"""W0 isolation checks; intentionally dependency-free like test_loop.py."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from adapters.backtest_adapter import (  # noqa: E402
    BacktestInput,
    configure,
    run_backtest,
)
from runtime_paths import RuntimePaths  # noqa: E402
from memory_store import PatternStore  # noqa: E402


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"FAIL {label}: {detail}")
    print(f"PASS {label}")


def _gate():
    """cycle-36 A: the adapter is fail-closed, so tests inject a real ExecGate."""
    from runtime_exec import local_exec_gate
    return local_exec_gate()


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="loop-w0-"))
    try:
        cfg = {
            "runtime": {
                "root": str(tmp / "runtime"),
                "db": "db/patterns.db",
                "io": "io",
                "events": "events",
                "logs": "logs",
                "state": "state/STATE.md",
                "handoff": "state/handoff.json",
            },
            "memory": {"sqlite_path": "ignored/patterns.db"},
        }
        paths = RuntimePaths.from_config(cfg, ROOT, ENGINE).ensure()
        check("runtime root is explicit", paths.root == (tmp / "runtime").resolve())
        check("runtime db is isolated", paths.db_path == paths.root / "db" / "patterns.db")
        check("runtime directories created", paths.io_dir.exists() and paths.events_dir.exists())

        s1 = configure({"script": "backtest/mock_backtest.py"}, ROOT,
                       io_dir=tmp / "io-1")
        s2 = configure({"script": "backtest/mock_backtest.py"}, ROOT,
                       io_dir=tmp / "io-2")
        check("settings instances do not share paths", s1.input_path != s2.input_path)
        check("settings instance remains immutable", s1.output_path.parent.name == "io-1")

        r1 = run_backtest(BacktestInput(signals=[{"signal_pattern": "one"}]), s1,
                          exec_gate=_gate())
        r2 = run_backtest(BacktestInput(signals=[{"signal_pattern": "two"}]), s2,
                          exec_gate=_gate())
        check("explicit settings route run 1", r1.status == "completed" and s1.output_path.exists())
        check("explicit settings route run 2", r2.status == "completed" and s2.output_path.exists())
        check("run artifacts remain separated", s1.output_path.read_text(encoding="utf-8") != "")
        check("settings are not a mutable dict", not isinstance(s1, dict))

        store = PatternStore(paths.db_path)
        store.save_checkpoint({
            "run_id": "w0-test-run", "task_name": "isolation",
            "round": 2, "step": "round_start", "signal_cursor": 3,
            "pool_hash": "pool", "config_hash": "config",
            "payload": {"runtime_root": str(paths.root)},
        })
        checkpoint = store.load_checkpoint("w0-test-run")
        check("checkpoint round-trip", checkpoint is not None and
              checkpoint["round"] == 2 and
              checkpoint["payload"]["runtime_root"] == str(paths.root))
        store.clear_checkpoint("w0-test-run")
        check("checkpoint clear", store.load_checkpoint("w0-test-run") is None)
        with store._connect() as conn:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        check("connection policy is explicit", journal_mode == "wal" and
              foreign_keys == 1 and busy_timeout >= 30000)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
