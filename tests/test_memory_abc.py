"""测试持久化抽象层 — 移植-P1 模块4"""

import sys
import tempfile
from pathlib import Path
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

import pytest
from memory_store_abc import BasePatternStore, FAILURE_MODES, SUCCESS_MODES
from memory_store_json import JSONPatternStore
from memory_store import PatternStore  # SQLite 后端


# ── ABC 不可实例化 ──

def test_base_pattern_store_cannot_instantiate():
    with pytest.raises(TypeError):
        BasePatternStore()


# ── PatternStore (SQLite) 继承 ABC ──

def test_sqlite_store_is_base_pattern_store():
    tmp = tempfile.mkdtemp()
    try:
        db = Path(tmp) / "test.db"
        store = PatternStore(db)
        assert isinstance(store, BasePatternStore)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── JSONPatternStore 继承 ABC ──

def test_json_store_is_base_pattern_store():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        assert isinstance(store, BasePatternStore)


# ── JSONPatternStore CRUD ──

def test_json_append_and_find_failure():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.append_failure([{
            "id": "F-001", "signal_pattern": "MA_cross",
            "market_condition": "uptrend", "failure_mode": "EXTREME_CHASE",
            "status": "open",
        }])
        found = store.find_failure("MA_cross", "uptrend")
        assert found is not None
        assert found["signal_pattern"] == "MA_cross"


def test_json_find_failure_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        assert store.find_failure("nonexistent", "sideways") is None


def test_json_load_failures():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.append_failure([
            {"id": "F-001", "signal_pattern": "a", "market_condition": "x"},
            {"id": "F-002", "signal_pattern": "b", "market_condition": "y"},
        ])
        all_f = store.load_failure_patterns()
        assert len(all_f) == 2


def test_json_bump_failure():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.append_failure([{
            "id": "F-001", "signal_pattern": "x", "market_condition": "y",
            "impact_trades": 1, "status": "open",
        }])
        store.bump_failure("F-001", extra_trades=2)
        found = store.find_failure("x", "y")
        assert found["impact_trades"] == 3


def test_json_update_failure_status():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.append_failure([{
            "id": "F-001", "signal_pattern": "x", "market_condition": "y",
            "status": "open",
        }])
        store.update_failure_status("F-001", "resolved", exclusion_rule="exclude:MA")
        found = store.find_failure("x", "y")
        assert found["status"] == "resolved"
        assert found["exclusion_rule"] == "exclude:MA"


def test_json_append_and_find_success():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.append_success([{
            "id": "S-001", "signal_pattern": "trend_follow",
            "market_condition": "uptrend", "status": "confirmed",
        }])
        found = store.find_success("trend_follow", "uptrend")
        assert found is not None
        assert found["status"] == "confirmed"


# ── JSONPatternStore 排除检查 ──

def test_json_check_exclusion_no_rules():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        result = store.check_exclusion([
            {"signal_pattern": "MA_cross", "market_condition": "uptrend"},
        ])
        assert len(result["passed"]) == 1
        assert len(result["excluded"]) == 0


def test_json_check_exclusion_with_rule():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.append_failure([{
            "id": "F-001", "signal_pattern": "MA_cross",
            "market_condition": "uptrend", "status": "resolved",
            "exclusion_rule": "exclude:MA_cross",
        }])
        result = store.check_exclusion([
            {"signal_pattern": "MA_cross", "market_condition": "uptrend"},
            {"signal_pattern": "fib_retrace", "market_condition": "sideways"},
        ])
        assert len(result["passed"]) == 1
        assert len(result["excluded"]) == 1


def test_json_get_active_exclusion_rules():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.append_failure([
            {"id": "F-001", "signal_pattern": "a", "status": "resolved",
             "exclusion_rule": "rule_a"},
            {"id": "F-002", "signal_pattern": "b", "status": "open",
             "exclusion_rule": "rule_b"},
            {"id": "F-003", "signal_pattern": "c", "status": "monitoring",
             "exclusion_rule": "rule_c"},
        ])
        active = store.get_active_exclusion_rules()
        assert len(active) == 2  # resolved + monitoring, not open
        rule_ids = {r["id"] for r in active}
        assert rule_ids == {"F-001", "F-003"}


# ── JSONPatternStore rounds ──

def test_json_log_round():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.log_round(10, 3, 7, 1, 0)
        # Just verify no exception — rounds are stored internally
        assert len(store._data["rounds"]) == 1


# ── JSONPatternStore problems ──

def test_json_push_and_pull_problems():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.push_problem({"id": "P-001", "status": "queued", "type": "test"})
        store.push_problem({"id": "P-002", "status": "resolved", "type": "test"})
        queued = store.pull_problems("queued")
        assert len(queued) == 1
        assert queued[0]["id"] == "P-001"


def test_json_get_queue_stats():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        store.push_problem({"id": "P-001", "status": "queued"})
        store.push_problem({"id": "P-002", "status": "queued"})
        stats = store.get_queue_stats()
        assert stats["total"] == 2
        assert stats["by_status"]["queued"] == 2


def test_json_next_id():
    with tempfile.TemporaryDirectory() as tmp:
        store = JSONPatternStore(Path(tmp) / "test.json")
        fid = store.next_id("failure", "2026-08-17")
        assert fid.startswith("F-2026-08-17-")


# ── JSON 持久化测试 ──

def test_json_persistence_across_instances():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.json"
        store1 = JSONPatternStore(path)
        store1.append_failure([{
            "id": "F-001", "signal_pattern": "test",
            "market_condition": "sideways",
        }])

        # 新实例从文件加载
        store2 = JSONPatternStore(path)
        found = store2.find_failure("test", "sideways")
        assert found is not None
        assert found["signal_pattern"] == "test"


# ── 两个后端都能独立工作 ──

def test_both_backends_independent():
    """SQLite 和 JSON 后端各自独立运行，不互相影响。"""
    import shutil
    tmp = tempfile.mkdtemp()
    try:
        # SQLite
        sqlite_store = PatternStore(Path(tmp) / "test.db")
        sqlite_store.append_failure([{
            "id": "F-sqlite", "signal_pattern": "sqlite_only",
            "market_condition": "any", "failure_mode": "EXTREME_CHASE",
        }])

        # JSON
        json_store = JSONPatternStore(Path(tmp) / "test.json")
        json_store.append_failure([{
            "id": "F-json", "signal_pattern": "json_only",
            "market_condition": "any",
        }])

        # 各自数据独立
        assert sqlite_store.find_failure("sqlite_only", "any") is not None
        assert json_store.find_failure("json_only", "any") is not None
        # SQLite 没有 JSON 的数据
        assert sqlite_store.find_failure("json_only", "any") is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)