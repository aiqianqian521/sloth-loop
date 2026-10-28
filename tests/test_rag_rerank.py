# -*- coding: utf-8 -*-
"""L3 cycle-5 A4 - bounded multiplicative rerank (adopted candidate C1).

Provenance (distilled from vectorize-io/hindsight, engine/search/reranking.py):
  :56-78   compute_recency_decay  (age days -> [0,1] freshness, neutral 0.5,
                                     future-dated clamped to 1.0)
  :193-198 combined_score = CE_normalized * recency_boost * temporal_boost *
             proof_count_boost ; each boost = 1 + alpha*(signal - 0.5),
             bounded in [1-alpha/2, 1+alpha/2]
  :300-304 the entity actually stores the combined score

Contract under test: the rerank factors are (a) multiplicative, (b) bounded,
(c) deterministic, and (d) an identity when alpha==0 (so the legacy recall
order is preserved bit-for-bit: alphas default 0.0).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import rag_layers as rl  # noqa: E402


# ---------------------------------------------------------------------------
# 1. recency decay: monotone, bounded, neutral, future clamp
# ---------------------------------------------------------------------------
def test_recency_decay_neutral_mode_is_half():
    assert rl.recency_decay(123.0, mode="none") == 0.5


def test_recency_decay_fresh_is_one_and_monotone_decreasing():
    assert rl.recency_decay(0.0) == 1.0
    d1 = rl.recency_decay(10.0)
    d2 = rl.recency_decay(100.0)
    assert 0.0 <= d2 < d1 <= 1.0


def test_recency_decay_future_dated_clamped_to_one():
    assert rl.recency_decay(-5.0) == 1.0
    assert rl.recency_decay(-5.0, mode="linear") == 1.0


def test_recency_decay_linear_has_floor():
    assert rl.recency_decay(1e9, mode="linear", halflife_days=30.0) >= 0.1


def test_recency_boost_bounded():
    a = 0.2
    lo, hi = 1.0 - a / 2.0, 1.0 + a / 2.0
    for age in (-1, 0, 1, 30, 365, 100000):
        b = rl.recency_boost(age, alpha=a)
        assert lo - 1e-9 <= b <= hi + 1e-9, (age, b)
    # fresh -> upper bound, very old -> lower bound
    assert rl.recency_boost(0.0, alpha=a) == pytest.approx(hi)
    assert rl.recency_boost(1e9, alpha=a) == pytest.approx(lo, abs=1e-6)


# ---------------------------------------------------------------------------
# 2. proof-count boost: bounded, saturating
# ---------------------------------------------------------------------------
def test_proof_count_boost_bounded_and_saturates():
    a = 0.2
    assert rl.proof_count_boost(0, alpha=a) == pytest.approx(1.0 - a / 2.0)
    assert rl.proof_count_boost(5, alpha=a) == pytest.approx(1.0 + a / 2.0)
    # saturates: beyond saturate_at no further growth
    assert rl.proof_count_boost(50, alpha=a) == rl.proof_count_boost(5, alpha=a)


def test_proof_count_boost_monotone_until_saturation():
    # saturate_at=5 => count 0..5 are distinct/non-decreasing, count>=5 saturates.
    vals = [rl.proof_count_boost(c, alpha=0.4, saturate_at=5) for c in range(0, 8)]
    assert vals[0] < vals[1] < vals[2] < vals[3] < vals[4] < vals[5]
    assert vals[5] == vals[6] == vals[7]


# ---------------------------------------------------------------------------
# 3. combined_score: multiplicative + identity at alpha 0
# ---------------------------------------------------------------------------
def test_combined_score_identity_when_alphas_zero():
    assert rl.combined_score(0.7) == 0.7
    assert rl.combined_score(0.7, age_days=3.0, proof_count=4) == 0.7


def test_combined_score_is_multiplicative():
    base = 0.8
    rb = rl.recency_boost(10.0, alpha=0.2)
    pb = rl.proof_count_boost(3, alpha=0.2)
    got = rl.combined_score(base, age_days=10.0, proof_count=3,
                            recency_alpha=0.2, proof_alpha=0.2)
    assert got == pytest.approx(base * rb * pb)


def test_combined_score_deterministic():
    args = dict(base=0.5, age_days=7.0, proof_count=2,
                recency_alpha=0.3, proof_alpha=0.3)
    a = rl.combined_score(**args)
    b = rl.combined_score(**args)
    assert a == b


# ---------------------------------------------------------------------------
# 4. LayeredMemory.search() integration
# ---------------------------------------------------------------------------
def _mem_with_ages():
    mem = rl.LayeredMemory()
    mem.add(rl.MemoryUnit(id="old", text="BTC breakout volume 84000",
                          layer="raw", timestamp="2020-01-01"))
    mem.add(rl.MemoryUnit(id="new", text="BTC breakout volume 84000",
                          layer="raw", timestamp="2026-10-17"))
    return mem


def test_search_alpha_zero_preserves_legacy_order():
    mem = _mem_with_ages()
    # equal text -> equal sim -> legacy tie broken by id ascending
    res = mem.search("BTC breakout volume 84000", top_k=2)
    assert [r["id"] for r in res] == ["new", "old"]  # id asc: 'new' < 'old'


def test_search_recency_alpha_promotes_fresh_unit():
    mem = _mem_with_ages()
    now = rl._ts("2026-10-18")
    res = mem.search("BTC breakout volume 84000", top_k=2,
                     recency_alpha=0.5, now_ts=now)
    assert res[0]["id"] == "new", "fresher unit must outrank the 2020 one"


def test_search_recency_identity_matches_legacy_when_disabled():
    mem = _mem_with_ages()
    now = rl._ts("2026-10-18")
    a = mem.search("BTC breakout volume 84000", top_k=2, now_ts=now)
    b = mem.search("BTC breakout volume 84000", top_k=2,
                   recency_alpha=0.0, proof_alpha=0.0, now_ts=now)
    assert [r["id"] for r in a] == [r["id"] for r in b]


def test_search_proof_alpha_promotes_corroborated_unit():
    mem = rl.LayeredMemory()
    mem.add(rl.MemoryUnit(id="solo", text="BTC breakout volume 84000",
                          layer="raw", source_ids=["a"]))
    mem.add(rl.MemoryUnit(id="many", text="BTC breakout volume 84000",
                          layer="raw", source_ids=["a", "b", "c", "d", "e"]))
    res = mem.search("BTC breakout volume 84000", top_k=2, proof_alpha=0.5)
    assert res[0]["id"] == "many", "better-corroborated unit must outrank"


def test_search_rerank_is_deterministic():
    mem = _mem_with_ages()
    now = rl._ts("2026-10-18")
    a = mem.search("BTC breakout volume 84000", top_k=2,
                   recency_alpha=0.4, now_ts=now)
    b = mem.search("BTC breakout volume 84000", top_k=2,
                   recency_alpha=0.4, now_ts=now)
    assert a == b


# ---------------------------------------------------------------------------
# 5. contract invariants + config default
# ---------------------------------------------------------------------------
def test_rag_rerank_module_has_no_io_no_network():
    src = (ENGINE / "rag_layers.py").read_text(encoding="utf-8")
    for token in ("import requests", "import socket", "urllib.request"):
        assert token not in src, f"rag_layers must stay offline, found {token!r}"


def test_config_default_rerank_alphas_are_identity():
    from config_util import DEFAULT_CONFIG
    loop = DEFAULT_CONFIG["loop"]
    assert loop["rerank_recency_alpha"] == 0.0
    assert loop["rerank_proof_alpha"] == 0.0
    yml = (ENGINE / "config.yaml").read_text(encoding="utf-8")
    assert "rerank_recency_alpha: 0.0" in yml


def test_search_signature_exposes_rerank_knobs():
    import inspect
    params = inspect.signature(rl.LayeredMemory.search).parameters
    for name in ("recency_alpha", "proof_alpha", "halflife_days",
                 "recency_mode", "now_ts"):
        assert name in params, f"search() must expose {name!r}"
        assert params[name].default is not inspect.Parameter.empty
