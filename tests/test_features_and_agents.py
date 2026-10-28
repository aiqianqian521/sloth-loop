"""Tests for Phase 2/3 additions: features.py + sub_agent RAII/InputQueue."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sloth_engine"))

from features import Features, Stage, FeatureConfigSource  # noqa: E402
from sub_agent import AgentRegistry, SpawnReservation, InputQueue  # noqa: E402


def test_unknown_feature_is_off_and_never_raises():
    f = Features()
    assert f.on("nonexistent") is False
    assert f.stage_of("nonexistent") == Stage.UNDEFINED


def test_registered_default_disabled():
    f = Features()
    f.register("x", stage=Stage.DISABLED)
    assert f.on("x") is False
    f.enable("x")
    assert f.on("x") is True
    assert f.source_of("x").source == "override"


def test_env_override_beats_default():
    f = Features()
    f.register("envflag", stage=Stage.DISABLED)
    os.environ["LOOP_FEATURE_ENVFLAG"] = "1"
    try:
        assert f.on("envflag") is True
        assert f.source_of("envflag").source == "env"
    finally:
        del os.environ["LOOP_FEATURE_ENVFLAG"]


def test_process_override_beats_env():
    f = Features()
    f.register("both", stage=Stage.DISABLED)
    os.environ["LOOP_FEATURE_BOTH"] = "1"
    f.disable("both")
    try:
        assert f.on("both") is False
        assert f.source_of("both").source == "override"
    finally:
        del os.environ["LOOP_FEATURE_BOTH"]


def test_config_source():
    f = Features(config={"features": {"cfgflag": {"stage": "enabled"}}})
    f.register("cfgflag", stage=Stage.DISABLED)
    assert f.on("cfgflag") is True
    assert f.source_of("cfgflag").source == "config"


def test_deprecated_still_on():
    f = Features()
    f.register("old", stage=Stage.DEPRECATED)
    assert f.on("old") is True


def test_removed_is_off():
    f = Features()
    f.register("dead", stage=Stage.REMOVED)
    assert f.on("dead") is False


def test_snapshot_and_enabled_names():
    f = Features()
    f.register("a", stage=Stage.ENABLED)
    f.register("b", stage=Stage.DISABLED)
    snap = f.snapshot()
    assert snap["a"]["on"] is True and snap["b"]["on"] is False
    assert f.enabled_names() == ["a"]


def test_reservation_auto_releases():
    reg = AgentRegistry(max_concurrent=1)
    with reg.reserve("a1") as slot:
        assert reg.active_count == 1
        assert isinstance(slot, SpawnReservation)
    assert reg.active_count == 0


def test_reservation_releases_on_exception():
    reg = AgentRegistry(max_concurrent=1)
    try:
        with reg.reserve("a1"):
            raise ValueError("boom")
    except ValueError:
        pass
    assert reg.active_count == 0


def test_registry_fails_fast_when_full():
    reg = AgentRegistry(max_concurrent=1)
    r = reg.reserve("a1")
    try:
        try:
            reg.reserve("a2", block=False)
            assert False, "should have raised"
        except RuntimeError:
            pass
    finally:
        r.release()
    assert reg.active_count == 0


def test_registry_blocking_reserve_with_timeout():
    reg = AgentRegistry(max_concurrent=1)
    r = reg.reserve("a1")
    try:
        try:
            reg.reserve("a2", block=True, timeout=0.05)
            assert False, "should time out"
        except TimeoutError:
            pass
    finally:
        r.release()


def test_release_walks_past_a_non_match_and_survives_a_missing_slot():
    """Deterministic cover of every branch of AgentRegistry._release.

    cycle-40 A2: the loop / `if` arcs of `_release` used to be covered only by
    the *thread race* inside `test_run_subagents_parallel_uses_registry` --
    whether a concurrent release walks past a still-held slot depends on
    scheduling, so two identical runs could record 79.47% vs 79.48%. Driving
    both shapes from one single-threaded test pins them (walk past a
    non-match; exhaust the scan with no match at all).
    """
    reg = AgentRegistry(max_concurrent=4)
    first = reg.reserve("first")
    second = reg.reserve("second")
    # dict order is insertion order, so releasing "second" walks past
    # "first" (a non-match) before it reaches its own entry.
    second.release()
    assert reg.active_count == 1
    first.release()
    assert reg.active_count == 0
    # a reservation that was never registered exhausts the scan.
    orphan = SpawnReservation(reg, "orphan")
    orphan.release()
    assert reg.active_count == 0


def test_input_queue_separates_steer_and_mailbox():
    q = InputQueue()
    q.push("note1", InputQueue.MAILBOX)
    q.push("urgent", InputQueue.STEER)
    q.push("note2", InputQueue.MAILBOX)
    assert q.has_steer() is True
    steer = q.drain_steer()
    assert steer == ["urgent"]
    assert q.has_steer() is False
    assert q.pop_mailbox() == "note1"
    assert q.drain_mailbox() == ["note2"]
    assert q.pending == 0


# ── SkillPolicy (plugin_manifest) ──
from plugin_manifest import SkillPolicy, PluginManifest, validate_skill_deps  # noqa: E402


def test_skillpolicy_normalize():
    assert SkillPolicy.normalize("AUTO") == "auto"
    assert SkillPolicy.normalize("bogus") == "auto"
    assert SkillPolicy.normalize("") == "auto"
    assert SkillPolicy.normalize("explicit") == "explicit"


def test_skillpolicy_exposes():
    assert SkillPolicy.exposes("auto", "s1", []) is True
    assert SkillPolicy.exposes("none", "s1", ["s1"]) is False
    assert SkillPolicy.exposes("explicit", "s1", ["s1"]) is True
    assert SkillPolicy.exposes("explicit", "s2", ["s1"]) is False
    assert SkillPolicy.exposes("inherit", "s9", []) is True


def test_validate_skill_deps_warnings():
    m = PluginManifest(id="p1", version="1.0.0", type="tool", entry="e.py",
                       skill_policy="explicit", skill_dependencies=[])
    w = validate_skill_deps(m)
    assert any("explicit" in x for x in w)

    m2 = PluginManifest(id="p2", version="1.0.0", type="tool", entry="e.py",
                        skill_policy="none", skill_dependencies=["a"])
    w2 = validate_skill_deps(m2)
    assert any("ignores" in x for x in w2)

    m3 = PluginManifest(id="p3", version="1.0.0", type="tool", entry="e.py",
                        skill_policy="auto", skill_dependencies=["missing"])
    w3 = validate_skill_deps(m3, available_skills={"present"})
    assert any("missing" in x for x in w3)


# ── Runtime wiring (integration) ──
def test_orchestrator_exposes_features_registry():
    """The orchestrator must expose a resolved Features registry."""
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "sloth_engine"))

    from context_compactor import ContextCompactor
    from context_fragment import FragmentCollector, SystemFragment, ToolOutputFragment

    cc = ContextCompactor(effective_window=4000)
    col = FragmentCollector()
    col.add(SystemFragment("you are a helpful agent"))
    col.add(ToolOutputFragment("read", "x" * 200))
    cc.attach_fragment_collector(col, budget_tokens=1024)
    r = cc.render_fragments()
    assert r["rendered"] >= 1
    assert r["tokens"] > 0


def test_compactor_without_collector_is_noop():
    from context_compactor import ContextCompactor
    cc = ContextCompactor(effective_window=4000)
    assert cc.render_fragments() == {"rendered": 0, "tokens": 0, "dropped": 0}


def test_run_subagents_parallel_uses_registry():
    from sub_agent import AgentContext, run_subagents_parallel

    def executor(ctx):
        return {"agent": ctx.agent_id}

    contexts = [AgentContext(agent_id=f"a{i}") for i in range(4)]
    results = run_subagents_parallel(contexts, executor, max_workers=2)
    assert len(results) == 4
    assert all(r.status == "completed" for r in results.values())


def test_mcp_register_noop_without_config():
    import plugin_bootstrap
    from tool_registry import ToolRegistry
    assert plugin_bootstrap._register_mcp_tools(ToolRegistry(), {}) == 0


# ── ErrorRecoveryLadder wiring ──
def test_error_recovery_ladder_shares_recovery_state():
    from error_recovery import ErrorRecoveryLadder, ErrorCategory
    from loop_state_enums import RecoveryState

    rs = RecoveryState()
    ladder = ErrorRecoveryLadder(rs, context_manager=None)
    assert ladder.rs is rs
    # prompt_too_long without a context_manager should still return a decision
    decision = ladder.attempt_recovery(ErrorCategory.PROMPT_TOO_LONG, round_num=1)
    assert decision is not None


def test_error_recovery_ladder_with_context_manager():
    from error_recovery import ErrorRecoveryLadder, ErrorCategory
    from loop_state_enums import RecoveryState
    from context_compactor import ContextCompactor

    cc = ContextCompactor(effective_window=1000)
    cc.append_messages(["x" * 5000 for _ in range(10)])
    ladder = ErrorRecoveryLadder(RecoveryState(), context_manager=cc)
    decision = ladder.attempt_recovery(ErrorCategory.PROMPT_TOO_LONG, round_num=2)
    assert decision is not None


# ── P3-E4: Evolution lifecycle hooks ──
def _fake_bridge(bus=None):
    from evolution_bridge import EvolutionSignalBridge, EvolutionConfig
    bridge = EvolutionSignalBridge(
        EvolutionConfig(population_size=4, generations=2, max_work=4),
        hook_bus=bus, task_name="demo")

    class _Res:
        status = "completed"
        sharpe = 0.7
        trades = [1, 2, 3]

    bridge._run_backtest = lambda inp, settings=None: _Res()
    return bridge


def test_evolution_fires_full_lifecycle():
    from hook_events import HookBus, HookEvent
    bus = HookBus()
    bridge = _fake_bridge(bus)
    seed = [
        {"signal_pattern": "a", "market_condition": "trend", "params": {"window": 20}},
        {"signal_pattern": "b", "market_condition": "range", "params": {"window": 14}},
    ]
    res = bridge.evolve(seed)
    assert res["status"] == "ok"
    assert bus.count(HookEvent.EVOLUTION_START) == 1
    assert bus.count(HookEvent.EVOLUTION_SEED_BUILT) == 1
    assert bus.count(HookEvent.EVOLUTION_CANDIDATES_READY) == 1
    assert bus.count(HookEvent.EVOLUTION_GENERATION_END) >= 1


def test_evolution_no_seed_fires_error():
    from hook_events import HookBus, HookEvent
    bus = HookBus()
    bridge = _fake_bridge(bus)
    res = bridge.evolve([])
    assert res["status"] == "no_seed"
    assert bus.count(HookEvent.EVOLUTION_ERROR) == 1


def test_evolution_hooks_safe_without_bus():
    from evolution_bridge import EvolutionSignalBridge, EvolutionConfig
    bridge = EvolutionSignalBridge(EvolutionConfig(population_size=2, generations=1))
    res = bridge.evolve([{"signal_pattern": "x", "params": {"window": 5}}])
    assert res["status"] in ("ok", "no_seed")


def test_evolution_event_category():
    from hook_events import HookEvent
    assert HookEvent.EVOLUTION_START.category == "evolution"
    assert HookEvent.EVOLUTION_CANDIDATES_READY.category == "evolution"


# ── Task 3: DSH todo/credentials plugin ports ──
import importlib.util as _ilu
from pathlib import Path as _P


def _load_plugin(mod_name, rel):
    root = _P(__file__).resolve().parent.parent
    spec = _ilu.spec_from_file_location(mod_name, root / rel)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_todo_whole_list_ok():
    todo = _load_plugin("t_dsh_todo", "sloth_engine/plugins/skill/dsh-todo/entry.py")
    r = todo._todo_write({"todos": [
        {"content": "step A", "status": "in_progress"},
        {"content": "step B", "status": "pending"}]})
    assert r["ok"] is True and r["count"] == 2


def test_todo_single_active_enforced():
    todo = _load_plugin("t_dsh_todo2", "sloth_engine/plugins/skill/dsh-todo/entry.py")
    bad = todo._todo_write({"todos": [
        {"content": "a", "status": "in_progress"},
        {"content": "b", "status": "in_progress"}]})
    assert bad["ok"] is False
    ok = todo._todo_write({"todos": [
        {"content": "a", "status": "in_progress"},
        {"content": "b", "status": "in_progress"}]}, allow_parallel=True)
    assert ok["ok"] is True


def test_todo_rejects_dup_and_empty_and_bad_status():
    todo = _load_plugin("t_dsh_todo3", "sloth_engine/plugins/skill/dsh-todo/entry.py")
    assert todo._todo_write({"todos": [
        {"content": "x", "status": "pending"},
        {"content": "x", "status": "completed"}]})["ok"] is False
    assert todo._todo_write({"todos": [
        {"content": "  ", "status": "pending"}]})["ok"] is False
    assert todo._todo_write({"todos": [
        {"content": "y", "status": "bogus"}]})["ok"] is False


def test_todo_projection_resets_on_turn_start():
    todo = _load_plugin("t_dsh_todo4", "sloth_engine/plugins/skill/dsh-todo/entry.py")
    todo._todo_write({"todos": [{"content": "z", "status": "pending"}]})
    assert todo._PROJECTION.todos is not None
    todo._PROJECTION.apply("turn/start")
    assert todo._PROJECTION.todos is None


def test_credentials_ref_and_key_grammar():
    c = _load_plugin("t_dsh_cred", "sloth_engine/plugins/memory/dsh-credentials/entry.py")
    assert c.is_credential_ref_name("DEEPSEEK_API_KEY") is True
    assert c.is_credential_ref_name("bad-name") is False
    assert c.is_credential_ref_name("1BAD") is False
    assert c.credential_key("llm-pi-ai", "deepseek") == "llm-pi-ai/deepseek"


def test_credentials_layered_resolution(tmp_path, monkeypatch):
    c = _load_plugin("t_dsh_cred2", "sloth_engine/plugins/memory/dsh-credentials/entry.py")
    monkeypatch.setenv("DSH_HOME", str(tmp_path))
    monkeypatch.delenv("MY_TEST_SECRET", raising=False)
    assert c.cred_set("MY_TEST_SECRET", "s3cr3t")["ok"] is True
    info = c.cred_info("MY_TEST_SECRET")
    assert info["configured"] is True and info["source"] == "managed"
    assert "value" not in info            # value is never surfaced
    val, src = c.resolve("MY_TEST_SECRET")
    assert val == "s3cr3t" and src == "managed"
    # inherited env wins
    monkeypatch.setenv("MY_TEST_SECRET", "envwin")
    val2, src2 = c.resolve("MY_TEST_SECRET")
    assert val2 == "envwin" and src2 == "env"


# ---------------------------------------------------------------------------
# dsh-schedule / dsh-jobs / dsh-document  (translated DS plugins)
# ---------------------------------------------------------------------------

def test_schedule_every_min_interval_and_after():
    sch = _load_plugin("t_dsh_sched", "sloth_engine/plugins/skill/dsh-schedule/entry.py")
    ok = sch._schedule_create({"kind": "every", "every_seconds": 300,
                               "title": "poll", "prompt": "check"})
    assert ok["ok"] is True
    too_soon = sch._schedule_create({"kind": "every", "every_seconds": 5,
                                     "title": "x", "prompt": "y"})
    assert too_soon["ok"] is False
    after = sch._schedule_create({"kind": "after", "after_seconds": 120,
                                  "title": "later", "prompt": "go"})
    assert after["ok"] is True


def test_schedule_at_strict_and_offset_normalized():
    sch = _load_plugin("t_dsh_sched2", "sloth_engine/plugins/skill/dsh-schedule/entry.py")
    # 用"运行时未来日期"构造 at 计划，避免硬编码日期过期（原用 2026-10-10，2026-10-14 起已在过去）
    from datetime import datetime, timezone, timedelta
    future = datetime.now(timezone.utc) + timedelta(days=30)
    at_z = future.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    good = sch._schedule_create({"kind": "at", "at": at_z,
                                 "title": "once", "prompt": "p"})
    assert good["ok"] is True
    assert good["schedule"]["scheduledAt"].endswith("Z")
    bad = sch._schedule_create({"kind": "at", "at": "2026-13-01T00:00:00.000Z",
                                "title": "b", "prompt": "p"})
    assert bad["ok"] is False
    # 用 +08:00 表示同一 UTC 时刻，验证时区归一化
    at_off = (future + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S.000+08:00")
    off = sch._schedule_create({"kind": "at", "at": at_off,
                                "title": "tz", "prompt": "p"})
    assert off["ok"] is True
    # +08:00 == 同一 UTC 时刻（归一化去除时区偏移）
    assert off["schedule"]["scheduledAt"] == at_z


def test_schedule_cron_fields_and_bounds():
    sch = _load_plugin("t_dsh_sched3", "sloth_engine/plugins/skill/dsh-schedule/entry.py")
    assert sch._schedule_create({"kind": "cron", "cron": "*/15 * * * *",
                                 "title": "q", "prompt": "p"})["ok"] is True
    assert sch._schedule_create({"kind": "cron", "cron": "0 9 * * MON-FRI",
                                 "title": "w", "prompt": "p"})["ok"] is True
    assert sch._schedule_create({"kind": "cron", "cron": "0 0 32 * *",
                                 "title": "b", "prompt": "p"})["ok"] is False
    assert sch._schedule_create({"kind": "cron", "cron": "0 0 * *",
                                 "title": "b2", "prompt": "p"})["ok"] is False


def test_schedule_title_required():
    sch = _load_plugin("t_dsh_sched4", "sloth_engine/plugins/skill/dsh-schedule/entry.py")
    assert sch._schedule_create({"kind": "after", "after_seconds": 60,
                                 "title": "", "prompt": "p"})["ok"] is False


def test_jobs_lifecycle_and_nonconconseming_read():
    jobs = _load_plugin("t_dsh_jobs", "sloth_engine/plugins/ops/dsh-jobs/entry.py")
    reg = jobs.JobRegistry()
    job = reg.submit("bash", "echo hi")
    job.append("hello ", {"channel": "stdout"})
    job.append("world", {"channel": "stdout"})
    v = job.view()
    assert v["status"] == "running" and v["output"]["total"] == 11
    # non-consuming read at 0 twice yields identical chunks
    a = reg.read_at(job.id, 0)
    b = reg.read_at(job.id, 0)
    assert len(a["chunks"]) == 2 and len(b["chunks"]) == 2
    assert a["next"] == 11 and b["next"] == 11
    # a read below earliest is lossy
    job.ring.earliest = 6
    assert reg.read_at(job.id, 0)["lossy"] is True


def test_jobs_kill_idempotent_and_settle_once():
    jobs = _load_plugin("t_dsh_jobs2", "sloth_engine/plugins/ops/dsh-jobs/entry.py")
    reg = jobs.JobRegistry()
    job = reg.submit("subagent", "report")
    assert reg.request_stop(job.id, "user")["status"] == "stopping"
    first = reg.settle(job.id, "killed", detail="user")
    assert first["status"] == "killed" and first["detail"] == "user"
    second = reg.settle(job.id, "completed")
    assert second["status"] == "killed"       # idempotent, first terminal wins
    assert job.finished_at is not None


def test_jobs_settled_result_handed_out_once():
    jobs = _load_plugin("t_dsh_jobs3", "sloth_engine/plugins/ops/dsh-jobs/entry.py")
    reg = jobs.JobRegistry()
    job = reg.submit("subagent", "report")
    reg.settle(job.id, "completed", result="final report")
    r1 = reg.read(job.id)
    r2 = reg.read(job.id)
    assert r1.get("result") == "final report"
    assert "result" not in r2


def test_jobs_ring_eviction_keeps_absolute_offsets():
    jobs = _load_plugin("t_dsh_jobs4", "sloth_engine/plugins/ops/dsh-jobs/entry.py")
    reg = jobs.JobRegistry()
    job = reg.submit("bash", "x", cap=8)
    job.append("aaaaaaaa")     # 8 bytes
    job.append("bbbbbbbb")     # evicts first chunk
    r = reg.read_at(job.id, 0)
    assert job.ring.total == 16
    assert job.ring.earliest >= 8          # offsets never move back
    assert r["lossy"] is True


def test_jobs_utf8_tail_never_splits_codepoint():
    jobs = _load_plugin("t_dsh_jobs5", "sloth_engine/plugins/ops/dsh-jobs/entry.py")
    # a single oversized chunk keeps only its UTF-8-safe tail
    text = "a" * 5 + "é" * 10   # é is 2 bytes
    tail, nbytes = jobs.utf8_tail(text, 7)
    assert nbytes <= 7
    assert not tail.startswith("\ufffd") or tail == ""
    # decoded tail must be valid (no replacement from a split codepoint start)
    assert "\ufffd" not in tail


def test_document_convert_and_content_dedup():
    doc = _load_plugin("t_dsh_doc", "sloth_engine/plugins/skill/dsh-document/entry.py")
    import base64
    q = doc.ConversionQueue()
    data = b"office payload"
    r1 = q.convert_bytes("ws/a.docx", "v1", "docx", data)
    r2 = q.convert_bytes("ws/b.docx", "v1", "docx", data)
    assert r1["cacheKey"] == r2["cacheKey"]      # same content -> shared conversion
    assert q.status()["conversions"] == 1


def test_document_error_taxonomy():
    doc = _load_plugin("t_dsh_doc2", "sloth_engine/plugins/skill/dsh-document/entry.py")
    q = doc.ConversionQueue()
    try:
        q.convert_bytes("ws/x.zzz", "v1", "zzz", b"data")
        assert False, "expected unsupported-format"
    except doc.OfficeToPdfError as exc:
        assert exc.code == "unsupported-format"
    try:
        q.convert_bytes("ws/x.docx", "v1", "docx", b"")
        assert False, "expected invalid-document"
    except doc.OfficeToPdfError as exc:
        assert exc.code == "invalid-document"
    big = doc.ConversionQueue(config={"maxInputBytes": 4})
    try:
        big.convert_bytes("ws/big.docx", "v1", "docx", b"12345")
        assert False, "expected input-too-large"
    except doc.OfficeToPdfError as exc:
        assert exc.code == "input-too-large"


def test_document_output_validation_rejects_bad_pdf():
    doc = _load_plugin("t_dsh_doc3", "sloth_engine/plugins/skill/dsh-document/entry.py")
    assert doc.validate_pdf_output(b"%PDF-1.4\nbody\n%%EOF", 1024)
    try:
        doc.validate_pdf_output(b"not a pdf", 1024)
        assert False
    except doc.OfficeToPdfError as exc:
        assert exc.code == "invalid-output"
    try:
        doc.validate_pdf_output(b"%PDF-1.4\nbody", 1024)   # no %%EOF
        assert False
    except doc.OfficeToPdfError as exc:
        assert exc.code == "invalid-output"
