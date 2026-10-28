"""L2 analysis boundary extracted from the orchestration composition root."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

_log = logging.getLogger("sloth_engine.l2")


@dataclass(frozen=True)
class L2Config:
    enabled: bool = True
    progress_window: int = 5
    periodic_every: int = 5
    queue_trigger: int = 5
    anomaly_trigger: bool = True
    stagnation_trigger: int = 3
    meta_every: int = 5
    consumer_min_queue: int = 3
    consumer_min_type: int = 3
    consumer_high_conf: int = 5
    consumer_max_suggestions: int = 10


class L2Analyzer:
    """Owns progress reading, trigger choice, health and suggestion analysis."""

    def __init__(self, store, config: L2Config):
        self.store = store
        self.config = config

    def read_progress(self, *, total_rounds: int, last_progress_round: int) -> dict:
        rounds = self.store.get_rounds()
        n = self.config.progress_window
        window = rounds[-n:] if len(rounds) >= n else rounds
        qs = self.store.get_queue_stats()
        return {
            "total_rounds": total_rounds,
            "window_size": len(window),
            "recent_new_patterns": sum(1 for r in window if r.get("new_failures", 0) + r.get("new_successes", 0) > 0),
            "recent_errors": sum(1 for r in window if r.get("status") == "error"),
            "recent_all_excluded": sum(1 for r in window if "all_excluded" in (r.get("notes") or "")),
            "queue_total": qs["total"],
            "queue_recurring": qs.get("by_status", {}).get("recurring", 0),
            "queue_l2_pending": qs.get("by_status", {}).get("l2_pending", 0),
            "stagnation_rounds": total_rounds - last_progress_round,
        }

    def check_triggers(self, progress: dict, *, total_rounds: int) -> str | None:
        cfg = self.config
        if not cfg.enabled:
            return "periodic" if cfg.meta_every and total_rounds % cfg.meta_every == 0 else None
        triggers: list[tuple[str, int]] = []
        if cfg.periodic_every and total_rounds % cfg.periodic_every == 0:
            triggers.append(("periodic", 1))
        if progress["queue_total"] >= cfg.queue_trigger:
            triggers.append(("queue_accumulation", 2 if progress["queue_recurring"] > 0 else 1))
        if cfg.anomaly_trigger:
            if progress["recent_errors"] >= 2:
                triggers.append(("anomaly_signal", 3))
            elif progress["recent_all_excluded"] >= 2:
                triggers.append(("anomaly_signal", 2))
            elif progress["stagnation_rounds"] >= cfg.stagnation_trigger:
                triggers.append(("anomaly_signal", 1))
        return max(triggers, key=lambda item: item[1])[0] if triggers else None

    def health_check(self, progress: dict, trigger_type: str) -> dict:
        progress_score = min(30, progress["recent_new_patterns"] * 15)
        total_q = max(1, progress["queue_total"])
        error_score = max(0, 30 - (progress["queue_recurring"] / total_q) * 60)
        qs = self.store.get_queue_stats()
        resolved = qs.get("by_status", {}).get("resolved", 0)
        fix_score = min(20, (resolved / total_q) * 40)
        rounds = self.store.get_rounds()
        n = self.config.progress_window
        window = rounds[-n:] if len(rounds) >= n else rounds
        types = set()
        for row in window:
            notes = (row.get("notes") or "").lower()
            if "failure_mode" in notes:
                types.add("failure")
            if "success" in notes:
                types.add("success")
        diversity_score = min(20, len(types) * 10)
        health = max(0, min(100, round(progress_score + error_score + fix_score + diversity_score)))
        last = self.store.get_last_l2_analysis()
        stop_signal = "suggest_terminate" if last and last.get("health_score", 100) < 40 and health < 40 else None
        if stop_signal is None and health < 25:
            stop_signal = "escalate"
        recent = rounds[-3:]
        pass_rates = [r.get("passed_count", 0) / max(r.get("input_count", 1), 1) for r in recent]
        inflection = "declining_pass_rate" if len(pass_rates) == 3 and pass_rates[0] > pass_rates[1] > pass_rates[2] else None
        problems = self.store.pull_problems(status=["queued", "recurring"], min_count=0)
        signatures = {p.get("error_signature") for p in problems[:20] if p.get("error_signature")}
        if len(signatures) >= 3 and health >= 70:
            inflection = inflection or "new_error_types"
        analysis = {
            "trigger_type": trigger_type, "health_score": health,
            "progress_speed": round(progress_score, 1), "error_recurrence": round(error_score, 1),
            "fix_effectiveness": round(fix_score, 1), "pattern_diversity": round(diversity_score, 1),
            "stop_signal": stop_signal,
            "summary": f"health={health} progress={progress_score:.0f} error={error_score:.0f} fix={fix_score:.0f} diversity={diversity_score:.0f}"
                       + (f" inflection={inflection}" if inflection else ""),
            "inflection_warning": inflection,
        }
        self.store.insert_l2_analysis(analysis)
        return analysis

    def meta_analyze(self, *, trigger_type: str = "periodic",
                     progress_data: dict | None = None) -> dict:
        freq = self.store.failure_mode_frequency()
        frequent = {mode: count for mode, count in freq.items() if count >= 3}
        recommendations = [f"Failure mode {mode} appeared {count} times — consider upgrading to hard exclusion"
                           for mode, count in frequent.items()]
        opens = [item for item in self.store.load_failure_patterns() if item.get("status") == "open"]
        if opens:
            recommendations.append(f"{len(opens)} open failures pending review — run --review")
        qs = self.store.get_queue_stats()
        by_level_hook: dict[str, list[dict]] = {}
        by_type: dict[str, list[dict]] = {}
        has_metadata = False
        if qs["total"] >= self.config.consumer_min_queue:
            for problem in self.store.pull_problems(status="queued", min_count=0):
                context = problem.get("context") or {}
                if isinstance(context, str):
                    try:
                        context = json.loads(context)
                    except (TypeError, json.JSONDecodeError):
                        context = {}
                level, hook = context.get("target_level", "?"), context.get("target_hook", "?")
                if level != "?" and hook != "?":
                    has_metadata = True
                    by_level_hook.setdefault(f"{level}:{hook}", []).append(problem)
                else:
                    by_type.setdefault(problem.get("type", "unknown"), []).append(problem)
            if by_level_hook:
                recommendations.append(
                    f"[CONTEXT] {sum(len(items) for items in by_level_hook.values())} "
                    f"problems in {len(by_level_hook)} level:hook groups")
            for key, problems in sorted(by_level_hook.items()):
                confidence = "HIGH" if len(problems) >= self.config.consumer_high_conf else "MEDIUM"
                severities = {problem.get("severity", "") for problem in problems}
                severity = "CRIT" if "critical" in severities else "MAJ" if "major" in severities else "MIN"
                hook = key.split(":", 1)[1]
                hints = {
                    "execute": "execution tracing / subprocess isolation",
                    "verify": "external verification / test suite integration",
                    "meta_analyze": "pattern detection / batch processing",
                    "problem_dispatch": "priority scheduling / profile routing",
                    "on_round_start": "exclusion rule quality / signal validation",
                    "on_round_end": "result recording / pattern classification",
                    "efficiency_tracker": "efficiency baseline / optimization",
                    "problem_resolution": "remediation / fix verification",
                }
                recommendations.append(
                    f"[{confidence}][{severity}] {key} ({len(problems)}x) — {hints.get(hook, 'general improvement')}")
                sample = str(problems[0].get("evidence") or "")[:80]
                if sample:
                    recommendations.append(f"    sample: {sample}")
            for problem_type, problems in sorted(by_type.items()):
                if len(problems) >= self.config.consumer_min_type:
                    confidence = "HIGH" if len(problems) >= self.config.consumer_high_conf else "MEDIUM"
                    recommendations.append(f"[{confidence}][NO-META] {len(problems)}x {problem_type} — add producer metadata")
        limited = recommendations[:self.config.consumer_max_suggestions]
        if len(recommendations) > self.config.consumer_max_suggestions:
            limited.append(f"... 还有 {len(recommendations) - self.config.consumer_max_suggestions} 条建议，运行 --status 查看")
        return {
            "analysis_date": date.today().isoformat(), "trigger_type": trigger_type,
            "progress": progress_data or {}, "failure_mode_frequency": freq,
            "frequent_modes": list(frequent), "recommendations": limited,
            "queue_stats": qs, "queue_analyzed": qs["total"] >= self.config.consumer_min_queue,
            "has_metadata": has_metadata,
            "by_level_hook": {key: len(items) for key, items in by_level_hook.items()},
            "by_type": {key: len(items) for key, items in by_type.items()},
        }

    def auto_suggest(self, meta_result: dict) -> list[dict]:
        suggestions = []
        patterns = self.store.load_failure_patterns()
        existing = {item.get("exclusion_rule", "") for item in self.store.get_active_exclusion_rules()}
        for mode, count in meta_result.get("failure_mode_frequency", {}).items():
            matches = [item for item in patterns if item.get("failure_mode") == mode
                       and item.get("status") in ("open", "monitoring")]
            if count < 3 or not matches:
                continue
            latest = matches[-1]
            rule = self.store.make_rule(latest.get("signal_pattern", mode), latest.get("market_condition", ""), scope="combo")
            if rule in existing:
                continue
            suggestion = {
                "id": f"L2S-{date.today().strftime('%Y%m%d')}-{len(suggestions)+1:03d}",
                "category": "pattern_exclusion", "priority": "medium",
                "suggestion": f"Add exclusion rule: {rule}", "auto_applicable": 1,
                "status": "pending", "target_param": f"exclusion_rule:{latest.get('id', '')}",
                "old_value": "", "new_value": rule,
                "confidence": min(0.3 + count * 0.1, 1.0),
            }
            self.store.insert_l2_suggestion(suggestion)
            suggestions.append(suggestion)
        _log.info("L2 auto-suggest: generated %d drafts", len(suggestions))
        return suggestions

    def verify_suggestions(self) -> dict:
        verified = reverted = kept = 0
        with self.store.transaction() as conn:
            conn.row_factory = __import__("sqlite3").Row
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM l2_suggestions WHERE status='applied' AND applied_at IS NOT NULL")]
            analyses = self.store.get_l2_analysis(limit=10)
            current = analyses[0] if analyses else None
            previous = analyses[1] if len(analyses) > 1 else None
            for row in rows:
                if not current or not previous:
                    kept += 1
                    continue
                delta = current.get("health_score", 0) - previous.get("health_score", 0)
                confidence = row.get("confidence", 0.5) or 0.5
                if delta > 5:
                    conn.execute("UPDATE l2_suggestions SET status='confirmed', confidence=?, verify_result='improved' WHERE id=?",
                                 (min(confidence + 0.2, 1.0), row["id"]))
                    verified += 1
                elif delta < -5:
                    conn.execute("UPDATE l2_suggestions SET status='reverted', confidence=?, verify_result='worsened' WHERE id=?",
                                 (max(confidence - 0.3, 0.0), row["id"]))
                    target_id = str(row.get("target_param") or "").replace("exclusion_rule:", "")
                    if target_id:
                        conn.execute("UPDATE failure_patterns SET status='open', exclusion_rule=? WHERE id=?",
                                     (row.get("old_value", ""), target_id))
                    reverted += 1
                else:
                    kept += 1
        result = {"verified": verified, "reverted": reverted, "kept": kept}
        _log.info("L2 verify: %s", result)
        return result
