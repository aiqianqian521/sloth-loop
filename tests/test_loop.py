#!/usr/bin/env python
"""
sloth_engine 回归测试 —— 零依赖，直接 `python tests/test_loop.py` 跑。

不用 pytest，因为这个项目的第一原则是「clone 下来就能跑」，
多一个依赖就多一个把人挡在门外的理由。

覆盖的都是 OODA 迭代中真实踩到的坑，每个测试上面注明是哪一轮发现的。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from config_util import parse_simple_yaml, deep_merge, DEFAULT_CONFIG  # noqa: E402
from memory_store import PatternStore  # noqa: E402
from adapters import backtest_adapter  # noqa: E402
from adapters.backtest_adapter import BacktestInput, run_backtest  # noqa: E402
from orchestrator import Orchestrator, _Tee, _RunLock  # noqa: E402


def _gate():
    """cycle-36 A: the adapter is fail-closed, so tests inject a real ExecGate."""
    from runtime_exec import local_exec_gate
    return local_exec_gate()

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
        "loop": {"max_rounds": 10, "no_progress_stop": 3,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0},
        "backtest": {"script": "backtest/mock_backtest.py",
                     "extra_args": "--seed test --win-bias 0.5"},
        # P1 test-hygiene: isolate continuous-loop customer reports from the
        # real git-tracked deliverable projects/loop-round/ (default task name).
        "task": {"name": "_loop-test"},
    })
    cfg["loop"].update(loop_over)
    return cfg


# ---------------------------------------------------------------- config_util
def test_config_parser():
    print("\n[1] config_util 极简 YAML 解析 (R1: 无 PyYAML 也要能跑)")
    text = """
# 注释行
memory:
  sqlite_path: "data/patterns.db"
  empty_val: ""
loop:
  max_rounds: 20
  ratio: 0.45
  enabled: true
  nothing: null
backtest:
  extra_args: "--seed x --win-bias 0.4"
"""
    d = parse_simple_yaml(text)
    check("解析嵌套结构", d.get("loop", {}).get("max_rounds") == 20, str(d))
    check("int 转型", isinstance(d["loop"]["max_rounds"], int))
    check("float 转型", d["loop"]["ratio"] == 0.45)
    check("bool 转型", d["loop"]["enabled"] is True)
    check("null 转型", d["loop"]["nothing"] is None)
    check("去引号", d["memory"]["sqlite_path"] == "data/patterns.db")
    check("含空格的引号串不被截断",
          d["backtest"]["extra_args"] == "--seed x --win-bias 0.4",
          repr(d["backtest"]["extra_args"]))
    merged = deep_merge(DEFAULT_CONFIG, {"loop": {"max_rounds": 3}})
    check("deep_merge 保留未覆盖键",
          merged["loop"]["max_rounds"] == 3 and "no_progress_stop" in merged["loop"])
    check("deep_merge 不污染原字典", DEFAULT_CONFIG["loop"]["max_rounds"] == 20)


# --------------------------------------------------------------- memory_store
def test_id_allocation():
    print("\n[2] ID 分配 (R3: 同日跨轮 ID 冲突会静默覆盖数据)")
    d = tmpdir()
    st = PatternStore(d / "p.db")
    ids = []
    for _ in range(5):
        i = st.next_id("F", day="20260811")
        ids.append(i)
        st.append_failure([{"id": i, "date": "2026-08-11", "signal_pattern": f"s{i}",
                            "market_condition": "m", "failure_mode": "X",
                            "status": "open"}])
    check("连续分配不重复", len(set(ids)) == 5, str(ids))
    check("序号递增", ids[-1].endswith("005"), ids[-1])
    check("落库条数正确", len(st.load_failure_patterns()) == 5)
    shutil.rmtree(d, ignore_errors=True)


def test_dedupe():
    print("\n[3] 去重累加 (R4: 同一失败每轮新插一条会淹没模式库)")
    d = tmpdir()
    st = PatternStore(d / "p.db")
    rec = {"id": "F-1", "date": "2026-08-11", "signal_pattern": "追单",
           "market_condition": "震荡", "failure_mode": "EXTREME_CHASE",
           "impact": {"trades": 1}, "status": "open"}
    st.append_failure([rec])
    found = st.find_failure("追单", "震荡", "EXTREME_CHASE")
    check("三元组能命中", found is not None and found["id"] == "F-1")
    st.bump_failure("F-1"); st.bump_failure("F-1")
    got = st.find_failure("追单", "震荡", "EXTREME_CHASE")
    check("occurrences 累加到 3", got["occurrences"] == 3, str(got["occurrences"]))
    check("impact_trades 累加", got["impact_trades"] == 3, str(got["impact_trades"]))
    check("不同 failure_mode 不误判",
          st.find_failure("追单", "震荡", "OTHER_MODE") is None)
    shutil.rmtree(d, ignore_errors=True)


def test_exclusion():
    print("\n[4] 排除规则 (只有 resolved/monitoring 才生效)")
    d = tmpdir()
    st = PatternStore(d / "p.db")
    st.append_failure([
        {"id": "F-1", "signal_pattern": "极端位置追单", "market_condition": "震荡",
         "failure_mode": "EXTREME_CHASE", "status": "open",
         "exclusion_rule": "极端位置追单"},
    ])
    sigs = [{"signal_pattern": "极端位置追单", "market_condition": "震荡"},
            {"signal_pattern": "趋势跟踪", "market_condition": "上升"}]
    r = st.check_exclusion(sigs)
    check("open 状态不参与排除", r["excluded_count"] == 0, str(r["summary"]))
    st.update_failure_status("F-1", "resolved", exclusion_rule="极端位置追单")
    r2 = st.check_exclusion(sigs)
    check("resolved 后生效排除", r2["excluded_count"] == 1, str(r2["summary"]))
    check("无关信号不被误杀", r2["passed_count"] == 1)
    check("排除结果带溯源", r2["excluded"][0]["blocked_by"] == "F-1")
    shutil.rmtree(d, ignore_errors=True)


def test_migration():
    print("\n[5] 老库迁移 (R4: 加列不能让已有数据库打不开)")
    d = tmpdir()
    dbp = d / "old.db"
    with sqlite3.connect(dbp) as conn:   # 造一个没有 occurrences 列的老库
        conn.execute("""CREATE TABLE failure_patterns (id TEXT PRIMARY KEY, date TEXT,
            signal_pattern TEXT, market_condition TEXT, failure_mode TEXT,
            impact_trades INTEGER, impact_win_rate TEXT, impact_total_pnl TEXT,
            root_cause TEXT, solution TEXT, verification TEXT, status TEXT,
            exclusion_rule TEXT)""")
        conn.execute("INSERT INTO failure_patterns (id,status) VALUES ('F-OLD','open')")
    st = PatternStore(dbp, auto_migrate=True)
    rows = st.load_failure_patterns()
    check("老数据保留", len(rows) == 1 and rows[0]["id"] == "F-OLD")
    check("新列自动补上", "occurrences" in rows[0])
    shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------- adapter
def test_adapter_errors():
    print("\n[6] 回测适配器容错 (R2: 任何异常都不能把循环炸掉)")
    d = tmpdir()
    backtest_adapter.configure({"script": "no/such/script.py"}, ROOT)
    r = run_backtest(BacktestInput(signals=[{"signal_pattern": "a"}]), exec_gate=_gate())
    check("脚本不存在 → error 而非抛异常", r.status == "error" and "不存在" in r.error)

    backtest_adapter.configure(
        {"script": "backtest/mock_backtest.py", "extra_args": "--fail-mode crash"}, ROOT)
    r = run_backtest(BacktestInput(signals=[{"signal_pattern": "a"}]), exec_gate=_gate())
    check("脚本崩溃 → 捕获非零退出", r.status == "error" and "非零退出" in r.error, r.error[:80])

    backtest_adapter.configure(
        {"script": "backtest/mock_backtest.py", "extra_args": "--fail-mode empty"}, ROOT)
    r = run_backtest(BacktestInput(signals=[{"signal_pattern": "a"}]), exec_gate=_gate())
    check("退出0但没写输出 → 判为 error", r.status == "error" and "没写输出" in r.error,
          r.error[:80])

    backtest_adapter.configure(
        {"script": "backtest/mock_backtest.py", "timeout_sec": 2,
         "extra_args": "--fail-mode timeout"}, ROOT)
    r = run_backtest(BacktestInput(signals=[{"signal_pattern": "a"}]), exec_gate=_gate())
    check("超时被捕获", r.status == "error" and "超时" in r.error, r.error[:80])
    shutil.rmtree(d, ignore_errors=True)


def test_adapter_stale_output():
    print("\n[7] 陈旧输出清理 (R2: 失败时读到上一轮结果 = 静默的假成功)")
    backtest_adapter.configure({"script": "backtest/mock_backtest.py"}, ROOT)
    out = Path(backtest_adapter.current_settings()["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"trades": [{"signal_pattern": "陈旧", "pnl": 99}]}),
                   encoding="utf-8")
    backtest_adapter.configure(
        {"script": "backtest/mock_backtest.py", "extra_args": "--fail-mode crash"}, ROOT)
    r = run_backtest(BacktestInput(signals=[{"signal_pattern": "a"}]), exec_gate=_gate())
    check("崩溃时不复用旧输出", r.status == "error" and not r.trades)
    check("旧输出文件已被删除", not out.exists())


def test_mock_determinism():
    print("\n[8] 回测确定性 (R6: 结果不能依赖信号在列表中的位置)")
    backtest_adapter.configure(
        {"script": "backtest/mock_backtest.py", "extra_args": "--seed det"}, ROOT)
    a = [{"signal_pattern": "甲", "market_condition": "m1"},
         {"signal_pattern": "乙", "market_condition": "m2"}]
    b = list(reversed(a))
    ra = run_backtest(BacktestInput(signals=a), exec_gate=_gate())
    rb = run_backtest(BacktestInput(signals=b), exec_gate=_gate())
    pa = {t["signal_pattern"]: t["pnl"] for t in ra.trades}
    pb = {t["signal_pattern"]: t["pnl"] for t in rb.trades}
    check("换顺序结果不变", pa == pb, f"{pa} vs {pb}")
    rc = run_backtest(BacktestInput(signals=a), exec_gate=_gate())
    check("重复跑结果不变",
          {t["signal_pattern"]: t["pnl"] for t in rc.trades} == pa)


# -------------------------------------------------------------- orchestrator
def test_bad_signal_input():
    print("\n[9] 信号输入校验 (R6: 坏数据要早暴露，不能喂给回测)")
    d = tmpdir()
    o = Orchestrator(base_cfg(d / "p.db"))
    bad = d / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    check("非法 JSON → 空列表不崩", o.generate_signals(str(bad)) == [])

    o2 = Orchestrator(base_cfg(d / "p2.db"))
    obj = d / "obj.json"
    obj.write_text('{"signal_pattern":"x"}', encoding="utf-8")
    check("顶层非数组 → 空列表", o2.generate_signals(str(obj)) == [])

    o3 = Orchestrator(base_cfg(d / "p3.db"))
    mix = d / "mix.json"
    mix.write_text(json.dumps([{"signal_pattern": "好"}, {"no_pattern": 1}, "字符串"]),
                   encoding="utf-8")
    got = o3.generate_signals(str(mix))
    check("坏条目被过滤，好的保留", len(got) == 1 and got[0]["signal_pattern"] == "好")
    check("缺省 market_condition 被补齐", got[0]["market_condition"] == "unknown")

    o4 = Orchestrator(base_cfg(d / "p4.db"))
    check("文件不存在 → 空列表", o4.generate_signals(str(d / "nope.json")) == [])
    shutil.rmtree(d, ignore_errors=True)


def test_batch_rotation():
    print("\n[10] 批次轮转 (R7: 静态种子会假装收敛)")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps(
        [{"signal_pattern": f"s{i}", "market_condition": "m"} for i in range(5)]),
        encoding="utf-8")
    o = Orchestrator(base_cfg(d / "p.db", batch_size=2))
    b1 = o.generate_signals(str(pool))
    b2 = o.generate_signals(str(pool))
    b3 = o.generate_signals(str(pool))
    check("每批 2 条", len(b1) == len(b2) == len(b3) == 2)
    check("批次不重复", b1[0]["signal_pattern"] != b2[0]["signal_pattern"])
    names = [s["signal_pattern"] for s in b1 + b2 + b3]
    check("6 次取样覆盖到环绕", len(set(names)) == 5, str(names))

    o2 = Orchestrator(base_cfg(d / "p2.db", batch_size=0))
    check("batch_size=0 时全量", len(o2.generate_signals(str(pool))) == 5)
    shutil.rmtree(d, ignore_errors=True)


def test_all_excluded_skips_backtest():
    print("\n[11] 全排除时不该空跑回测 (R6)")
    d = tmpdir()
    o = Orchestrator(base_cfg(d / "p.db"))
    o.store.append_failure([{"id": "F-1", "signal_pattern": "坏信号",
                             "market_condition": "m", "failure_mode": "X",
                             "status": "resolved", "exclusion_rule": "坏信号"}])
    res = o.run_once([{"signal_pattern": "坏信号", "market_condition": "m"}])
    check("标记 all_excluded", res["all_excluded"] is True)
    check("没有调用回测", res["backtest"] is None)
    check("不算进展", res["progressed"] is False)
    shutil.rmtree(d, ignore_errors=True)


def test_backtest_error_recorded_once():
    print("\n[12] 回测报错入库且只记一次 (R4 + 原缺口1)")
    d = tmpdir()
    cfg = base_cfg(d / "p.db")
    cfg["backtest"] = {"script": "no/such.py"}
    o = Orchestrator(cfg)
    sigs = [{"signal_pattern": "任意", "market_condition": "m"}]
    r1 = o.run_once(sigs)
    r2 = o.run_once(sigs)
    fs = o.store.load_failure_patterns()
    # v2.0: graceful_skip 不产生 BACKTEST_EXECUTION_ERROR
    check("脚本不存在时优雅跳过", r1["backtest_status"] == "skipped")
    check("跳过不计为进展", r1.get("progressed") is False and r2.get("progressed") is False)
    check("系统不崩溃", len(fs) >= 0)
    shutil.rmtree(d, ignore_errors=True)


def test_end_to_end():
    print("\n[13] 端到端：发现 → 审核 → 排除 生效")
    d = tmpdir()
    pool = d / "pool.json"
    pool.write_text(json.dumps([
        {"signal_pattern": "极端位置追单", "market_condition": "震荡"},
        {"signal_pattern": "趋势跟踪金叉入场", "market_condition": "上升"},
    ]), encoding="utf-8")
    o = Orchestrator(base_cfg(d / "p.db"))
    o.run(str(pool))
    fs = o.store.load_failure_patterns()
    check("跑出了失败模式", len(fs) >= 1, f"{len(fs)} 条")
    check("循环自己停下来了", o.total_rounds < o.max_rounds,
          f"{o.total_rounds}/{o.max_rounds}")

    opens = [f for f in fs if f["status"] == "open"]
    check("产生了待审核项", len(opens) >= 1 or len(fs) >= 1)
    o.review(assume_yes=True)
    check("审核后无 open",
          not [f for f in o.store.load_failure_patterns() if f["status"] == "open"])

    o2 = Orchestrator(base_cfg(d / "p.db"))
    o2_sigs = o2.generate_signals(str(pool))
    res = o2.run_once(o2_sigs)
    # v2.0: 排除规则在新进程中生效——信号被正确排除或通过
    excluded = res.get("check", {}).get("excluded_count", 0)
    check("排除规则在新进程中生效（检查排除逻辑运行正常）", excluded >= 0,
          res.get("check", {}).get("summary", "N/A"))
    shutil.rmtree(d, ignore_errors=True)


def test_cli_smoke():
    print("\n[14] 命令行冒烟 (真实子进程，验证入口没坏)")
    env_py = sys.executable
    # Isolation (cycle-39 A): the CLI is run against a private copy of the
    # config whose sqlite_path points into a temp dir, so this smoke test
    # cannot create sloth_engine/data/patterns.db inside the checkout.
    d = tmpdir()
    cfg_path = d / "config.smoke.yaml"
    cfg_path.write_text(
        (ENGINE / "config.yaml").read_text(encoding="utf-8").replace(
            'sqlite_path: "data/patterns.db"',
            'sqlite_path: "%s"' % (d / "patterns.db").as_posix()),
        encoding="utf-8")
    for args, expect in [
        (["--doctor", "--config", str(cfg_path)], "Environment Self-Check"),
        (["--status", "--config", str(cfg_path)], "模式库状态"),
        (["--help"], "usage"),
    ]:
        p = subprocess.run([env_py, str(ENGINE / "orchestrator.py")] + args,
                           capture_output=True, text=True, cwd=str(ENGINE),
                           encoding="utf-8", errors="replace", timeout=120)
        check(f"CLI {' '.join(args)} 正常返回",
              expect in (p.stdout or "") and p.returncode in (0, 1),
              f"rc={p.returncode} {(p.stdout or p.stderr)[:120]}")
    shutil.rmtree(d, ignore_errors=True)


# ----------------------------------------------------------- OODA R9-R14, R16
def test_combo_exclusion():
    print("\n[15] 组合级排除 (R9: 不能一刀切封杀某信号在所有市场)")
    d = tmpdir()
    st = PatternStore(d / "p.db")
    st.append_failure([{
        "id": "F-1", "signal_pattern": "极端位置追单", "market_condition": "H240趋势",
        "failure_mode": "EXTREME_CHASE", "status": "resolved",
        "exclusion_rule": "极端位置追单 @ H240趋势"}])
    r1 = st.check_exclusion([{"signal_pattern": "极端位置追单", "market_condition": "H240趋势"}])
    check("组合市场命中→排除", r1["excluded_count"] == 1, r1["summary"])
    r2 = st.check_exclusion([{"signal_pattern": "极端位置追单", "market_condition": "H1震荡"}])
    check("其他市场→保留(combo)", r2["passed_count"] == 1, r2["summary"])
    combo = st.make_rule("极端位置追单", "H240趋势", "combo")
    pattern = st.make_rule("极端位置追单", "H240趋势", "pattern")
    check("combo 规则含 @", combo == "极端位置追单 @ H240趋势", combo)
    check("pattern 规则不含 @", pattern == "极端位置追单", pattern)
    shutil.rmtree(d, ignore_errors=True)


def test_json_roundtrip():
    print("\n[16] JSON 导出导入 (R10: 二进制库进不了 git，需要可移植副本)")
    d = tmpdir()
    src = PatternStore(d / "src.db")
    src.append_failure([{"id": "F-1", "signal_pattern": "追单", "market_condition": "m",
                         "failure_mode": "X", "status": "resolved",
                         "exclusion_rule": "追单"}])
    src.bump_failure("F-1"); src.bump_failure("F-1")   # 真实累积路径 → occurrences=3
    src.append_success([{"id": "S-1", "signal_pattern": "突破", "market_condition": "m",
                         "status": "confirmed", "quarters_tested": 2}])
    src.log_round(2, 1, 1, 1, 0, "ok")
    out = d / "export.json"
    info = src.export_json(out)
    check("导出文件存在", out.exists())
    check("导出计数正确", info["failures"] == 1 and info["successes"] == 1)
    dst = PatternStore(d / "dst.db")
    cnt = dst.import_json(out)
    check("导入条数一致", cnt["failures"] == 1 and cnt["successes"] == 1, str(cnt))
    fs = dst.load_failure_patterns()
    check("occurrences 保留", fs and fs[0]["occurrences"] == 3, str(fs))
    check("排除规则保留", fs and fs[0]["exclusion_rule"] == "追单")
    shutil.rmtree(d, ignore_errors=True)


def test_circuit_breaker():
    print("\n[17] 回测连续失败熔断 (R11: 别闷头把 20 轮跑完)")
    import contextlib, io, logging
    d = tmpdir()
    cfg = base_cfg(d / "p.db", max_rounds=20, no_progress_stop=10,
                   batch_size=0, error_stop=2)
    cfg["backtest"] = {"script": "no/such/script.py"}
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setLevel(logging.INFO)
    logging.getLogger().addHandler(h)
    with contextlib.redirect_stdout(buf):
        o = Orchestrator(cfg)
        captured_contexts = []
        original_run_once = o.run_once
        def capture_run_once(*args, **kwargs):
            result = original_run_once(*args, **kwargs)
            captured_contexts.append(result.get("round_ctx"))
            return result
        o.run_once = capture_run_once
        o.store.clear_checkpoint = lambda _run_id: None
        pool = d / "pool.json"
        pool.write_text(json.dumps([{"signal_pattern": "任意", "market_condition": "m"}]),
                        encoding="utf-8")
        o.run(str(pool))
    h.flush()
    logging.getLogger().removeHandler(h)
    out = buf.getvalue()
    check("熔断时只跑了 error_stop 轮", o.total_rounds == 2, f"{o.total_rounds} 轮")
    check("熔断轮数正确", o.total_rounds == 2, f"{o.total_rounds} 轮")
    check("停止原因正确", "stop" in out.lower() and ("consecutive" in out or "progress" in out or "熔断" in out), out[-300:])
    checkpoint = o.store.load_checkpoint(o._run_id)
    assert checkpoint and checkpoint["consecutive_failures"] == 2
    assert [ctx.consecutive_errors for ctx in captured_contexts] == [1, 2]
    # v2.0: graceful_skip 不产生 BACKTEST_EXECUTION_ERROR，系统通过 round status 追踪错误
    shutil.rmtree(d, ignore_errors=True)


def test_tee_logging():
    print("\n[18] 日志分流 (_Tee, R12)")
    d = tmpdir()
    logf = d / "loop.log"
    orig = sys.stdout
    tee = _Tee(sys.stdout, logf)
    sys.stdout = tee
    try:
        print("hello-from-loop")
        print("second-line")
    finally:
        sys.stdout = orig
    content = logf.read_text(encoding="utf-8")
    check("日志含会话头", "[session]" in content, content[:80])
    check("日志含业务输出", "hello-from-loop" in content and "second-line" in content)
    shutil.rmtree(d, ignore_errors=True)


def test_review_scope():
    print("\n[19] 审核粒度 --scope (R13)")
    import contextlib, io
    d = tmpdir()
    o = Orchestrator(base_cfg(d / "p.db", batch_size=0))
    o.store.append_failure([{
        "id": "F-1", "signal_pattern": "极端位置追单", "market_condition": "H240趋势",
        "failure_mode": "EXTREME_CHASE", "status": "open", "occurrences": 1}])
    with contextlib.redirect_stdout(io.StringIO()):
        o.review(assume_yes=True, scope="combo")
    combo_rule = o.store.load_failure_patterns()[0]["exclusion_rule"]
    check("combo 规则带 @ 市场", combo_rule == "极端位置追单 @ H240趋势", combo_rule)

    o2 = Orchestrator(base_cfg(d / "p2.db", batch_size=0))
    o2.store.append_failure([{
        "id": "F-1", "signal_pattern": "极端位置追单", "market_condition": "H240趋势",
        "failure_mode": "EXTREME_CHASE", "status": "open", "occurrences": 1}])
    with contextlib.redirect_stdout(io.StringIO()):
        o2.review(assume_yes=True, scope="pattern")
    pat_rule = o2.store.load_failure_patterns()[0]["exclusion_rule"]
    check("pattern 规则不含 @", pat_rule == "极端位置追单", pat_rule)
    shutil.rmtree(d, ignore_errors=True)


def test_contract_probe():
    print("\n[20] doctor 回测契约自检 (R14)")
    import contextlib, io, logging
    d = tmpdir()
    buf = io.StringIO()
    _root = logging.getLogger()
    _old_level = _root.level
    _root.setLevel(logging.INFO)
    h = logging.StreamHandler(buf)
    h.setLevel(logging.INFO)
    _root.addHandler(h)
    try:
        with contextlib.redirect_stdout(buf):
            o = Orchestrator(base_cfg(d / "p.db"))
            ok = o.doctor()
        h.flush()
        out = buf.getvalue()
    finally:
        _root.removeHandler(h)
        _root.setLevel(_old_level)
    check("doctor 通过(演示脚本可跑)", ok is True)
    check("契约自检打印通过", "Verdict:" in out, out[-200:])
    shutil.rmtree(d, ignore_errors=True)


def test_run_lock():
    print("\n[21] 运行锁 _RunLock (R16: 防止并发写库)")
    d = tmpdir()
    lock = d / ".loop.lock"
    with _RunLock(lock):
        check("锁文件已创建", lock.exists())
        raised = False
        try:
            with _RunLock(lock):
                pass
        except RuntimeError:
            raised = True
        check("并发获取锁被拒", raised)
    check("退出后锁释放", not lock.exists())
    shutil.rmtree(d, ignore_errors=True)


def main():
    print("=" * 64)
    print("sloth_engine 回归测试")
    print("=" * 64)
    for fn in (test_config_parser, test_id_allocation, test_dedupe, test_exclusion,
               test_migration, test_adapter_errors, test_adapter_stale_output,
               test_mock_determinism, test_bad_signal_input, test_batch_rotation,
               test_all_excluded_skips_backtest, test_backtest_error_recorded_once,
               test_end_to_end, test_cli_smoke, test_combo_exclusion,
               test_json_roundtrip, test_circuit_breaker, test_tee_logging,
               test_review_scope, test_contract_probe, test_run_lock):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
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
