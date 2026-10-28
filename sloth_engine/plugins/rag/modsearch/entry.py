"""modsearch (Python port, concept) - pluggable web search + page fetch.

Translated (not copied) from @nickyxyz/modsearch (TS). Three backends, in order:
  1. injected callables via config: search_fn(query, topK) and fetch_fn(url)
  2. offline grep over a corpus_dir (web_search) / local file read (fetch_page)
  3. honest `backend not configured` when nothing is wired
This is the pluggable seam a user plugin / orchestrator supplies: drop a
callable in config.plugins.modsearch.{search_fn,fetch_fn} and it goes live,
with zero core edits (soft-pluggable, non-????).
Tools: web_search / fetch_page.
"""
from __future__ import annotations

import re
from pathlib import Path


class _Search:
    def __init__(self, config):
        c = (config.get("plugins") or {}).get("modsearch") or {}
        self.corpus = Path(c["corpus_dir"]) if c.get("corpus_dir") else None
        self.engine = c.get("engine")
        self.search_fn = c.get("search_fn")
        self.fetch_fn = c.get("fetch_fn")

    def _score(self, terms, text):
        low = text.lower()
        return sum(low.count(t) for t in terms)

    def search(self, query, topK=5):
        q = str(query or "").strip()
        if not q:
            return {"ok": False, "error": "query required"}
        topK = max(1, min(50, int(topK or 5)))
        if callable(self.search_fn):
            try:
                hits = self.search_fn(q, topK) or []
            except Exception as exc:
                return {"ok": False, "error": "search_fn failed: " + str(exc)[:120]}
            return {"ok": True, "engine": "injected", "count": len(hits),
                    "results": list(hits)[:topK]}
        if self.engine:
            return {"ok": False, "error": "backend not configured",
                    "hint": "engine set but no HTTP fetcher wired (offline mode)"}
        if not self.corpus or not self.corpus.exists():
            return {"ok": False, "error": "backend not configured",
                    "hint": "set plugins.modsearch.corpus_dir for offline grep, or inject search_fn"}
        terms = [t for t in re.findall(r"[A-Za-z0-9_]+", q.lower()) if len(t) > 1]
        hits = []
        for f in sorted(self.corpus.rglob("*")):
            if not f.is_file() or f.suffix not in (".md", ".txt", ".json"):
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            sc = self._score(terms, txt)
            if sc > 0:
                lows = [txt.lower().find(t) for t in terms if txt.lower().find(t) >= 0]
                idx = min(lows) if lows else 0
                snippet = txt[max(0, idx - 40): idx + 120].replace("\n", " ")
                hits.append({"path": str(f), "score": sc, "snippet": snippet})
        hits.sort(key=lambda h: h["score"], reverse=True)
        return {"ok": True, "engine": "offline-grep", "count": len(hits),
                "results": hits[:topK]}

    def fetch_page(self, url):
        u = str(url or "")
        if callable(self.fetch_fn):
            try:
                body = self.fetch_fn(u)
            except Exception as exc:
                return {"ok": False, "error": "fetch_fn failed: " + str(exc)[:120], "url": u}
            return {"ok": True, "url": u, "body": body, "source": "injected"}
        p = u[7:] if u.startswith("file://") else u
        try:
            pth = Path(p)
            if pth.exists() and pth.is_file():
                body = pth.read_text(encoding="utf-8", errors="ignore")
                return {"ok": True, "url": u, "body": body, "source": "local-file"}
        except Exception as exc:
            return {"ok": False, "error": "read failed: " + str(exc)[:120], "url": u}
        return {"ok": False, "error": "backend not configured", "url": u,
                "hint": "inject fetch_fn or pass a local path / file:// url"}


def register(ctx):
    s = _Search(ctx.config)
    from tool_registry import ToolDefinition
    def _search(payload=None, **k):
        p = payload or {}
        return s.search(p.get("query"), p.get("topK"))
    def _fetch(payload=None, **k):
        return s.fetch_page((payload or {}).get("url"))
    ctx.register_tool(ToolDefinition(name="web_search", source="rag",
        handler=_search, description="Web search; injected search_fn > offline grep. params: query(str), topK(int)."))
    ctx.register_tool(ToolDefinition(name="fetch_page", source="rag",
        handler=_fetch, description="Fetch a URL body; injected fetch_fn > local-file > not-configured. params: url(str)."))
    return {"tools": ["web_search", "fetch_page"]}
