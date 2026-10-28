"""dsh-credentials (Python port) - credential-reference capability seam.

Translated (not copied) from @deepseek-ai/dsh-credentials (+ credentials-local).

Domain essence (preserved):
  - Configuration carries *references* (POSIX env-var names), never values.
    `CredentialRef` grammar: ^[A-Za-z_][A-Za-z0-9_]*$
  - `CredentialKey` addresses one stored record as `<scope>/<id>`; each segment
    is ^[a-z][a-z0-9-]*$. The `/` keeps the two key spaces disjoint.
  - Records are tagged: {"kind":"api-key","key","env"} | {"kind":"grant","payload"}.
  - CredentialInfo (configured/source) is the ONLY thing readable; the value is
    resolved once per operation through resolve(), never surfaced to config UIs.
  - Layered resolution precedence (most-trusted wins):
        inherited process environment   (read-only, wins)
      > managed store (.credentials.json) (writable)
      > project cwd/.env                 (read-only fallback)
      > $DSH_HOME/.env                   (read-only fallback)
  - Writes go ONLY to the managed store, and re-read under a lock so a
    concurrently edited document is patched (last-writer-safe), not clobbered.

Tools: cred_ref_check, cred_info, cred_set, cred_resolve.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path

_log = logging.getLogger("sloth_engine.plugin.dsh-credentials")

REF_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KEY_SEGMENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")

_LOCK = threading.RLock()


def is_credential_ref_name(value: str) -> bool:
    """True when the raw string could name a reference at all."""
    return bool(value) and bool(REF_PATTERN.match(value))


def is_credential_key_segment(value: str) -> bool:
    return bool(value) and bool(KEY_SEGMENT_PATTERN.match(value))


def credential_key(scope: str, key_id: str) -> str:
    """Brand a scope + id into a `<scope>/<id>` key. Raises on bad segments."""
    if not is_credential_key_segment(scope) or not is_credential_key_segment(key_id):
        raise ValueError(
            f"credential key segments must match {KEY_SEGMENT_PATTERN.pattern}: "
            f"got scope={scope!r} id={key_id!r}")
    return f"{scope}/{key_id}"


def _managed_store_path():
    home = os.environ.get("DSH_HOME") or str(Path.home() / ".dsh")
    return Path(home) / ".credentials.json"


def _load_store() -> dict:
    p = _managed_store_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        _log.warning("[credentials] store unreadable (%s); treating as empty", exc)
        return {}


def _read_dotenv(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if is_credential_ref_name(k):
                out[k] = v
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return out


def resolve(ref: str):
    """Resolve a reference through the layered stack. Returns (value, source).

    source in {env, managed, project, home_env, None}. Value is None when the
    reference is unset anywhere. Grammar-external names read as unset (no raise).
    """
    if not is_credential_ref_name(ref):
        return None, None
    # 1. inherited process env wins (read-only)
    if ref in os.environ:
        return os.environ[ref], "env"
    # 2. managed store (writable)
    store = _load_store()
    if ref in store:
        return store[ref], "managed"
    # 3. project cwd/.env
    proj = _read_dotenv(Path.cwd() / ".env")
    if ref in proj:
        return proj[ref], "project"
    # 4. $DSH_HOME/.env
    home_env = _read_dotenv(_managed_store_path().parent / ".env")
    if ref in home_env:
        return home_env[ref], "home_env"
    return None, None


def cred_info(ref: str) -> dict:
    """Public, value-free view of a reference (safe for config UIs)."""
    value, source = resolve(ref)
    return {"ref": ref, "configured": value is not None, "source": source,
            "valid_name": is_credential_ref_name(ref)}


def cred_set(ref: str, value: str, *, scope: str = "dsh-credentials",
             key_id: str | None = None) -> dict:
    """Write a value into the MANAGED store only (never env). Locked RMW.

    Returns CredentialInfo-shaped dict (never the value).
    """
    if not is_credential_ref_name(ref):
        return {"ok": False, "error": f"invalid ref {ref!r}"}
    if value is None or str(value) == "":
        return {"ok": False, "error": "value must be a non-empty string"}
    p = _managed_store_path()
    with _LOCK:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            store = _load_store()          # re-read under lock (RMW)
            store[ref] = str(value)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, p)             # atomic publish
        except Exception as exc:
            return {"ok": False, "error": f"store write failed: {exc}"}
    _log.info("[credentials] stored ref %s (scope=%s)", ref, scope)
    return {"ok": True, **cred_info(ref)}


# ── tool handlers ──────────────────────────────────────────────
def _cred_ref_check(payload):
    p = payload or {}
    name = str(p.get("ref") or "")
    return {"ok": True, "ref": name,
            "valid_ref": is_credential_ref_name(name),
            "valid_key_segment": is_credential_key_segment(name)}


def _cred_info(payload):
    p = payload or {}
    ref = str(p.get("ref") or "")
    if not ref:
        return {"ok": False, "error": "ref required"}
    return {"ok": True, **cred_info(ref)}


def _cred_set(payload):
    p = payload or {}
    ref = str(p.get("ref") or "")
    value = p.get("value")
    if not ref or value is None:
        return {"ok": False, "error": "ref and value required"}
    return cred_set(ref, value, scope=str(p.get("scope") or "dsh-credentials"))


def _cred_resolve(payload):
    p = payload or {}
    ref = str(p.get("ref") or "")
    value, source = resolve(ref)
    # Deliberately DO NOT return the value; expose presence + source only.
    return {"ok": True, "ref": ref, "configured": value is not None,
            "source": source, "length": (len(value) if value else 0)}


def register(ctx):
    from tool_registry import ToolDefinition

    def _mk(name, fn, desc):
        ctx.register_tool(ToolDefinition(name=name, source="memory",
                                         handler=lambda payload=None, **k: fn(payload),
                                         description=desc))

    _mk("cred_ref_check", _cred_ref_check,
        "Validate a credential ref name / key segment. params:{ref:str}")
    _mk("cred_info", _cred_info,
        "Value-free info for a credential ref (configured/source). params:{ref:str}")
    _mk("cred_set", _cred_set,
        "Write a credential value into the managed store. params:{ref:str,value:str}")
    _mk("cred_resolve", _cred_resolve,
        "Resolve presence+source for a ref WITHOUT returning the value. params:{ref:str}")
    return {"tools": ["cred_ref_check", "cred_info", "cred_set", "cred_resolve"]}
