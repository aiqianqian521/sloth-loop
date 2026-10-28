"""Explicit SQLite migration command; never imported by normal runtime startup."""
from __future__ import annotations

import argparse
from pathlib import Path

from migrations import MIGRATIONS, MigrationRunner


def _require_within(path: Path, root: Path, parser: argparse.ArgumentParser) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        parser.error(f"migration path escapes --allowed-root: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loop SQLite migration gate")
    parser.add_argument("database", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    up = sub.add_parser("up")
    up.add_argument("--backup", type=Path, required=True)
    up.add_argument("--target", type=int, default=None)
    up.add_argument("--allowed-root", type=Path, required=True)
    down = sub.add_parser("rehearse-down")
    down.add_argument("--copy", type=Path, required=True)
    down.add_argument("--target", type=int, required=True)
    down.add_argument("--allowed-root", type=Path, required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--allowed-root", type=Path, required=True)
    args = parser.parse_args(argv)

    runner = MigrationRunner(args.database, MIGRATIONS)
    if args.command == "status":
        print({"current": runner.inspect_current_version(),
               "latest": max(item.version for item in MIGRATIONS),
               "integrity": runner.integrity(args.database)})
        return 0
    _require_within(args.database, args.allowed_root, parser)
    if args.command == "up":
        _require_within(args.backup, args.allowed_root, parser)
        print({"backup": str(args.backup),
               "applied": runner.apply_with_backup(args.backup, args.target),
               "integrity": runner.integrity(args.database)})
        return 0
    if args.command == "rehearse-down":
        _require_within(args.copy, args.allowed_root, parser)
        if args.copy.resolve() == args.database.resolve():
            parser.error("--copy must be an isolated database path, not the source database")
        runner.backup(args.copy)
        copy_runner = MigrationRunner(args.copy, MIGRATIONS)
        print({"copy": str(args.copy),
               "rolled_back": copy_runner.rollback(args.target, allow_destructive=True),
               "integrity": copy_runner.integrity(args.copy)})
        return 0
    _require_within(args.backup, args.allowed_root, parser)
    _require_within(args.destination, args.allowed_root, parser)
    restored = runner.restore_copy(args.backup, args.destination)
    print({"restored": str(restored), "integrity": runner.integrity(restored)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
