"""测试 Session Projection 层 — P2-N3。"""

import sys
import tempfile
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from event_log import EventLog, LoopEvent
from session_projection import (
    SessionProjector, ProjectionSpec,
    create_default_projector,
)


# ── 辅助 ──

def _make_log(events_data: list[dict]) -> EventLog:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "proj.jsonl"
        log = EventLog(path, task_name="test", auto_load=False)
        for ed in events_data:
            log.append(ed.get("event_type", "step/observe/end"),
                       {k: v for k, v in ed.items() if k != "event_type"})
        return log


# ── 基本投影 ──

def test_basic_projection():
    """注册一个简单投影 → 重放 → 正确折叠。"""
    p = SessionProjector()
    p.register(ProjectionSpec("counter", 0, lambda s, e: s + 1))

    log = _make_log([
        {"event_type": "round/start", "round": 1},
        {"event_type": "step/observe/end", "round": 1},
        {"event_type": "step/act/end", "round": 1},
    ])
    state = p.project(log)
    assert state["counter"] == 3


def test_multiple_projections():
    """多个投影各自独立折叠。"""
    p = SessionProjector()
    p.register(ProjectionSpec("total", 0, lambda s, e: s + 1))
    p.register(ProjectionSpec("failures", [],
                               lambda s, e: s + [e.error] if e.status == "FAIL" else s))

    log = _make_log([
        {"event_type": "step/observe/end", "round": 1},
        {"event_type": "act/result", "round": 1, "status": "error",
         "error": "disk full"},
        {"event_type": "act/result", "round": 1, "status": "ok"},
    ])
    state = p.project(log)
    assert state["total"] == 3
    assert len(state["failures"]) == 1
    assert "disk full" in state["failures"][0]


def test_incremental_replay():
    """增量重放：在已有状态上叠加新事件。"""
    p = SessionProjector()
    p.register(ProjectionSpec("count", 0, lambda s, e: s + 1))

    log1 = _make_log([
        {"event_type": "round/start", "round": 1},
        {"event_type": "step/observe/end", "round": 1},
    ])
    base = p.project(log1)  # count=2

    log2 = _make_log([
        {"event_type": "step/act/end", "round": 1},
    ])
    updated = p.replay_incremental(log2.events, base)
    assert updated["count"] == 3


def test_spec_replace():
    """同名注册覆盖旧规约。"""
    p = SessionProjector()
    p.register(ProjectionSpec("x", 0, lambda s, e: s + 1))
    p.register(ProjectionSpec("x", 100, lambda s, e: s + 10))

    log = _make_log([{"event_type": "round/start", "round": 1}])
    state = p.project(log)
    assert state["x"] == 110  # 100 + 10


def test_remove_spec():
    """移除规约后不再重放。"""
    p = SessionProjector()
    p.register(ProjectionSpec("a", 0, lambda s, e: s + 1))
    p.register(ProjectionSpec("b", 0, lambda s, e: s + 1))
    p.remove("a")

    log = _make_log([{"event_type": "round/start", "round": 1}])
    state = p.project(log)
    assert "a" not in state
    assert state["b"] == 1


def test_fold_error_isolated():
    """一个投影 fold 报错不影响其他投影。"""
    p = SessionProjector()
    p.register(ProjectionSpec("good", 0, lambda s, e: s + 1))
    p.register(ProjectionSpec("bad", 0, lambda s, e: 1 / 0))  # 必然除零

    log = _make_log([{"event_type": "round/start", "round": 1}])
    state = p.project(log)
    assert state["good"] == 1
    assert "bad" in state  # 保留了 initial_state=0


# ── 预置投影 ──

def test_default_projector_turn_count():
    """turn_count 投影正确。"""
    p = create_default_projector()
    log = _make_log([
        {"event_type": "round/start", "round": 1},
        {"event_type": "step/observe/end", "round": 1},
        {"event_type": "round/start", "round": 3},
        {"event_type": "step/act/end", "round": 3},
    ])
    state = p.project(log)
    assert state["turn_count"] == 3


def test_default_projector_failure_messages():
    """failure_messages 正确收集 FAIL 事件。"""
    p = create_default_projector()
    log = _make_log([
        {"event_type": "act/result", "round": 1, "status": "error",
         "error": "disk full"},
        {"event_type": "act/result", "round": 1, "status": "ok"},
        {"event_type": "act/result", "round": 2, "status": "error",
         "error": "timeout"},
    ])
    state = p.project(log)
    assert len(state["failure_messages"]) == 2


def test_default_projector_step_timeline():
    """step_timeline 保留最近 20 条。"""
    p = create_default_projector()
    events = [{"event_type": "step/observe/end", "round": i} for i in range(1, 25)]
    log = _make_log(events)
    state = p.project(log)
    assert len(state["step_timeline"]) <= 20


def test_default_projector_last_status():
    """last_status 反映最后一条事件。"""
    p = create_default_projector()
    log = _make_log([
        {"event_type": "step/observe/end", "round": 1},
        {"event_type": "act/result", "round": 1, "status": "error",
         "error": "boom"},
    ])
    state = p.project(log)
    assert state["last_status"]["status"] == "FAIL"


def test_default_projector_status_breakdown():
    """status_breakdown 统计正确。"""
    p = create_default_projector()
    log = _make_log([
        {"event_type": "step/observe/end", "round": 1},
        {"event_type": "act/result", "round": 1, "status": "error"},
        {"event_type": "act/result", "round": 1, "status": "ok"},
        {"event_type": "act/result", "round": 1, "status": "skipped"},
    ])
    state = p.project(log)
    bd = state["status_breakdown"]
    assert bd["PASS"] >= 1
    assert bd["FAIL"] >= 1
    assert bd["SKIP"] >= 1


def test_default_projector_error_categories():
    """error_categories 按错误消息分类。"""
    p = create_default_projector()
    log = _make_log([
        {"event_type": "act/result", "round": 1, "status": "error",
         "error": "disk full"},
        {"event_type": "act/result", "round": 1, "status": "error",
         "error": "disk full"},
        {"event_type": "act/result", "round": 1, "status": "error",
         "error": "timeout"},
    ])
    state = p.project(log)
    cats = state["error_categories"]
    assert any("disk full" in k for k in cats)
    assert sum(cats.values()) == 3


# ── 空日志 ──

def test_empty_log():
    """空日志重放 → 返回初始状态。"""
    p = create_default_projector()
    log = _make_log([])
    state = p.project(log)
    assert state["turn_count"] == 0
    assert state["failure_messages"] == []
    assert state["last_status"]["status"] == "UNKNOWN"


# ── spec_keys / get_spec ──

def test_spec_keys():
    p = create_default_projector()
    keys = p.spec_keys
    assert "turn_count" in keys
    assert "failure_messages" in keys
    assert "step_timeline" in keys
    assert "last_status" in keys
    assert "status_breakdown" in keys
    assert "error_categories" in keys


def test_get_spec():
    p = create_default_projector()
    spec = p.get_spec("turn_count")
    assert spec is not None
    assert spec.key == "turn_count"
    assert spec.initial_state == 0
    assert p.get_spec("nonexistent") is None
