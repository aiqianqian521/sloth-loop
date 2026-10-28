"""dsh-todo (Python port) - model-facing whole-list todo tool.

Translated (not copied) from @deepseek-ai/dsh-tool-todo (TS).

Domain essence (preserved):
  - The tool writes the WHOLE list every call; replay is last-write-wins.
    Entries therefore need no stable identity (content + status only).
  - Three-state lifecycle: pending | in_progress | completed.
  - `content` must be non-empty after trim and unique across the list.
  - Single-active discipline by default: at most ONE item may be `in_progress`.
    Config `allow_parallel_in_progress=true` lifts that (subagents/fan-out).
  - The projection `todos` holds the latest snapshot; cleared on `turn/start`
    (finished checklist stays visible through turn/end).

Tools: todo_write.
params: {"todos": [{"content": str, "status": "pending|in_progress|completed"}, ...]}
"""
from __future__ import annotations

import logging

_log = logging.getLogger("sloth_engine.plugin.dsh-todo")

STATUSES = ("pending", "in_progress", "completed")

_DESC_HEAD = (
    "Record and update a task list to plan multi-step work and show progress; "
    "skip it for trivial single-step tasks. Add one todo per concrete step "
    "before you start. "
)
_DESC_PARALLEL = (
    "While work remains, keep the todos being worked on `in_progress`, several "
    "only when work runs in parallel. "
)
_DESC_SINGLE = "While work remains, keep exactly one todo `in_progress`. "
_DESC_TAIL = "Mark each todo `completed` as soon as it is done."


def describe(allow_parallel: bool) -> str:
    return _DESC_HEAD + (_DESC_PARALLEL if allow_parallel else _DESC_SINGLE) + _DESC_TAIL


def to_todo_list(raw, allow_parallel: bool):
    """Validate + canonicalize the model-supplied list.

    Mirrors dsh-tool-todo toTodoList(): trimmed non-empty unique content, and
    at most one `in_progress` unless parallel is allowed. Raises ValueError on
    any violation (fail-loud at the boundary).
    """
    todos = []
    seen = set()
    active = 0
    for item in raw or []:
        if not isinstance(item, dict):
            raise ValueError("invalid todo: each item must be an object")
        content = str(item.get("content") or "").strip()
        status = item.get("status")
        if not content:
            raise ValueError("invalid todo: `content` must be a non-empty string")
        if status not in STATUSES:
            raise ValueError(
                f"invalid todo: `status` must be one of {STATUSES}, got {status!r}")
        if content in seen:
            raise ValueError(f"invalid todos: duplicate content {content!r}")
        seen.add(content)
        if status == "in_progress":
            active += 1
        todos.append({"content": content, "status": status})
    if not allow_parallel and active > 1:
        raise ValueError(
            f"invalid todos: at most one task may be in_progress (got {active})")
    return todos


class TodoProjection:
    """Latest whole-list snapshot (last-write-wins), cleared on turn/start."""

    def __init__(self):
        self._state = None  # None before first write / after turn/start

    def apply(self, event_type: str, data=None):
        if event_type == "todo/write":
            self._state = list((data or {}).get("todos") or [])
        elif event_type == "turn/start":
            self._state = None
        return self._state

    @property
    def todos(self):
        return self._state


# process-wide projection singleton (one owning agent list, codex parity)
_PROJECTION = TodoProjection()


def _todo_write(payload, allow_parallel=False):
    p = payload or {}
    raw = p.get("todos")
    if raw is None:
        return {"ok": False, "error": "todos required (a list of {content,status})"}
    try:
        todos = to_todo_list(raw, allow_parallel)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    _PROJECTION.apply("todo/write", {"todos": todos})
    _log.info("[todo] write %d item(s): %s", len(todos),
              ", ".join(f"{t['content']}:{t['status']}" for t in todos))
    return {"ok": True, "count": len(todos), "todos": todos,
            "allow_parallel": allow_parallel}


def register(ctx):
    from tool_registry import ToolDefinition

    cfg = {}
    try:
        cfg = (getattr(ctx, "config", None) or {}).get("dsh-todo") or {}
    except Exception:
        cfg = {}
    allow_parallel = bool(cfg.get("allow_parallel_in_progress", False))

    ctx.register_tool(ToolDefinition(
        name="todo_write", source="skill",
        handler=lambda payload=None, **k: _todo_write(payload, allow_parallel),
        description=describe(allow_parallel) +
                    " params: {todos:[{content:str,status:pending|in_progress|completed}]}."))
    return {"tools": ["todo_write"], "projection": "todos",
            "allow_parallel": allow_parallel}
