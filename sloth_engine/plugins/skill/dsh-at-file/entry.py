"""dsh-at-file (Python port, concept) - @path resolution + listing.

Translated (not copied) from dsh-at-file (TS): resolve @-mentions to real
workspace files. Offline we glob a configured workspace_root. Lets the PM-quant
loop @-reference signal/csv artifacts without hardcoding absolute paths.
Relative paths are returned with forward slashes for portability.
Tools: resolve_path / list_paths.
Config: plugins.at_file.workspace_root (default ".").
"""
from __future__ import annotations

from pathlib import Path

_SKIP = ("node_modules", ".venv", "__pycache__", ".git")


def _skip(p):
    return any(s in p.parts for s in _SKIP)


def _rel(p, root):
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


class _AtFile:
    def __init__(self, config):
        c = (config.get("plugins") or {}).get("at_file") or {}
        self.root = Path(c.get("workspace_root") or ".")

    def resolve(self, ref):
        r = str(ref or "").strip().lstrip("@")
        if not r:
            return {"ok": False, "error": "ref required"}
        cand = Path(r) if Path(r).is_absolute() else (self.root / r)
        if cand.exists():
            return {"ok": True, "ref": r, "abs_path": str(cand.resolve()),
                    "rel_path": _rel(cand, self.root), "exists": True, "is_file": cand.is_file()}
        name = Path(r).name
        for f in self.root.rglob(name):
            if _skip(f):
                continue
            return {"ok": True, "ref": r, "abs_path": str(f.resolve()),
                    "rel_path": _rel(f, self.root), "exists": True, "is_file": f.is_file(),
                    "matched_by": "filename"}
        return {"ok": True, "ref": r, "abs_path": str(cand), "exists": False}

    def list_paths(self, pattern="*"):
        pat = str(pattern or "*")
        out = []
        if self.root.exists():
            for f in self.root.rglob(pat):
                if _skip(f):
                    continue
                out.append(_rel(f, self.root))
                if len(out) >= 200:
                    break
        return {"ok": True, "root": str(self.root), "count": len(out), "paths": out}


def register(ctx):
    af = _AtFile(ctx.config)
    from tool_registry import ToolDefinition
    def _resolve(payload=None, **k):
        return af.resolve((payload or {}).get("ref"))
    def _list(payload=None, **k):
        return af.list_paths((payload or {}).get("pattern"))
    ctx.register_tool(ToolDefinition(name="resolve_path", source="skill",
        handler=_resolve, description="Resolve an @path/file ref against workspace_root. params: ref(str)."))
    ctx.register_tool(ToolDefinition(name="list_paths", source="skill",
        handler=_list, description="List files under workspace_root matching a glob. params: pattern(str,default *)."))
    return {"tools": ["resolve_path", "list_paths"]}
