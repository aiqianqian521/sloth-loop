"""Safe, repeatable SQLite migration recovery rehearsal.

The source database is never migrated in place.  All destructive operations
run on copies below ``work_dir`` and every copy is validated before it is
accepted as evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .sloth_engine_path import ensure_engine_imports
except ImportError:  # direct ``python scripts/migration_rehearsal.py`` execution
    from sloth_engine_path import ensure_engine_imports

ensure_engine_imports()
from migrations import MIGRATIONS, MigrationRunner  # noqa: E402
from memory_store import PatternStore  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_database(source: Path, destination: Path) -> Path:
    if destination.exists():
        raise FileExistsError(f"rehearsal artifact already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _row_count(snapshot: dict[str, Any]) -> int:
    return sum(int(value) for value in (snapshot.get("row_counts") or {}).values())
_RPO_SIMULATED_COMMITS = 3
_RPO_COMMIT_SETTLE_SECONDS = 0.02


def _sentinel_rows(path: Path, sql: str, params: tuple = ()) -> list:
    """One seam for read-only sentinel queries; always closes its connection."""
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _sentinel_present(path: Path) -> bool:
    return bool(_sentinel_rows(
        path, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='commit_sentinel'"))


def _sentinel_watermark(path: Path) -> "tuple[int, str] | None":
    """Newest (seq, committed_at) in *path*; None when no unit is committed."""
    rows = _sentinel_rows(
        path, "SELECT seq, committed_at FROM commit_sentinel ORDER BY seq DESC LIMIT 1")
    return (int(rows[0][0]), str(rows[0][1])) if rows else None


def _parse_utc(value: "str | None"):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return None


def _window_ms(earlier: "str | None", later: "str | None") -> float:
    start, end = _parse_utc(earlier), _parse_utc(later)
    if start is None or end is None:
        return 0.0
    return round((end - start).total_seconds() * 1000, 3)


def _rehearse_rpo(live: Path, live_runner: MigrationRunner, work: Path,
                  source_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Measure the recovery point in business time, not in rows.

    Honest about what it proves: on an *isolated copy* it records the sentinel
    watermark at backup time ("cutoff"), commits real business rows after the
    cutoff, restores from the cutoff backup, and asserts the restored copy
    reproduces exactly the cutoff watermark.  A missing sentinel table is
    fail-closed -- without it there is no time point to recover to.
    """
    work.mkdir(parents=True, exist_ok=True)
    if not _sentinel_present(live):
        raise RuntimeError(
            "commit_sentinel missing on the migrated copy; RPO cannot be verified")
    cutoff = _sentinel_watermark(live)
    cutoff_backup = live_runner.backup(work / "rpo-cutoff.db")
    store = PatternStore(live)
    for index in range(_RPO_SIMULATED_COMMITS):
        time.sleep(_RPO_COMMIT_SETTLE_SECONDS)
        store.insert_l2_suggestion({
            "id": f"rpo-post-cutoff-{index}", "category": "migration-rehearsal",
            "priority": "low", "suggestion": "committed after the backup cutoff",
        })
    after_cutoff = _sentinel_watermark(live)
    restored_copy = MigrationRunner.restore_copy(cutoff_backup, work / "rpo-restored.db")
    restored = _sentinel_watermark(restored_copy)
    cutoff_seq = cutoff[0] if cutoff else 0
    live_seq = after_cutoff[0] if after_cutoff else 0
    restored_seq = restored[0] if restored else 0
    units_after = live_seq - cutoff_seq
    units_lost = live_seq - restored_seq
    restores_to_cutoff = restored == cutoff
    if not restores_to_cutoff:
        raise RuntimeError(
            "RPO rehearsal failed: restored sentinel differs from the backup cutoff")
    if units_after <= 0:
        raise RuntimeError(
            "RPO rehearsal failed: post-cutoff business writes produced no sentinel")
    return {
        "mode": "sentinel_timestamp",
        "verified": True,
        "sentinel_table": "commit_sentinel",
        "backup_cutoff": cutoff[1] if cutoff else None,
        "backup_cutoff_seq": cutoff[0] if cutoff else None,
        "restored_last_committed": restored[1] if restored else None,
        "last_committed": restored[1] if restored else None,
        "live_last_committed": after_cutoff[1] if after_cutoff else None,
        "business_sample": max(int(source_snapshot["row_counts"].get("l2_suggestions", 0)), 1),
        "units_after_cutoff": units_after,
        "units_lost_on_restore": units_lost,
        "window_ms": _window_ms(cutoff[1] if cutoff else None,
                                after_cutoff[1] if after_cutoff else None),
        "restores_to_cutoff": restores_to_cutoff,
    }




def run_rehearsal(db_path: str | Path, work_dir: str | Path) -> dict[str, Any]:
    """Run backup, forward migration, rollback-copy and restore checks."""
    source = Path(db_path).resolve()
    work = Path(work_dir).resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f"source database does not exist or is empty: {source}")
    if work == source.parent or work.suffix.lower() == ".db":
        raise ValueError("work_dir must be an isolated directory, not the source database or a .db path")
    work.mkdir(parents=True, exist_ok=True)

    runner = MigrationRunner(source, MIGRATIONS)
    source_snapshot = runner.snapshot(source)
    if source_snapshot["integrity"] != "ok" or source_snapshot["foreign_key_errors"]:
        raise RuntimeError("source database failed integrity preflight")
    source_sha = _sha256(source)

    backup = runner.backup(work / "backup-source.db")
    backup_sha = _sha256(backup)
    (backup.with_name(backup.name + ".sha256")).write_text(
        json.dumps({"sha256": backup_sha, "size_bytes": backup.stat().st_size}, sort_keys=True),
        encoding="utf-8",
    )
    backup_snapshot = runner.snapshot(backup)
    if backup_snapshot != source_snapshot:
        raise RuntimeError("backup snapshot differs from source")

    upgraded = _copy_database(backup, work / "upgrade.db")
    upgrade_runner = MigrationRunner(upgraded, MIGRATIONS)
    latest = max(item.version for item in MIGRATIONS)
    if upgrade_runner.current_version() < latest:
        upgrade_runner.apply(latest)
    # Force one reversible down/up cycle on the isolated copy.
    down_target = max(0, latest - 1)
    rolled_back = upgrade_runner.rollback(down_target, allow_destructive=True)
    down_snapshot = upgrade_runner.snapshot(upgraded)
    if down_snapshot["integrity"] != "ok" or upgrade_runner.current_version() != down_target:
        raise RuntimeError("isolated rollback validation failed")
    before_up_backup = work / "upgrade-before-up.db"
    applied = upgrade_runner.apply_with_backup(before_up_backup, latest)
    upgraded_snapshot = upgrade_runner.snapshot(upgraded)
    if upgraded_snapshot["integrity"] != "ok" or upgrade_runner.current_version() != latest:
        raise RuntimeError("isolated forward migration validation failed")

    restore_target = work / "restored.db"
    restore_started = time.perf_counter()
    restored = runner.restore_copy(backup, restore_target)
    restored_snapshot = runner.snapshot(restored)
    rto_ms = round((time.perf_counter() - restore_started) * 1000, 3)
    if restored_snapshot != source_snapshot:
        raise RuntimeError("restored snapshot differs from source")

    # RPO: prove the recovery point in business time on the isolated copy.
    rpo = _rehearse_rpo(upgraded, upgrade_runner, work / "rpo", source_snapshot)

    return {
        "status": "passed",
        "source": {
            "path": str(source),
            "sha256": source_sha,
            "schema_version": runner.inspect_current_version(),
            "row_counts": source_snapshot["row_counts"],
        },
        "backup": {
            "path": str(backup),
            "sha256": backup_sha,
            "source_sha256": source_sha,
            "matches_source": backup_snapshot == source_snapshot,
            "row_counts": backup_snapshot["row_counts"],
        },
        "migration": {
            "latest": latest,
            "rolled_back": rolled_back,
            "applied": applied,
            "down_version": down_target,
            "up_version": upgrade_runner.current_version(),
        },
        "restore": {
            "path": str(restored),
            "integrity": restored_snapshot["integrity"],
            "foreign_key_errors": restored_snapshot["foreign_key_errors"],
            "row_counts": restored_snapshot["row_counts"],
            "matches_source": restored_snapshot == source_snapshot,
        },
        "rto_ms": rto_ms,
        "rpo": rpo,
        "rpo_last_committed": _row_count(source_snapshot),
        "work_dir": str(work),
    }



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loop migration recovery rehearsal")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--backup", type=Path, default=None,
                        help="verified backup for --restore-only")
    parser.add_argument("--restore-only", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    try:
        if args.restore_only:
            if args.backup is None:
                raise ValueError("--restore-only requires --backup")
            backup = args.backup.resolve()
            sidecar = backup.with_name(backup.name + ".sha256")
            if sidecar.is_file():
                expected = json.loads(sidecar.read_text(encoding="utf-8")).get("sha256", "")
                if expected and _sha256(backup) != expected:
                    raise ValueError("backup_checksum_mismatch")
            check = MigrationRunner.integrity(backup)
            if check["integrity"] != "ok" or check["foreign_key_errors"]:
                raise RuntimeError("backup_integrity_failed")
            work = Path(args.work_dir).resolve()
            if work == Path(args.database).resolve().parent or work.suffix.lower() == ".db":
                raise ValueError("work_dir must be an isolated directory")
            work.mkdir(parents=True, exist_ok=True)
            restored = MigrationRunner.restore_copy(backup, work / "restored.db")
            result = {"status": "ok", "restore": {"path": str(restored), **MigrationRunner.integrity(restored)}}
        else:
            result = run_rehearsal(args.database, args.work_dir)
            result["status"] = "ok"
            evidence = Path(args.work_dir).resolve() / "rehearsal-evidence.json"
            evidence.write_text(json.dumps({"rto_ms": result["rto_ms"], "rpo": result["rpo"]},
                                            ensure_ascii=False, sort_keys=True), encoding="utf-8")
            result["evidence_path"] = str(evidence)
    except Exception as exc:
        code = "backup_checksum_mismatch" if str(exc) == "backup_checksum_mismatch" else (
            "backup_integrity_failed" if str(exc) == "backup_integrity_failed" else type(exc).__name__)
        result = {"status": "failed", "error_code": code,
                  "error": {"code": code, "message": str(exc)}}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print(result)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
