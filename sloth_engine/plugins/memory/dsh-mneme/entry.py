"""dsh-mneme (Python port, concept only) - cross-session semantic memory engine.

Translated (not code copy) from @modusensus/dsh-mneme (TS). Same idea:
  - remember facts with optional tags + auto entity extraction
  - semantic search over memories (local bigram-hash embedding, offline)
  - entity timeline
  - human-editable Markdown mirror store
Tools: memory_remember / memory_search / memory_timeline / memory_status.
Config: plugins.memory.mneme_store (default data/dsh-mneme-store.json) +
        plugins.memory.mneme_md    (default data/dsh-mneme.md).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from pathlib import Path

DIM = 384


def _tok(t):
    return re.findall(r"[a-zA-Z0-9_]+", (t or "").lower())


def _embed(text):
    v = [0.0] * DIM
    toks = _tok(text)
    grams = list(toks) + [(toks[i] + "_" + toks[i + 1]) for i in range(max(0, len(toks) - 1))]
    for g in grams:
        h = hashlib.blake2b(g.encode("utf-8"), digest_size=4).digest()
        v[int.from_bytes(h, "big") % DIM] += (1.0 if (h[0] & 1) == 0 else -1.0)
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def _entities(text):
    caps = re.findall(r"\b[A-Z][a-zA-Z0-9_]{2,}\b", text or "")
    quoted = re.findall(r'"([A-Za-z0-9_ -]{2,30})"', text or "")
    tags = re.findall(r"#([a-zA-Z0-9_-]+)", text or "")
    out = set()
    for w in caps + quoted + tags:
        w = w.strip()
        if w:
            out.add(w)
    return sorted(out)[:20]


class _Mneme:
    def __init__(self, config):
        mem = (config.get("plugins") or {}).get("memory") or {}
        self.store_path = Path(mem.get("mneme_store") or "data/dsh-mneme-store.json")
        self.md_path = Path(mem.get("mneme_md") or "data/dsh-mneme.md")
        self._store = None
        self._ensure()

    def _ensure(self):
        if self._store is not None:
            return
        if self.store_path.exists():
            try:
                self._store = json.loads(self.store_path.read_text(encoding="utf-8"))
            except Exception:
                self._store = {"entries": []}
        else:
            self._store = {"entries": []}
        if "entries" not in self._store:
            self._store = {"entries": []}

    def _save(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(self._store, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = ["# dsh-mneme memory", ""]
        for e in self._store["entries"]:
            lines.append("## " + str(e["id"]) + " - " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["createdAt"])))
            lines.append("- tags: " + json.dumps(e.get("tags", []), ensure_ascii=False))
            lines.append("- entities: " + json.dumps(e.get("entities", []), ensure_ascii=False))
            lines.append("")
            lines.append(e.get("text", ""))
            lines.append("")
        self.md_path.parent.mkdir(parents=True, exist_ok=True)
        self.md_path.write_text("\n".join(lines), encoding="utf-8")

    def remember(self, text, tags=None):
        text = str(text or "")
        if not text.strip():
            return {"ok": False, "error": "text required"}
        tags = list(tags) if tags else []
        ents = _entities(text)
        e = {"id": uuid.uuid4().hex[:8], "text": text, "tags": tags,
             "entities": ents, "vector": _embed(text), "createdAt": int(time.time())}
        self._store["entries"].append(e)
        self._save()
        return {"ok": True, "id": e["id"], "entities": ents}

    def search(self, query, topK=5):
        q = str(query or "")
        if not q.strip():
            return {"ok": False, "error": "query required"}
        es = self._store["entries"]
        if not es:
            return {"ok": True, "results": []}
        qv = _embed(q)
        sc = sorted([(_cos(qv, e["vector"]), e) for e in es], key=lambda x: x[0], reverse=True)
        topK = max(1, min(50, int(topK or 5)))
        return {"ok": True, "results": [{"id": e["id"], "score": round(s, 4),
                "text": e["text"][:400], "entities": e.get("entities", []),
                "createdAt": e.get("createdAt")} for s, e in sc[:topK]]}

    def timeline(self, entity=None):
        es = self._store["entries"]
        if entity:
            es = [e for e in es if entity in e.get("entities", []) or entity in e.get("tags", [])]
        es = sorted(es, key=lambda e: e.get("createdAt", 0))
        return {"ok": True, "timeline": [{"id": e["id"], "createdAt": e.get("createdAt"),
                "text": e["text"][:200], "entities": e.get("entities", [])} for e in es]}

    def status(self):
        es = self._store["entries"]
        ents = {}
        for e in es:
            for x in e.get("entities", []):
                ents[x] = ents.get(x, 0) + 1
        return {"ok": True, "count": len(es),
                "topEntities": [list(p) for p in sorted(ents.items(), key=lambda x: -x[1])[:10]]}


def register(ctx):
    m = _Mneme(ctx.config)

    def _remember(payload=None, **kw):
        a = payload or {}
        return m.remember(a.get("text", ""), a.get("tags"))

    def _search(payload=None, **kw):
        a = payload or {}
        return m.search(a.get("query", ""), a.get("topK") or 5)

    def _timeline(payload=None, **kw):
        a = payload or {}
        return m.timeline(a.get("entity"))

    def _status(payload=None, **kw):
        return m.status()

    from tool_registry import ToolDefinition
    ctx.register_tool(ToolDefinition(
        name="memory_remember", source="memory", handler=_remember,
        description="Store a memory with auto entity extraction. params: text(str,required), tags(list[str],optional)."))
    ctx.register_tool(ToolDefinition(
        name="memory_search", source="memory", handler=_search,
        description="Semantic search memories. params: query(str,required), topK(int,default5)."))
    ctx.register_tool(ToolDefinition(
        name="memory_timeline", source="memory", handler=_timeline,
        description="Timeline of memories by entity/tag. params: entity(str,optional)."))
    ctx.register_tool(ToolDefinition(
        name="memory_status", source="memory", handler=_status,
        description="Memory stats: count + top entities."))
    return {"tools": ["memory_remember", "memory_search", "memory_timeline", "memory_status"]}
