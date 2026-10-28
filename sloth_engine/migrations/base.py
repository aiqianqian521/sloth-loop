"""Versioned SQLite migration primitives with reversible execution."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

MigrationFn = Callable[[sqlite3.Connection], None]


class _ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    up: MigrationFn
    down: MigrationFn
    fingerprint: str

    @property
    def checksum(self) -> str:
        def implementation(fn: MigrationFn) -> str:
            try:
                module = inspect.getmodule(fn)
                if module is not None and module.__name__ != __name__:
                    return inspect.getsource(module)
                return inspect.getsource(fn)
            except (OSError, TypeError):
                code = getattr(fn, "__code__", None)
                return repr((getattr(code, "co_code", b""), getattr(code, "co_consts", ())))
        payload = (f"{self.version}\n{self.description}\n{self.fingerprint}\n"
                   f"{implementation(self.up)}\n{implementation(self.down)}")
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MigrationDriftError(RuntimeError):
    pass


class DestructiveMigrationError(RuntimeError):
    pass


class MigrationRunner:
    def __init__(self, db_path: str | Path, migrations: tuple[Migration, ...]):
        self.db_path = Path(db_path)
        self.migrations = tuple(sorted(migrations, key=lambda item: item.version))
        versions = [item.version for item in self.migrations]
        if len(versions) != len(set(versions)):
            raise ValueError("Duplicate migration versions")
        if versions and versions != list(range(versions[0], versions[-1] + 1)):
            raise ValueError(f"Migration versions must be contiguous: {versions}")

    @staticmethod
    def _open(path, *, wal: bool = True) -> sqlite3.Connection:
        """One-seam connection policy: timeout + WAL(optional) + foreign_keys +
        busy_timeout + managed factory. _connect and all static backup/integrity/
        snapshot paths route here so no call site omits lock backoff or (main db)
        WAL. W1-STORE-01."""
        conn = sqlite3.connect(str(path), timeout=30, factory=_ManagedConnection)
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _connect(self) -> sqlite3.Connection:
        return MigrationRunner._open(self.db_path)

    @staticmethod
    def _ensure_ledger(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT DEFAULT '',
                checksum TEXT DEFAULT '',
                status TEXT DEFAULT 'applied'
            )
        """)

    def apply(self, target_version: int | None = None) -> list[int]:
        applied = []
        with self._connect() as conn:
            self._ensure_ledger(conn)
            rows = {int(row[0]): (row[1] or "", row[2] or "") for row in conn.execute(
                "SELECT version, checksum, status FROM schema_versions")}
            by_version = {item.version: item for item in self.migrations}
            for version, (stored_checksum, status) in rows.items():
                if status != "applied":
                    continue
                migration = by_version.get(version)
                if migration is None:
                    raise MigrationDriftError(f"No migration registered for applied v{version}")
                if not stored_checksum:
                    raise MigrationDriftError(
                        f"Migration v{version} has no checksum; explicit offline ledger rebuild required")
                if stored_checksum != migration.checksum:
                    raise MigrationDriftError(
                        f"Migration v{version} checksum drift: {stored_checksum} != {migration.checksum}")
            for migration in self.migrations:
                if target_version is not None and migration.version > target_version:
                    break
                stored = rows.get(migration.version)
                if stored and stored[1] == "applied":
                    continue
                conn.execute("BEGIN IMMEDIATE")
                try:
                    migration.up(conn)
                    conn.execute("""
                        INSERT INTO schema_versions(version, applied_at, description, checksum, status)
                        VALUES(?,?,?,?, 'applied')
                        ON CONFLICT(version) DO UPDATE SET
                          applied_at=excluded.applied_at,
                          description=excluded.description,
                          checksum=excluded.checksum,
                          status='applied'
                    """, (migration.version, datetime.now().isoformat(),
                          migration.description, migration.checksum))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                applied.append(migration.version)
        return applied

    def rollback(self, target_version: int, *, allow_destructive: bool = False) -> list[int]:
        if not allow_destructive:
            raise DestructiveMigrationError(
                "down migrations are rehearsal-only; restore a verified backup or use a forward fix")
        rolled_back = []
        by_version = {item.version: item for item in self.migrations}
        with self._connect() as conn:
            self._ensure_ledger(conn)
            rows = list(conn.execute(
                "SELECT version, checksum FROM schema_versions WHERE status='applied' AND version>? ORDER BY version DESC",
                (target_version,)))
            # Validate the complete chain before the first destructive step so
            # rollback cannot stop half-way through an unknown/drifted version.
            for version, stored_checksum in rows:
                migration = by_version.get(int(version))
                if migration is None:
                    raise MigrationDriftError(f"No down migration registered for applied v{version}")
                if not stored_checksum:
                    raise MigrationDriftError(
                        f"Migration v{version} has no checksum; rollback blocked")
                if stored_checksum != migration.checksum:
                    raise MigrationDriftError(f"Migration v{version} checksum drift; rollback blocked")
            conn.execute("BEGIN IMMEDIATE")
            try:
                for version, stored_checksum in rows:
                    migration = by_version[int(version)]
                    migration.down(conn)
                    conn.execute("UPDATE schema_versions SET status='rolled_back' WHERE version=?", (version,))
                    rolled_back.append(int(version))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return rolled_back

    def current_version(self) -> int:
        with self._connect() as conn:
            self._ensure_ledger(conn)
            row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_versions WHERE status='applied'").fetchone()
        return int(row[0] if row else 0)

    def inspect_current_version(self) -> int:
        """Read the ledger without creating or changing any schema."""
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return 0
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_versions'"
            ).fetchone()
            if not exists:
                return 0
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_versions WHERE status='applied'"
            ).fetchone()
        return int(row[0] if row else 0)

    def backup(self, destination: str | Path) -> Path:
        destination = Path(destination)
        if not self.db_path.is_file() or self.db_path.stat().st_size == 0:
            raise FileNotFoundError(f"source database does not exist: {self.db_path}")
        if destination.resolve() == self.db_path.resolve():
            raise ValueError("backup destination must differ from source database")
        if destination.exists():
            try:
                if os.path.samefile(self.db_path, destination):
                    raise ValueError("backup destination resolves to the source database")
            except OSError:
                pass
            raise FileExistsError(f"backup destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, MigrationRunner._open(destination, wal=False) as target:
            source.backup(target)
        return destination

    def apply_with_backup(self, destination: str | Path,
                          target_version: int | None = None) -> list[int]:
        before = self.snapshot(self.db_path)
        if before["integrity"] != "ok" or before["foreign_key_errors"]:
            raise MigrationDriftError("source database failed pre-migration integrity checks")
        backup = self.backup(destination)
        backup_snapshot = self.snapshot(backup)
        if backup_snapshot != before:
            raise MigrationDriftError(
                "backup snapshot does not match source; migration was not started")
        applied = self.apply(target_version)
        after = self.snapshot(self.db_path)
        if after["integrity"] != "ok" or after["foreign_key_errors"]:
            raise MigrationDriftError("database failed post-migration integrity checks; restore backup")
        return applied

    @staticmethod
    def restore_copy(backup_path: str | Path, destination: str | Path) -> Path:
        backup_path, destination = Path(backup_path), Path(destination)
        if not backup_path.is_file() or backup_path.stat().st_size == 0:
            raise FileNotFoundError(f"verified backup does not exist: {backup_path}")
        source_check = MigrationRunner.integrity(backup_path)
        if source_check["integrity"] != "ok" or source_check["foreign_key_errors"]:
            raise MigrationDriftError("backup failed integrity checks")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.restore-{uuid.uuid4().hex}.tmp")
        try:
            with MigrationRunner._open(backup_path, wal=False) as source, \
                    MigrationRunner._open(temporary, wal=False) as target:
                source.backup(target)
            restored_check = MigrationRunner.integrity(temporary)
            if (restored_check["integrity"] != "ok"
                    or restored_check["foreign_key_errors"]
                    or restored_check["row_counts"] != source_check["row_counts"]
                    or MigrationRunner.schema_fingerprint(temporary)
                    != MigrationRunner.schema_fingerprint(backup_path)):
                raise MigrationDriftError("restored copy failed post-restore validation")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return destination

    @staticmethod
    def integrity(path: str | Path) -> dict:
        path = Path(path)
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"database does not exist or is empty: {path}")
        with MigrationRunner._open(path, wal=False) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            tables = {row[0]: conn.execute(f'SELECT COUNT(*) FROM "{row[0]}"').fetchone()[0]
                      for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        return {"integrity": integrity, "foreign_key_errors": len(foreign_keys), "row_counts": tables}

    @staticmethod
    def schema_fingerprint(path: str | Path) -> str:
        """Return a stable structural fingerprint for backup/restore comparison."""
        path = Path(path)
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"database does not exist or is empty: {path}")
        with MigrationRunner._open(path, wal=False) as conn:
            objects = []
            rows = conn.execute(
                "SELECT type, name, tbl_name, COALESCE(sql, '') FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
            for obj_type, name, table, sql in rows:
                item = {"type": obj_type, "name": name, "table": table,
                        "sql": " ".join(sql.split())}
                if obj_type == "table":
                    item["columns"] = conn.execute(
                        f'PRAGMA table_info("{name}")').fetchall()
                    item["foreign_keys"] = conn.execute(
                        f'PRAGMA foreign_key_list("{name}")').fetchall()
                    item["indexes"] = conn.execute(
                        f'PRAGMA index_list("{name}")').fetchall()
                objects.append(item)
        payload = json.dumps(objects, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), default=str)
        return "schema-v1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def snapshot(cls, path: str | Path) -> dict:
        snapshot = cls.integrity(path)
        snapshot["schema_fingerprint"] = cls.schema_fingerprint(path)
        with MigrationRunner._open(path, wal=False) as conn:
            ledger_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_versions'"
            ).fetchone()
            snapshot["ledger"] = (conn.execute(
                "SELECT version, description, checksum, status FROM schema_versions ORDER BY version"
            ).fetchall() if ledger_exists else [])
        return snapshot
