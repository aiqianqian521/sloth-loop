"""Acceptance tests for the migration backup/restore rehearsal CLI.

These tests intentionally describe the operator-facing contract for the
rehearsal command. They are RED until ``scripts/migration_rehearsal.py``
implements the contract; the normal runtime and live database are never
used. The command must emit one JSON document so RPO/RTO evidence can be
archived by CI or an operator runbook.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
SCRIPT = ROOT / "scripts" / "migration_rehearsal.py"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from memory_store import PatternStore  # noqa: E402


def _seed_database(path: Path) -> None:
    """Create a realistic, committed Loop database in an isolated directory."""
    store = PatternStore(path)
    store.insert_l2_suggestion({
        "id": "rto-rpo-marker", "category": "migration-rehearsal", "priority": "high",
        "suggestion": "committed-before-fault", "target_param": "recovery",
        "old_value": "before", "new_value": "after", "confidence": 0.99,
    })
    store.log_round(1, 0, 1, 0, 0, notes="rpo-marker")


def _run_cli(database: Path, work_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([
        sys.executable, str(SCRIPT), "--database", str(database),
        "--work-dir", str(work_dir), "--json",
    ], cwd=str(ROOT), text=True, capture_output=True, check=False)


def _result(proc: subprocess.CompletedProcess[str]) -> dict:
    assert proc.returncode == 0, proc.stderr or proc.stdout
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise AssertionError(f"rehearsal must emit JSON, got: {proc.stdout!r}") from exc


def test_cli_emits_backup_checksum_and_migration_evidence(tmp_path: Path) -> None:
    database, work_dir = tmp_path / "patterns.db", tmp_path / "rehearsal"
    _seed_database(database)
    result = _result(_run_cli(database, work_dir))
    assert result["status"] in {"ok", "passed"}
    backup = Path(result["backup"]["path"])
    assert backup.is_file()
    digest = result["backup"]["sha256"]
    assert len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == digest
    before_version = result["migration"].get("before_version", result["source"]["schema_version"])
    after_version = result["migration"].get(
        "after_version", result["migration"].get("up_version", result["migration"]["latest"])
    )
    assert before_version <= after_version
    assert result["migration"]["applied"]


def test_cli_restore_is_complete_and_preserves_business_rows(tmp_path: Path) -> None:
    database, work_dir = tmp_path / "patterns.db", tmp_path / "rehearsal"
    _seed_database(database)
    result = _result(_run_cli(database, work_dir))
    restored = Path(result["restore"]["path"])
    assert restored.is_file()
    assert result["restore"]["integrity"] == "ok"
    assert result["restore"]["foreign_key_errors"] == 0
    assert result["restore"]["row_counts"] == result["backup"]["row_counts"]
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT suggestion FROM l2_suggestions WHERE id='rto-rpo-marker'").fetchone()[0] == "committed-before-fault"


def test_cli_rejects_corrupted_backup_before_restore(tmp_path: Path) -> None:
    database, work_dir = tmp_path / "patterns.db", tmp_path / "rehearsal"
    _seed_database(database)
    first = _result(_run_cli(database, work_dir))
    backup = Path(first["backup"]["path"])
    original = backup.read_bytes()
    backup.write_bytes(original[: max(1, len(original) // 2)] + b"corrupted")
    proc = subprocess.run([
        sys.executable, str(SCRIPT), "--database", str(database),
        "--work-dir", str(work_dir / "corrupt-attempt"), "--backup", str(backup),
        "--restore-only", "--json",
    ], cwd=str(ROOT), text=True, capture_output=True, check=False)
    assert proc.returncode != 0
    payload = json.loads(proc.stdout or proc.stderr)
    assert payload["error"]["code"] in {"backup_checksum_mismatch", "backup_integrity_failed"}


def test_cli_records_rto_rpo_evidence(tmp_path: Path) -> None:
    database, work_dir = tmp_path / "patterns.db", tmp_path / "rehearsal"
    _seed_database(database)
    started = time.perf_counter()
    result = _result(_run_cli(database, work_dir))
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert isinstance(result["rto_ms"], (int, float))
    assert 0 <= result["rto_ms"] <= elapsed_ms + 1000
    rpo = result.get("rpo", {
        "last_committed": result.get("rpo_last_committed"),
        "business_sample": result.get("rpo_last_committed", 0),
    })
    assert rpo["last_committed"]
    assert rpo["business_sample"] >= 1
    evidence = Path(result["evidence_path"])
    assert evidence.is_file()
    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_payload["rto_ms"] == result["rto_ms"]
    assert evidence_payload["rpo"] == rpo


def test_cli_rpo_is_a_verified_time_point(tmp_path: Path) -> None:
    """RPO must be a business instant, not a row-count proxy."""
    database, work_dir = tmp_path / "patterns.db", tmp_path / "rehearsal"
    _seed_database(database)
    rpo = _result(_run_cli(database, work_dir))["rpo"]
    assert rpo["mode"] == "sentinel_timestamp"
    assert rpo["verified"] is True
    assert rpo["sentinel_table"] == "commit_sentinel"
    # A time point: the cutoff is an ISO-8601 UTC instant.
    assert rpo["backup_cutoff"].endswith("Z")
    assert rpo["restored_last_committed"] <= rpo["backup_cutoff"]
    assert rpo["restores_to_cutoff"] is True
    # The rehearsal commits real business rows after the cutoff, so a restore of
    # the cutoff backup must lose exactly those units and nothing else.
    assert rpo["units_after_cutoff"] >= 1
    assert rpo["units_lost_on_restore"] == rpo["units_after_cutoff"]
    assert isinstance(rpo["window_ms"], (int, float)) and rpo["window_ms"] >= 0


def test_cli_requires_isolated_work_dir(tmp_path: Path) -> None:
    database = tmp_path / "patterns.db"
    _seed_database(database)
    proc = subprocess.run([
        sys.executable, str(SCRIPT), "--database", str(database),
        # A database file is not an acceptable workspace for destructive
        # rehearsal artifacts; this also guards against in-place migration.
        "--work-dir", str(database), "--json",
    ], cwd=str(ROOT), text=True, capture_output=True, check=False)
    assert proc.returncode != 0
    assert "isolated" in (proc.stdout + proc.stderr).lower()


def test_cli_rejects_missing_database_without_creating_it(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.db"
    proc = subprocess.run([
        sys.executable, str(SCRIPT), "--database", str(missing),
        "--work-dir", str(tmp_path / "rehearsal"), "--json",
    ], cwd=str(ROOT), text=True, capture_output=True, check=False)
    assert proc.returncode != 0
    assert not missing.exists()
    payload = json.loads(proc.stdout or proc.stderr)
    assert payload.get("error_code") in {"FileNotFoundError", "source_missing"}
