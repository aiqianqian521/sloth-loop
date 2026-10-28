r"""RAG 分层记忆 + 图检索 + MMR — Hindsight 阶段2/4 的零依赖对标实现。

对标 vectorize-io/hindsight 的记忆体系（比较笔记不入本发布版）：

  阶段2 — 语义记忆层 (observations):
    - 三层记忆: mental_models > observations > raw facts
      (Hindsight 的 prefer_observations 语义: observation 覆盖其来源 raw facts)
    - 实体提取: 从文本抽取 PERSON/ORG/DATE/MONEY/PERCENT/PATH 标签
      (对标 Hindsight entity labels)
    - Consolidation: 相似记忆合并 + 去重, 保留 provenance(来源 id 链)

  阶段4 — 图检索 (Spreading Activation):
    - 记忆节点 + 4 类边 (temporal/semantic/entity/causal)
    - 从种子节点沿边扩散, 每跳衰减, 激活度超阈值的节点入结果
      (对标 Hindsight spreading activation)

  融合增强 — MMR (Maximal Marginal Relevance):
    - λ·relevance - (1-λ)·max_similarity_to_selected
      (对标 Hindsight MMR diversity filter)

设计原则 (与 sloth-loop 定位一致):
  - 零依赖: 纯 Python 算法, 不引入 numpy/PG/LLM
  - 可注入 embedding: 相似度用调用方提供的向量或内置 bigram-hash
  - 确定性: 同输入必得同输出 (便于三轮既定模式校验)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from text_merge import merge_texts

# ============================================================================
# 通用工具: 分词 / 余弦 / bigram-hash 嵌入 (与 dsh-rag-kb 同构, 避免耦合)
# ============================================================================

def tokenize(text: str) -> list[str]:
    """CJK-aware 分词: ASCII 词按 \\w+，CJK 按字。"""
    if not text:
        return []
    tokens: list[str] = []
    for m in re.finditer(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text):
        tok = m.group(0).lower()
        tokens.append(tok)
    return tokens


def local_embed(text: str, dim: int = 384) -> list[float]:
    """bigram-hash 嵌入 (确定性, 零依赖)。"""
    vec = [0.0] * dim
    toks = tokenize(text)
    if not toks:
        return vec
    grams = toks if len(toks) == 1 else [a + "_" + b for a, b in zip(toks, toks[1:])]
    for g in grams:
        h = 0
        for ch in g:
            h = (h * 131 + ord(ch)) & 0xFFFFFFFF
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n])) or 1.0
    nb = math.sqrt(sum(x * x for x in b[:n])) or 1.0
    return dot / (na * nb)


# ============================================================================
# 阶段2.1 — 实体提取 (对标 Hindsight entity labels)
# ============================================================================

# 标签词表 (确定性、可扩展)
_ENTITY_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("DATE", re.compile(r"\b(?:19|20)\d{2}[-/](?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])\b")),
    ("TIME", re.compile(r"\b(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b")),
    ("PERCENT", re.compile(r"[-+]?\d+(?:\.\d+)?\s?%")),
    ("MONEY", re.compile(r"(?:\$|USD|USDT|CNY|\u00a5|RMB)\s?\d+(?:\.\d+)?[KkMm]?", re.I)),
    ("PATH", re.compile(r"[A-Za-z]:\\[^\s\"']+|/[\w./-]{3,}")),
    ("ORG", re.compile(r"\b(?:Inc|Ltd|Corp|LLC|GmbH|Co)\b\.?", re.I)),
    ("PERSON", re.compile(r"\b[A-Z][a-z]{1,20}\s+(?!(?:Inc|Ltd|Corp|LLC|GmbH|Co)\b)[A-Z][a-z]{1,20}\b")),
    ("TICKER", re.compile(r"\b(?:BTC|ETH|SOL|USDT|USDC)\b")),
]


def extract_entities(text: str) -> list[dict]:
    """从文本抽取 (label, value, span)。确定性顺序: 先按 label, 再按位置。"""
    if not text:
        return []
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for label, pat in _ENTITY_PATTERNS:
        for m in pat.finditer(text):
            key = (label, m.group(0))
            if key in seen:
                continue
            seen.add(key)
            found.append({"label": label, "value": m.group(0), "span": [m.start(), m.end()]})
    found.sort(key=lambda e: (e["label"], e["span"][0]))
    return found


# ============================================================================
# 阶段2.2 — 分层记忆 (mental_models > observations > raw facts)
# ============================================================================

LAYER_RANK = {"mental_model": 3, "observation": 2, "raw": 1}


@dataclass
class MemoryUnit:
    """一个记忆单元 (任意层的统一载体)。"""
    id: str
    text: str
    layer: str = "raw"                 # mental_model | observation | raw
    entities: list[dict] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)   # provenance (来源 raw ids)
    vector: list[float] = field(default_factory=list)
    timestamp: Optional[str] = None
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)

    def ensure_vector(self, dim: int = 384) -> None:
        if not self.vector:
            self.vector = local_embed(self.text, dim)
        if not self.entities:
            self.entities = extract_entities(self.text)


class LayeredMemory:
    """三层记忆库 + Consolidation + prefer_observations 语义。"""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.units: dict[str, MemoryUnit] = {}
        self._by_layer: dict[str, set[str]] = {"mental_model": set(), "observation": set(), "raw": set()}
        self._covered: set[str] = set()   # 被 observation 覆盖的 raw ids

    # ── 写入 ────────────────────────────────
    def add(self, unit: MemoryUnit) -> MemoryUnit:
        unit.ensure_vector(self.dim)
        self.units[unit.id] = unit
        self._by_layer.setdefault(unit.layer, set()).add(unit.id)
        return unit

    def add_many(self, units: list[MemoryUnit]) -> int:
        for u in units:
            self.add(u)
        return len(units)

    # ── Consolidation: 相似记忆合并 + provenance ─────────
    def consolidate(self, threshold: float = 0.9, into_layer: str = "observation",
                    min_group: int = 2) -> list[MemoryUnit]:
        """将相似 raw 记忆合并为 observation (对标 Hindsight Consolidation)。

        - 仅合并 raw 层
        - 组内 >= min_group 才生成 observation
        - observation.source_ids 记录来源; 来源 raw 被封存 (covered), 检索时若
          prefer_observations=True 则用 observation 替代其来源 raw
        """
        raws = [self.units[i] for i in self._by_layer.get("raw", set())
                if i not in self._covered]
        raws.sort(key=lambda u: u.id)          # 确定性
        groups: list[list[MemoryUnit]] = []
        used: set[str] = set()
        for i, a in enumerate(raws):
            if a.id in used:
                continue
            grp = [a]
            used.add(a.id)
            for b in raws[i + 1:]:
                if b.id in used:
                    continue
                if cosine(a.vector, b.vector) >= threshold:
                    grp.append(b)
                    used.add(b.id)
            groups.append(grp)

        created: list[MemoryUnit] = []
        for grp in groups:
            if len(grp) < min_group:
                continue
            grp.sort(key=lambda u: u.id)
            src_ids = [u.id for u in grp]
            text = self._merge_text(grp)
            obs = MemoryUnit(
                id="obs-" + src_ids[0],
                text=text,
                layer=into_layer,
                source_ids=src_ids,
                confidence=min(1.0, 0.5 + 0.1 * len(src_ids)),
                metadata={"merged_from": src_ids, "count": len(src_ids)},
            )
            self.add(obs)
            for sid in src_ids:
                self._covered.add(sid)
            created.append(obs)
        return created

    @staticmethod
    def _merge_text(grp: list[MemoryUnit]) -> str:
        # 重叠感知的保守拼接（对标 WeKnora internal/searchutil/chunkmerge.go）:
        # 完全包含折叠 + 有界后缀/前缀重叠去除 + 短串不判包含 + 无重叠可去时按
        # 分隔符拼接（宁可保留重复，也不静默丢内容）。
        return merge_texts(u.text for u in grp)

    # ── 检索 (分层 + prefer_observations) ──────────
    def search(self, query: str, top_k: int = 8, prefer_observations: bool = True,
               layer_boost: Optional[dict] = None,
               recency_alpha: float = 0.0, proof_alpha: float = 0.0,
               halflife_days: float = 30.0, recency_mode: str = "exponential",
               now_ts: Optional[float] = None) -> list[dict]:
        """分层检索: 相似度 × 层权重 × (可选) 有界新鲜度/佐证增益。

        recency_alpha / proof_alpha 缺省 0.0 → 乘法恒等 (与旧行为逐位一致)。
        对标 Hindsight combined_score = base * recency_boost * proof_count_boost;
        每个 boost 有界 [1-alpha/2, 1+alpha/2], 且确定性 (同输入同输出)。
        """
        qv = local_embed(query, self.dim)
        boost = layer_boost or {"mental_model": 1.15, "observation": 1.08, "raw": 1.0}
        now = _ts_now() if now_ts is None else float(now_ts)
        rows: list[tuple[float, MemoryUnit]] = []
        for uid, u in self.units.items():
            if prefer_observations and uid in self._covered:
                continue
            sim = cosine(qv, u.vector)
            score = sim * boost.get(u.layer, 1.0)
            if recency_alpha or proof_alpha:
                age_days = None
                if recency_alpha and u.timestamp:
                    ts = _ts(u.timestamp)
                    if ts > 0:
                        age_days = max(0.0, (now - ts) / 86400.0)
                proof = None
                if proof_alpha:
                    proof = int(u.metadata.get("count", 0)) if u.metadata else 0
                    proof = max(proof, len(u.source_ids))
                score = combined_score(
                    score, age_days=age_days, proof_count=proof,
                    recency_alpha=recency_alpha, proof_alpha=proof_alpha,
                    halflife_days=halflife_days, mode=recency_mode)
            rows.append((score, u))
        rows.sort(key=lambda x: (-x[0], x[1].id))   # 确定性 tie-break
        out = []
        for score, u in rows[:top_k]:
            out.append({
                "id": u.id, "layer": u.layer, "score": round(score, 4),
                "text": u.text, "source_ids": list(u.source_ids),
                "entities": [e["value"] for e in u.entities],
            })
        return out

    def stats(self) -> dict:
        return {
            "total": len(self.units),
            "mental_models": len(self._by_layer.get("mental_model", set())),
            "observations": len(self._by_layer.get("observation", set())),
            "raw": len(self._by_layer.get("raw", set())),
            "covered_raw": len(self._covered),
        }


# ============================================================================
# 阶段4 — 图检索: Spreading Activation
# ============================================================================

EDGE_TYPES = ("temporal", "semantic", "entity", "causal")


@dataclass
class MemoryGraph:
    """记忆图: 节点=记忆 id, 边=(src,dst,type,weight)。"""
    nodes: dict[str, MemoryUnit] = field(default_factory=dict)
    edges: list[tuple[str, str, str, float]] = field(default_factory=list)

    def add_node(self, unit: MemoryUnit) -> None:
        unit.ensure_vector()
        self.nodes[unit.id] = unit

    def add_edge(self, src: str, dst: str, etype: str = "semantic", weight: float = 1.0) -> None:
        if etype not in EDGE_TYPES:
            raise ValueError("edge type must be one of {}".format(EDGE_TYPES))
        self.edges.append((src, dst, etype, float(weight)))

    def neighbors(self, node: str) -> list[tuple[str, str, float]]:
        out = []
        for s, d, t, w in self.edges:
            if s == node:
                out.append((d, t, w))
            elif d == node:
                out.append((s, t, w))
        out.sort(key=lambda x: (x[0], x[1]))
        return out

    def auto_link(self, threshold: float = 0.6) -> int:
        """自动建边: 语义(高相似) + 实体(共享实体值) + 时间(邻近时间戳)。

        对标 Hindsight 的 semantic/entity/temporal links。
        """
        ids = sorted(self.nodes)
        added = 0
        for i, a in enumerate(ids):
            ua = self.nodes[a]
            for b in ids[i + 1:]:
                ub = self.nodes[b]
                sim = cosine(ua.vector, ub.vector)
                if sim >= threshold:
                    self.add_edge(a, b, "semantic", round(sim, 4))
                    added += 1
                va = {e["value"] for e in ua.entities}
                vb = {e["value"] for e in ub.entities}
                shared = va & vb
                if shared:
                    self.add_edge(a, b, "entity", float(len(shared)))
                    added += 1
            if ua.timestamp:
                for b in ids[i + 1:]:
                    ub = self.nodes[b]
                    if ub.timestamp and abs(_ts(ua.timestamp) - _ts(ub.timestamp)) <= 86400:
                        self.add_edge(a, b, "temporal", 1.0)
                        added += 1
        return added

    def spreading_activation(self, seeds: list[str], max_hops: int = 3,
                             decay: float = 0.5, threshold: float = 0.05) -> list[dict]:
        """从种子节点沿边扩散, 每跳衰减; 激活度>阈值的节点入结果。

        激活度 = Σ 路径衰减积 × 边权; 节点取最大激活(不累加, 避免重复计数)。
        """
        activation: dict[str, float] = {}
        for s in seeds:
            if s in self.nodes:
                activation[s] = max(activation.get(s, 0.0), 1.0)
        frontier = dict(activation)
        for hop in range(1, max_hops + 1):
            nxt: dict[str, float] = {}
            for node, act in sorted(frontier.items()):
                for (nb, etype, w) in self.neighbors(node):
                    gain = act * (decay ** hop) * w / max(1.0, float(max_hops))
                    if gain > nxt.get(nb, 0.0):
                        nxt[nb] = gain
            for node, gain in nxt.items():
                if gain > activation.get(node, 0.0):
                    activation[node] = gain
            frontier = nxt
            if not frontier:
                break
        out = []
        for node, act in sorted(activation.items(), key=lambda x: (-x[1], x[0])):
            if act < threshold:
                continue
            u = self.nodes[node]
            out.append({"id": node, "activation": round(act, 4),
                        "layer": u.layer, "text": u.text})
        return out


# ============================================================================
# ???????? (?? Hindsight reranking.py:193-198)
#   combined_score = base * recency_boost * proof_count_boost
#   ?? boost = 1 + alpha*(signal - 0.5), ?? [1-alpha/2, 1+alpha/2] ? (??)?
# ??? / ??? / ?? alpha=0 ? ?? (????, ????)?
# ??: 999-hindsight-core .../engine/search/reranking.py:56-78 (recency decay),
#       :193-198 (??), :300-304 (??)?
# ============================================================================

def recency_decay(age_days: float, halflife_days: float = 30.0,
                  mode: str = "exponential") -> float:
    """??????(?)??? [0,1] ????? (?? 0.5)?

    mode:
      "none"        -> ? 0.5 (??, ?????)
      "exponential" -> 0.5 ** (age / halflife); 0 ?=1.0
      "linear"      -> ???? 0.1 ? (??????? 1.0)
    ???? (age < 0) ???? 1.0 (?? Hindsight future-dated clamp)?
    """
    if mode == "none":
        return 0.5
    age = float(age_days)
    if age <= 0.0:
        return 1.0
    if mode == "linear":
        hl = max(1e-9, float(halflife_days))
        return max(0.1, 1.0 - age / (hl * 3.0)) if hl else 0.1
    hl = max(1e-9, float(halflife_days))
    return float(0.5 ** (age / hl))


def recency_boost(age_days: float, alpha: float = 0.2, halflife_days: float = 30.0,
                  mode: str = "exponential") -> float:
    """?????????: 1 + alpha*(decay - 0.5), ?? [1-alpha/2, 1+alpha/2]?"""
    d = recency_decay(age_days, halflife_days=halflife_days, mode=mode)
    a = max(0.0, float(alpha))
    return 1.0 + a * (d - 0.5)


def proof_count_boost(count: int, alpha: float = 0.2, saturate_at: int = 5) -> float:
    """?????????? (???????)?

    signal = min(count, saturate_at) / saturate_at ? [0,1] (?????),
    ? 1 + alpha*(signal - 0.5)?count<=0 ? signal 0 ? 1-alpha/2 (??)?
    """
    sa = max(1, int(saturate_at))
    c = max(0, int(count))
    signal = min(c, sa) / float(sa)
    a = max(0.0, float(alpha))
    return 1.0 + a * (signal - 0.5)


def combined_score(base: float, *, age_days: float | None = None,
                   proof_count: int | None = None,
                   recency_alpha: float = 0.0, proof_alpha: float = 0.0,
                   halflife_days: float = 30.0,
                   mode: str = "exponential") -> float:
    """????: base * recency_boost * proof_count_boost?

    ?? alpha ?? 0 ???? boost ?? 1+0*(...) = 1.0 ? ?? (????????)?
    """
    score = float(base)
    if age_days is not None and recency_alpha:
        score *= recency_boost(age_days, alpha=recency_alpha,
                               halflife_days=halflife_days, mode=mode)
    if proof_count is not None and proof_alpha:
        score *= proof_count_boost(proof_count, alpha=proof_alpha)
    return score


def _ts_now() -> float:
    """当前墙钟 (秒), 独立函数以便测试注入/确定性。"""
    import time as _time
    return _time.time()


def _ts(value: str) -> float:
    """宽松时间戳 → epoch 秒 (失败返回 0)。支持 ISO8601 / 'YYYY-MM-DD'。"""
    import datetime as _dt
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return _dt.datetime.strptime(value.replace("+00:00", "").rstrip("Z"), fmt).timestamp()
        except Exception:
            continue
    return 0.0


# ============================================================================
# MMR — Maximal Marginal Relevance 多样性过滤
# ============================================================================

def mmr_select(candidates: list[dict], top_k: int, lambda_param: float = 0.7,
               vector_of: Optional[Callable[[dict], list[float]]] = None) -> list[dict]:
    """MMR 贪心选择: λ·relevance - (1-λ)·max_sim(已选)。

    Args:
      candidates: [{id, score, text?, vector?}]
      top_k: 目标数量
      lambda_param: 0=只看多样性, 1=只看相关性
      vector_of: 取向量的回调; 缺省用 candidate['vector'] 或 local_embed(text)
    """
    if top_k <= 0 or not candidates:
        return []
    lam = max(0.0, min(1.0, float(lambda_param)))

    def vof(c: dict) -> list[float]:
        if vector_of is not None:
            return vector_of(c)
        v = c.get("vector")
        if v:
            return v
        return local_embed(c.get("text", ""))

    remaining = list(candidates)
    # 确定性: 同分按 id 排序
    remaining.sort(key=lambda c: (-float(c.get("score", 0.0)), str(c.get("id", ""))))
    selected: list[dict] = []
    while remaining and len(selected) < top_k:
        if not selected:
            best = remaining[0]
        else:
            sel_vecs = [vof(s) for s in selected]
            best = None
            best_val = None
            for c in remaining:
                rel = float(c.get("score", 0.0))
                cv = vof(c)
                div = max((cosine(cv, sv) for sv in sel_vecs), default=0.0)
                val = lam * rel - (1.0 - lam) * div
                if best_val is None or val > best_val or (
                        val == best_val and str(c.get("id", "")) < str(best.get("id", ""))):
                    best_val = val
                    best = c
        selected.append(best)
        remaining.remove(best)
    return selected


# ============================================================================
# 分层 + 图 + MMR 的统一检索入口 (对标 Hindsight recall 栈)
# ============================================================================

def layered_recall(memory: LayeredMemory, graph: Optional[MemoryGraph], query: str,
                   top_k: int = 5, lambda_param: float = 0.7,
                   use_graph: bool = True, prefer_observations: bool = True) -> list[dict]:
    """检索 = 分层相似 + (可选)图激活 → 合并 → MMR。"""
    base = memory.search(query, top_k=max(top_k * 3, top_k),
                         prefer_observations=prefer_observations)
    merged: dict[str, dict] = {r["id"]: dict(r) for r in base}
    if use_graph and graph is not None and merged:
        seeds = [r["id"] for r in base[:3]]
        for hit in graph.spreading_activation(seeds, max_hops=2, decay=0.6, threshold=0.02):
            if hit["id"] not in merged:
                merged[hit["id"]] = {
                    "id": hit["id"], "layer": hit["layer"],
                    "score": round(hit["activation"] * 0.5, 4),
                    "text": hit["text"], "source_ids": [], "entities": [],
                    "via": "graph",
                }
            else:
                merged[hit["id"]]["score"] = round(
                    merged[hit["id"]]["score"] + hit["activation"] * 0.3, 4)
    ranked = sorted(merged.values(), key=lambda r: (-r["score"], r["id"]))
    return mmr_select(ranked, top_k=top_k, lambda_param=lambda_param,
                      vector_of=lambda c: local_embed(c.get("text", "")))
