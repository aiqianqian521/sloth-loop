"""Provenance and reproducibility contract tests.

These tests describe the public boundary between the real task bridge and
Loop's result contract.  They deliberately exercise the small fingerprint
seams in ``backtest.runtime_resolver`` and use a disposable bridge script for the
adapter test; no external runtime or credentials are required for the unit
cases.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from adapters.backtest_adapter import BacktestInput, configure, run_backtest  # noqa: E402
from runtime_exec import local_exec_gate  # noqa: E402
from adapters.task_runner import TaskInput, normalize_task_result  # noqa: E402
from backtest.runtime_resolver import (  # noqa: E402
    DataResolutionError,
    RuntimeResolutionError,
    build_provenance,
    fingerprint_file,
    fingerprint_runtime,
    resolve_data_path,
    resolve_runtime_root,
)
from run_once_pipeline import _compact_provenance_ref  # noqa: E402


def _runtime(root: Path) -> Path:
    """Create the minimum trusted runtime layout and deterministic source files."""
    for name in ("core", "signals", "backtest"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "core" / "indicators.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "signals" / "detector.py").write_text("VALUE = 2\n", encoding="utf-8")
    (root / "backtest" / "simulator.py").write_text("VALUE = 3\n", encoding="utf-8")
    return root


def test_fingerprint_file_is_stable_and_content_addressed(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_bytes(b"abc")
    fixed_ns = 1_700_000_000_000_000_000
    os.utime(path, ns=(fixed_ns, fixed_ns))

    first = fingerprint_file(path)
    second = fingerprint_file(path)

    assert first == second
    assert first["path"] == str(path.resolve())
    assert first["size_bytes"] == 3
    assert first["mtime_ns"] == fixed_ns
    assert first["sha256"] == hashlib.sha256(b"abc").hexdigest()

    # Same size and mtime, different bytes: the hash must still change.
    path.write_bytes(b"abd")
    os.utime(path, ns=(fixed_ns, fixed_ns))
    changed = fingerprint_file(path)
    assert changed["size_bytes"] == first["size_bytes"]
    assert changed["mtime_ns"] == first["mtime_ns"]
    assert changed["sha256"] != first["sha256"]


def test_fingerprint_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ValueError)):
        fingerprint_file(tmp_path / "missing.csv")


def test_runtime_fingerprint_uses_sorted_python_manifest(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    # Files outside the source manifest must not perturb the runtime identity.
    (runtime / "README.txt").write_text("ignored", encoding="utf-8")
    (runtime / "core" / "__pycache__").mkdir()
    (runtime / "core" / "__pycache__" / "ignored.py").write_text("x", encoding="utf-8")

    first = fingerprint_runtime(runtime)
    second = fingerprint_runtime(runtime)
    assert first == second
    assert first["path"] == str(runtime.resolve())
    source_files = [
        p
        for dirname in ("core", "signals", "backtest")
        for p in (runtime / dirname).rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    assert first["size_bytes"] == sum(p.stat().st_size for p in source_files)
    assert first["mtime_ns"] == max(
        p.stat().st_mtime_ns
        for p in source_files
    )

    before = first["sha256"]
    (runtime / "README.txt").write_text("a different ignored file", encoding="utf-8")
    assert fingerprint_runtime(runtime)["sha256"] == before

    source = runtime / "core" / "indicators.py"
    source.write_text("VALUE = 999\n", encoding="utf-8")
    assert fingerprint_runtime(runtime)["sha256"] != before


def test_build_provenance_has_versioned_runtime_and_data_fingerprints(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    data = tmp_path / "ETH_USDC_5m_fixture.csv"
    data.write_bytes(b"timestamp,open,high,low,close,volume\n")

    provenance = build_provenance(runtime, data)

    assert provenance["schema"] == "loop.provenance.v1"
    assert provenance.get("provenance_schema", "v1") == "v1"
    assert provenance.get("hash_algorithm", "sha256") == "sha256"
    resolver = provenance["resolver"]
    if isinstance(resolver, dict):
        assert resolver == {"name": "loop_runtime", "version": "v1"}
    else:
        assert resolver == "loop_runtime.v1"
    assert set(("runtime", "data")) <= provenance.keys()
    for item, expected in ((provenance["runtime"], runtime), (provenance["data"], data)):
        assert item["path"] == str(expected.resolve())
        assert isinstance(item["size_bytes"], int)
        assert isinstance(item["mtime_ns"], int)
        assert len(item["sha256"]) == 64
    runtime_meta = provenance["runtime"]
    assert runtime_meta["root"] == str(runtime.resolve())
    assert runtime_meta["resolved"] == str(runtime.resolve())
    assert runtime_meta["total_bytes"] == runtime_meta["size_bytes"]
    assert runtime_meta["manifest_sha256"] == runtime_meta["sha256"]
    assert runtime_meta["file_count"] == runtime_meta["source_file_count"]
    assert provenance["provenance_digest"]


def test_build_provenance_missing_inputs_fail_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    with pytest.raises((FileNotFoundError, ValueError, RuntimeResolutionError)):
        build_provenance(runtime, tmp_path / "missing.csv")
    with pytest.raises((FileNotFoundError, ValueError, RuntimeResolutionError)):
        build_provenance(tmp_path / "missing-runtime", tmp_path / "missing.csv")


def test_provenance_digest_excludes_paths_and_mtimes(tmp_path: Path) -> None:
    """The canonical digest is safe for resume/idempotency, not host paths."""
    runtime = _runtime(tmp_path / "runtime")
    data = tmp_path / "data.csv"
    data.write_bytes(b"same bytes")
    first = build_provenance(runtime, data)

    # Preserve bytes and sizes while changing volatile filesystem timestamps.
    new_ns = 1_900_000_000_000_000_000
    os.utime(data, ns=(new_ns, new_ns))
    for name in ("core", "signals", "backtest"):
        for source in (runtime / name).glob("*.py"):
            os.utime(source, ns=(new_ns, new_ns))
    second = build_provenance(runtime, data)

    assert second["data"]["mtime_ns"] != first["data"]["mtime_ns"]
    assert second["runtime"]["sha256"] == first["runtime"]["sha256"]
    assert second["provenance_digest"] == first["provenance_digest"]

    # The same bytes in a different checkout/data location have the same
    # canonical identity; absolute paths remain diagnostic metadata only.
    runtime_copy = tmp_path / "other-checkout" / "runtime"
    shutil.copytree(runtime, runtime_copy)
    data_copy = tmp_path / "other-checkout" / "data.csv"
    shutil.copy2(data, data_copy)
    relocated = build_provenance(runtime_copy, data_copy)
    assert relocated["runtime"]["path"] != first["runtime"]["path"]
    assert relocated["data"]["path"] != first["data"]["path"]
    assert relocated["provenance_digest"] == first["provenance_digest"]


def test_backtest_adapter_merges_bridge_provenance_under_source(tmp_path: Path) -> None:
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        "import json, sys\n"
        "args = iter(sys.argv[1:])\n"
        "opts = dict(zip(args, args))\n"
        "argv = sys.argv\n"
        "inp = argv[argv.index('--input') + 1]\n"
        "out = argv[argv.index('--output') + 1]\n"
        "json.dump({'trades':[{'signal_pattern':'fixture','pnl':1.0}],"
        "'pnl':{'total':1.0},'win_rate':'100%','sharpe':1.0,"
        "'provenance':{'schema':'loop.provenance.v1','provenance_schema':'v1',"
        "'hash_algorithm':'sha256','resolver':{'name':'loop_runtime','version':'v1'},"
        "'runtime':{'path':'runtime','size_bytes':3,'mtime_ns':7,'sha256':'r'*64},"
        "'data':{'path':'data.csv','size_bytes':4,'mtime_ns':8,'sha256':'d'*64}}},"
        "open(out,'w'), indent=2)\n",
        encoding="utf-8",
    )
    settings = configure({"script": str(bridge)}, ROOT, io_dir=tmp_path / "io")
    result = run_backtest(
        BacktestInput(signals=[{"signal_pattern": "fixture"}]), settings,
        exec_gate=local_exec_gate(tmp_path),
    )

    assert result.status == "completed"
    source = result.provenance["source"]
    assert source["schema"] == "loop.provenance.v1"
    assert source["provenance_schema"] == "v1"
    assert source["runtime"]["sha256"] == "r" * 64
    assert source["data"]["sha256"] == "d" * 64
    assert result.provenance["script"].endswith("bridge.py")
    assert "source" not in result.metrics


def test_normalize_task_result_preserves_source_and_adds_context() -> None:
    bridge_source = {
        "schema": "loop.provenance.v1",
        "resolver": "loop_runtime.v1",
        "runtime": {"path": "runtime", "size_bytes": 1, "mtime_ns": 2, "sha256": "r" * 64},
        "data": {"path": "data.csv", "size_bytes": 2, "mtime_ns": 3, "sha256": "d" * 64},
    }
    result = normalize_task_result(
        {
            "status": "completed",
            "provenance": {"source": bridge_source, "custom": "preserve"},
        },
        adapter="backtest",
        entry="task_bridge",
        task_input=TaskInput(task_type="backtest", signals=[{"signal_pattern": "x"}]),
    )

    assert result.provenance["source"] == bridge_source
    assert result.provenance["custom"] == "preserve"
    assert result.provenance["adapter"] == "backtest"
    assert result.provenance["entry"] == "task_bridge"
    assert result.provenance["task_type"] == "backtest"
    assert result.provenance["signal_count"] == 1


def test_event_log_provenance_ref_is_compact_and_path_free() -> None:
    result = SimpleNamespace(provenance={
        "source": {
            "schema": "loop.provenance.v1",
            "resolver": "loop_runtime.v1",
            "provenance_digest": "p" * 64,
            "runtime": {"manifest_sha256": "r" * 64},
            "data": {"path": r"E:\secret\prices.csv", "sha256": "d" * 64},
        }
    })
    ref = _compact_provenance_ref(result)
    assert ref["provenance_digest"] == "p" * 64
    assert ref["runtime_sha256"] == "r" * 64
    assert ref["data_sha256"] == "d" * 64
    assert ref["data_name"] == "prices.csv"
    assert "secret" not in json.dumps(ref)

