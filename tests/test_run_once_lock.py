"""R1 (cycle-10): --once must hold the same process run lock as the loop.

Before this fix only the continuous entrypoint took the lock, so a manual
``--once`` overlapping a cron run wrote the same SQLite DB / shared runtime
io_dir concurrently.  These checks pin the new contract: the lock is acquired
for the whole --once body, a held lock blocks it with exit code 2, and the lock
is released on every path.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from cli_router import CliDependencies, CliRouter  # noqa: E402
from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from run_lock import _RunLock  # noqa: E402


class _Logger:
    def info(self, *_a, **_kw):
        pass

    def error(self, *_a, **_kw):
        pass

    def warning(self, *_a, **_kw):
        pass


def _router(orch):
    return CliRouter(CliDependencies(
        build_orchestrator=lambda _cfg: orch,
        inspection_service=lambda _wd: SimpleNamespace(
            inspect_handler=lambda *_: None, trace_handler=lambda *_: None),
        show_history=lambda *_: None,
        run_lock_cls=_RunLock,
        tee_cls=lambda stream, _path: stream,
        logger=_Logger()))


def _build_orchestrator(tmp_path, task_name):
    pool = tmp_path / "signals.json"
    pool.write_text(json.dumps(
        [{"signal_pattern": "r1_signal", "market_condition": "trend"}],
        ensure_ascii=False), encoding="utf-8")
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(tmp_path), "db": "db/patterns.db",
                    "io": "io/_data", "events": "runs", "logs": "logs",
                    "state": "state/STATE.md", "handoff": "state/handoff.json"},
        "loop": {"max_rounds": 1, "no_progress_stop": 10,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "task": {"name": task_name,
                 "success_criteria": [{"metric": "trades_count",
                                       "operator": "gt", "threshold": 0}],
                 "scope": {"allow": [], "deny": []}},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "python": str(Path(sys.executable))},
        "ooda": {"enabled": False, "uq_enabled": False, "uq_require_input": False},
    })
    return Orchestrator(cfg), pool


def _sweep(task_name):
    shutil.rmtree(ROOT / "projects" / task_name, ignore_errors=True)


def test_run_once_blocks_when_the_lock_is_held(tmp_path):
    task = "r1-once-held"
    try:
        orch, pool = _build_orchestrator(tmp_path, task)
        lock_path = orch.runtime.root / ".loop.lock"
        lock_path.write_text("pid=%d at=now" % os.getpid(), encoding="utf-8")
        rc = _router(orch)._run_once(
            orch, SimpleNamespace(signals=str(pool), fast=True))
        assert rc == 2, "--once must refuse to run while the lock is held"
        assert lock_path.exists(), "the pre-existing lock must be left intact"
    finally:
        _sweep(task)


def test_run_once_holds_the_lock_for_the_whole_body(tmp_path):
    task = "r1-once-cycle"
    try:
        orch, pool = _build_orchestrator(tmp_path, task)
        lock_path = orch.runtime.root / ".loop.lock"
        seen = {}
        original = orch.run_once

        def spy(signals, round_num, **kwargs):
            seen["held"] = lock_path.exists()
            seen["body"] = lock_path.read_text(encoding="utf-8")
            return original(signals, round_num, **kwargs)

        orch.run_once = spy
        rc = _router(orch)._run_once(
            orch, SimpleNamespace(signals=str(pool), fast=True))
        assert rc == 0
        assert seen.get("held") is True, "the lock must be held during the round"
        assert "pid=" in (seen.get("body") or "")
        assert not lock_path.exists(), "the lock must be released afterwards"
    finally:
        _sweep(task)


def test_run_once_releases_the_lock_on_failure(tmp_path):
    task = "r1-once-fail"
    try:
        orch, pool = _build_orchestrator(tmp_path, task)

        def boom(*_a, **_kw):
            raise RuntimeError("r1 body exploded")

        orch.run_once = boom
        lock_path = orch.runtime.root / ".loop.lock"
        try:
            _router(orch)._run_once(
                orch, SimpleNamespace(signals=str(pool), fast=True))
            raise AssertionError("the body error must propagate")
        except RuntimeError as exc:
            assert str(exc) == "r1 body exploded"
        assert not lock_path.exists(), "a failing --once must not strand the lock"
    finally:
        _sweep(task)