"""W1-RESUME-01: resume compatibility guard (pure helpers).

Keeping resume's 4-tuple check pure + side-effect-free makes it independently
unit-testable without booting the full Orchestrator (architect-test: test at
the seam, don't mock internals).

architect-agent mandate: "状态恢复必须校验 schema_version、task_id 和幂等键，
拒绝恢复过期或跨 scope 的 checkpoint。" Without this, a crash->restart with a
changed config.yaml silently resumes with a stale cursor/breaker and replays a
round -> duplicate Learn -> PatternStore pollution (scheme critical ③, matches
reeaudit-2026-08-22 R2).

Invariants are know-before-the-loop (config_hash, schema_version, task identity);
pool_hash can only be compared AFTER the signal pool is rebuilt, so callers
validate at two points: (1) on load via check_compatibility, (2) after pool
rebuild via pool_matches.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["compute_config_hash", "compute_signature", "compute_pool_hash",
           "check_compatibility", "check_provenance_compatibility",
           "extract_provenance_digest", "pool_matches"]


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def compute_config_hash(cfg: Any) -> str:
    """Stable digest of the merged config dict (DEFAULT_CONFIG + user cfg).

    The Orchestrator stores this in run_checkpoints.config_hash at save time;
    recomputing on resume with the freshly-loaded config and comparing detects
    config drift between crash and restart.
    """
    return _sha(cfg)


def compute_pool_hash(pool: Any) -> str:
    return _sha(pool or [])


def compute_signature(obj: Any) -> str:
    """Stable digest of a step-checkpoint idempotency-key component.

    Single source of truth shared with compute_config_hash / compute_pool_hash
    (_sha: sha256 over sorted-key json). The Orchestrator feeds
    {"step","round","cursor","artifacts"} so the protocol idempotency key
    (run_id + round + step + attempt + signature) is auditable and any input
    change flips the signature. Pure + side-effect-free so it is unit-testable
    in isolation (architect-test: test at the seam).
    """
    return _sha(obj)


def extract_provenance_digest(value: Any) -> str:
    """Extract a provenance digest from a checkpoint, result, or payload."""
    if isinstance(value, dict):
        direct = value.get("provenance_digest")
        if direct:
            return str(direct)
        provenance = value.get("provenance")
        if isinstance(provenance, dict):
            direct = provenance.get("provenance_digest")
            if direct:
                return str(direct)
            nested_source = provenance.get("source")
            if isinstance(nested_source, dict):
                digest = extract_provenance_digest(nested_source)
                if digest:
                    return digest
        task_result = value.get("task_result")
        if task_result is not None:
            return extract_provenance_digest(task_result)
        artifacts = value.get("artifacts")
        if isinstance(artifacts, dict):
            for artifact in artifacts.values():
                digest = extract_provenance_digest(artifact)
                if digest:
                    return digest
        payload = value.get("payload")
        if isinstance(payload, dict):
            return extract_provenance_digest(payload)
        return ""
    provenance = getattr(value, "provenance", None)
    if isinstance(provenance, dict):
        return str(provenance.get("provenance_digest") or "")
    return ""


def check_provenance_compatibility(
    stored_digest: str | None,
    current_digest: str | None,
) -> tuple[bool, str]:
    """Compare content identity for a resumable checkpoint.

    A legacy checkpoint without a digest remains compatible.  Once a digest
    exists, a missing or different current digest is a hard refusal so resume
    cannot silently replay work against another runtime/data version.
    """
    stored = str(stored_digest or "")
    current = str(current_digest or "")
    if not stored:
        return True, "legacy_provenance"
    if not current:
        return False, "resume_provenance_mismatch: current digest unavailable"
    if stored != current:
        return False, "resume_provenance_mismatch: digest changed"
    return True, "provenance_match"


def check_compatibility(stored: dict | None, *, current_cfg: Any,
                        current_task_name: str,
                        current_schema_version: int,
                        current_provenance_digest: str | None = None) -> tuple[bool, str]:
    """Decide whether ``stored`` may be replayed on top of the current world.

    Returns ``(ok, reason)``. ``ok=False`` means the checkpoint MUST NOT be
    replayed: callers clear it and start fresh (do not silently apply a stale
    cursor/breaker). An empty/None checkpoint returns ``(True, "empty")`` —
    "nothing to resume, fresh start" is not a mismatch.

    Checks: task_name scope, config_hash drift, schema_version drift.
    pool_hash is intentionally NOT checked here (pool not rebuilt yet).
    """
    if not stored:
        return True, "empty"
    st_task = stored.get("task_name", "")
    if st_task and st_task != current_task_name:
        return False, f"task_name: stored={st_task!r} current={current_task_name!r}"
    st_cfg = stored.get("config_hash", "")
    if st_cfg and st_cfg != compute_config_hash(current_cfg):
        return False, "config_hash: config drifted since checkpoint"
    payload = stored.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload) or {}
        except Exception:
            payload = {}
    st_schema = payload.get("schema_version")
    if st_schema is not None and int(st_schema) != int(current_schema_version):
        return False, f"schema_version: stored={st_schema} current={current_schema_version}"
    stored_provenance = extract_provenance_digest(payload) or extract_provenance_digest(stored)
    ok, reason = check_provenance_compatibility(stored_provenance, current_provenance_digest)
    if not ok:
        return False, reason
    return True, "ok"


def pool_matches(stored_pool_hash: str, current_pool: Any) -> bool:
    """Compare pool_hash AFTER the signal pool is rebuilt at resume time.

    A blank stored hash means "not recorded" -> cannot disagree -> allow.
    A non-blank mismatch means the cursor may index a different pool -> refuse
    (caller decides to reset cursor or start fresh).
    """
    if not stored_pool_hash:
        return True
    return stored_pool_hash == compute_pool_hash(current_pool)
