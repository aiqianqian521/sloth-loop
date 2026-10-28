"""dsh_workflow (Python port, concept) - workflow DAG with real ordered run.

Adapted from DSH dsh_workflow: turn multi-step dispatch into a runnable DAG.
workflow_run now executes steps in dependency (topological) order and returns
the order + per-step results. Offline default marks each step planned:ok;
inject `plugins.dsh-workflow.step_fn(step, prior_results)` via config to run
real orchestrator steps (pluggable backend seam).
Tools: workflow_create / workflow_run / workflow_get.

Top-level result key is `wf_status` (not `status`) to avoid colliding with the
loop task-result contract field that normalize_task_result maps to
{completed,error,skipped}.
"""
from __future__ import annotations

import uuid

_WF = {}


def _create(steps):
    steps = list(steps or [])
    nodes = [{"id": str(s.get("id", i + 1)), "name": str(s.get("name", s.get("id", i + 1))),
              "deps": list(s.get("deps", []))} for i, s in enumerate(steps)]
    wid = uuid.uuid4().hex[:6]
    _WF[wid] = {"steps": nodes, "results": {}, "state": "created"}
    return {"ok": True, "workflow_id": wid, "steps": nodes, "wf_status": "created"}


def _topo(steps):
    by = {s["id"]: s for s in steps}
    indeg = {sid: 0 for sid in by}
    adj = {sid: [] for sid in by}
    for s in steps:
        for d in s["deps"]:
            if d in by:
                adj[d].append(s["id"])
                indeg[s["id"]] += 1
    ready = sorted([sid for sid, d in indeg.items() if d == 0])
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
        ready.sort()
    if len(order) != len(by):
        return None
    return order


def _run(wid, step_fn=None):
    w = _WF.get(wid)
    if not w:
        return {"ok": False, "error": "workflow not found"}
    order = _topo(w["steps"])
    if order is None:
        return {"ok": False, "error": "cycle detected in deps"}
    results = {}
    for sid in order:
        step = next(s for s in w["steps"] if s["id"] == sid)
        prior = dict(results)
        if callable(step_fn):
            try:
                res = step_fn(step, prior)
            except Exception as exc:
                res = "step-error:" + str(exc)[:80]
        else:
            res = "planned:ok"
        results[sid] = res
    w["results"] = results
    w["state"] = "ran"
    return {"ok": True, "workflow_id": wid, "results": results,
            "order": order, "wf_status": "ran"}


def _get(wid):
    w = _WF.get(wid)
    return {"ok": True, "workflow": w} if w else {"ok": False, "error": "not found"}


def register(ctx):
    cfg = (ctx.config.get("plugins") or {}).get("dsh-workflow") or {}
    step_fn = cfg.get("step_fn")
    from tool_registry import ToolDefinition
    ctx.register_tool(ToolDefinition(name="workflow_create", source="skill",
        handler=lambda payload=None, **k: _create((payload or {}).get("steps")),
        description="Create a workflow DAG. params: steps(list of {id,name,deps}). Returns wf_status=created."))
    ctx.register_tool(ToolDefinition(name="workflow_run", source="skill",
        handler=lambda payload=None, **k: _run((payload or {}).get("workflow_id"), step_fn),
        description="Run a workflow in dependency order. params: workflow_id(str). Returns wf_status=ran, order, results. Offline default; inject step_fn via config for real."))
    ctx.register_tool(ToolDefinition(name="workflow_get", source="skill",
        handler=lambda payload=None, **k: _get((payload or {}).get("workflow_id")),
        description="Get workflow state. params: workflow_id(str)."))
    return {"tools": ["workflow_create", "workflow_run", "workflow_get"]}
