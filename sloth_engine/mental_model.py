"""MentalModels 规则版 — P1-1: 从 PatternStore 统计最佳参数 → 预计算答案缓存。

对标 Hindsight mental_models + observations 模式:
  - 问题模板: 标准化的查询模板
  - 参数统计: 从 PatternStore 的成功/失败模式中提取统计量
  - 预计算缓存: 避免重复探索，答案预计算

设计:
  MentalModel = {
    question_template: "What is the best <param> for <scenario>?"
    parameters: ["MA快线周期", "止损比例", ...]
    best_value: 统计出的最佳值
    confidence: 置信度
    evidence_count: 支持样本数
  }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from typing import Any, Optional

try:
    import json
except ImportError:
    import json


# ============================================================================
# MentalModel 数据结构
# ============================================================================

@dataclass
class MentalModel:
    """一条心智模型：从模式统计中凝结的预计算知识。"""
    id: str
    question_template: str          # 问题模板, 如 "What is the best {param} for {scenario}?"
    category: str                   # 分类: strategy/risk/filter/exit
    best_value: Any = None          # 统计出的最佳值
    confidence: float = 0.0         # 置信度 [0, 1]
    evidence_count: int = 0         # 支持样本数
    alternatives: list[dict] = field(default_factory=list)  # [{value, score, count}]
    source_rules: list[str] = field(default_factory=list)   # 来源规则 id
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question_template": self.question_template,
            "category": self.category,
            "best_value": self.best_value,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "alternatives": self.alternatives,
            "source_rules": self.source_rules,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ============================================================================
# MentalModelEngine — 规则版引擎
# ============================================================================

class MentalModelEngine:
    """MentalModels 规则版引擎。

    从 PatternStore 的成功/失败模式中提取统计数据，生成预计算答案。

    使用方式:
        engine = MentalModelEngine(pattern_store)
        engine.register_template("MA快线最佳周期",
            "What is the best fast MA period for {market}?",
            "strategy")
        engine.compute("MA快线最佳周期", params={"market": "H240Trend"})
    """

    def __init__(self, pattern_store=None):
        self._store = pattern_store  # PatternStore 实例（可选）
        self._templates: dict[str, dict] = {}  # id → {template, category, extractor}
        self._cache: dict[str, MentalModel] = {}  # cache_key → result
        self._stats: dict[str, Any] = {}  # 预计算统计量

    # ── 模板注册 ───────────────────────────────

    def register_template(self, model_id: str, question_template: str,
                          category: str, extractor: callable = None) -> None:
        """注册心智模型模板。

        Args:
            model_id: 唯一标识
            question_template: 问题模板，可用 {param} 占位
            category: strategy/risk/filter/exit
            extractor: 从 PatternStore 提取统计量的函数 (store, params) → dict
        """
        self._templates[model_id] = {
            "template": question_template,
            "category": category,
            "extractor": extractor or self._default_extractor,
        }

    # ── 计算 ───────────────────────────────────

    def compute(self, model_id: str, params: dict | None = None) -> MentalModel | None:
        """计算心智模型答案。

        优先返回缓存；若无缓存则从 PatternStore 提取统计量。

        Args:
            model_id: 注册的模板 id
            params: 模板参数, 如 {"market": "H240Trend"}

        Returns:
            MentalModel 或 None（数据不足时）
        """
        if model_id not in self._templates:
            return None

        tmpl = self._templates[model_id]
        cache_key = f"{model_id}:{json.dumps(params or {}, sort_keys=True)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 调用提取器
        extractor = tmpl["extractor"]
        stats = extractor(self._store, params or {})

        if not stats or not stats.get("values"):
            return None

        # 构建 MentalModel
        values = stats["values"]  # list of (value, count)
        total_count = sum(c for _, c in values)
        best_value, best_count = values[0] if values else (None, 0)
        confidence = best_count / max(total_count, 1)

        model = MentalModel(
            id=model_id,
            question_template=tmpl["template"].format(**params) if params else tmpl["template"],
            category=tmpl["category"],
            best_value=best_value,
            confidence=round(confidence, 3),
            evidence_count=total_count,
            alternatives=[
                {"value": v, "score": round(c / max(total_count, 1), 3), "count": c}
                for v, c in values[:5]  # top 5
            ],
            source_rules=stats.get("source_rules", []),
            created_at=stats.get("created_at", ""),
            updated_at=stats.get("updated_at", ""),
        )

        self._cache[cache_key] = model
        return model

    def compute_all(self, params: dict | None = None) -> list[MentalModel]:
        """计算所有注册模板的答案。"""
        results = []
        for model_id in self._templates:
            m = self.compute(model_id, params)
            if m:
                results.append(m)
        return results

    # ── 缓存与查询 ─────────────────────────────

    def get_cached(self, model_id: str, params: dict | None = None) -> MentalModel | None:
        """从缓存获取（不重新计算）。"""
        key = f"{model_id}:{json.dumps(params or {}, sort_keys=True)}"
        return self._cache.get(key)

    def clear_cache(self) -> None:
        """清空缓存。"""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @property
    def template_count(self) -> int:
        return len(self._templates)

    @property
    def templates(self) -> dict:
        return dict(self._templates)

    # ── 序列化 ─────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "templates": list(self._templates.keys()),
            "cache_size": self.cache_size,
            "models": [m.to_dict() for m in self._cache.values()],
        }

    def summary(self) -> str:
        models = list(self._cache.values())
        if not models:
            return "MentalModelEngine: no cached models"
        lines = [f"MentalModelEngine: {len(models)} models cached"]
        for m in models[:10]:
            lines.append(f"  {m.id}: best={m.best_value} (conf={m.confidence}, n={m.evidence_count})")
        return "\n".join(lines)


    # -- RAG-05: search context --

    def to_search_context(self, top_k: int = 10) -> str:
        """Convert cached mental models into a text block suitable for RAG retrieval.

        RAG-05: Layered memory integration. Returns a structured text that can
        be used as an additional retrieval source alongside traditional KB chunks.
        """
        models = list(self._cache.values())
        if not models:
            return ""
        # Sort by confidence * evidence_count as a rough relevance score
        scored = sorted(models, key=lambda m: m.confidence * m.evidence_count, reverse=True)
        top = scored[:top_k]
        parts = ["[Mental Models]"]
        for m in top:
            alt_text = ", ".join("{}({:.2f})".format(a["value"], a["score"]) for a in m.alternatives[:3])
            parts.append(
                f"  Q: {m.question_template}\n"
                f"  A: best={m.best_value} (confidence={m.confidence:.2f}, n={m.evidence_count})\n"
                f"  alternatives: [{alt_text}]"
            )
        return "\n".join(parts)
    # ── 默认提取器（从 PatternStore 提取通用统计）─────────────

    @staticmethod
    def _default_extractor(store, params: dict) -> dict | None:
        """默认提取器：从 PatternStore 中提取频率统计。

        子类或调用方可替换为领域特化提取器。
        """
        if store is None:
            return None

        # 尝试从 PatternStore 的 get_summary() 获取数据
        try:
            summary = store.get_summary()
        except Exception:
            summary = {}

        # 尝试从 exclusion_rules 或 corrections 中提取统计
        patterns = getattr(store, '_patterns', []) or []
        if not patterns:
            try:
                patterns = store.list_patterns()
            except Exception:
                pass

        # 按参数统计频率
        param_counts: dict[Any, int] = defaultdict(int)
        for p in patterns:
            for key, value in p.items():
                if isinstance(value, (str, int, float)):
                    param_counts[value] += 1

        if not param_counts:
            return None

        sorted_values = sorted(param_counts.items(), key=lambda x: x[1], reverse=True)
        return {
            "values": sorted_values[:20],
            "source_rules": [],
            "created_at": "",
            "updated_at": "",
        }


# ============================================================================
# 预置模板工厂
# ============================================================================

def create_default_templates(engine: MentalModelEngine) -> MentalModelEngine:
    """注册预置的心智模型模板。"""
    engine.register_template(
        "best_fast_ma_period",
        "What is the best fast MA period for {market}?",
        "strategy",
    )
    engine.register_template(
        "best_stop_loss_pct",
        "What is the optimal stop-loss percentage for {strategy}?",
        "risk",
    )
    engine.register_template(
        "best_filter_rule",
        "Which filter rule has the highest pass rate for {scenario}?",
        "filter",
    )
    engine.register_template(
        "best_take_profit_method",
        "What is the best take-profit method for {strategy} in {market}?",
        "exit",
    )
    engine.register_template(
        "most_effective_correction",
        "What is the most effective correction for failure mode {failure_mode}?",
        "strategy",
    )
    return engine
