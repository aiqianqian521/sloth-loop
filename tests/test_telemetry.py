"""Telemetry backend factory + noop fallback (M1-1, observability dimension 10).

Covers the architect-observability checklist item: a pluggable factory that degrades
to NoopTraceBackend when a backend is missing/unknown/failing, never raising into the
core path.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from telemetry import (  # noqa: E402
    ConsoleTraceBackend,
    NoopTraceBackend,
    TraceBackend,
    create_backend,
)


def test_factory_default_is_noop():
    b = create_backend()
    assert isinstance(b, NoopTraceBackend)


def test_factory_missing_or_unknown_degrades_to_noop():
    assert isinstance(create_backend(None), NoopTraceBackend)
    assert isinstance(create_backend(""), NoopTraceBackend)
    assert isinstance(create_backend("does-not-exist"), NoopTraceBackend)


def test_factory_console_type():
    assert isinstance(create_backend("console"), ConsoleTraceBackend)


def test_factory_console_case_insensitive():
    assert isinstance(create_backend("CONSOLE"), ConsoleTraceBackend)


def test_factory_failing_constructor_degrades_to_noop():
    # ConsoleTraceBackend does not accept arbitrary kwargs -> ctor fails -> noop fallback
    b = create_backend("console", unexpected_kw=1)
    assert isinstance(b, NoopTraceBackend)


def test_noop_never_raises():
    b = NoopTraceBackend()
    b.report_span(trace_id="t1", name="s", extra="x")
    b.report_metric(name="m", value=1.5, label="k")
    b.flush()  # must not raise


def test_console_emits_trace_id_and_metric():
    buf = io.StringIO()
    b = ConsoleTraceBackend(stream=buf)
    b.report_span(trace_id="abc", name="step", k="v")
    b.report_metric(name="latency_ms", value=12.5)
    b.flush()
    out = buf.getvalue()
    assert "trace_id=abc" in out
    assert "span=step" in out
    assert "k=v" in out
    assert "latency_ms=12.5" in out


def test_backends_satisfy_protocol():
    assert isinstance(NoopTraceBackend(), TraceBackend)
    assert isinstance(ConsoleTraceBackend(), TraceBackend)
    assert isinstance(create_backend(), TraceBackend)
