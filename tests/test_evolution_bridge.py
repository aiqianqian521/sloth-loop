"""第1档: 半自主信号演化桥接层单测（evolution_bridge + evolution_loader）。

覆盖: config 默认/读取、种群种子构建、演化运行、候选落盘、评审纳入、
Orchestrator 接入且默认关闭不改变既有 generate_signals 行为。
fitness 评估用注入的确定性 fake，避免依赖回测子进程（真实回测链路在真跑阶段验证）。
"""
import json, os, sys, tempfile
from pathlib import Path
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from evolution_bridge import EvolutionConfig, EvolutionSignalBridge
from evolution_loader import EvolutionLoader

# ── EvolutionConfig ─────────────────────────────────────────
def test_evo_config_defaults_disabled():
    c = EvolutionConfig()
    assert c.enabled is False
    assert c.generations == 3 and c.population_size == 6
    assert c.mutation_rate == 0.3 and c.crossover_rate == 0.5
    assert "window" in c.param_domain

def test_evo_config_from_dict():
    c = EvolutionConfig.from_dict({"enabled": True, "generations": 5,
                                   "param_domain": {"window": 40}})
    assert c.enabled is True and c.generations == 5
    assert c.param_domain["window"] == 40      # 覆盖
    assert c.param_domain["entry_delay"] == 0  # 默认保留

def test_evo_config_from_empty():
    c = EvolutionConfig.from_dict(None)
    assert c.enabled is False

# ── build_seed ──────────────────────────────────────────────
_SIGS = [
    {"signal_pattern": "极端位置追单", "market_condition": "H240趋势+H1震荡"},
    {"signal_pattern": "窄幅整理突破", "market_condition": "低波动收敛",
     "params": {"window": 30, "position_size_pct": 0.1}},
]

def test_build_seed_uses_own_params():
    br = EvolutionSignalBridge(EvolutionConfig(enabled=True), run_backtest=lambda *a, **k: None)
    seed = br.build_seed(_SIGS)
    assert len(seed) == 2
    assert seed[1]["params"]["window"] == 30          # 自带 params 保留
    assert seed[0]["params"]["window"] == 20          # 无 params 用默认域

def test_build_seed_empty():
    br = EvolutionSignalBridge()
    assert br.build_seed([]) == []

# ── evolve ──────────────────────────────────────────────────
def test_evolve_produces_candidates():
    br = EvolutionSignalBridge(EvolutionConfig(enabled=True, generations=2,
                                               population_size=4, random_seed=7),
                               run_backtest=lambda *a, **k: None)
    # 确定性 fake evaluator：window 越小 fitness 越高（推动演化）
    ev = lambda params: max(0.0, 10.0 - params.get("window", 20))
    result = br.evolve(_SIGS, evaluator=ev)
    assert result["status"] == "ok"
    assert result["candidates"], "应产出候选"
    for cand in result["candidates"]:
        assert cand["source"] == "evolution"
        assert cand["status"] == "pending_review"
        assert cand["signal_pattern"] in {"极端位置追单", "窄幅整理突破"}
        assert "fitness" in cand and "params" in cand

def test_evolve_falls_back_on_error():
    br = EvolutionSignalBridge(EvolutionConfig(enabled=True), run_backtest=lambda *a, **k: None)
    def boom(params):
        raise RuntimeError("evaluator fail")
    result = br.evolve(_SIGS, evaluator=boom)
    assert result["status"] == "error"           # 静默回退
    assert result["candidates"] == []

# ── persist_candidates（评审待审，落 projects/<domain>/<task>/candidates/）──
def test_persist_candidates_path_ok():
    with tempfile.TemporaryDirectory() as td:
        br = EvolutionSignalBridge(EvolutionConfig(enabled=True),
                                   run_backtest=lambda *a, **k: None,
                                   projects_root=Path(td))
        result = br.evolve(_SIGS, evaluator=lambda p: 1.0)
        p = br.persist_candidates(result, project_name="qupm", task_name="lh")
        assert p is not None
        rel = p.relative_to(Path(td))
        assert rel.parts[0] == "qupm" and rel.parts[1] == "lh" and rel.parts[2] == "candidates"
        payload = json.loads(p.read_text(encoding="utf-8"))
        assert payload["candidates"]

def test_persist_candidates_skips_on_no_seed():
    br = EvolutionSignalBridge(EvolutionConfig(enabled=True))
    assert br.persist_candidates({"status": "no_seed", "candidates": []}) is None

# ── review_candidates（人审闸门）─────────────────────────────
class _FakePool:
    def __init__(self):
        self._pool = []
        self._cursor = 0

class _DummyHost(EvolutionLoader):
    """承载 loader 的最小宿主：仅提供 review_candidates 需要的属性。"""
    def __init__(self, tmp_path):
        self.signal_pool = _FakePool()
        self.task_cfg = {"name": "lh"}
        self.evolution_bridge = EvolutionSignalBridge(
            EvolutionConfig(enabled=True), run_backtest=lambda *a, **k: None,
            projects_root=tmp_path)

def test_review_requires_yes(tmp_path):
    host = _DummyHost(Path(tmp_path))
    result = host.evolution_bridge.evolve(_SIGS, evaluator=lambda p: 1.0)
    path = host.evolution_bridge.persist_candidates(result)
    assert path is not None
    r = host.review_candidates(str(path), assume_yes=False)
    assert r["status"] == "pending_review"       # 未 yes 只待审
    rc = host.review_candidates(str(path), assume_yes=True)
    assert rc["status"] == "committed" and rc["committed"] >= 1
    # 候选已进池尾
    assert len(host.signal_pool._pool) == rc["committed"]


# ── Orchestrator 接入 ───────────────────────────────────────
def _isolated_cfg(tmp_dir) -> dict:
    """Repo config with a private DB (cycle-39 A).

    Tests must not create sloth_engine/data/patterns.db inside the
    checkout; only memory.sqlite_path is redirected so the run-root
    containment semantics of the real config stay intact.
    """
    import config_util
    cfg = config_util.load_config(str(_ENGINE / "config.yaml"), {})
    cfg.setdefault("memory", {})["sqlite_path"] = str(Path(tmp_dir) / "patterns.db")
    return cfg


def _build_orch(tmp_path):
    import orchestrator as orch_mod
    cfg = _isolated_cfg(tmp_path)
    # 隔离监控: 不真跑, 仅构造验证接线
    return orch_mod.Orchestrator(cfg)

def test_orchestrator_has_evolution_loader(tmp_path):
    import config_util, orchestrator as orch_mod
    cfg = _isolated_cfg(tmp_path)
    o = orch_mod.Orchestrator(cfg)
    assert isinstance(o, EvolutionLoader)
    assert o.evolution_cfg.enabled is False          # 默认关
    assert hasattr(o, "evolve_signals")
    assert hasattr(o, "review_candidates")

def test_generate_signals_unchanged_when_disabled(tmp_path):
    import config_util, orchestrator as orch_mod
    cfg = _isolated_cfg(tmp_path)
    o = orch_mod.Orchestrator(cfg)
    # 默认关闭演化 -> generate_signals 走原 JSON 池路径
    sigs = o.generate_signals(str(_ENGINE / "data" / "signals_seed.json"))
    assert len(sigs) == o.batch_size                # 默认旋转批次大小
    assert sigs, "应返回信号"
    assert all(s.get("signal_pattern") for s in sigs)   # 原 JSON 池路径语义保留
