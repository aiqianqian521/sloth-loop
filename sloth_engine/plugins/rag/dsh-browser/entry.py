"""dsh-browser (Python port, concept) - pluggable headless browser.

Translated (not copied) from dsh-browser (TS). Two backends, in order:
  1. injected callable via config: backend_fn(action, target=None, selector=None)
     where action in {status, read, click}; returns a dict merged into the result
  2. honest `backend not configured` (no driver wired offline)
Drop a callable in config.plugins.dsh-browser.backend_fn (e.g. a playwright
adapter supplied by a user plugin) to go live, with zero core edits.
Tools: browser_read / browser_click / browser_status.
"""
from __future__ import annotations


class _Browser:
    def __init__(self, config):
        c = (config.get("plugins") or {}).get("dsh-browser") or {}
        self.backend = c.get("backend")
        self.backend_fn = c.get("backend_fn")

    def _nc(self, extra=None):
        r = {"ok": False, "error": "backend not configured",
             "hint": "inject plugins.dsh-browser.backend_fn (callable) or set .backend"}
        if extra:
            r.update(extra)
        return r

    def _call(self, action, **kw):
        try:
            out = self.backend_fn(action, **kw) or {}
        except Exception as exc:
            return {"ok": False, "error": "backend_fn failed: " + str(exc)[:120]}
        r = {"ok": True, "backend": "injected"}
        if isinstance(out, dict):
            r.update(out)
        return r

    def status(self):
        if callable(self.backend_fn):
            return self._call("status")
        if self.backend:
            return {"ok": True, "backend": self.backend, "alive": False,
                    "note": "backend declared but no driver wired (offline)"}
        return self._nc()

    def read(self, target):
        if callable(self.backend_fn):
            r = self._call("read", target=str(target or ""))
            return r
        return self._nc({"target": str(target or "")})

    def click(self, selector):
        if callable(self.backend_fn):
            return self._call("click", selector=str(selector or ""))
        return self._nc({"selector": str(selector or "")})


def register(ctx):
    b = _Browser(ctx.config)
    from tool_registry import ToolDefinition
    def _read(payload=None, **k):
        p = payload or {}
        return b.read(p.get("url") or p.get("target"))
    def _click(payload=None, **k):
        return b.click((payload or {}).get("selector"))
    ctx.register_tool(ToolDefinition(name="browser_read", source="rag",
        handler=_read, description="Read a page/selector; injected backend_fn > not-configured. params: url or target(str)."))
    ctx.register_tool(ToolDefinition(name="browser_click", source="rag",
        handler=_click, description="Click a selector; injected backend_fn > not-configured. params: selector(str)."))
    ctx.register_tool(ToolDefinition(name="browser_status", source="rag",
        handler=lambda payload=None, **k: b.status(), description="Report browser backend status."))
    return {"tools": ["browser_read", "browser_click", "browser_status"]}
