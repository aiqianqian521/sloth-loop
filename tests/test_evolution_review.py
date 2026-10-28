"""Evolution 候选自动评审策略单元测试 (Task 3)。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = _ROOT / "sloth_engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from evolution_review import (  # noqa: E402
    ReviewPolicy, review_candidates_deterministic, param_signature,
    apply_existing_from_pool,
)


def _cand(sp, mc, params, fit=None):
    c = {"signal_pattern": sp, "market_condition": mc, "params": params}
    if fit is not None:
        c["fitness"] = fit
    return c


def test_policy_defaults_and_roundtrip():
    pol = ReviewPolicy.from_dict({"fitness_threshold": 0.7, "max_accept_per_round": 5,
                                  "param_bounds": {"window": [10, 45]}})
    assert pol.fitness_threshold == 0.7
    assert pol.max_accept_per_round == 5
    assert pol.param_bounds == {"window": [10.0, 45.0]}
    d = pol.to_dict()
    assert ReviewPolicy.from_dict(d).fitness_threshold == 0.7


def test_accept_reject_defer_taxonomy():
    pol = ReviewPolicy(fitness_threshold=0.5, margin_over_incumbent=0.1,
                       max_accept_per_round=2)
    cands = [
        _cand("A", "up", {"window": 20}, 1.2),
        _cand("A", "up", {"window": 20}, 1.1),   # duplicate signature
        _cand("B", "down", {"window": 30}, 0.3), # below threshold
        _cand("C", "up", {"window": 40}, 0.9),
        _cand("D", "up", {"window": 50}, 0.7),   # exceeds max_accept
        _cand("E", "up", {"window": 60}),        # no fitness -> defer
    ]
    d = review_candidates_deterministic(cands, policy=pol, incumbent_fitness=0.6)
    assert d["summary"] == {"accept": 2, "reject": 2, "defer": 2}
    assert [c["signal_pattern"] for c in d["accepted"]] == ["A", "C"]


def test_param_bounds_reject():
    pol = ReviewPolicy(param_bounds={"window": [10, 45]})
    d = review_candidates_deterministic(
        [_cand("X", "up", {"window": 99}, 9.0)], policy=pol)
    assert d["summary"]["reject"] == 1
    assert "outside" in d["rejected"][0]["reason"]


def test_dedup_against_existing_signatures():
    existing = param_signature(_cand("A", "up", {"window": 20}))
    pol = ReviewPolicy(fitness_threshold=0.0, dedup=True)
    d = review_candidates_deterministic(
        [_cand("A", "up", {"window": 20}, 5.0)],
        policy=pol, existing_signatures=[existing])
    assert d["summary"]["reject"] == 1


def test_margin_over_incumbent_defers_marginal():
    pol = ReviewPolicy(fitness_threshold=0.0, margin_over_incumbent=0.5,
                       max_accept_per_round=10)
    d = review_candidates_deterministic(
        [_cand("A", "up", {"w": 1}, 1.0)], policy=pol, incumbent_fitness=0.9)
    assert d["summary"]["defer"] == 1
    assert "improvement" in d["deferred"][0]["reason"]


def test_deterministic_ordering_same_input_same_output():
    cands = [_cand("B", "up", {"w": 2}, 1.0),
             _cand("A", "up", {"w": 1}, 1.0),
             _cand("C", "up", {"w": 3}, 1.0)]
    pol = ReviewPolicy(fitness_threshold=0.0, margin_over_incumbent=0.0,
                       max_accept_per_round=10)
    a = review_candidates_deterministic(cands, policy=pol, incumbent_fitness=0.0)
    b = review_candidates_deterministic(cands, policy=pol, incumbent_fitness=0.0)
    assert [c["signal_pattern"] for c in a["accepted"]] == \
           [c["signal_pattern"] for c in b["accepted"]]
    # equal fitness -> signature ascending tie-break
    assert [c["signal_pattern"] for c in a["accepted"]] == ["A", "B", "C"]


def test_signature_stable_across_param_order():
    c1 = _cand("A", "up", {"a": 1, "b": 2})
    c2 = _cand("A", "up", {"b": 2, "a": 1})
    assert param_signature(c1) == param_signature(c2)


def test_empty_candidates():
    d = review_candidates_deterministic([], policy=ReviewPolicy())
    assert d["summary"] == {"accept": 0, "reject": 0, "defer": 0}


def test_apply_existing_from_pool():
    pool = [_cand("A", "up", {"w": 1}), _cand("B", "down", {"w": 2})]
    sigs = apply_existing_from_pool(pool)
    assert len(sigs) == 2 and all(isinstance(s, str) for s in sigs)


def test_loader_auto_review_commits(tmp_path, monkeypatch):
    """EvolutionLoader.auto_review_candidates 端到端: 接受则写入信号池。"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("t_evo_loader", _ENGINE / "evolution_loader.py")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Pool:
        def __init__(self):
            self._pool = []
            self._cursor = 0

    class _Dummy(mod.EvolutionLoader):
        def _fire_evolution(self, *a, **k):
            return None

    d = _Dummy.__new__(_Dummy)
    d.signal_pool = _Pool()
    d.task_cfg = {"name": "loop"}

    payload = {"candidates": [
        _cand("A", "up", {"window": 20}, 1.5),
        _cand("B", "up", {"window": 30}, 0.1),   # below default threshold? threshold=0 -> accept
    ]}
    cpath = tmp_path / "candidates.json"
    cpath.write_text(__import__("json").dumps(payload), encoding="utf-8")

    result = d.auto_review_candidates(str(cpath),
                                      policy={"fitness_threshold": 1.0,
                                              "max_accept_per_round": 5})
    assert result["status"] == "auto_committed"
    assert result["committed"] == 1
    assert len(d.signal_pool._pool) == 1
    assert (tmp_path / "candidates.json.auto-committed").exists()


def test_loader_auto_review_holds_when_nothing_qualifies(tmp_path):
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("t_evo_loader2", _ENGINE / "evolution_loader.py")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Pool:
        def __init__(self):
            self._pool = []
            self._cursor = 0

    class _Dummy(mod.EvolutionLoader):
        def _fire_evolution(self, *a, **k):
            return None

    d = _Dummy.__new__(_Dummy)
    d.signal_pool = _Pool()
    d.task_cfg = {"name": "loop"}
    cpath = tmp_path / "c2.json"
    cpath.write_text(__import__("json").dumps(
        {"candidates": [_cand("A", "up", {"w": 1}, 0.2)]}), encoding="utf-8")
    result = d.auto_review_candidates(str(cpath),
                                      policy={"fitness_threshold": 1.0})
    assert result["status"] == "auto_held"
    assert result["committed"] == 0
    assert len(d.signal_pool._pool) == 0
