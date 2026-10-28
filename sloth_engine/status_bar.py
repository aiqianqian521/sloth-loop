"""OODA 7-step status bar UI.

Extracted from orchestrator.py as part of P2.1 Slice A
(god-file split). Behavior unchanged; re-exported by orchestrator.py for back-compat.
"""
from __future__ import annotations

import time

class StatusBar:
    """OODA 7-step status bar with real-time flow graph visualization."""

    STEPS = ["Understand", "Observe", "Orient", "Decide", "Act", "Verify", "Learn"]
    STEP_ICONS = {"Understand": "U", "Observe": "O1", "Orient": "O2",
                  "Decide": "D", "Act": "A", "Verify": "V", "Learn": "L"}
    STEP_LABELS = {"Understand": "Understand Task",
                   "Observe": "Observe State",
                   "Orient": "Diagnose Root Cause",
                   "Decide": "Make Decision",
                   "Act": "Execute Action",
                   "Verify": "Verify Results",
                   "Learn": "Record Lessons"}

    def __init__(self, round_num: int, task_name: str = "", max_rounds: int = 0,
                 annotation_enabled: bool = False):
        self.round_num = round_num
        self.task_name = task_name
        self.max_rounds = max_rounds
        self.current_step = 0
        self.completed: list[str] = []
        self.issues: list[dict] = []
        self.suggestions: list[str] = []
        self._step_msgs: dict[str, str] = {}
        self._start_time = time.time()
        self._decision_branch = ""  # "execute" | "skip_backtest" | "skip"
        self.annotation_enabled = annotation_enabled  # v2.0 P0-3

    # ── v2.0 P0-3: 推理标注 ────────────────────────────────
    _ANNOTATION_TAGS = {
        "data": "[数据]",
        "inference": "[推理]",
        "conclusion": "[结论]",
    }

    def _tag(self, kind: str, msg: str) -> str:
        """Add inference annotation tag if enabled."""
        if self.annotation_enabled:
            tag = self._ANNOTATION_TAGS.get(kind, "")
            return f"{tag} {msg}" if tag else msg
        return msg

    def render_flow(self):
        """Render ASCII flow graph showing 7-step pipeline with current position."""
        nodes = []
        status = []
        for s in self.STEPS:
            icon = self.STEP_ICONS[s]
            is_current = (s == self.STEPS[self.current_step])
            is_done = s in self.completed

            # Node label: add branch annotation at Decision point
            if s == "Decide" and self._decision_branch:
                label = f"{icon}:{self._decision_branch}"
            else:
                label = icon

            if is_done:
                nodes.append(f"[{label}]")
                status.append("V")
            elif is_current:
                nodes.append(f"({label})")
                status.append(">")
            else:
                nodes.append(f" {label} ")
                status.append(".")

        flow_line = "--".join(nodes) + "--(loop)"
        status_line = "   ".join(status)
        print(f"  Flow:  {flow_line}")
        print(f"         {status_line}")

    def set_decision(self, branch: str):
        """Set the decision branch for flow visualization."""
        self._decision_branch = branch

    def begin_step(self, step: str, detail: str = ""):
        self.current_step = self.STEPS.index(step)
        self.render_flow()
        icon = self.STEP_ICONS.get(step, step)
        label = self.STEP_LABELS.get(step, step)
        msg = f"[{step}] {icon} {label}"
        if detail:
            msg += f": {detail}"
        print(msg)

    def end_step(self, step: str, result: str = "ok"):
        self.completed.append(step)
        self._step_msgs[step] = result
        icon = "V" if "ok" in result.lower() or step in self.completed else "X"
        print(f"  {icon} {step}: {result}")

    def add_issue(self, severity: str, rule_id: str, msg: str):
        self.issues.append({"severity": severity, "rule": rule_id, "msg": msg})
        tag = "[BLOCK]" if severity == "block" else "[WARN]"
        print(f"  {tag} {rule_id}: {msg}")

    def add_suggestion(self, msg: str):
        self.suggestions.append(msg)

    def render_summary(self):
        """Output this round's OODA status summary."""
        elapsed = time.time() - self._start_time
        n = len(self.completed)
        total = len(self.STEPS)
        bar_width = 30
        filled = int(bar_width * n / total)
        bar = "=" * filled + "-" * (bar_width - filled)

        print()
        print("=" * 56)
        print(f"  Loop Round {self.round_num}"
              + (f"/{self.max_rounds}" if self.max_rounds else "")
              + f"  |  {self.task_name}")
        print(f"  Steps: [{bar}] {n}/{total}  ({elapsed:.1f}s)")
        step_line = "  "
        for i, s in enumerate(self.STEPS):
            if s in self.completed:
                step_line += f"[{self.STEP_ICONS[s]}]"
            elif i == self.current_step:
                step_line += f"({self.STEP_ICONS[s]})"
            else:
                step_line += f" {self.STEP_ICONS[s]} "
        print(step_line)

        if self.issues:
            print(f"  Issues ({len(self.issues)}):")
            for iss in self.issues[:5]:
                tag = "BLOCK" if iss["severity"] == "block" else "WARN"
                print(f"    [{tag}] {iss['rule']}: {iss['msg'][:60]}")

        if self.suggestions:
            print(f"  Suggestions:")
            for sug in self.suggestions[:3]:
                print(f"    -> {sug[:70]}")

        print("=" * 56)

    def final(self, verified: dict, learned: dict):
        """Final status output with verification and learning summary."""
        self.render_summary()
        vp = verified.get("pass_count", 0)
        vt = verified.get("total", 0)
        nf = learned.get("new_failures", 0)
        ns = learned.get("new_successes", 0)
        msg = (f"Verify: {vp}/{vt} criteria passed | "
               f"Learn: +{nf} failures, +{ns} successes")
        print(f"  >>> {msg}")
        print()
