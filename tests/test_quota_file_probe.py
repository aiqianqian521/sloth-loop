"""cycle-13 A (N-3 feasible slice): file-backed provider quota probe.

Contracts under test (see sloth_engine/quota_file_probe.py header):
  1. unset / blank / whitespace-only LOOP_QUOTA_FILE => OFF, target untouched;
  2. an enabled path yields a zero-arg probe returning the parsed JSON object
     verbatim (window mapping stays quota_window's job);
  3. provider label precedence: LOOP_QUOTA_PROVIDER > payload["provider"] > "loop";
  4. probe failures raise; quota_window.resolve_snapshot degrades instead;
  5. the gate really consumes the file: an exhausted payload stops a real
     Orchestrator run with a "Quota exhausted (provider=...)" stop reason, while
     an unset env leaves the run byte-for-byte unchanged.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from config_util import DEFAULT_CONFIG, deep_merge  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402
from quota_file_probe import (  # noqa: E402
    DEFAULT_PROVIDER,
    ENV_FILE,
    ENV_PROVIDER,
    enabled,
    install,
    load_payload,
    make_probe,
    resolve_path,
    resolve_provider,
)
from quota_window import resolve_snapshot  # noqa: E402
from run_loop import RunLoopMixin  # noqa: E402

TASK_NAME = "_q13-file-quota"

HEADROOM = {"provider": "file-provider",
            "primary": {"usedPercent": 12.5, "windowDurationMins": 300},
            "secondary": {"used_percent": 88.0}}
EXHAUSTED = {"provider": "file-provider",
             "primary": {"usedPercent": 100, "resetsAt": 1761200000},
             "secondary": {"usedPercent": 10}}


class _Stub(RunLoopMixin):
    """Minimal host: the gate only reads quota_probe / _provider / _cache."""

    def __init__(self):
        self.quota_probe = None
        self.quota_provider = ""
        self.quota_cache = None


def _write(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---- env gating -----------------------------------------------------------

@pytest.mark.parametrize("env", [{}, {ENV_FILE: ""}, {ENV_FILE: "   "},
                                 {ENV_FILE: "\t\n"}])
def test_blank_or_missing_env_is_off(env):
    assert enabled(env) is False
    assert resolve_path(env) is None


def test_enabled_env_names_a_path():
    assert enabled({ENV_FILE: "/tmp/q.json"}) is True
    assert resolve_path({ENV_FILE: "  /tmp/q.json  "}) == "/tmp/q.json"


def test_resolve_path_expands_user():
    resolved = resolve_path({ENV_FILE: "~/q.json"})
    assert resolved is not None
    assert resolved.endswith("q.json")
    assert "~" not in resolved


# ---- payload loading ------------------------------------------------------

def test_load_payload_accepts_bom_and_returns_object(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps(HEADROOM), encoding="utf-8-sig")
    assert load_payload(str(path)) == HEADROOM


@pytest.mark.parametrize("raw", ["[]", "\"x\"", "3", "null"])
def test_load_payload_rejects_non_object(tmp_path, raw):
    path = tmp_path / "q.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        load_payload(str(path))


def test_load_payload_rejects_bad_json(tmp_path):
    path = tmp_path / "q.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_payload(str(path))


def test_load_payload_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        load_payload(str(tmp_path / "nope.json"))


def test_probe_is_fresh_not_cached(tmp_path):
    path = _write(tmp_path / "q.json", HEADROOM)
    probe = make_probe(str(path))
    assert probe()["secondary"]["used_percent"] == 88.0
    _write(path, EXHAUSTED)
    assert probe()["primary"]["usedPercent"] == 100


# ---- provider label -------------------------------------------------------

def test_provider_precedence_env_wins(tmp_path):
    path = _write(tmp_path / "q.json", HEADROOM)
    assert resolve_provider({ENV_PROVIDER: "openai"}, str(path)) == "openai"


def test_provider_falls_back_to_payload(tmp_path):
    path = _write(tmp_path / "q.json", HEADROOM)
    assert resolve_provider({}, str(path)) == "file-provider"


def test_provider_defaults_when_absent(tmp_path):
    path = _write(tmp_path / "q.json", {"primary": {"usedPercent": 1}})
    assert resolve_provider({}, str(path)) == DEFAULT_PROVIDER


def test_broken_payload_does_not_break_provider_lookup(tmp_path):
    path = tmp_path / "q.json"
    path.write_text("{oops", encoding="utf-8")
    assert resolve_provider({}, str(path)) == DEFAULT_PROVIDER
    assert resolve_provider({}, None) == DEFAULT_PROVIDER


# ---- install --------------------------------------------------------------

def test_install_disabled_leaves_target_untouched():
    stub = _Stub()
    assert install(stub, env={}) is None
    assert stub.quota_probe is None
    assert stub.quota_provider == ""


def test_install_enabled_sets_probe_provider_and_cache(tmp_path):
    path = _write(tmp_path / "q.json", HEADROOM)
    stub = _Stub()
    probe = install(stub, env={ENV_FILE: str(path)})
    assert probe is stub.quota_probe
    assert stub.quota_provider == "file-provider"
    assert stub.quota_cache is None
    assert stub.quota_probe() == HEADROOM


def test_install_provider_env_override(tmp_path):
    path = _write(tmp_path / "q.json", HEADROOM)
    stub = _Stub()
    install(stub, env={ENV_FILE: str(path), ENV_PROVIDER: "anthropic"})
    assert stub.quota_provider == "anthropic"


# ---- fail-soft hand-off ---------------------------------------------------

def test_unreadable_file_degrades_instead_of_raising(tmp_path):
    probe = make_probe(str(tmp_path / "missing.json"))
    snapshot = resolve_snapshot(probe, provider="file")
    assert snapshot.status == "error"
    assert snapshot.degraded is True
    assert snapshot.exhausted is False


def test_unreadable_file_keeps_last_known_windows(tmp_path):
    good = resolve_snapshot(make_probe(str(_write(tmp_path / "q.json", HEADROOM))),
                            provider="file")
    probe = make_probe(str(tmp_path / "missing.json"))
    degraded = resolve_snapshot(probe, provider="file", cache=good)
    assert degraded.degraded is True
    assert [w.label for w in degraded.windows] == ["primary", "secondary"]


# ---- the gate really consumes the file ------------------------------------

def test_gate_no_stop_with_headroom(tmp_path):
    stub = _Stub()
    install(stub, env={ENV_FILE: str(_write(tmp_path / "q.json", HEADROOM))})
    assert stub._quota_stop_reason() is None


def test_gate_stops_on_exhausted_file(tmp_path):
    stub = _Stub()
    install(stub, env={ENV_FILE: str(_write(tmp_path / "q.json", EXHAUSTED))})
    reason = stub._quota_stop_reason()
    assert reason is not None
    assert reason.startswith("Quota exhausted (provider=file-provider")
    assert "next_reset_at=1761200000000" in reason


def test_gate_missing_file_never_stops(tmp_path):
    stub = _Stub()
    install(stub, env={ENV_FILE: str(tmp_path / "gone.json")})
    assert stub._quota_stop_reason() is None
    assert stub.quota_cache.degraded is True


# ---- end-to-end: Orchestrator reads the env ------------------------------

_ROUND = {
    "record": {"new_failures": 0, "new_successes": 0,
               "bumped_failures": 0, "bumped_successes": 0},
    "backtest": None, "backtest_status": "deferred",
    "execution_failed": True, "error": "store indexing is behind",
    "progressed": False, "all_excluded": False, "round_ctx": None,
}


def _cfg(db_path: Path) -> dict:
    return deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(db_path.parent), "db": str(db_path)},
        "memory": {"sqlite_path": str(db_path)},
        "loop": {"max_rounds": 3, "no_progress_stop": 10, "meta_analyze_every": 100,
                 "batch_size": 0, "max_seconds": 0, "error_stop": 2},
        "backtest": {"script": "backtest/mock_backtest.py"},
        "task": {"name": TASK_NAME},
        "ooda": {"enabled": False},
    })


def _run_with_env(payload_path):
    d = Path(tempfile.mkdtemp(prefix="q13-file-"))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            orch = Orchestrator(_cfg(d / "p.db"))
            orch.run_once = lambda *a, **k: dict(_ROUND)
            pool = d / "pool.json"
            pool.write_text(json.dumps([{"signal_pattern": "s",
                                         "market_condition": "m"}]),
                            encoding="utf-8")
            result = orch.run(str(pool))
        return orch, result
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(ROOT / "projects" / TASK_NAME, ignore_errors=True)


def test_orchestrator_env_off_is_unchanged(monkeypatch):
    monkeypatch.delenv(ENV_FILE, raising=False)
    monkeypatch.delenv(ENV_PROVIDER, raising=False)
    orch, result = _run_with_env(None)
    assert orch.quota_probe is None
    assert result["total_rounds"] == 3
    assert "Quota" not in result["stop_reason"]


def test_orchestrator_env_on_stops_when_exhausted(monkeypatch, tmp_path):
    path = _write(tmp_path / "q.json", EXHAUSTED)
    monkeypatch.setenv(ENV_FILE, str(path))
    monkeypatch.delenv(ENV_PROVIDER, raising=False)
    orch, result = _run_with_env(path)
    assert orch.quota_probe is not None
    assert orch.quota_provider == "file-provider"
    assert result["status"] == "ok"
    assert result["total_rounds"] == 0
    assert "Quota exhausted (provider=file-provider" in result["stop_reason"]


def test_orchestrator_env_on_continues_with_headroom(monkeypatch, tmp_path):
    path = _write(tmp_path / "q.json", HEADROOM)
    monkeypatch.setenv(ENV_FILE, str(path))
    monkeypatch.setenv(ENV_PROVIDER, "openai")
    orch, result = _run_with_env(path)
    assert orch.quota_provider == "openai"
    assert result["total_rounds"] == 3
    assert "Quota exhausted" not in result["stop_reason"]


# ---- wiring tripwire ------------------------------------------------------

def test_orchestrator_installs_the_file_probe():
    source = (ENGINE / "orchestrator.py").read_text(encoding="utf-8")
    assert "quota_file_probe import install" in source
    assert "_install_quota_file_probe(self)" in source


def test_env_var_names_are_stable():
    assert (ENV_FILE, ENV_PROVIDER) == ("LOOP_QUOTA_FILE", "LOOP_QUOTA_PROVIDER")
    assert DEFAULT_PROVIDER == "loop"
    assert os.environ.get(ENV_FILE) is None or isinstance(os.environ[ENV_FILE], str)

def test_install_adds_missing_cache_attribute(tmp_path):
    path = _write(tmp_path / "q.json", HEADROOM)

    class _Bare:
        quota_probe = None
        quota_provider = ""

    target = _Bare()
    probe = install(target, env={ENV_FILE: str(path)})
    assert probe is not None
    assert target.quota_cache is None
