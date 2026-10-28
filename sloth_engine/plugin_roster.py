"""Plugin roster - mount decision (which plugins are enabled/trusted).

Aligned with architect-plugin SKILL 1.7 (Roster combination decision).
Discovery-by-scan does NOT decide mounting; a deployment roster (typically
sourced from config) decides which discovered plugins are enabled and
whether they are trusted for full privileges.

Roster entries are deployment attributes, NOT package attributes: the same
plugin package may be mounted with different rosters across deployments.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RosterEntry:
    id: str
    enabled: bool = True
    trusted: bool = False


class PluginRoster:
    """Map plugin id -> RosterEntry. Defaults: nothing enabled."""

    def __init__(self, entries=None):
        self._by_id = {}
        for e in (entries or []):
            self._by_id[e.id] = e

    @classmethod
    def from_config(cls, config) -> "PluginRoster":
        """Read {plugins: {roster: [{id, enabled, trusted}, ...]}}.

        Backward compatible: a config without a `plugins` key yields an empty
        roster (no plugins activated), so existing config-based projects are
        undisturbed.
        """
        cfg = config or {}
        raw = cfg.get("plugins", {}).get("roster", []) or []
        entries = []
        for item in raw:
            pid = item.get("id")
            if not pid:
                continue
            entries.append(RosterEntry(
                id=str(pid),
                enabled=bool(item.get("enabled", True)),
                trusted=bool(item.get("trusted", False)),
            ))
        return cls(entries)

    def is_enabled(self, plugin_id) -> bool:
        e = self._by_id.get(plugin_id)
        return bool(e and e.enabled)

    def is_trusted(self, plugin_id) -> bool:
        e = self._by_id.get(plugin_id)
        return bool(e and e.trusted)

    @property
    def entries(self):
        return list(self._by_id.values())

    def enabled_ids(self):
        return [e.id for e in self._by_id.values() if e.enabled]
