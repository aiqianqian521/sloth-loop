"""modlens (Python port, concept) - pluggable vision / image description.

Translated (not copied) from modlens (TS). Three backends, in order:
  1. injected callable via config: describe_fn(path, question) -> dict|str
  2. Pillow metadata when importable and the path exists (offline)
  3. honest `backend not configured` otherwise
Drop a callable in config.plugins.modlens.describe_fn to wire a real vision
API / a user-supplied vision plugin (soft-pluggable, non-????).
Tools: describe_image.
"""
from __future__ import annotations


class _Lens:
    def __init__(self, config):
        c = (config.get("plugins") or {}).get("modlens") or {}
        self.backend = c.get("backend")
        self.describe_fn = c.get("describe_fn")

    def describe(self, path, question=None):
        p = str(path or "")
        if callable(self.describe_fn):
            try:
                out = self.describe_fn(p, question)
            except Exception as exc:
                return {"ok": False, "error": "describe_fn failed: " + str(exc)[:120]}
            if isinstance(out, dict):
                r = {"ok": True, "backend": "injected", "path": p}
                r.update(out)
                return r
            return {"ok": True, "backend": "injected", "path": p, "caption": str(out)}
        if self.backend:
            return {"ok": False, "error": "backend not configured",
                    "backend": self.backend, "hint": "backend set but no vision client wired; inject describe_fn"}
        if not p:
            return {"ok": False, "error": "path required"}
        try:
            from PIL import Image
        except Exception:
            return {"ok": False, "error": "backend not configured",
                    "hint": "PIL not installed; install Pillow or inject plugins.modlens.describe_fn"}
        try:
            with Image.open(p) as im:
                return {"ok": True, "mode": im.mode, "size": list(im.size),
                        "format": (im.format or ""), "path": p}
        except Exception as exc:
            return {"ok": False, "error": "backend not configured",
                    "hint": "could not read image: " + str(exc)}


def register(ctx):
    lens = _Lens(ctx.config)
    from tool_registry import ToolDefinition
    def _describe(payload=None, **k):
        p = payload or {}
        return lens.describe(p.get("path"), p.get("question"))
    ctx.register_tool(ToolDefinition(name="describe_image", source="rag",
        handler=_describe, description="Describe an image; injected describe_fn > Pillow metadata > not-configured. params: path(str), question(str,optional)."))
    return {"tools": ["describe_image"]}
