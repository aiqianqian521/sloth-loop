"""Inspection service for Loop's event-log inspection CLI commands.

W2-BOUNDARY-01 / H2 Slice 1-PATH (Z-β): per-instance replacement for the
``orchestrator._ACTIVE_INSPECT_WORK_DIR`` module-global singleton. Holding the
work_dir on an instance that the composition root injects lets two CLIs (or a
CLI and a test) inspect two run trees concurrently without one mutating the
other's global state. The method bodies are byte-equivalent to the former
orchestrator free functions; only the work_dir source (instance attr vs module
global) and call targets (self.* vs module-level) changed.
"""
from __future__ import annotations

import logging
from pathlib import Path


class InspectionService:
    """Per-run-tree inspector for JSONL event logs.

    The inspect/handler methods are byte-equivalent to the orchestrator free
    functions that they replace; they only rebind the work_dir from a module
    global to ``self.work_dir`` (set by the composition root at launch time).
    """

    def __init__(self, work_dir, logger=None):
        self.work_dir = Path(work_dir)
        self._log = logger if logger is not None else logging.getLogger("inspection")

    def find_latest_log(self) -> Path | None:
        """查找最新的 JSONL 事件日志文件。"""
        import glob as _glob
        work_dir = self.work_dir
        pattern = str(work_dir / "runs-*" / "events-*.jsonl")
        files = sorted(_glob.glob(pattern), reverse=True)
        return Path(files[0]) if files else None


    def inspect_handler(self, mode: str, round_num: int | None):
        """--inspect 命令分发。"""
        if mode == "runs":
            self.inspect_runs()
        elif mode == "round":
            if round_num is None:
                self._log.info("[inspect] 需要 --round N 指定轮次")
                return
            self.inspect_round(round_num)
        elif mode == "timeline":
            self.inspect_timeline()
        elif mode == "last-error":
            self.inspect_last_error()



    def trace_handler(self, log_path: str | None = None) -> None:
        """--trace: 生成本地 HTML 复盘报告（零依赖静态查看器）。"""
        from trace_viewer import render_trace, discover_logs
        work_dir = self.work_dir
        if log_path:
            lp = Path(log_path)
            logs = [lp] if lp.exists() else []
            if not logs:
                self._log.info(f"[trace] 找不到日志: {log_path}")
                return
        else:
            logs = discover_logs(work_dir)
        if not logs:
            self._log.info("[trace] 没有找到事件日志 (work_ooda/runs-*/events-*.jsonl)")
            return
        out = Path(logs[0]).parent / "trace.html"
        out.write_text(render_trace(logs, f"Loop Trace {logs[0].parent.name}"), encoding="utf-8")
        n = sum(1 for p in logs for _ in open(p, encoding="utf-8"))
        self._log.info(f"[trace] 已生成: {out}  ({len(logs)} 个日志, {n} 事件)")


    def inspect_runs(self):
        """列出所有 JSONL 日志文件及其摘要。"""
        import glob as _glob
        from event_log import EventLog

        work_dir = self.work_dir
        pattern = str(work_dir / "runs-*" / "events-*.jsonl")
        files = sorted(_glob.glob(pattern), reverse=True)

        if not files:
            self._log.info("[inspect] 没有找到 JSONL 日志文件 (work_ooda/runs-*/events-*.jsonl)")
            return

        self._log.info(f"\n  事件日志 — {len(files)} 个文件")
        self._log.info("  " + "─" * 62)
        for i, f in enumerate(files, 1):
            p = Path(f)
            elog = EventLog(p)
            s = elog.get_summary()
            rounds = s["rounds"]
            fails = s["status_counts"].get("FAIL", 0)
            warns = s["status_counts"].get("WARN", 0)
            total = s["total_events"]

            # 提取日期和任务名
            ts_str = p.stem.replace("events-", "") if p.stem.startswith("events-") else p.stem
            fail_tag = f" [FAIL:{fails}]" if fails > 0 else ""
            warn_tag = f" [WARN:{warns}]" if warns > 0 else ""
            self._log.info(f"  [{i}] {p.parent.name}/{p.name}")
            self._log.info(f"      轮次: {rounds} · 事件: {total}{fail_tag}{warn_tag}")
            if s["failures"]:
                for err in s["failures"][:3]:
                    self._log.info(f"      ✗ R{err['round']} {err['step']}: {err['error'][:80]}")
        self._log.info("  " + "─" * 62)


    def inspect_round(self, round_num: int):
        """查看指定轮次的所有事件。"""
        from event_log import EventLog

        log_path = self.find_latest_log()
        if log_path is None:
            self._log.info("[inspect] 没有找到 JSONL 日志文件")
            return

        elog = EventLog(log_path)
        events = elog.get_round_events(round_num)

        if not events:
            self._log.info(f" 未找到第 {round_num} 轮的事件（可用轮次: {self._list_rounds(elog)}）")
            return

        STATUS_ICON = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "→", "START": "▶"}
        self._log.info(f"\n  第 {round_num} 轮事件 — {elog._task_name or '(无任务名)'}")
        self._log.info(f"  日志: {log_path.parent.name}/{log_path.name}")
        self._log.info("  " + "─" * 80)
        for e in events:
            icon = STATUS_ICON.get(e.status, "?")
            ts_short = e.ts[-12:] if len(e.ts) > 12 else e.ts  # HH:MM:SS.mmm
            step_label = e.step.ljust(14)
            msg = e.message[:70] if e.message else ""
            err = f"  ERROR: {e.error[:80]}" if e.error else ""
            elapsed = f"  ({e.elapsed_ms:.0f}ms)" if e.elapsed_ms > 0 else ""
            self._log.info(f"  {ts_short} [{icon} {e.status}] {step_label} {msg}{err}{elapsed}")
        self._log.info("  " + "─" * 80)


    def inspect_timeline(self):
        """显示所有轮次的时间线摘要。"""
        from event_log import EventLog

        log_path = self.find_latest_log()
        if log_path is None:
            self._log.info("[inspect] 没有找到 JSONL 日志文件")
            return

        elog = EventLog(log_path)
        rounds = sorted(set(e.round for e in elog._events if e.round > 0))
        if not rounds:
            self._log.info("[inspect] 没有轮次数据")
            return

        self._log.info(f"\n  时间线 — {elog._task_name or '(无任务名)'}  ({len(rounds)} 轮)")
        self._log.info(f"  日志: {log_path.parent.name}/{log_path.name}")
        self._log.info("  " + "─" * 80)

        for rnd in rounds:
            revents = elog.get_round_events(rnd)
            failures = [e for e in revents if e.status == "FAIL"]
            skips = [e for e in revents if e.status == "SKIP"]
            status = "✗" if failures else ("→" if skips else "✓")

            # 计算轮次耗时
            start_evt = next((e for e in revents if e.status == "START" and "round" in e.step), None)
            end_evts = [e for e in revents if e.status != "START" and e.elapsed_ms > 0]
            total_ms = sum(e.elapsed_ms for e in end_evts)

            act_evt = next((e for e in revents if e.step in ("act:result", "act") and e.status != "START"), None)
            act_msg = ""
            if act_evt:
                act_msg = f" | act: {act_evt.status}"

            self._log.info(f"  [{status}] R{rnd}: {len(revents)} events{act_msg} | {total_ms:.0f}ms")
            for f in failures:
                self._log.info(f"       ✗ {f.step}: {f.error[:100]}")
        self._log.info("  " + "─" * 80)


    def inspect_last_error(self):
        """显示最近一次失败事件的详情。"""
        from event_log import EventLog

        log_path = self.find_latest_log()
        if log_path is None:
            self._log.info("[inspect] 没有找到 JSONL 日志文件")
            return

        elog = EventLog(log_path)
        last_fail = elog.last_event_by_status("FAIL")
        if last_fail is None:
            self._log.info("[inspect] 没有找到 FAIL 事件 ✓ 全部通过")
            return

        # 找该轮次上下文
        round_events = elog.get_round_events(last_fail.round)
        steps_before = [e for e in round_events if e.seq < last_fail.seq and e.status not in ("START",)]

        self._log.info(f"\n  最近失败")
        self._log.info("  " + "─" * 62)
        self._log.info(f"  时间:    {last_fail.ts}")
        self._log.info(f"  任务:    {last_fail.task}")
        self._log.info(f"  轮次:    {last_fail.round}")
        self._log.info(f"  步骤:    {last_fail.step}")
        self._log.info(f"  错误:    {last_fail.error}")

        # 上下文：失败前经过了哪些步骤
        if steps_before:
            self._log.info(f"  上下文 (失败前 {len(steps_before)} 步):")
            for s in steps_before[-5:]:
                self._log.info(f"    {s.status} {s.step}: {s.message[:80]}")
        self._log.info("  " + "─" * 62)


    def _list_rounds(self, elog) -> list[int]:
        return sorted(set(e.round for e in elog._events if e.round > 0))
