"""P0-3: 上下文压缩管线 — 对标 Claude Code 四层压缩的简化版。

实现四层压缩管线:
1. Snip Compact: 物理删除最旧的N条消息，释放token
2. Auto-Compact: 超过阈值时触发摘要压缩

熔断器: 连续3次 auto-compact 失败 → 永久停止
token估算: 保守近似 ~4 chars/token (英文) / ~1.5 chars/token (中文)

对标 CC:
- Snip Compact  ? Layer1: 物理删除旧消息
- Auto-Compact ? Layer4: 全量对话摘要（简化版——调用方注入compactor_fn而非fork Claude对话）
- 熔断器       ? MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES=3
- 阈值         ? effectiveWindow - 13000 (对标 AUTOCOMPACT_BUFFER_TOKENS)
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from loop_state_enums import RecoveryState
from telemetry import report_token_usage

_log = logging.getLogger("sloth_engine.context-compactor")

# ── Token 估算 ────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """保守的 token 估算（偏向高估，提前触发压缩）。

    ASCII: ~4 chars/token
    CJK:   ~1.5 chars/token
    """
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    cjk_chars = len(text) - ascii_chars
    return int(ascii_chars / 4 + cjk_chars / 1.5)


# ── 上下文压缩器 ────────────────────────────────────────

class ContextCompactor:
    """上下文压缩管线。

    Args:
        effective_window: 有效上下文窗口 (contextWindow - min(modelMaxOutput, 20000))
        compact_fn: 压缩函数 — 接收 messages list，返回 (summary_text, freed_tokens)
                    对标 CC: auto-compact forks Claude conversation to summarize
        recovery_state: RecoveryState 实例，用于熔断器追踪
    """

    # 对标 CC 常量
    AUTOCOMPACT_BUFFER = 13_000   # 触发阈值: effectiveWindow - 13000
    BLOCKING_BUFFER = 3_000       # 硬性阻塞: effectiveWindow - 3000
    MAX_COMPACT_FAILURES = 3      # 熔断器阈值

    def __init__(
        self,
        effective_window: int,
        compact_fn: Optional[Callable] = None,
        recovery_state: Optional[RecoveryState] = None,
    ):
        self.effective_window = effective_window
        self.compact_fn = compact_fn
        self.rs = recovery_state or RecoveryState()
        self._history: list[str] = []
        # Optional Codex-style fragment collector (opt-in). When set, fragments
        # are rendered through a FragmentBudget and appended as a Layer-0
        # context block before the numeric compaction layers run.
        # C6 (cycle-6 A4): checkpoint chaining - the latest compaction
        # summary is carried into the next compaction so accumulated
        # context is not lost when the history is replaced.
        self._previous_summary: Optional[str] = None
        self.fragment_collector = None
        self._fragment_budget_tokens = max(256, effective_window // 8)
  # 简化: 文本消息列表

    def append_message(self, text: str):
        """追加一条消息到历史。"""
        self._history.append(text)

    def append_messages(self, texts: list[str]):
        """批量追加。"""
        self._history.extend(texts)

    @property
    def estimated_tokens(self) -> int:
        """当前历史总 token 估算。"""
        return sum(estimate_tokens(m) for m in self._history)

    @property
    def auto_compact_threshold(self) -> int:
        """触发 auto-compact 的阈值。"""
        return max(0, self.effective_window - self.AUTOCOMPACT_BUFFER)

    @property
    def blocking_threshold(self) -> int:
        """硬性阻塞阈值——不应达到此值。"""
        return max(0, self.effective_window - self.BLOCKING_BUFFER)

    def needs_compaction(self) -> bool:
        """是否应该触发压缩。"""
        if self.rs.auto_compact_circuit_open():
            return False  # 熔断器已断开
        return self.estimated_tokens >= self.auto_compact_threshold

    def at_blocking_limit(self) -> bool:
        """是否已达到硬性阻塞限制。"""
        return self.estimated_tokens >= self.blocking_threshold

    # ── Snip Compact (Layer1) ──────────────────────────

    def snip_compact(self, keep_last: int = 20) -> int:
        """物理删除最旧的消息，只保留最近 `keep_last` 条。

        对标 CC: 物理删除旧消息，返回边界消息。

        Returns:
            freed_tokens: 估算释放的 token 数
        """
        if len(self._history) <= keep_last:
            return 0

        old_tokens = self.estimated_tokens
        removed = self._history[:-keep_last]
        self._history = self._history[-keep_last:]
        freed = old_tokens - self.estimated_tokens

        _log.info("[compact] snipped %d messages, freed ~%d tokens, kept %d",
                  len(removed), freed, keep_last)
        return freed

    # ── Tool Result Budget (Layer1) ────────────────────

    @staticmethod
    def tool_result_budget(result_text: str, max_chars: int = 8000) -> str:
        """Layer1: Tool Result Budget — 截断过长工具输出，保留头尾。

        对标 CC: 每个 tool result 后截断，保留开头(60%)和结尾(40%)。
        """
        if len(result_text) <= max_chars:
            return result_text
        head = result_text[:int(max_chars * 0.6)]
        tail = result_text[-int(max_chars * 0.4):]
        _log.debug("[compact] tool result budget: %d->%d chars", len(result_text), max_chars)
        return head + f"\n... [{len(result_text) - max_chars} chars truncated] ...\n" + tail

    # ── Tool Result Budget (Layer1) ────────────────────

    @staticmethod
    def tool_result_budget(result_text: str, max_chars: int = 8000) -> str:
        """Layer1: Tool Result Budget — 截断过长工具输出，保留头尾。

        对标 CC: 每个 tool result 后截断，保留开头(60%)和结尾(40%)。
        """
        if len(result_text) <= max_chars:
            return result_text
        head = result_text[:int(max_chars * 0.6)]
        tail = result_text[-int(max_chars * 0.4):]
        _log.debug("[compact] tool result budget: %d->%d chars", len(result_text), max_chars)
        return head + f"\n... [{len(result_text) - max_chars} chars truncated] ...\n" + tail

    # ── Tool Result Budget (Layer1) ────────────────────

    @staticmethod
    def tool_result_budget(result_text: str, max_chars: int = 8000) -> str:
        """Layer1: Tool Result Budget — 截断过长工具输出，保留头尾。

        对标 CC: 每个 tool result 后截断，保留开头(60%)和结尾(40%)。
        """
        if len(result_text) <= max_chars:
            return result_text
        head = result_text[:int(max_chars * 0.6)]
        tail = result_text[-int(max_chars * 0.4):]
        _log.debug("[compact] tool result budget: %d->%d chars", len(result_text), max_chars)
        return head + f"\n... [{len(result_text) - max_chars} chars truncated] ...\n" + tail

    # ── Collapse Drain (Layer3-4 bridge) ────────────────

    def collapse_drain(self) -> int:
        """Context collapse drain — 用于 413 恢复阶梯的第一步。

        对标 CC: collapse replaces spans with summaries before auto-compact.
        这里简化: 触发 snip_compact + 如果仍超限则尝试 compact_fn。
        """
        freed = self.snip_compact(keep_last=10)
        if self.estimated_tokens < self.auto_compact_threshold:
            return freed
        # 如果 snip 不够，尝试 compact
        return freed + self.reactive_compact()

    # ── Reactive Compact (Layer4 fallback) ──────────────

    def reactive_compact(self) -> int:
        """Reactive compact — 用于 413/media_error 恢复阶梯的第二步。

        对标 CC: reactive compact catches the 413 error and compacts on demand.
        """
        if self.compact_fn is None:
            _log.debug("[compact] no compact_fn, reactive compact skipped")
            return 0

        try:
            summary, freed = self.compact_fn(self._history)
            self._previous_summary = summary
            self._history = [summary]
            _log.info("[compact] reactive: freed ~%d tokens", freed)
            return freed
        except Exception as exc:
            _log.warning("[compact] reactive compact failed: %s", exc)
            return 0


    # ── Three-Phase Compact (Phase 1-3) ───────────────

    def compact_three_phase(self, summarizer_fn=None) -> dict:
        """对标 Codex compact.rs: 三阶段压缩
        Phase 1 - collect: 提取需要压缩的消息
        Phase 2 - summarize: 调用summarizer_fn或降级trim
        Phase 3 - replace: 用摘要替换原始消息
        """
        messages = self._history.copy()
        keep_last = 5
        to_compact = messages[:-keep_last] if len(messages) > keep_last else []
        if not to_compact:
            return {"action": "skip", "reason": "nothing_to_compact"}
        
        # Phase 2: 摘要（降级策略）
        try:
            if summarizer_fn:
                summary, freed = summarizer_fn(to_compact)
            else:
                raise ValueError("no summarizer")
        except Exception:
            trim_at = max(1, len(to_compact) // 2)
            kept = to_compact[trim_at:]
            summary = f"[{len(to_compact) - len(kept)} older messages trimmed]"
            freed = sum(estimate_tokens(m) for m in to_compact[:trim_at])
        
        # Phase 3: 替换
        self._history = [summary] + messages[-keep_last:]
        self._last_compaction_summary = summary
        
        return {
            "action": "compact_3phase",
            "messages_compacted": len(to_compact),
            "freed_tokens": freed,
            "current_tokens": self.estimated_tokens,
        }

    @property
    def compaction_summary(self) -> Optional[str]:
        return getattr(self, '_last_compaction_summary', None)
    # ── Auto-Compact (Layer4) ───────────────────────────

    def auto_compact(self) -> int:
        """Auto-compact — 超过阈值时自动触发。

        对标 CC: forks Claude conversation to summarize.
        熔断器: 连续3次失败永久停止。

        Returns:
            freed_tokens: 释放的 token 数，0 表示无操作或失败
        """
        if self.rs.auto_compact_circuit_open():
            _log.warning("[compact] auto-compact circuit breaker OPEN — stopped trying")
            return 0

        if not self.needs_compaction():
            return 0

        if self.compact_fn is None:
            _log.debug("[compact] no compact_fn, auto-compact skipped")
            return 0

        try:
            summary, freed = self.compact_fn(self._history)
            self._previous_summary = summary
            self._history = [summary]
            self.rs.record_auto_compact_success()
            _log.info("[compact] auto: freed ~%d tokens, tokens now ~%d",
                      freed, self.estimated_tokens)
            return freed
        except Exception as exc:
            self.rs.record_auto_compact_failure()
            _log.warning("[compact] auto-compact FAILED (%d/%d): %s",
                         self.rs.auto_compact_failures,
                         self.MAX_COMPACT_FAILURES,
                         exc)
            if self.rs.auto_compact_circuit_open():
                _log.error("[compact] CIRCUIT BREAKER OPEN — auto-compact permanently disabled")
            return 0

    # ── Checkpoint Compact (C6, cycle-6 A4) ────────────

    def retention_boundary(self, retention_percentage: int = 40) -> int:
        """Return the index that splits (to_compact, to_keep).

        Distilled from open-webui@0.11.3 context_compaction.py:328-333:
        keep_count = max(2, len(history) * retention_percentage // 100) with
        retention clamped to [10, 50]. Loop history is list[str] (no roles),
        so the open-webui user-turn snapping degrades to a plain count
        boundary - the transferable core is proportional retention.
        """
        pct = min(50, max(10, int(retention_percentage)))
        n = len(self._history)
        if n == 0:
            return 0
        keep_count = max(2, n * pct // 100)
        return max(0, n - keep_count)

    def compact_with_checkpoint(
        self,
        summarizer_fn=None,
        retention_percentage: int = 40,
    ) -> dict:
        """Compact the tail while *keeping* a proportional recent window.

        Unlike reactive_compact/auto_compact (which replace the whole history
        with a single summary), this:
          1. splits history into (to_compact, to_keep) by retention_percentage;
          2. feeds the previous compaction summary into the summarizer so
             knowledge accumulates across compactions (no lossy reset);
          3. keeps the recent window verbatim and prepends the new summary.

        Returns a dict with action/freed_tokens/kept/summary. Safe no-op when
        there is nothing to compact. Never raises.
        """
        n = len(self._history)
        if n == 0:
            return {"action": "skip", "reason": "empty"}
        boundary = self.retention_boundary(retention_percentage)
        to_compact = self._history[:boundary]
        to_keep = self._history[boundary:]
        if not to_compact:
            return {"action": "skip", "reason": "nothing_to_compact"}

        before = self.estimated_tokens
        summary = None
        try:
            if summarizer_fn is not None:
                result = summarizer_fn(to_compact, self._previous_summary)
                summary = result[0] if isinstance(result, tuple) else result
            else:
                raise ValueError("no summarizer")
        except Exception:
            # Degrade: keep raw tail, emit a trimming marker (mirrors
            # compact_three_phase fallback).
            summary = "[%d older messages trimmed]" % len(to_compact)

        if not summary:
            summary = "[%d older messages trimmed]" % len(to_compact)

        self._previous_summary = summary
        self._last_compaction_summary = summary
        self._history = [summary] + to_keep
        freed = max(0, before - self.estimated_tokens)
        _log.info("[compact] checkpoint: compacted=%d kept=%d freed~%d",
                  len(to_compact), len(to_keep), freed)
        return {
            "action": "checkpoint",
            "compacted": len(to_compact),
            "kept": len(to_keep),
            "freed_tokens": freed,
            "current_tokens": self.estimated_tokens,
            "summary": summary,
        }

    @property
    def previous_summary(self) -> Optional[str]:
        return self._previous_summary
    # ── 完整压缩管线 ────────────────────────────────────

    def attach_fragment_collector(self, collector, budget_tokens: int | None = None):
        """Attach a FragmentCollector; optionally override its token budget."""
        self.fragment_collector = collector
        if budget_tokens is not None:
            self._fragment_budget_tokens = int(budget_tokens)
        return self

    def render_fragments(self) -> dict:
        """Render collected fragments under the token budget (Layer 0).

        Returns {"rendered": int, "tokens": int, "dropped": int}. Safe no-op when
        no collector is attached. Never raises.
        """
        result = {"rendered": 0, "tokens": 0, "dropped": 0}
        if self.fragment_collector is None:
            return result
        try:
            from context_fragment import FragmentBudget
            frags = list(self.fragment_collector.fragments)
            budget = FragmentBudget(total=self._fragment_budget_tokens)
            rendered = 0
            dropped = 0
            for frag in frags:
                if budget.allocate_fragment(frag) > 0:
                    rendered += 1
                else:
                    dropped += 1
            result = {"rendered": rendered, "tokens": budget.used,
                      "dropped": dropped}
            _log.debug("[compact] fragments rendered=%d tokens=%d dropped=%d",
                       result["rendered"], result["tokens"], result["dropped"])
        except Exception as exc:
            _log.debug("[compact] render_fragments skipped: %s", exc)
        return result

    def run_pipeline(self, pre_api_call: bool = False) -> dict:
        """运行完整压缩管线（每次 API 调用前调用）。

        对标 CC: context management pipeline — 4层按序执行:
          Layer 1: Tool Result Budget (外部调用 tool_result_budget)
          Layer 2: Snip Compact (硬性阻塞)
          Layer 3: Collapse Drain (snip+compact 桥接)
          Layer 4: Auto-Compact (阈值触发 + 熔断器)

        Returns:
            dict with actions_taken, total_freed, current_tokens
        """
        actions = []
        total_freed = 0

        # Layer 2: Snip Compact — 如果超过硬性阻塞
        if self.at_blocking_limit():
            freed = self.snip_compact(keep_last=15)
            if freed > 0:
                actions.append(f"snip: {freed}")
                total_freed += freed

        # Layer 3-4 bridge: Collapse Drain — 必须先于 auto-compact
        # 对标 CC: collapse replaces spans with summaries before auto-compact.
        # 如果 collapse 把上下文降到阈值以下，auto-compact 变为空操作。
        if self.needs_compaction():
            freed = self.collapse_drain()
            if freed > 0:
                actions.append(f"collapse_drain: {freed}")
                total_freed += freed

        # Layer 4: Auto-Compact — 如果 collapse 后仍超过阈值
        # 优先使用 compact_three_phase（对标 Codex compact.rs），降级到 auto_compact
        if self.needs_compaction():
            if self.compact_fn is not None:
                result = self.compact_three_phase(self.compact_fn)
                if result["action"] != "skip":
                    freed = result.get("freed_tokens", 0)
                    if freed > 0:
                        actions.append(f"compact_3phase: {freed}")
                        total_freed += freed
            else:
                freed = self.auto_compact()
                if freed > 0:
                    actions.append(f"auto-compact: {freed}")
                    total_freed += freed

        # CTX-07: token usage monitoring
        token_alert = report_token_usage(
            current_tokens=self.estimated_tokens,
            threshold=self.auto_compact_threshold,
            run_id=getattr(self, "_run_id", ""),
            round_num=getattr(self, "_round_num", 0),
        )

        return {
            "actions_taken": actions,
            "total_freed": total_freed,
            "current_tokens": self.estimated_tokens,
            "threshold": self.auto_compact_threshold,
            "blocking_at": self.blocking_threshold,
            "circuit_open": self.rs.auto_compact_circuit_open(),
            "token_alert": token_alert,  # CTX-07
        }
