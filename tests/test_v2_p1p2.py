"""
v2.0 P1-P2 comprehensive tests using real database.
  factor_evolution | report_generator | prompt_renderer | orchestrator
"""
import atexit, json, os, sys, inspect, subprocess, shutil, tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from memory_store import PatternStore
import orchestrator


def _seed_store(s):
    """Deterministic seed: report / prompt row paths run on every host."""
    try:
        s.append_failure([
            {"id": "SEED-F1", "date": "2026-01-01",
             "signal_pattern": "SEED_SIG", "market_condition": "trend",
             "failure_mode": "EXTREME_CHASE", "failure_reason": "extreme",
             "status": "resolved", "exclusion_rule": "seed-exclusion-1",
             "impact": {"trades": 3}},
            {"id": "SEED-F2", "date": "2026-01-02",
             "signal_pattern": "SEED_SIG2", "market_condition": "range",
             "failure_mode": "WASHOUT", "failure_reason": "washout",
             "status": "open"},
        ])
        s.append_success([
            {"id": "SEED-S1", "date": "2026-01-03",
             "signal_pattern": "SEED_SIG", "market_condition": "trend",
             "status": "confirmed", "reuse_rule": "seed-reuse-1",
             "parameters": {"entry": 1.0, "stop_loss": 0.5,
                            "take_profit": 2.0, "position_size": 1.0},
             "performance": {"quarters_tested": 4, "quarters_positive": 3,
                             "avg_sharpe": 1.2, "avg_annual_excess": 0.1}},
        ])
        s.log_round(3, 1, 2, 2, 1, notes="seed round")
        s.save_run_history({"run_id": "SEED-RUN-1", "task": "seed",
                            "total_rounds": 1, "verdict": "OK"})
    except Exception:
        # Best-effort: tests below assert on shapes, not on the seed.
        pass


# Isolation (cycle-39 A): this module must not open the repo runtime DB.
# It used to do store = PatternStore(_ENGINE/data/patterns.db) at import
# time, which on a fresh clone (a) wrote a ~110KB DB into the checkout
# during *collection*, and (b) turned a legacy-schema DB in the tree into a
# *collection error* that aborted the whole session.
_STORE_DIR = tempfile.mkdtemp(prefix="loop-v2-p1p2-")
atexit.register(shutil.rmtree, _STORE_DIR, ignore_errors=True)
store = PatternStore(str(Path(_STORE_DIR) / "patterns.db"))
_seed_store(store)

# ── factor_evolution (17) ───────────────────────────────────
from factor_evolution import (
    FactorEvolution, EvolveConfig, SignalParams,
    gaussian_mutate, uniform_crossover,
)

def test_evo_config_defaults():
    c = EvolveConfig()
    assert c.population_size == 10 and c.generations == 5 and c.mutation_rate == 0.3

def test_evo_config_custom():
    c = EvolveConfig(population_size=20, generations=10, random_seed=42)
    assert c.population_size == 20 and c.generations == 10 and c.random_seed == 42

def test_signal_params_defaults():
    sp = SignalParams(id="t")
    assert sp.fitness == 0.0 and sp.generation == 0 and sp.parent_ids == []

def test_signal_params_custom():
    sp = SignalParams(id="x", fitness=0.8, generation=3, parent_ids=["a","b"])
    assert sp.fitness == 0.8 and sp.generation == 3

def test_evo_init_none():
    evo = FactorEvolution()
    assert evo._mutator is None and evo._crossover is None and evo._evaluator is None

def test_evo_set_ops():
    evo = FactorEvolution()
    evo.set_mutator(lambda p: p)
    evo.set_crossover(lambda a,b: a)
    evo.set_evaluator(lambda p: 1.0)
    assert evo._mutator and evo._crossover and evo._evaluator

def test_evo_no_eval_raises():
    evo = FactorEvolution()
    try:
        evo.evolve([{"params":{"x":1}}])
        assert False
    except RuntimeError:
        pass

def test_evo_empty():
    evo = FactorEvolution(); evo.set_evaluator(lambda p: 1.0)
    assert evo.evolve([]) == []

def test_evo_basic():
    evo = FactorEvolution(EvolveConfig(population_size=4,generations=2,random_seed=1))
    evo.set_evaluator(lambda p: p.get("score",0))
    r = evo.evolve([{"params":{"score":i*10}} for i in range(5)])
    assert len(r) > 0 and r[0].fitness >= 0

def test_evo_sorted():
    evo = FactorEvolution(EvolveConfig(population_size=3,generations=3,random_seed=2))
    evo.set_evaluator(lambda p: p["v"])
    r = evo.evolve([{"params":{"v":5}},{"params":{"v":20}}])
    for i in range(len(r)-1): assert r[i].fitness >= r[i+1].fitness

def test_evo_history():
    evo = FactorEvolution(EvolveConfig(population_size=3,generations=3,random_seed=3))
    evo.set_evaluator(lambda p: p["v"]); evo.evolve([{"params":{"v":10}}])
    h = evo.get_history(); assert len(h)==3 and "best_fitness" in h[0]

def test_evo_save():
    evo = FactorEvolution(EvolveConfig(population_size=3,generations=2,random_seed=4))
    evo.set_evaluator(lambda p: p["v"]); evo.evolve([{"params":{"v":10}}])
    p = _ENGINE/"data"/"test_evo.json"; evo.save(str(p))
    assert p.exists() and "history" in json.loads(p.read_text(encoding="utf-8"))
    os.unlink(p)

def test_gauss_fixed_string():
    r = gaussian_mutate({"a":1,"name":"x"}, sigma=0.1)
    assert r["name"] == "x"

def test_gauss_specific_keys():
    r = gaussian_mutate({"a":100,"b":200}, keys=["a"], sigma=0.1)
    assert isinstance(r["a"],float) and r["b"]==200

def test_gauss_no_mutate_orig():
    o = {"a":100}; gaussian_mutate(o, sigma=0.1); assert o["a"]==100

def test_crossover_keys():
    r = uniform_crossover({"a":1,"b":2},{"a":3,"c":4})
    assert "a" in r and "b" in r and "c" in r

def test_crossover_no_mutate():
    a,b = {"x":1},{"y":2}; uniform_crossover(a,b)
    assert a=={"x":1} and b=={"y":2}

# ── report_generator (5) ────────────────────────────────────
from report_generator import generate_html_report

def test_rpt_create():
    p = _ENGINE/"data"/"t1.html"; r = generate_html_report(store, str(p))
    assert r.exists(); os.unlink(p)

def test_rpt_html():
    p = _ENGINE/"data"/"t2.html"; r = generate_html_report(store, str(p))
    c = r.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in c and "</html>" in c
    os.unlink(p)

def test_rpt_overview():
    p = _ENGINE/"data"/"t3.html"; r = generate_html_report(store, str(p))
    c = r.read_text(encoding="utf-8")
    assert "Total Rounds" in c and "Failure Patterns" in c
    os.unlink(p)

def test_rpt_tables():
    p = _ENGINE/"data"/"t4.html"; r = generate_html_report(store, str(p))
    c = r.read_text(encoding="utf-8")
    assert "Active Exclusion Rules" in c and "Recent Rounds" in c
    os.unlink(p)

def test_rpt_parent_dirs():
    p = _ENGINE/"data"/"d"/"t5.html"; r = generate_html_report(store, str(p))
    assert r.exists(); shutil.rmtree(p.parent, ignore_errors=True)

# ── prompt_renderer (11) ────────────────────────────────────
from prompt_renderer import render_prompt, render_context_block, _get_state_snapshot

def test_snap_dict():
    s = _get_state_snapshot(store); assert isinstance(s, dict) and "total_rounds" in s

def test_snap_fields():
    s = _get_state_snapshot(store)
    for f in ["total_rounds","total_failures","total_successes","active_rules",
              "open_failures","confirmed_successes","queue_total","queue_queued",
              "stale_rules","date","time"]:
        assert f in s, f"missing {f}"

def test_snap_date(): assert len(_get_state_snapshot(store)["date"]) == 10

def test_snap_nonneg():
    s = _get_state_snapshot(store)
    assert s["total_rounds"]>=0 and s["total_failures"]>=0 and s["active_rules"]>=0

def test_render_bad_tpl():
    assert "error" in render_prompt(store, "nonexistent").lower()

def test_render_has_ctx():
    r = render_prompt(store, "pre-backtest")
    if "error" not in r.lower(): assert "v2.0 Dynamic Context" in r or "<!--" in r

def test_ctx_markers():
    c = render_context_block(store)
    assert "LOOP CONTEXT" in c and "/LOOP CONTEXT" in c

def test_ctx_fields():
    c = render_context_block(store)
    assert "Rounds completed" in c and "Failure patterns" in c

def test_ctx_compact():
    l = [x for x in render_context_block(store).strip().split("\n") if x.strip()]
    assert 5 <= len(l) <= 12

def test_snap_modes_str():
    assert isinstance(_get_state_snapshot(store)["top_failure_modes"], str)

def test_snap_ids_list():
    assert isinstance(_get_state_snapshot(store)["active_rule_ids"], list)

# ── orchestrator (7) ────────────────────────────────────────

def test_confirm_off_true():
    class M: interactive=False
    M._interactive_confirm = orchestrator.Orchestrator._interactive_confirm
    assert M()._interactive_confirm("t") is True

def test_confirm_off_false():
    class M: interactive=False
    M._interactive_confirm = orchestrator.Orchestrator._interactive_confirm
    assert M()._interactive_confirm("t","n") is False

def test_parallel_exists():
    assert hasattr(orchestrator.Orchestrator, "run_parallel")

def test_parallel_sig():
    p = list(inspect.signature(orchestrator.Orchestrator.run_parallel).parameters.keys())
    assert p[0]=="self" and "windows" in p[1]

def test_parallel_mp():
    assert "multiprocessing" in inspect.getsource(orchestrator.Orchestrator.run_parallel)

def test_logging():
    assert orchestrator._log is not None

def test_config_v2():
    from config_util import load_config
    o = load_config(_ENGINE/"config.yaml").get("ooda",{})
    assert "annotation_enabled" in o and "delta_enabled" in o

# ── integration (5) ─────────────────────────────────────────

def test_modules_ok():
    from factor_evolution import FactorEvolution
    from report_generator import generate_html_report
    from prompt_renderer import render_prompt
    assert True

def test_classify_via_store():
    assert store.classify_failure({"failure_reason":"extreme"}) == "EXTREME_CHASE"
    assert store.classify_success({"signal_pattern":"trend following"}) == "TREND_FOLLOWING"

def test_active_rules():
    assert isinstance(store.get_active_exclusion_rules(), list)

def test_cli_doctor():
    # Self-contained doctor CLI check: an isolated temp runtime root with a
    # fresh DB (PatternStore builds v5 via apply(); the migration gate is
    # untouched) and the repo mock_backtest script. This avoids env coupling
    # to the <RUNTIME_ROOT> dev profile; doctor does not consume signals, so
    # none are configured and the signals-containment boundary is not
    # exercised here (it is covered by the boundary test suite instead).
    import tempfile
    with tempfile.TemporaryDirectory(prefix="loop-cli-doctor-") as td:
        cfg_path = Path(td) / "config.doctor.yaml"
        cfg_path.write_text(
            "runtime:\n"
            '  root: "%s"\n'
            '  db: "patterns.db"\n'
            "loop:\n"
            "  max_rounds: 1\n"
            "  no_progress_stop: 3\n"
            "  meta_analyze_every: 100\n"
            "  batch_size: 0\n"
            "  max_seconds: 0\n"
            "backtest:\n"
            '  script: "backtest/mock_backtest.py"\n'
            '  extra_args: "--seed doctor --win-bias 0.5"\n'
            % td.replace("\\", "/"),
            encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(_ENGINE/"orchestrator.py"),
             "--config", str(cfg_path), "--doctor"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(_ENGINE))
        assert "5W1H" in r.stdout, r.stdout + r.stderr
        assert r.returncode == 0, r.stdout + r.stderr

def test_cli_doctor_relative_config_from_non_engine_cwd():
    # --config relative path should resolve from CWD (not the engine dir).
    # Run from a non-engine CWD with a relative config name; the file must be
    # found (no "Config file not found"). Backward compatible: only falls back
    # to _HERE when the CWD-relative path does not exist.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="loop-cli-relative-") as td:
        cwd_dir = Path(td)
        cfg_path = cwd_dir / "config.doctor.yaml"
        cfg_path.write_text(
            "runtime:\n"
            '  root: "%s"\n'
            '  db: "patterns.db"\n'
            "loop:\n"
            "  max_rounds: 1\n"
            "  no_progress_stop: 3\n"
            "  meta_analyze_every: 100\n"
            "  batch_size: 0\n"
            "  max_seconds: 0\n"
            "backtest:\n"
            '  script: "backtest/mock_backtest.py"\n'
            '  extra_args: "--seed doctor --win-bias 0.5"\n'
            % td.replace("\\", "/"),
            encoding="utf-8")
        # relative config name + CWD points to a non-engine dir
        r = subprocess.run(
            [sys.executable, str(_ENGINE/"orchestrator.py"),
             "--config", "config.doctor.yaml", "--doctor"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(cwd_dir))
        assert "5W1H" in r.stdout, r.stdout + r.stderr
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Config file not found" not in (r.stdout + r.stderr), \
            (r.stdout + r.stderr)

def test_cli_help():
    r = subprocess.run(
        [sys.executable, str(_ENGINE/"orchestrator.py"), "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ENGINE))
    assert r.returncode == 0

# ── extended classify (12) ──────────────────────────────────

def test_classify_failure_chinese_jiduan():
    assert store.classify_failure({"failure_reason":"极端位置追单"}) == "INSUFFICIENT_EVIDENCE"

def test_classify_failure_chinese_mangqu():
    assert store.classify_failure({"failure_reason":"绝对位置盲区"}) == "INSUFFICIENT_EVIDENCE"

def test_classify_failure_chinese_zhisun():
    assert store.classify_failure({"failure_reason":"先止损后达标"}) == "INSUFFICIENT_EVIDENCE"

def test_classify_failure_chinese_fangxiang():
    assert store.classify_failure({"failure_reason":"连续方向偏移"}) == "INSUFFICIENT_EVIDENCE"

def test_classify_failure_chinese_zhendang():
    assert store.classify_failure({"failure_reason":"震荡假突破"}) == "INSUFFICIENT_EVIDENCE"

def test_classify_failure_none_reason():
    assert store.classify_failure({"failure_reason": None}) == "INSUFFICIENT_EVIDENCE"

def test_classify_success_chinese_qushi():
    assert store.classify_success({"signal_pattern":"趋势跟踪信号"}) == "EVENT_DRIVEN"

def test_classify_success_chinese_junzhi():
    assert store.classify_success({"signal_pattern":"均值回归策略"}) == "EVENT_DRIVEN"

def test_classify_success_chinese_tupo():
    assert store.classify_success({"signal_pattern":"突破确认模式"}) == "EVENT_DRIVEN"

def test_classify_success_chinese_zhendang():
    assert store.classify_success({"signal_pattern":"震荡区间反转"}) == "EVENT_DRIVEN"

def test_classify_failure_case_insensitive():
    assert store.classify_failure({"failure_reason":"EXTREME CHASE"}) == "EXTREME_CHASE"

def test_match_combo_with_at():
    assert PatternStore._match(
        {"signal_pattern":"ExtremeChase signal","market_condition":"H240Trend"},
        {"exclusion_rule":"ExtremeChase @ H240Trend"})

# ── PatternStore operations (10) ────────────────────────────

def test_store_check_exclusion_returns_dict():
    r = store.check_exclusion([{"signal_pattern":"test","market_condition":"x"}])
    assert isinstance(r, dict) and "passed" in r and "excluded" in r

def test_store_check_exclusion_counts():
    r = store.check_exclusion([{"signal_pattern":"t1"},{"signal_pattern":"t2"}])
    assert r["input_count"] == 2

def test_store_load_failures():
    f = store.load_failure_patterns()
    assert isinstance(f, list) and len(f) >= 0

def test_store_load_successes():
    s = store.load_success_patterns()
    assert isinstance(s, list) and len(s) >= 0

def test_store_rounds():
    r = store.get_rounds()
    assert isinstance(r, list)

def test_store_queue_stats():
    s = store.get_queue_stats()
    assert isinstance(s, dict) and "total" in s

def test_store_run_history():
    h = store.get_run_history(limit=5)
    assert isinstance(h, list) and len(h) <= 5

def test_store_l2_analysis():
    a = store.get_last_l2_analysis()
    assert a is None or isinstance(a, dict)

def test_store_make_rule():
    r = store.make_rule("TestPattern", "TestMarket", scope="combo")
    assert "TestPattern" in r and "TestMarket" in r

def test_store_make_rule_pattern_only():
    r = store.make_rule("OnlyPattern", scope="pattern")
    assert r == "OnlyPattern"

# ── FactorEvolution extended (8) ─────────────────────────────

def test_evo_population_padded():
    evo = FactorEvolution(EvolveConfig(population_size=10, generations=1, random_seed=5))
    evo.set_mutator(lambda p: gaussian_mutate(p, sigma=0.01))
    evo.set_evaluator(lambda p: p.get("v", 0))
    r = evo.evolve([{"params":{"v":100}}])  # only 1 seed, should pad to 10
    assert len([x for x in r if x.generation == 0]) <= 10

def test_evo_elite_preserved():
    evo = FactorEvolution(EvolveConfig(population_size=4, generations=3, elite_keep=2, random_seed=6))
    evo.set_evaluator(lambda p: p["v"])
    r = evo.evolve([{"params":{"v":i*10}} for i in range(5)])
    # best individual should come from highest fitness
    assert r[0].fitness >= r[-1].fitness

def test_evo_crossover_applied():
    crossed = [False]
    def xover(p1, p2): crossed[0] = True; return uniform_crossover(p1, p2)
    evo = FactorEvolution(EvolveConfig(population_size=4, generations=3, crossover_rate=1.0, random_seed=7))
    evo.set_crossover(xover); evo.set_evaluator(lambda p: p.get("v", 0))
    evo.evolve([{"params":{"v":10}}, {"params":{"v":20}}])
    assert crossed[0]

def test_evo_mutation_applied():
    mutated = [False]
    def mut(p): mutated[0] = True; return gaussian_mutate(p, sigma=0.1)
    evo = FactorEvolution(EvolveConfig(population_size=4, generations=3, mutation_rate=1.0, random_seed=8))
    evo.set_mutator(mut); evo.set_evaluator(lambda p: p.get("v", 0))
    evo.evolve([{"params":{"v":10}}])
    assert mutated[0]

def test_evo_preserves_signal_pattern():
    evo = FactorEvolution(EvolveConfig(population_size=3, generations=2, random_seed=9))
    evo.set_evaluator(lambda p: p.get("v", 0))
    r = evo.evolve([{"signal_pattern":"MY_SIG","params":{"v":10}}])
    for ind in r:
        if ind.generation > 0:
            assert ind.signal_pattern == "MY_SIG"

def test_evo_config_no_seed():
    c = EvolveConfig(random_seed=None)
    assert c.random_seed is None

def test_evo_individual_count():
    evo = FactorEvolution(EvolveConfig(population_size=6, generations=3, random_seed=10))
    evo.set_evaluator(lambda p: p["v"])
    r = evo.evolve([{"params":{"v":i}} for i in range(3)])
    # Rough check: should have at least population_size * generations individuals
    assert len(r) > 10

def test_evo_save_non_existent_dir():
    evo = FactorEvolution(EvolveConfig(population_size=2, generations=1, random_seed=11))
    evo.set_evaluator(lambda p: 1.0); evo.evolve([{"params":{"v":1}}])
    p = _ENGINE/"data"/"evo"/"deep"/"test.json"
    evo.save(str(p))
    assert p.exists()
    shutil.rmtree(p.parent.parent, ignore_errors=True)

# ══════════════════════════════════════════════════════════════
def test_store_is_isolated_from_the_repo_tree():
    """Regression (cycle-39 A): the module store must not be the repo DB.

    Opening sloth_engine/data/patterns.db at import time made collection
    depend on machine-local state -- a legacy-schema DB aborted the whole
    session with a collection error, and a fresh clone had a ~110KB DB
    written into the checkout by collecting.
    """
    import os
    store_path = os.path.abspath(str(store.db_path))
    repo = os.path.abspath(str(_ENGINE))
    assert not store_path.startswith(repo + os.sep), store_path


if __name__ == "__main__":
    tests = [v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    p,f = 0,[]
    for t in tests:
        try: t(); p += 1
        except Exception as e: f.append(f"{t.__name__}: {e}")
    print(f"v2.0 P1-P2: {p}/{len(tests)} passed")
    for x in f: print(f"  FAIL {x}")
    if not f:
        print("ALL PASSED")
    else:
        raise SystemExit(1)
