"""File-backed provider quota probe (cycle-13 A: N-3 feasible slice).

Why: G-6 wired an opt-in quota stop gate (``Orchestrator.quota_probe`` ->
``run_loop._quota_stop_reason`` -> clean stop when a window is exhausted) but
the only known real sources need a vendor SDK / host credentials this repo does
not have (N-3 was registered *blocked* in cycle-11). A host wrapper that can
read provider usage can publish it as a JSON file instead; this module turns
that file into the zero-arg callable the gate already accepts. No network, no
vendor SDK, fully offline-testable.

Enable (opt-in; a default run is byte-for-byte unchanged):

    LOOP_QUOTA_FILE=<path to json>     # e.g. C:\\rt\\quota.json   (unset = off)
    LOOP_QUOTA_PROVIDER=<label>        # optional, default: payload provider, else "loop"

Payload shape == the raw dict accepted by ``quota_window.from_raw`` (aliases
accepted: usedPercent/used_percent, resetsAt/resets_at,
windowDurationMins/window_duration_minutes):

    {"provider":  "openai",
     "primary":   {"usedPercent": 12.5, "resetsAt": 1761200000000,
                   "windowDurationMins": 300},
     "secondary": {"used_percent": 91.0,
                   "resets_at": "2026-11-01T00:00:00Z"}}

Fail-soft split of responsibilities: this module only *reads and parses*; a
missing / unreadable / non-object file RAISES inside the probe, and
``quota_window.resolve_snapshot`` turns that into a degraded (cached) or error
snapshot. So an unreadable file can never stop a run by itself -- only a window
with used_percent >= 100 does. See docs/design/2026-10-22-cycle13-A-quota-file-probe.md.

Contract invariants (asserted in tests/test_quota_file_probe.py):
1. ``enabled``/``install`` treat unset / blank / whitespace-only env as OFF and
   leave the orchestrator attributes untouched (no probe => old behaviour).
2. an enabled path yields a zero-arg probe that returns the parsed JSON object
   verbatim (window mapping stays quota_window's job, not ours).
3. provider label precedence: LOOP_QUOTA_PROVIDER > payload["provider"] > "loop".
4. probe failures raise; ``resolve_snapshot`` degrades instead of raising.
5. the gate really consumes it: an exhausted payload drives
   ``run_loop._quota_stop_reason()`` to a "Quota exhausted (... provider=...)" stop.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

__all__ = [
    "ENV_FILE",
    "ENV_PROVIDER",
    "DEFAULT_PROVIDER",
    "enabled",
    "resolve_path",
    "resolve_provider",
    "load_payload",
    "make_probe",
    "install",
]

ENV_FILE = "LOOP_QUOTA_FILE"
ENV_PROVIDER = "LOOP_QUOTA_PROVIDER"
DEFAULT_PROVIDER = "loop"


def _clean(value: Any) -> str:
    """str(value).strip() with None / non-str tolerated -> ""."""
    if isinstance(value, str):
        return value.strip()
    return ""


def enabled(env: Mapping[str, str]) -> bool:
    """True when LOOP_QUOTA_FILE names something (blank/whitespace => off)."""
    return bool(_clean(env.get(ENV_FILE)))


def resolve_path(env: Mapping[str, str]) -> Optional[str]:
    """The configured payload path (``~`` expanded) or None when disabled."""
    raw = _clean(env.get(ENV_FILE))
    if not raw:
        return None
    return os.path.expanduser(raw)


def load_payload(path: str) -> dict:
    """Read + parse the JSON payload. Raises on missing / bad / non-object."""
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("quota payload must be a JSON object, got %s"
                         % type(data).__name__)
    return data


def make_probe(path: str) -> Callable[[], Any]:
    """A zero-arg probe reading ``path`` on every call (fresh, not cached)."""
    def probe() -> Any:
        return load_payload(path)
    return probe


def _payload_provider(path: Optional[str]) -> str:
    """Best-effort payload provider label (a broken file is simply ignored)."""
    if not path:
        return ""
    try:
        return _clean(load_payload(path).get("provider"))
    except Exception:  # noqa: BLE001 - label lookup must never break install
        return ""


def resolve_provider(env: Mapping[str, str], path: Optional[str]) -> str:
    """Label precedence: env LOOP_QUOTA_PROVIDER > payload["provider"] > "loop"."""
    return (_clean(env.get(ENV_PROVIDER))
            or _payload_provider(path)
            or DEFAULT_PROVIDER)


def install(target: Any, env: Optional[Mapping[str, str]] = None) -> Optional[Callable[[], Any]]:
    """Wire a file probe onto ``target`` (duck-typed: quota_probe/_provider/_cache).

    Returns the probe when enabled, else None. Disabled => attributes untouched
    (so a caller may keep its own probe). ``target`` is normally an Orchestrator.
    """
    env = os.environ if env is None else env
    path = resolve_path(env)
    if path is None:
        return None
    probe = make_probe(path)
    target.quota_probe = probe
    target.quota_provider = resolve_provider(env, path)
    if not hasattr(target, "quota_cache"):
        target.quota_cache = None
    return probe