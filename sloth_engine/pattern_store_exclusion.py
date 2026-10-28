"""PatternStore 排除检查 mixin — H1-P1d godfile 拆分（行为保持）。

check_exclusion/_match/make_rule 原为 memory_store.PatternStore 方法，移至本 mixin；
PatternStore 继承后公共 API 不变。零模块级依赖（仅 self.* + builtins）。
"""
from __future__ import annotations


class PatternStoreExclusion:
    """排除规则匹配。由 PatternStore 继承。"""

    def check_exclusion(self, signals: list[dict],
                        warn_namespace: bool = True) -> dict:
        """Pre-backtest exclusion check. Deduplicates signals against active rules.
        Set warn_namespace=False to suppress repeated namespace mismatch warnings."""
        rules = self.get_active_exclusion_rules()
        passed, excluded = [], []
        for s in signals:
            hit = None
            for r in rules:
                if self._match(s, r):
                    hit = r
                    break
            if hit:
                excluded.append({
                    "signal": s,
                    "blocked_by": hit["id"],
                    "failure_mode": hit.get("failure_mode"),
                    "rule": hit.get("exclusion_rule"),
                })
            else:
                passed.append(s)
        # Warn if active rules exist but zero hits — possible namespace mismatch (once)
        if warn_namespace and rules and len(excluded) == 0 and signals:
            import sys as _sys
            print(f"[warn] check_exclusion: {len(rules)} active exclusion rules, "
                  f"but {len(signals)} candidates had ZERO hits. "
                  "Confirm signal labels match knowledge base labels.", file=_sys.stderr)
        return {
            "input_count": len(signals),
            "excluded_count": len(excluded),
            "passed_count": len(passed),
            "passed": passed,
            "excluded": excluded,
            "summary": f"in={len(signals)} excl={len(excluded)} pass={len(passed)}",
            "rules_active": len(rules),
            "rules_hit": len(excluded),
        }

    @staticmethod
    def _match(signal: dict, rule: dict) -> bool:
        """Exclusion rule matching with alias support.

        Two granularity levels via exclusion_rule format:
          "ExtremeChase"              → pattern-level: block in ALL market conditions
          "ExtremeChase @ H240Trend"  → combo-level: block only in this market (default, safer)

        M1 fix: signal_pattern matching also checks signal['aliases'] list,
        enabling cross-namespace matching without changing knowledge base labels.
        """
        raw = (rule.get("exclusion_rule") or "").strip()
        if not raw:
            return False

        # Collect all matchable labels: primary pattern + aliases
        labels = [str(signal.get("signal_pattern") or "")]
        for alias in signal.get("aliases") or []:
            labels.append(str(alias))

        mc = (signal.get("market_condition") or "").lower()

        if "@" in raw:
            pat, _, mkt = raw.partition("@")
            pat, mkt = pat.strip().lower(), mkt.strip().lower()
            if not pat:
                return False
            pattern_match = any(pat in lbl.lower() or lbl.lower() in pat for lbl in labels)
            market_match = bool(mkt) and (mkt in mc or mc in mkt)
            return pattern_match and market_match

        pat = raw.lower()
        return any(pat in lbl.lower() or lbl.lower() in pat for lbl in labels)

    @staticmethod
    def make_rule(signal_pattern: str, market_condition: str = "",
                  scope: str = "combo") -> str:
        """生成排除规则字符串。scope: combo(组合级, 默认) | pattern(模式级)。"""
        sp = (signal_pattern or "").strip()
        if scope == "pattern" or not market_condition:
            return sp
        return f"{sp} @ {str(market_condition).strip()}"
