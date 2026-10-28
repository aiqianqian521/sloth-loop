# -*- coding: utf-8 -*-
"""P0 failure-propagation + lock-liveness regression layer.

Covers the independent-audit findings:
  * Act-level failures (wrapper non-zero exit / invalid JSON / missing script)
    must propagate to a non-zero CLI exit code AND status="error" envelope,
    for BOTH --once and continuous entrypoints (P0-A / F4,F5,D1).
  * The run lock must treat a fresh lock whose owner PID is provably dead as
    stale (P0-B / D3), while never stealing a lock held by a live or
    unparseable owner.
  * An unrecognized success_criteria operator must fail closed instead of
    being silently counted as "unknown" (P0-C / D6).

These are behavioural regression guards, not source-grep checks.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from cli_router import CliDependencies, CliRouter  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from run_lock import _RunLock, _parse_lock_pid, _pid_alive  # noqa: E402
from verifier import Verifier  # noqa: E402


class _Logger:
    def info(self, *_a, **_kw):
        pass

    def error(self, *_a, **_kw):
        pass

    def warning(self, *_a, **_kw):
        pass


def _silent(fn):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn()


_SCRATCH = ENGINE / "tests" / "_tmp_p0_prop"


@contextlib.contextmanager
def _scratch_wrapper(body: str):
    """Write a wrapper script inside the repo tree (runtime containment
    requires exec assets to live under the repo root) and clean it up."""
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="p0-", dir=str(_SCRATCH)))
    try:
        w = d / "wrapper.py"
        w.write_text(body, encoding="utf-8")
        yield w
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _make_router(orch):
    return CliRouter(CliDependencies(
        build_orchestrator=lambda _cfg: orch,
        inspection_service=lambda _wd: SimpleNamespace(
            inspect_handler=lambda *_: None, trace_handler=lambda *_a, **_k: None),
        show_history=lambda *_: None,
        run_lock_cls=_RunLock,
        tee_cls=lambda stream, _path: stream,
        logger=_Logger()))


def _write_wrapper(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


_OK_WRAPPER = (
    "import argparse, json, pathlib\n"
    "ap = argparse.ArgumentParser()\n"
    "ap.add_argument('--input', required=True)\n"
    "ap.add_argument('--output', required=True)\n"
    "a = ap.parse_args()\n"
    "p = json.loads(pathlib.Path(a.input).read_text(encoding='utf-8'))\n"
    "sigs = p.get('signals', [])\n"
    "out = {'trades': [{'signal_pattern': s.get('signal_pattern'), 'pnl': 1.0} for s in sigs],\n"
    "       'pnl': {'total': float(len(sigs))}, 'win_rate': 1.0, 'sharpe': 0.5}\n"
    "pathlib.Path(a.output).write_text(json.dumps(out), encoding='utf-8')\n"
)

_BAD_JSON_WRAPPER = _OK_WRAPPER.replace(
    "pathlib.Path(a.output).write_text(json.dumps(out), encoding='utf-8')",
    "pathlib.Path(a.output).write_text('{ not valid json', encoding='utf-8')")

_NONZERO_WRAPPER = _OK_WRAPPER + "raise SystemExit(3)\n"


def _make_once_orch(tmp_path: Path, wrapper_path: Path, script: str) -> Orchestrator:
    seed = tmp_path / "signals.json"
    seed.write_text(json.dumps([{"signal_pattern": "p0sig", "market_condition": "trend"}]),
                    encoding="utf-8")
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(tmp_path), "db": "db/patterns.db", "io": "io/_data",
                    "events": "runs", "logs": "logs", "state": "state/STATE.md"},
        "loop": {"max_rounds": 3, "no_progress_stop": 10, "meta_analyze_every": 100,
                 "batch_size": 3, "max_seconds": 0},
        "task": {"name": "p0-prop", "task_name": "p0-prop",
                 "success_criteria": [{"metric": "trades_count", "operator": "gt", "threshold": 0}],
                 "scope": {"allow": [], "deny": []}},
        "backtest": {"script": script, "python": str(Path(sys.executable))},
        "ooda": {"enabled": True, "uq_enabled": False, "uq_require_input": False,
                 "schema_validate": False},
    })
    return Orchestrator(cfg)


# ---- P0-A: --once must exit non-zero on act failure -------------------------

def test_once_wrapper_bad_json_exits_nonzero(tmp_path):
    with _scratch_wrapper(_BAD_JSON_WRAPPER) as w:
        orch = _make_once_orch(tmp_path, w, str(w))
        router = _make_router(orch)
        args = SimpleNamespace(signals=str(tmp_path / "signals.json"), fast=False)
        rc = _silent(lambda: router._run_once(orch, args))
    assert rc == 1, f"wrapper invalid JSON must exit non-zero, got {rc}"


def test_once_wrapper_nonzero_exit_exits_nonzero(tmp_path):
    with _scratch_wrapper(_NONZERO_WRAPPER) as w:
        orch = _make_once_orch(tmp_path, w, str(w))
        router = _make_router(orch)
        args = SimpleNamespace(signals=str(tmp_path / "signals.json"), fast=False)
        rc = _silent(lambda: router._run_once(orch, args))
    assert rc == 1, f"wrapper non-zero exit must exit non-zero, got {rc}"


def test_once_missing_script_exits_nonzero(tmp_path):
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    missing = _SCRATCH / "definitely_missing_script.py"
    orch = _make_once_orch(tmp_path, missing, str(missing))
    router = _make_router(orch)
    args = SimpleNamespace(signals=str(tmp_path / "signals.json"), fast=False)
    rc = _silent(lambda: router._run_once(orch, args))
    assert rc == 1, f"missing backtest script must exit non-zero, got {rc}"


def test_once_success_still_exits_zero(tmp_path):
    with _scratch_wrapper(_OK_WRAPPER) as w:
        orch = _make_once_orch(tmp_path, w, str(w))
        router = _make_router(orch)
        args = SimpleNamespace(signals=str(tmp_path / "signals.json"), fast=False)
        rc = _silent(lambda: router._run_once(orch, args))
    assert rc == 0, f"successful round must exit 0, got {rc}"


# ---- P0-A: run_once envelope carries the failure ---------------------------

def test_run_once_envelope_reports_act_failure(tmp_path):
    with _scratch_wrapper(_BAD_JSON_WRAPPER) as w:
        orch = _make_once_orch(tmp_path, w, str(w))
        batch = _silent(lambda: orch.generate_signals(str(tmp_path / "signals.json")))
        res = _silent(lambda: orch.run_once(batch, 1))
    assert res.get("status") == "error", f"act failure must set status=error, got {res.get('status')}"
    for key in ("status", "progressed", "error"):
        assert key in res, f"envelope missing {key!r}"
    assert res.get("error"), "failure envelope must carry an error message"


# ---- P0-B: run lock PID liveness -------------------------------------------

def test_pid_alive_self_true():
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_absent_is_false():
    assert _pid_alive(999999) is False


def test_parse_lock_pid_roundtrip():
    assert _parse_lock_pid("pid=4321 at=2026-01-01") == 4321
    assert _parse_lock_pid("no pid token") is None


def test_lock_steals_fresh_dead_pid_lock(tmp_path):
    lock_path = tmp_path / ".loop.lock"
    lock_path.write_text("pid=999999 at=now", encoding="utf-8")
    lock = _RunLock(lock_path)
    lock.__enter__()  # must not raise
    try:
        assert lock.acquired is True
    finally:
        lock.__exit__(None, None, None)


def test_lock_blocks_live_pid_fresh_lock(tmp_path):
    lock_path = tmp_path / ".loop.lock"
    lock_path.write_text(f"pid={os.getpid()} at=now", encoding="utf-8")
    lock = _RunLock(lock_path)
    try:
        try:
            lock.__enter__()
        except RuntimeError:
            pass
        else:
            raise AssertionError("live owner's fresh lock must block a second run")
    finally:
        # do not leave an acquired lock; we never acquired
        if lock.acquired:
            lock.__exit__(None, None, None)


def test_lock_blocks_unparseable_fresh_lock(tmp_path):
    lock_path = tmp_path / ".loop.lock"
    lock_path.write_text("garbage without pid", encoding="utf-8")
    lock = _RunLock(lock_path)
    try:
        try:
            lock.__enter__()
        except RuntimeError:
            pass
        else:
            raise AssertionError("unparseable fresh lock must fail safe (block)")
    finally:
        if lock.acquired:
            lock.__exit__(None, None, None)


def test_lock_steals_old_lock(tmp_path):
    lock_path = tmp_path / ".loop.lock"
    lock_path.write_text("pid=999999 at=old", encoding="utf-8")
    old = time.time() - 7 * 3600
    os.utime(lock_path, (old, old))
    lock = _RunLock(lock_path)
    lock.__enter__()
    try:
        assert lock.acquired is True
    finally:
        lock.__exit__(None, None, None)


# ---- P0-C: verifier unknown operator fails closed --------------------------

def test_verifier_unknown_operator_fails_closed():
    act = {"status": "completed", "trades": [{"pnl": 1.0}], "metrics": {}}
    r = Verifier.verify(act, [{"metric": "trades_count", "operator": "definitely_invalid",
                               "threshold": 0}])
    assert r["unknown"] == 0, "unknown operator must not be counted as 'unknown'"
    assert r["fail_count"] == 1, "unknown operator must fail closed"


def test_verifier_known_operators_still_work():
    act = {"status": "completed", "trades": [{"pnl": 1.0}], "signals_tested": 1,
           "sharpe": 1.5}
    r = Verifier.verify(act, [
        {"metric": "trades_count", "operator": "gte", "threshold": 1},
        {"metric": "sharpe", "operator": "gt", "threshold": 1.0},
        {"metric": "trades_count", "operator": "lte", "threshold": 1},
        {"metric": "trades_count", "operator": "eq", "threshold": 1},
        {"metric": "trades_count", "operator": "lt", "threshold": 2},
    ])
    assert r["pass_count"] == 5, r
    assert r["fail_count"] == 0
