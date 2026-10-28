"""cycle-7 A4: failure-scope classification + two-level circuit registry.

Distilled from TencentCloud/Octop v1.0.2 providers/health.py. Verifies the
loop-local port keeps the upstream semantics: three-way scope classification,
model vs provider circuit isolation, exponential cooldown (base/5x/max), and a
half-open single-flight probe at BOTH levels.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from failure_scope import (  # noqa: E402
    FailureDecision,
    FailureScope,
    classify_failure,
    provider_of,
)
from failure_scope_registry import ModelHealthRegistry  # noqa: E402


class _Clock:
    """Deterministic monotonic stand-in."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


def _registry(**kw) -> ModelHealthRegistry:
    clock = _Clock()
    reg = ModelHealthRegistry(time_fn=clock, **kw)
    reg._test_clock = clock  # convenience handle (not part of public API)
    return reg


# -- failure_scope.classify_failure ----------------------------------------

def test_scope_enum_values():
    assert FailureScope.NONE.value == "none"
    assert FailureScope.MODEL.value == "model"
    assert FailureScope.PROVIDER.value == "provider"


def test_provider_of_splits_on_slash():
    assert provider_of("openai/gpt-4o") == "openai"
    assert provider_of("anthropic/claude") == "anthropic"
    assert provider_of("bare-model") == "bare-model"
    assert provider_of("") == ""


def test_model_not_found_is_model_scope():
    d = classify_failure(ValueError("Model not found: gpt-9"))
    assert d == FailureDecision(True, "model_not_found", FailureScope.MODEL)


def test_provider_markers_are_provider_scope():
    for msg in ("401 unauthorized", "invalid api key", "rate limit exceeded",
                "insufficient balance", "HTTP 429"):
        d = classify_failure(RuntimeError(msg))
        assert d.scope is FailureScope.PROVIDER, msg
        assert d.failover is True, msg


def test_model_markers_are_model_scope():
    for msg in ("model call failed", "stream stall detected",
                "connection reset by peer", "HTTP 503"):
        d = classify_failure(RuntimeError(msg))
        assert d.scope is FailureScope.MODEL, msg
        assert d.failover is True, msg


def test_bare_timeout_and_connection_errors_are_model_scope():
    assert classify_failure(TimeoutError()).scope is FailureScope.MODEL
    assert classify_failure(ConnectionError()).scope is FailureScope.MODEL


def test_unknown_error_is_none_scope_no_failover():
    d = classify_failure(ValueError("bad request body"))
    assert d == FailureDecision(False, "request_error", FailureScope.NONE)


def test_explicit_detail_overrides_exception_text():
    # The exception says nothing; the explicit detail carries the marker.
    d = classify_failure(ValueError("boom"), detail="model not found")
    assert d.scope is FailureScope.MODEL
    # Explicit detail that is a clean request error wins even if exc looked bad.
    d2 = classify_failure(TimeoutError("timeout"), detail="bad request body")
    assert d2.scope is FailureScope.NONE


def test_classify_is_pure_and_repeatable():
    e = RuntimeError("rate limit")
    assert classify_failure(e) == classify_failure(e) == classify_failure(e)


# -- exponential cooldown ---------------------------------------------------

def test_cooldown_curve_base_5x_max():
    reg = _registry(base_cooldown_s=60.0, max_cooldown_s=900.0)
    assert reg.cooldown_for(1) == 60.0
    assert reg.cooldown_for(0) == 60.0
    assert reg.cooldown_for(2) == min(300.0, 900.0)
    assert reg.cooldown_for(3) == 900.0
    assert reg.cooldown_for(99) == 900.0


def test_cooldown_5x_respects_max_cap():
    reg = _registry(base_cooldown_s=500.0, max_cooldown_s=900.0)
    assert reg.cooldown_for(2) == 900.0  # 5x=2500 capped to max


def test_cooldown_clamps_negative_input():
    reg = _registry(base_cooldown_s=-5.0, max_cooldown_s=10.0)
    assert reg.base_cooldown_s == 0.0
    assert reg.max_cooldown_s == 10.0


# -- model vs provider isolation -------------------------------------------

def test_model_scope_opens_only_that_model():
    reg = _registry()
    reg.record_failure("openai/gpt-4o", scope=FailureScope.MODEL, kind="model_error")
    assert reg.is_routable("openai/gpt-4o") is False
    assert reg.is_routable("openai/gpt-4o-mini") is True   # sibling survives
    assert reg.is_routable("anthropic/claude") is True     # other provider


def test_provider_scope_quarantines_whole_provider():
    reg = _registry()
    reg.record_failure("openai/gpt-4o", scope=FailureScope.PROVIDER, kind="auth")
    assert reg.is_routable("openai/gpt-4o") is False
    assert reg.is_routable("openai/gpt-4o-mini") is False  # whole provider down
    assert reg.is_routable("anthropic/claude") is True


def test_none_scope_does_not_quarantine():
    reg = _registry()
    reg.record_failure("openai/gpt-4o", scope=FailureScope.NONE, kind="request_error")
    assert reg.is_routable("openai/gpt-4o") is True


def test_success_closes_both_levels():
    reg = _registry()
    reg.record_failure("openai/gpt-4o", scope=FailureScope.PROVIDER)
    assert reg.is_routable("openai/gpt-4o") is False
    reg.record_success("openai/gpt-4o")
    assert reg.is_routable("openai/gpt-4o") is True


def test_model_failure_clears_stale_provider_circuit():
    reg = _registry()
    # Open the provider circuit, then let it expire...
    reg.record_failure("openai/gpt-4o", scope=FailureScope.PROVIDER)
    reg._test_clock.advance(1000.0)   # past max cooldown
    assert reg.is_routable("openai/gpt-4o") is True
    # A MODEL-scope failure now must drop the expired provider entry (not
    # count it as a second provider failure).
    reg.record_failure("openai/gpt-4o", scope=FailureScope.MODEL)
    assert reg.is_routable("openai/gpt-4o-mini") is True, "provider entry was cleared"
    assert reg.is_routable("openai/gpt-4o") is False, "only this model is open"


# -- exponential re-open on repeated failures ------------------------------

def test_repeated_provider_failures_escalate_cooldown():
    reg = _registry(base_cooldown_s=60.0, max_cooldown_s=900.0)
    clk = reg._test_clock
    reg.record_failure("p/m", scope=FailureScope.PROVIDER)   # failures=1 -> 60s
    open_for_1 = reg._providers["p"].open_until - clk.now
    assert open_for_1 == 60.0
    clk.advance(61.0)
    reg.record_failure("p/m", scope=FailureScope.PROVIDER)   # failures=2 -> 300s
    open_for_2 = reg._providers["p"].open_until - clk.now
    assert open_for_2 == 300.0
    clk.advance(301.0)
    reg.record_failure("p/m", scope=FailureScope.PROVIDER)   # failures=3 -> 900s
    open_for_3 = reg._providers["p"].open_until - clk.now
    assert open_for_3 == 900.0


# -- half-open single-flight probe -----------------------------------------

def test_half_open_admits_one_probe_at_model_level():
    reg = _registry(base_cooldown_s=60.0)
    reg.record_failure("p/m", scope=FailureScope.MODEL)
    assert reg.begin_attempt("p/m") is False        # open
    reg._test_clock.advance(61.0)
    assert reg.is_routable("p/m") is True           # cooldown elapsed
    assert reg.begin_attempt("p/m") is True         # first probe
    assert reg.begin_attempt("p/m") is False        # single-flight (probe in flight)
    reg.record_success("p/m")
    assert reg.begin_attempt("p/m") is True         # recovered


def test_half_open_probe_failure_reopens():
    reg = _registry(base_cooldown_s=60.0)
    reg.record_failure("p/m", scope=FailureScope.MODEL)
    reg._test_clock.advance(61.0)
    assert reg.begin_attempt("p/m") is True
    reg.record_failure("p/m", scope=FailureScope.MODEL)
    assert reg.is_routable("p/m") is False          # re-opened


def test_provider_level_single_flight_blocks_siblings():
    reg = _registry(base_cooldown_s=60.0)
    reg.record_failure("p/m1", scope=FailureScope.PROVIDER)
    reg._test_clock.advance(61.0)
    assert reg.begin_attempt("p/m1") is True        # reserve provider probe
    assert reg.begin_attempt("p/m2") is False       # sibling blocked while probing


# -- snapshot ---------------------------------------------------------------

def test_snapshot_reports_open_scope():
    reg = _registry()
    assert reg.snapshot("p/m")["open_scope"] == "none"
    assert reg.snapshot("p/m")["healthy"] is True
    reg.record_failure("p/m", scope=FailureScope.PROVIDER)
    snap = reg.snapshot("p/m")
    assert snap["open_scope"] == "provider"
    assert snap["failures"] == 1
    assert snap["healthy"] is False
    assert snap["provider"] == "p"


def test_snapshot_is_json_safe():
    import json
    reg = _registry()
    reg.record_failure("p/m", scope=FailureScope.MODEL)
    json.dumps(reg.snapshot("p/m"))  # must not raise


# -- config wiring (composition root) ---------------------------------------

def test_registry_defaults_match_octop():
    reg = ModelHealthRegistry()
    assert reg.base_cooldown_s == 60.0
    assert reg.max_cooldown_s == 900.0

# -- composition-root wiring (orchestrator) ---------------------------------

def _tiny_cfg(td):
    import json as _json
    from config_util import deep_merge, DEFAULT_CONFIG
    db = pathlib_join(td, "p.db")
    sig = pathlib_join(td, "signals.json")
    with open(sig, "w", encoding="utf-8") as fh:
        _json.dump([{"signal_pattern": "fail-me-please", "market_condition": "m"}], fh)
    return deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": td, "db": db},
        "memory": {"sqlite_path": db},
        "loop": {"max_rounds": 1, "no_progress_stop": 3,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0,
                 "signals": sig},
        "backtest": {"script": "backtest/does_not_exist.py", "extra_args": ""},
    })


def pathlib_join(td, name):
    import os as _os
    return _os.path.join(td, name)


def test_orchestrator_creates_health_registry(tmp_path):
    from orchestrator import Orchestrator  # noqa: E402
    o = Orchestrator(_tiny_cfg(str(tmp_path)))
    assert isinstance(o.health, ModelHealthRegistry)
    assert o.health.base_cooldown_s == 60.0
    assert o.health.max_cooldown_s == 900.0


def test_orchestrator_health_registry_reads_config(tmp_path):
    cfg = _tiny_cfg(str(tmp_path))
    cfg["loop"]["provider_base_cooldown_seconds"] = 5
    cfg["loop"]["provider_max_cooldown_seconds"] = 30
    from orchestrator import Orchestrator  # noqa: E402
    o = Orchestrator(cfg)
    assert o.health.base_cooldown_s == 5.0
    assert o.health.max_cooldown_s == 30.0


def test_health_registry_coexists_with_controller_breaker(tmp_path):
    from orchestrator import Orchestrator  # noqa: E402
    from circuit_breaker import CircuitBreaker  # noqa: E402
    o = Orchestrator(_tiny_cfg(str(tmp_path)))
    # the per-controller breaker is untouched by the fleet registry
    assert isinstance(o.circuit, CircuitBreaker)
    assert o.controller.breaker is o.circuit
    # fleet registry is a separate object with independent state
    o.health.record_failure("p/m", scope=FailureScope.PROVIDER)
    assert o.health.is_routable("p/m") is False
    assert o.circuit.state == "CLOSED", "fleet failure must not open the controller breaker"
