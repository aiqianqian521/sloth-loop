"""RAG 分层记忆/图检索/MMR 单元测试 (Hindsight 阶段2/4 对标)。"""
from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = _ROOT / "sloth_engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import rag_layers as rl  # noqa: E402


# ── 实体提取 ──────────────────────────────────────────────

def test_entity_extraction_labels():
    ents = rl.extract_entities(
        "On 2026-09-25 BTC rose 3.5% to $84000 at 14:30 by Alice Smith (Acme Inc).")
    labels = {e["label"] for e in ents}
    assert {"DATE", "TICKER", "PERCENT", "MONEY", "TIME", "PERSON", "ORG"} <= labels


def test_entity_extraction_deterministic_and_dedup():
    txt = "BTC BTC 2026-09-25 2026-09-25"
    a = rl.extract_entities(txt)
    b = rl.extract_entities(txt)
    assert a == b
    assert len([e for e in a if e["label"] == "TICKER"]) == 1
    assert len([e for e in a if e["label"] == "DATE"]) == 1


def test_entity_empty_text():
    assert rl.extract_entities("") == []


# ── 分层记忆 + consolidation ───────────────────────────────

def test_consolidate_merges_similar_raw_into_observation():
    mem = rl.LayeredMemory()
    mem.add_many([
        rl.MemoryUnit(id="r1", text="BTC breakout above 84000 with volume"),
        rl.MemoryUnit(id="r2", text="BTC breakout above 84000 with volume surge"),
        rl.MemoryUnit(id="r3", text="ETH range-bound"),
    ])
    obs = mem.consolidate(threshold=0.85, min_group=2)
    assert len(obs) == 1
    assert sorted(obs[0].source_ids) == ["r1", "r2"]
    st = mem.stats()
    assert st["observations"] == 1 and st["covered_raw"] == 2


def test_prefer_observations_hides_covered_raw():
    mem = rl.LayeredMemory()
    mem.add_many([
        rl.MemoryUnit(id="r1", text="BTC breakout 84000 volume"),
        rl.MemoryUnit(id="r2", text="BTC breakout 84000 volume surge"),
    ])
    mem.consolidate(threshold=0.85, min_group=2)
    prefer = mem.search("BTC breakout 84000", top_k=5, prefer_observations=True)
    raw_hits = mem.search("BTC breakout 84000", top_k=5, prefer_observations=False)
    assert all(r["id"] != "r1" and r["id"] != "r2" for r in prefer)
    assert any(r["id"] == "r1" for r in raw_hits)


def test_layer_boost_ranks_mental_model_first():
    mem = rl.LayeredMemory()
    mem.add(rl.MemoryUnit(id="raw1", text="BTC breakout 84000 volume",
                          layer="raw"))
    mem.add(rl.MemoryUnit(id="mm1", text="BTC breakout 84000 volume",
                          layer="mental_model"))
    res = mem.search("BTC breakout 84000", top_k=2)
    assert res[0]["id"] == "mm1"


# ── 图检索: spreading activation ───────────────────────────

def test_auto_link_and_spreading_activation():
    g = rl.MemoryGraph()
    for uid, txt in [("n1", "BTC breakout"), ("n2", "BTC breakout volume"),
                     ("n3", "ETH range"), ("n4", "weather sunny")]:
        g.add_node(rl.MemoryUnit(id=uid, text=txt))
    g.auto_link(threshold=0.5)
    assert len(g.edges) >= 1
    act = g.spreading_activation(["n1"], max_hops=2, decay=0.6, threshold=0.01)
    ids = [a["id"] for a in act]
    assert ids[0] == "n1"                 # seed has max activation
    assert "n1" in ids


def test_graph_edge_type_validation():
    g = rl.MemoryGraph()
    g.add_node(rl.MemoryUnit(id="x", text="x"))
    g.add_node(rl.MemoryUnit(id="y", text="y"))
    g.add_edge("x", "y", "semantic", 1.0)
    try:
        g.add_edge("x", "y", "bogus", 1.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_spreading_activation_decays_with_distance():
    g = rl.MemoryGraph()
    for uid in ("a", "b", "c"):
        g.add_node(rl.MemoryUnit(id=uid, text=uid))
    g.add_edge("a", "b", "semantic", 1.0)
    g.add_edge("b", "c", "semantic", 1.0)
    act = {x["id"]: x["activation"] for x in
           g.spreading_activation(["a"], max_hops=3, decay=0.5, threshold=0.0)}
    assert act["a"] > act["b"] >= act["c"]


# ── MMR ───────────────────────────────────────────────────

def test_mmr_selects_diverse():
    cands = [{"id": "a", "text": "BTC breakout", "score": 1.0},
             {"id": "b", "text": "BTC breakout volume", "score": 0.98},
             {"id": "c", "text": "ETH range bound", "score": 0.6}]
    sel = rl.mmr_select(cands, top_k=2, lambda_param=0.5)
    ids = [c["id"] for c in sel]
    assert ids[0] == "a" and "c" in ids     # diverse pick over near-dup b


def test_mmr_lambda_one_is_pure_relevance():
    cands = [{"id": "a", "text": "x", "score": 1.0},
             {"id": "b", "text": "x", "score": 0.9},
             {"id": "c", "text": "x", "score": 0.1}]
    sel = rl.mmr_select(cands, top_k=2, lambda_param=1.0)
    assert [c["id"] for c in sel] == ["a", "b"]


def test_mmr_deterministic():
    cands = [{"id": "a", "text": "alpha", "score": 1.0},
             {"id": "b", "text": "beta", "score": 1.0},
             {"id": "c", "text": "gamma", "score": 1.0}]
    assert [c["id"] for c in rl.mmr_select(cands, 3, 0.7)] == \
           [c["id"] for c in rl.mmr_select(cands, 3, 0.7)]


# ── 统一 recall ────────────────────────────────────────────

def test_layered_recall_integrates_graph_and_mmr():
    mem = rl.LayeredMemory()
    mem.add_many([
        rl.MemoryUnit(id="r1", text="BTC breakout above 84000 with volume"),
        rl.MemoryUnit(id="r2", text="BTC breakout above 84000 with volume surge"),
        rl.MemoryUnit(id="r3", text="ETH range-bound 2600-2700"),
    ])
    mem.consolidate(threshold=0.85, min_group=2)
    g = rl.MemoryGraph()
    for u in mem.units.values():
        g.add_node(u)
    g.auto_link(threshold=0.5)
    res = rl.layered_recall(mem, g, "BTC breakout 84000", top_k=3)
    assert res and len(res) <= 3
    assert all("id" in r for r in res)
