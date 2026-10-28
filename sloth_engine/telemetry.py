"""Telemetry backend abstraction (observability dimension 10) - M1-1.

Pluggable trace/metrics backend with a factory create_backend(type) that assembles
multiple backends (noop / console / ...) and degrades to NoopTraceBackend when a
backend is missing or fails to load, so an observability fault never breaks the
core path.

Spec (architect-observability SKILL.md checklist, B-corrected 2026-09-05):
'telemetry backend pluggable factory + noop fallback' (true value: createBackend(type)
factory multi-backend + NoopTraceBackend unavailable degradation). The factory MUST
NEVER raise into the hot path.

This module is the additive scaffolding only; pipeline trace_id propagation and
SLI/SLO wiring are follow-on slices (M1-2+). Adopting it does not change existing
behavior.
"""
from __future__ import annotations

import sys
import enum
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TraceBackend(Protocol):
    """Minimal trace/metrics backend surface (observability dimension 10).

    Implementations MUST keep the public surface fault-tolerant: a backend that
    cannot honour a call no-ops rather than raising into the core path.
    """

    def report_span(self, *, trace_id: str, name: str, **fields: Any) -> None: ...
    def report_metric(self, *, name: str, value: float, **labels: Any) -> None: ...
    def flush(self) -> None: ...


class NoopTraceBackend:
    """Default backend: records nothing. Guarantees observability faults do not
    drag the core path (degradation target per architect-observability noop rule)."""

    def report_span(self, *, trace_id: str, name: str, **fields: Any) -> None:
        return None

    def report_metric(self, *, name: str, value: float, **labels: Any) -> None:
        return None

    def flush(self) -> None:
        return None


class ConsoleTraceBackend:
    """Local-dev backend: writes one line per span/metric to a stream (stderr by
    default). Verifies trace_id propagation in a single run without a real backend."""

    def __init__(self, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def report_span(self, *, trace_id: str, name: str, **fields: Any) -> None:
        rest = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"[trace] {datetime.now().isoformat()} trace_id={trace_id} span={name}"
        if rest:
            line += f" {rest}"
        print(line, file=self._stream)

    def report_metric(self, *, name: str, value: float, **labels: Any) -> None:
        rest = " ".join(f"{k}={v}" for k, v in labels.items())
        line = f"[metric] {datetime.now().isoformat()} {name}={value}"
        if rest:
            line += f" {rest}"
        print(line, file=self._stream)

    def flush(self) -> None:
        try:
            self._stream.flush()
        except Exception:
            pass


_BACKENDS = {
    "noop": NoopTraceBackend,
    "none": NoopTraceBackend,
    "console": ConsoleTraceBackend,
}

_NOOP = NoopTraceBackend()


def create_backend(backend_type: str | None = None, **config: Any) -> TraceBackend:
    """Factory: assemble a backend by type. Never raises: missing / unknown / failing
    types degrade to NoopTraceBackend (architect-observability noop-fallback rule).

    Observability must never break the core path.
    """
    if not backend_type:
        return _NOOP
    key = str(backend_type).strip().lower()
    cls = _BACKENDS.get(key)
    if cls is None:
        return _NOOP
    try:
        return cls(**config)
    except Exception:
        return _NOOP

# === M1-2a: OTel / OpenInference semantic-convention span model scaffold (additive) ===
# Fills ⑩-9 gap: report_span(**fields) had no SpanKind / OpenInference / llm.*
# semantic conventions. This scaffold introduces a structured span model with OTel
# GenAI / OpenInference attribute names so future hot-path callers (M1-2b) emit
# conventioned spans. Additive + noop-default: no existing behavior changes; backends
# still consume report_span(*, trace_id, name, **fields) unchanged; SpanRecord only
# structures the fields before they enter that contract.
# Backed by ⑩ sources: codex rust-otel ToolDecisionSource/TelemetryAuthMode + W3C
# trace_context, adk/autogen/librechat/deer-flow/eino/coze-loop OTel span conventions.

class SpanKind(enum.Enum):
    """OTel standard span kinds (interop with W3C trace-context)."""

    INTERNAL = "internal"
    CLIENT = "client"
    SERVER = "server"
    CONSUMER = "consumer"
    PRODUCER = "producer"


# OpenInference / OTel GenAI semantic-convention attribute names (gen_ai.*).
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_USAGE_PROMPT_TOKENS = "gen_ai.usage.prompt_tokens"
GEN_AI_USAGE_COMPLETION_TOKENS = "gen_ai.usage.completion_tokens"
GEN_AI_USAGE_TOTAL_TOKENS = "gen_ai.usage.total_tokens"

# OpenInference llm.* legacy attribute names (cross-source interop).
LLM_SYSTEM = "llm.system"
LLM_MODEL_NAME = "llm.model_name"
LLM_PROMPT = "llm.input_messages"
LLM_COMPLETION = "llm.output_messages"
LLM_TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
LLM_TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
LLM_TOKEN_COUNT_TOTAL = "llm.token_count.total"

SEMANTIC_CONVENTION_ATTRS = frozenset({
    GEN_AI_SYSTEM,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_OPERATION_NAME,
    GEN_AI_USAGE_PROMPT_TOKENS,
    GEN_AI_USAGE_COMPLETION_TOKENS,
    GEN_AI_USAGE_TOTAL_TOKENS,
    LLM_SYSTEM,
    LLM_MODEL_NAME,
    LLM_PROMPT,
    LLM_COMPLETION,
    LLM_TOKEN_COUNT_PROMPT,
    LLM_TOKEN_COUNT_COMPLETION,
    LLM_TOKEN_COUNT_TOTAL,
})


@dataclass
class SpanRecord:
    """Structured span model (M1-2a scaffold).

    Additive: flatten to the existing report_span(*, trace_id, name, **fields)
    contract via as_fields(); noop backends consume it without raising. Does not
    change existing behavior (M1-2b wires the hot path).
    """

    name: str
    trace_id: str
    kind: SpanKind = SpanKind.INTERNAL
    attributes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SpanKind):
            try:
                self.kind = SpanKind(self.kind)
            except ValueError:
                self.kind = SpanKind.INTERNAL

    def as_fields(self) -> dict:
        """Flatten into the report_span(**fields) contract (preserves it)."""
        out: dict = dict(self.attributes)
        out["kind"] = self.kind.value
        return out


def build_span(
    *,
    name: str,
    trace_id: str,
    kind: SpanKind | str = SpanKind.INTERNAL,
    **attributes: Any,
) -> SpanRecord:
    """Build a conventioned SpanRecord.

    Fault-tolerant (M1-1 noop-fallback discipline): bad string kinds downgrade to
    INTERNAL instead of raising. Attributes are stored verbatim; semantic-convention
    keys are intentionally NOT validated here (scaffold, not gate) — callers decide
    which OpenInference / gen_ai.* keys to attach.
    """
    return SpanRecord(name=name, trace_id=trace_id, kind=kind, attributes=attributes)



# === CTX-07: Token usage monitoring (wired into context_compactor.run_pipeline) ===
# 80% threshold alert: when current_tokens >= threshold * 0.8, emit a metric.

TOKEN_ALERT_THRESHOLD_RATIO: float = 0.80

_token_alert_emitted: dict[str, bool] = {}  # per-run_id dedup on alerts


def report_token_usage(
    *,
    current_tokens: int,
    threshold: int,
    run_id: str = "",
    backend=None,  # TraceBackend | None
    round_num: int = 0,
) -> bool:
    """Report token usage to telemetry backend, return True if alert threshold crossed.

    Alert logic:
    - 80% of threshold -> WARN metric
    - 100% of threshold -> CRITICAL metric
    - Alerts are deduplicated per run_id (only first crossing emits).

    Returns:
        True if an alert was emitted (caller may want to trigger early compaction).
    """
    if backend is None:
        # Try the module-level default backend
        backend = create_backend(_TELEMETRY_BACKEND_TYPE) if '_TELEMETRY_BACKEND_TYPE' in dir() else _NOOP

    if threshold <= 0:
        return False

    ratio = current_tokens / threshold
    alert_key = f"{run_id}:token_alert"
    did_alert = False

    # 80% threshold alert (WARN)
    if ratio >= TOKEN_ALERT_THRESHOLD_RATIO and not _token_alert_emitted.get(alert_key, False):
        _token_alert_emitted[alert_key] = True
        backend.report_metric(
            name="context.token_usage_warn",
            value=ratio * 100,
            run_id=run_id,
            current_tokens=current_tokens,
            threshold=threshold,
            round_num=round_num,
        )
        did_alert = True

    # 100% threshold alert (CRITICAL)
    if ratio >= 1.0:
        backend.report_metric(
            name="context.token_usage_critical",
            value=ratio * 100,
            run_id=run_id,
            current_tokens=current_tokens,
            threshold=threshold,
            round_num=round_num,
        )
        did_alert = True

    # Always report current usage as a gauge
    backend.report_metric(
        name="context.token_usage_current",
        value=current_tokens,
        run_id=run_id,
        round_num=round_num,
    )

    return did_alert


def reset_token_alerts(run_id: str = "") -> None:
    """Reset alert state for a new run."""
    if run_id:
        _token_alert_emitted.pop(f"{run_id}:token_alert", None)
    else:
        _token_alert_emitted.clear()