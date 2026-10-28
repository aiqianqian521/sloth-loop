"""Resume provenance gate contract tests (pure seam + checkpoint payload)."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from circuit_state import CircuitState  # noqa: E402
from run_loop import RunLoopMixin  # noqa: E402
from resume_guard import (  # noqa: E402
    check_compatibility,
    check_provenance_compatibility,
    compute_config_hash,
    extract_provenance_digest,
)
from adapters.task_runner import TaskResult  # noqa: E402
from adapters.backtest_adapter import configure, probe_provenance  # noqa: E402
from runtime_exec import local_exec_gate  # noqa: E402


def test_provenance_match_allows_resume() -> None:
    assert check_provenance_compatibility("abc", "abc") == (True, "provenance_match")


def test_provenance_change_fails_closed_with_stable_reason() -> None:
    ok, reason = check_provenance_compatibility("abc", "def")
    assert not ok
    assert reason.startswith("resume_provenance_mismatch")


def test_new_checkpoint_digest_without_current_digest_fails_closed() -> None:
    ok, reason = check_provenance_compatibility("abc", None)
    assert not ok
    assert reason == "resume_provenance_mismatch: current digest unavailable"


def test_legacy_checkpoint_without_digest_remains_compatible() -> None:
    ok, reason = check_provenance_compatibility(None, None)
    assert ok and reason == "legacy_provenance"
    ok, reason = check_compatibility(
        {"task_name": "task", "payload": {"schema_version": 5}},
        current_cfg={}, current_task_name="task", current_schema_version=5,
        current_provenance_digest=None,
    )
    assert ok and reason == "ok"


def test_extract_digest_from_nested_task_result() -> None:
    result = TaskResult(status="completed", provenance={"provenance_digest": "abc"})
    assert extract_provenance_digest({"task_result": result}) == "abc"
    assert extract_provenance_digest({"payload": {"provenance_digest": "def"}}) == "def"


class _FakeStore:
    def schema_version(self) -> int:
        return 5


class _FakeCircuit:
    def snapshot(self) -> dict:
        return {"state": "CLOSED"}


class _FakeRuntime:
    root = Path("<RUNTIME_ROOT>/test-resume-provenance")


class _CheckpointOwner(CircuitState):
    def __init__(self) -> None:
        self.runtime = _FakeRuntime()
        self.circuit = _FakeCircuit()
        self.store = _FakeStore()
        self.cfg = {"backtest": {}}
        self._pool = []
        self._round_start_cursor = 0
        self._cursor = 0
        self._run_id = "run-1"
        self.task_cfg = {"name": "task"}
        self.total_rounds = 1
        self._consecutive_errors = 0
        self._resume_pass = False


def test_checkpoint_payload_persists_digest_outside_opaque_artifacts() -> None:
    owner = _CheckpointOwner()
    result = TaskResult(status="completed", provenance={"provenance_digest": "digest-1"})
    checkpoint = owner._checkpoint_payload(
        "act", {"artifacts": {"act": {"task_result": result}}}
    )
    assert checkpoint["payload"]["provenance_digest"] == "digest-1"


def test_adapter_probe_returns_current_digest_without_backtest(tmp_path: Path) -> None:
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        "import json,sys\n"
        "out=sys.argv[sys.argv.index('--output')+1]\n"
        "json.dump({'provenance':{'schema':'loop.provenance.v1',"
        "'provenance_digest':'digest-current'}},open(out,'w'))\n",
        encoding="utf-8",
    )
    settings = configure({"script": str(bridge)}, ROOT, io_dir=tmp_path / "io")
    provenance = probe_provenance(settings, exec_gate=local_exec_gate(tmp_path))
    assert provenance is not None
    assert provenance["provenance_digest"] == "digest-current"
    assert not list((tmp_path / "io").glob("*.provenance_probe.json"))


class _ResumeStore:
    def __init__(self, checkpoint: dict):
        self.checkpoint = checkpoint
        self.cleared = False

    def load_latest_checkpoint(self, _task_name: str) -> dict:
        return self.checkpoint

    def schema_version(self) -> int:
        return 5

    def clear_checkpoint(self, _run_id: str) -> None:
        self.cleared = True


class _ResumeOwner(RunLoopMixin):
    def __init__(self, checkpoint: dict):
        self.resume_requested = True
        self.store = _ResumeStore(checkpoint)
        self.task_cfg = {"name": "task"}
        self.cfg = {}
        self.bt_settings = {}
        self._exec_gate = None


def test_run_refuses_provenance_mismatch_before_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {}
    checkpoint = {
        "run_id": "run-1", "task_name": "task", "config_hash": compute_config_hash(cfg),
        "payload": {"schema_version": 5, "provenance_digest": "old"},
    }
    monkeypatch.setattr("run_loop.probe_provenance", lambda *_a, **_k: {
        "provenance_digest": "new"
    })
    owner = _ResumeOwner(checkpoint)
    result = owner.run()
    assert result["status"] == "error"
    assert result["error_code"] == "resume_provenance_mismatch"
    assert owner.store.cleared is False
