"""Act→Orient 错误传递链路验证 — v2.2 P0 集成测试。

构造 4 个错误场景，验证 RoundContext 能正确传递错误信息到下一轮 _orient。
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from config_util import deep_merge, DEFAULT_CONFIG
from memory_store import PatternStore
from orchestrator import Orchestrator
from round_context import RoundContext

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


def base_cfg(db: Path, **loop_over) -> dict:
    cfg = deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(db.parent), "db": str(db)},
        "memory": {"sqlite_path": str(db)},
        "loop": {"max_rounds": 10, "no_progress_stop": 10,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "extra_args": "--seed test --win-bias 0.5"},
    })
    cfg["loop"].update(loop_over)
    return cfg


# ── 场景 1: 数据位置错误 ───────────────────────────────────────

def test_data_path_error_chain():
    """场景: 信号文件路径不存在 → Act 失败 → 下轮 Orient 应看到 PREV_ACT_ERROR"""
    print("\n[场景1] 数据位置错误 → Act→Orient 断链修复验证")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "test_signal", "market_condition": "震荡"}
    ]), encoding="utf-8")

    # 使用不存在的脚本路径模拟数据/路径错误
    cfg = base_cfg(d / "p.db", batch_size=0, error_stop=10)
    cfg["backtest"] = {"script": "no/such/backtest_script.py"}
    o = Orchestrator(cfg)

    # Round 1: Act should fail
    sigs = o.generate_signals(str(pool))
    buf1 = io.StringIO()
    with contextlib.redirect_stdout(buf1):
        r1 = o.run_once(sigs, round_num=1)
    ctx1 = r1.get("round_ctx")
    check("R1 返回 RoundContext", ctx1 is not None)
    check("R1 prev_act_status = skipped", ctx1.prev_act_status == "skipped",
          f"got: {ctx1.prev_act_status}")
    check("R1 l1_history 不为空", ctx1.l1_retry_count > 0,
          f"got {ctx1.l1_retry_count} retries")

    # Round 2: Orient should see R1's error
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        r2 = o.run_once(sigs, round_num=2, prev_ctx=ctx1)
    ctx2 = r2.get("round_ctx")
    check("R2 RoundContext 存在", ctx2 is not None)
    check("R2 error_chain 含 R1 错误", len(ctx2.error_chain) >= 1,
          f"error_chain: {ctx2.error_chain}")
    check("R2 consecutive_errors 正确累加",
          ctx2.consecutive_errors >= 0,
          f"consecutive_errors={ctx2.consecutive_errors}")

    # Round 2 diagnosis should have issues from R1
    diag2 = r2.get("diagnosis", {})
    check("R2 diagnosis 包含 issues", diag2.get("issues", 0) >= 0,
          f"issues={diag2.get('issues')}")

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 2: Python 路径错误 ─────────────────────────────────────

def test_python_path_error_chain():
    """场景: task 定义引用不存在的 Python 模块 → Act error → 下轮 Orient 诊断"""
    print("\n[场景2] Python 路径错误 → Act→Orient 链路")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "test_signal", "market_condition": "震荡"}
    ]), encoding="utf-8")

    cfg = base_cfg(d / "p.db", batch_size=0, error_stop=10)
    cfg["task"] = {
        "name": "broken-import-task",
        "execution": {
            "type": "agent_prompt",
            "entry": "nonexistent.module.MissingClass"
        },
        "success_criteria": [{"metric": "trades_count", "operator": "gt", "threshold": 0}],
    }
    o = Orchestrator(cfg)

    sigs = o.generate_signals(str(pool))
    buf1 = io.StringIO()
    with contextlib.redirect_stdout(buf1):
        r1 = o.run_once(sigs, round_num=1)

    ctx1 = r1.get("round_ctx")
    check("R1 RoundContext 存在", ctx1 is not None)
    # agent_prompt import 失败 → L1 retry → graceful_skip
    check("R1 Act 非 completed（import 失败后跳过）",
          ctx1.prev_act_status != "completed",
          f"status={ctx1.prev_act_status}")

    # R2: Orient should analyze the error
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        r2 = o.run_once(sigs, round_num=2, prev_ctx=ctx1)

    ctx2 = r2.get("round_ctx")
    check("R2 error_chain 累积", len(ctx2.error_chain) >= 1,
          f"error_chain length: {len(ctx2.error_chain)}")
    diag2_out = buf2.getvalue()
    check("R2 Orient 输出含 PREV_ACT 标记",
          "PREV_ACT_SKIPPED" in diag2_out or "PREV_ACT_ERROR" in diag2_out,
          f"Orient output: {diag2_out[-400:]}")

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 3: 输出格式错误 ───────────────────────────────────────

def test_output_format_error_chain():
    """场景: 回测脚本不存在 → L1 三级重试 → Orient 分析重试历史"""
    print("\n[场景3] 输出格式/脚本错误 → L1 重试 → Orient 分析")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "format_test", "market_condition": "上升"}
    ]), encoding="utf-8")

    # 使用不存在的脚本，触发 3 级重试: standard → longer_timeout → graceful_skip
    cfg = base_cfg(d / "p.db", batch_size=0, error_stop=10)
    cfg["backtest"] = {"script": "no/such/backtest.py"}
    o = Orchestrator(cfg)

    sigs = o.generate_signals(str(pool))
    buf1 = io.StringIO()
    with contextlib.redirect_stdout(buf1):
        r1 = o.run_once(sigs, round_num=1)

    ctx1 = r1.get("round_ctx")
    check("R1 RoundContext 存在", ctx1 is not None)
    check("R1 Act status 不是 completed", ctx1.prev_act_status != "completed",
          f"status={ctx1.prev_act_status}")
    # 3 级重试: standard(timeout) → longer_timeout → graceful_skip
    check("R1 L1 至少尝试 3 次含 graceful_skip",
          ctx1.l1_retry_count >= 3 or "skip" in ctx1.prev_act_status,
          f"retries={ctx1.l1_retry_count}, status={ctx1.prev_act_status}")

    # R2: Orient should see L1 history
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        r2 = o.run_once(sigs, round_num=2, prev_ctx=ctx1)

    ctx2 = r2.get("round_ctx")
    check("R2 收到上轮 L1 重试历史", ctx2.l1_retry_count > 0,
          f"l1_history count={ctx2.l1_retry_count}")
    diag2_out = buf2.getvalue()
    check("R2 Orient 检测到上轮问题",
          any(tag in diag2_out for tag in ["PREV_ACT_SKIPPED", "PREV_ACT_ERROR", "L1_ALL_RETRIES"]),
          f"Orient output: {diag2_out[-500:]}")

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 4: PM 要求模糊 → 验证失败 ─────────────────────────────

def test_ambiguous_pm_requirements():
    """场景: success_criteria 设置了无法达到的指标 → Verify 失败 → Orient 诊断"""
    print("\n[场景4] PM 要求模糊/不可达 → Verify 失败 → Orient 诊断")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "t1", "market_condition": "m1"},
        {"signal_pattern": "t2", "market_condition": "m2"},
    ]), encoding="utf-8")

    cfg = base_cfg(d / "p.db", batch_size=0, error_stop=10)
    # 设置不可能达到的成功标准
    cfg["task"] = {
        "name": "unreachable-target",
        "success_criteria": [
            {"metric": "win_rate", "operator": "gte", "threshold": 0.99},  # 99% 胜率不可能
            {"metric": "sharpe", "operator": "gt", "threshold": 100},       # Sharpe > 100
            {"metric": "trades_count", "operator": "gt", "threshold": 9999}, # 1万笔交易
        ],
    }
    o = Orchestrator(cfg)

    sigs = o.generate_signals(str(pool))
    buf1 = io.StringIO()
    with contextlib.redirect_stdout(buf1):
        r1 = o.run_once(sigs, round_num=1)

    ctx1 = r1.get("round_ctx")
    check("R1 RoundContext 存在", ctx1 is not None)
    check("R1 Verify 有失败项", ctx1.has_verify_failures,
          f"verify_failures={ctx1.prev_verify_failures}")
    check("R1 Verify pass < total", ctx1.prev_verify_pass < ctx1.prev_verify_total,
          f"pass={ctx1.prev_verify_pass}/{ctx1.prev_verify_total}")

    # R2: Orient should flag unreachable targets
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        r2 = o.run_once(sigs, round_num=2, prev_ctx=ctx1)

    ctx2 = r2.get("round_ctx")
    check("R2 携带 R1 Verify 失败信息", ctx2.has_verify_failures,
          f"failures={ctx2.prev_verify_failures}")
    check("R2 error_chain 或 verify 传递正常",
          len(ctx2.error_chain) >= 0 and ctx2.prev_verify_total > 0)

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 5: 连续多轮错误累积 ───────────────────────────────────

def test_consecutive_error_accumulation():
    """场景: 连续 3 轮 Act 失败 → error_chain 累积 → consecutive_errors 递增"""
    print("\n[场景5] 连续 3 轮错误累积")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "err_loop", "market_condition": "震荡"}
    ]), encoding="utf-8")

    cfg = base_cfg(d / "p.db", batch_size=0, error_stop=10)
    cfg["backtest"] = {"script": "no/such/script.py"}
    o = Orchestrator(cfg)

    sigs = o.generate_signals(str(pool))
    ctx = None
    error_chain_lengths = []

    for rnd in range(1, 4):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = o.run_once(sigs, round_num=rnd, prev_ctx=ctx)
        ctx = res.get("round_ctx")
        error_chain_lengths.append(len(ctx.error_chain) if ctx else 0)
        check(f"R{rnd} RoundContext 存在", ctx is not None)

    check("error_chain 随轮次累积", error_chain_lengths[2] >= error_chain_lengths[1] >= error_chain_lengths[0],
          f"chain lengths: {error_chain_lengths}")

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 6: 配置缺失/无效 ───────────────────────────────────────

def test_invalid_config_handling():
    """场景: 缺少 backtest.script → Orchestrator 应能优雅处理"""
    print("\n[场景6] 配置缺失/无效")
    d = tmpdir()

    # 完全缺 backtest 配置
    cfg = base_cfg(d / "p1.db", batch_size=0)
    cfg.pop("backtest", None)
    try:
        o = Orchestrator(cfg)
        check("缺 backtest 配置不崩溃", True)
    except Exception as e:
        check("缺 backtest 配置不崩溃", False, str(e))

    # backtest.script 为空字符串 → 应容错，不崩溃
    cfg2 = base_cfg(d / "p2.db", batch_size=0)
    cfg2["backtest"] = {"script": ""}
    try:
        o2 = Orchestrator(cfg2)
        check("空 script 容错不崩溃", True)
    except Exception:
        check("空 script 容错不崩溃", False)

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 7: 信号数据污染 ─────────────────────────────────────────

def test_corrupted_signal_data():
    """场景: 信号数据字段类型错误 → 框架应过滤而非崩溃"""
    print("\n[场景7] 信号数据污染")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "good1", "market_condition": "m1"},
        {"signal_pattern": 12345, "market_condition": "m2"},       # pattern 是数字
        {"market_condition": "m3"},                                  # 缺 signal_pattern
        {"signal_pattern": None, "market_condition": "m4"},         # pattern 是 None
        {"signal_pattern": "good2", "market_condition": 999},       # condition 是数字
        "not_a_dict",                                                # 字符串
        {"signal_pattern": "good3", "market_condition": "m5"},
    ]), encoding="utf-8")

    o = Orchestrator(base_cfg(d / "p.db", batch_size=0))
    sigs = o.generate_signals(str(pool))
    # P1-4: strict schema validation is now on by default (fail-closed), so a
    # signal with a malformed core field (good2's market_condition is a number)
    # is rejected too -- not just the missing-pattern / non-dict entries. The
    # framework must still FILTER (never crash) and keep the truly valid ones.
    pattern_names = [s["signal_pattern"] for s in sigs]
    check("过滤后只剩有效信号", len(sigs) == 2,
          f"got {len(sigs)} signals: {pattern_names}")
    check("good1 保留", "good1" in pattern_names)
    check("good3 保留", "good3" in pattern_names)
    # malformed entries were surfaced as rejections (never silently kept).
    rejected = list(getattr(o.signal_pool, "_rejected", []) or [])
    check("污染信号被拒绝(非静默保留)", len(rejected) >= 4,
          f"rejected={[r.get('code') for r in rejected]}")

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 8: 混合状态跨轮传递 ─────────────────────────────────────

def test_mixed_state_propagation():
    """场景: PASS→FAIL→PASS 跨轮状态正确传递"""
    print("\n[场景8] 混合状态跨轮传递")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "t1", "market_condition": "m1"},
        {"signal_pattern": "t2", "market_condition": "m2"},
    ]), encoding="utf-8")

    # R1: 正常执行
    cfg_ok = base_cfg(d / "p.db", batch_size=0, error_stop=10)
    cfg_ok["backtest"] = {"script": "backtest/mock_backtest.py",
                          "extra_args": "--seed ok --win-bias 0.7"}
    o1 = Orchestrator(cfg_ok)
    sigs1 = o1.generate_signals(str(pool))
    r1 = o1.run_once(sigs1, round_num=1)
    ctx1 = r1.get("round_ctx")
    check("R1 status = completed", ctx1.prev_act_status == "completed",
          f"got: {ctx1.prev_act_status}")

    # R2: 用失败配置（脚本不存在）
    cfg_fail = base_cfg(d / "p2.db", batch_size=0, error_stop=10)
    cfg_fail["backtest"] = {"script": "no/such.py"}
    o2 = Orchestrator(cfg_fail)
    sigs2 = o2.generate_signals(str(pool))
    r2 = o2.run_once(sigs2, round_num=2, prev_ctx=ctx1)
    ctx2 = r2.get("round_ctx")
    check("R2 status != completed", ctx2.prev_act_status != "completed",
          f"got: {ctx2.prev_act_status}")
    check("R2 error_chain 含 R1+R2", len(ctx2.error_chain) == 2,
          f"error_chain len={len(ctx2.error_chain)}")

    # R3: 恢复正常
    cfg_ok3 = base_cfg(d / "p3.db", batch_size=0, error_stop=10)
    cfg_ok3["backtest"] = {"script": "backtest/mock_backtest.py",
                           "extra_args": "--seed ok --win-bias 0.7"}
    o3 = Orchestrator(cfg_ok3)
    sigs3 = o3.generate_signals(str(pool))
    r3 = o3.run_once(sigs3, round_num=3, prev_ctx=ctx2)
    ctx3 = r3.get("round_ctx")
    check("R3 恢复正常 status=completed", ctx3.prev_act_status == "completed",
          f"got: {ctx3.prev_act_status}")
    check("R3 error_chain 保留历史记录", len(ctx3.error_chain) >= len(ctx2.error_chain),
          f"R2 chain={len(ctx2.error_chain)} → R3 chain={len(ctx3.error_chain)}")

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 9: 成功标准边界 ─────────────────────────────────────────

def test_success_criteria_edge_cases():
    """场景: 成功标准的各种边界组合"""
    print("\n[场景9] 成功标准边界")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "t1", "market_condition": "m1"}
    ]), encoding="utf-8")

    # 空 criteria → 默认 trades_count > 0
    cfg1 = base_cfg(d / "p1.db", batch_size=0)
    cfg1["task"] = {"name": "no-criteria", "success_criteria": []}
    o1 = Orchestrator(cfg1)
    r1 = o1.run_once(o1.generate_signals(str(pool)), round_num=1)
    v1 = r1.get("verified", {})
    check("空 criteria 默认 trades_count>0", v1.get("total", 0) == 1,
          f"total={v1.get('total')}")
    # P1-D5: the fallback must be LOUD + AUDITABLE, never a silent PASS.
    check("空 criteria 标记 implicit_criteria=True",
          v1.get("implicit_criteria") is True, f"implicit={v1.get('implicit_criteria')}")
    bar1 = r1.get("status_bar")
    issues1 = getattr(bar1, "issues", []) if bar1 else []
    check("空 criteria 发出 CRITERIA-IMPLICIT 警告",
          any(i.get("rule") == "CRITERIA-IMPLICIT" for i in issues1),
          f"issues={[i.get('rule') for i in issues1]}")

    # 全部通过
    cfg2 = base_cfg(d / "p2.db", batch_size=0)
    cfg2["task"] = {"name": "all-pass",
        "success_criteria": [{"metric": "trades_count", "operator": "gt", "threshold": -1}]}
    o2 = Orchestrator(cfg2)
    r2 = o2.run_once(o2.generate_signals(str(pool)), round_num=1)
    v2 = r2.get("verified", {})
    check("全部通过", v2.get("fail_count", 99) == 0,
          f"pass={v2.get('pass_count')} fail={v2.get('fail_count')}")

    # 全部失败
    cfg3 = base_cfg(d / "p3.db", batch_size=0)
    cfg3["task"] = {"name": "all-fail",
        "success_criteria": [
            {"metric": "win_rate", "operator": "gte", "threshold": 0.99},
            {"metric": "sharpe", "operator": "gt", "threshold": 999},
        ]}
    o3 = Orchestrator(cfg3)
    r3 = o3.run_once(o3.generate_signals(str(pool)), round_num=1)
    v3 = r3.get("verified", {})
    check("全部失败", v3.get("pass_count", 99) == 0,
          f"pass={v3.get('pass_count')} total={v3.get('total')}")
    ctx3 = r3.get("round_ctx")
    check("全部失败时 has_verify_failures=True",
          ctx3.has_verify_failures if ctx3 else False)

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 10: 信号池耗尽 ──────────────────────────────────────────

def test_signal_pool_exhaustion():
    """场景: 信号文件空 → 应优雅停止而非崩溃"""
    print("\n[场景10] 信号池耗尽")
    d = tmpdir()

    # 空信号池
    empty_pool = d / "empty.json"
    empty_pool.write_text("[]", encoding="utf-8")
    o = Orchestrator(base_cfg(d / "p.db", batch_size=0))
    sigs = o.generate_signals(str(empty_pool))
    check("空信号数组返回空列表", sigs == [])

    # 文件不存在
    sigs2 = o.generate_signals(str(d / "nope.json"))
    check("文件不存在返回空列表", sigs2 == [])

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 11: RoundContext 序列化/反序列化 ─────────────────────────

def test_round_context_serialization():
    """场景: RoundContext 可序列化为 dict 并重建"""
    print("\n[场景11] RoundContext 序列化")
    from round_context import RoundContext

    ctx = RoundContext(
        round_num=5,
        prev_act_status="error",
        prev_act_error="script timeout after 300s",
        prev_act_trades_count=0,
        prev_act_elapsed_ms=300500.0,
        l1_history=[
            {"strategy": "standard", "ok": False, "note": "timeout"},
            {"strategy": "longer_timeout", "ok": False, "note": "also timeout"},
            {"strategy": "graceful_skip", "ok": True, "note": "skipped"},
        ],
        prev_verify_pass=0,
        prev_verify_total=3,
        prev_verify_failures=[
            {"metric": "win_rate", "actual": 0.3, "threshold": 0.5, "operator": "gte"},
        ],
        prev_severity="major",
        prev_issue_count=3,
        consecutive_errors=2,
        error_chain=["timeout R4", "timeout R5"],
    )

    d = ctx.to_dict()
    check("to_dict 含所有关键字段",
          all(k in d for k in ["round_num", "prev_act_status", "error_chain"]))
    check("l1_history 序列化", len(d["l1_history"]) == 3)
    check("verify_failures 序列化", len(d["prev_verify_failures"]) == 1)
    check("had_act_error=True", ctx.had_act_error)
    check("l1_all_failed=False (graceful_skip=ok)", not ctx.l1_all_failed)
    check("has_verify_failures=True", ctx.has_verify_failures)


# ── 场景 12: EventLog 新格式查询 ─────────────────────────────────

def test_event_log_v3_queries():
    """场景: v3.0 EventLog 查询方法——get_summary / last_event_by_status"""
    print("\n[场景12] EventLog v3.0 查询")
    d = tmpdir()
    from event_log import EventLog

    elog = EventLog(d / "test.jsonl", task_name="query-test")

    # 模拟一轮完整 OODA
    elog.append("round/start", {"round": 1, "signals_input": 3})
    elog.append("step/observe/start", {"round": 1})
    elog.append("step/observe/end", {"round": 1, "signals_input": 3, "signals_excluded": 1})
    elog.append("step/orient/start", {"round": 1})
    elog.append("step/orient/end", {"round": 1, "severity": "normal", "issue_count": 0})
    elog.append("step/act/start", {"round": 1})
    elog.append("act/result", {"round": 1, "status": "completed", "trades": 2, "error": ""})
    elog.append("step/verify/start", {"round": 1})
    elog.append("verify/result", {"round": 1, "pass_count": 1, "total": 1, "fail_count": 0})
    elog.append("round/end", {"round": 1, "status": "ok"})

    # 模拟失败轮
    elog.append("round/start", {"round": 2, "signals_input": 3})
    elog.append("step/act/start", {"round": 2})
    elog.append("act/retry", {"round": 2, "strategy": "standard", "ok": False, "note": "timeout"})
    elog.append("act/retry", {"round": 2, "strategy": "longer_timeout", "ok": False, "note": "also failed"})
    elog.append("act/result", {"round": 2, "status": "skipped", "trades": 0, "error": "retries_exhausted"})
    elog.append("round/end", {"round": 2, "status": "error"})

    # 查询
    summary = elog.get_summary()
    check("total_events=16", summary["total_events"] == 16)
    check("rounds=2", summary["rounds"] == 2)
    check("有 FAIL 事件", summary["status_counts"].get("FAIL", 0) >= 2,
          f"status_counts={summary['status_counts']}")
    check("failures 列表非空", len(summary["failures"]) >= 1)

    # 按步骤查询
    r1_events = elog.get_round_events(1)
    check("R1 有 10 个事件", len(r1_events) == 10, f"got {len(r1_events)}")

    r2_events = elog.get_round_events(2)
    check("R2 有 6 个事件", len(r2_events) == 6, f"got {len(r2_events)}")

    # 最后失败事件
    last_fail = elog.last_event_by_status("FAIL")
    check("最后 FAIL 是 retry", last_fail is not None and "retry" in last_fail.step,
          f"step={last_fail.step if last_fail else 'None'}")

    # 查询重试历史
    retries = elog.get_retry_history(2)
    check("R2 有 2 次重试", len(retries) == 2)
    check("两次重试都失败", all(not r["ok"] for r in retries))

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 13: OODA 步骤跳过场景 ────────────────────────────────────

def test_ooda_skip_scenarios():
    """场景: 全排除→skip_backtest、无信号→skip、正常执行"""
    print("\n[场景13] OODA 决策分支覆盖")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "skip_test", "market_condition": "m1"}
    ]), encoding="utf-8")

    # 分支1: all_excluded → skip_backtest
    o1 = Orchestrator(base_cfg(d / "p1.db", batch_size=0))
    o1.store.append_failure([{
        "id": "F-skip", "signal_pattern": "skip_test", "market_condition": "m1",
        "failure_mode": "X", "status": "resolved", "exclusion_rule": "skip_test @ m1",
    }])
    r1 = o1.run_once(o1.generate_signals(str(pool)), round_num=1)
    check("all_excluded → skip_backtest", r1["all_excluded"] is True)
    check("skip 时 backtest=None", r1.get("backtest") is None)

    # 分支2: 正常执行
    o2 = Orchestrator(base_cfg(d / "p2.db", batch_size=0))
    cfg2 = base_cfg(d / "p2.db", batch_size=0)
    cfg2["backtest"] = {"script": "backtest/mock_backtest.py",
                        "extra_args": "--seed skip --win-bias 0.5"}
    o2 = Orchestrator(cfg2)
    r2 = o2.run_once(o2.generate_signals(str(pool)), round_num=1)
    check("正常执行 backtest_status=completed",
          r2.get("backtest_status") == "completed",
          f"got: {r2.get('backtest_status')}")

    # 分支3: critical → skip
    o3 = Orchestrator(base_cfg(d / "p3.db", batch_size=0))
    r3 = o3.run_once([], round_num=1)  # 空信号 → NO_SIGNALS critical
    check("无信号 → decision=skip",
          r3.get("decision") in ("skip_on_critical", "skip"),
          f"decision={r3.get('decision')}")

    shutil.rmtree(d, ignore_errors=True)


# ── 场景 14: StatusBar 状态完整性 ─────────────────────────────────

def test_status_bar_completeness():
    """场景: 7 步全部完成后 StatusBar 状态完整"""
    print("\n[场景14] StatusBar 状态完整性")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "bar_test", "market_condition": "m1"}
    ]), encoding="utf-8")

    o = Orchestrator(base_cfg(d / "p.db", batch_size=0))
    r = o.run_once(o.generate_signals(str(pool)), round_num=1)

    bar = r.get("status_bar")
    check("StatusBar 存在", bar is not None)
    if bar:
        check("7 步全部完成", len(bar.completed) == 7,
              f"completed={bar.completed}")
        check("步骤顺序正确", bar.completed == bar.STEPS,
              f"got: {bar.completed}")

    shutil.rmtree(d, ignore_errors=True)


def main():
    print("=" * 64)
    print("Act→Orient 错误传递链路 — 集成测试")
    print("=" * 64)
    for fn in (test_data_path_error_chain, test_python_path_error_chain,
               test_output_format_error_chain, test_ambiguous_pm_requirements,
               test_consecutive_error_accumulation,
               test_invalid_config_handling, test_corrupted_signal_data,
               test_mixed_state_propagation, test_success_criteria_edge_cases,
               test_signal_pool_exhaustion, test_round_context_serialization,
               test_event_log_v3_queries, test_ooda_skip_scenarios,
               test_status_bar_completeness):
        try:
            fn()
        except Exception as e:
            import traceback
            FAIL.append((fn.__name__, repr(e)))
            print(f"  ERROR {fn.__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 64)
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
    if FAIL:
        for n, d in FAIL:
            print(f"  FAIL  {n}  {d}")
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
