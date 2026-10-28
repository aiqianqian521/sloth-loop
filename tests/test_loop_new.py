#!/usr/bin/env python
"""
New-feature regression tests for Loop framework (P0+).
Zero dependencies. Run: python tests/test_loop_new.py

Covers: P0 problem queue, alias matching, zone config,
consumer logic, min-win-rate filtering, stop diagnosis.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from config_util import deep_merge, DEFAULT_CONFIG  # noqa: E402
from memory_store import PatternStore  # noqa: E402
from orchestrator import Orchestrator  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append((name, detail))
        print(f"  FAIL  {name}   {detail}")
        if "pytest" in sys.modules:
            raise AssertionError(f"{name}: {detail}")


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="looptest_"))


def base_cfg(db: Path, **overrides) -> dict:
    cfg = deep_merge(DEFAULT_CONFIG, {
        "memory": {"sqlite_path": str(db)},
        "loop": {"max_rounds": 10, "no_progress_stop": 3,
                 "meta_analyze_every": 100, "batch_size": 0},
        "backtest": {"script": str(ROOT / "backtest" / "mock_backtest.py"),
                     "extra_args": "--seed test --win-bias 0.5"},
        "ooda": {"enabled": True},
        "zones": {"green": ["batch_size"], "yellow": ["exclusion_rule"], "red": ["hard_constraints"]},
        "consumer": {"min_queue_size": 3, "min_same_type": 3, "high_confidence": 5, "max_suggestions": 5},
        "task": {"name": "test-loop", "success_criteria": [{"metric": "trades_count", "operator": "gt", "threshold": 0}]},
    })
    cfg["loop"].update(overrides)
    return cfg


# ── P0 Problem Queue ────────────────────────────────────────

def test_problem_queue_push():
    print("\n[1] P0 problem queue: push and stats")
    db = tmpdir() / "test.db"
    ps = PatternStore(db)

    ps.push_problem({"id": "P-TEST-001", "type": "execution_error",
                     "severity": "critical", "source": "test",
                     "round": 1, "context": {"error": "crash"},
                     "evidence": "Backtest crashed", "suggested_action": "run doctor",
                     "created_at": "2026-08-11"})
    stats = ps.get_queue_stats()
    check("total=1", stats["total"] == 1, str(stats))
    check("by_status queued=1", stats["by_status"].get("queued") == 1)
    check("by_type execution_error=1", stats["by_type"].get("execution_error") == 1)


def test_problem_queue_dedup():
    print("\n[2] P0 problem queue: dedup on push")
    db = tmpdir() / "test.db"
    ps = PatternStore(db)

    ps.push_problem({"id": "P-DUP-001", "type": "stagnation",
                     "severity": "minor", "source": "test",
                     "round": 1, "context": {}, "evidence": "x",
                     "suggested_action": "x", "created_at": "2026-08-11"})
    ps.push_problem({"id": "P-DUP-001", "type": "stagnation",
                     "severity": "minor", "source": "test",
                     "round": 2, "context": {}, "evidence": "x2",
                     "suggested_action": "x2", "created_at": "2026-08-11"})
    stats = ps.get_queue_stats()
    check("dedup: total=1", stats["total"] == 1, str(stats))


def test_problem_queue_pull_grouped():
    print("\n[3] P0 problem queue: pull grouped by type")
    db = tmpdir() / "test.db"
    ps = PatternStore(db)

    for i in range(4):
        ps.push_problem({"id": f"P-E{i:03d}", "type": "execution_error",
                         "severity": "critical", "source": "test",
                         "round": i, "context": {}, "evidence": f"err{i}",
                         "suggested_action": "fix", "created_at": "2026-08-11"})
    for i in range(2):
        ps.push_problem({"id": f"P-S{i:03d}", "type": "stagnation",
                         "severity": "minor", "source": "test",
                         "round": i + 10, "context": {}, "evidence": f"stag{i}",
                         "suggested_action": "expand", "created_at": "2026-08-11"})

    grouped = ps.pull_problems(status="queued", min_count=3, group_by="type")
    check("execution_error group exists (4>=3)", any(g["type"] == "execution_error" for g in grouped))
    check("stagnation group NOT present (2<3)", not any(g["type"] == "stagnation" for g in grouped))

    # Individual pull without group_by
    all_q = ps.pull_problems(status="queued")
    check("individual pull returns 6", len(all_q) == 6)

    # Status update
    ps.update_problem_status("P-E000", "resolved")
    remaining = ps.pull_problems(status="queued")
    check("status update: 5 remaining after resolve 1", len(remaining) == 5)


# ── M1 Alias Matching ───────────────────────────────────────

def test_alias_matching():
    print("\n[4] M1 alias matching: alias triggers exclusion")
    # Simulate: knowledge base has rule for "old_label"
    # Test signal has signal_pattern="new_label" + aliases=["old_label"]
    from memory_store import PatternStore as PS

    signal = {"signal_pattern": "new_label", "market_condition": "trend",
              "aliases": ["old_label", "legacy_name"]}
    rule = {"exclusion_rule": "old_label", "id": "F-001", "failure_mode": "TEST"}

    check("alias match (direct rule)", PS._match(signal, rule) is True)

    signal2 = {"signal_pattern": "new_label", "market_condition": "trend",
               "aliases": ["other_name"]}
    check("no alias match (wrong alias)", PS._match(signal2, rule) is False)

    # Combo match: alias + market
    rule_combo = {"exclusion_rule": "legacy_name @ trend", "id": "F-002"}
    check("alias + market combo match", PS._match(signal, rule_combo) is True)

    # No aliases field at all
    signal3 = {"signal_pattern": "new_label", "market_condition": "trend"}
    check("no aliases field, no match", PS._match(signal3, rule) is False)


# ── Zones Config Loading ────────────────────────────────────

def test_zones_config_loading():
    print("\n[5] Zones: green/yellow/red loaded from config")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)

    check("green contains batch_size", "batch_size" in orch.zone_green)
    check("yellow contains exclusion_rule", "exclusion_rule" in orch.zone_yellow)
    check("red contains hard_constraints", "hard_constraints" in orch.zone_red)
    check("consumer min_queue=3", orch.consumer_min_queue == 3)
    check("consumer high_conf=5", orch.consumer_high_conf == 5)


def test_default_config_has_zones():
    print("\n[6] Zones: DEFAULT_CONFIG provides sensible defaults")
    db = tmpdir() / "test.db"
    cfg = deep_merge(DEFAULT_CONFIG, {
        "memory": {"sqlite_path": str(db)},
        "backtest": {"script": str(ROOT / "backtest" / "mock_backtest.py")},
    })
    orch = Orchestrator(cfg)
    check("green has defaults", len(orch.zone_green) >= 2)
    check("yellow has defaults", len(orch.zone_yellow) >= 1)
    check("red has defaults", len(orch.zone_red) >= 1)
    check("consumer defaults min_queue=3", orch.consumer_min_queue == 3)


def test_default_scope_nonempty():
    print("\n[6b] Scope: DEFAULT_CONFIG scope defaults are non-empty")
    db = tmpdir() / "test.db"
    cfg = deep_merge(DEFAULT_CONFIG, {
        "memory": {"sqlite_path": str(db)},
        "backtest": {"script": str(ROOT / "backtest" / "mock_backtest.py")},
        "task": {"name": "x"},  # deliberately does NOT override scope
    })
    orch = Orchestrator(cfg)
    check("scope_allow has defaults", len(orch.scope_allow) >= 1, str(orch.scope_allow))
    check("scope_deny has defaults", len(orch.scope_deny) >= 1, str(orch.scope_deny))


def test_hard_budget_looser_than_loop_is_info():
    print("\n[6c] Scope: budget.hard.max_rounds looser than loop is info (no WARN)")
    db = tmpdir() / "test.db"
    cfg = deep_merge(DEFAULT_CONFIG, {
        "memory": {"sqlite_path": str(db)},
        "backtest": {"script": str(ROOT / "backtest" / "mock_backtest.py")},
        "task": {"name": "x"},
        "loop": {"max_rounds": 1},
        "budget": {"hard": {"max_rounds": 20}},
    })
    import io
    import logging
    logger = logging.getLogger("sloth_engine")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    old_level = logger.level
    try:
        logger.setLevel(logging.DEBUG)
        orch = Orchestrator(cfg)
        output = stream.getvalue()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    warn_lines = [ln for ln in output.splitlines()
                  if "budget.hard.max_rounds" in ln and "!" in ln]
    check("looser budget.max_rounds no WARN", len(warn_lines) == 0, output)


# ── Consumer Logic ──────────────────────────────────────────

def test_consumer_skips_below_min_queue():
    print("\n[7] Consumer: skips when queue < min_queue_size")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)

    # Push 2 problems (below min_queue_size=3)
    for i in range(2):
        orch.store.push_problem({"id": f"P-T{i:03d}", "type": "config_tuning",
                                 "severity": "minor", "source": "test",
                                 "round": i, "context": {}, "evidence": "x",
                                 "suggested_action": "x", "created_at": "2026-08-11"})

    result = orch.meta_analyze()
    check("queue_analyzed=False when below min", result["queue_analyzed"] is False)
    check("no queue recommendations", not any("config" in r for r in result["recommendations"]))


def test_consumer_analyzes_above_threshold():
    print("\n[8] Consumer: analyzes when queue >= min_queue_size")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)

    # Push 4 config_tuning problems (>= min_same_type=3)
    for i in range(4):
        orch.store.push_problem({"id": f"P-CT{i:03d}", "type": "config_tuning",
                                 "severity": "major", "source": "test",
                                 "round": i, "context": {}, "evidence": f"ev{i}",
                                 "suggested_action": "review", "created_at": "2026-08-11"})

    result = orch.meta_analyze()
    check("queue_analyzed=True when above min", result["queue_analyzed"] is True)
    check("has config_tuning recommendation",
          any("config" in r.lower() for r in result["recommendations"]))


# ── Review: min_win_rate filtering ──────────────────────────

def test_review_min_win_rate():
    print("\n[9] Review: min_win_rate filters low-win-rate entries")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)

    # Inject failures with different win rates
    from memory_store import PatternStore as PS
    store = orch.store
    store.append_failure([{"id": store.next_id("F"), "date": "2026-08-11",
                            "signal_pattern": "HighWR", "market_condition": "trend",
                            "failure_mode": "TEST", "impact": {"trades": 1, "win_rate": "60%", "total_pnl": "-1%"},
                            "root_cause": "test", "solution": "TBD",
                            "verification": "TBD", "status": "open", "exclusion_rule": ""}])
    store.append_failure([{"id": store.next_id("F"), "date": "2026-08-11",
                            "signal_pattern": "LowWR", "market_condition": "trend",
                            "failure_mode": "TEST", "impact": {"trades": 1, "win_rate": "30%", "total_pnl": "-1%"},
                            "root_cause": "test", "solution": "TBD",
                            "verification": "TBD", "status": "open", "exclusion_rule": ""}])

    # Review with min_win_rate=0.4: HighWR (60%) should be approved, LowWR (30%) skipped
    orch.review(assume_yes=True, scope="combo", min_win_rate=0.4)

    # After review, HighWR should be resolved, LowWR should still be open
    resolved = [f for f in store.load_failure_patterns() if f.get("status") == "resolved"]
    still_open = [f for f in store.load_failure_patterns() if f.get("status") == "open"]

    check("HighWR resolved", any("HighWR" == f.get("signal_pattern") for f in resolved),
          str([f.get("signal_pattern") for f in resolved]))
    check("LowWR still open", any("LowWR" == f.get("signal_pattern") for f in still_open))


# ── Stop Diagnosis ──────────────────────────────────────────

def test_stop_diagnosis_skips_normal():
    print("\n[10] Stop diagnosis: skips normal termination reasons")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)

    # Normal stops should NOT trigger diagnosis (silent return)
    import io
    import sys
    stdout_capture = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_capture
    try:
        orch._stop_diagnosis("max_rounds reached", 20)
        output1 = stdout_capture.getvalue()
        check("max_rounds produces no diagnosis", output1.strip() == "")

        stdout_capture = io.StringIO()
        sys.stdout = stdout_capture
        orch._stop_diagnosis("Time limit reached (1800s)", 15)
        output2 = stdout_capture.getvalue()
        check("time limit produces no diagnosis", output2.strip() == "")
    finally:
        sys.stdout = old_stdout


def test_stop_diagnosis_outputs_for_anomaly():
    print("\n[11] Stop diagnosis: outputs for anomaly stops")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)

    import io
    import sys
    stdout_capture = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_capture
    try:
        orch._stop_diagnosis("No new patterns for 3 consecutive rounds", 3)
        output = stdout_capture.getvalue()
        check("anomaly stop produces output", "Stop reason" in output)
        check("anomaly output mentions rounds", "Total rounds" in output)
    finally:
        sys.stdout = old_stdout


# ── Alias in check_exclusion flow ───────────────────────────

def test_check_exclusion_with_aliases():
    print("\n[12] check_exclusion: aliases trigger real exclusion")
    db = tmpdir() / "test.db"
    ps = PatternStore(db)

    # Insert a failure with exclusion rule
    ps.append_failure([{"id": ps.next_id("F"), "date": "2026-08-11",
                         "signal_pattern": "old_pattern", "market_condition": "range",
                         "failure_mode": "EXTREME_CHASE",
                         "impact": {"trades": 1, "win_rate": "0%", "total_pnl": "-5%"},
                         "root_cause": "test", "solution": "TBD",
                         "verification": "TBD", "status": "resolved",
                         "exclusion_rule": "old_pattern @ range"}])

    # Signal with alias should be excluded
    signals = [{"signal_pattern": "new_pattern", "market_condition": "range",
                "aliases": ["old_pattern"]}]
    chk = ps.check_exclusion(signals)
    check("alias triggers exclusion", chk["excluded_count"] == 1, str(chk))
    check("alias exclusion summary",
          chk["summary"].startswith("in=1 excl=1"), chk["summary"])

    # Same signal without aliases should NOT be excluded
    signals2 = [{"signal_pattern": "new_pattern", "market_condition": "range"}]
    chk2 = ps.check_exclusion(signals2)
    check("no alias = no exclusion", chk2["excluded_count"] == 0, str(chk2))


# ── Problem status update round-trip ────────────────────────

def test_problem_status_roundtrip():
    print("\n[13] Problem queue: status update round-trip")
    db = tmpdir() / "test.db"
    ps = PatternStore(db)

    ps.push_problem({"id": "P-RT-001", "type": "execution_error",
                     "severity": "critical", "source": "test",
                     "round": 1, "context": {}, "evidence": "test",
                     "suggested_action": "x", "created_at": "2026-08-11"})

    ps.update_problem_status("P-RT-001", "resolved")
    queued = ps.pull_problems(status="queued")
    resolved = ps.pull_problems(status="resolved")

    check("queued=0 after resolve", len(queued) == 0)
    check("resolved=1 after resolve", len(resolved) == 1)
    check("resolved id matches", resolved[0]["id"] == "P-RT-001")


# ── CLI args ────────────────────────────────────────────────

def test_cli_min_win_rate_flag():
    print("[14] CLI: --min-win-rate flag registered")
    from cli_router import CliRouter
    parser = CliRouter.build_parser()
    has_flag = any("--min-win-rate" in a.option_strings for a in parser._actions)
    check(
        "--min-win-rate flag exists",
        has_flag,
        "Flag not found in CliRouter.build_parser()" if not has_flag else "",
    )


# ── Warm namespace dedup ────────────────────────────────────

def test_namespace_warning_dedup():
    print("\n[15] Namespace warning: only warns once per session")
    db = tmpdir() / "test.db"
    ps = PatternStore(db)

    # Add rules but no matching signals — should warn first time only
    ps.append_failure([{"id": ps.next_id("F"), "date": "2026-08-11",
                         "signal_pattern": "X", "market_condition": "Y",
                         "failure_mode": "EXTREME_CHASE",
                         "impact": {"trades": 1, "win_rate": "0%", "total_pnl": "-1%"},
                         "root_cause": "test", "solution": "TBD",
                         "verification": "TBD", "status": "resolved",
                         "exclusion_rule": "X @ Y"}])

    import io
    import sys
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        # First call: warn_namespace=True → should warn
        chk1 = ps.check_exclusion(
            [{"signal_pattern": "unrelated", "market_condition": "other"}],
            warn_namespace=True)
        output1 = sys.stderr.getvalue()
        check("first call warns", "ZERO hits" in output1 or "zero hits" in output1.lower())

        # Second call: warn_namespace=False → should NOT warn
        sys.stderr = io.StringIO()
        chk2 = ps.check_exclusion(
            [{"signal_pattern": "unrelated", "market_condition": "other"}],
            warn_namespace=False)
        output2 = sys.stderr.getvalue()
        check("second call silent", output2.strip() == "")
    finally:
        sys.stderr = old_stderr


# ── Phase 1: Budget/Stop/Scope ─────────────────────────────

def test_budget_hard_soft_loaded():
    print("\n[16] Phase 1: budget hard/soft loaded from config")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)
    check("budget_hard has max_rounds", orch.budget_hard.get("max_rounds") == 20)
    check("budget_hard has max_consecutive_failures",
          orch.budget_hard.get("max_consecutive_failures") == 2)
    check("budget_soft has max_tokens",
          orch.budget_soft.get("max_tokens_per_round") == 50000)


def test_stop_completion_safety_loaded():
    print("\n[17] Phase 1: stop completion/safety loaded from config")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)
    check("stop_completion has entries", len(orch.stop_completion) >= 1)
    check("stop_safety has entries", len(orch.stop_safety) >= 1)


def test_scope_allow_deny_loaded():
    print("\n[18] Phase 1: scope allow/deny loaded from config")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    # base_cfg doesn't set scope, so merge it into task config
    if "task" not in cfg:
        cfg["task"] = {}
    cfg["task"]["scope"] = {"allow": ["data/", "signals/"], "deny": ["secrets/", "keys/"]}
    orch = Orchestrator(cfg)
    check("scope_allow has entries", len(orch.scope_allow) >= 1)
    check("scope_deny has secrets", any("secret" in d.lower() for d in orch.scope_deny))


# ── Run History ────────────────────────────────────────────

def test_run_history_save_and_query():
    print("\n[16] Run history: save to SQLite and query")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)
    orch.store.save_run_history({
        "run_id": "2026-08-12-test-001",
        "task": "test-loop",
        "total_rounds": 20,
        "elapsed_seconds": 45.2,
        "stop_reason": "max_rounds reached",
        "new_failures": 5,
        "new_successes": 12,
        "active_exclusion_rules": 3,
        "problem_queue_total": 7,
        "verdict": "OK",
        "created_at": "2026-08-12T10:00:00",
    })
    history = orch.store.get_run_history(limit=10)
    check("history has 1 entry", len(history) == 1)
    check("run_id matches", history[0]["id"] == "2026-08-12-test-001")
    check("verdict is OK", history[0]["verdict"] == "OK")


def test_run_history_multiple_entries():
    print("\n[17] Run history: multiple entries ordered by date")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)

    for i in range(3):
        orch.store.save_run_history({
            "run_id": f"2026-08-12-test-{i:03d}",
            "task": "test", "total_rounds": 10 + i,
            "elapsed_seconds": 30.0, "stop_reason": "max_rounds reached",
            "new_failures": i, "new_successes": i + 1,
            "active_exclusion_rules": 0, "problem_queue_total": 0,
            "verdict": "OK", "created_at": f"2026-08-12T0{i}:00:00",
        })

    history = orch.store.get_run_history(limit=10)
    check("history has 3 entries", len(history) == 3)


# ── Phase 1: Contract enforcement ──────────────────────────

def test_contract_runtime_limit():
    print("\n[19] Contract: max_runtime_minutes triggers stop")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    cfg["budget"] = {"hard": {"max_runtime_minutes": 1, "max_rounds": 100}, "soft": {}}
    orch = Orchestrator(cfg)
    orch.started_at = time.time() - 120  # started 2 minutes ago, 1min limit
    orch.total_rounds = 1
    result = orch._check_contract_limits()
    check("runtime limit breached", result is not None and "max_runtime_minutes" in str(result))


def test_contract_scope_deny_signals():
    print("\n[20] Contract: scope.deny blocks matching signals")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    cfg["task"]["scope"] = {"allow": ["data/"], "deny": ["secrets/", "production/"]}
    orch = Orchestrator(cfg)
    result = orch._check_scope_violation([
        {"signal_pattern": "access production/config", "market_condition": "any"}
    ])
    check("production denied", result is not None and "production" in str(result).lower())
    result2 = orch._check_scope_violation([
        {"signal_pattern": "normal signal", "market_condition": "trend"}
    ])
    check("clean signal passes", result2 is None)


def test_contract_consecutive_failures():
    print("\n[21] Contract: consecutive_failures circuit breaker")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    cfg["budget"]["hard"]["max_consecutive_failures"] = 2
    cfg["loop"]["error_stop"] = 3
    orch = Orchestrator(cfg)
    orch._consecutive_errors = 2
    orch.total_rounds = 2
    result = orch._check_contract_limits()
    check("2 consecutive failures triggers safety stop",
          result is not None and "consecutive_failures" in str(result))


def test_zones_in_decision():
    print("\n[22] Zones: decision tagged by zone")
    from orchestrator import OODASteps
    zones = {"green": {"batch_size"}, "yellow": {"exclusion_rule"}, "red": {"hard_constraints"}}
    diag_normal = {"severity": "normal", "issue_count": 0, "issues": []}
    d = OODASteps._decide(diag_normal, 1, {"name": "test"}, zones)
    check("normal → green zone", d["zone"] == "green")
    diag_warn = {"severity": "major", "issue_count": 1,
                 "issues": [{"severity": "major", "rule": "exclusion_rule", "msg": "test"}]}
    d2 = OODASteps._decide(diag_warn, 1, {"name": "test"}, zones)
    check("exclusion_rule in yellow → yellow zone", d2["zone"] == "yellow")
    diag_red = {"severity": "critical", "issue_count": 1,
                "issues": [{"severity": "critical", "rule": "hard_constraints", "msg": "test"}]}
    d3 = OODASteps._decide(diag_red, 1, {"name": "test"}, zones)
    check("hard_constraints → skip (not zone tag)", d3["action"] == "skip")


def test_consumer_max_suggestions():
    print("\n[23] Consumer: max_suggestions truncates recommendations")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    cfg["consumer"]["max_suggestions"] = 1
    orch = Orchestrator(cfg)
    # Push ≥3 same-type to trigger consumer + different types for more recs
    for i in range(4):
        orch.store.push_problem({
            "id": f"P-MS{i:03d}", "type": "config_tuning",
            "severity": "major", "source": "test",
            "round": i, "context": {},
            "evidence": f"test {i}",
            "suggested_action": "review", "created_at": "2026-08-13",
        })
    for i in range(4):
        orch.store.push_problem({
            "id": f"P-MS{i+4:03d}", "type": "execution_error",
            "severity": "critical", "source": "test",
            "round": i+4, "context": {},
            "evidence": f"err {i}",
            "suggested_action": "fix", "created_at": "2026-08-13",
        })
    result = orch.meta_analyze()
    recs = result["recommendations"]
    has_truncation = any("还有" in r for r in recs)
    check("recommendations truncated",
          has_truncation,
          f"got {len(recs)} recs, truncation={'yes' if has_truncation else 'no'}")


def test_all_criteria_met():
    print("\n[24] Contract: _all_criteria_met with resolved failures")
    db = tmpdir() / "test.db"
    cfg = base_cfg(db)
    orch = Orchestrator(cfg)
    # No rounds yet
    check("empty → not met", orch._all_criteria_met() is False)
    # Log a round with no new patterns
    orch.store.log_round(10, 0, 10, 0, 0, "ok")
    check("clean round → met", orch._all_criteria_met() is True)
    # Add an open failure
    orch.store.append_failure([{
        "id": orch.store.next_id("F"), "date": "2026-08-13",
        "signal_pattern": "TestFail", "market_condition": "trend",
        "failure_mode": "TEST", "impact": {"trades": 1, "win_rate": "0%", "total_pnl": "-1%"},
        "root_cause": "test", "solution": "TBD", "verification": "TBD",
        "status": "open", "exclusion_rule": "",
    }])
    check("open failure → not met", orch._all_criteria_met() is False)


# ── Main ────────────────────────────────────────────────────

def main():
    print("=" * 64)
    print("Loop framework — new feature regression tests")
    print("=" * 64)

    for fn in (test_problem_queue_push, test_problem_queue_dedup,
               test_problem_queue_pull_grouped, test_alias_matching,
               test_zones_config_loading, test_default_config_has_zones,
               test_default_scope_nonempty,
               test_hard_budget_looser_than_loop_is_info,
               test_consumer_skips_below_min_queue, test_consumer_analyzes_above_threshold,
               test_review_min_win_rate, test_stop_diagnosis_skips_normal,
               test_stop_diagnosis_outputs_for_anomaly, test_check_exclusion_with_aliases,
               test_problem_status_roundtrip, test_cli_min_win_rate_flag,
               test_namespace_warning_dedup,
               test_budget_hard_soft_loaded,
               test_stop_completion_safety_loaded,
               test_scope_allow_deny_loaded,
               test_run_history_save_and_query,
               test_run_history_multiple_entries,
               test_contract_runtime_limit,
               test_contract_scope_deny_signals,
               test_contract_consecutive_failures,
               test_zones_in_decision,
               test_consumer_max_suggestions,
               test_all_criteria_met):
        try:
            fn()
        except Exception as e:
            import traceback
            FAIL.append((fn.__name__, repr(e)))
            print(f"  ERROR {fn.__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 64)
    print(f"Result: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for n, d in FAIL:
            print(f"  FAIL  {n}  {d}")
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
