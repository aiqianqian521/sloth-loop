"""
Loop Self-Evolving Orchestration System — Orchestrator (Loop Driver + OODA Engine)

Embedded OODA 7-step cycle: U(Understand)→O(Observe)→O(Orient)→D(Decide)→A(Act)→V(Verify)→L(Learn)
Each step enforces mandatory artifacts + status bar visualization.

Commands:
  python orchestrator.py --doctor            Environment self-check
  python orchestrator.py --once              Run one round (full OODA 7-step)
  python orchestrator.py --once --fast       Run one round (skip OODA, quick verify)
  python orchestrator.py                     Run continuous loop
  python orchestrator.py --status            View pattern library state
  python orchestrator.py --review            Review open failures → upgrade to exclusion rules
  python orchestrator.py --review --yes      Non-interactive batch upgrade
  python orchestrator.py --reset --yes       Clear pattern library (dangerous)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from signal_pool import SignalPool
from loop_controller import LoopController
from resume_guard import check_compatibility, compute_config_hash, compute_pool_hash, compute_signature, pool_matches

# ── v2.0 P2: 统一日志 ───────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
_log = logging.getLogger("sloth_engine")

# Windows console UTF-8 encoding protection
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# W1-RESUME-01 Slice 3: OODA step tokens for mid-round checkpoint/resume.
# These lowercase tokens match step_start_event/step_end_event and are stored
# in run_checkpoints.step. They are the resume skip-through timeline: a step
# checkpoint at index i means steps 0..i already committed on the pre-crash
# pass; resume skips+restores 0..i.
_STEP_ORDER = ("understand", "observe", "orient", "decide", "act", "verify", "learn")
_STEP_INDEX = {name: idx for idx, name in enumerate(_STEP_ORDER)}


# ============================================================================
# UI / runtime infra (extracted to peer modules; re-exported for back-compat)
# ============================================================================
from status_bar import StatusBar    # OODA 7-step status bar
from log_tee import _Tee             # logging tee
from run_lock import _RunLock        # process-level mutex


from config_util import DEFAULT_CONFIG, deep_merge, load_config, HAS_YAML
from memory_store import PatternStore
from adapters import backtest_adapter
from adapters.backtest_adapter import BacktestInput, run_backtest
from tool_registry import ToolRegistry, ToolDefinition  # v2.1 移植-P2
from round_context import RoundContext  # v2.2 P0: Act→Orient 跨轮状态载体
from runtime_paths import ContainmentError, RuntimePaths
from circuit_breaker import CircuitBreaker
from failure_scope_registry import ModelHealthRegistry  # cycle-7 A4
from context_compactor import ContextCompactor
from loop_state_enums import RecoveryState  # CTX-01: compactor recovery state
from error_recovery import ErrorRecoveryLadder, ErrorCategory  # P0-2
from task_tracker import TaskTracker  # P1-N2: step-level task tracking
from l2_analyzer import L2Analyzer, L2Config
from run_reporter import RunReporter, RunReportContext
from cli_router import CliRouter, CliDependencies
from inspection_service import InspectionService
from runtime_exec import ExecGate
from event_log import (EventLog, EVT_ROUND_START, EVT_ROUND_END,
    EVT_ACT_EXECUTE, EVT_ACT_RESULT, EVT_ACT_RETRY,
    EVT_DIAGNOSIS, EVT_DECISION, EVT_VERIFY_RESULT, EVT_LEARN_RECORD,
    step_start_event, step_end_event, build_context_snapshot)  # v2.2 P0: 结构化事件类型

PROJECT_ROOT = _HERE.parent


# ============================================================================
# OODA 7-Step Methods (used by Orchestrator)
# ============================================================================

# ============================================================================
# OODA 7-step pipeline (extracted to ooda_pipeline.py; OODASteps re-exported for back-compat)
# ============================================================================
from ooda_pipeline import OODASteps
from project_loader import ProjectLoader  # P2.1 C1 mixin base
from circuit_state import CircuitState  # P2.1 C2 mixin base
from l2_meta import L2Meta  # P2.1 C3 mixin base
from run_state import RunState  # P2.1 C4 mixin base
from run_once_pipeline import RunOnceMixin  # P2.2 E1 mixin base
from run_loop import RunLoopMixin  # P2.2 E2 mixin base
from evolution_loader import EvolutionLoader  # 自主进化 第1档 mixin base


# ============================================================================
# Orchestrator
# ============================================================================

def _parallel_exclusion_check(win: dict, db_path) -> dict:
    """P2-B: module-level (picklable) helper for ``Orchestrator.run_parallel``.

    Runs a single window's PatternStore exclusion check in a worker process.
    Module-level (not a closure) so Windows ``multiprocessing`` spawn can
    pickle it. ``db_path`` is passed explicitly rather than captured from
    ``self``, and ``PatternStore`` is imported at module top (already on
    ``sys.path``) so the worker re-imports it cleanly on spawn.
    """
    name = win.get("name", "unknown")
    try:
        from memory_store import PatternStore
        store = PatternStore(str(db_path))
        chk = store.check_exclusion(win.get("signals", []))
        return {"name": name, "excluded": chk["excluded_count"],
                "passed": chk["passed_count"], "error": None}
    except Exception as e:  # pragma: no cover - defensive worker error branch
        return {"name": name, "error": str(e), "excluded": 0, "passed": 0}


from orchestrator_safety import SafeComponentMixin  # H1-P3a: _safe_run_component mixin
from hook_events import HookBus, HookEvent
class Orchestrator(ProjectLoader, CircuitState, L2Meta, RunState, RunOnceMixin, RunLoopMixin, EvolutionLoader, SafeComponentMixin):
    def __init__(self, config: dict):
        self.cfg = config
        # W2-BOUNDARY-01 / H2 Slice 1-PATH: containment audit sink. Bound lazily
        # once runtime directories exist (below); the on_violation closure passed
        # to RuntimePaths uses it after __init__ finishes, i.e. only on the
        # runtime sinks that actually call assert_under_root/assert_interpreter.
        self._sec_log = None
        def _on_containment_violation(payload):
            sink = self._sec_log
            if sink is None:
                return
            try:
                sink.append("runtime/path-violation", payload)
            except Exception:
                _log.debug("[containment] audit write failed", exc_info=True)
        self._on_containment_violation = _on_containment_violation
        self.runtime = RuntimePaths.from_config(
            config, project_root=PROJECT_ROOT, engine_root=_HERE,
            on_violation=_on_containment_violation).ensure()
        self._exec_gate = ExecGate(self.runtime)
        self.db_path = self.runtime.db_path
        self.tool_registry = ToolRegistry()
        # v3 plugin-ification: bootstrap moved before store creation so a
        # memory plugin may substitute the pattern store (Upgrade-Law: plain
        # -> plugin at the extension point). Empty roster => no-op (legacy
        # config-based projects undisturbed).
        self.plugin_host = None
        try:
            try:
                from plugin_bootstrap import merge_global_into
                merge_global_into(config)
            except Exception:
                _log.exception('[plugin-host] global fold failed; using legacy roster')
            from plugin_loader import PluginHost
            from plugin_roster import PluginRoster
            self.plugin_host = PluginHost(
                _HERE / 'plugins', self.tool_registry,
                roster=PluginRoster.from_config(config), config=config)
            self.plugin_host.discover()
            self.plugin_host.load_all()
            self.plugin_host.activate_roster()
        except Exception:
            _log.exception('[plugin-host] bootstrap failed; continuing without plugins')
            self.plugin_host = None
        self.store = PatternStore(self.db_path)
        _mem_active = ((config.get('plugins') or {}).get('memory') or {}).get('active')
        if _mem_active and self.plugin_host is not None:
            try:
                _factory = self.plugin_host.memory_factory(_mem_active)
                if _factory is not None:
                    self.store = _factory(config, self.db_path)
                    _log.info('[plugin-host] pattern store replaced by plugin %r', _mem_active)
            except Exception:
                _log.exception('[plugin-host] memory substitution failed; fallback PatternStore')
                self.store = PatternStore(self.db_path)
        self.reporter = RunReporter(self.store, self.runtime)

        loop = config.get("loop", {})
        self.max_rounds = int(loop.get("max_rounds", 20))
        self.token_budget = int(loop.get("token_budget", 500000))
        self.max_seconds = int(loop.get("max_seconds", 0))
        self.no_progress_stop = int(loop.get("no_progress_stop", 3))
        self.meta_every = int(loop.get("meta_analyze_every", 20))
        self.batch_size = int(loop.get("batch_size", 0))
        self.signals_path = loop.get("signals") or "data/signals_seed.json"
        self.error_stop = int(loop.get("error_stop", 2))
        # W2-BOUNDARY-01 / H2 Slice 1-PATH: contain user-provided signals path
        # to runtime root. The default seed ("data/signals_seed.json") resolves
        # under the engine root and is left untouched; config-injected paths
        # (relative to the engine root, matching SignalPool) or absolute paths
        # outside root are rejected with an audit event.
        if loop.get("signals"):
            sp = Path(self.signals_path)
            sp_resolved = (sp if sp.is_absolute() else (_HERE / sp)).resolve()
            self.signals_path = str(
                self.runtime.assert_under_root(sp_resolved, kind="signals"))
        # P1-4: strict input-schema validation is ON by default (fail-closed).
        # signal_schema.validate_signals had 141 lines of checks that were
        # dead unless schema_validate was explicitly enabled; malformed core
        # fields (e.g. non-string market_condition) silently passed. Set
        # schema_validate=false to opt back into the legacy lenient path.
        _schema_on = bool((config.get("ooda") or {}).get("schema_validate", True))
        self.signal_pool = SignalPool(
            self.signals_path, self.batch_size, _HERE,
            task_cfg=(config.get("task") or {}), strict_schema=_schema_on)
        self.signal_validation_last = None
        self._pool: list[dict] | None = None  # legacy introspection alias
        self._cursor = 0  # legacy introspection alias
        self._consecutive_errors = 0
        self._run_id = ""
        # W1-RESUME-01 Slice 3: step-level resume hint (set by run() from a
        # mid-round step checkpoint), the per-round cumulative artifact
        # accumulator backing step checkpoints, and the pre-consume cursor
        # captured at the top of each round so a step checkpoint restores the
        # same signal batch deterministically.
        self._resume_at = None
        self._step_arts = {}
        self._round_start_cursor = 0
        # W1-RESUME-01 Slice 6: protocol-level idempotency attempt counter - 0 on
        # a first pass, 1 on a resume pass (set by run() after loading the
        # checkpoint); carried into run_checkpoints.attempt so the idempotency
        # key (run_id + round + step + attempt + signature) is fully recorded.
        self._resume_pass = False
        self.resume_requested = False
        self.circuit = CircuitBreaker(
            failure_threshold=self.error_stop,
            cooldown_seconds=float(loop.get("circuit_cooldown_seconds", 60)),
            probe_success_threshold=int(loop.get("circuit_probe_success_threshold", 1)),
            on_transition=self._stage_circuit_transition,
        )
        # W1-CB-01 Slice 1: insert the on_transition port; the audit sink and
        # pending transition slot are initialised lazily in run() (run-level
        # scope) so a single injection survives the whole run incl. resume.
        self._pending_circuit_transition = None
        self._breaker_log = None
        self.controller = LoopController(self.circuit, self.max_rounds,
                                         self.no_progress_stop)
        # cycle-7 A4: two-level outbound-fleet health registry (model + provider
        # circuits, exponential cooldown, half-open single-flight). Additive: the
        # per-controller CircuitBreaker above is unchanged; this registry guards
        # the model fleet (sub_agent refs), not the loop controller.
        self.health = ModelHealthRegistry(
            base_cooldown_s=float(loop.get("provider_base_cooldown_seconds", 60)),
            max_cooldown_s=float(loop.get("provider_max_cooldown_seconds", 900)),
        )

        self.bt_settings = backtest_adapter.configure(
            config.get("backtest", {}), PROJECT_ROOT,
            io_dir=self.runtime.io_dir)
        # W2-BOUNDARY-01 / H2 Slice 1-PATH: contain the backtest script to
        # runtime root before any doctor probe or Act run_backtest touches it.
        self.runtime.assert_under(
            self.bt_settings["script"], PROJECT_ROOT, kind="backtest-script")

        self.tokens_used = 0
        # cycle-10 G-6: opt-in provider quota probe.  Left as None so a default
        # run has no quota gate (behaviour unchanged).  A host that can read
        # provider usage injects a callable returning a raw payload or a
        # QuotaSnapshot; the run loop then stops cleanly once a window is
        # exhausted.  See sloth_engine/quota_window.py.
        self.quota_probe = None          # Callable[[], Any] | None
        self.quota_provider = ""         # provider label for the snapshot
        self.quota_cache = None          # last QuotaSnapshot (fail-soft fallback)
        # cycle-13 A (N-3 feasible slice): opt-in file-backed probe.  A host
        # wrapper publishes provider usage to LOOP_QUOTA_FILE; unset => the
        # defaults above stay in force (byte-for-byte unchanged run).
        from quota_file_probe import install as _install_quota_file_probe
        _install_quota_file_probe(self)
        self.last_progress_round = 0
        self.total_rounds = 0
        self.started_at = 0.0

        self.task_cfg = config.get("task") or {}

        # P3-B2: HookBus 事件总线（联动 EventLog）
        self.hook_bus = HookBus(event_log=EventLog(
            self.runtime.events_dir / "hook-events.jsonl",
            task_name=self.task_cfg.get("name", "loop")))
        from hook_events import log_listener
        self.hook_bus.on("*", log_listener)
        self.tool_registry._hook_bus = self.hook_bus  # P3-B2: inject
        self.enable_ooda = config.get("ooda", {}).get("enabled", True)
        self.enable_annotation = config.get("ooda", {}).get("annotation_enabled", True)  # v2.0 P0-3
        # L3 cycle-4 A4 (adopted C2): honor an explicit defer/backpressure as a
        # NON-failure. Default True; an explicit false restores legacy
        # count-everything behaviour (see sloth_engine/backpressure.py).
        self.enable_backpressure_defer = config.get(
            "loop", {}).get("backpressure_defer_enabled", True)
        # L3 cycle-5 A4 (adopted C1): bounded multiplicative rerank settings for
        # the RAG recall stack. alphas default 0.0 -> identity (legacy order);
        # see sloth_engine/rag_layers.py (combined_score).
        _loop_cfg = config.get("loop", {})
        self.rerank_recency_alpha = float(_loop_cfg.get("rerank_recency_alpha", 0.0) or 0.0)
        self.rerank_proof_alpha = float(_loop_cfg.get("rerank_proof_alpha", 0.0) or 0.0)
        self.rerank_halflife_days = float(_loop_cfg.get("rerank_halflife_days", 30.0) or 30.0)
        self.rerank_recency_mode = str(_loop_cfg.get("rerank_recency_mode", "exponential"))

        # Feature flags (Codex five-stage lifecycle). Registered + resolved so the
        # flag state is observable/auditable; defaults map to the legacy
        # enable_* booleans so behaviour is unchanged when no flag is overridden.
        self.features = self._build_features(config)
        self.work_dir = self.runtime.events_dir
        # W2-BOUNDARY-01 / H2 Slice 1-PATH: append-only audit sink for
        # containment violations (who/when/what/base/result). Bound once the
        # runtime dirs and task_cfg exist; reused by _load_project rebuilds.
        self._sec_log = EventLog(
            self.runtime.events_dir / "security-audit.jsonl",
            task_name=self.task_cfg.get("name", "loop"))
        self._warned_namespace = False
        self._task_file = None
        # Phase 1: Contract values loaded for enforcement points
        budget = config.get("budget") or {}
        self.budget_hard = budget.get("hard") or {}
        self.budget_soft = budget.get("soft") or {}
        stop_cfg = config.get("stop") or {}
        self.stop_completion = stop_cfg.get("completion") or []
        self.stop_safety = stop_cfg.get("safety") or []
        scope = (self.task_cfg or {}).get("scope") or {}
        self.scope_allow = scope.get("allow") or []
        self.scope_deny = scope.get("deny") or []
        self._check_scope()
        # Green/Yellow/Red zones + consumer config
        zones = config.get("zones") or {}
        self.zone_green = set(zones.get("green") or [])
        self.zone_yellow = set(zones.get("yellow") or [])
        self.zone_red = set(zones.get("red") or [])
        consumer = config.get("consumer") or {}
        self.consumer_min_queue = int(consumer.get("min_queue_size", 3))
        self.consumer_min_type = int(consumer.get("min_same_type", 3))
        self.consumer_high_conf = int(consumer.get("high_confidence", 5))
        self.consumer_max_suggestions = int(consumer.get("max_suggestions", 5))
        l2 = config.get("l2") or {}
        self.l2_enabled = bool(l2.get("enabled", True))
        self.l2_progress_window = int(l2.get("progress_window", 5))
        self.l2_periodic_every = int(l2.get("periodic_every", 5))
        self.l2_queue_trigger = int(l2.get("queue_trigger", 3))
        self.l2_anomaly_trigger = bool(l2.get("anomaly_trigger", True))
        self.l2_stagnation_trigger = int(l2.get("stagnation_trigger", 2))
        self.l2_analyzer = L2Analyzer(self.store, L2Config(
            enabled=self.l2_enabled,
            progress_window=self.l2_progress_window,
            periodic_every=self.l2_periodic_every,
            queue_trigger=self.l2_queue_trigger,
            anomaly_trigger=self.l2_anomaly_trigger,
            stagnation_trigger=self.l2_stagnation_trigger,
            meta_every=self.meta_every,
            consumer_min_queue=self.consumer_min_queue,
            consumer_min_type=self.consumer_min_type,
            consumer_high_conf=self.consumer_high_conf,
            consumer_max_suggestions=self.consumer_max_suggestions,
        ))
        self.interactive = config.get("ooda", {}).get("uq_enabled", True)  # v2.0 P1
        self._init_evolution()  # 自主进化 第1档: 半自主信号演化

        # ── CTX-01: Context compactor + P0-2 error recovery ladder ──
        effective = int(loop.get("effective_window", 128000))
        self._recovery_state = RecoveryState()
        self.compactor = ContextCompactor(
            effective_window=effective,
            compact_fn=None,  # loop 无 LLM，compact_fn 由子类/适配器注入
            recovery_state=self._recovery_state,
        )
        # P0-2: escalation ladder shares the recovery state and can drive the
        # compactor on prompt_too_long (collapse/compact before giving up).
        self.recovery_ladder = ErrorRecoveryLadder(
            self._recovery_state, context_manager=self.compactor)

        # P1-N2: step-level task tracking (Codex TodoWrite analogue). Seeded
        # with the OODA round skeleton so downstream steps can mark progress.
        self.task_tracker = TaskTracker(
            self.task_cfg.get("name", "loop"), round_num=0)


    # ── v2.0 P1: 交互式确认 ─────────────────────────────────

    # ── Signal generation ─────────────────────────────────────

    # ── OODA 7-step single round ──────────────────────────────


    def _build_features(self, config: dict):
        """Construct the Feature registry and resolve standard flags.

        The three legacy OODA switches become features whose DEFAULT stage is
        derived from the existing config booleans, so nothing changes unless a
        LOOP_FEATURE_* env var or config.features override is set.
        """
        try:
            from features import Features
        except Exception as exc:  # never let flags break construction
            _log.warning("[features] unavailable (%s); using no-op", exc)
            return None

        feats = Features(config=config)
        feats.register_many([
            {"name": "ooda", "stage": "enabled" if self.enable_ooda else "disabled",
             "description": "OODA decision pipeline"},
            {"name": "annotation", "stage": "enabled" if self.enable_annotation else "disabled",
             "description": "delta annotation"},
            {"name": "context_fragment", "stage": "enabled",
             "description": "Codex-style context fragment collection"},
            {"name": "guardian", "stage": "enabled",
             "description": "layered security review"},
            {"name": "mcp_tools", "stage": "disabled",
             "description": "MCP tool discovery (opt-in)"},
            {"name": "subagent_registry", "stage": "enabled",
             "description": "bounded concurrency sub-agent registry"},
        ])
        snap = feats.snapshot()
        active = [k for k, v in snap.items() if v["on"]]
        _log.info(f"  Feature flags    : {len(active)}/{len(snap)} active -> {active}")
        return feats


    def run_fast(self, signals: list[dict]) -> dict:
        """Fast mode: skip OODA steps, direct check→backtest→record."""
        chk = self.store.check_exclusion(signals)
        if not chk["passed"]:
            self.store.log_round(chk["input_count"], chk["excluded_count"],
                                 0, 0, 0, "all_excluded")
            return {"check": chk, "backtest": None,
                    "record": {"new_failures": 0, "new_successes": 0,
                               "bumped_failures": 0, "bumped_successes": 0},
                    "progressed": False, "all_excluded": True,
                    "status": "ok", "error": None,
                    "verified": {"pass_count": 0, "total": 0}}
        from adapters.task_runner import TaskInput, BacktestRunner
        success_starts = [s for s in self.store.load_success_patterns()
                          if s.get("status") == "confirmed"][:3]
        runner = BacktestRunner(self.bt_settings)
        task_result = runner.run(TaskInput(
            task_type=self.task_cfg.get("name", "backtest"),
            signals=chk["passed"], params={"success_starts": success_starts},
        ))
        act = {"status": task_result.status,
               "trades": task_result.raw_output.trades if task_result.raw_output else [],
               "error": task_result.errors[0]["evidence"] if task_result.errors else "",
               "sharpe": task_result.metrics.get("sharpe", 0),
               "win_rate": task_result.metrics.get("win_rate", ""),
               "signals_tested": chk["passed_count"],
               "raw": task_result.raw_output,
               "task_result": task_result}
        # W1-STORE-01 R1: legacy fast-path version of the same atomic Learn
        # boundary used in run_once.  Buffers a round row together with the
        # failure/success patterns it summarizes.
        with self.store.transaction():
            learned = OODASteps._learn(act, {}, self.store)
            bt = task_result.raw_output
            execution_error = bool(task_result.errors) or task_result.status == "error"
            bt_error = (task_result.errors[0].get("evidence", "")
                        if task_result.errors else "")
            self.store.log_round(chk["input_count"], chk["excluded_count"],
                                 chk["passed_count"], learned["new_failures"],
                                 learned["new_successes"], bt_error or "ok")
        progressed = (learned["new_failures"] > 0 or learned["new_successes"] > 0) \
            and not (execution_error and not (bt and bt.trades))
        return {"check": chk, "backtest": bt,
                "backtest_status": task_result.status,
                "backtest_error": bt_error,
                "trades": len(bt.trades) if bt else 0,
                "status": "ok", "error": None,
                "record": learned, "progressed": progressed,
                "all_excluded": False,
                "verified": {"pass_count": 0, "total": 0}}

    # ── Meta analysis ─────────────────────────────────────────

    # ── v2.0 P2: L2 规则自动建议 ────────────────────────────

    # ── v2.0 P2: 多窗口并行回测 ──────────────────────────────

    def run_parallel(self, windows: list[dict]) -> list[dict]:
        """Execute multiple backtest windows in parallel using multiprocessing.

        Args:
            windows: list of {name, signals, params} dicts

        Returns:
            list of {name, status, trades, error} dicts
        """
        from multiprocessing import Pool, cpu_count
        from functools import partial

        if not windows:
            return []
        workers = min(len(windows), cpu_count())
        _log.info("Parallel mode: %d windows on %d workers", len(windows), workers)

        # P2-B: pass the module-level picklable helper + explicit db_path via
        # functools.partial so Windows spawn can pickle the worker target
        # (a local closure referencing self/`_HERE` is not picklable).
        with Pool(workers) as pool:
            results = pool.map(
                partial(_parallel_exclusion_check, db_path=self.db_path), windows)

        return list(results)

    # ── Doctor ────────────────────────────────────────────────

    def doctor(self) -> bool:
        ok = True
        _log.info("=" * 60)
        _log.info("Environment Self-Check (doctor)")
        _log.info("=" * 60)
        _log.info(f"  Python           : {sys.version.split()[0]}  ({sys.executable})")
        _log.info(f"  PyYAML           : {'Installed' if HAS_YAML else 'Not installed (core unaffected)'}")
        _log.info(f"  OODA mode        : {'Enabled' if self.enable_ooda else 'Disabled (--fast)'}")

        _log.info(f"  Pattern library  : {self.db_path}")
        try:
            self.store.load_failure_patterns()
            _log.info("                      Read/Write OK")
        except Exception as e:
            _log.info(f"                     [FAIL] {e}")
            ok = False

        script = Path(self.bt_settings["script"])
        try:
            self.runtime.assert_under(script, PROJECT_ROOT, kind="backtest-script")
        except ContainmentError as e:
            _log.info(f"                     [FAIL] Backtest script escapes runtime root: {e}")
            ok = False
            return ok
        if script.exists():
            _log.info(f"  Backtest script  : {script}  exists")
            try:
                probe = run_backtest(BacktestInput(
                    signals=[{"signal_pattern": "contract-probe",
                              "market_condition": "probe"}]),
                    exec_gate=self._exec_gate)
                if probe.status == "error":
                    _log.info(f"                     [FAIL] Contract probe failed: {probe.error[:160]}")
                    ok = False
                elif not probe.trades:
                    _log.info("                     [FAIL] Contract probe: 0 trades (check output format)")
                    ok = False
                else:
                    _log.info(f"                     [OK] Contract probe: {len(probe.trades)} trades")
            except Exception as e:
                _log.info(f"                     [FAIL] Contract probe exception: {e}")
                ok = False
        else:
            _log.info(f"  Backtest script  : {script}")
            _log.info("                     [FAIL] Not found — fix backtest.script in config.yaml")
            ok = False

        data_dir = self.runtime.io_dir
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            probe = data_dir / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            _log.info(f"  Data directory   : {data_dir}  writable")
        except OSError as e:
            _log.info(f"  Data directory   : [FAIL] {data_dir} not writable: {e}")
            ok = False

        _log.info(f"  Loop limits      : max_rounds={self.max_rounds} "
              f"no_progress_stop={self.no_progress_stop} "
              f"max_seconds={self.max_seconds or 'unlimited'}")
        if self.budget_hard:
            _log.info(f"  Contract BUDGET  : hard={self.budget_hard} soft={self.budget_soft}")
        if self.stop_completion:
            _log.info(f"  Contract STOP    : completion={self.stop_completion} safety={self.stop_safety}")
        if self.scope_allow:
            _log.info(f"  Contract SCOPE   : allow={self.scope_allow[:3]}... deny={self.scope_deny[:3]}...")
        _log.info("=" * 60)
        _log.info("Verdict: " + ("Ready — run python orchestrator.py --once"
                            if ok else "Blockers found — fix [FAIL] items above first"))

        # ── v2.0 P1: 首次运行向导 — 5W1H 扫描 ──
        if ok:
            _log.info("")
            _log.info("=" * 60)
            _log.info("v2.0 First-Run Wizard — 5W1H Scan")
            _log.info("=" * 60)
            task_name = self.task_cfg.get("name", "unknown")
            _log.info(f"  Task            : {task_name}")
            sc = self.task_cfg.get("success_criteria", [])
            if sc:
                for c in sc:
                    _log.info(f"  Success metric  : {c.get('metric','?')} {c.get('operator','?')} {c.get('threshold','?')}")
            _log.info(f"  Max rounds      : {self.max_rounds}")
            _log.info(f"  v2.0 Features   : OODA={self.enable_ooda} Delta={self.enable_ooda} Annotation={self.enable_annotation}")
            _log.info("")
            _log.info("  5W1H Scan:")
            _log.info(f"    Who   : Task owner → you (sloth-loop developer)")
            _log.info(f"    What  : Execute '{task_name}' with auto-learning from failures")
            _log.info(f"    Where : {self.db_path} (patterns), {self.runtime.io_dir} (I/O)")
            _log.info(f"    When  : Max {self.max_rounds} rounds, {self.max_seconds}s timeout")
            _log.info(f"    Why   : Accumulate failure patterns to improve success rate over time")
            _log.info(f"    How   : OODA 7-step cycle + L1 retry + L2 evolution + pattern persistence")
            _log.info("")
            _log.info("  [数据] Review the 5W1H above. Edit 00-purpose.md to refine if needed.")
            _log.info("  [数据] Run with --once to execute one round and verify.")
            _log.info("=" * 60)

        return ok

    # ── Status ────────────────────────────────────────────────

    def status(self):
        fs = self.store.load_failure_patterns()
        ss = self.store.load_success_patterns()
        rounds = self.store.get_rounds()
        active_rules = self.store.get_active_exclusion_rules()

        # ── Header ──
        _log.info("")
        _log.info("  模式库状态")
        _log.info("  " + "─" * 62)

        # ── Failure patterns ──
        if fs:
            by_mode = {}
            for f in fs:
                m = f.get("failure_mode", "未知")
                by_mode.setdefault(m, []).append(f)
            _log.info(f"  失败模式: {len(fs)} 条 ({len(by_mode)} 种类型)")
            for mode, items in sorted(by_mode.items(), key=lambda x: -len(x[1])):
                resolved = sum(1 for f in items if f.get("status") == "resolved")
                open_n = sum(1 for f in items if f.get("status") == "open")
                _log.info(f"    {mode}: {len(items)} 次 (已解决 {resolved}, 待审核 {open_n})")
        else:
            _log.info("  失败模式: 暂无 (运行 loop 后自动积累)")

        # ── Success patterns ──
        if ss:
            confirmed = sum(1 for s in ss if s.get("status") == "confirmed")
            candidate = sum(1 for s in ss if s.get("status") == "candidate")
            _log.info(f"  成功模式: {len(ss)} 条 (已确认 {confirmed}, 候选 {candidate})")
        else:
            _log.info("  成功模式: 暂无")

        # ── Active rules ──
        if active_rules:
            _log.info(f"  活跃排除规则: {len(active_rules)} 条")
            for r in active_rules[:5]:
                _log.info(f"    - {r.get('exclusion_rule', '?')} ({r.get('failure_mode', '?')})")
            if len(active_rules) > 5:
                _log.info(f"    ... 还有 {len(active_rules) - 5} 条")
        else:
            _log.info("  活跃排除规则: 暂无")

        # ── Recent rounds summary ──
        if rounds:
            # Deduplicate: show summary of last N rounds, not every identical round
            recent = rounds[-10:]
            total_new_f = sum(r.get("new_failures", 0) for r in recent)
            total_new_s = sum(r.get("new_successes", 0) for r in recent)
            last_ts = (recent[-1].get("ts") or "")[:16].replace("T", " ")
            distinct_notes = list(set(r.get("notes", "") for r in recent))
            _log.info(f"\n  最近 {len(recent)} 轮 (截止 {last_ts})")
            _log.info(f"    新发现: +{total_new_f} 失败 / +{total_new_s} 成功")
            if len(set(r.get("notes", "") for r in recent)) <= 1 and recent:
                note = recent[-1].get("notes", "")
                if note == "ok":
                    _log.info(f"    状态: 全部正常完成，但未发现新模式 (信号可能已穷尽)")
                elif note == "all_excluded":
                    _log.info(f"    状态: 信号全部被排除规则拦截")
                else:
                    _log.info(f"    状态: {note}")
            _log.info(f"    总轮次: {len(rounds)}")

        # ── Problem queue ──
        qs = self.store.get_queue_stats()
        if qs["total"] > 0:
            _log.info(f"\n  问题队列: {qs['total']} 条待处理")
            TYPE_CN = {
                "execution_error": "执行错误", "config_tuning": "配置问题",
                "stagnation": "停滞告警", "pattern_anomaly": "模式异常",
            }
            for tp, n in sorted(qs["by_type"].items()):
                label = TYPE_CN.get(tp, tp)
                _log.info(f"    {label}: {n} 条")
            # Show recent problems with evidence
            queued = self.store.pull_problems(status="queued")
            if queued:
                _log.info(f"\n  最新问题 (最近 5 条):")
                for p in queued[-5:]:
                    sev = p.get("severity", "")
                    sev_tag = "!!" if sev == "critical" else "! " if sev == "major" else "· "
                    ev = (p.get("evidence") or "")[:80]
                    act = (p.get("suggested_action") or "")[:60]
                    rn = p.get("round", "?")
                    _log.info(f"    [{sev_tag}] 第{rn}轮: {ev}")
                    if act:
                        _log.info(f"         建议: {act}")
        else:
            _log.info(f"\n  问题队列: 空")

        _log.info("  " + "─" * 62)
        if fs or ss:
            opens = [f for f in fs if f.get("status") == "open"]
            if opens:
                _log.info(f"  → {len(opens)} 条待审核，执行 --review 升级为排除规则")
            else:
                _log.info(f"  → 执行 --once 继续积累模式")
        else:
            _log.info(f"  → 执行 --once 开始第一轮")
        _log.info("")

    # ── Review (human approval gate) ──────────────────────────

    def review(self, assume_yes: bool = False, scope: str = "combo",
               min_win_rate: float | None = None):
        opens = [f for f in self.store.load_failure_patterns()
                 if f.get("status") == "open"]
        if not opens:
            _log.info("[review] No open failures to review")
            return
        # L1 fix: --yes means "don't interact", regardless of tty
        if not assume_yes and not sys.stdin.isatty():
            _log.info(f" Non-interactive environment, {len(opens)} open items pending. "
                  f"Use --yes to auto-upgrade all (with --scope combo|pattern)")
            return

        tag = f"--min-win-rate={min_win_rate:.0%}" if min_win_rate else ""
        _log.info(f" {len(opens)} open failures (--scope={scope} {tag}):")
        resolve_all = assume_yes
        skipped_low_wr = 0
        for f in opens:
            occ = f.get("occurrences") or 1
            _log.info(f"  {f['id']} | {f.get('failure_mode')} | "
                  f"{f.get('signal_pattern')} @ {f.get('market_condition')} | x{occ}")
            _log.info(f"      root_cause: {str(f.get('root_cause'))[:100]}")

            # L3 fix: --yes with min_win_rate filters low-win-rate entries
            if resolve_all and min_win_rate is not None:
                # SQLite stores impact_win_rate as flat column, not nested in impact dict
                wr_str = f.get("impact_win_rate") or \
                         (f.get("impact") or {}).get("win_rate", "N/A")
                try:
                    wr_val = float(str(wr_str).replace("%", "").strip())
                    wr = wr_val if (not str(wr_str).endswith("%") and wr_val <= 1) else wr_val / 100
                    if wr < min_win_rate:
                        _log.info(f"      -> skip (win_rate {wr:.0%} < --min-win-rate {min_win_rate:.0%})")
                        skipped_low_wr += 1
                        continue
                except (ValueError, TypeError):
                    pass  # Unparseable win_rate — don't skip

            if resolve_all:
                ans = "y"
            else:
                ans = input("      Upgrade to resolved and exclude? [y/n/a=all/q=quit] ").strip().lower()
            if ans == "q":
                _log.info("[review] Quit")
                break
            if ans == "a":
                resolve_all, ans = True, "y"
            if ans == "y":
                rule = self.store.make_rule(
                    f.get("signal_pattern") or f.get("failure_mode"),
                    f.get("market_condition", ""), scope)
                self.store.update_failure_status(f["id"], "resolved", exclusion_rule=rule)
                _log.info(f"      -> resolved, exclusion rule({scope}): {rule}")
            else:
                _log.info("      -> skipped")
        msg = "[review] Done. check_exclusion will block these patterns next round."
        if skipped_low_wr:
            msg += f" ({skipped_low_wr} skipped due to low win rate)"
        _log.info(msg)

    # ── Main loop ─────────────────────────────────────────────

    # ── L2: Progress Reading & Trigger Detection ─────────────────

    # ── v2.0: L2 效果评估闭环 ──────────────────────────────


    # ── P0 Problem Queue Producer ─────────────────────────────

    # ── Phase 1: 合同执行方法 ───────────────────────────────────

    # ── P0 问题队列生产者 ───────────────────────────────────────

    # ── Stop diagnosis ────────────────────────────────────────

    # ── STATE.md 结构化持久 ──────────────────────────────────────

    # ── v2.0 P3: 多项目支持 ─────────────────────────────────

    # ── Reset ─────────────────────────────────────────────────

    def reset(self, assume_yes: bool = False):
        if not assume_yes:
            _log.info("[reset] This will clear ALL pattern library data. Add --yes to confirm")
            return
        import sqlite3
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            for t in ("failure_patterns", "success_patterns", "rounds",
                       "problem_queue", "run_history"):
                conn.execute(f"DELETE FROM {t}")
        _log.warning(f" Cleared: {self.db_path}")


# ============================================================================
# CLI
# ============================================================================

class ConfigNotFoundError(RuntimeError):
    """Raised when an explicitly requested config file does not exist (D4)."""


def build_orchestrator(config_path: str) -> Orchestrator:
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        if (Path.cwd() / cfg_path).exists():
            cfg_path = Path.cwd() / cfg_path
        else:
            cfg_path = _HERE / cfg_path
    # D4-FIX: fail-closed on a missing config file. Previously load_config
    # returned {} and the run continued with built-in defaults, so the user
    # saw a misleading ContainmentError (path escape) instead of the real
    # cause (config not found). The CLI entry now rejects it explicitly.
    try:
        user_cfg = load_config(cfg_path, {}, require_exists=True)
    except FileNotFoundError as exc:
        raise ConfigNotFoundError(str(exc)) from exc
    if not HAS_YAML and cfg_path.suffix.lower() in (".yaml", ".yml"):
        _log.info("[info] PyYAML not installed, using built-in minimal YAML parser")
    return Orchestrator(deep_merge(DEFAULT_CONFIG, user_cfg))


def _show_history(db_path: Path | None = None):
    """Display past run history in human-readable format."""
    import sqlite3
    db_path = db_path or (PROJECT_ROOT / "sloth_engine" / "data" / "patterns.db")
    if not db_path.exists():
        _log.info("[history] 没有找到数据库，请先运行一次 loop")
        return

    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM run_history ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

    runs = [dict(r) for r in rows]
    if not runs:
        _log.info("[history] 还没有运行记录，执行 python orchestrator.py --once 开始")
        return

    VERDICT_CN = {
        "OK": "正常完成", "WARN": "异常终止", "ERR": "执行错误", "STOP": "达到上限",
    }
    _log.info("")
    _log.info("  运行历史")
    _log.info("  " + "─" * 62)
    for i, r in enumerate(runs, 1):
        ts = (r.get("created_at") or "")[:16].replace("T", " ")
        task = r.get("task", "?")
        rounds = r.get("total_rounds", 0)
        elapsed = r.get("elapsed_seconds", 0)
        verdict = VERDICT_CN.get(r.get("verdict", ""), r.get("verdict", "?"))
        stop = r.get("stop_reason", "?")
        nf = r.get("new_failures", 0)
        ns = r.get("new_successes", 0)
        rules = r.get("active_exclusion_rules", 0)
        problems = r.get("problems_queued", 0)
        run_id = r.get("id", "?")

        # Map stop reason to plain Chinese
        stop_cn = stop
        if "max_rounds" in stop.lower():
            stop_cn = f"达到最大轮数({rounds}轮)"
        elif "no new" in stop.lower() or "no progress" in stop.lower():
            stop_cn = f"连续{rounds}轮无新发现，自动停止"
        elif "time limit" in stop.lower():
            stop_cn = f"时间限制({elapsed:.0f}s)"
        elif "circuit" in stop.lower() or "error" in stop.lower():
            stop_cn = "回测连续出错，熔断停止"

        _log.info(f"  [{i}] {ts} | {task}")
        _log.info(f"      状态: {verdict} · {stop_cn}")
        new_stuff = []
        if nf > 0:
            new_stuff.append(f"{nf} 个失败模式")
        if ns > 0:
            new_stuff.append(f"{ns} 个成功模式")
        if new_stuff:
            _log.info(f"      发现: {', '.join(new_stuff)}")
        else:
            _log.info(f"      发现: 本轮未发现新模式")
        _log.info(f"      活跃排除规则: {rules} · 问题队列: {problems}")
        _log.info(f"      存档: runs/{run_id}/")
        _log.info("")
    _log.info("  " + "─" * 62)
    _log.info(f"  共 {len(runs)} 次运行")


# ── v3.1 P1: --inspect CLI ────────────────────────────────

# Inspect CLI handlers moved to inspection_service.InspectionService (W2-BOUNDARY-01 / H2 Slice 1-PATH Z-β: per-instance, no module global).


def main(argv: list[str] | None = None):
    """Composition root; parsing and command dispatch live in CliRouter."""
    router = CliRouter(CliDependencies(
        build_orchestrator=build_orchestrator,
        inspection_service=lambda wd: InspectionService(wd, logger=_log),
        show_history=_show_history,
        run_lock_cls=_RunLock,
        tee_cls=_Tee,
        logger=_log,
    ))
    code = router.run(argv)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
