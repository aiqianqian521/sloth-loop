# -*- coding: utf-8 -*-
"""L3 cycle-9 A4 - dual-window quota snapshot (lobehub-canary distillation).

Provenance (distilled from lobehub-canary desktop app):
  apps/desktop/src/main/modules/heterogeneousAgent/codexQuota.ts:18-20
    5h primary / 7d secondary windows + RESET_CONSUME_TIMEOUT_MS = 30_000
  .../codexQuota.ts:115-122   errorSnapshot() instead of throwing
  .../codexQuota.ts:348-364   usedPercent clamped, duration fallback
  .../codexQuota.ts:372-374   both windows unusable -> null
  .../codexQuota.ts:596-600   outer try/catch -> error snapshot
  .../codexQuota.ts:613-641   mandatory idempotency key, rejected when blank,
                              reused across the RPC -> HTTP fallback, own timeout

Contract under test (behavioural, not source-grep):
  1. used_percent clamped to [0,100]; unusable value drops the window.
  2. resets_at normalises s vs ms and accepts ISO-8601.
  3. both windows unusable -> from_raw() is None (never a fake 0%).
  4. resolve_snapshot() never raises: cache or error snapshot.
  5. exhausted / next_reset_at derive from the windows.
  6. CreditLedger: blank key rejected; same key -> one call; timeout -> not cached.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from quota_window import (  # noqa: E402
    PRIMARY_WINDOW_MINUTES,
    SECONDARY_WINDOW_MINUTES,
    ConsumeOutcome,
    CreditLedger,
    QuotaSnapshot,
    QuotaWindow,
    error_snapshot,
    from_raw,
    map_window,
    resolve_snapshot,
)


def test_window_labels_and_nominal_durations():
    snapshot = from_raw("codex", {"primary": {"usedPercent": 10},
                                  "secondary": {"usedPercent": 20}})
    assert snapshot is not None
    assert snapshot.status == "ok"
    primary = snapshot.window("primary")
    secondary = snapshot.window("secondary")
    assert primary.duration_minutes == PRIMARY_WINDOW_MINUTES == 300
    assert secondary.duration_minutes == SECONDARY_WINDOW_MINUTES == 10080


def test_used_percent_is_clamped_into_range():
    high = map_window({"usedPercent": 140}, label="primary",
                      default_duration_minutes=300)
    low = map_window({"usedPercent": -3}, label="primary",
                     default_duration_minutes=300)
    assert high.used_percent == 100.0
    assert high.exhausted is True
    assert low.used_percent == 0.0
    assert low.remaining_percent == 100.0


def test_unusable_percentage_drops_the_window():
    for bad in ({}, {"usedPercent": "90"}, {"usedPercent": True},
                {"usedPercent": float("nan")}, {"usedPercent": float("inf")},
                None, "nope"):
        assert map_window(bad, label="primary", default_duration_minutes=300) is None


def test_explicit_duration_overrides_nominal_one():
    window = map_window({"usedPercent": 1, "windowDurationMins": 90.7},
                        label="primary", default_duration_minutes=300)
    assert window.duration_minutes == 90  # floored
    zero = map_window({"usedPercent": 1, "windowDurationMins": 0},
                      label="primary", default_duration_minutes=300)
    assert zero.duration_minutes == 300   # invalid -> nominal fallback


def test_resets_at_normalises_seconds_and_accepts_iso():
    seconds = map_window({"usedPercent": 1, "resetsAt": 1_700_000_000},
                         label="primary", default_duration_minutes=300)
    millis = map_window({"usedPercent": 1, "resetsAt": 1_700_000_000_000},
                        label="primary", default_duration_minutes=300)
    iso = map_window({"usedPercent": 1, "resetsAt": "2023-11-14T22:13:20Z"},
                     label="primary", default_duration_minutes=300)

    assert seconds.resets_at == 1_700_000_000_000
    assert millis.resets_at == 1_700_000_000_000
    assert iso.resets_at == 1_700_000_000_000
    assert map_window({"usedPercent": 1, "resetsAt": "not-a-date"},
                      label="primary", default_duration_minutes=300).resets_at is None


def test_from_raw_requires_at_least_one_usable_window():
    assert from_raw("codex", {"primary": {}, "secondary": {}}) is None
    assert from_raw("codex", {"primary": {"usedPercent": 5}}) is not None
    assert from_raw("codex", "not-a-dict") is None
    one = from_raw("codex", {"primary": {"usedPercent": 5}})
    assert [w.label for w in one.windows] == ["primary"]


def test_error_snapshot_shape_is_stable():
    snap = error_snapshot("codex", "boom", now=123)
    assert (snap.provider, snap.status, snap.updated_at) == ("codex", "error", 123)
    assert snap.error == "boom"
    assert snap.windows == ()
    assert snap.exhausted is False
    assert snap.next_reset_at() is None


def test_resolve_snapshot_degrades_without_raising():
    def raising():
        raise RuntimeError("rpc down")

    snap = resolve_snapshot(raising, provider="codex", now=7)
    assert snap.status == "error"
    assert snap.degraded is True
    assert "RuntimeError" in (snap.error or "")
    assert snap.updated_at == 7

    cached = from_raw("codex", {"primary": {"usedPercent": 42}})
    degraded = resolve_snapshot(raising, provider="codex", cache=cached)
    assert degraded.windows == cached.windows
    assert degraded.degraded is True
    assert "rpc down" in (degraded.error or "")

    empty = resolve_snapshot(lambda: None, provider="codex", cache=cached)
    assert empty.windows == cached.windows and empty.degraded is True


def test_resolve_snapshot_passes_through_good_payloads():
    snap = resolve_snapshot(lambda: {"primary": {"usedPercent": 5}},
                            provider="codex", now=11)
    assert snap.status == "ok" and snap.updated_at == 11

    passthrough = QuotaSnapshot(provider="codex", status="ok", updated_at=1)
    assert resolve_snapshot(lambda: passthrough, provider="codex") is passthrough


def test_exhausted_and_next_reset_use_the_exhausted_window():
    snapshot = from_raw("codex", {
        "primary": {"usedPercent": 100, "resetsAt": 2_000},
        "secondary": {"usedPercent": 30, "resetsAt": 9_999},
    })
    assert snapshot.exhausted is True
    assert snapshot.next_reset_at() == 2_000_000  # only exhausted windows count

    healthy = from_raw("codex", {
        "primary": {"usedPercent": 30, "resetsAt": 2_000},
        "secondary": {"usedPercent": 90, "resetsAt": 9_999},
    })
    assert healthy.exhausted is False
    assert healthy.next_reset_at() is None


def test_credit_ledger_requires_a_real_idempotency_key():
    ledger = CreditLedger()
    for bad in ("", "   ", None, 7):
        with pytest.raises(ValueError):
            ledger.consume(bad, lambda key: "reset")


def test_credit_ledger_is_idempotent_per_key():
    calls = []

    def consume(key):
        calls.append(key)
        return "reset"

    ledger = CreditLedger()
    first = ledger.consume("run-1-credit-a", consume)
    second = ledger.consume("run-1-credit-a", consume)

    assert calls == ["run-1-credit-a"]
    assert (first.status, first.cached) == ("consumed", False)
    assert (second.status, second.cached) == ("consumed", True)
    assert second.outcome == "reset"
    assert ledger.known("run-1-credit-a") is True


def test_credit_ledger_surfaces_errors_without_caching_them():
    calls = []

    def flaky(key):
        calls.append(key)
        if len(calls) == 1:
            raise RuntimeError("backend 500")
        return "nothingToReset"

    ledger = CreditLedger()
    failed = ledger.consume("k", flaky)
    assert failed.status == "error" and failed.cached is False
    assert "RuntimeError" in (failed.detail or "")
    assert ledger.known("k") is False

    retried = ledger.consume("k", flaky)
    assert retried.status == "consumed" and retried.outcome == "nothingToReset"
    assert len(calls) == 2


def test_credit_ledger_timeout_leaves_the_key_reusable():
    calls = []

    def hang(key):
        calls.append(key)
        time.sleep(0.5)
        return "reset"

    ledger = CreditLedger(timeout_ms=50)
    started = time.monotonic()
    outcome = ledger.consume("slow-key", hang)
    elapsed = time.monotonic() - started

    assert outcome.status == "timeout"
    assert elapsed < 0.4
    assert ledger.known("slow-key") is False   # unknown outcome -> key stays durable

    ledger.timeout_ms = 5000
    ok = ledger.consume("slow-key", hang)
    assert ok.status == "consumed" and calls == ["slow-key", "slow-key"]


def test_credit_ledger_rejects_a_bad_timeout():
    with pytest.raises(ValueError):
        CreditLedger(timeout_ms=-5)
    assert ConsumeOutcome(key="k", status="consumed").ok is True
    assert QuotaWindow(label="primary", duration_minutes=300,
                       used_percent=100).exhausted is True