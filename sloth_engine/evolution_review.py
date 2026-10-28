"""Evolution 候选自动评审策略 (P3-E4 收尾 / Task 3).

背景 (见 docs/design/sloth-loop-evolution-roadmap-20261009.md 与 P3-E4 hooks):
  evolution_loader.review_candidates() 原本必须人工 --yes 才纳入候选。
  本模块提供一个**确定性、可解释**的自动评审策略，使演化闭环可在无人工
  干预下自我推进，同时保留人工闸门作为 override。

决策三态 (deterministic):
  accept  — 候选通过全部门槛, 可直接纳入下一批信号池
  reject  — 明确不达标 (低 fitness / 与已纳重复 / 参数越界)
  defer   — 边界情形, 交人工 (保底: 不确定不自动放行)

门槛 (policy, 全部可配置):
  1. fitness_threshold       候选 fitness 必须 >= 该值 (绝对值门)
  2. margin_over_incumbent   相对当前基线 (incumbent) 的最小提升幅度
                              (shadow evaluation: candidate vs incumbent)
  3. max_accept_per_round    单轮最多自动纳入的候选数 (成本/风险护栏)
  4. dedup                   参数签名去重 (与已有/本轮已接受候选重复 -> reject)
  5. param_bounds            参数必须落在 param_domain 合理区间 (可缺省)

设计原则:
  - 纯函数式核心 (review_candidates_deterministic), 便于三轮既定模式校验
  - 无副作用: 只返回决策, 由调用方 (loader) 执行写入
  - 绝不抛异常: 输入异常一律降级为 defer + 原因
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ReviewPolicy:
    """自动评审策略配置。"""
    fitness_threshold: float = 0.0          # 绝对 fitness 门
    margin_over_incumbent: float = 0.0      # 相对基线最小提升
    max_accept_per_round: int = 3           # 单轮自动纳入上限
    dedup: bool = True                      # 参数签名去重
    param_bounds: dict = field(default_factory=dict)   # {key: [lo, hi]}

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ReviewPolicy":
        data = data or {}
        bounds = data.get("param_bounds") or {}
        clean = {}
        for k, v in bounds.items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                clean[str(k)] = [float(v[0]), float(v[1])]
        return cls(
            fitness_threshold=float(data.get("fitness_threshold", 0.0)),
            margin_over_incumbent=float(data.get("margin_over_incumbent", 0.0)),
            max_accept_per_round=int(data.get("max_accept_per_round", 3)),
            dedup=bool(data.get("dedup", True)),
            param_bounds=clean,
        )

    def to_dict(self) -> dict:
        return {
            "fitness_threshold": self.fitness_threshold,
            "margin_over_incumbent": self.margin_over_incumbent,
            "max_accept_per_round": self.max_accept_per_round,
            "dedup": self.dedup,
            "param_bounds": dict(self.param_bounds),
        }


def param_signature(candidate: dict) -> str:
    """候选的参数签名 (确定性): signal_pattern + market_condition + 排序后的 params。"""
    sp = str(candidate.get("signal_pattern", ""))
    mc = str(candidate.get("market_condition", ""))
    params = candidate.get("params") or {}
    try:
        items = sorted((str(k), json.dumps(v, sort_keys=True, ensure_ascii=False))
                       for k, v in params.items())
    except Exception:
        items = sorted((str(k), repr(v)) for k, v in params.items())
    return sp + "|" + mc + "|" + ";".join(k + "=" + v for k, v in items)


def _fitness(candidate: dict) -> float:
    try:
        v = candidate.get("fitness")
        if v is None:
            return -math.inf
        return float(v)
    except (TypeError, ValueError):
        return -math.inf


def _bounds_violations(candidate: dict, bounds: dict) -> list[str]:
    out: list[str] = []
    params = candidate.get("params") or {}
    for key, (lo, hi) in bounds.items():
        if key in params:
            try:
                val = float(params[key])
            except (TypeError, ValueError):
                out.append("{} not numeric".format(key))
                continue
            if val < lo or val > hi:
                out.append("{}={} outside [{},{}]".format(key, val, lo, hi))
    return out


def review_candidates_deterministic(
    candidates: list[dict],
    *,
    policy: Optional[ReviewPolicy] = None,
    incumbent_fitness: float = -math.inf,
    existing_signatures: Optional[list[str]] = None,
) -> dict:
    """确定性自动评审核心。

    Args:
      candidates: 候选列表 (含 fitness / params / signal_pattern ...)
      policy: 评审策略
      incumbent_fitness: 当前基线 fitness (shadow evaluation 对照)
      existing_signatures: 已纳入候选的参数签名 (去重用)

    Returns:
      {
        "accepted": [candidate...],   # 按 fitness 降序, 受 max_accept_per_round 限制
        "rejected": [{candidate, reason}...],
        "deferred": [{candidate, reason}...],
        "policy": {...},
        "incumbent_fitness": float,
        "summary": {"accept": n, "reject": n, "defer": n},
      }
    """
    pol = policy or ReviewPolicy()
    existing = set(existing_signatures or [])
    accepted: list[dict] = []
    rejected: list[dict] = []
    deferred: list[dict] = []
    seen_this_round: set[str] = set()

    def _norm(cand: dict) -> dict:
        out = dict(cand)
        out.setdefault("signal_pattern", "")
        out.setdefault("market_condition", "unknown")
        out.setdefault("params", {})
        return out

    # 确定性排序: fitness 降序, 签名升序 (tie-break)
    ordered = sorted((_norm(c) for c in (candidates or [])),
                     key=lambda c: (-_fitness(c), param_signature(c)))

    for cand in ordered:
        sig = param_signature(cand)
        fit = _fitness(cand)
        # 1) 参数越界 -> reject
        viol = _bounds_violations(cand, pol.param_bounds)
        if viol:
            rejected.append({"candidate": cand, "reason": "param_bounds: " + ", ".join(viol),
                             "signature": sig})
            continue
        # 2) fitness 无效 -> defer (可能评估失败, 不武断拒绝)
        if fit == -math.inf:
            deferred.append({"candidate": cand, "reason": "missing/invalid fitness",
                             "signature": sig})
            continue
        # 3) 绝对门 -> reject
        if fit < pol.fitness_threshold:
            rejected.append({"candidate": cand,
                             "reason": "fitness {:.4f} < threshold {:.4f}".format(
                                 fit, pol.fitness_threshold),
                             "signature": sig})
            continue
        # 4) 去重 -> reject
        if pol.dedup and (sig in existing or sig in seen_this_round):
            rejected.append({"candidate": cand, "reason": "duplicate signature",
                             "signature": sig})
            continue
        # 5) marginal 提升不足 -> defer (边界, 交人工)
        if fit < incumbent_fitness + pol.margin_over_incumbent:
            deferred.append({"candidate": cand,
                             "reason": "improvement {:.4f} < margin {:.4f}".format(
                                 fit - incumbent_fitness, pol.margin_over_incumbent)
                             if incumbent_fitness != -math.inf else "no incumbent baseline",
                             "signature": sig})
            continue
        # 6) 通过所有门 -> accept (受 max_accept_per_round 限制)
        if len(accepted) >= max(0, pol.max_accept_per_round):
            deferred.append({"candidate": cand,
                             "reason": "exceeds max_accept_per_round={}".format(
                                 pol.max_accept_per_round),
                             "signature": sig})
            continue
        accepted.append(cand)
        seen_this_round.add(sig)

    return {
        "accepted": accepted,
        "rejected": rejected,
        "deferred": deferred,
        "policy": pol.to_dict(),
        "incumbent_fitness": (None if incumbent_fitness == -math.inf else incumbent_fitness),
        "summary": {"accept": len(accepted), "reject": len(rejected),
                    "defer": len(deferred)},
    }


def apply_existing_from_pool(pool: list[dict]) -> list[str]:
    """从既有信号池提取签名 (供去重)。"""
    return [param_signature(c) for c in (pool or [])]
