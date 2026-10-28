"""P0-2: 错误恢复阶梯 — 对标 Claude Code query.ts 的 escalation ladder。

Claude Code 的错误恢复不是单一策略，而是逐步升级:
  prompt_too_long → [1] context collapse drain → [2] reactive compact → 退出
  max_output_tokens → [1] 8K→64K → [2] 多轮恢复(最多3次) → 退出
  media_error → reactive compact → 退出

每条路径独立追踪恢复状态，通过 RecoveryState 防止无限循环。
"""

from __future__ import annotations

import logging
from typing import Optional

from loop_state_enums import (
    TerminalReason,
    ContinueReason,
    LoopTermination,
    LoopContinuation,
    RecoveryState,
)

_log = logging.getLogger("sloth_engine.error-recovery")

# ── 错误分类 ────────────────────────────────────────

class ErrorCategory:
    """错误分类常量 — 对标 CC 的 error classification。"""

    PROMPT_TOO_LONG = "prompt_too_long"       # 413/context overflow
    MAX_OUTPUT_TOKENS = "max_output_tokens"    # hit max_tokens cap
    MEDIA_ERROR = "media_error"               # image size/resize error
    MODEL_ERROR = "model_error"               # unrecoverable API error
    UNKNOWN = "unknown"

    @staticmethod
    def classify(error: Exception | str | dict) -> str:
        """从异常/字符串/字典中推断错误类别。"""
        msg = ""
        if isinstance(error, Exception):
            msg = str(error).lower()
        elif isinstance(error, str):
            msg = error.lower()
        elif isinstance(error, dict):
            msg = str(error.get("error", "") or error.get("message", "")).lower()

        if any(k in msg for k in ("413", "prompt too long", "context length", "token limit", "too large", "reduce")):
            return ErrorCategory.PROMPT_TOO_LONG
        if any(k in msg for k in ("max_tokens", "max output", "output token", "too many tokens", "truncated")):
            return ErrorCategory.MAX_OUTPUT_TOKENS
        if any(k in msg for k in ("image", "media", "resize", "dimension", "file too large")):
            return ErrorCategory.MEDIA_ERROR
        if any(k in msg for k in ("model", "api error", "service unavailable", "overloaded", "rate limit", "500", "503")):
            return ErrorCategory.MODEL_ERROR
        return ErrorCategory.UNKNOWN


# ── 恢复阶梯 ────────────────────────────────────────

class ErrorRecoveryLadder:
    """错误恢复阶梯 — 对标 CC 的 escalation ladder。

    用法:
        ladder = ErrorRecoveryLadder(recovery_state, context_manager)
        decision = ladder.attempt_recovery(error_category, round_num)
        if decision.is_terminal:
            return decision  # 退出循环
        # decision.is_continue → 用 decision.reason 决定重试策略
    """

    def __init__(
        self,
        recovery_state: RecoveryState,
        context_manager=None,  # 可选: 注入上下文压缩器 (P0-3)
    ):
        self.rs = recovery_state
        self.context_manager = context_manager
        self._last_decision: Optional[LoopTermination | LoopContinuation] = None

    def attempt_recovery(
        self,
        category: str,
        round_num: int = 0,
    ) -> LoopTermination | LoopContinuation:
        """尝试恢复。返回 LoopTermination(退出) 或 LoopContinuation(重试)。

        Args:
            category: ErrorCategory 分类
            round_num: 当前轮次
        """
        if category == ErrorCategory.PROMPT_TOO_LONG:
            return self._recover_prompt_too_long(round_num)
        elif category == ErrorCategory.MAX_OUTPUT_TOKENS:
            return self._recover_max_output(round_num)
        elif category == ErrorCategory.MEDIA_ERROR:
            return self._recover_media_error(round_num)
        elif category == ErrorCategory.MODEL_ERROR:
            return LoopTermination(
                reason=TerminalReason.MODEL_ERROR,
                detail="unrecoverable model/API error",
                round=round_num,
            )
        else:
            return LoopTermination(
                reason=TerminalReason.MODEL_ERROR,
                detail=f"unknown error category: {category}",
                round=round_num,
            )

    def _recover_prompt_too_long(self, round_num: int) -> LoopTermination | LoopContinuation:
        """413/prompt-too-long 恢复阶梯:
        [1] context collapse drain → [2] reactive compact → 退出
        """
        # Step 1: collapse drain (一次性)
        if self.rs.collapse_allowed() and self.context_manager is not None:
            self.rs.has_attempted_collapse = True
            if hasattr(self.context_manager, 'collapse_drain'):
                try:
                    freed = self.context_manager.collapse_drain()
                    _log.info("[recovery] collapse drain freed ~%d tokens", freed)
                    return LoopContinuation(
                        reason=ContinueReason.COLLAPSE_DRAIN_RETRY,
                        detail=f"collapse drain freed ~{freed} tokens",
                        round=round_num,
                    )
                except Exception as exc:
                    _log.warning("[recovery] collapse drain failed: %s", exc)
        elif self.rs.collapse_allowed() and self.context_manager is None:
            # No context manager injected — skip collapse, fall through to compact
            self.rs.has_attempted_collapse = True
            _log.debug("[recovery] no context_manager, skipping collapse drain")

        # Step 2: reactive compact (一次性)
        if self.rs.reactive_compact_allowed() and self.context_manager is not None:
            self.rs.has_attempted_reactive_compact = True
            if hasattr(self.context_manager, 'reactive_compact'):
                try:
                    freed = self.context_manager.reactive_compact()
                    _log.info("[recovery] reactive compact freed ~%d tokens", freed)
                    return LoopContinuation(
                        reason=ContinueReason.REACTIVE_COMPACT_RETRY,
                        detail=f"reactive compact freed ~{freed} tokens",
                        round=round_num,
                    )
                except Exception as exc:
                    _log.warning("[recovery] reactive compact failed: %s", exc)
        elif self.rs.reactive_compact_allowed() and self.context_manager is None:
            # No context manager injected — skip compact
            self.rs.has_attempted_reactive_compact = True
            _log.debug("[recovery] no context_manager, skipping reactive compact")

        # 所有恢复路径耗尽
        return LoopTermination(
            reason=TerminalReason.CONTEXT_EXHAUSTED,
            detail="prompt_too_long: collapse drain + reactive compact both exhausted",
            round=round_num,
        )

    def _recover_max_output(self, round_num: int) -> LoopTermination | LoopContinuation:
        """max_output_tokens 恢复阶梯:
        [1] 8K→64K 升级 → [2] 多轮恢复(最多3次) → 退出
        """
        # Step 1: 8K→64K 升级 (一次性)
        if self.rs.max_output_escalate_allowed():
            _log.info("[recovery] max_output: 8K→64K escalated")
            return LoopContinuation(
                reason=ContinueReason.MAX_OUTPUT_ESCALATE,
                detail="8K→64K max_output_tokens escalated",
                round=round_num,
            )

        # Step 2: 多轮恢复 (最多3次)
        if self.rs.max_output_recovery_allowed():
            _log.info("[recovery] max_output: multi-turn recovery attempt %d/%d",
                      self.rs.max_output_recovery_count,
                      self.rs.MAX_OUTPUT_RECOVERY_LIMIT)
            return LoopContinuation(
                reason=ContinueReason.MAX_OUTPUT_RECOVERY,
                detail=f"multi-turn recovery {self.rs.max_output_recovery_count}/{self.rs.MAX_OUTPUT_RECOVERY_LIMIT}",
                round=round_num,
            )

        # 所有恢复路径耗尽
        return LoopTermination(
            reason=TerminalReason.CONTEXT_EXHAUSTED,
            detail=f"max_output: escalate + {self.rs.MAX_OUTPUT_RECOVERY_LIMIT}× recovery exhausted",
            round=round_num,
        )

    def _recover_media_error(self, round_num: int) -> LoopTermination | LoopContinuation:
        """media_error: reactive compact → 退出。"""
        if self.rs.reactive_compact_allowed():
            self.rs.has_attempted_reactive_compact = True
            _log.info("[recovery] media_error: attempting reactive compact")
            return LoopContinuation(
                reason=ContinueReason.REACTIVE_COMPACT_RETRY,
                detail="media_error: reactive compact attempted",
                round=round_num,
            )

        return LoopTermination(
            reason=TerminalReason.CONTEXT_EXHAUSTED,
            detail="media_error: reactive compact exhausted",
            round=round_num,
        )

    @property
    def last_decision(self):
        return self._last_decision

