"""P2-2: 工具执行14步管线对标 — 对标 Claude Code checkPermissionsAndCallTool().

将现有 tool_registry.dispatch() 扩展为更细粒度的管线，增加可观测性。
每一步产生事件记录，用于事后审计。

对标 CC 14步:
1. Tool Lookup → 2. Abort Check → 3. Schema Validation
4. Semantic Validation → 5. Speculative Classifier
6. Input Backfill → 7. PreToolUse Hooks
8. Permission Resolution → 9. Permission Denied?
10. Tool Execution → 11. Result Budgeting
12. PostToolUse Hooks → 13. New Messages → 14. Error Handling

本模块不与现有 dispatch() 冲突——可作为增强的 `dispatch_audited()` 替代使用。
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# G-5 (cycle-10): wire the opt-in step exception policy into the 14-step
# pipeline's step 10 (tool execution).  Same engine-root bootstrap as
# adapters/task_runner.py.
_ENGINE_DIR = Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from step_exception_policy import ExceptionPolicy, apply_policy  # noqa: E402

_log = logging.getLogger("sloth_engine.tool-pipeline")

# ── 审计事件 ───────────────────────────────────────────

@dataclass
class PipelineStep:
    """管线步骤记录。"""
    step: int
    name: str
    status: str  # passed | failed | skipped
    elapsed_ms: float = 0.0
    detail: str = ""


@dataclass
class ToolPipelineResult:
    """工具执行完整审计结果。"""
    tool_name: str
    status: str  # completed | blocked | error
    result: Any = None
    error: Optional[str] = None
    total_elapsed_ms: float = 0.0
    steps: list[PipelineStep] = field(default_factory=list)
    # G-5: step-10 attempts and the fallback route (0 / "" = legacy single try).
    attempts: int = 0
    route: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool_name,
            "status": self.status,
            "error": self.error,
            "elapsed_ms": round(self.total_elapsed_ms, 2),
            "attempts": self.attempts,
            "route": self.route,
            "pipeline": [
                {"step": s.step, "name": s.name, "status": s.status,
                 "elapsed_ms": round(s.elapsed_ms, 2), "detail": s.detail}
                for s in self.steps
            ],
        }


# ── 14步管线执行器 ─────────────────────────────────────

class ToolPipeline:
    """14步工具执行管线 — 对标 CC checkPermissionsAndCallTool()。

    用法:
        pipeline = ToolPipeline(registry, hook_bus, permission_gate)
        result = pipeline.execute("tool_name", {"arg": "value"})
    """

    def __init__(self, tool_registry=None, hook_bus=None, permission_gate=None):
        self.registry = tool_registry
        self.hook_bus = hook_bus
        self.permission_gate = permission_gate

    def execute(
        self,
        tool_name: str,
        params: dict,
        *,
        signal: Any = None,
        policy: ExceptionPolicy | None = None,
        is_interrupt: Callable[[BaseException], bool] | None = None,
    ) -> ToolPipelineResult:
        """执行完整的14步管线。"""
        t0 = time.time()
        steps: list[PipelineStep] = []
        result = ToolPipelineResult(tool_name=tool_name, status="pending")

        def _step(num: int, name: str):
            t = time.time()
            return t, num, name

        def _done(t_start, num, name, status, detail=""):
            elapsed = (time.time() - t_start) * 1000
            steps.append(PipelineStep(step=num, name=name, status=status,
                                       elapsed_ms=elapsed, detail=detail))
            return elapsed

        # ── Step 1: Tool Lookup ────────────────────────
        ts, n, name = _step(1, "tool_lookup")
        tool = None
        if self.registry:
            tool = self.registry._tools.get(tool_name)
        if tool is None:
            _done(ts, n, name, "failed", f"tool '{tool_name}' not found")
            result.status = "error"
            result.error = f"Tool not found: {tool_name}"
            result.total_elapsed_ms = (time.time() - t0) * 1000
            result.steps = steps
            return result
        _done(ts, n, name, "passed")

        # ── Step 2: Abort Check ────────────────────────
        ts, n, name = _step(2, "abort_check")
        if signal is not None and hasattr(signal, 'aborted') and signal.aborted:
            _done(ts, n, name, "failed", "aborted")
            result.status = "blocked"
            result.error = "aborted"
            result.total_elapsed_ms = (time.time() - t0) * 1000
            result.steps = steps
            return result
        _done(ts, n, name, "passed")

        # ── Step 3: Schema Validation ──────────────────
        ts, n, name = _step(3, "schema_validation")
        schema = getattr(tool, 'input_schema', None)
        if schema and isinstance(params, dict):
            required = schema.get("required", [])
            missing = [k for k in required if k not in params]
            if missing:
                _done(ts, n, name, "failed", f"missing: {missing}")
                result.status = "error"
                result.error = f"Schema validation failed: missing {missing}"
                result.total_elapsed_ms = (time.time() - t0) * 1000
                result.steps = steps
                return result
        _done(ts, n, name, "passed")

        # ── Step 4-6: Prepared (合并) ──────────────────
        for step_num, step_name in [(4, "semantic_validation"), (5, "classifier_skip"), (6, "input_backfill")]:
            ts, n, name = _step(step_num, step_name)
            _done(ts, n, name, "passed", "no-op (not needed for local tools)")

        # ── Step 7: PreToolUse Hooks ───────────────────
        ts, n, name = _step(7, "pre_tool_hooks")
        if self.hook_bus:
            try:
                self.hook_bus.emit("tool/pre", {"tool": tool_name, "params": params})
            except Exception:
                pass
        _done(ts, n, name, "passed")

        # ── Step 8-9: Permission ───────────────────────
        ts, n, name = _step(8, "permission_resolution")
        if self.permission_gate:
            perm = self.permission_gate.check_tool_call(tool_name, params)
            if not perm.allowed:
                _done(ts, n, name, "failed", f"denied: {perm.reason}")
                _done(time.time(), 9, "permission_denied", "failed", "blocked")
                result.status = "blocked"
                result.error = f"Permission denied: {perm.reason}"
                result.total_elapsed_ms = (time.time() - t0) * 1000
                result.steps = steps
                return result
        _done(ts, n, name, "passed")
        _done(time.time(), 9, "permission_denied", "passed", "no-op")

        # ── Step 10: Execute ───────────────────────────
        ts, n, name = _step(10, "tool_execution")
        step_policy = policy if policy is not None else ExceptionPolicy()
        if not isinstance(step_policy, ExceptionPolicy):
            raise TypeError("policy must be an ExceptionPolicy")
        try:
            handler = tool.handler
            outcome = apply_policy(step_policy, lambda: handler(params),
                                   is_interrupt=is_interrupt)
        except Exception as exc:
            _done(ts, n, name, "failed", str(exc)[:120])
            result.status = "error"
            result.error = str(exc)
            # A THROW policy only escapes apply_policy after exhausting every
            # attempt, so the ceiling is the true attempt count here.
            result.attempts = step_policy.max_attempts
            result.total_elapsed_ms = (time.time() - t0) * 1000
            result.steps = steps
            return result
        raw_result = outcome.value
        result.attempts = outcome.attempts
        if not outcome.ok:
            # G-5 fallback policy: the step no longer fails the pipeline; the
            # raw error is kept for audit and the route is surfaced.
            _done(ts, n, name, "fallback", str(outcome.error or "")[:120])
            result.error = outcome.error
            result.route = outcome.route
        else:
            _done(ts, n, name, "passed")

        # ── Step 11-14: Post-exec ──────────────────────
        for step_num, step_name in [(11, "result_budgeting"), (12, "post_tool_hooks"),
                                      (13, "new_messages"), (14, "error_handling")]:
            ts, n, name = _step(step_num, step_name)
            _done(ts, n, name, "passed", "no-op")

        # ── Final ───────────────────────────────────────
        result.status = "completed"
        result.result = raw_result
        result.total_elapsed_ms = (time.time() - t0) * 1000
        result.steps = steps
        return result



# ── Tool Orchestrator ──────────────────────────────────

class ToolOrchestrator:
    """Codex tools/orchestrator analogue: approval -> sandbox -> attempt -> retry.

    Rather than re-implement the pipeline (ToolRegistry.dispatch already owns
    permission gate -> pre_hooks -> guards -> execute -> post_hooks), this is a
    thin adapter so callers get the Codex-shaped entry point while the proven
    single dispatch path stays the one source of truth. Optional guardian is
    consulted first (fail-closed on deny/escalate).
    """

    def __init__(self, registry, guardian=None, sandbox=None):
        self.registry = registry
        self.guardian = guardian
        self.sandbox = sandbox

    def execute(self, tool_name: str, params: dict | None = None, ctx=None) -> dict:
        """Run one tool through the unified dispatch pipeline.

        params: {"args": tuple, "kwargs": dict, ...} (else treated as kwargs).
        Never raises for tool-level failures: returns a normalized dict.
        """
        params = params or {}
        args = tuple(params.get("args", ()))
        kwargs = dict(params.get("kwargs", {}))
        if not args and not kwargs:
            # Allow flat params dicts as pure kwargs, excluding control keys.
            kwargs = {k: v for k, v in params.items()
                      if k not in ("args", "kwargs", "name")}

        # 1. Approval (guardian), fail-closed.
        if self.guardian is not None and ctx is not None:
            try:
                decision = self.guardian.assess(ctx)
                if getattr(decision, "decision", "allow") in ("deny", "escalate"):
                    return {"status": "denied",
                            "reason": getattr(decision, "reason", "guardian denied")}
            except Exception as exc:  # pragma: no cover - defensive
                return {"status": "denied", "reason": f"guardian error: {exc}"}

        # 2-4. sandbox/attempt/retry are owned by dispatch (guards + hooks).
        try:
            return self.registry.dispatch(tool_name, *args, **kwargs)
        except Exception as exc:
            return {"status": "error", "error": str(exc),
                    "error_code": "orchestrator_dispatch_failed"}


def create_pipeline(orchestrator) -> ToolPipeline:
    """从 Orchestrator 实例创建管线（零额外配置）。"""
    return ToolPipeline(
        tool_registry=getattr(orchestrator, 'tool_registry', None),
        hook_bus=getattr(orchestrator, '_hook_bus', None),
        permission_gate=getattr(orchestrator, '_permission_gate', None),
    )
