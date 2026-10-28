"""测试 MentalModels 规则版 — P1-1。"""

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from mental_model import (
    MentalModel, MentalModelEngine,
    create_default_templates,
)


# ── 模板注册 ──

def test_register_template():
    """注册模板 → 查询。"""
    engine = MentalModelEngine()
    engine.register_template("T1", "What is the best X for {Y}?", "strategy")
    assert engine.template_count == 1
    assert "T1" in engine.templates


# ── 计算（无数据） ──

def test_compute_no_store():
    """无 PatternStore → 返回 None。"""
    engine = MentalModelEngine()
    engine.register_template("T1", "Best param?", "strategy")
    result = engine.compute("T1")
    assert result is None


# ── 自定义提取器 ──

def test_compute_with_extractor():
    """自定义提取器 → 返回 MentalModel。"""
    def my_extractor(store, params):
        return {
            "values": [("EMA20", 15), ("EMA10", 8), ("EMA50", 3)],
            "source_rules": ["r1", "r2"],
        }

    engine = MentalModelEngine()
    engine.register_template("bestMA", "Best MA for {market}?", "strategy",
                             extractor=my_extractor)
    result = engine.compute("bestMA", {"market": "H240Trend"})
    assert result is not None
    assert result.best_value == "EMA20"
    assert result.confidence > 0.5
    assert result.evidence_count == 26  # 15+8+3
    assert len(result.alternatives) == 3
    assert result.alternatives[0]["value"] == "EMA20"


# ── 缓存 ──

def test_cache():
    """相同参数 → 返回缓存。"""
    call_count = [0]

    def counting_extractor(store, params):
        call_count[0] += 1
        return {"values": [("A", 10)]}

    engine = MentalModelEngine()
    engine.register_template("T", "test", "strategy", extractor=counting_extractor)

    # 第一次计算
    r1 = engine.compute("T")
    assert r1 is not None
    assert call_count[0] == 1

    # 第二次 → 缓存
    r2 = engine.compute("T")
    assert r2 is not None
    assert call_count[0] == 1  # 未再次调用

    assert engine.cache_size == 1


# ── 不同参数 → 不同缓存 ──

def test_different_params_different_cache():
    """不同参数 → 不同缓存条目。"""
    def ext(store, params):
        market = params.get("market", "default")
        vals = {"BTC": [("BTC_best", 10)], "ETH": [("ETH_best", 8)]}
        return {"values": vals.get(market, [("default", 1)])}

    engine = MentalModelEngine()
    engine.register_template("T", "best for {market}?", "strategy", extractor=ext)

    r_btc = engine.compute("T", {"market": "BTC"})
    r_eth = engine.compute("T", {"market": "ETH"})
    assert r_btc.best_value == "BTC_best"
    assert r_eth.best_value == "ETH_best"
    assert engine.cache_size == 2


# ── clear_cache ──

def test_clear_cache():
    """清空缓存。"""
    engine = MentalModelEngine()
    engine.register_template("T", "test", "strategy",
                             extractor=lambda s, p: {"values": [("x", 1)]})
    engine.compute("T")
    assert engine.cache_size == 1
    engine.clear_cache()
    assert engine.cache_size == 0


# ── compute_all ──

def test_compute_all():
    """计算所有模板。"""
    def ext(store, params):
        return {"values": [(params.get("id", "default"), 5)]}

    engine = MentalModelEngine()
    engine.register_template("A", "qA", "strategy", extractor=ext)
    engine.register_template("B", "qB", "risk", extractor=ext)
    engine.register_template("C", "qC", "filter", extractor=ext)

    results = engine.compute_all(params={"id": "test"})
    assert len(results) == 3


# ── 默认模板工厂 ──

def test_create_default_templates():
    """预置模板注册。"""
    engine = MentalModelEngine()
    create_default_templates(engine)
    assert engine.template_count == 5
    assert "best_fast_ma_period" in engine.templates
    assert "best_stop_loss_pct" in engine.templates
    assert "best_filter_rule" in engine.templates
    assert "best_take_profit_method" in engine.templates
    assert "most_effective_correction" in engine.templates


# ── MentalModel.to_dict ──

def test_mental_model_to_dict():
    """序列化。"""
    m = MentalModel(
        id="test",
        question_template="best X?",
        category="strategy",
        best_value=42,
        confidence=0.85,
        evidence_count=100,
        alternatives=[{"value": 20, "score": 0.1, "count": 10}],
    )
    d = m.to_dict()
    assert d["id"] == "test"
    assert d["best_value"] == 42
    assert d["confidence"] == 0.85


# ── engine.to_dict / summary ──

def test_engine_to_dict():
    """引擎序列化。"""
    engine = MentalModelEngine()
    engine.register_template("T", "q", "strategy",
                             extractor=lambda s, p: {"values": [("x", 1)]})
    engine.compute("T")
    d = engine.to_dict()
    assert d["cache_size"] == 1
    assert len(d["models"]) == 1


def test_summary():
    """人类可读摘要。"""
    engine = MentalModelEngine()
    engine.register_template("T", "q", "strategy",
                             extractor=lambda s, p: {"values": [("EMA20", 10)]})
    engine.compute("T")
    s = engine.summary()
    assert "MentalModelEngine" in s
    assert "EMA20" in s


# ── 空引擎 ──

def test_empty_engine():
    """空引擎的各种操作不报错。"""
    engine = MentalModelEngine()
    assert engine.template_count == 0
    assert engine.cache_size == 0
    assert engine.compute("nonexistent") is None
    assert engine.compute_all() == []
    assert "no cached models" in engine.summary()
