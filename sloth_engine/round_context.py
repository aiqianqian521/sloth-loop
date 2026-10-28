"""OODA 跨轮上下文 — 解决 Act→Orient 错误传递断链。

v2.2 P0: RoundContext 作为跨轮状态载体，使上轮的 Act 结果、Verify 结果、
L1 重试历史能够传递到下一轮的 Orient 步骤。

参考 DSH 的 turn/step 边界事件模式：每个 turn 结束时记录 TurnEndReason，
下个 turn 的 preStep 可以读取上轮结束原因。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoundContext:
    """OODA 跨轮上下文 —— Act→Orient 数据桥接。

    在每轮 run_once() 结束时创建，作为返回值的一部分传递给调用方。
    下一轮 run_once() 接收 prev_ctx 参数，_orient() 消费其中的错误信息。
    """
    round_num: int

    # 上轮 Act 执行结果
    prev_act_status: str = ""                    # "completed" | "error" | "skipped"
    prev_act_error: str = ""                     # 错误消息（截断到 500 字符）
    prev_act_trades_count: int = 0               # 交易数量
    prev_act_elapsed_ms: float = 0               # Act 耗时

    # L1 重试历史
    l1_history: list[dict] = field(default_factory=list)
    # 每项: {strategy, ok, note}

    # 上轮 Verify 结果
    prev_verify_pass: int = 0
    prev_verify_total: int = 0
    prev_verify_failures: list[dict] = field(default_factory=list)
    # 每项: {metric, actual, threshold, operator}

    # 上轮 Orient 诊断
    prev_severity: str = ""                      # "normal" | "major" | "critical"
    prev_issue_count: int = 0

    # 错误链追踪
    consecutive_errors: int = 0
    error_chain: list[str] = field(default_factory=list)
    # 最近 N 轮的 error 消息（最多保留 5 条）

    @property
    def had_act_error(self) -> bool:
        """上轮 Act 是否失败。"""
        return self.prev_act_status == "error"

    @property
    def had_act_skip(self) -> bool:
        """上轮 Act 是否跳过。"""
        return self.prev_act_status in ("skipped", "")

    @property
    def has_verify_failures(self) -> bool:
        """上轮 Verify 是否有失败项。"""
        return len(self.prev_verify_failures) > 0

    @property
    def l1_retry_count(self) -> int:
        """L1 重试次数。"""
        return len(self.l1_history)

    @property
    def l1_all_failed(self) -> bool:
        """L1 三级重试是否全部失败。"""
        return len(self.l1_history) > 0 and all(not a.get("ok") for a in self.l1_history)

    def to_dict(self) -> dict:
        """序列化为字典（用于 JSON 持久化）。"""
        return {
            "round_num": self.round_num,
            "prev_act_status": self.prev_act_status,
            "prev_act_error": self.prev_act_error[:500],
            "prev_act_trades_count": self.prev_act_trades_count,
            "prev_act_elapsed_ms": self.prev_act_elapsed_ms,
            "l1_history": self.l1_history,
            "prev_verify_pass": self.prev_verify_pass,
            "prev_verify_total": self.prev_verify_total,
            "prev_verify_failures": self.prev_verify_failures,
            "prev_severity": self.prev_severity,
            "prev_issue_count": self.prev_issue_count,
            "consecutive_errors": self.consecutive_errors,
            "error_chain": self.error_chain[-5:],
        }