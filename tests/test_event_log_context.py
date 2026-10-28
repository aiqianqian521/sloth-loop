"""Wave2 上下文可观察性 — ContextSnapshot 回归测试（零依赖，直接 python 跑 / 亦可 pytest）。"""
import json
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from event_log import EventLog, LoopEvent, ContextSnapshot, build_context_snapshot


def test_context_snapshot_to_dict_minimal():
    c = ContextSnapshot(context_type="observe")
    d = c.to_dict()
    assert d == {"context_type": "observe"}
    # 无敏感原文 / 无多余字段
    assert "input_hash" not in d
    assert "sources" not in d


def test_build_context_snapshot_hashes_deterministic():
    a = build_context_snapshot(context_type="act", input_data=[{"s": 1}, {"s": 2}],
                               config={"window": 48})
    b = build_context_snapshot(context_type="act", input_data=[{"s": 1}, {"s": 2}],
                               config={"window": 48})
    assert a.input_hash == b.input_hash
    assert a.config_hash == b.config_hash
    # 摘要一致但绝不等于原文
    assert a.input_hash != "[]"
    assert len(a.input_hash) == 16


def test_build_context_snapshot_strips_original_from_sources():
    c = build_context_snapshot(context_type="observe",
                               sources=[{"kind": "kline", "path": "data/x.csv",
                                         "summary": "276k bars"}])
    assert c.sources[0]["summary"] == "276k bars"
    # 仅记录摘要，不记录敏感正文
    assert "secret" not in json.dumps(c.to_dict())


def test_append_step_roundtrip_context_via_replay():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path, task_name="t")
        ctx = build_context_snapshot(context_type="decide",
                                     pattern_ids=[1, 2], correction_ids=[9],
                                     summary="2 candidates")
        e = log.append_step("decide", "PASS", "ok", round_num=1, ctx=ctx)
        assert e.ctx is not None and e.ctx.pattern_ids == [1, 2]

        # 重放后 ctx 还原
        r = log.replay()[0]
        assert r.ctx is not None
        assert r.ctx.context_type == "decide"
        assert r.ctx.pattern_ids == [1, 2]
        assert r.ctx.correction_ids == [9]
        assert r.ctx.summary == "2 candidates"


def test_old_events_without_ctx_still_replay():
    # 无 ctx 的旧日志行必须能正常重放（ctx=None）
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        log.append("step/observe", {"signals": 5})
        r = log.replay()[0]
        assert r.ctx is None
        assert r.step == "observe"


def test_append_accepts_ctx_in_data():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        e = log.append("act/result", {"status": "completed", "trades": 3,
                                      "ctx": {"context_type": "act",
                                              "input_hash": "abc"}})
        assert e.ctx is not None and e.ctx.context_type == "act"
        assert e.ctx.input_hash == "abc"
        # _type 兼容字段必须保留
        assert e.data.get("_type") == "act/result"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
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
