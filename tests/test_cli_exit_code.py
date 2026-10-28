"""Worker 2 regressions: --once exit code + uniform envelope + run_parallel crash.

Covers:
  D1  --once must return a non-zero exit code when the round fails
      (e.g. strict signal-schema gate -> SIG_INVALID_SIGNALS), not always 0.
  D2  run_once succeed / fail paths must return the same uniform envelope with
      {status, progressed, error} keys present in both outcomes.
  D8  orchestrator.run_parallel must not reference the undefined module-global
      ``_ENGINE`` (that would raise ``NameError``); it must use ``_HERE``.

Notes:
  * run_parallel uses a nested ``_run_one`` closure, which cannot be pickled to
    a multiprocessing worker on Windows, so a true subprocess call would fail
    for an unrelated reason. The regression test therefore statically asserts
    the function body no longer references the undefined ``_ENGINE``.
  * Full OODA run_once completes the mock backtest path (≈ 1-2s).
"""
from __future__ import annotations

import contextlib
import io
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from cli_router import CliDependencies, CliRouter  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402


class _Logger:
    def info(self, *_a, **_kw):
        pass

    def error(self, *_a, **_kw):
        pass


class _NoopLock:
    """R1 (cycle-10): CliRouter now locks --once as well; this stub keeps the
    unit tests hermetic (no on-disk lock) while satisfying the CM protocol."""

    def __init__(self, _path):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _make_router(orch):
    return CliRouter(CliDependencies(
        build_orchestrator=lambda _cfg: orch,
        inspection_service=lambda _wd: SimpleNamespace(
            inspect_handler=lambda *_: None, trace_handler=lambda *_: None),
        show_history=lambda *_: None,
        run_lock_cls=_NoopLock,
        tee_cls=lambda stream, _path: stream,
        logger=_Logger()))


def _make_orch(tmp_path, fast, schema_validate, valid_signals):
    """Build an Orchestrator with a seed pool of valid/invalid signals.

    ``valid_signals`` False => the only candidate lacks signal_pattern, so with
    ``schema_validate`` on the strict gate rejects it and run_once fails.
    """
    pool = tmp_path / "signals.json"
    data = ([{"signal_pattern": "wb2_engine_sig", "market_condition": "trend"}]
            if valid_signals else [{"market_condition": "trend"}])
    pool.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(tmp_path), "db": "db/patterns.db",
                    "io": "io/_data", "events": "runs", "logs": "logs",
                    "state": "state/STATE.md", "handoff": "state/handoff.json"},
        "loop": {"max_rounds": 1, "no_progress_stop": 10,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "task": {"name": "wb2-exit-code",
                 "success_criteria": [{"metric": "trades_count",
                                       "operator": "gt", "threshold": 0}],
                 "scope": {"allow": [], "deny": []}},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "python": str(Path(sys.executable))},
    })
    cfg["ooda"] = {"enabled": not fast, "uq_enabled": False,
                   "uq_require_input": False, "schema_validate": schema_validate}
    return Orchestrator(cfg), pool


def _silent(fn):
    with contextlib.redirect_stdout(io.StringIO()),             contextlib.redirect_stderr(io.StringIO()):
        return fn()


# ---- D8: run_parallel must not dereference the undefined _ENGINE ----

def test_run_parallel_body_does_not_reference_undefined_engine():
    src = (ENGINE / "orchestrator.py").read_text(encoding="utf-8")
    marker = "def run_parallel"
    assert marker in src
    body = src.split(marker, 1)[1].split("def _safe_run_component", 1)[0]
    # D8: never reference the undefined _ENGINE global.
    assert "_ENGINE" not in body, "run_parallel still references undefined _ENGINE"
    # P2-B: parallel worker must be a module-level picklable helper dispatched
    # via functools.partial (a local closure is not picklable on Windows spawn).
    assert "functools.partial" in body or "from functools import partial" in body
    assert "_parallel_exclusion_check" in body


def test_parallel_exclusion_check_is_module_level():
    src = (ENGINE / "orchestrator.py").read_text(encoding="utf-8")
    # _parallel_exclusion_check must be defined at module scope (no indentation),
    # never inside a class, so Windows spawn can pickle it.
    found = False
    for ln in src.splitlines():
        if "def _parallel_exclusion_check" in ln:
            found = True
            assert not ln.startswith(" ") and not ln.startswith("\t"), \
                "_parallel_exclusion_check must be module-level, got: " + ln
    assert found, "_parallel_exclusion_check not found in orchestrator.py"


# ---- D1: --once exit code on failure / success ----

def test_once_failure_returns_nonzero_exit_code(tmp_path):
    orch, pool = _make_orch(tmp_path, fast=False, schema_validate=True,
                            valid_signals=False)
    router = _make_router(orch)
    args = SimpleNamespace(signals=str(pool), fast=False)
    rc = _silent(lambda: router._run_once(orch, args))
    assert rc == 1, f"--once failure must exit non-zero, got {rc}"


def test_once_success_returns_zero_exit_code(tmp_path):
    orch, pool = _make_orch(tmp_path, fast=True, schema_validate=True,
                            valid_signals=True)
    router = _make_router(orch)
    args = SimpleNamespace(signals=str(pool), fast=True)
    rc = _silent(lambda: router._run_once(orch, args))
    assert rc == 0, f"--once success must exit 0, got {rc}"


# ---- D2: uniform envelope {status, progressed, error} on both outcomes ----

def test_run_once_failure_envelope_has_uniform_keys(tmp_path):
    orch, pool = _make_orch(tmp_path, fast=False, schema_validate=True,
                            valid_signals=False)
    batch = _silent(lambda: orch.generate_signals(str(pool)))
    assert batch == []  # strict gate accepted nothing
    res = _silent(lambda: orch.run_once(batch, 1))
    assert res.get("status") == "error"
    for key in ("status", "progressed", "error"):
        assert key in res, f"failure envelope missing {key!r}: {sorted(res)}"
    assert res["progressed"] is False


def test_run_once_success_envelope_has_uniform_keys(tmp_path):
    orch, pool = _make_orch(tmp_path, fast=False, schema_validate=True,
                            valid_signals=True)
    batch = _silent(lambda: orch.generate_signals(str(pool)))
    assert batch, "seed pool should yield one valid signal"
    res = _silent(lambda: orch.run_once(batch, 1))
    assert res.get("status") == "ok", f"expected ok, got {res.get('status')}"
    for key in ("status", "progressed", "error"):
        assert key in res, f"success envelope missing {key!r}: {sorted(res)}"
