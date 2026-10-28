"""模式库上下文压缩 — 移植自 DSH compaction 引擎。

当模式库超过阈值时，自动生成结构化摘要，避免 prompt 膨胀。

移植自 DSH packages/compaction/ (compaction-basic)
"""

from __future__ import annotations

from collections import Counter


def compact_patterns(patterns: list[dict],
                     max_summary: int = 30,
                     group_by: str = "failure_mode") -> dict:
    """将模式列表压缩为结构化摘要。

    当模式库 > 100 条时调用，生成紧凑的统计摘要而非全量列表。

    Args:
        patterns: 模式字典列表
        max_summary: 摘要最大条数
        group_by: 分组字段 (failure_mode | rule_type | status)

    Returns:
        {"total": int, "by_group": {key: count}, "top": [...],
         "active_rules": int, "compacted": bool}
    """
    total = len(patterns)
    if total <= max_summary:
        return {
            "total": total,
            "by_group": {},
            "top": patterns,
            "active_rules": sum(1 for p in patterns
                               if p.get("exclusion_rule")),
            "compacted": False,
        }

    # 按 group_by 分组统计
    groups = Counter()
    for p in patterns:
        key = p.get(group_by, "unknown")
        groups[str(key)] += 1

    # Top-N: 按 impact_trades 或 occurrences 排序
    sorted_patterns = sorted(
        patterns,
        key=lambda p: p.get("impact_trades") or p.get("occurrences") or 0,
        reverse=True,
    )
    top = sorted_patterns[:max_summary]

    return {
        "total": total,
        "by_group": dict(groups.most_common(10)),
        "top": top,
        "active_rules": sum(1 for p in patterns if p.get("exclusion_rule")),
        "compacted": True,
    }


def compact_for_prompt(store, max_patterns: int = 20) -> str:
    """生成可嵌入 prompt 的紧凑模式摘要文本。

    用法: prompt += compact_for_prompt(store)
    """
    failures = store.load_failure_patterns()
    if len(failures) <= max_patterns:
        lines = []
        for f in failures:
            sp = f.get("signal_pattern", "?")
            mc = f.get("market_condition", "?")
            er = f.get("exclusion_rule", "")
            status = f.get("status", "?")
            line = f"  - {sp} @ {mc} [{status}]"
            if er:
                line += f" rule={er[:60]}"
            lines.append(line)
        return "Active patterns:\n" + "\n".join(lines)

    summary = compact_patterns(failures, max_summary=max_patterns)
    lines = [
        f"Pattern library: {summary['total']} total, "
        f"{summary['active_rules']} active exclusion rules",
        "Top failure modes:",
    ]
    for mode, count in summary["by_group"].items():
        lines.append(f"  - {mode}: {count}")
    lines.append(f"\nTop {max_patterns} patterns (by impact):")
    for p in summary["top"][:max_patterns]:
        sp = p.get("signal_pattern", "?")
        mc = p.get("market_condition", "?")
        it = p.get("impact_trades", 0)
        lines.append(f"  - {sp} @ {mc} (trades={it})")
    return "\n".join(lines)