"""PatternStore classify statics mixin - H1-P1h godfile split (behavior-preserving).

classify_failure / classify_success (@staticmethod) moved from memory_store.PatternStore
to this mixin; PatternStore inherits them. Pure functions on a trade dict; no self/imports.
"""
from __future__ import annotations


class PatternStoreClassify:
    """Trade classification statics (failure/success mode). Inherited by PatternStore."""

    # ── P0-1: 分类函数（从 orchestrator.py 移入，统一入口）──────

    @staticmethod
    def classify_failure(trade: dict) -> str:
        """将亏损交易归类到失败模式。"""
        r = (trade.get("failure_reason") or "").lower()
        if "extreme" in r:
            return "EXTREME_CHASE"
        if "blindspot" in r:
            return "ABSOLUTE_BLINDSPOT"
        if "stop" in r and "tp" in r:
            return "STOPPED_OUT_FIRST"
        if "direction" in r and "bias" in r:
            return "DIRECTION_BIAS"
        if "range" in r or "fakeout" in r:
            return "RANGING_FAKEOUT"
        return "INSUFFICIENT_EVIDENCE"

    @staticmethod
    def classify_success(trade: dict) -> str:
        """将盈利交易归类到成功模式。"""
        p = (trade.get("signal_pattern") or "").lower()
        if "trend" in p and ("follow" in p or "track" in p):
            return "TREND_FOLLOWING"
        if "mean" in p or "reversion" in p:
            return "MEAN_REVERSION"
        if "breakout" in p:
            return "BREAKOUT_CONFIRMED"
        if "range" in p:
            return "RANGING_REVERSAL"
        return "EVENT_DRIVEN"
