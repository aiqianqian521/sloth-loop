"""dsh-genui (Python port, concept) - offline text dashboard / panel renderer.

Translated (not copied) from dsh-genui (TS). Render a UI panel for the agent /
loop. Offline we render an ASCII dashboard (no web); a future web backend can
consume the same row schema. Useful for PM-quant round summaries.
Tools: render_panel.
params: title(str), rows(list of {label,value,kind?}), kind(str,optional).
"""
from __future__ import annotations


def _render(payload):
    p = payload or {}
    title = str(p.get("title") or "panel")
    rows = list(p.get("rows") or [])
    width = max(40, len(title) + 4)
    lines = ["=" * width, title.center(width), "-" * width]
    for r in rows:
        label = str(r.get("label", ""))
        val = r.get("value")
        kind = str(r.get("kind", "text"))
        if isinstance(val, float):
            sval = ("%.4f" % val)
        elif isinstance(val, (int, bool)):
            sval = str(val)
        else:
            sval = str(val)
        lines.append("%-28s %-8s %s" % (label, kind, sval))
    lines.append("=" * width)
    return {"ok": True, "title": title, "row_count": len(rows),
            "panel": "\n".join(lines)}


def register(ctx):
    from tool_registry import ToolDefinition
    ctx.register_tool(ToolDefinition(name="render_panel", source="ui",
        handler=lambda payload=None, **k: _render(payload),
        description="Render an offline text dashboard panel. params: title(str), rows([{label,value,kind}]), kind(str)."))
    return {"tools": ["render_panel"]}
