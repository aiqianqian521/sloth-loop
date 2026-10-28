"""测试 BM25 多路检索 — P1-N4。

验证：BM25索引/检索、RRF融合、check_exclusion_v2增强。
"""

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from bm25_retrieval import (
    BM25Index, BM25Doc,
    reciprocal_rank_fusion, RRF_K,
    build_pattern_index, check_exclusion_v2, _build_query_from_signal,
)


# ── BM25 索引基础 ──

def test_bm25_add_and_search():
    """添加文档 → 检索 → 返回相关文档。"""
    idx = BM25Index()
    idx.add(BM25Doc(id="d1", text="python pytest coverage test"))
    idx.add(BM25Doc(id="d2", text="javascript jest unit test npm"))
    idx.add(BM25Doc(id="d3", text="python backtest ooda loop signal"))

    results = idx.search("python test", top_k=3)
    assert len(results) > 0
    # d1 最相关 (python + test)
    assert results[0][0].id == "d1"


def test_bm25_empty_index():
    """空索引检索返回空。"""
    idx = BM25Index()
    results = idx.search("anything")
    assert results == []


def test_bm25_no_match():
    """查询词不在索引中 → 返回空。"""
    idx = BM25Index()
    idx.add(BM25Doc(id="d1", text="python test"))
    results = idx.search("xyzabc")
    assert results == []


def test_bm25_batch_add():
    """批量添加。"""
    idx = BM25Index()
    idx.add_batch([
        BM25Doc(id="a", text="alpha"),
        BM25Doc(id="b", text="beta"),
    ])
    assert idx.doc_count == 2
    results = idx.search("alpha")
    assert len(results) == 1
    assert results[0][0].id == "a"


def test_bm25_doc_count():
    """doc_count 正确。"""
    idx = BM25Index()
    assert idx.doc_count == 0
    idx.add(BM25Doc(id="1", text="test"))
    assert idx.doc_count == 1


# ── RRF 融合 ──

def test_rrf_fusion_basic():
    """两路结果 → RRF 融合排序。"""
    r1 = [("a", 0.9), ("b", 0.8)]
    r2 = [("c", 0.7), ("a", 0.3)]
    fused = reciprocal_rank_fusion([r1, r2], k=60, top_k=3)
    assert len(fused) >= 1
    # a 出现两次 → rank 最高
    assert fused[0][0] == "a"


def test_rrf_fusion_single_list():
    """只有一路结果 → RRF 仍工作。"""
    r1 = [("x", 1.0)]
    fused = reciprocal_rank_fusion([r1], k=60, top_k=3)
    assert fused[0][0] == "x"


def test_rrf_fusion_empty():
    """空结果 → 返回空。"""
    fused = reciprocal_rank_fusion([], k=60, top_k=3)
    assert fused == []


# ── check_exclusion_v2 ──

def test_check_exclusion_v2_exact_only():
    """无 BM25 索引 → 降级为精确匹配。"""
    def fake_check(signals):
        return {
            "input_count": len(signals),
            "excluded_count": 0,
            "passed_count": len(signals),
            "passed": signals,
            "excluded": [],
            "summary": f"in={len(signals)} excl=0 pass={len(signals)}",
            "rules_active": 0,
            "rules_hit": 0,
        }

    signals = [{"signal_pattern": "ExtremeChase", "market_condition": "H240Trend"}]
    result = check_exclusion_v2(fake_check, signals, bm25_index=None)
    assert result["fusion"] == "exact_only"
    assert result["passed_count"] == 1


def test_check_exclusion_v2_with_bm25():
    """有 BM25 索引 → RRF 融合。"""
    def fake_check(signals):
        return {
            "input_count": len(signals),
            "excluded_count": 1,
            "passed_count": 0,
            "passed": [],
            "excluded": [
                {"blocked_by": "rule_001", "signal": signals[0],
                 "failure_mode": "extreme_chase", "rule": "ExtremeChase @ H240Trend"},
            ],
            "summary": "in=1 excl=1 pass=0",
            "rules_active": 1,
            "rules_hit": 1,
        }

    idx = BM25Index()
    idx.add(BM25Doc(id="rule_001", text="ExtremeChase H240Trend extreme chase pattern"))

    signals = [{"signal_pattern": "ExtremeChase", "market_condition": "H240Trend",
                 "failure_mode": "extreme_chase"}]
    result = check_exclusion_v2(fake_check, signals, bm25_index=idx)
    assert result["fusion"] == "rrf"
    assert result["bm25_hits"] >= 0


# ── build_pattern_index ──

def test_build_pattern_index():
    """从模式列表构建 BM25 索引。"""
    patterns = [
        {"id": "r1", "pattern": "ExtremeChase", "failure_mode": "chase",
         "description": "Chase extreme price", "signal_pattern": "ExtremeChase"},
        {"id": "r2", "pattern": "FalseBreakout", "failure_mode": "breakout",
         "description": "False breakout detection"},
    ]
    idx = build_pattern_index(patterns)
    assert idx.doc_count == 2
    results = idx.search("extreme chase")
    assert len(results) >= 1
    assert results[0][0].id == "r1"


# ── _build_query_from_signal ──

def test_build_query_from_signal():
    """信号 → 查询字符串。"""
    signal = {"signal_pattern": "ExtremeChase", "market_condition": "H240Trend",
              "failure_mode": "extreme_chase"}
    q = _build_query_from_signal(signal)
    assert "ExtremeChase" in q
    assert "H240Trend" in q
    assert "extreme_chase" in q


def test_build_query_empty_signal():
    """空信号 → 空查询。"""
    q = _build_query_from_signal({})
    assert q == ""
