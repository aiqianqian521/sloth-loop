"""测试事件溯源会话 — v3.0 扁平结构回归测试。

原 test_event_log.py 引用旧 v2.0 DSH 信封 (type/time/data)。当前 event_log.py
为 v3.0 自包含扁平结构 (ts/task/round/step/status)，本文件重写断言以匹配真实 API，
同时保留原测试意图：事件创建、序列化、追加、重放、过滤、容错与完整 OODA 流。
零依赖，可 `python tests/test_event_log.py` 或 pytest 运行。
"""
import json
import sys
import tempfile
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from event_log import LoopEvent, EventLog, EventStatus


# ── LoopEvent 基本测试 ──

def test_loop_event_create_defaults():
    e = LoopEvent(ts="t", task="task", round=1, step="observe",
                  status="PASS", seq=1, time=1000.0)
    assert e.seq == 1
    assert e.time == 1000.0
    assert e.step == "observe"
    assert e.status == "PASS"
    assert e.data == {}
    assert e.ctx is None


def test_loop_event_to_dict_flat():
    e = LoopEvent(ts="t", task="task", round=1, step="observe",
                  status="PASS", message="in=10",
                  data={"signals_input": 10}, seq=1, time=1000.0)
    d = e.to_dict()
    assert d["step"] == "observe"
    assert d["status"] == "PASS"
    assert d["data"]["signals_input"] == 10
    # v3.0 无顶层 type 字段
    assert "type" not in d


def test_loop_event_to_dict_omits_empty():
    e = LoopEvent(ts="t", task="task", round=0, step="observe", status="PASS", seq=0)
    d = e.to_dict()
    assert "error" not in d
    assert "elapsed_ms" not in d
    assert "data" not in d
    assert "ctx" not in d


# ── EventLog 基本操作 ──

def test_event_log_append():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        e = log.append("round/start", {"round": 1})
        assert e.seq == 1
        assert log.count == 1
        assert path.exists()


def test_event_log_seq_increments():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        log.append("a")
        log.append("b")
        log.append("c")
        assert log.count == 3


def test_event_log_replay():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        log.append("step/observe", {"signals": 5})
        log.append("step/decide", {"action": "execute"})
        log.append("step/act", {"trades": 3})

        events = log.replay()
        assert len(events) == 3
        # v3: "step/observe" -> step="observe"；_type 保留旧 type 供过滤
        assert events[0].step == "observe"
        assert events[1].step == "decide"
        assert events[2].step == "act"
        assert events[0].data.get("_type") == "step/observe"


def test_event_log_replay_from_seq():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        for i in range(5):
            log.append(f"event_{i}")

        events = log.replay(from_seq=3)
        assert len(events) == 3
        assert events[0].seq == 3


def test_event_log_filter_by_type():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        log.append("step/observe")
        log.append("step/decide")
        log.append("step/observe")
        log.append("step/act")

        observes = log.filter("step/observe")
        assert len(observes) == 2
        assert all(e.data.get("_type") == "step/observe" for e in observes)


def test_event_log_replay_nonexistent_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "nonexistent" / "events.jsonl"
        log = EventLog(path)
        events = log.replay()
        assert events == []


def test_event_log_replay_empty_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        path.write_text("", encoding="utf-8")
        log = EventLog(path)
        events = log.replay()
        assert events == []


def test_event_log_replay_skips_invalid_json():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        path.write_text('not json\n{"seq":1,"time":1,"step":"ok","data":{}}\n', encoding="utf-8")
        log = EventLog(path)
        events = log.replay()
        assert len(events) == 1


def test_event_log_as_dicts():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        log.append("a", {"x": 1})
        log.append("b", {"y": 2})
        dicts = log.as_dicts()
        assert len(dicts) == 2
        assert dicts[0]["data"]["_type"] == "a"
        assert dicts[1]["data"]["_type"] == "b"


def test_event_log_path_property():
    p = Path("/tmp/test.jsonl")
    log = EventLog(p)
    assert log.path == p


# ── 完整 OODA 事件流模拟 ──

def test_full_ooda_event_flow():
    """模拟完整 OODA 循环的事件流。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)

        log.append("run/start", {"round": 1, "task": "test"})
        log.append("step/understand", {"complete": True})
        log.append("step/observe", {"signals_input": 10, "signals_excluded": 3})
        log.append("step/orient", {"severity": "moderate", "issue_count": 2})
        log.append("step/decide", {"action": "execute", "approach": "standard_backtest"})
        log.append("step/act", {"status": "completed", "trades": 5})
        log.append("step/verify", {"pass_count": 2, "total": 2})
        log.append("step/learn", {"new_failures": 1, "new_successes": 0})
        log.append("run/end", {"status": "ok"})

        assert log.count == 9

        # 重放 — 验证完整性
        events = log.replay()
        assert events[0].step == "run"
        assert events[-1].step == "run"

        # 按类型过滤 step 事件
        step_events = [e for e in events if e.data.get("_type", "").startswith("step/")]
        assert len(step_events) == 7  # understand to learn


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n结果: {passed} 通过, {len(fns)-passed} 失败")
    sys.exit(0 if passed == len(fns) else 1)
