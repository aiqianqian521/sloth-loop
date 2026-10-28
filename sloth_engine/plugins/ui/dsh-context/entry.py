"""dsh-context (Python port, concept) - context/token observability for loop rounds.

Adapted from DSH dsh-context: instead of DSH web context dashboard, this reads
sloth-loop's own event_log (jsonl) and gives the agent round/context stats,
recent events, and a token+cost estimate. Offline, real, reuses loop artifacts.
Tools: context_stats / context_events / context_tokens.
Config: plugins.context.events_dir (default data/events); plugins.context.usd_per_1k.
"""
from __future__ import annotations

import json
from pathlib import Path


class _Ctx:
    def __init__(self, config):
        c = (config.get("plugins") or {}).get("context") or {}
        self.dir = Path(c.get("events_dir") or "data/events")
        self.rate = float(c.get("usd_per_1k") or 0.0)

    def _events(self):
        ev = []
        if not self.dir.exists():
            return ev
        for f in sorted(self.dir.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.strip():
                    continue
                try:
                    ev.append(json.loads(line))
                except Exception:
                    pass
        return ev

    def stats(self):
        ev = self._events()
        by = {}
        for e in ev:
            k = e.get("type", e.get("event", "unknown"))
            by[k] = by.get(k, 0) + 1
        ts = [e.get("ts", e.get("timestamp")) for e in ev if e.get("ts", e.get("timestamp"))]
        return {"ok": True, "event_count": len(ev), "by_type": by,
                "first": ts[0] if ts else None, "last": ts[-1] if ts else None}

    def events(self, limit=20):
        ev = self._events()[-int(limit or 20):]
        return {"ok": True, "count": len(ev), "events": ev}

    def tokens(self):
        ev = self._events()
        total = 0
        for e in ev:
            hit = False
            for k in ("tokens", "token_count", "in_tokens", "out_tokens", "total_tokens"):
                v = e.get(k)
                if isinstance(v, (int, float)):
                    total += v
                    hit = True
            if not hit:
                total += len(json.dumps(e, ensure_ascii=False)) // 4
        return {"ok": True, "estimated_tokens": total,
                "estimated_cost_usd": round(total / 1000 * self.rate, 6)}


def register(ctx):
    c = _Ctx(ctx.config)
    from tool_registry import ToolDefinition
    ctx.register_tool(ToolDefinition(name="context_stats", source="ui",
        handler=lambda payload=None, **k: c.stats(), description="Loop round context stats from event_log."))
    ctx.register_tool(ToolDefinition(name="context_events", source="ui",
        handler=lambda payload=None, **k: c.events((payload or {}).get("limit")),
        description="Recent loop events. params: limit(int,default20)."))
    ctx.register_tool(ToolDefinition(name="context_tokens", source="ui",
        handler=lambda payload=None, **k: c.tokens(), description="Estimated token usage + cost from event_log."))
    return {"tools": ["context_stats", "context_events", "context_tokens"]}
