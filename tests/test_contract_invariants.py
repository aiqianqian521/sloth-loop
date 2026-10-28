# -*- coding: utf-8 -*-
"""Contract-invariant test layer.

Purpose (docs/sloth-loop-架构基建规划-2026-09-03.md): encode sloth-loop's
stated architectural contracts as continuously-guaranteed assertions, so
contract drift (root cause in docs/sloth-loop-架构扫描-完整与根因-2026-09-03.md)
is caught by CI instead of by hand-re-scanning each round.

Five invariants (each guards a known breach family F/A/C/D):
  1. ExecGate is the single business-spawn chokepoint (F1/F2/F3)
  2. Every stop condition incl. token_budget has a real trigger path (A2)
  3. Unknown success_criteria metrics must never count as silent PASS (F6)
  4. EventLog writes are single-point / thread-safe and replay is lossless (C-1/C-2)
  5. run_fast and run_once share one archive/event semantic (D1/B2)

Method (先测后写): contracts that are **currently breached** are registered with
``pytest.xfail(reason=...)`` carrying the breach family + fix order; once fixed the
xfail path stops firing and the real assertion becomes the guard. Already-satisfied
contracts assert directly. These tests never mutate the repo.
"""
from __future__ import annotations

import re
import sys
import ast
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "sloth_engine"
SCRIPTS = ROOT / "scripts"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

def _repo_py_files():
    """Tracked + pending .py under sloth_engine/ and scripts/, no junk/archive.

    cycle-35 A: the sampler used rglob, so untracked scratch scripts
    (scripts/tmp/**, gitignored) counted as "business code" -- the check's
    verdict depended on whatever local junk happened to be lying around.  The
    domain is now the one the doc guard already uses: git's tracked + pending
    set (gitignored scratch excluded).
    """
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others",
         "--exclude-standard", "sloth_engine", "scripts"],
        capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    out = []
    for rel in listed:
        if not rel.endswith(".py"):
            continue
        parts = Path(rel).parts
        if "_archive" in parts or "tmp" in parts or "_tmp" in parts:
            continue
        out.append(ROOT / rel)
    return sorted(out)


_PY_FILES = _repo_py_files()


def _read(p):
    return p.read_text(encoding="utf-8")


# ---- helpers ---------------------------------------------------------------


def _spawn_sites():
    """(path, lineno, snippet) for every subprocess/os spawn call."""
    sites = []
    for path in _PY_FILES:
        try:
            tree = ast.parse(_read(path))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr = node.func.attr
            if attr not in {"run", "Popen", "call", "check_call", "check_output",
                            "system", "popen"}:
                continue
            src = ast.unparse(node.func)
            if "subprocess" in src or "sp." in src or "os." in src:
                sites.append((path, node.lineno, ast.unparse(node)[:110]))
    return sites


def _enclosing_refs(path, lineno):
    try:
        tree = ast.parse(_read(path))
    except Exception:
        return set()
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        if node.lineno <= lineno <= end:
            for n in ast.walk(node):
                if isinstance(n, ast.Name):
                    names.add(n.id)
                elif isinstance(n, ast.Attribute):
                    names.add(n.attr)
    return names


def _tokens_accrual_sites():
    """Return repo-relative paths that accumulate tokens_used."""
    out = []
    for path in _PY_FILES:
        txt = _read(path)
        if re.search(r"tokens_used\s*(?:\+=|-=|\*=|\^=)", txt):
            out.append(str(path.relative_to(ROOT)))
    return out


# Invariant 1 : ExecGate single business-spawn chokepoint (F1/F2/F3) ----------
#
# cycle-35 A: the old rule exempted a spawn *site* whenever the word "gate" /
# "ExecGate" / "_gate" / "assert_interpreter" appeared anywhere in the
# enclosing function.  Naming the gate is not going through it -- a probe that
# merely takes a `gate` argument and then calls bare subprocess.run was
# exempted -- and, worse, the rule *hid* real bypasses: the backtest adapter's
# `if exec_gate is not None: ... else: subprocess.run(...)` fallback and the
# callback/regression spawns in ooda_pipeline were all "green by name".
# "Guarded" is now a registered fact: only the gate implementation may spawn,
# plus an explicit, reasoned list of files outside the business-spawn domain.
# Every registration must stay load-bearing (it must still match a spawn site)
# or the check fails closed -- registrations may not rot silently (cycle-23
# family).
SPAWN_SANCTIONED = {
    "sloth_engine/runtime_exec.py":
        "the ExecGate implementation itself -- the one sanctioned spawn",
}
SPAWN_OUTSIDE_GATE = {
    "sloth_engine/self_modify_gate.py":
        "bootstrapping: the self-modify gate must not depend on the code it "
        "stages/tests (it runs pytest against its own sandbox copy)",
    "scripts/run_gate.py":
        "host release gate: runs git/pytest for the developer, not a business spawn",
    "scripts/audit_cross_repo_ledger.py":
        "host forensic tool: runs git, not a business spawn",
    "scripts/push_gate.py":
        "host fail-closed push gate: runs git archive and the local gate on the "
        "receiving host, not a business spawn",
    "scripts/install_push_gate.py":
        "host installer for the push gate: writes hooks and pins core.hooksPath, "
        "not a business spawn",
}


def unguarded_spawn_rows(sites):
    """Rows whose file is neither the gate nor a registered outside-domain tool."""
    known = set(SPAWN_SANCTIONED) | set(SPAWN_OUTSIDE_GATE)
    return ["%s:%s: %s" % (p.relative_to(ROOT).as_posix(), lineno, snippet)
            for p, lineno, snippet in sites
            if p.relative_to(ROOT).as_posix() not in known]


def _unguarded_spawns():
    return unguarded_spawn_rows(_spawn_sites())


def test_invariant_1_spawn_goes_through_execgate():
    """Only the gate (and registered outside-domain tools) may spawn (F1)."""
    unguarded = _unguarded_spawns()
    if unguarded:
        pytest.xfail(
            "invariant-1 breached (F1): %d bare business spawn(s) bypass "
            "ExecGate (no guardian check, no scrub_env, no output cap) - %s. "
            "Fix order P0: route each through ExecGate.run/popen, or make "
            "exec_gate mandatory (fail-closed) the way OODASteps._act already "
            "is; remove xfail once guarded."
            % (len(unguarded), "; ".join(unguarded)))
    assert unguarded == [], "exec-gate single-exit contract violated"


def test_invariant_1_registrations_are_load_bearing():
    """Every registered file must still contain a spawn site.

    A registration is a claim: if the file stops spawning (or is renamed) the
    claim is stale and must be removed -- it may not rot silently.
    """
    seen = {}
    for p, _lineno, _snippet in _spawn_sites():
        rel = p.relative_to(ROOT).as_posix()
        seen[rel] = seen.get(rel, 0) + 1
    for rel in list(SPAWN_SANCTIONED) + list(SPAWN_OUTSIDE_GATE):
        assert rel in seen, (
            "registered spawn file %r no longer contains a spawn site -- the "
            "registration is stale" % rel)


def test_invariant_1_exemption_is_not_name_level():
    """Mentioning the gate must not exempt a bare spawn (cycle-35 A).

    The judged object is the *file*, not the shape of the names inside it, so a
    row from a non-registered file is unguarded no matter what it mentions.
    """
    fake = ROOT / "scripts" / "_c35_probe_nonexistent.py"
    rows = unguarded_spawn_rows([
        (fake, 4, "subprocess.run(cmd) in a function that only says gate")])
    assert rows, "naming the gate must not exempt a bare spawn"


def test_invariant_1_sampling_domain_is_git_tracked_only():
    """No gitignored scratch or archived file may enter the sampled domain."""
    for p in _PY_FILES:
        rel = p.relative_to(ROOT).as_posix()
        assert "scripts/tmp/" not in rel, rel
        assert "_archive" not in rel, rel
    assert len(_PY_FILES) > 20, "the sampled domain collapsed to %d files" % len(_PY_FILES)


# Invariant-1 companion (cycle-35 A): the MCP client's server spawn must go
# through the gate.  Without a gate the client refuses to spawn (fail-closed).


class _FakeProc:
    def __init__(self, hello: bool = True):
        import io
        import json
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            (json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n")
            if hello else "")
        self.stderr = io.StringIO()
        self.returncode = 0

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class _FakeGate:
    def __init__(self, proc):
        self.proc = proc
        self.calls = []

    def popen(self, cmd, *, cwd=None, env=None, encoding="utf-8"):
        self.calls.append(list(cmd))
        return self.proc


def test_mcp_client_spawns_only_through_the_gate():
    import mcp_client
    proc = _FakeProc()
    gate = _FakeGate(proc)
    client = mcp_client.MCPClient(gate)
    client.connect(["python", "server.py"], timeout_start=0.05)
    assert gate.calls == [["python", "server.py"]], gate.calls
    assert client._proc is proc
    client.disconnect()


def test_mcp_client_without_a_gate_refuses_to_spawn():
    import mcp_client
    client = mcp_client.MCPClient(None)
    try:
        client.connect(["python", "server.py"], timeout_start=0.05)
    except Exception as exc:
        assert "gate" in str(exc).lower(), exc
    else:
        raise AssertionError("an ungated MCP spawn must be refused (fail-closed)")


# Invariant 2 : every stop condition has a real trigger path (A2) --------------


def test_invariant_2_token_budget_has_real_accrual():
    """token_budget is *dead* while tokens_used never accumulates (A2)."""
    accrual = _tokens_accrual_sites()
    if not accrual:
        pytest.xfail(
            "invariant-2 breached (A2): `tokens_used` has no accumulation site, "
            "so `token_budget` exhaustion is a dead stop condition (run_loop.py:244 / "
            "circuit_state.py:154). Fix order P1; remove xfail once a real accrual path."
        )
    assert accrual, "token_budget stop condition must have a real accrual path"


# Invariant 3 : unknown metric must never count as silent PASS (F6) ------------


def test_invariant_3_verifier_surfaces_unknown_metric():
    """Unresolvable success_criteria metric must be surfaced, never silent PASS (F6)."""
    from verifier import Verifier
    act = {"status": "completed", "trades": [],
           "metrics": {"sharpe": 1.0, "win_rate": 0.5}}
    sc = [{"metric": "definitely_not_a_metric_xyz", "operator": "gte", "threshold": 1}]
    r = Verifier.verify(act, sc)
    if r.get("unknown", 0) > 0 and r.get("fail_count", 0) == 0:
        pytest.xfail(
            "invariant-3 breached (F6): verifier returns unknown>0 & fail_count==0 "
            "for an unresolvable metric; consumer (ooda_pipeline.py:782-783) does "
            "not treat unknown as a failure -> silent false-PASS. Fix order P1."
        )
    assert r.get("unknown", 0) == 0, "unknown metric must not be silently ignored"


# Invariant 4 : EventLog single-point / thread-safe + lossless replay (C-1/C-2) 


def test_invariant_4a_eventlog_replay_is_lossless():
    """Append N events then replay returns exactly N in order (fact-store contract)."""
    from event_log import EventLog
    with tempfile.TemporaryDirectory(prefix="loop-inv4-") as td:
        el = EventLog(Path(td) / "events.jsonl", task_name="inv4")
        for i in range(20):
            el.append("inv4_probe", {"i": i, "msg": "event" + str(i)})
        replayed = el.replay()
        assert len(replayed) == 20, "replay must be lossless (got %d/20)" % len(replayed)


def test_invariant_4b_eventlog_writes_are_single_point():
    """All EventLog append-writes must funnel through one _write_event exit (C-1)."""
    src = _read(ENGINE / "event_log.py")
    append_writes = src.count("open(self._path, \"a\"")
    if append_writes > 1:
        pytest.xfail(
            "invariant-4 breached (C-1/C-2): EventLog has multiple append-open "
            "write exits without a single locked _write_event; concurrent append can "
            "tear JSONL and replay silently skips. Fix order P1; one _write_event "
            "behind a thread lock."
        )
    assert append_writes <= 1, "event log writes must be single-point"


# Invariant 5 : run_once / run_fast share one archive semantic (D1/B2) ---------


def test_invariant_5_single_archive_entrypoint():
    """run_once & run_fast must converge on one _archive_run sink (D1/B2)."""
    orch = _read(ENGINE / "orchestrator.py")
    ronce = _read(ENGINE / "run_once_pipeline.py")
    state = _read(ENGINE / "run_state.py")
    arc_in_orch = "_archive_run" in orch
    arc_in_once = "_archive_run" in ronce or "run_fast" in ronce
    arc_in_state = "_archive_run" in state
    single_sink = arc_in_state and (arc_in_orch or arc_in_once)
    assert single_sink, (
        "archive must route through a single _archive_run entrypoint shared by "
        "run_once & run_fast (D1)"
    )


# Invariant 1b/1c : behavior companions to invariant-1 (AST heuristic blind spot).
# An enclosing function that merely *mentions* exec_gate can still bare-spawn in a
# branch. These exercise the exec.type=="script" branch (F1 critical site,
# ooda_pipeline.py) via monkeypatched subprocess.run (zero real spawn) to prove:
#   1b) exec_gate=None  -> fail-closed error, subprocess.run NEVER called
#   1c) exec_gate given  -> routes through gate.run, subprocess.run NEVER called


def _f1_ok_proc():
    """CompletedProcess-like stand-in returned by the monkeypatched subprocess.run."""
    from types import SimpleNamespace
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_invariant_1b_script_branch_fail_closed_without_exec_gate(monkeypatch):
    """exec.type=='script' with no ExecGate must fail-closed, never bare spawn (F1)."""
    import subprocess
    from ooda_pipeline import OODASteps
    spawned = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: spawned.append(a) or _f1_ok_proc())
    decision = {"action": "execute"}
    task_cfg = {"execution": {"type": "script", "entry": "echo loopf1"}, "name": "f1-probe"}
    res = OODASteps._act(decision, [], {}, None, task_cfg, registry=None, exec_gate=None)
    assert res["status"] == "error", \
        "exec_gate=None must fail-closed (F1), got status=%r" % (res.get("status"),)
    assert not spawned, \
        "exec_gate=None must NOT bare-spawn (F1), but subprocess.run was called: %r" % (spawned,)


def test_invariant_1c_script_branch_routes_through_exec_gate(monkeypatch):
    """exec.type=='script' with an ExecGate must call gate.run, not bare subprocess (F1)."""
    import subprocess
    from ooda_pipeline import OODASteps
    spawned = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: spawned.append(a) or _f1_ok_proc())
    calls = []

    class _FakeGate:
        def run(self, cmd, **kw):
            calls.append((cmd, kw))
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0, stdout="ok", stderr="",
                                   timed_out=False, truncated=False)

    decision = {"action": "execute"}
    task_cfg = {"execution": {"type": "script", "entry": "echo loopf1"}, "name": "f1-probe"}
    res = OODASteps._act(decision, [], {}, None, task_cfg, registry=None, exec_gate=_FakeGate())
    assert res["status"] == "completed", \
        "gate returncode 0 -> completed, got status=%r" % (res.get("status"),)
    assert len(calls) == 1, \
        "script branch must route through ExecGate.run exactly once (F1), got calls=%r" % (calls,)
    assert not spawned, \
        "must NOT bare-spawn when a gate is provided (F1), subprocess.run called: %r" % (spawned,)

def test_invariant_1d_script_branch_gate_deny_is_fail_closed(monkeypatch):
    """exec.type=='script' where ExecGate.run raises -> fail-closed error, never bare spawn (F1)."""
    import subprocess
    from ooda_pipeline import OODASteps
    spawned = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: spawned.append(a) or _f1_ok_proc())

    class _DenyGate:
        def run(self, cmd, **kw):
            raise RuntimeError("interpreter denied by allow-list")

    decision = {"action": "execute"}
    task_cfg = {"execution": {"type": "script", "entry": "echo loopf1"}, "name": "f1-probe"}
    res = OODASteps._act(decision, [], {}, None, task_cfg, registry=None, exec_gate=_DenyGate())
    assert res["status"] == "error", \
        "gate deny must surface as fail-closed error (F1), got status=%r" % (res.get("status"),)
    assert not spawned, \
        "must NOT bare-spawn when gate denies (F1), subprocess.run called: %r" % (spawned,)
    tr = res.get("task_result")
    code = None
    if hasattr(tr, "execution"):
        code = (tr.execution or {}).get("code") if isinstance(tr.execution, dict) else getattr(tr.execution, "code", None)
    elif isinstance(tr, dict):
        code = (tr.get("execution") or {}).get("code")
    assert code == "exec_gate_exception", "expected exec_gate_exception code, got %r" % (code,)


# Invariant 4c : concurrent append must be tear-free (C-1 P1 = _write_event behind a thread lock)
# 先测后写: 当前 _write_event 无锁 -> 多线程 append 时 _seq += 1 竞态(重复/丢 seq)、
# 并发 open("a") 撕裂行。修后(RLock) -> 全量无损、seq 连续唯一。inv-4b 注释即此 P1 ticket。


def test_invariant_4c_concurrent_append_is_tear_free():
    """C-1: 多线程并发 append 不得丢事件/重复 seq/撕裂行(需 _write_event behind a thread lock)."""
    import threading
    from event_log import EventLog
    with tempfile.TemporaryDirectory(prefix="loop-inv4c-") as td:
        path = Path(td) / "events.jsonl"
        el = EventLog(path, task_name="inv4c")
        N, W = 150, 8

        def worker():
            for i in range(N):
                el.append("inv4c_probe", {"i": i})

        threads = [threading.Thread(target=worker) for _ in range(W)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total = N * W
        replayed = el.replay()
        malformed = getattr(el, "_last_replay_malformed", 0)
        assert len(replayed) == total, (
            "C-1 concurrent tear: 期望 %d 事件, 实得 %d (malformed=%d) — "
            "_write_event 需 behind a thread lock" % (total, len(replayed), malformed))
        seqs = sorted(e.seq for e in replayed)
        assert seqs == list(range(1, total + 1)), (
            "C-1 seq 竞态: 重复/缺失 seq — _seq 自增与写入需同一锁内原子化, 前10: %r" % (seqs[:10],))


# Invariant 4d : replay 不得把残缺/坏行静默吞成 PASS (F6 同族 @replay)
# defensive-patterns "正交结果独立报告": 缺 status 的行不得默认 "PASS"(假成功);
# 坏 JSON 行不得静默计数为 0(掩盖完整性损失)。


def test_invariant_4d_replay_surfaces_incomplete_not_silent_pass():
    """F6@replay: 缺 status 行不得默认 PASS; 坏 JSON 行必须计数暴露(不得静默 0)."""
    from event_log import EventLog
    with tempfile.TemporaryDirectory(prefix="loop-inv4d-") as td:
        path = Path(td) / "events.jsonl"
        # 行1 合法; 行2 缺 status; 行3 坏 JSON
        path.write_text(
            '{"seq":1,"time":1,"ts":"t","task":"t","round":1,"step":"observe","status":"PASS","data":{}}\n'
            '{"seq":2,"time":1,"ts":"t","task":"t","round":1,"step":"observe","data":{}}\n'
            'not-json-at-all\n',
            encoding="utf-8")
        el = EventLog(path, task_name="inv4d", auto_load=False)
        events = el.replay()
        seq2 = [e for e in events if e.seq == 2]
        assert seq2, "缺 status 的行应仍保留(可溯源), 不得丢弃"
        assert seq2[0].status != "PASS", (
            "F6@replay: 缺 status 行被默认 PASS(假成功) — 应标 UNKNOWN 暴露残缺, got %r" % (seq2[0].status,))
        malformed = getattr(el, "_last_replay_malformed", 0)
        assert malformed >= 1, (
            "F6@replay: 坏 JSON 行被静默吞(malformed=0) — 必须计数暴露完整性损失, got %d" % (malformed,))


# Invariant 6 : E4 subagent 死契约 tripwire (gated on model layer; 不半自动接线)
# E4 产品化 subagent 依赖 loop 引入 model 层(gated 决策)。当前 EVT_SUB_TASK_* 登记
# 但无生产者、max_sub_agents 死 knob。本 invariant 锁定 gated 边界: 不得在 subagent
# 运行时层(subagent_spec 标"已实施")未落地前半自动接 EVT_SUB_TASK 生产者。


_SUBTASK_PRODUCER_RE = re.compile(r'\.(?:append|append_step)\s*\(\s*(?:["\']subtask/|EVT_SUB_TASK)')


def _subagent_spec_path():
    """Path to the subagent spec file (inv-6 read target; real file under sloth_engine/)."""
    return ROOT / "sloth_engine" / "subagent_spec.md"


def test_invariant_6_subagent_dead_contract_not_half_wired():
    """E4 tripwire: EVT_SUB_TASK 若出现生产者, subagent_spec 须标'已实施'(防半自动接线)."""
    import re
    producer_hits = []
    for path in _PY_FILES:
        txt = _read(path)
        if _SUBTASK_PRODUCER_RE.search(txt):
            producer_hits.append(str(path.relative_to(ROOT)))
    spec = _subagent_spec_path()
    spec_text = spec.read_text(encoding="utf-8") if spec.exists() else ""
    has_runtime_layer = "已实施" in spec_text
    if producer_hits and not has_runtime_layer:
        pytest.fail(
            "E4 契约漂移: EVT_SUB_TASK 生产者 %r 出现但 subagent_spec 未标'已实施' — "
            "E4 依赖 model 层 gated 决策, 不得半自动接线; 先落地运行时层再接生产者." % (producer_hits[:3],))
    # 当前 gated 状态(无生产者) -> tripwire 静默通过(锁定 dead 契约待 E4 触发)


def test_invariant_6b_detector_catches_variable_form_and_right_spec():
    """6b: assert inv-6 detector catches variable-form producer and points at the real spec path."""
    assert _SUBTASK_PRODUCER_RE.search('el.append(EVT_SUB_TASK_START, {"i": 1})'), (
        "inv-6 detector blind-spot: variable-form EVT_SUB_TASK_* producer escapes tripwire (half-wiring passes).")
    assert _subagent_spec_path().exists(), (
        "inv-6 path blind-spot: spec path missing -> has_runtime_layer vacuously False -> tripwire empty guard.")


# Invariant 7 : E3 gate 本地触发前缀须覆盖代码目录(防代码改动静默 SKIP)
# E3 fail-closed CI 是 ROADMAP gated P0(未触发不抢跑); 但本地 gate path-scoped 触发须
# 覆盖所有运行码目录(sloth_engine/ 、tests/ 、scripts/), 不得漏盖让代码改动静默 SKIP。


def test_invariant_7_gate_trigger_covers_code_dirs():
    """E3 tripwire: run_gate TRIGGER_PREFIXES 须含 sloth_engine/、tests/、scripts/(代码目录)."""
    import re
    gate_path = SCRIPTS / "run_gate.py"
    if not gate_path.exists():
        pytest.skip("run_gate.py 不存在")
    gate_src = _read(gate_path)
    m = re.search(r"TRIGGER_PREFIXES\s*=\s*[\(\[]([^)\]]*)[\)\]]", gate_src)
    assert m, "未找到 TRIGGER_PREFIXES 定义(scripts/run_gate.py)"
    prefixes = m.group(1)
    for required in ("sloth_engine", "tests", "scripts"):
        assert required in prefixes, (
            "E3: run_gate TRIGGER_PREFIXES 缺 '%s' — 该代码目录改动会静默 SKIP gate("
            "path-scoped 绕过面)" % (required,))


# Invariant 8 : 无 workspace 时缺陷报告不得落 runtime.root(仓库根)
# 归根: run_state._produce_defect_report 旧实现 `task_cfg.get('workspace') or
# self.runtime.root` —— 无 workspace 时直接拿 runtime.root（开发态 = 仓库根）
# 做 project_dir，把 IMPROVEMENTS.md 撞到仓库根（违反 CLAUDE.md §9.1）。同族
# 于 P2-1 report_util hardcode：报告输出逃出其指定目录）。修后显式离根。


def _defect_report_engine_src():
    return _read(ENGINE / "run_state.py")


def test_invariant_8_defect_report_never_uses_runtime_root_as_project_dir():
    """8: _produce_defect_report 不得把 runtime.root 当 project_dir(会落仓库根)。"""
    src = _defect_report_engine_src()
    assert 'self.task_cfg.get("workspace") or self.runtime.root' not in src, (
        "inv-8 回归: _produce_defect_report 又把 runtime.root 当 project_dir 回退了 — "
        "无 workspace 时会把 IMPROVEMENTS.md 撞到仓库根(CLAUDE.md §9.1 违反)。")
    assert '"projects"' in src and 'self.runtime.root)' in src, (
        "inv-8 缺失: 未找到无-workspace 时的显式离根落点。")


def test_invariant_8b_no_workspace_report_lands_off_root(tmp_path):
    """8b(伴生, 行为级): 无 workspace 时真跑 → 文件在 runtime.root/projects 下, 不在 root。"""
    from run_state import RunState

    class _Store:
        def load_failure_patterns(self):
            return [{"signal_pattern": "sig", "root_cause": "gbk decode error",
                     "solution": "use utf-8", "status": "open", "failure_mode": "encode"}]

    class _Runtime:
        root = tmp_path

    orch = object.__new__(RunState)
    orch.store = _Store()
    orch.runtime = _Runtime()
    orch.task_cfg = {"name": "t_inv8"}   # no workspace
    RunState._produce_defect_report(orch, {}, {}, {})
    assert not (tmp_path / "IMPROVEMENTS.md").exists(), (
        "inv-8b: 无 workspace 时 IMPROVEMENTS.md 仍落 runtime.root(仓库根)。")
    landed = list(tmp_path.rglob("IMPROVEMENTS.md"))
    assert len(landed) == 1, "inv-8b: 应恰好产出 1 份缺陷报告, 实为 %r" % (landed,)
    rel = landed[0].relative_to(tmp_path).as_posix()
    assert rel == "projects/t_inv8/IMPROVEMENTS.md", "inv-8b: 落点异常 %r" % rel


# --- cycle-36 A: the fail-closed half of the F1 contract ---------------------
# Making ExecGate the single chokepoint is only half the fix: a caller that
# forgets to inject the gate must also be refused, or the "single exit" degrades
# back into a name-level promise.  These cases pin the fail-closed behaviour of
# the adapter call points (plus the OODA callback/regression sinks).


def test_invariant_1e_backtest_adapter_without_gate_fails_closed(monkeypatch):
    """run_backtest(exec_gate=None) refuses to spawn, with an explicit code."""
    from adapters import backtest_adapter as ba

    spawned = []
    monkeypatch.setattr(ba.subprocess, "run",
                        lambda *a, **k: spawned.append(a) or None)

    settings = ba.configure({"script": str(ROOT / "backtest" / "mock_backtest.py")},
                            ROOT, io_dir=Path(tempfile.mkdtemp(prefix="c36-inv-")))
    res = ba.run_backtest(ba.BacktestInput(signals=[{"signal_pattern": "x"}]), settings)
    assert res.status == "error"
    assert res.error_code == "exec_gate_required", res.error_code
    assert spawned == [], "no gate must mean no spawn (F1)"


def test_invariant_1f_probe_provenance_without_gate_fails_closed(monkeypatch):
    """probe_provenance(exec_gate=None) returns None without spawning."""
    from adapters import backtest_adapter as ba

    spawned = []
    monkeypatch.setattr(ba.subprocess, "run",
                        lambda *a, **k: spawned.append(a) or None)
    settings = ba.configure({"script": str(ROOT / "backtest" / "mock_backtest.py")},
                            ROOT, io_dir=Path(tempfile.mkdtemp(prefix="c36-probe-")))
    assert ba.probe_provenance(settings) is None
    assert spawned == [], "no gate must mean no probe spawn (F1)"


def test_invariant_1g_ooda_sinks_without_gate_fail_closed():
    """callback / regression sinks refuse to spawn without any gate (F1)."""
    from ooda_pipeline import OODASteps

    ok, detail = OODASteps._run_callback(
        str(ENGINE / "runtime_paths.py"), {"trades": []}, runtime=None)
    assert ok is False and "gate" in detail.lower(), detail

    reg = OODASteps._verify_regression(
        {"tests": [str(ENGINE / "runtime_paths.py")]}, bar=None, runtime=None)
    assert reg["fail_count"] == 1, reg
    assert "gate" in reg["details"][0]["detail"].lower(), reg["details"]


def test_invariant_1h_orchestrator_wires_its_gate_to_every_spawn_owner():
    """Fail-closed is only honest if the composition root injects the gate.

    The orchestrator owns the run's ExecGate; the evolution bridge must resolve
    that same gate at call time, so an enabled evolution run cannot silently fall
    back to an ungated fitness backtest (F1).
    """
    import config_util
    import orchestrator as orch_mod
    from runtime_exec import ExecGate

    cfg = config_util.load_config(str(ENGINE / "config.yaml"), {})
    # Isolation (cycle-39 A): redirect only the DB path so this wiring
    # check cannot create sloth_engine/data/patterns.db inside the checkout.
    _iso = Path(tempfile.mkdtemp(prefix="loop-c39-inv-"))
    cfg.setdefault("memory", {})["sqlite_path"] = str(_iso / "patterns.db")
    orch = orch_mod.Orchestrator(cfg)
    assert isinstance(orch._exec_gate, ExecGate)
    provider = getattr(orch.evolution_bridge, "_exec_gate_source", None)
    assert provider is not None, "evolution bridge must be wired to the run gate"
    assert orch.evolution_bridge._current_gate() is orch._exec_gate
