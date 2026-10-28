"""dsh-handbook (Python port, concept) - offline onboarding handbook snippets.

Translated (not copied) from dsh-handbook (TS): serve curated onboarding /
white-paper fragments by topic, so a fresh agent or PM round can pull concise
canonical knowledge. Offline built-in topic dict (PM-quant relevant). A future
version can index real handbook markdown.
Tools: handbook.
params: topic(str) e.g. entry, exit, regime, filter, loop, plugin, rag.
"""
from __future__ import annotations

_TOPICS = {
    "entry": (
        "## ENTRY (entry-filter discipline)\n"
        "Discipline: trigger on strict 5m signal, THEN confirm against the\n"
        "higher-timeframe regime (1H/4H). Do NOT widen the indicator globally to\n"
        "fit a losing month. If 1H and 4H are already extended (HH), a fresh 5m\n"
        "long is rebound, not trend-start: classify the scene before the filter."
    ),
    "exit": (
        "## EXIT (trail by regime, not one-template)\n"
        "Different regimes need different exits:\n"
        "- trend: trail below the last HL swing; never trail in a range chop.\n"
        "- range: take profit at the opposite wall; no trailing (it whipsaws).\n"
        "- counter-trend rebound: targets are shallow; set a price*0.003 stop\n"
        "  floor and let the runner go only if the channel confirms.\n"
        "Take-profit must never be a single global template."
    ),
    "regime": (
        "## REGIME (1H/4H scene classification)\n"
        "Lag truth: a regime is only confirmed after several bars. 1H trend is\n"
        "12x 5m bars. Use the regime ONLY to label the scene behind a triggered\n"
        "5m signal, not to predict the next bar."
    ),
    "filter": (
        "## FILTER (strict signal gating)\n"
        "Counter-trend 5m signals inside a trend are filtered out unless\n"
        "classified as a deliberate reversal scene. Net sign / unit / range\n"
        "gates prevent the SIDEWAYS=0 misclassification bug."
    ),
    "loop": (
        "## LOOP (sloth-loop essence)\n"
        "Loop = same flow, error first, repeatable for every coin. Log every\n"
        "error to the knowledge base so the next coin does not repeat it. It is\n"
        "not re-implementation; it is learning + adaptation."
    ),
    "plugin": (
        "## PLUGIN (soft-pluggable, manifest contract)\n"
        "Drop manifest+entry into plugins/<type>/<id>/; roster-enable in config;\n"
        "core wires it via extension points (tool_registry / hook / memory).\n"
        "No core edits. Purity gate blocks cross-plugin imports."
    ),
    "rag": (
        "## RAG (retrieval over local knowledge)\n"
        "Participants: dsh-rag-kb(kb_search), modsearch(web/offline grep),\n"
        "dsh-mneme(semantic memory). Use them so a PM round retrieves prior\n"
        "decisions instead of re-deriving from scratch."
    ),
}


def _handbook(payload):
    p = payload or {}
    topic = str(p.get("topic") or "").strip().lower()
    if not topic:
        return {"ok": False, "error": "topic required", "available": sorted(_TOPICS.keys())}
    if topic in _TOPICS:
        return {"ok": True, "topic": topic, "markdown": _TOPICS[topic]}
    for k in _TOPICS:
        if topic in k or k in topic:
            return {"ok": True, "topic": k, "markdown": _TOPICS[k], "matched_by": "fuzzy"}
    return {"ok": False, "topic": topic, "error": "topic not found", "available": sorted(_TOPICS.keys())}


def register(ctx):
    from tool_registry import ToolDefinition
    ctx.register_tool(ToolDefinition(name="handbook", source="skill",
        handler=lambda payload=None, **k: _handbook(payload),
        description="Onboarding handbook snippet by topic. params: topic(str) e.g. entry,exit,regime,filter,loop,plugin,rag."))
    return {"tools": ["handbook"]}
