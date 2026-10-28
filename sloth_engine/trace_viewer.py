"""Loop Wave2 — 本地 Trace Viewer（零依赖静态 HTML 生成器）。

不依赖 SaaS/JS 框架；读取 work_ooda/runs-*/events-*.jsonl 事件日志，
按 run → round → step 生成可读 HTML 复盘：状态、耗时、错误、上下文快照(含 hash)、
重试与 Learn 结果。
用法: python trace_viewer.py [--log PATH] [--out OUTPUT.html]
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from event_log import EventLog

STATUS_ICON = {"PASS": "ok", "FAIL": "err", "WARN": "warn", "SKIP": "skip", "START": "start"}
STATUS_LABEL = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN", "SKIP": "SKIP", "START": "START"}


def discover_logs(work_dir: Path) -> list[Path]:
    pattern = str(work_dir / "runs-*" / "events-*.jsonl")
    files = sorted(glob.glob(pattern), reverse=True)
    return [Path(f) for f in files]


def _esc(v) -> str:
    return html.escape(str(v))


def _short_ts(ts: str) -> str:
    return ts[-12:] if len(ts) > 12 else ts


def _render_ctx(ctx) -> str:
    if not isinstance(ctx, dict) or not ctx:
        return ""
    parts = []
    if ctx.get("context_type"):
        parts.append(f"<b>type</b>={_esc(ctx['context_type'])}")
    for k in ("input_hash", "config_hash"):
        if ctx.get(k):
            parts.append(f"<b>{k}</b>=<code>{_esc(ctx[k])}</code>")
    for k in ("pattern_ids", "correction_ids"):
        v = ctx.get(k)
        if v:
            parts.append(f"<b>{k}</b>=[{_esc(', '.join(str(x) for x in v))}]")
    if ctx.get("sources"):
        parts.append(f"<b>sources</b>={_esc(json.dumps(ctx['sources'], ensure_ascii=False))}")
    if ctx.get("summary"):
        parts.append(f"<i>{_esc(ctx['summary'])}</i>")
    return "<div class='ctx'>" + " &nbsp; ".join(parts) + "</div>"


def render_trace(logs: list[Path], title: str = "Loop Trace") -> str:
    rows: list[str] = []
    status_counts: dict[str, int] = {}
    total_events = 0

    for p in logs:
        elog = EventLog(p)
        events = elog.as_dicts()
        total_events += len(events)
        rounds = sorted({e.get("round", 0) for e in events if e.get("round", 0) > 0})
        row = [f"<tr class='log'><td colspan='5'><b>{_esc(p.parent.name)}/{_esc(p.name)}</b>"
               f" &mdash; {len(events)} events / {len(rounds)} round(s)"
               f" / task={_esc(elog._task_name or '')}</td></tr>"]

        for rnd in rounds:
            rev = [e for e in events if e.get("round") == rnd]
            has_fail = any(e.get("status") == "FAIL" for e in rev)
            has_skip = any(e.get("status") == "SKIP" for e in rev)
            icon = "err" if has_fail else ("skip" if has_skip else "ok")
            row.append(f"<tr class='rnd'><td colspan='5'>&nbsp;&nbsp;Round {rnd} "
                       f"<span class='{icon}'>{'&#10007;' if has_fail else ('&#8594;' if has_skip else '&#10003;')}</span>"
                       f" ({len(rev)} events)</td></tr>")
            for e in rev:
                st = e.get("status", "")
                status_counts[st] = status_counts.get(st, 0) + 1
                cls = STATUS_ICON.get(st, "")
                label = STATUS_LABEL.get(st, st)
                elapsed = ""
                if e.get("elapsed_ms"):
                    elapsed = f"{float(e['elapsed_ms']):.0f}ms"
                msg = _esc(e.get("message", ""))[:200]
                err = f"<div class='err'>{_esc(e.get('error', ''))}</div>" if e.get("error") else ""
                row.append(
                    f"<tr><td>{_short_ts(e.get('ts',''))}</td>"
                    f"<td class='st-{cls}'>{label}</td>"
                    f"<td>{_esc(e.get('step',''))}</td>"
                    f"<td>{msg}{err}{_render_ctx(e.get('ctx'))}</td><td>{elapsed}</td></tr>")
        rows.append("\n".join(row))

    summary_line = ", ".join(f"{k}:{v}" for k, v in sorted(status_counts.items()))

    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>{_esc(title)}</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:24px;color:#1a1a1a;background:#fafafa}}
 h1{{font-size:20px}} .meta{{color:#555;margin-bottom:12px}}
 table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px}}
 td{{border-bottom:1px solid #eee;padding:5px 8px;vertical-align:top}}
 tr.log td{{background:#e7ecff;font-weight:600}}
 tr.rnd td{{background:#f2f2f2;font-weight:600}}
 .st-ok{{color:#0a7}} .st-err{{color:#c00;font-weight:600}} .st-warn{{color:#c90}}
 .st-skip{{color:#888}} .st-start{{color:#06c}}
 .ctx{{color:#555;font-size:12px;margin-top:2px}}
 .err{{color:#c00;font-size:12px;white-space:pre-wrap}}
</style></head><body>
<h1>Loop Trace 复盘</h1>
<div class="meta">{_esc(title)} &middot; {total_events} events &middot; {summary_line}</div>
<table><thead><tr><th>time</th><th>status</th><th>step</th><th>detail / context</th><th>elapsed</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table></body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Loop local trace viewer (static HTML, zero deps)")
    ap.add_argument("--log", default=None, help="specific events JSONL path")
    ap.add_argument("--out", default=None, help="output HTML path")
    ap.add_argument("--title", default="Loop Trace")
    args = ap.parse_args(argv)

    if args.log:
        lp = Path(args.log)
        logs = [lp] if lp.exists() else []
        if not logs:
            print(f"  [trace] 找不到日志: {lp}", file=sys.stderr)
            return 1
    else:
        logs = discover_logs(_HERE.parent / "work_ooda")
    if not logs:
        print("  [trace] 没有找到事件日志 (work_ooda/runs-*/events-*.jsonl)", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else Path(logs[0]).parent / "trace.html"
    out.write_text(render_trace(logs, args.title), encoding="utf-8")
    n = sum(1 for p in logs for _ in open(p, encoding="utf-8"))
    print(f"  [trace] 已生成: {out}  ({len(logs)} 个日志, {n} 事件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
