"""Evolution bridge for the Loop orchestrator (P2.1 -> 自主进化 第1档).

接 FactorEvolution 遗传引擎到信号生成链，实现「半自主候选信号演化」。
默认关闭，不影响既有 generate_signals 行为；开启后产出候选信号集交由
人审闸门 (--review) 决定是否入库 —— 对应自主演化阶段B。

安全约束（对齐既有回测隔离）:
  - fitness 评估一律走 backtest_adapter.run_backtest（经过 ExecGate / runtime 隔离）
  - 任何评估异常降级为低 fitness，绝不向上抛；演化失败静默回退原信号池
  - 候选输出落在 projects/<domain>/<task>/candidates/，不写生产信号文件
"""
from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import time

from typing import Any, Callable

from factor_evolution import FactorEvolution, EvolveConfig, gaussian_mutate, uniform_crossover

log = logging.getLogger("sloth_engine.evolution-bridge")

_DEFAULT_PARAM_DOMAIN = {
    "entry_delay": 0,
    "stop_loss_pct": 1.5,
    "take_profit_pct": 3.0,
    "position_size_pct": 0.2,
    "window": 20,
}


@dataclass
class EvolutionConfig:
    """半自主因子演化配置（对应 config ooda.factor_evolution 段）。"""
    enabled: bool = False
    generations: int = 3
    population_size: int = 6
    mutation_rate: float = 0.3
    crossover_rate: float = 0.5
    elite_keep: int = 2
    param_domain: dict = field(default_factory=lambda: dict(_DEFAULT_PARAM_DOMAIN))
    seed: str = "demo"
    win_bias: float = 0.45          # 传给 mock 的 win-bias（真实脚本忽略）
    max_work: int = 40              # 单次演化最多跑多少回测（成本护栏）
    random_seed: int | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "EvolutionConfig":
        data = data or {}
        pd = data.get("param_domain") or {}
        merged_domain = dict(_DEFAULT_PARAM_DOMAIN)
        merged_domain.update({k: v for k, v in pd.items()})
        return cls(
            enabled=bool(data.get("enabled", False)),
            generations=int(data.get("generations", 3)),
            population_size=int(data.get("population_size", 6)),
            mutation_rate=float(data.get("mutation_rate", 0.3)),
            crossover_rate=float(data.get("crossover_rate", 0.5)),
            elite_keep=int(data.get("elite_keep", 2)),
            param_domain=merged_domain,
            seed=str(data.get("seed", "demo")),
            win_bias=float(data.get("win_bias", 0.45)),
            max_work=int(data.get("max_work", 40)),
            random_seed=data.get("random_seed"),
        )


class EvolutionSignalBridge:
    """把信号池 + 领域参数域转成演化种群，产出候选信号集供 review。

    职责边界: 只做「演化候选生成」，不写库、不改信号池、不自动纳入生产。
    评审纳入由上层 --review / 人审闸门完成。
    """

    def __init__(self, config: EvolutionConfig | None = None,
                 *, run_backtest: Callable | None = None,
                 projects_root: Path | None = None,
                 task_name: str = "loop",
                 io_dir: Path | None = None,
                 backtest_cfg: dict | None = None,
                 hook_bus=None,
                 exec_gate=None):
        self.config = config or EvolutionConfig()
        self.hook_bus = hook_bus  # optional HookBus for P3-E4 lifecycle events
        # cycle-36 A: a fitness backtest must go through an ExecGate.  Accept
        # either a gate or a zero-arg provider so a long-lived bridge follows
        # its owner's gate across a project-overlay reload (no stale pin).
        self._exec_gate_source = exec_gate
        # 默认用 backtest_adapter.run_backtest(BacktestInput, settings)
        if run_backtest is None:
            from adapters.backtest_adapter import run_backtest, BacktestInput
            self._run_backtest = lambda inp, settings=None: run_backtest(
                inp, settings, exec_gate=self._current_gate())
            self._BacktestInput = BacktestInput
        else:
            self._run_backtest = run_backtest
            from adapters.backtest_adapter import BacktestInput
            self._BacktestInput = BacktestInput
        self._projects_root = Path(projects_root) if projects_root else Path(__file__).resolve().parent.parent
        self.task_name = task_name
        # 隔离 fitness I/O: 演化期间的回测不与会话/多进程共用同一 input/output，
        # 避免并发写同一文件互相覆盖导致解析卡死。
        self._fit_settings = None
        if io_dir is not None:
            try:
                from adapters.backtest_adapter import configure as _configure
                _abs_io = Path(io_dir).resolve()
                _abs_io.mkdir(parents=True, exist_ok=True)
                self._fit_settings = _configure(dict(backtest_cfg or {}),
                                                project_root=self._projects_root,
                                                io_dir=_abs_io)
            except Exception as exc:
                log.debug("[evolution] isolated io not used: %s", exc)

    def _current_gate(self):
        """Resolve the ExecGate at call time (a gate, or a zero-arg provider)."""
        src = self._exec_gate_source
        if src is None:
            return None
        if hasattr(src, "run"):
            return src
        return src()

    # ── 种群种子 ──────────────────────────────────────────
    # ── 进化生命周期事件 (P3-E4) ────────────────────────────────────
    def _fire(self, event_name: str, **data):
        """Fire an evolution lifecycle event if a HookBus is attached. Never raises."""
        bus = getattr(self, "hook_bus", None)
        if bus is None:
            return
        try:
            from hook_events import HookEvent
            evt = getattr(HookEvent, event_name, None)
            if evt is None:
                return
            bus.fire_evolution(evt, task_name=self.task_name, **data)
        except Exception as exc:  # pragma: no cover - observability must not break
            log.debug("[evolution] hook fire failed (%s): %s", event_name, exc)

    # ── 种子群种子 ────────────────────────────────────
    def build_seed(self, signals: list[dict]) -> list[dict]:
        """把信号池转换为演化种群种子：每条信号绑定一个 params 副本。

        优先用信号自带 params/parameters; 没有则取 param_domain 的默认值。
        """
        seed = []
        for s in signals or []:
            params = s.get("params")
            if not isinstance(params, dict):
                params = s.get("parameters")
            if not isinstance(params, dict) or not params:
                params = copy.deepcopy(self.config.param_domain)
            item = {
                "signal_pattern": s.get("signal_pattern", ""),
                "market_condition": s.get("market_condition", "unknown"),
                "params": copy.deepcopy(params),
            }
            seed.append(item)
        return seed

    # ── fitness 评估 ──────────────────────────────────────
    def default_evaluator(self, seeded_signals: list[dict]) -> Callable[[dict], float]:
        """返回一个评估器：给定 params，跑一遍回测取 sharpe 作为 fitness。

        失败/异常一律降级返回 0.0（绝不抛）。调用次数受 config.max_work 护栏。
        """
        cfg = self.config
        calls = {"n": 0}

        def _ev(params: dict) -> float:
            if calls["n"] >= cfg.max_work:
                return 0.0
            calls["n"] += 1
            try:
                inp = self._BacktestInput(signals=list(seeded_signals), params=dict(params))
                res = self._run_backtest(inp, self._fit_settings)
                if res and getattr(res, "status", "") == "completed":
                    base = float(getattr(res, "sharpe", 0.0) or 0.0)
                    # 有成交才加分，防止空跑刷高；保留真实负值以推动淘汰
                    n_trades = len(getattr(res, "trades", []) or [])
                    if n_trades == 0:
                        return -1.0
                    return max(base, -2.0)
                return -2.0
            except Exception as exc:  # 评估失败降级，绝不中断演化
                log.debug("[evolution] evaluator downgrade: %s", exc)
                return -2.0
        return _ev

    # ── 运行演化 ──────────────────────────────────────────
    def evolve(self, seed_signals: list[dict], evaluator: Callable[[dict], float] | None = None) -> dict:
        """运行遗传演化，返回候选 + 历史。种子不足时直接回退源信号。"""
        self._fire("EVOLUTION_START",
                   generations=self.config.generations,
                   population_size=self.config.population_size,
                   seed_pool=len(seed_signals or []))
        seed = self.build_seed(seed_signals)
        if not seed:
            self._fire("EVOLUTION_ERROR", reason="no_seed")
            return {"status": "no_seed", "candidates": [], "history": [],
                    "source_pool_size": 0}
        self._fire("EVOLUTION_SEED_BUILT", population=len(seed))

        evo = FactorEvolution(EvolveConfig(
            population_size=self.config.population_size,
            generations=self.config.generations,
            mutation_rate=self.config.mutation_rate,
            crossover_rate=self.config.crossover_rate,
            elite_keep=self.config.elite_keep,
            random_seed=self.config.random_seed,
        ))
        domain_keys = list(self.config.param_domain.keys())
        evo.set_mutator(lambda p: gaussian_mutate(copy.deepcopy(p), keys=domain_keys))
        evo.set_crossover(lambda p1, p2: uniform_crossover(copy.deepcopy(p1), copy.deepcopy(p2)))
        evo.set_evaluator(evaluator or self.default_evaluator(seed_signals))

        try:
            individuals = evo.evolve(seed)
        except Exception as exc:
            log.warning("[evolution] evolve failed, falling back to seed pool: %s", exc)
            self._fire("EVOLUTION_ERROR", reason=str(exc)[:200])
            return {"status": "error", "error": str(exc),
                    "candidates": [], "history": [],
                    "source_pool_size": len(seed)}

        # per-generation observability
        try:
            for rec in (evo.get_history() or []):
                gen = rec.get("generation") if isinstance(rec, dict) else None
                self._fire("EVOLUTION_GENERATION_END",
                           generation=gen,
                           best_fitness=(rec.get("best_fitness")
                                         if isinstance(rec, dict) else None))
        except Exception:
            pass

        # 转候选信号（保留 signal_pattern / market_condition，合入演化后的 params）
        best = individuals[: self.config.population_size] if individuals else []
        candidates = []
        for ind in best:
            candidates.append({
                "signal_pattern": ind.signal_pattern,
                "market_condition": ind.market_condition,
                "params": dict(ind.params),
                "fitness": round(float(ind.fitness), 4),
                "generation": int(ind.generation),
                "source": "evolution",
                "status": "pending_review",
            })
        result = {
            "status": "ok",
            "candidates": candidates,
            "history": evo.get_history(),
            "best_fitness": round(best[0].fitness, 4) if best else None,
            "source_pool_size": len(seed),
        }
        self._fire("EVOLUTION_CANDIDATES_READY",
                   candidates=len(candidates),
                   best_fitness=result["best_fitness"])
        return result

    # ── 候选落盘（评审待审）───────────────────────────────
    def persist_candidates(self, result: dict, *, project_name: str | None = None,
                           task_name: str | None = None) -> Path | None:
        """把候选写成待审 JSON，落 projects/<domain>/<task>/candidates/<date>/。

        不写回生产信号文件 —— 评审通过后由 --review 流程做正式纳入。
        """
        if result.get("status") != "ok" or not result.get("candidates"):
            return None
        _raw = (project_name or "loop")
        domain = _raw.split("/", 1)[0] if "/" in _raw else _raw
        task = (task_name or self.task_name)
        if domain and domain != task:
            out_dir = (self._projects_root / domain / task
                       / "candidates" / date.today().isoformat())
        else:
            out_dir = (self._projects_root / task
                       / "candidates" / date.today().isoformat())
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"candidates-{int(time.time())}.json"
        payload = {
            "generated_at": datetime.now().isoformat(),
            "config": {
                "generations": self.config.generations,
                "population_size": self.config.population_size,
                "mutation_rate": self.config.mutation_rate,
                "crossover_rate": self.config.crossover_rate,
                "param_domain": self.config.param_domain,
            },
            "best_fitness": result.get("best_fitness"),
            "candidates": result.get("candidates"),
            "history": result.get("history"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

