"""dsh-find-plugin (Python port, concept) - plugin discovery inside the agent.

Adapted from DSH dsh-find-plugin: instead of GitHub dsh-plugin topic search,
this scans the LOCAL sloth-loop plugins/ tree + roster, validates manifests, and
lets the agent find/list/validate installed plugins. Offline-first; a remote
registry can be added behind config later.
Tools: find_plugins / plugin_list / plugin_doctor.
"""
from __future__ import annotations

from pathlib import Path

import plugin_manifest


class _Finder:
    def __init__(self, config, plugins_root):
        cfg = config.get("plugins") or {}
        self.roster = {}
        for r in cfg.get("roster", []) or []:
            if isinstance(r, dict) and r.get("id"):
                self.roster[r["id"]] = r
        self.root = Path(plugins_root)

    def _scan(self):
        out = []
        if not self.root.exists():
            return out
        for mf in sorted(self.root.rglob("manifest.json")):
            try:
                m = plugin_manifest.load_manifest(mf)
            except Exception:
                continue
            errs = plugin_manifest.validate(m)
            rentry = self.roster.get(m.id, {})
            out.append({"id": m.id, "type": m.type, "version": m.version,
                        "extension_points": m.extension_points, "description": m.description,
                        "roster_enabled": bool(rentry.get("enabled", False)),
                        "manifest_valid": not errs, "errors": errs})
        return out

    def find(self, query):
        q = str(query or "").lower().strip()
        items = self._scan()
        if q:
            keep = []
            for i in items:
                hay = (i["id"] + " " + (i.get("description") or "") + " " + str(i.get("extension_points"))).lower()
                if q in hay:
                    keep.append(i)
            items = keep
        ranked = sorted(items, key=lambda i: (not i["roster_enabled"], i["id"]))
        return {"ok": True, "count": len(ranked), "plugins": ranked}

    def list_all(self):
        items = self._scan()
        return {"ok": True, "count": len(items),
                "plugins": [{"id": i["id"], "type": i["type"],
                             "roster_enabled": i["roster_enabled"],
                             "manifest_valid": i["manifest_valid"]} for i in items]}

    def doctor(self):
        items = self._scan()
        bad = [i for i in items if not i["manifest_valid"]]
        return {"ok": True, "total": len(items), "invalid": len(bad), "invalid_plugins": bad}


def register(ctx):
    root = (ctx.config.get("plugins") or {}).get("root") or "plugins"
    f = _Finder(ctx.config, root)

    def _find(payload=None, **kw):
        a = payload or {}
        return f.find(a.get("query"))

    def _list(payload=None, **kw):
        return f.list_all()

    def _doctor(payload=None, **kw):
        return f.doctor()

    from tool_registry import ToolDefinition
    ctx.register_tool(ToolDefinition(
        name="find_plugins", source="skill", handler=_find,
        description="Find installed sloth-loop plugins by query (id/description/ext-point). params: query(str,optional)."))
    ctx.register_tool(ToolDefinition(
        name="plugin_list", source="skill", handler=_list,
        description="List all installed sloth-loop plugins with roster/validity."))
    ctx.register_tool(ToolDefinition(
        name="plugin_doctor", source="skill", handler=_doctor,
        description="Validate all installed plugin manifests; report invalid."))
    return {"tools": ["find_plugins", "plugin_list", "plugin_doctor"]}
