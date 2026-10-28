"""Run artifact, handoff and diagnosis reporting boundary."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_log = logging.getLogger("sloth_engine.reporter")


def classify_stop(stop_reason: str) -> str:
    """Map an archive stop_reason to a coarse customer verdict.

    Order: ERR > WARN(no new/no progress) > STOP(completion/limit/budget) > OK.
    """
    low = (stop_reason or "").lower()
    if "error" in low:
        return "ERR"
    if "no new" in low or "no progress" in low or "no new patterns" in low:
        return "WARN"
    if "stop.completion" in low or "completed" in low or "time limit" in low or "budget" in low:
        return "STOP"
    return "OK"


def run_base_dir(project_path: str | None, task_name: str,
                 root: Path | None = None) -> Path:
    """Single source of truth for the projects/<domain>/<task> tree of a run.

    ``root`` defaults to the repository root; tests may redirect it.
    """
    name = task_name or "loop"
    seg = (project_path or "").split("/", 1)[0] if "/" in (project_path or "") else ""
    dom = seg if (seg and seg != name) else name
    base_root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    return ((base_root / "projects" / dom / name) if (dom != name)
            else (base_root / "projects" / name))


def claim_run_ts(project_path: str | None, task_name: str, timestamp: str,
                 root: Path | None = None) -> str:
    """Atomically claim a unique run-directory name for an archive.

    Two runs started in the same second would otherwise share one
    ``projects/<domain>/<task>/runs/<YYYYMMDD-HHMMSS>/`` directory and clobber
    each other's archived JSONs and REPORT (found by the F9 same-project
    concurrency probe, 2026-10-22). ``mkdir(exist_ok=False)`` makes the claim
    atomic across processes; on collision a ``-2``, ``-3`` ... suffix is added.
    The first claim keeps the historical 15-char ``YYYYMMDD-HHMMSS`` form, so
    existing paths and parsers are unaffected.
    """
    runs = run_base_dir(project_path, task_name, root) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    candidate, n = timestamp, 1
    while True:
        try:
            (runs / candidate).mkdir(exist_ok=False)
            return candidate
        except FileExistsError:
            n += 1
            candidate = "%s-%d" % (timestamp, n)


def _data_root() -> Path:
    """Repo-root `_data` fallback for raw-I/O archiving (injectable seam).

    A warm checkout carries a gitignored `_data/` that a clean clone lacks;
    reading the ambient dir flipped the "no raw I/O found" branch and drifted
    the recorded coverage by ~0.01pp with no source change (cycle-40 A). A
    named function keeps the path test-injectable.
    """
    return Path(__file__).resolve().parent.parent / "_data"


@dataclass(frozen=True)
class RunReportContext:
    total_rounds: int
    task_cfg: dict
    enable_ooda: bool
    zones: dict
    consumer: dict
    # Authoritative runtime run_id (from run_loop/_run_id). When None/empty the
    # archive falls back to a derived date-task-rounds-seq id for back-compat.
    run_id: str | None = None
    project_path: str = ""  # raw --project (e.g. "pm/pm-exit-buy-sym"); leading segment = domain
    run_ts: str | None = None  # subtask-instance timestamp YYYYMMDD-HHMMSS; enables projects/<task>/runs/<run_ts>/ tree


class RunReporter:
    def __init__(self, store, runtime):
        self.store = store
        self.runtime = runtime

    def write_state(self, ctx: RunReportContext, stop_reason: str = "", elapsed: float = 0) -> None:
        stats = self.store.get_queue_stats()
        last = self.store.get_last_l2_analysis()
        rounds = self.store.get_rounds()
        lines = [
            f"# Loop State — {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
            "## Run Summary", f"- Total rounds: {ctx.total_rounds}",
            f"- Stop reason: {stop_reason}", f"- Elapsed: {elapsed:.1f}s", "", "## L2 Health",
        ]
        if last:
            lines.extend([f"- Score: {last.get('health_score', '?')}/100",
                          f"- Trigger: {last.get('trigger_type', '?')}",
                          f"- Stop signal: {last.get('stop_signal') or 'none'}"])
        else:
            lines.append("- No L2 analysis yet")
        lines.extend(["", "## Problem Queue", f"- Total: {stats['total']}",
                      f"- By status: {stats.get('by_status', {})}",
                      f"- By type: {stats.get('by_type', {})}", "", "## Pattern Library",
                      f"- Failures: {len(self.store.load_failure_patterns())}",
                      f"- Active exclusion rules: {len(self.store.get_active_exclusion_rules())}",
                      "", "## Recent Rounds"])
        for row in rounds[-5:]:
            lines.append(f"- R{row.get('id','?')}: {row.get('status','?')} "
                         f"new_f={row.get('new_failures',0)} new_s={row.get('new_successes',0)}")
        lines.append("")
        path = self.runtime.state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        _log.info("[state] Written: %s", path)

    def recover_state(self) -> dict | None:
        path = self.runtime.state_file
        if not path.exists():
            return None
        info = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("- Total rounds: "):
                info["prev_rounds"] = int(line.split(":", 1)[1].strip())
            elif line.startswith("- Stop reason: "):
                info["prev_stop"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Score: "):
                info["prev_health"] = float(line.split(":", 1)[1].strip().rstrip("/100"))
        if info:
            _log.info("[state] Recovered: %s", info)
        return info or None

    def write_handoff(self, ctx: RunReportContext, stop_reason: str) -> None:
        stats = self.store.get_queue_stats()
        last = self.store.get_last_l2_analysis()
        handoff = {
            "run_id": f"{date.today().isoformat()}-{ctx.task_cfg.get('name','loop')}-{ctx.total_rounds:03d}",
            "timestamp": datetime.now().isoformat(), "total_rounds": ctx.total_rounds,
            "stop_reason": stop_reason,
            "l2_health": {"score": last.get("health_score", 0) if last else 0,
                          "trigger_type": last.get("trigger_type", "") if last else "",
                          "stop_signal": last.get("stop_signal") if last else None},
            "problem_queue": stats,
        }
        path = self.runtime.handoff_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
        _log.info("[handoff] Written: %s", path)

    def read_handoff(self) -> dict | None:
        path = self.runtime.handoff_file
        if not path.exists():
            return None
        handoff = json.loads(path.read_text(encoding="utf-8"))
        _log.info("[handoff] Recovered: run=%s health=%s rounds=%s",
                  handoff.get("run_id"), handoff.get("l2_health", {}).get("score", "?"),
                  handoff.get("total_rounds", "?"))
        return handoff

    def diagnose_stop(self, stop_reason: str, total_rounds: int) -> None:
        if any(token in stop_reason.lower() for token in ("max_rounds", "time limit", "token budget")):
            return
        # Keep a user-visible diagnosis independent of logger handler binding.
        print(f"\n[diagnosis] Stop reason: {stop_reason}")
        print(f"  Total rounds: {total_rounds}")
        rounds = self.store.get_rounds()
        if rounds and len(rounds) >= 3:
            rates = [row["excluded_count"] / row["input_count"] for row in rounds[-5:]
                     if row.get("input_count", 0) > 0]
            if rates:
                trend = "rising" if len(rates) >= 2 and rates[-1] > rates[0] else "falling" if len(rates) >= 2 and rates[-1] < rates[0] else "stable"
                average = sum(rates) / len(rates)
                print(f"  Exclusion rate ({len(rates)} rounds): {average:.0%} ({trend})")
                if average > 0.5:
                    print("    WARNING: High exclusion rate — rules may be over-aggressive or signal pool is stale")
        new_total = sum(row.get("new_failures", 0) + row.get("new_successes", 0)
                        for row in rounds)
        if new_total == 0 and total_rounds > 2:
            print("    WARNING: Zero new patterns across all rounds — signal pool may be exhausted or fully overlapped with exclusion rules")
        stats = self.store.get_queue_stats()
        if stats["total"]:
            print(f"  Problem queue: {stats['total']} items (P0)")
            for status, count in stats.get("by_status", {}).items():
                print(f"    {status}: {count}")
            if stats.get("by_type", {}).get("execution_error", 0):
                print("    WARNING: Execution errors present — run --doctor first")
        causes = []
        if "no new" in stop_reason.lower() or "no progress" in stop_reason.lower():
            causes.append("Signal pool possibly exhausted — try expanding candidate signals")
            active = self.store.get_active_exclusion_rules()
            if len(active) > 5:
                causes.append(f"Many exclusion rules active ({len(active)}) — try relaxing or cleaning stale rules")
        if "circuit" in stop_reason.lower() or "error" in stop_reason.lower():
            causes.append("Backtest script unstable — run --doctor to verify contract")
        if causes:
            print("\n  Likely causes:")
            for cause in causes:
                print(f"    -> {cause}")

    # Raw I/O artifacts worth preserving verbatim with each run snapshot.
    _RAW_IO_FILES = ("loop_backtest_input.json", "loop_backtest_output.json")

    def _archive_raw_io(self, ctx: "RunReportContext", target: Path) -> list[str]:
        """P1-6: copy the raw run input/output into the archive `data/` dir.

        Sources, in order: the task workspace `_data` dir (when the run used a
        workspace), the runtime io_dir, then the project root `_data`. Files are
        copied verbatim (no re-serialization) so the archived evidence is
        byte-identical to what the wrapper produced. Returns the copied names.
        """
        import shutil as _shutil
        candidates: list[Path] = []
        ws = getattr(ctx, "workspace", None) or getattr(self, "workspace", None)
        if ws:
            candidates.append(Path(ws) / "_data")
        io_dir = getattr(self.runtime, "io_dir", None)
        if io_dir:
            candidates.append(Path(io_dir))
        candidates.append(_data_root())
        copied: list[str] = []
        for name in self._RAW_IO_FILES:
            for base in candidates:
                src = base / name
                try:
                    if src.exists() and src.is_file():
                        _shutil.copyfile(src, target / name)
                        copied.append(name)
                        break
                except OSError:
                    continue
        if copied:
            _log.info("[archive] Raw I/O preserved: %s", ", ".join(copied))
        return copied


    def _resolve_run_id(self, ctx: "RunReportContext") -> str:
        """Authoritative run id: prefer ctx.run_id, else a derived fallback."""
        if ctx.run_id:
            return ctx.run_id
        sequence = len(self.store.get_run_history(limit=1000)) + 1
        return (f"{date.today().isoformat()}-"
                f"{ctx.task_cfg.get('name','loop')}-"
                f"{ctx.total_rounds:03d}-{sequence:03d}")

    def _tree_root(self) -> Path:
        """Root of the runtime ``projects/`` tree (O-3, cycle-29 A).

        Runtime artifacts -- ``projects/<task>/runs/<ts>/data`` and the per-run
        REPORT.md -- must obey ``runtime.root``, the same containment root as db
        / io / events / logs / state (CLAUDE.md section 4: run artifacts are
        written under runtime.root only).  Until cycle-29 the run_ts subtask tree
        was pinned to the *repository* root, so a run with
        ``runtime.root=<RUNTIME_ROOT>`` still wrote
        ``<repo>/projects/<task>/runs/...``; the 2026-10-25 full stress suite
        left ~50 task dirs in the repo that way.  Customer reports
        (``reports/<date>/REPORT.md``) stay project-norm and are deliberately not
        moved (CLAUDE.md 9.4).  Without a ``runtime`` section the default root
        *is* the repository, so the legacy on-disk layout is unchanged.
        """
        return Path(getattr(self.runtime, "root", None)
                    or Path(__file__).resolve().parent.parent)

    def _run_data_dir(self, ctx: "RunReportContext", run_id: str) -> Path:
        """Single source of truth for where a run's archived JSONs live.

        When run_ts is present the JSONs join the report under
        projects/<domain>/<task>/runs/<run_ts>/data/; otherwise they land in
        the runtime events dir. Both archive_run and write_customer_report use
        this so the report's data/ refs always resolve.
        """
        if getattr(ctx, "run_ts", None):
            base = run_base_dir(ctx.project_path, ctx.task_cfg.get("name") or "loop",
                                root=self._tree_root())
            return base / "runs" / ctx.run_ts / "data"
        events_dir = getattr(self.runtime, "events_dir", None)
        return (events_dir / run_id) if events_dir is not None else None

    def archive_run(self, ctx: RunReportContext, stop_reason: str, elapsed: float):
        # D-1/D-2: prefer the authoritative runtime run_id so the archive row,
        # index entry and circuit filename share one identity. Only fall back to
        # a derived date-task-rounds-seq id when the caller passed no run_id
        # (back-compat for callers building a bare RunReportContext).
        run_id = self._resolve_run_id(ctx)
        target = self._run_data_dir(ctx, run_id)
        target.mkdir(parents=True, exist_ok=True)
        contract = {"task": ctx.task_cfg, "ooda_enabled": ctx.enable_ooda,
                    "zones": ctx.zones, "consumer": ctx.consumer}
        rounds = self.store.get_rounds()
        failures, successes = self.store.load_failure_patterns(), self.store.load_success_patterns()
        for name, payload in {
            "contract.json": contract,
            "rounds.json": rounds,
            "patterns.json": {"failures": failures, "successes": successes},
        }.items():
            (target / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            problems = self.store.pull_problems(status="queued") + self.store.pull_problems(status="resolved")
        except Exception:
            problems = []
        (target / "problems.json").write_text(json.dumps(problems, ensure_ascii=False, indent=2), encoding="utf-8")
        # P1-6: also archive the raw run I/O (the wrapper input and the model
        # output), which live in the runtime io_dir and are overwritten every
        # run. Without this, the evidence behind an accumulated pattern is lost
        # -- only the 5 summary JSONs survived. Best-effort: a missing io_dir
        # or file never fails the archive.
        self._archive_raw_io(ctx, target)
        stats, last = self.store.get_queue_stats(), self.store.get_last_l2_analysis()
        summary = {
            "run_id": run_id, "task": ctx.task_cfg.get("name", "unknown"),
            "total_rounds": ctx.total_rounds, "elapsed_seconds": round(elapsed, 1),
            "stop_reason": stop_reason,
            "new_failures": sum(row.get("new_failures", 0) for row in rounds),
            "new_successes": sum(row.get("new_successes", 0) for row in rounds),
            "active_exclusion_rules": len(self.store.get_active_exclusion_rules()),
            "problem_queue_total": stats.get("total", 0),
            "l2_health_score": last.get("health_score", 0) if last else 0,
            "l2_trigger_type": last.get("trigger_type", "") if last else "",
            "problem_summary": json.dumps(stats, ensure_ascii=False),
            "decision_context": json.dumps({"stop_reason": stop_reason,
                                             "stop_signal": last.get("stop_signal") if last else None}, ensure_ascii=False),
        }
        summary["verdict"] = classify_stop(stop_reason)
        summary["created_at"] = datetime.now().isoformat()
        (target / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.store.save_run_history(summary)
        index_path = self.runtime.events_dir / "_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
        # D-2: idempotent index. When an authoritative run_id exists, replace
        # any prior entry with the same run_id instead of appending a duplicate.
        runs = list(index.get("runs", []))
        if ctx.run_id:
            runs = [r for r in runs if r.get("run_id") != ctx.run_id]
        runs.append(summary)
        index["runs"] = runs
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        _log.info("[archive] Run snapshot saved: %s", target)
        return target


    def _latest_archive_data_dir(self, tree_root, task: str):
        """Newest archived run's ``data/`` dir under ``<tree_root>/projects/<task>/runs/``.

        Used by the ``--report`` path (no run in this process): the report must
        cite a snapshot that is *really on disk* so the findings table's
        ``file:line:`` refs resolve (previously it cited ``<events>/<run_id>``,
        which the archive never creates).
        """
        runs = Path(tree_root) / "projects" / task / "runs"
        if not runs.is_dir():
            return None
        cands = sorted((d / "data") for d in runs.iterdir() if (d / "data").is_dir())
        return cands[-1] if cands else None

    def _resolve_input_ref(self, project_root: Path) -> str:
        """Project-relative path to the archived run input, or "" if unknown.

        Prefers the runtime io_dir (the authoritative <root>/_data directory
        holding loop_backtest_input.json). Falls back to the conventional
        <root>/_data/loop_backtest_input.json when io_dir is unavailable.
        """
        candidates = []
        io_dir = getattr(self.runtime, "io_dir", None)
        if io_dir:
            candidates.append(Path(io_dir) / "loop_backtest_input.json")
        candidates.append(project_root / "_data" / "loop_backtest_input.json")
        for cand in candidates:
            try:
                if Path(cand).exists():
                    return Path(cand).resolve().relative_to(project_root.resolve()).as_posix()
            except (ValueError, OSError):
                continue
        # No materialised input on disk yet: fall back to the conventional
        # location so the ref is still domain-correct and stable.
        try:
            return (Path(project_root) / "_data" / "loop_backtest_input.json").relative_to(project_root).as_posix()
        except (ValueError, OSError):
            return ""


    def write_customer_report(self, ctx: "RunReportContext", stop_reason: str = "", elapsed: float = 0):
        """Emit a customer-facing completion md report into project-norm dirs.

        project norms: projects/<task>/reports/<date>/REPORT.md. Reads the live
        store snapshot and delegates to sloth_engine.report_util. Returns path.

        Boundary (cycle-30 A): the *dated* tree is the human deliverable and
        stays in the project workspace (``engine.parent``, i.e. the repo) even
        when ``runtime.root`` is external -- unlike the run tree (O-3). Its
        evidence refs therefore cite the newest archived snapshot (§7) instead
        of a co-located ``data/``; any ``repo_leak`` style assertion only
        governs the run tree, not this deliverable.
        """
        from report_util import write_customer_report as _write
        latest = (self.store.get_run_history(limit=1) or [{}])[0]
        failures = self.store.load_failure_patterns()
        mode_counts = {}
        for f in failures:
            m = f.get("failure_mode", "UNKNOWN")
            mode_counts[m] = mode_counts.get(m, 0) + 1
        summary = dict(latest)
        # run_history stores the run id in the "id" column; normalise
        # it to run_id so report_util renders the real run id.
        if not summary.get("run_id") and summary.get("id"):
            summary["run_id"] = summary["id"]
        summary.setdefault("verdict", classify_stop(summary.get("stop_reason", "")))
        name = ctx.task_cfg.get("name") or "loop"
        engine = Path(__file__).resolve().parent
        seg = (ctx.project_path or "").split("/", 1)[0] if "/" in (ctx.project_path or "") else ""
        domain = seg if (seg and seg != name) else name
        kwargs = {"summary": summary, "failure_modes": mode_counts}
        if getattr(ctx, "run_ts", None):
            kwargs["run_ts"] = ctx.run_ts
            # O-3: the run_ts subtask tree is a runtime artifact -> same root as
            # the archived JSONs, and input_ref must be relative to that root.
            kwargs["runs_root"] = self._tree_root()
            _ref = self._resolve_input_ref(self._tree_root())
        else:
            _ref = self._resolve_input_ref(engine.parent)
        # P2-1: point input_ref at the real run input. The runtime io_dir is
        # the authoritative input location (<root>/_data, holding
        # loop_backtest_input.json), so reference it project-relatively when
        # resolvable; otherwise report_util falls back to its domain-aware
        # default. This replaces the historical hardcoded
        # projects/<task>/data/signals.json which never existed on disk.
        if _ref:
            kwargs["input_ref"] = _ref
        _data_dir = self._run_data_dir(ctx, self._resolve_run_id(ctx))
        if not getattr(ctx, "run_ts", None) and not (_data_dir and Path(_data_dir).exists()):
            # O-3 family (cycle-30 A): --report has no run in this process, so
            # _run_data_dir hands back <events>/<run_id> which the archive never
            # creates -> every data/ ref would dangle. Cite the newest archived
            # snapshot instead so the report's evidence refs resolve on disk.
            _data_dir = self._latest_archive_data_dir(self._tree_root(), name)
        if _data_dir is not None:
            kwargs["data_dir"] = _data_dir
        path = _write(project_root=engine.parent, task=name, domain=domain, **kwargs)
        _log.info("[report] Customer completion report: %s", path)
        return path

    def next_steps(self) -> None:
        opens = [item for item in self.store.load_failure_patterns() if item.get("status") == "open"]
        _log.info("\nNext steps:")
        _log.info("  1) python orchestrator.py --status        Review what was learned")
        if opens:
            _log.info("  2) python orchestrator.py --review         Review %d open failures", len(opens))
            _log.info("  3) Run again — excluded signals will be skipped automatically")
        else:
            _log.info("  2) Add new candidate signals to --signals file, then run again")
