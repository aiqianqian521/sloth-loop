"""BM25 多路检索 — P1-N4: 从精确匹配升级为语义感知检索。

对标 Hindsight 4路并行检索 (semantic+bm25+graph+temporal), 
sloth-loop 最小实现: exact_match + BM25 → RRF 融合 → top_k。

BM25 索引源: EventLog 事件 (JSONL), PatternStore 模式库。
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

# ============================================================================
# BM25 核心
# ============================================================================

@dataclass
class BM25Doc:
    """BM25 文档。"""
    id: str           # 唯一标识
    text: str         # 原始文本
    metadata: dict = field(default_factory=dict)  # 额外元数据


class BM25Index:
    """轻量级 BM25 索引。

    内存索引，支持实时添加文档。
    实现 BM25 Okapi 变体 (k1=1.5, b=0.75)。
    """

    K1 = 1.5
    B = 0.75

    def __init__(self):
        self._docs: list[BM25Doc] = []
        self._doc_lengths: list[int] = []       # 每篇文档 token 数
        self._term_doc_freq: dict[str, int] = defaultdict(int)  # 词项→文档频率
        self._avg_doc_len: float = 0.0
        self._total_docs: int = 0

    # ── 索引构建 ───────────────────────────────

    def add(self, doc: BM25Doc) -> None:
        """添加单篇文档。"""
        tokens = self._tokenize(doc.text)
        self._docs.append(doc)
        self._doc_lengths.append(len(tokens))
        unique_terms = set(tokens)
        for term in unique_terms:
            self._term_doc_freq[term] += 1
        self._total_docs += 1
        self._avg_doc_len = sum(self._doc_lengths) / max(self._total_docs, 1)

    def add_batch(self, docs: list[BM25Doc]) -> None:
        """批量添加。"""
        for doc in docs:
            self.add(doc)

    # ── 检索 ───────────────────────────────────

    def search(self, query: str, top_k: int = 10) -> list[tuple[BM25Doc, float]]:
        """BM25 检索，返回 (doc, score) 列表按分数降序。"""
        query_tokens = self._tokenize(query)
        if not query_tokens or self._total_docs == 0:
            return []

        scores: list[tuple[int, float]] = []  # (doc_index, score)
        for i in range(self._total_docs):
            score = self._bm25_score(query_tokens, i)
            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [(self._docs[i], s) for i, s in scores[:top_k]]

    # ── 内部 ───────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        """简单分词：小写 + 去标点 + 切分。"""
        return re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text.lower()).split()

    def _bm25_score(self, query_tokens: list[str], doc_idx: int) -> float:
        """计算单文档 BM25 分数。"""
        doc_len = self._doc_lengths[doc_idx]
        score = 0.0
        for term in set(query_tokens):
            df = self._term_doc_freq.get(term, 0)
            if df == 0:
                continue
            # IDF
            idf = math.log((self._total_docs - df + 0.5) / (df + 0.5) + 1.0)
            # TF (词频)
            tf = self._term_freq(term, doc_idx)
            # BM25 term score
            num = tf * (self.K1 + 1)
            denom = tf + self.K1 * (1 - self.B + self.B * doc_len / max(self._avg_doc_len, 1))
            score += idf * num / denom
        return score

    def _term_freq(self, term: str, doc_idx: int) -> int:
        """词项在指定文档中的出现次数。"""
        tokens = self._tokenize(self._docs[doc_idx].text)
        return tokens.count(term)

    @property
    def doc_count(self) -> int:
        return self._total_docs


# ============================================================================
# 多路融合（RRF: Reciprocal Rank Fusion）
# ============================================================================

RRF_K = 60  # RRF 平滑常数（标准值）


def reciprocal_rank_fusion(
    result_sets: list[list[tuple[str, float]]],
    k: int = RRF_K,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: 融合多路检索结果。

    Args:
        result_sets: 每路检索结果列表 [(doc_id, score), ...]
        k: RRF 平滑常数
        top_k: 返回前 k 个

    Returns:
        融合后的 [(doc_id, rrf_score), ...] 降序
    """
    rrf_scores: dict[str, float] = defaultdict(float)
    for results in result_sets:
        for rank, (doc_id, _) in enumerate(results, start=1):
            rrf_scores[doc_id] += 1.0 / (k + rank)

    sorted_items = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_items[:top_k]


# ============================================================================
# 排除检查 V2: exact_match + BM25 → RRF 融合
# ============================================================================


def build_pattern_index(patterns: list[dict]) -> BM25Index:
    """从 PatternStore 模式列表构建 BM25 索引。

    每个模式作为一篇文档：pattern_name + failure_mode + description。
    """
    index = BM25Index()
    for p in patterns:
        text_parts = [
            p.get("pattern", ""),
            p.get("failure_mode", ""),
            p.get("description", ""),
            p.get("signal_pattern", ""),
        ]
        text = " ".join(part for part in text_parts if part)
        if text.strip():
            index.add(BM25Doc(
                id=p.get("id", ""),
                text=text,
                metadata={"pattern": p.get("pattern"), "failure_mode": p.get("failure_mode")},
            ))
    return index


def check_exclusion_v2(
    check_fn,           # 原有精确匹配函数 (PatternStoreExclusion.check_exclusion)
    signals: list[dict],
    bm25_index: BM25Index | None = None,
    top_k: int = 5,
    rrf_k: int = RRF_K,
) -> dict:
    """排除检查 V2: exact_match + BM25 → RRF 融合。

    1. 运行原有精确匹配 (check_fn)
    2. 对每个信号构建查询字符串 → BM25 检索
    3. RRF 融合两路结果
    4. 返回增强结果

    Args:
        check_fn: 原有 check_exclusion 函数 (signals) → dict
        signals: 信号列表
        bm25_index: 预构建的 BM25 索引（可选）
        top_k: BM25 返回前 k 个
        rrf_k: RRF 融合常数

    Returns:
        增强的排除检查结果 dict
    """
    # 路1: 精确匹配
    exact_result = check_fn(signals)
    exact_hits = {e["blocked_by"]: e for e in exact_result.get("excluded", [])}

    if bm25_index is None or bm25_index.doc_count == 0:
        # 无 BM25 索引 → 降级为精确匹配
        return {**exact_result, "fusion": "exact_only"}

    # 路2: BM25 检索
    bm25_hits: dict[str, float] = {}
    for s in signals:
        query = _build_query_from_signal(s)
        results = bm25_index.search(query, top_k=top_k)
        for doc, score in results:
            if doc.id not in bm25_hits or score > bm25_hits[doc.id]:
                bm25_hits[doc.id] = score

    # 路3: RRF 融合
    exact_ranked = [(rid, 1.0) for rid in exact_hits]  # 精确匹配视为 rank1
    bm25_ranked = sorted(bm25_hits.items(), key=lambda x: x[1], reverse=True)
    fused = reciprocal_rank_fusion(
        [exact_ranked, [(rid, s) for rid, s in bm25_ranked]],
        k=rrf_k,
        top_k=top_k,
    )

    # 合并结果
    fused_excluded = []
    seen_ids = set(exact_hits.keys())
    for doc_id, rrf_score in fused:
        if doc_id in exact_hits:
            fused_excluded.append({**exact_hits[doc_id], "rrf_score": rrf_score, "source": "exact"})
        elif doc_id in bm25_hits:
            fused_excluded.append({
                "blocked_by": doc_id,
                "bm25_score": bm25_hits[doc_id],
                "rrf_score": rrf_score,
                "source": "bm25",
                "signal": signals[0] if signals else {},
            })

    return {
        **exact_result,
        "fused_excluded_count": len(fused_excluded),
        "fused_excluded": fused_excluded,
        "bm25_hits": len(bm25_hits),
        "fusion": "rrf",
        "fusion_k": rrf_k,
    }


def _build_query_from_signal(signal: dict) -> str:
    """从信号构建 BM25 查询字符串。"""
    parts = [
        signal.get("signal_pattern", ""),
        signal.get("market_condition", ""),
        signal.get("failure_mode", ""),
    ]
    return " ".join(p for p in parts if p)
