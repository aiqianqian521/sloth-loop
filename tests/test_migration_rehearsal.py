"""Isolated up/down/backup/restore rehearsal for versioned migrations."""
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from memory_store import PatternStore  # noqa: E402
from migrate import main as migrate_main  # noqa: E402
from migrations import (DestructiveMigrationError, MIGRATIONS,
                        MigrationDriftError, MigrationRunner)  # noqa: E402


def _columns(path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_migration_rehearsal() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-migration-rehearsal-") as td:
        root = Path(td)
        database = root / "patterns.db"
        store = PatternStore(database)
        store.insert_l2_suggestion({
            "id": "rehearsal", "category": "test", "priority": "medium",
            "suggestion": "preserve me", "target_param": "exclusion_rule:F-1",
            "old_value": "old", "new_value": "new", "confidence": 0.7,
        })
        runner = MigrationRunner(database, MIGRATIONS)
        assert runner.current_version() == 6
        assert {"target_param", "old_value", "new_value", "confidence", "verify_result"}.issubset(
            _columns(database, "l2_suggestions"))
        assert _columns(database, "commit_sentinel") == {"seq", "scope", "committed_at"}

        backup = runner.backup(root / "backup.db")
        before = runner.integrity(database)
        assert before["integrity"] == "ok" and before["foreign_key_errors"] == 0
        assert runner.snapshot(database) == runner.snapshot(backup)
        assert not hasattr(runner, "adopt_legacy_ledger")

        try:
            runner.backup(database)
            raise AssertionError("same-path backup must be rejected")
        except ValueError:
            pass
        try:
            runner.backup(backup)
            raise AssertionError("existing backup must not be overwritten")
        except FileExistsError:
            pass
        missing_runner = MigrationRunner(root / "missing-source.db", MIGRATIONS)
        try:
            missing_runner.backup(root / "must-not-be-created.db")
            raise AssertionError("missing source must not create an empty database")
        except FileNotFoundError:
            pass
        assert not (root / "missing-source.db").exists()

        outside = root.parent / "outside-live.db"
        try:
            migrate_main([
                str(outside), "up", "--backup", str(root / "outside.bak"),
                "--allowed-root", str(root),
            ])
            raise AssertionError("mutating CLI must reject paths outside allowed root")
        except SystemExit as exc:
            assert exc.code == 2
        assert not outside.exists()

        source_ledger = runner.snapshot(database)["ledger"]
        original_backup = runner.backup
        def _corrupting_backup(destination):
            copied = original_backup(destination)
            conn = sqlite3.connect(copied)
            try:
                conn.execute("DELETE FROM l2_suggestions WHERE id='rehearsal'")
                conn.commit()
            finally:
                conn.close()
            return copied
        runner.backup = _corrupting_backup
        try:
            runner.apply_with_backup(root / "corrupt-backup.db")
            raise AssertionError("mismatched backup must block migration")
        except MigrationDriftError:
            pass
        finally:
            runner.backup = original_backup
        assert runner.snapshot(database)["ledger"] == source_ledger

        assert runner.rollback(2, allow_destructive=True) == [6, 5, 4, 3]
        assert runner.current_version() == 2
        assert "target_param" not in _columns(database, "l2_suggestions")
        assert "idempotency_signature" not in _columns(database, "run_checkpoints")
        conn = sqlite3.connect(database)
        try:
            assert conn.execute("SELECT suggestion FROM l2_suggestions WHERE id='rehearsal'").fetchone()[0] == "preserve me"
        finally:
            conn.close()

        assert runner.apply() == [3, 4, 5, 6]
        assert runner.current_version() == 6
        assert "target_param" in _columns(database, "l2_suggestions")
        assert "idempotency_signature" in _columns(database, "run_checkpoints")

        restored = runner.restore_copy(backup, root / "restored.db")
        restored_check = runner.integrity(restored)
        assert restored_check["integrity"] == "ok"
        assert restored_check["foreign_key_errors"] == 0
        assert restored_check["row_counts"] == before["row_counts"]

        chain_copy = runner.restore_copy(backup, root / "full-chain.db")
        chain_runner = MigrationRunner(chain_copy, MIGRATIONS)
        try:
            chain_runner.rollback(0)
            raise AssertionError("in-place down must require an explicit rehearsal gate")
        except DestructiveMigrationError:
            pass
        assert chain_runner.rollback(0, allow_destructive=True) == [6, 5, 4, 3, 2, 1]
        assert chain_runner.current_version() == 0
        assert chain_runner.apply() == [1, 2, 3, 4, 5, 6]
        assert chain_runner.integrity(chain_copy)["integrity"] == "ok"

        conn = sqlite3.connect(database)
        try:
            conn.execute("UPDATE schema_versions SET checksum='tampered' WHERE version=3")
            conn.commit()
        finally:
            conn.close()
        try:
            runner.rollback(2, allow_destructive=True)
            raise AssertionError("checksum drift should block rollback")
        except MigrationDriftError:
            pass

        conn = sqlite3.connect(database)
        try:
            conn.execute("UPDATE schema_versions SET checksum='' WHERE version=3")
            conn.commit()
        finally:
            conn.close()
        try:
            runner.apply()
            raise AssertionError("empty checksum must not bypass drift detection")
        except MigrationDriftError:
            pass
        before_empty_rollback = runner.snapshot(database)
        try:
            runner.rollback(2, allow_destructive=True)
            raise AssertionError("empty checksum must not bypass rollback preflight")
        except MigrationDriftError:
            pass
        assert runner.snapshot(database) == before_empty_rollback

        missing = root / "missing-backup.db"
        try:
            runner.restore_copy(missing, root / "must-not-exist.db")
            raise AssertionError("missing backup must be rejected")
        except FileNotFoundError:
            pass


def main() -> None:
    test_migration_rehearsal()
    print("PASS migration up/down + backup/restore rehearsal")


if __name__ == "__main__":
    main()
