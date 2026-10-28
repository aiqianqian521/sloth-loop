"""
v2.0 P2: Report generator — HTML visualization of loop run history.
Zero new dependencies: pure Python string formatting.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def generate_html_report(store, output_path: str | Path) -> Path:
    """Generate an HTML report from PatternStore data.

    Includes: rounds trend, failure mode distribution, health score chart,
    active rules list, recent runs table.
    """
    failures = store.load_failure_patterns()
    successes = store.load_success_patterns()
    rounds = store.get_rounds()
    runs = store.get_run_history(limit=10)
    qstats = store.get_queue_stats()
    last_l2 = store.get_last_l2_analysis()

    # ── Compute stats ──
    total_rounds = len(rounds)
    total_failures = len(failures)
    total_successes = len(successes)
    active_rules = store.get_active_exclusion_rules()

    # Mode distribution
    mode_counts: dict[str, int] = {}
    for f in failures:
        m = f.get("failure_mode", "UNKNOWN")
        mode_counts[m] = mode_counts.get(m, 0) + 1

    # Round trend data (last 20 rounds)
    round_labels = []
    excl_rates = []
    for r in rounds[-20:]:
        round_labels.append(f"R{r.get('id', '?')}")
        inp = max(r.get("input_count", 1), 1)
        excl_rates.append(round(r.get("excluded_count", 0) / inp * 100, 1))

    # Health score from last L2
    health = last_l2.get("health_score", 0) if last_l2 else 0

    # ── Build HTML ──
    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Loop v2.0 — Run Report</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; color: #333; }}
  h1 {{ border-bottom: 2px solid #4a90d9; padding-bottom: 0.3em; }}
  h2 {{ color: #4a90d9; margin-top: 1.5em; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1em; }}
  .stat {{ background: #f5f7fa; padding: 1em; border-radius: 8px; text-align: center; }}
  .stat .value {{ font-size: 2em; font-weight: bold; color: #4a90d9; }}
  .stat .label {{ font-size: 0.85em; color: #666; margin-top: 0.3em; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1em 0; }}
  th, td {{ padding: 0.5em 0.8em; text-align: left; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #f5f7fa; font-weight: 600; }}
  .bar {{ height: 20px; background: #4a90d9; border-radius: 3px; min-width: 2px; }}
  .bar-container {{ background: #eee; border-radius: 3px; width: 100%; }}
  .critical {{ color: #d32f2f; font-weight: bold; }}
  .major {{ color: #f57c00; }}
  .ok {{ color: #2e7d32; }}
  .footer {{ margin-top: 2em; padding-top: 1em; border-top: 1px solid #e0e0e0; font-size: 0.85em; color: #999; }}
</style>
</head>
<body>

<h1>Loop v2.0 — Run Report</h1>
<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Overview</h2>
<div class="stats">
  <div class="stat"><div class="value">{total_rounds}</div><div class="label">Total Rounds</div></div>
  <div class="stat"><div class="value">{total_failures}</div><div class="label">Failure Patterns</div></div>
  <div class="stat"><div class="value">{total_successes}</div><div class="label">Success Patterns</div></div>
  <div class="stat"><div class="value">{health:.0f}</div><div class="label">Health Score</div></div>
</div>

<h2>Failure Mode Distribution</h2>
<table>
<tr><th>Mode</th><th>Count</th><th>Distribution</th></tr>
"""
    for mode, count in sorted(mode_counts.items(), key=lambda x: -x[1]):
        pct = round(count / max(total_failures, 1) * 100)
        html += f"""<tr><td>{mode}</td><td>{count}</td>
<td><div class="bar-container"><div class="bar" style="width:{pct}%"></div></div></td></tr>
"""

    html += """</table>

<h2>Recent Rounds</h2>
<table>
<tr><th>Round</th><th>Input</th><th>Excluded</th><th>Passed</th><th>Excl Rate</th><th>Status</th></tr>
"""
    for r in reversed(rounds[-20:]):
        inp = max(r.get("input_count", 1), 1)
        excl = r.get("excluded_count", 0)
        rate = round(excl / inp * 100)
        status = r.get("status", "?")
        tag = "critical" if status == "error" else ("major" if status == "partial" else "ok")
        html += f"""<tr><td>R{r.get('id','?')}</td><td>{inp}</td><td>{excl}</td>
<td>{r.get('passed_count', 0)}</td><td>{rate}%</td>
<td class="{tag}">{status}</td></tr>
"""

    html += """</table>

<h2>Active Exclusion Rules</h2>
<table>
<tr><th>ID</th><th>Mode</th><th>Rule</th><th>Status</th></tr>
"""
    for r in active_rules[:20]:
        html += f"""<tr><td>{r.get('id','?')}</td><td>{r.get('failure_mode','?')}</td>
<td>{r.get('exclusion_rule','')[:80]}</td><td>{r.get('status','?')}</td></tr>
"""

    html += """</table>

<h2>Recent Runs</h2>
<table>
<tr><th>Run ID</th><th>Task</th><th>Rounds</th><th>Stop Reason</th><th>Health</th><th>Verdict</th></tr>
"""
    for r in runs[:10]:
        html += f"""<tr><td>{r.get('id','?')[:20]}</td><td>{r.get('task','?')}</td>
<td>{r.get('total_rounds',0)}</td><td>{r.get('stop_reason','?')[:40]}</td>
<td>{r.get('l2_health_score',0):.0f}</td><td>{r.get('verdict','?')}</td></tr>
"""

    html += f"""</table>

<div class="footer">
  Loop v2.0 Report Generator | Patterns: {total_failures} failures / {total_successes} successes |
  Queue: {qstats.get('total', 0)} problems ({qstats.get('by_status', {})})
</div>
</body></html>"""

    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    return p