"""dsh-agent-teams (Python port, concept) - multi-agent team plan + run.

Adapted from DSH dsh-agent-teams: decompose a goal into captain + members +
tasks-with-dependencies, then RUN the plan. Offline default executes each task
deterministically; inject `plugins.agent-teams.executor_fn(member, task, prior)`
via config to delegate to real subagents / tools (pluggable backend seam).
Tools: team_plan / team_run / team_status.

NOTE: tasks are emitted in dependency order, so a linear run respects deps.
Top-level result keys avoid the task-result `status` field (use run_state).
"""
from __future__ import annotations

import uuid

_TEAM = {}


def _plan(goal):
    g = str(goal or "").lower()
    if "exit" in g or "tp" in g:
        members = [("trailing-stop-analyst", "design trailing exit per regime"),
                   ("regime-analyst", "judge 1H trend vs range"),
                   ("risk-officer", "set stop floor price*0.003")]
    elif "entry" in g:
        members = [("scene-analyst", "classify 1H regime"),
                   ("filter-analyst", "apply strict entry filters"),
                   ("backtester", "replay signals 2024-2026")]
    elif "filter" in g:
        members = [("filter-analyst", "evaluate F1/F3/F5 filters"),
                   ("verifier", "cross-validate per month")]
    else:
        members = [("writer", "gather PM context"),
                   ("analyst", "analyze signal"),
                   ("executor", "run loop round")]
    tasks = [{"id": str(i + 1), "member": m, "task": t, "deps": [] if i == 0 else [str(i)]}
             for i, (m, t) in enumerate(members)]
    tid = uuid.uuid4().hex[:6]
    _TEAM[tid] = {"goal": goal, "captain": "loop-orchestrator",
                  "members": members, "tasks": tasks, "status": "planned"}
    return {"ok": True, "team_id": tid, "captain": "loop-orchestrator",
            "members": members, "tasks": tasks}


def _run(team_id, executor_fn=None):
    t = _TEAM.get(team_id)
    if not t:
        return {"ok": False, "error": "team not found"}
    results = {}
    for task in t["tasks"]:
        prior = dict(results)
        member = task.get("member")
        if callable(executor_fn):
            try:
                res = executor_fn(member, task, prior)
            except Exception as exc:
                res = "executor-error:" + str(exc)[:80]
        else:
            res = "executed:" + str(task.get("task", ""))[:24]
        results[task["id"]] = res
    t["status"] = "done"
    return {"ok": True, "team_id": team_id, "captain": t["captain"],
            "run_state": "done", "tasks_done": len(results), "results": results}


def _status():
    return {"ok": True, "teams": [{"id": t, "goal": v["goal"], "status": v["status"],
            "tasks": len(v["tasks"])} for t, v in _TEAM.items()]}


def register(ctx):
    cfg = (ctx.config.get("plugins") or {}).get("agent-teams") or {}
    executor_fn = cfg.get("executor_fn")
    from tool_registry import ToolDefinition
    ctx.register_tool(ToolDefinition(name="team_plan", source="skill",
        handler=lambda payload=None, **k: _plan((payload or {}).get("goal")),
        description="Decompose a goal into captain+members+tasks plan. params: goal(str)."))
    ctx.register_tool(ToolDefinition(name="team_run", source="skill",
        handler=lambda payload=None, **k: _run((payload or {}).get("team_id"), executor_fn),
        description="Run a planned team's tasks in dep order. params: team_id(str). Offline default; inject executor_fn via config for real."))
    ctx.register_tool(ToolDefinition(name="team_status", source="skill",
        handler=lambda payload=None, **k: _status(), description="List planned teams."))
    return {"tools": ["team_plan", "team_run", "team_status"]}
