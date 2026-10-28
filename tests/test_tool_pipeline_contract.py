"""cycle-15 A: ToolPipeline 14-step contract.

tool_pipeline.ToolPipeline.execute() is the audited counterpart of
ToolRegistry.dispatch().  Until now only step 10 (tool execution / G-5 step
policy) was asserted, so every short-circuit branch (lookup miss, abort,
schema reject, permission deny) and the two adapters around the pipeline
(ToolOrchestrator, create_pipeline) were unverified: a regression could
silently turn a denial into a completed call, or drop a step from the audit
trail, without any test failing.

This file pins, for each step, (a) the audit record it must emit, (b) the
result verdict, and (c) that no later step runs after a short-circuit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from step_exception_policy import ErrorProcessType, ExceptionPolicy  # noqa: E402
from tool_pipeline import (  # noqa: E402
    ToolOrchestrator,
    ToolPipeline,
    create_pipeline,
)

PIPELINE_STEP_NAMES = [
    (1, "tool_lookup"),
    (2, "abort_check"),
    (3, "schema_validation"),
    (4, "semantic_validation"),
    (5, "classifier_skip"),
    (6, "input_backfill"),
    (7, "pre_tool_hooks"),
    (8, "permission_resolution"),
    (9, "permission_denied"),
    (10, "tool_execution"),
    (11, "result_budgeting"),
    (12, "post_tool_hooks"),
    (13, "new_messages"),
    (14, "error_handling"),
]


# ---- fakes -----------------------------------------------------------------

class _Tool:
    def __init__(self, handler, schema=None):
        self.handler = handler
        self.input_schema = schema if schema is not None else {"required": []}


class _Registry:
    def __init__(self, tools):
        self._tools = dict(tools)

    def dispatch(self, name, *args, **kwargs):  # used by ToolOrchestrator
        return {"status": "ok", "tool": name, "args": args, "kwargs": kwargs}


class _Hooks:
    def __init__(self, raise_on_emit=False):
        self.events = []
        self._raise = raise_on_emit

    def emit(self, name, payload):
        self.events.append((name, payload))
        if self._raise:
            raise RuntimeError("hook bus exploded")


class _Perm:
    def __init__(self, allowed, reason="policy"):
        self.allowed = allowed
        self.reason = reason


class _Gate:
    def __init__(self, perm):
        self.perm = perm
        self.calls = []

    def check_tool_call(self, name, params):
        self.calls.append((name, params))
        return self.perm


class _Signal:
    def __init__(self, aborted):
        self.aborted = aborted


class _Decision:
    def __init__(self, decision, reason="because"):
        self.decision = decision
        self.reason = reason


class _Guardian:
    def __init__(self, decision=None, raises=False):
        self._decision = decision
        self._raises = raises

    def assess(self, _ctx):
        if self._raises:
            raise RuntimeError("guardian blew up")
        return self._decision


def _ok_handler(params):
    return {"echo": params}


def _pipeline(handler=_ok_handler, **kw):
    reg = _Registry({"t": _Tool(handler)})
    return ToolPipeline(reg, **kw)


def _statuses(res):
    return {s.step: s.status for s in res.steps}


# ---- step 1: tool lookup ---------------------------------------------------

def test_step1_missing_tool_short_circuits():
    res = _pipeline().execute("nope", {})
    assert res.status == "error"
    assert res.error == "Tool not found: nope"
    assert [s.step for s in res.steps] == [1]
    assert res.steps[0].name == "tool_lookup"
    assert res.steps[0].status == "failed"
    assert "not found" in res.steps[0].detail
    assert res.result is None


def test_step1_registry_none_is_a_lookup_miss_not_a_crash():
    res = ToolPipeline(None).execute("t", {})
    assert res.status == "error"
    assert res.error == "Tool not found: t"
    assert [s.step for s in res.steps] == [1]


# ---- step 2: abort ---------------------------------------------------------

def test_step2_aborted_signal_blocks_before_execution():
    calls = {"n": 0}

    def handler(params):
        calls["n"] += 1
        return {}

    res = _pipeline(handler).execute("t", {}, signal=_Signal(True))
    assert res.status == "blocked"
    assert res.error == "aborted"
    assert calls["n"] == 0
    assert [s.step for s in res.steps] == [1, 2]
    assert _statuses(res)[2] == "failed"


def test_step2_non_aborted_signal_passes_through():
    res = _pipeline().execute("t", {}, signal=_Signal(False))
    assert res.status == "completed"
    assert _statuses(res)[2] == "passed"


# ---- step 3: schema --------------------------------------------------------

def test_step3_missing_required_param_rejects():
    reg = _Registry({"t": _Tool(_ok_handler,
                                schema={"required": ["alpha", "beta"]})})
    res = ToolPipeline(reg).execute("t", {"alpha": 1})
    assert res.status == "error"
    assert res.error == "Schema validation failed: missing ['beta']"
    assert [s.step for s in res.steps] == [1, 2, 3]
    assert _statuses(res)[3] == "failed"


def test_step3_satisfied_schema_passes():
    reg = _Registry({"t": _Tool(_ok_handler, schema={"required": ["alpha"]})})
    res = ToolPipeline(reg).execute("t", {"alpha": 1})
    assert res.status == "completed"
    assert _statuses(res)[3] == "passed"


def test_step3_is_skipped_for_schemaless_or_non_dict_params():
    reg = _Registry({"t": _Tool(_ok_handler, schema=None)})
    assert ToolPipeline(reg).execute("t", {}).status == "completed"
    reg2 = _Registry({"t": _Tool(_ok_handler, schema={"required": ["x"]})})
    # a non-dict params payload cannot be introspected -> schema is skipped
    assert ToolPipeline(reg2).execute("t", ["not", "a", "dict"]).status == "completed"


# ---- step 7: pre hooks -----------------------------------------------------

def test_step7_pre_hook_receives_tool_and_params():
    hooks = _Hooks()
    res = _pipeline(hook_bus=hooks).execute("t", {"k": "v"})
    assert res.status == "completed"
    assert hooks.events == [("tool/pre", {"tool": "t", "params": {"k": "v"}})]


def test_step7_hook_failure_is_swallowed_and_audited_as_passed():
    res = _pipeline(hook_bus=_Hooks(raise_on_emit=True)).execute("t", {})
    assert res.status == "completed"
    assert _statuses(res)[7] == "passed"


# ---- steps 8/9: permission -------------------------------------------------

def test_step8_denied_permission_blocks_and_records_two_steps():
    gate = _Gate(_Perm(False, reason="denylist:secrets/"))
    res = _pipeline(permission_gate=gate).execute("t", {"p": 1})
    assert res.status == "blocked"
    assert res.error == "Permission denied: denylist:secrets/"
    assert gate.calls == [("t", {"p": 1})]
    assert [s.step for s in res.steps] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert _statuses(res)[8] == "failed"
    assert _statuses(res)[9] == "failed"
    assert res.steps[-1].detail == "blocked"


def test_step9_after_allow_is_a_passed_no_op():
    gate = _Gate(_Perm(True))
    res = _pipeline(permission_gate=gate).execute("t", {})
    assert res.status == "completed"
    assert _statuses(res)[8] == "passed"
    assert _statuses(res)[9] == "passed"
    assert res.steps[-1].detail == "no-op"


# ---- happy path: the full 14-step audit trail ------------------------------

def test_happy_path_emits_all_14_steps_in_order():
    res = _pipeline().execute("t", {"x": 2})
    assert res.status == "completed"
    assert res.error is None
    assert res.result == {"echo": {"x": 2}}
    assert [(s.step, s.name) for s in res.steps] == PIPELINE_STEP_NAMES
    assert all(s.status == "passed" for s in res.steps)
    assert res.total_elapsed_ms >= 0


def test_steps_4_5_6_11_12_13_14_are_declared_no_ops():
    res = _pipeline().execute("t", {})
    noop = {4, 5, 6, 11, 12, 13, 14}
    for s in res.steps:
        if s.step in noop:
            assert s.detail in ("no-op", "no-op (not needed for local tools)")


# ---- step 10: policy plumbing ---------------------------------------------

def test_step10_throw_policy_reports_attempt_ceiling():
    calls = {"n": 0}

    def boom(_params):
        calls["n"] += 1
        raise ValueError("always")

    res = _pipeline(boom).execute("t", {},
                                  policy=ExceptionPolicy(max_retry=2))
    assert calls["n"] == 3                      # max_retry + 1 attempts
    assert res.status == "error"
    assert res.attempts == 3
    assert res.route == ""
    assert _statuses(res)[10] == "failed"


def test_step10_return_default_is_a_completed_route_not_an_error():
    def boom(_params):
        raise ValueError("hard fail")

    res = _pipeline(boom).execute(
        "t", {},
        policy=ExceptionPolicy(process_type=ErrorProcessType.RETURN_DEFAULT,
                               data_on_err={"fallback": True}))
    assert res.status == "completed"
    assert res.route == "return_default"
    assert res.result == {"fallback": True}
    assert res.error.startswith("ValueError: hard fail")
    assert _statuses(res)[10] == "fallback"


def test_step10_rejects_a_non_policy_object():
    with pytest.raises(TypeError):
        _pipeline().execute("t", {}, policy=object())


# ---- result serialization --------------------------------------------------

def test_to_dict_is_audit_ready():
    res = _pipeline().execute("t", {"x": 1})
    d = res.to_dict()
    assert d["tool"] == "t"
    assert d["status"] == "completed"
    assert d["attempts"] == 1
    assert d["route"] == ""
    assert [p["step"] for p in d["pipeline"]] == [n for n, _ in PIPELINE_STEP_NAMES]
    assert isinstance(d["elapsed_ms"], float)


# ---- ToolOrchestrator adapter ---------------------------------------------

def test_orchestrator_dispatches_flat_params_as_kwargs():
    out = ToolOrchestrator(_Registry({"t": _Tool(_ok_handler)})).execute(
        "t", {"a": 1, "b": 2})
    assert out["status"] == "ok"
    assert out["kwargs"] == {"a": 1, "b": 2}


def test_orchestrator_splits_explicit_args_and_kwargs():
    out = ToolOrchestrator(_Registry({"t": _Tool(_ok_handler)})).execute(
        "t", {"args": (1, 2), "kwargs": {"k": 3}})
    assert out["args"] == (1, 2)
    assert out["kwargs"] == {"k": 3}


def test_orchestrator_guardian_deny_and_escalate_are_fail_closed():
    reg = _Registry({"t": _Tool(_ok_handler)})
    for verdict in ("deny", "escalate"):
        out = ToolOrchestrator(reg, guardian=_Guardian(_Decision(verdict))).execute(
            "t", {}, ctx=object())
        assert out == {"status": "denied", "reason": "because"}


def test_orchestrator_guardian_allow_proceeds():
    reg = _Registry({"t": _Tool(_ok_handler)})
    out = ToolOrchestrator(reg, guardian=_Guardian(_Decision("allow"))).execute(
        "t", {}, ctx=object())
    assert out["status"] == "ok"


def test_orchestrator_guardian_error_is_fail_closed():
    reg = _Registry({"t": _Tool(_ok_handler)})
    out = ToolOrchestrator(reg, guardian=_Guardian(raises=True)).execute(
        "t", {}, ctx=object())
    assert out["status"] == "denied"
    assert out["reason"].startswith("guardian error:")


def test_orchestrator_normalizes_dispatch_failure():
    class _Boom:
        _tools = {}

        def dispatch(self, *_a, **_kw):
            raise RuntimeError("dispatch exploded")

    out = ToolOrchestrator(_Boom()).execute("t", {})
    assert out["status"] == "error"
    assert out["error_code"] == "orchestrator_dispatch_failed"
    assert "dispatch exploded" in out["error"]


def test_create_pipeline_reads_the_orchestrator_wiring():
    class _Orch:
        tool_registry = _Registry({"t": _Tool(_ok_handler)})
        _hook_bus = _Hooks()
        _permission_gate = _Gate(_Perm(True))

    pipeline = create_pipeline(_Orch())
    assert isinstance(pipeline, ToolPipeline)
    assert pipeline.registry is _Orch.tool_registry
    assert pipeline.hook_bus is _Orch._hook_bus
    assert pipeline.permission_gate is _Orch._permission_gate
    assert pipeline.execute("t", {}).status == "completed"


def test_create_pipeline_tolerates_a_bare_orchestrator():
    pipeline = create_pipeline(object())
    assert pipeline.registry is None and pipeline.hook_bus is None
    assert pipeline.permission_gate is None