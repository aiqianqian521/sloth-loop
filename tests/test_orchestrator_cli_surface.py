"""cycle-17 A (P4): cover the orchestrator CLI surface.

Before this file, ``sloth_engine/orchestrator.py`` sat at 53% coverage: the whole
operator-facing surface -- ``status()``, ``review()``, ``_show_history()``,
``reset()``, ``build_orchestrator()`` and ``main()`` -- was never executed by the
gate.  These are the product's own commands, so an unexecuted branch (the
``--min-win-rate`` filter, the non-tty review guard, the fail-closed missing
config) was an unverified contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import pytest  # noqa: E402

import orchestrator as om  # noqa: E402
from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402


def _cfg(tmp: Path, **loop_over) -> dict:
    db = tmp / "patterns.db"
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(tmp), "db": str(db)},
        "memory": {"sqlite_path": str(db)},
        "loop": {"max_rounds": 5, "no_progress_stop": 5,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "extra_args": "--seed test --win-bias 0.5"},
    })
    cfg["loop"].update(loop_over)
    return cfg


def _open_failure(i: int, **over) -> dict:
    row = {
        "id": "F-%03d" % i,
        "date": "2026-10-23",
        "signal_pattern": "sig_%d" % i,
        "market_condition": "trend",
        "failure_mode": "timeout",
        "root_cause": "root cause %d" % i,
        "status": "open",
        "impact": {"trades": 3, "win_rate": "40%", "total_pnl": "-1.2"},
    }
    row.update(over)
    return row


class _Rec:
    def __init__(self):
        self.lines: list[str] = []

    def _add(self, *a, **_kw):
        self.lines.append(" ".join(str(x) for x in a if x is not None))

    info = warning = error = debug = _add

    def joined(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def orch(tmp_path):
    return om.Orchestrator(_cfg(tmp_path))


# ---- status() --------------------------------------------------------------

def test_status_on_an_empty_library(orch, monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.status()  # must not raise
    assert "ok" not in rec.joined().lower().split()  # smoke: produced a report
    assert rec.joined() != ""


def test_status_renders_data_and_the_problem_queue(orch, monkeypatch):
    orch.store.append_failure([
        _open_failure(1),
        _open_failure(2, failure_mode="data_gap"),
        _open_failure(3, status="resolved", exclusion_rule="sig_3@trend"),
    ])
    orch.store.log_round(10, 2, 8, 1, 0, notes="ok")
    orch.store.push_problem({
        "id": "P-20261023-001", "type": "execution_error", "severity": "critical",
        "error_signature": "sig-x", "evidence": "e" * 200,
        "suggested_action": "fix it", "round": 2, "status": "queued",
    })
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.status()
    out = rec.joined()
    assert "F-001" not in out
    assert "2" in out


def test_status_caps_the_active_rule_list(orch, monkeypatch):
    rows = [_open_failure(i, status="resolved", exclusion_rule="r%d" % i)
            for i in range(1, 9)]
    orch.store.append_failure(rows)
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.status()
    assert "..." in rec.joined()


# ---- review() --------------------------------------------------------------

def test_review_with_nothing_open(orch, monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.review(assume_yes=True)
    assert "No open failures" in rec.joined()


def test_review_without_tty_and_without_yes_is_a_no_op(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1)])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.review()
    assert "Non-interactive" in rec.joined()
    assert orch.store.load_failure_patterns()[0]["status"] == "open"


def test_review_yes_resolves_every_open_failure(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1), _open_failure(2)])
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.review(assume_yes=True)
    assert all(f["status"] == "resolved"
               for f in orch.store.load_failure_patterns())
    assert "Done." in rec.joined()


def test_review_yes_with_min_win_rate_skips_low_win_rate(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1)])
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.review(assume_yes=True, min_win_rate=0.9)
    assert orch.store.load_failure_patterns()[0]["status"] == "open"
    assert "skipped due to low win rate" in rec.joined()


def test_review_yes_with_min_win_rate_keeps_high_win_rate(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1, impact={"trades": 3, "win_rate": "95%",
                                                        "total_pnl": "1.0"})])
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.review(assume_yes=True, min_win_rate=0.5)
    assert orch.store.load_failure_patterns()[0]["status"] == "resolved"


def test_review_interactive_skip_and_quit_and_all(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1), _open_failure(2)])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    answers = iter(["n", "a"])
    monkeypatch.setattr("builtins.input", lambda *_a: next(answers))
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.review()
    assert "-> skipped" in rec.joined()
    assert "Done." in rec.joined()


def test_review_interactive_quit_stops_the_loop(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1), _open_failure(2)])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda *_a: "q")
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.review()
    assert "Quit" in rec.joined()
    assert all(f["status"] == "open" for f in orch.store.load_failure_patterns())


def test_review_tolerates_an_unparseable_win_rate(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1, impact={"trades": 1,
                                                        "win_rate": "N/A",
                                                        "total_pnl": "0"})])
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.review(assume_yes=True, min_win_rate=0.5)
    assert orch.store.load_failure_patterns()[0]["status"] == "resolved"


# ---- reset() ---------------------------------------------------------------

def test_reset_without_yes_does_not_touch_the_library(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1)])
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.reset()
    assert len(orch.store.load_failure_patterns()) == 1
    assert "Add --yes" in rec.joined()


def test_reset_with_yes_clears_every_table(orch, monkeypatch):
    orch.store.append_failure([_open_failure(1)])
    orch.store.log_round(1, 0, 1, 0, 0, notes="ok")
    orch.store.save_run_history({"run_id": "R-1", "task": "t"})
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    orch.reset(assume_yes=True)
    assert orch.store.load_failure_patterns() == []
    assert orch.store.get_rounds() == []


# ---- _show_history() -------------------------------------------------------

def test_show_history_without_a_database(tmp_path, monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    om._show_history(tmp_path / "missing.db")
    assert "history" in rec.joined()


def test_show_history_with_an_empty_database(orch, monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    om._show_history(orch.db_path)
    assert "history" in rec.joined()


def test_show_history_renders_rows_and_stop_reasons(orch, monkeypatch):
    extra = [(0, 0), (0, 2)]  # no new patterns (else branch) / successes only
    rows = [("OK", "max_rounds reached"),
            ("WARN", "no progress detected"),
            ("ERR", "time limit hit"),
            ("STOP", "circuit breaker open")] + [
                ("OK", "unknown reason")] * 2
    for i, (verdict, stop) in enumerate(rows, 1):
        nf, ns = extra[i - 5] if i > 4 else (i, 0)
        orch.store.save_run_history({
            "run_id": "R-%d" % i, "task": "task-%d" % i, "total_rounds": i,
            "elapsed_seconds": 1.5, "stop_reason": stop, "new_failures": nf,
            "new_successes": ns, "active_exclusion_rules": 1, "problem_queue_total": 2,
            "verdict": verdict, "created_at": "2026-10-23T10:00:00"})
    rec = _Rec()
    monkeypatch.setattr(om, "_log", rec)
    om._show_history(orch.db_path)
    out = rec.joined()
    assert "R-4" in out
    assert "4" in out


# ---- build_orchestrator() --------------------------------------------------

def test_build_orchestrator_fails_closed_on_a_missing_config(tmp_path):
    with pytest.raises(om.ConfigNotFoundError):
        om.build_orchestrator(str(tmp_path / "nope.yaml"))


def test_build_orchestrator_loads_a_real_yaml_config(tmp_path):
    root = str(tmp_path).replace(chr(92), "/")
    db = (str(tmp_path) + "/patterns.db").replace(chr(92), "/")
    (tmp_path / "config.yaml").write_text(
        "runtime:\n  root: %s\n  db: %s\n"
        "loop:\n  max_rounds: 3\n"
        "backtest:\n  script: backtest/mock_backtest.py\n" % (root, db),
        encoding="utf-8")
    built = om.build_orchestrator(str(tmp_path / "config.yaml"))
    assert isinstance(built, om.Orchestrator)
    assert built.max_rounds == 3


# ---- main() composition root ----------------------------------------------

def test_main_wires_the_router_and_swallows_a_zero_exit(monkeypatch):
    seen: dict = {}

    class FakeDeps:
        def __init__(self, **kw):
            seen["deps"] = kw

    class FakeRouter:
        def __init__(self, deps):
            seen["config"] = deps

        def run(self, argv):
            seen["argv"] = argv
            return 0

    monkeypatch.setattr(om, "CliDependencies", FakeDeps)
    monkeypatch.setattr(om, "CliRouter", FakeRouter)
    om.main(["--status"])
    assert seen["argv"] == ["--status"]
    assert seen["deps"]["build_orchestrator"] is om.build_orchestrator
    assert seen["deps"]["show_history"] is om._show_history
    assert callable(seen["deps"]["inspection_service"])
    assert seen["deps"]["run_lock_cls"] is om._RunLock
    assert seen["deps"]["tee_cls"] is om._Tee
    assert seen["deps"]["logger"] is om._log


def test_main_raises_system_exit_on_a_nonzero_router_code(monkeypatch):
    class FakeDeps:
        def __init__(self, **kw):
            pass

    class FakeRouter:
        def __init__(self, deps):
            pass

        def run(self, argv):
            return 3

    monkeypatch.setattr(om, "CliDependencies", FakeDeps)
    monkeypatch.setattr(om, "CliRouter", FakeRouter)
    with pytest.raises(SystemExit) as excinfo:
        om.main([])
    assert excinfo.value.code == 3


def test_main_accepts_no_arguments(monkeypatch):
    seen: dict = {}

    class FakeDeps:
        def __init__(self, **kw):
            pass

    class FakeRouter:
        def __init__(self, deps):
            pass

        def run(self, argv):
            seen["argv"] = argv
            return 0

    monkeypatch.setattr(om, "CliDependencies", FakeDeps)
    monkeypatch.setattr(om, "CliRouter", FakeRouter)
    om.main(None)
    assert seen["argv"] is None
