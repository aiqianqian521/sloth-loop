
# ============================================================================
# EventDiagnostics — 诊断层 (P1-N3)
# ============================================================================
# 对标 dsh-maze VERDICT_RULES + ANALYSIS_RULES.SIGNALS
# 只记录不诊断 → 记录+诊断：失败模式归类、恢复链追踪、行为信号检测
# 所有诊断结论可回溯到原始事件（seq 引用）


from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from event_log import EventLog, LoopEvent
from collections import Counter, defaultdict

# ── 阈值常量（对标 dsh-maze ANALYSIS_RULES.SIGNALS）───────────────

BLIND_RETRY_THRESHOLD = 3        # 连续 ≥3 次同工具+相似参数 → 盲目重试
SLOW_CALL_THRESHOLD_MS = 120000  # 调用耗时 ≥120s → 慢调用
CONTEXT_SURGE_RATIO = 1.5        # Token 使用骤增 ≥1.5x → 上下文压力信号
CONSECUTIVE_FAILURE_LIMIT = 3    # 连续失败 ≥3 次 → 信号


@dataclass
class FailureRecovery:
    """单次失败的恢复分析。"""
    failed_seq: int               # 失败事件 seq
    failed_step: str              # 失败步骤
    error_msg: str                # 错误信息（截断 200 字）
    recovery_strategy: str        # "原样重试"|"换参数"|"换工具"|"未恢复"
    recovery_seqs: list[int] = field(default_factory=list)  # 恢复尝试 seq 列表
    recovery_cost_ms: float = 0   # 恢复总耗时


@dataclass
class BehaviorSignal:
    """诊断出的行为信号。"""
    signal: str                   # 信号名称
    severity: str                 # "高"|"中"|"低"|"信息"
    description: str              # 一句话依据
    affected_rounds: list[int] = field(default_factory=list)
    evidence_seqs: list[int] = field(default_factory=list)


@dataclass
class DiagnosticSummary:
    """一次完整诊断的摘要。"""
    total_rounds: int
    total_failures: int
    blind_retries: int            # 盲目重试次数
    consecutive_failures: int     # 最大连续失败数
    recovery_chains: list[FailureRecovery] = field(default_factory=list)
    signals: list[BehaviorSignal] = field(default_factory=list)
    tool_result_matrix: dict[str, dict] = field(default_factory=dict)
        # {tool_name: {success, failed, no_result, blind_retry, success_rate, p50_ms, p95_ms, max_ms}}


class EventDiagnostics:
    """事件日志诊断器。

    输入：已填充的 EventLog 实例（含事件列表）
    输出：DiagnosticSummary —— 失败模式归类、恢复链追踪、行为信号检测。
    所有结论带 seq 引用，可回溯到原始事件行。
    """

    def __init__(self, event_log: EventLog):
        self._log = event_log
        self._events = event_log.events

    def diagnose(self) -> DiagnosticSummary:
        """执行完整诊断，返回结构化摘要。"""
        rounds = sorted(set(e.round for e in self._events if e.round > 0))
        failures = [e for e in self._events if e.status == "FAIL"]

        # 1. 盲目重试检测
        blind_retries, blind_pairs = self._detect_blind_retries()

        # 2. 连续失败检测
        max_consecutive = self._detect_consecutive_failures()

        # 3. 失败恢复链
        recovery_chains = self._build_recovery_chains(failures)

        # 4. 行为信号扫描
        signals = self._scan_signals(blind_pairs, failures, recovery_chains)

        # 5. 工具结果矩阵
        tool_matrix = self._build_tool_matrix()

        return DiagnosticSummary(
            total_rounds=len(rounds),
            total_failures=len(failures),
            blind_retries=blind_retries,
            consecutive_failures=max_consecutive,
            recovery_chains=recovery_chains,
            signals=signals,
            tool_result_matrix=tool_matrix,
        )

    # ── 盲目重试检测 ─────────────────────────────

    def _detect_blind_retries(self) -> tuple[int, list[tuple[int, int]]]:
        """检测连续 ≥BLIND_RETRY_THRESHOLD 次同工具调用（归为盲目重试）。

        Returns:
            (盲目重试总次数, [(起始seq, 结束seq), ...])
        """
        total_blind = 0
        pairs: list[tuple[int, int]] = []

        # 按 seq 排序的事件流
        sorted_events = sorted(self._events, key=lambda e: e.seq)
        i = 0
        while i < len(sorted_events):
            e = sorted_events[i]
            tool = e.data.get("tool", e.step)
            if not tool:
                i += 1
                continue
            # 找连续同工具调用
            j = i + 1
            while j < len(sorted_events):
                next_e = sorted_events[j]
                next_tool = next_e.data.get("tool", next_e.step)
                if next_tool == tool:
                    j += 1
                else:
                    break
            run_len = j - i
            if run_len >= BLIND_RETRY_THRESHOLD:
                total_blind += run_len
                pairs.append((sorted_events[i].seq, sorted_events[j-1].seq))
            i = j

        return total_blind, pairs

    # ── 连续失败检测 ─────────────────────────────

    def _detect_consecutive_failures(self) -> int:
        """计算最大连续失败次数。"""
        max_run = 0
        current_run = 0
        sorted_events = sorted(self._events, key=lambda e: e.seq)
        for e in sorted_events:
            if e.status == "FAIL":
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0
        return max_run

    # ── 失败恢复链 ───────────────────────────────

    def _build_recovery_chains(self, failures: list[LoopEvent]) -> list[FailureRecovery]:
        """每个失败事件后的恢复尝试分析。"""
        chains: list[FailureRecovery] = []
        sorted_events = sorted(self._events, key=lambda e: e.seq)

        failure_index = {e.seq: e for e in failures}

        for fail_evt in failures:
            # 找到失败后接下来的事件（恢复尝试）
            recovery_seqs: list[int] = []
            strategy = "未恢复"
            prev_tool = fail_evt.data.get("tool", fail_evt.step)
            recovery_cost = 0.0

            for e in sorted_events:
                if e.seq <= fail_evt.seq:
                    continue
                if e.status == "FAIL":
                    cur_tool = e.data.get("tool", e.step)
                    if cur_tool == prev_tool:
                        strategy = "原样重试"
                    elif e.data.get("strategy"):
                        strategy = "换策略"
                    else:
                        strategy = "换工具"
                    recovery_seqs.append(e.seq)
                    recovery_cost = max(recovery_cost, e.elapsed_ms)
                    break
                if e.status in ("PASS", "WARN"):
                    # 下一个非失败事件 = 恢复成功
                    if not recovery_seqs:
                        cur_tool = e.data.get("tool", e.step)
                        if cur_tool != prev_tool and e.data.get("strategy"):
                            strategy = "换策略恢复"
                        elif cur_tool != prev_tool:
                            strategy = "换工具恢复"
                        else:
                            strategy = "自恢复"
                        recovery_seqs.append(e.seq)
                        recovery_cost = e.elapsed_ms
                    break

            chains.append(FailureRecovery(
                failed_seq=fail_evt.seq,
                failed_step=fail_evt.step,
                error_msg=fail_evt.error[:200],
                recovery_strategy=strategy,
                recovery_seqs=recovery_seqs,
                recovery_cost_ms=recovery_cost,
            ))

        return chains

    # ── 行为信号扫描 ─────────────────────────────

    def _scan_signals(self, blind_pairs: list, failures: list,
                      recovery_chains: list) -> list[BehaviorSignal]:
        """扫描行为信号。"""
        signals: list[BehaviorSignal] = []

        # 信号1: 盲目重试
        if blind_pairs:
            affected_rounds = list(set(
                e.round for e in self._events
                for pair in blind_pairs
                if pair[0] <= e.seq <= pair[1]
            ))
            signals.append(BehaviorSignal(
                signal="盲目重试",
                severity="高",
                description=f"检测到 {len(blind_pairs)} 段连续同工具调用（≥{BLIND_RETRY_THRESHOLD}次）",
                affected_rounds=affected_rounds,
                evidence_seqs=[pair[0] for pair in blind_pairs],
            ))

        # 信号2: 连续失败
        max_consecutive = self._detect_consecutive_failures()
        if max_consecutive >= CONSECUTIVE_FAILURE_LIMIT:
            fail_rounds = list(set(e.round for e in failures))
            signals.append(BehaviorSignal(
                signal="连续失败",
                severity="高",
                description=f"最大连续失败 {max_consecutive} 次（阈值≥{CONSECUTIVE_FAILURE_LIMIT}）",
                affected_rounds=fail_rounds,
                evidence_seqs=[e.seq for e in failures if e.status == "FAIL"],
            ))

        # 信号3: 慢调用
        slow_events = [e for e in self._events
                       if e.elapsed_ms >= SLOW_CALL_THRESHOLD_MS]
        if slow_events:
            signals.append(BehaviorSignal(
                signal="慢调用",
                severity="中",
                description=f"{len(slow_events)} 次调用耗时 ≥{SLOW_CALL_THRESHOLD_MS}ms, "
                            f"最慢 {max(e.elapsed_ms for e in slow_events):.0f}ms",
                affected_rounds=list(set(e.round for e in slow_events)),
                evidence_seqs=[e.seq for e in slow_events],
            ))

        # 信号4: 未恢复失败
        unrecovered = [c for c in recovery_chains if c.recovery_strategy == "未恢复"]
        if unrecovered:
            signals.append(BehaviorSignal(
                signal="未恢复失败",
                severity="高",
                description=f"{len(unrecovered)} 次失败后未检测到恢复尝试",
                affected_rounds=list(set(
                    self._events[s.seq-1].round if s.seq > 0 else 0
                    for s in failures if s.seq in [c.failed_seq for c in unrecovered]
                )),
                evidence_seqs=[c.failed_seq for c in unrecovered],
            ))

        # 信号5: 失败率过高
        total = len(self._events)
        fail_count = len(failures)
        if total > 0 and fail_count / total > 0.20:  # 失败率 >20%
            signals.append(BehaviorSignal(
                signal="高失败率",
                severity="高",
                description=f"失败率 {fail_count/total:.1%}（{fail_count}/{total}），超过20%阈值",
                affected_rounds=list(set(e.round for e in failures)),
                evidence_seqs=[e.seq for e in failures],
            ))

        # 信号6: 循环检测（同步骤在同一轮反复出现）
        step_repeat = self._detect_step_repeat_in_round()
        if step_repeat:
            signals.append(BehaviorSignal(
                signal="循环",
                severity="中",
                description=f"检测到 {len(step_repeat)} 轮次内存在步骤重复（可能存在循环）",
                affected_rounds=list(set(r for r, _ in step_repeat)),
                evidence_seqs=[e.seq for _, e in step_repeat for e in [e]],
            ))

        return signals

    def _detect_step_repeat_in_round(self) -> list[tuple[int, LoopEvent]]:
        """检测同一轮次中同步骤反复出现 ≥4 次。"""
        by_round: dict[int, list[LoopEvent]] = defaultdict(list)
        for e in self._events:
            if e.round > 0:
                by_round[e.round].append(e)

        repeats: list[tuple[int, LoopEvent]] = []
        for rnd, events in by_round.items():
            step_counts = Counter(e.step for e in events)
            for step, count in step_counts.items():
                if count >= 4:
                    e = next((e for e in events if e.step == step), events[0])
                    repeats.append((rnd, e))

        return repeats

    # ── 工具结果矩阵 ─────────────────────────────

    def _build_tool_matrix(self) -> dict[str, dict]:
        """构建 {tool_name: {success, failed, no_result, blind_retry, ...}} 矩阵。"""
        by_tool: dict[str, list[LoopEvent]] = defaultdict(list)
        for e in self._events:
            tool = e.data.get("tool", e.step)
            if tool:
                by_tool[tool].append(e)

        matrix: dict[str, dict] = {}
        for tool, events in by_tool.items():
            success = sum(1 for e in events if e.status == "PASS")
            failed = sum(1 for e in events if e.status == "FAIL")
            no_result = sum(1 for e in events if e.status == "SKIP")
            blind_retry = 0
            total = len(events)
            elapsed = sorted(e.elapsed_ms for e in events if e.elapsed_ms > 0)
            p50 = elapsed[len(elapsed)//2] if elapsed else 0
            p95 = elapsed[int(len(elapsed)*0.95)] if elapsed else 0
            max_ms = max(elapsed) if elapsed else 0

            matrix[tool] = {
                "success": success,
                "failed": failed,
                "no_result": no_result,
                "blind_retry": blind_retry,
                "success_rate": (success / total * 100) if total > 0 else 0,
                "p50_ms": p50,
                "p95_ms": p95,
                "max_ms": max_ms,
                "total_calls": total,
            }

        return matrix

    # ── 便捷序列化 ──────────────────────────────

    def summary_dict(self) -> dict:
        """将 DiagnosticSummary 序列化为字典。"""
        s = self.diagnose()
        return {
            "total_rounds": s.total_rounds,
            "total_failures": s.total_failures,
            "blind_retries": s.blind_retries,
            "consecutive_failures": s.consecutive_failures,
            "recovery_chains": [
                {
                    "failed_seq": c.failed_seq,
                    "failed_step": c.failed_step,
                    "error": c.error_msg,
                    "strategy": c.recovery_strategy,
                    "recovery_seqs": c.recovery_seqs,
                    "recovery_cost_ms": c.recovery_cost_ms,
                }
                for c in s.recovery_chains
            ],
            "signals": [
                {
                    "signal": sig.signal,
                    "severity": sig.severity,
                    "description": sig.description,
                    "affected_rounds": sig.affected_rounds,
                    "evidence_seqs": sig.evidence_seqs,
                }
                for sig in s.signals
            ],
            "tool_result_matrix": s.tool_result_matrix,
        }

