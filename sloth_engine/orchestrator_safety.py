"""Orchestrator safe-component mixin - H1-P3a orchestrator godfile split (behavior-preserving).

_safe_run_component (@staticmethod) moved from orchestrator.Orchestrator to this mixin;
Orchestrator inherits it. Pure function: flattens a run-id component into a safe
filesystem segment (no path separators / traversal / control chars). No deps except
re (imported inside the method).
"""
from __future__ import annotations


class SafeComponentMixin:

    @staticmethod
    def _safe_run_component(name: object) -> str:
        """W2-BOUNDARY-01 / H2 Slice 1-PATH: flatten a config-supplied run-id
        component (task.name) into a single safe filesystem segment so that
        ``circuit-{run_id}.jsonl`` and archive dirs cannot traverse the
        runtime root via path separators, traversal dots, or control chars.

        Single dots inside a name are preserved (e.g. ``loop.v2``); only the
        path-making characters are flattened.
        """
        import re
        s = str(name) if name is not None else ""
        s = re.sub(r"[\\/\x00-\x1f]+", "_", s)
        s = s.replace("..", "_")
        s = s.strip("._") or "loop"
        return s
