"""
v2.0 P2: Dynamic prompt renderer — generates agent prompts with current
PatternStore state injected. Zero new dependencies: uses str.format.

Usage:
    from prompt_renderer import render_prompt
    prompt = render_prompt(store, "pre-backtest")
    # → prompt string with current metrics injected
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

_AGENT_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "agent-prompts"


def _get_state_snapshot(store) -> dict:
    """Collect current PatternStore state for prompt injection."""
    failures = store.load_failure_patterns()
    successes = store.load_success_patterns()
    active = store.get_active_exclusion_rules()
    rounds = store.get_rounds()
    qstats = store.get_queue_stats()

    freq = {}
    for f in failures:
        m = f.get("failure_mode", "UNKNOWN")
        freq[m] = freq.get(m, 0) + 1

    # Top failure modes
    top_modes = sorted(freq.items(), key=lambda x: -x[1])[:3]

    return {
        "total_rounds": len(rounds),
        "total_failures": len(failures),
        "total_successes": len(successes),
        "active_rules": len(active),
        "active_rule_ids": [r.get("id", "") for r in active[:5]],
        "open_failures": len([f for f in failures if f.get("status") == "open"]),
        "confirmed_successes": len([s for s in successes if s.get("status") == "confirmed"]),
        "top_failure_modes": ", ".join(f"{m}({c}x)" for m, c in top_modes),
        "queue_total": qstats.get("total", 0),
        "queue_queued": qstats.get("by_status", {}).get("queued", 0),
        "stale_rules": len([r for r in active if r.get("impact_trades", 0) == 0]),
        "date": date.today().isoformat(),
        "time": datetime.now().strftime("%H:%M"),
    }


def render_prompt(store, template_name: str) -> str:
    """Render a named prompt template with current state injected.

    Args:
        store: PatternStore instance
        template_name: "pre-backtest" | "post-backtest" | "meta-loop"

    Returns:
        Rendered prompt string with {state} placeholders filled.
    """
    state = _get_state_snapshot(store)
    template_file = _AGENT_PROMPTS_DIR / f"{template_name}.md"

    if not template_file.exists():
        return f"[error] Template not found: {template_file}"

    base = template_file.read_text(encoding="utf-8")

    # Inject state summary at the top
    header = f"""<!-- v2.0 Dynamic Context (auto-generated {state['date']} {state['time']}) -->
> Current State: {state['total_rounds']} rounds | {state['total_failures']} failures | {state['active_rules']} active rules
> Top failures: {state['top_failure_modes'] or 'none'}
> Open: {state['open_failures']} | Confirmed: {state['confirmed_successes']} | Queue: {state['queue_total']}
> Stale rules (0 hits): {state['stale_rules']}
---
"""

    return header + base


def render_context_block(store) -> str:
    """Render a compact context block for embedding in arbitrary prompts.

    Returns a markdown block that can be appended to any agent prompt.
    """
    state = _get_state_snapshot(store)
    return f"""
<!-- LOOP CONTEXT -->
- Rounds completed: {state['total_rounds']}
- Failure patterns: {state['total_failures']} ({state['open_failures']} open)
- Active exclusion rules: {state['active_rules']} (IDs: {', '.join(state['active_rule_ids'][:3])})
- Top failure modes: {state['top_failure_modes'] or 'none'}
- Problem queue: {state['queue_total']} total, {state['queue_queued']} queued
- Stale rules with 0 hits: {state['stale_rules']}
<!-- /LOOP CONTEXT -->
"""