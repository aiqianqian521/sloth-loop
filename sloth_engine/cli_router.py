"""CLI parser and command router for Loop's composition root."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable


@dataclass(frozen=True)
class CliDependencies:
    build_orchestrator: Callable[[str], Any]
    inspection_service: Callable[[Any], Any]
    show_history: Callable[[Any], None]
    run_lock_cls: type
    tee_cls: type
    logger: Any


class CliRouter:
    def __init__(self, deps: CliDependencies):
        self.deps = deps

    @staticmethod
    def build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Loop Self-Evolving Orchestrator (OODA Engine)",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="Run --doctor first, then --once, then the full loop.")
        parser.add_argument("--config", default="config.yaml")
        parser.add_argument("--signals", default=None, help="Candidate signal JSON path")
        parser.add_argument("--once", action="store_true", help="Run one round (full OODA 7-step)")
        parser.add_argument("--resume", action="store_true", help="Resume latest unfinished checkpoint")
        parser.add_argument("--fast", action="store_true", help="Skip OODA steps with --once")
        parser.add_argument("--doctor", action="store_true", help="Environment self-check")
        parser.add_argument("--status", action="store_true", help="View pattern library state")
        parser.add_argument("--history", action="store_true", help="View past run history")
        parser.add_argument("--review", action="store_true", help="Review open failures")
        parser.add_argument("--reset", action="store_true", help="Clear pattern library (dangerous)")
        parser.add_argument("--yes", action="store_true", help="Non-interactive confirmation")
        parser.add_argument("--scope", default="combo", choices=["combo", "pattern"])
        parser.add_argument("--min-win-rate", type=float, default=None)
        parser.add_argument("--max-rounds", type=int, default=None)
        parser.add_argument("--task", default=None)
        parser.add_argument("--allow-missing-task", action="store_true",
                            help="Legacy escape hatch: use config task defaults when --task cannot be loaded")
        parser.add_argument("--project", default=None)
        parser.add_argument("--allow-missing-project", action="store_true",
                            help="Legacy escape hatch: run with root defaults when --project cannot be loaded")
        parser.add_argument("--inspect", default=None, nargs="?", const="runs",
                            choices=["runs", "round", "timeline", "last-error"])
        parser.add_argument("--round", type=int, default=None)
        parser.add_argument("--evolve", action="store_true", help="Semi-autonomous signal evolution (第1档)")
        parser.add_argument("--rev-candidates", default=None, help="Review a candidates JSON and commit into signal pool (with --yes)")
        parser.add_argument("--auto-review", default=None, help="Auto-review a candidates JSON via deterministic policy (no --yes needed)")
        parser.add_argument("--report", action="store_true", help="Generate customer completion report")
        parser.add_argument("--trace", default=None, nargs="?", const="",
                            help="Generate local HTML trace report (optional LOG path)")
        return parser

    def run(self, argv: list[str] | None = None) -> int:
        parser = self.build_parser()
        args = parser.parse_args(argv)
        if args.resume and args.once:
            parser.error("--resume applies to the continuous loop; omit --once")
        deps = self.deps
        try:
            orch = deps.build_orchestrator(args.config)
        except Exception as exc:  # D4-FIX: config missing/invalid -> explicit exit 2
            self.deps.logger.error("Config error: %s", exc)
            return 2
        if args.max_rounds is not None:
            orch.max_rounds = args.max_rounds
        if args.fast:
            orch.enable_ooda = False
        if args.project:
            orch.allow_missing_project = bool(args.allow_missing_project)
            if not orch._load_project(args.project):
                self.deps.logger.error(
                    " Project '%s' could not be loaded (fail-closed); refusing "
                    "to run with root defaults. Pass --allow-missing-project to "
                    "opt into the legacy fallback.", args.project)
                return 1
        if args.task:
            orch.allow_missing_task = bool(args.allow_missing_task)
            if not orch._load_task_file(args.task):
                self.deps.logger.error(
                    " Task file '%s' could not be loaded (fail-closed); refusing "
                    "to run with config defaults. Pass --allow-missing-task to "
                    "opt into the legacy fallback.", args.task)
                return 1
        orch.resume_requested = args.resume
        inspection = deps.inspection_service(orch.work_dir)

        if args.evolve:
            result = orch.evolve_signals(args.signals, project_name=args.project,
                                         assume_yes=args.yes, auto_apply=args.yes)
            self.deps.logger.info(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        if args.rev_candidates:
            result = orch.review_candidates(args.rev_candidates, assume_yes=args.yes)
            self.deps.logger.info(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        if args.auto_review:
            result = orch.review_candidates(args.auto_review, auto=True)
            self.deps.logger.info(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        if args.report:
            path = orch.reporter.write_customer_report(orch._report_context())
            self.deps.logger.info("[report] Customer completion report: %s", path)
            return 0
        if args.trace is not None:
            inspection.trace_handler(args.trace or None)
            return 0
        if args.inspect:
            inspection.inspect_handler(args.inspect, args.round)
            return 0
        if args.doctor:
            return 0 if orch.doctor() else 1
        if args.status:
            orch.status()
            return 0
        if args.history:
            deps.show_history(orch.db_path)
            return 0
        if args.review:
            orch.review(assume_yes=args.yes, scope=args.scope, min_win_rate=args.min_win_rate)
            return 0
        if args.reset:
            orch.reset(assume_yes=args.yes)
            return 0
        if args.once:
            return self._run_once(orch, args)
        return self._run_continuous(orch, args)

    def _run_once(self, orch, args) -> int:
        # R1 (cycle-10): --once must hold the SAME process lock as the
        # continuous loop.  It writes the same SQLite DB and the shared runtime
        # io_dir, so a manual --once overlapping a cron run used to corrupt
        # both (the lock previously guarded the continuous path only).
        lock_path = orch.runtime.root / ".loop.lock"
        lock = self.deps.run_lock_cls(lock_path)
        try:
            lock.__enter__()
        except RuntimeError as exc:
            self.deps.logger.warning(" Cannot acquire run lock: %s", exc)
            return 2
        try:
            return self._run_once_locked(orch, args)
        finally:
            lock.__exit__(*sys.exc_info())

    def _run_once_locked(self, orch, args) -> int:
        """Run one round and archive it.

        O-1 exit-code contract (cycle-29 A): --once: exit 0 = the round ran
        (regardless of whether the task's ``success_criteria`` were met), 1 =
        the round itself errored (``status == "error"``), 2 = the run lock could
        not be acquired / bad config.  "Criteria not met" is *data*, not a CLI
        failure: it is recorded in the archived verdict (RunReporter.classify_stop)
        and read back with --inspect / --status, so cron/CI must not treat it as a
        crash.  Pinned by tests/test_runtime_artifact_containment.py.
        """
        signals = orch.generate_signals(args.signals)
        if not signals:
            self.deps.logger.error(" No candidate signals. Use --signals data/signals_seed.json")
            return 1
        orch.total_rounds = 1
        orch.started_at = time.time()
        result = orch.run_once(signals, 1, fast=not orch.enable_ooda)
        orch._write_state_md("--once completed", time.time() - orch.started_at)
        elapsed = time.time() - orch.started_at
        stop_reason = "--once completed"
        orch._archive_run(stop_reason, elapsed)
        orch._write_customer_report(stop_reason, elapsed)
        if not orch.enable_ooda and result.get("status") != "error":
            backtest = result.get("backtest")
            self.deps.logger.info(json.dumps({
                "check": result.get("check", {}).get("summary", ""),
                "backtest_status": backtest.status if backtest and hasattr(backtest, "status") else "skipped",
                "backtest_error": backtest.error[:300] if backtest and getattr(backtest, "error", None) else "",
                "trades": len(backtest.trades) if backtest and hasattr(backtest, "trades") else 0,
                "record": result["record"], "progressed": result["progressed"],
            }, ensure_ascii=False, indent=2))
        if result.get("status") == "error":
            self.deps.logger.error(" Loop --once failed: %s",
                                   result.get("error_code") or result.get("error"))
            return 1
        return 0

    def _run_continuous(self, orch, args) -> int:
        lock_path = orch.runtime.root / ".loop.lock"
        log_path = orch.runtime.logs_dir / f"loop-{date.today().isoformat()}.log"
        lock = self.deps.run_lock_cls(lock_path)
        try:
            lock.__enter__()
        except RuntimeError as exc:
            self.deps.logger.warning(" Cannot acquire run lock: %s", exc)
            return 2
        original_out, original_err = sys.stdout, sys.stderr
        tee_out = tee_err = None
        run_result = None
        try:
            tee_out = self.deps.tee_cls(sys.stdout, log_path)
            sys.stdout = tee_out
            tee_err = self.deps.tee_cls(sys.stderr, log_path)
            sys.stderr = tee_err
            run_result = orch.run(args.signals)
        finally:
            sys.stdout, sys.stderr = original_out, original_err
            for tee, original in ((tee_err, original_err), (tee_out, original_out)):
                if tee is not None and tee is not original:
                    close = getattr(tee, "close", None)
                    if close:
                        try:
                            close()
                        except Exception as exc:  # cleanup must not strand the run lock
                            self.deps.logger.warning(" Cannot close tee stream: %s", exc)
            lock.__exit__(*sys.exc_info())
        if isinstance(run_result, dict) and run_result.get("status") == "error":
            self.deps.logger.error(
                " Loop run failed: %s", run_result.get("error_code") or run_result.get("error"))
            return 1
        return 0
