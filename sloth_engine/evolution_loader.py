"""Evolution loader mixin for Orchestra (P2.1 -> 自主进化 第1档).

把 EvolutionSignalBridge 挂到 Orchestrator，提供：
  - evolve_signals(): 读信号池 -> 演化产出候选 -> 落盘 candidates/ 待评审
  - review_candidates(): 评审通过后把候选正式写入信号池（人审闸门，--review 语义）

默认关闭；config ooda.factor_evolution.enabled=true 时才参与 generate_signals 的前置演化。
"""
from __future__ import annotations

import copy
import json
import logging
from datetime import date
from pathlib import Path

from evolution_bridge import EvolutionConfig, EvolutionSignalBridge
from evolution_review import (
    ReviewPolicy, review_candidates_deterministic, param_signature,
    apply_existing_from_pool,
)

log = logging.getLogger("sloth_engine.evolution-loader")


class EvolutionLoader:
    """Mixin: Orchestrator 的半自主信号演化入口。"""

    def _init_evolution(self) -> None:
        cfg = (self.cfg or {})
        evo_cfg = EvolutionConfig.from_dict(
            (cfg.get("ooda") or {}).get("factor_evolution")
            or cfg.get("factor_evolution"))
        self.evolution_cfg = evo_cfg
        # projects_root 默认用 bridge 的 <engine>/.. (projects store)；
        # 真跑时由 execute/CLI 按项目域进一步限定。
        # fitness 回测使用隔离 I/O 目录，避免与会话/多进程共用 input/output 打架。
        _io_dir = None
        if getattr(self, "runtime", None) is not None and getattr(self.runtime, "io_dir", None):
            _io_dir = self.runtime.io_dir / "evolution"
        self.evolution_bridge = EvolutionSignalBridge(
            evo_cfg,
            run_backtest=None,  # 默认走 backtest_adapter.run_backtest
            task_name=(cfg.get("task") or {}).get("name", "loop"),
            io_dir=_io_dir,
            backtest_cfg=cfg.get("backtest") or {},
            hook_bus=getattr(self, "hook_bus", None),  # P3-E4: lifecycle events
            # cycle-36 A: fitness backtests spawn through the orchestrator gate.
            exec_gate=lambda: getattr(self, "_exec_gate", None))
        self._last_evolution: dict = {}

    def _fire_evolution(self, event_name: str, **data):
        """Fire a P3-E4 evolution event via the orchestrator HookBus. Never raises."""
        bus = getattr(self, "hook_bus", None)
        if bus is None:
            return
        try:
            from hook_events import HookEvent
            evt = getattr(HookEvent, event_name, None)
            if evt is None:
                return
            bus.fire_evolution(evt, task_name=self.task_cfg.get("name", "loop"), **data)
        except Exception as exc:  # pragma: no cover
            log.debug("[evolution] hook fire failed (%s): %s", event_name, exc)

    def evolve_signals(self, seed_path: str | None = None,
                       *, project_name: str | None = None,
                       assume_yes: bool = False,
                       auto_apply: bool = False) -> dict:
        """半自主信号演化。

        读取信号池（或 --signals 指定） -> 演化出候选 -> 落盘 candidates/ 待审。
        assume_yes + auto_apply = true 时直接把 best 候选替换回信号批次（评审跳过）。
        默认只生成候选 + 落到 candidates/，交人工 --review。
        """
        seed_signals = list(self.generate_signals(seed_path))
        if not seed_signals:
            result = {"status": "no_seed", "candidates": [],
                      "message": "No candidate signals to evolve from"}
            self._last_evolution = result
            return result

        result = self.evolution_bridge.evolve(seed_signals)
        result["source_pool_size"] = len(seed_signals)
        self._last_evolution = result

        # 落盘候选（评审待审）—— 不写生产信号文件
        path = self.evolution_bridge.persist_candidates(
            result, project_name=project_name, task_name=self.task_cfg.get("name", "loop"))
        result["candidates_path"] = str(path) if path else None
        if path:
            log.info("[evolution] %d candidate(s) -> %s",
                     len(result.get("candidates") or []), path)

        # 评审/直通：把 best 候选替换为下一批候选信号
        if auto_apply and result.get("status") == "ok" and result.get("candidates"):
            applied = self._apply_candidates(result["candidates"])
            result["applied"] = applied
            self._fire_evolution("EVOLUTION_APPLIED",
                                 applied=applied, source="auto_apply")
        return result

    def _apply_candidates(self, candidates: list[dict]) -> int:
        """把候选写进 SignalsPool 的下一批（临时替换，不入生产文件）。

        返回写入条数。生产信号文件的正式纳入仍应由 --review 完成。
        """
        n = 0
        for cand in (candidates or []):
            row = {
                "signal_pattern": cand.get("signal_pattern", ""),
                "market_condition": cand.get("market_condition", "unknown"),
                "params": dict(cand.get("params") or {}),
            }
            if self.signal_pool._pool is None:
                self.signal_pool._pool = []
            # 追加候选到池尾，供后续 generate_signals 消费
            self.signal_pool._pool.append(row)
            self.signal_pool._cursor = 0
            n += 1
        return n

    def _incumbent_fitness(self) -> float:
        """当前信号池基线 fitness（shadow evaluation 对照）。

        信号池条目未必带 fitness：取其中已记录 fitness 的最大值；无则 -inf。
        """
        pool = getattr(getattr(self, "signal_pool", None), "_pool", None) or []
        best = float("-inf")
        for row in pool:
            try:
                f = row.get("fitness")
                if f is not None:
                    best = max(best, float(f))
            except (TypeError, ValueError, AttributeError):
                continue
        return best

    def _existing_signatures(self) -> list[str]:
        pool = getattr(getattr(self, "signal_pool", None), "_pool", None) or []
        return apply_existing_from_pool(pool)

    def auto_review_candidates(self, candidates_path: str, *,
                               policy: dict | None = None) -> dict:
        """自动评审一个候选文件 (无需人工 --yes)，依据确定性策略决定纳入。

        三态: accept 直接写入信号池并落 .auto-committed 标记；
              reject / defer 仅落盘决策，不改动信号池 (defer 交人工)。
        """
        path = Path(candidates_path)
        if not path.exists():
            return {"status": "missing", "message": str(path)}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"status": "invalid", "message": str(path)}
        candidates = payload.get("candidates") or []
        if not candidates:
            return {"status": "empty", "candidates": []}

        pol = ReviewPolicy.from_dict(policy)
        decision = review_candidates_deterministic(
            candidates, policy=pol,
            incumbent_fitness=self._incumbent_fitness(),
            existing_signatures=self._existing_signatures())

        n = 0
        if decision["accepted"]:
            n = self._apply_candidates(decision["accepted"])
            mark = path.with_name(path.name + ".auto-committed")
            mark.write_text(json.dumps({
                "committed_at": date.today().isoformat(),
                "count": n,
                "policy": pol.to_dict(),
                "summary": decision["summary"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            decision["marker"] = str(mark)

        self._fire_evolution(
            "EVOLUTION_REVIEW",
            decision=("commit" if decision["summary"]["accept"] else "auto_hold"),
            candidates=len(candidates), path=str(path))
        if n:
            self._fire_evolution("EVOLUTION_APPLIED", applied=n, source="auto_review")
        return {"status": "auto_committed" if n else "auto_held",
                "committed": n, **decision}

    def review_candidates(self, candidates_path: str, *, assume_yes: bool = False,
                          auto: bool = False, policy: dict | None = None) -> dict:
        """评审一个候选文件：通过(assume_yes)则正式写入信号池。

        fail-safe: 必须显式 assume_yes 才纳入；否则仅打印候选并返回 pending。
        auto=True 时改走确定性自动评审策略 (见 auto_review_candidates)。
        """
        if auto:
            return self.auto_review_candidates(candidates_path, policy=policy)
        path = Path(candidates_path)
        if not path.exists():
            return {"status": "missing", "message": str(path)}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"status": "invalid", "message": str(path)}

        candidates = payload.get("candidates") or []
        if not candidates:
            return {"status": "empty", "candidates": []}

        if not assume_yes:
            self._fire_evolution("EVOLUTION_REVIEW",
                                 decision="pending", candidates=len(candidates),
                                 path=str(path))
            return {"status": "pending_review", "candidates": candidates,
                    "message": "Use --yes to confirm and commit into signal pool"}

        self._fire_evolution("EVOLUTION_REVIEW",
                             decision="commit", candidates=len(candidates),
                             path=str(path))
        n = self._apply_candidates(candidates)
        # 标记该候选文件已纳入
        mark = path.with_name(path.name + ".committed")
        mark.write_text(json.dumps({
            "committed_at": date.today().isoformat(),
            "count": n,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "committed", "committed": n, "marker": str(mark)}
