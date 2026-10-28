"""Wave2 本地 Trace Viewer + EventLog 自动加载 — 回归测试（零依赖）。"""
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from event_log import EventLog, build_context_snapshot
from trace_viewer import discover_logs, render_trace, _render_ctx, _esc


def test_discover_logs_finds_events():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        run = work / "runs-2026-08-26"
        run.mkdir()
        (run / "events-1.jsonl").write_text("", encoding="utf-8")
        logs = discover_logs(work)
        assert len(logs) == 1


def test_render_trace_contains_ctx():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        ctx = build_context_snapshot(context_type="verify",
                                     input_data={"criteria": [{"metric": "trades_count"}]},
                                     summary="verify 1/1 (0 failed)")
        log.append("verify/result", {"round": 1, "pass_count": 1, "total": 1,
                                     "ctx": ctx.to_dict()})
        html_out = render_trace([path], "T")
        assert "verify" in html_out
        assert "ctx" in html_out
        assert "input_hash" in html_out
        assert "1/1" in html_out


def test_render_ctx_omits_empty():
    assert _render_ctx(None) == ""
    assert _render_ctx({}) == ""


def test_render_ctx_sanitizes():
    out = _render_ctx({"context_type": "observe",
                       "input_hash": "a1", "sources": [{"path": "x"}]})
    assert "a1" in out
    assert "input_hash" in out


def test_esc_escapes_html():
    assert "&lt;" in _esc("<tag>")


def test_eventlog_autoload_on_ctor():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        log = EventLog(path)
        log.append("a", {"x": 1})
        log.append("b", {"x": 2})
        # fresh instance on same file should auto-load
        log2 = EventLog(path)
        assert log2.count == 2
        assert len(log2.events) == 2
        assert log2.as_dicts()[0]["data"]["_type"] == "a"


def test_autoload_continuation_seq():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        EventLog(path).append("a")
        log2 = EventLog(path)          # auto-loads seq up to 1
        e = log2.append("b")           # should continue from max seq
        assert e.seq == 2
        assert log2.count == 2          # max seq after append
        assert len(log2.events) == 2      # 1 loaded + 1 new


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
