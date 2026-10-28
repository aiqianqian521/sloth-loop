"""Project / task loading mixin for the Orchestrator (P2.1 slice C1).

Extracted verbatim from orchestrator.py: project/task config loading with
interactive confirm. Kept as a mixin so self.* wiring and monkeypatch
seams (e.g. Orchestrator._interactive_confirm) stay intact.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from signal_pool import SignalPool
from loop_controller import LoopController
from config_util import deep_merge, load_config
from memory_store import PatternStore
from adapters import backtest_adapter
from runtime_paths import ContainmentError, RuntimePaths
from l2_analyzer import L2Analyzer, L2Config
from run_reporter import RunReporter
from event_log import EventLog
from runtime_exec import ExecGate

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
PROJECT_ROOT = _HERE.parent
_log = logging.getLogger("sloth_engine")

class ProjectLoader:

    def _interactive_confirm(self, prompt: str, default: str = "y") -> bool:
        """Ask user for confirmation at key decision points.
        Returns True if confirmed, False otherwise.
        Skips when interactive mode disabled (--yes flag or uq_enabled=false).
        """
        if not self.interactive:
            return default == "y"
        try:
            answer = input(f"\n{prompt}\n  [y/N]: ").strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            _log.info("Interactive confirm skipped (no TTY input)")
            return default == "y"

    def _validate_signal_batch(self, signals: list[dict]) -> dict:
        """Opt-in strict signal schema gate (fail-closed when enabled).

        When ooda.schema_validate is not disabled the SignalPool already ran
        strict schema validation on the raw input and recorded
        _rejected/_schema_valid; this helper surfaces that state for the round
        gate. P1-4: on by default (fail-closed); set schema_validate=false to
        opt back into the legacy lenient path.
        """
        pool = getattr(self, "signal_pool", None)
        enabled = bool((self.cfg or {}).get("ooda", {}).get("schema_validate", True))
        if not enabled:
            return {"enabled": False, "valid": True, "accepted": list(signals),
                    "rejected": [], "warnings": []}
        if pool is not None:
            return {
                "enabled": True,
                "valid": bool(getattr(pool, "_schema_valid", True)),
                "accepted": list(signals),
                "rejected": list(getattr(pool, "_rejected", []) or []),
                "warnings": [],
            }
        return {"enabled": True, "valid": True, "accepted": list(signals),
                "rejected": [], "warnings": []}

    def generate_signals(self, seed_path: str | None) -> list[dict]:
        batch = self.signal_pool.next_batch(seed_path or self.signals_path)
        self._pool = self.signal_pool._pool
        self._cursor = self.signal_pool.cursor
        self.signal_validation_last = self._validate_signal_batch(batch)
        return batch

    def _load_pool(self, seed_path: str | None) -> list[dict]:
        pool = self.signal_pool.load(seed_path or self.signals_path)
        self._pool = self.signal_pool._pool
        return pool

    def _task_fail_closed(self, reason: str) -> bool:
        """P0 fail-closed twin of _project_fail_closed for --task."""
        allow = bool(getattr(self, "allow_missing_task", False)) or bool(
            (self.cfg or {}).get("task_file", {}).get("allow_missing", False))
        if allow:
            _log.warning(" %s -- using config defaults (allow_missing=True)", reason)
            return True
        _log.error(" [FAIL-CLOSED] %s", reason)
        self._task_error = {
            "status": "error",
            "error_code": "task_not_loadable",
            "error": reason,
            "task_file": str(getattr(self, "_task_file", "") or ""),
        }
        return False

    def _load_task_file(self, task_path: str):
        """Load task definition from YAML/JSON file. Overrides config task section."""
        p = Path(task_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.exists():
            return self._task_fail_closed(f"task file not found: {p}")
        try:
            if p.suffix in (".yaml", ".yml"):
                from config_util import load_config
                data = load_config(p, {})
            else:
                data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return self._task_fail_closed(f"failed to load task file {p}: {e}")
        if isinstance(data, dict):
            self.task_cfg = data
            self._task_file = str(p)
            _log.info(f"[task] Loaded: {p}")
        else:
            return self._task_fail_closed(
                f"task file {p} is not a mapping (got {type(data).__name__})")
        return True

    def _project_fail_closed(self, reason: str) -> bool:
        """P0 fail-closed: an unresolvable --project must NOT silently fall
        back to root defaults (that produced false PASS reports). Returns True
        only when the caller explicitly opted into the legacy fallback."""
        allow = bool(getattr(self, "allow_missing_project", False)) or bool(
            (self.cfg or {}).get("project", {}).get("allow_missing", False))
        if allow:
            _log.warning(" %s -- using defaults (allow_missing=True)", reason)
            return True
        _log.error(" [FAIL-CLOSED] %s", reason)
        self._project_error = {
            "status": "error",
            "error_code": "project_not_loadable",
            "error": reason,
            "project": str(getattr(self, "_project_path", "") or ""),
        }
        return False

    def _load_project(self, project_name: str):
        """Load project-specific config from projects/<name>/config.yaml.

        Overrides backtest script, signals, and db paths.
        Falls back gracefully if project dir doesn't exist.
        """
        # W2-BOUNDARY-01 / H2 Slice 1-PATH: project_name traversal is the
        # upstream of the config.yaml -> shell sink RCE chain; constrain it
        # to the projects store and fail-closed (no overlay loaded).
        self._project_path = project_name
        projects_root = (PROJECT_ROOT / "projects").resolve()
        proj_dir = (PROJECT_ROOT / "projects" / project_name).resolve()
        if not proj_dir.is_relative_to(projects_root):
            _log.warning(f"Project name '{project_name}' escapes projects root, rejected")
            try:
                if self._sec_log is not None:
                    self._sec_log.append(
                        "runtime/project-name-violation",
                        {"kind": "project-name", "name": project_name,
                         "path": str(proj_dir), "base": str(projects_root),
                         "result": "denied"})
            except Exception:
                _log.debug("[containment] audit write failed", exc_info=True)
            return self._project_fail_closed(
                f"project '{project_name}' escapes projects root")
        if not proj_dir.exists():
            return self._project_fail_closed(
                f"project '{project_name}' not found at {proj_dir}")

        # Load project config overlay
        proj_cfg = proj_dir / "config.yaml"
        if proj_cfg.exists():
            try:
                from config_util import load_config, deep_merge
                overlay = load_config(proj_cfg)
                # Merge project config on top of current config
                import copy
                merged = copy.deepcopy(self.cfg)
                merged = deep_merge(merged, overlay)
                # Update paths relative to project dir
                if "backtest" in overlay:
                    for key in ("script", "cwd"):
                        if key in overlay.get("backtest", {}):
                            val = str(overlay["backtest"][key])
                            if not Path(val).is_absolute():
                                merged["backtest"][key] = str(proj_dir / val)
                if "loop" in overlay and "signals" in overlay["loop"]:
                    sig = str(overlay["loop"]["signals"])
                    if not Path(sig).is_absolute():
                        merged["loop"]["signals"] = str(proj_dir / sig)
                if "memory" in overlay and "sqlite_path" in overlay["memory"]:
                    db = str(overlay["memory"]["sqlite_path"])
                    if not Path(db).is_absolute():
                        merged["memory"]["sqlite_path"] = str(proj_dir / db)

                # Reload orchestrator with merged config
                self.cfg = merged
                self.runtime = RuntimePaths.from_config(
                    merged, project_root=PROJECT_ROOT, engine_root=_HERE,
                    on_violation=self._on_containment_violation).ensure()
                self._exec_gate = ExecGate(self.runtime)
                self.db_path = self.runtime.db_path
                self.store = PatternStore(self.db_path)
                self.reporter = RunReporter(self.store, self.runtime)
                self.l2_analyzer.store = self.store
                # Rebind the containment audit sink to the rebuilt events_dir
                # so on_violation keeps recording where the new runtime writes.
                self._sec_log = EventLog(
                    self.runtime.events_dir / "security-audit.jsonl",
                    task_name=(merged.get("task", {}) or {}).get("name", "loop"))

                # 解析 task.workspace，创建任务专属工作目录
                task_cfg = merged.get("task", {})
                workspace_path = None
                workspace_raw = task_cfg.get("workspace", "")
                if workspace_raw:
                    w = Path(workspace_raw)
                    if not w.is_absolute():
                        w = (proj_dir / w).resolve()
                    try:
                        self.runtime.assert_under_root(w, kind="workspace")
                    except ContainmentError:
                        _log.warning(
                            f"workspace '{workspace_raw}' escapes runtime "
                            f"root, rejected")
                        return self._project_fail_closed(
                            f"workspace '{workspace_raw}' escapes runtime root")
                    w.mkdir(parents=True, exist_ok=True)
                    (w / "_data").mkdir(parents=True, exist_ok=True)
                    workspace_path = w

                bt_settings = backtest_adapter.configure(
                    merged.get("backtest", {}), PROJECT_ROOT,
                    workspace=workspace_path, io_dir=self.runtime.io_dir)
                self.bt_settings = bt_settings
                self.work_dir = self.runtime.events_dir

                loop = merged.get("loop", {})
                self.signals_path = loop.get("signals", self.signals_path)
                # Apply project-level loop controls to the live orchestrator.
                # Previously only signals_path was refreshed, so project
                # batch_size/max_rounds settings silently fell back to the
                # root config/defaults.
                self.max_rounds = int(loop.get("max_rounds", self.max_rounds))
                self.max_seconds = int(loop.get("max_seconds", self.max_seconds))
                self.no_progress_stop = int(loop.get("no_progress_stop", self.no_progress_stop))
                self.meta_every = int(loop.get("meta_analyze_every", self.meta_every))
                self.batch_size = int(loop.get("batch_size", self.batch_size))
                self.error_stop = int(loop.get("error_stop", self.error_stop))
                self.circuit.failure_threshold = self.error_stop
                self.circuit.cooldown_seconds = float(
                    loop.get("circuit_cooldown_seconds", self.circuit.cooldown_seconds))
                # cycle-7 A4: keep the fleet health registry's cooldown curve in
                # sync with a project-level override (same refresh path as circuit).
                self.health.base_cooldown_s = max(0.0, float(
                    loop.get("provider_base_cooldown_seconds", self.health.base_cooldown_s)))
                self.health.max_cooldown_s = max(
                    self.health.base_cooldown_s,
                    float(loop.get("provider_max_cooldown_seconds", self.health.max_cooldown_s)))
                self.signal_pool = SignalPool(self.signals_path, self.batch_size, _HERE)
                self.controller = LoopController(self.circuit, self.max_rounds,
                                                 self.no_progress_stop)
                self._pool = None  # Reset signal cache
                self._cursor = 0

                # Update budget/stop/scope from merged config
                budget = merged.get("budget", {})
                self.budget_hard = budget.get("hard", self.budget_hard)
                self.budget_soft = budget.get("soft", self.budget_soft)
                stop_cfg = merged.get("stop", {})
                self.stop_completion = stop_cfg.get("completion", self.stop_completion)
                self.stop_safety = stop_cfg.get("safety", self.stop_safety)
                self.task_cfg = merged.get("task", self.task_cfg)
                scope = self.task_cfg.get("scope", {})
                self.scope_allow = scope.get("allow", self.scope_allow)
                self.scope_deny = scope.get("deny", self.scope_deny)

                consumer = merged.get("consumer", {})
                self.consumer_min_queue = int(consumer.get("min_queue_size", self.consumer_min_queue))
                self.consumer_min_type = int(consumer.get("min_same_type", self.consumer_min_type))
                self.consumer_high_conf = int(consumer.get("high_confidence", self.consumer_high_conf))
                self.consumer_max_suggestions = int(consumer.get("max_suggestions", self.consumer_max_suggestions))
                l2 = merged.get("l2", {})
                self.l2_enabled = bool(l2.get("enabled", self.l2_enabled))
                self.l2_progress_window = int(l2.get("progress_window", self.l2_progress_window))
                self.l2_periodic_every = int(l2.get("periodic_every", self.l2_periodic_every))
                self.l2_queue_trigger = int(l2.get("queue_trigger", self.l2_queue_trigger))
                self.l2_anomaly_trigger = bool(l2.get("anomaly_trigger", self.l2_anomaly_trigger))
                self.l2_stagnation_trigger = int(l2.get("stagnation_trigger", self.l2_stagnation_trigger))
                self.l2_analyzer = L2Analyzer(self.store, L2Config(
                    enabled=self.l2_enabled, progress_window=self.l2_progress_window,
                    periodic_every=self.l2_periodic_every, queue_trigger=self.l2_queue_trigger,
                    anomaly_trigger=self.l2_anomaly_trigger,
                    stagnation_trigger=self.l2_stagnation_trigger, meta_every=self.meta_every,
                    consumer_min_queue=self.consumer_min_queue,
                    consumer_min_type=self.consumer_min_type,
                    consumer_high_conf=self.consumer_high_conf,
                    consumer_max_suggestions=self.consumer_max_suggestions))

                _log.info(f"[project] Loaded: {project_name} ({proj_dir})")
                _log.info(f"          db={self.db_path} signals={self.signals_path}")
            except Exception as e:
                return self._project_fail_closed(
                    f"failed to load project config {proj_cfg}: {e}")
        else:
            return self._project_fail_closed(
                f"project '{project_name}' has no config.yaml")
        return True
