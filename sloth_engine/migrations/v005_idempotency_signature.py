"""v5: W1-RESUME-01 idempotency_signature column on run_checkpoints.

Adds the signature component of the protocol-level idempotency key
(run_id + round + step + attempt + signature) so each step checkpoint records a
deterministic digest of its committed inputs -- auditable and replayable
without relying on in-memory flags (plan B P1.1; a "加固项": the data-pollution
surface is already closed by config_hash + run_learns + step-skip + pool_hash
gate; this column is the precision/auditability layer).

run_checkpoints is created by v2; v001..v004 run before v005 in the apply loop,
so the table exists on a fresh database and the ALTER works there too. SQLite
has no "ADD COLUMN IF NOT EXISTS": guard at the call site. Existing rows get ''
(no recorded signature), backward-compatible with the existing 4-tuple +
ledger + step-skip + pool_hash dedup.

The down migration is rehearsal-only (gated behind allow_destructive by the
runner): it rebuilds run_checkpoints without the column so it is portable
across SQLite versions (mirrors v2's table-rebuild down), preserving rows.
"""
from __future__ import annotations

import sqlite3

from .base import Migration


def _up(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(run_checkpoints)")}
    if "idempotency_signature" not in existing:
        conn.execute(
            "ALTER TABLE run_checkpoints "
            "ADD COLUMN idempotency_signature TEXT DEFAULT ''"
        )


def _down(conn: sqlite3.Connection) -> None:
    # Rehearsal-only. Rebuild run_checkpoints without idempotency_signature so
    # the down is portable across SQLite versions (mirrors v2's table-rebuild
    # down). Columns are reconstructed from PRAGMA table_info; existing rows are
    # copied by name so a rehearsed rollback preserves data.
    cols = list(conn.execute("PRAGMA table_info(run_checkpoints)"))
    keep = [c for c in cols if c[1] != "idempotency_signature"]
    decls = []
    for c in keep:
        name, ctype, notnull, dflt, pk = c[1], c[2], c[3], c[4], c[5]
        decl = f'"{name}" {ctype}'.strip()
        if pk:
            decl += " PRIMARY KEY"
        elif notnull:
            decl += " NOT NULL"
        if dflt is not None and dflt != "":
            decl += f" DEFAULT {dflt}"
        decls.append(decl)
    conn.execute("ALTER TABLE run_checkpoints RENAME TO run_checkpoints_v5_old")
    conn.execute(f'CREATE TABLE run_checkpoints ({", ".join(decls)})')
    names = ", ".join(f'"{c[1]}"' for c in keep)
    conn.execute(
        f"INSERT INTO run_checkpoints ({names}) "
        f"SELECT {names} FROM run_checkpoints_v5_old"
    )
    conn.execute("DROP TABLE run_checkpoints_v5_old")


MIGRATION = Migration(
    version=5,
    description="W1-RESUME-01 idempotency_signature column on run_checkpoints",
    up=_up,
    down=_down,
    fingerprint="add run_checkpoints.idempotency_signature (protocol idempotency-key signature); down rebuilds table without the column",
)
