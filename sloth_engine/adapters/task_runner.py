"""
Task Runner 抽象接口 — Phase 0 任务类型通用化。

定义任意任务接入 Loop 的接口契约。实现 TaskRunner 即可让 loop
自动获得 OODA 循环 + 问题队列 + 模式学习 + 排除检查能力。

支持两种运行模式:
  - subprocess: 调用外部脚本（回测、XPath 抓取等）
  - inline: Agent 进程内执行（skill 纠错、格式检查等）
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# G-5 (cycle-10): the step-level exception policy is a sibling module in
# sloth_engine/.  Make the engine root importable rather than relying on the
# caller's sys.path having already been seeded (run_loop.py precedent).
_ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from step_exception_policy import ExceptionPolicy, apply_policy  # noqa: E402


@dataclass
class TaskInput:
    """任意任务的输入。"""
    task_type: str                                    # "backtest" | "book-distill" | "xpath-learn" | ...
    params: dict = field(default_factory=dict)        # 任务参数快照
    signals: list[dict] | None = None                 # 兼容旧回测信号（过渡期）
    context: dict = field(default_factory=dict)       # 额外上下文


@dataclass
class TaskResult:
    # Three-layer result contract: process execution, transport/schema output,
    # and domain/business evaluation. Legacy fields remain supported.
    execution: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    business: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    """任意任务的输出。Loop 引擎从 errors 中学习。"""
    status: str = "error"                             # "completed" | "error" | "skipped"
    rounds: list[dict] = field(default_factory=list)  # 每轮执行记录
    errors: list[dict] = field(default_factory=list)  # [{signature, params_snapshot, fix_recipe, evidence}, ...]
    metrics: dict = field(default_factory=dict)       # {win_rate, sharpe, success_rate, ...}
    raw_output: Any = None                            # runner 的原始输出


    def __post_init__(self) -> None:
        self.execution = dict(self.execution or {})
        self.output = dict(self.output or {})
        self.business = dict(self.business or {})
        self.provenance = dict(self.provenance or {})
        # Preserve the legacy empty ``TaskResult(status="skipped")`` shape for
        # callers that intentionally use it as a control-flow sentinel. Actual
        # adapters provide explicit layers for skipped outcomes.
        if self.status == "skipped" and not any((self.execution, self.output, self.business, self.provenance)):
            return
        self.execution.setdefault("stage", "execution")
        self.execution.setdefault("status", "succeeded" if self.status == "completed" else "not_started")
        # Process completion is not proof that an adapter output was parsed or
        # that the business criteria passed. Adapters that can prove those
        # layers must set them explicitly.
        self.output.setdefault("status", "not_verified" if self.status == "completed" else "not_available")
        self.output.setdefault("present", self.output.get("status") == "valid")
        self.output.setdefault("parseable", self.output.get("status") not in {"not_run", "not_available"})
        self.output.setdefault("schema_valid", self.output.get("status") == "valid")
        self.business.setdefault("status", "not_evaluated")

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "execution": self.execution,
            "output": self.output,
            "business": self.business,
            "provenance": self.provenance,
            "rounds": self.rounds,
            "errors": self.errors,
            "metrics": self.metrics,
        }


def normalize_task_result(value: Any, *, adapter: str, entry: str = "",
                          task_input: TaskInput | None = None) -> TaskResult:
    """Normalize any execution-adapter value into the shared result contract.

    Adapters may keep legacy top-level fields, but orchestration code must use
    this boundary before Verify/Learn. A completed process without an explicit
    output/business assessment is deliberately marked ``not_verified`` and
    ``not_evaluated`` instead of being promoted to business success.
    """
    if isinstance(value, TaskResult):
        result = value
    elif isinstance(value, dict):
        nested = value.get("task_result")
        if isinstance(nested, TaskResult):
            result = nested
        else:
            raw_status = str(value.get("status", "completed"))
            status_map = {"ok": "completed", "success": "completed",
                          "blocked": "skipped", "timeout": "error"}
            status = status_map.get(raw_status, raw_status)
            if status not in {"completed", "error", "skipped"}:
                status = "error"
            execution = dict(value.get("execution") or {})
            output = dict(value.get("output") or {})
            business = dict(value.get("business") or {})
            errors = list(value.get("errors") or [])
            if status == "completed":
                execution.setdefault("status", "succeeded")
                execution.setdefault("code", "ok")
                output.setdefault("status", "not_verified")
                business.setdefault("status", "not_evaluated")
            elif status == "skipped":
                execution.setdefault("status", "blocked" if raw_status == "blocked" else "not_started")
                execution.setdefault("code", "pre_hook_blocked" if raw_status == "blocked" else "skipped")
                output.setdefault("status", "not_run")
                business.setdefault("status", "not_evaluated")
            else:
                execution.setdefault("status", "timeout" if raw_status == "timeout" else "failed")
                execution.setdefault("code", str(value.get("error_code") or "adapter_error"))
                output.setdefault("status", "not_available")
                business.setdefault("status", "not_evaluated")
                if not errors:
                    evidence = str(value.get("error") or execution["code"])
                    errors.append({"signature": f"{adapter}:{execution['code']}",
                                   "params_snapshot": {},
                                   "fix_recipe": "Inspect adapter execution and output contract",
                                   "evidence": evidence[:500]})
            result = TaskResult(
                status=status, execution=execution, output=output,
                business=business, provenance=dict(value.get("provenance") or {}),
                rounds=list(value.get("rounds") or []), errors=errors,
                metrics=dict(value.get("metrics") or {}), raw_output=value.get("raw", value),
            )
    else:
        result = TaskResult(
            status="error",
            execution={"status": "failed", "code": "invalid_result_type", "stage": "adapter"},
            output={"status": "not_available"}, business={"status": "not_evaluated"},
            errors=[{"signature": f"{adapter}:invalid_result_type",
                     "params_snapshot": {},
                     "fix_recipe": "Return TaskResult or a result dictionary",
                     "evidence": type(value).__name__}], raw_output=value,
        )
    result.provenance.setdefault("adapter", adapter)
    if entry:
        result.provenance.setdefault("entry", entry)
    if task_input is not None:
        result.provenance.setdefault("task_type", task_input.task_type)
        result.provenance.setdefault("signal_count", len(task_input.signals or []))
    return result


def task_result_payload(result: TaskResult, legacy: dict | None = None) -> dict:
    """Return a JSON-friendly contract while retaining legacy adapter fields."""
    payload = dict(legacy or {})
    payload.update(result.to_dict())
    payload["task_result"] = result.to_dict()
    payload.setdefault("trades", list((legacy or {}).get("trades") or []))
    payload.setdefault("error", result.errors[0].get("evidence", "") if result.errors else "")
    return payload

class TaskRunner(ABC):
    """任务执行器抽象基类。subprocess 或进程内均可实现。

    移植自 DeepSeek Harness 的插件化架构模式：任何领域只需实现
    TaskRunner 即可接入 Loop 的 OODA + 模式库 + 自进化能力。
    """

    @abstractmethod
    def run(self, input: TaskInput) -> TaskResult:
        """执行任务，返回 TaskResult。异常不应抛出——转为 TaskResult(status="error")。"""
        ...

    def validate_input(self, signals: list[dict]) -> list[dict]:
        """验证输入信号。默认透传，子类可覆盖做领域校验。

        返回过滤后的信号列表（默认不过滤）。
        子类可在此处：检查必填字段、去重、格式转换。
        """
        return signals

    def validate_output(self, result: TaskResult) -> bool:
        """验证输出是否满足任务要求。默认通过，子类可覆盖。

        返回 True 表示输出有效，False 表示应跳过 Learn 步骤。
        子类可在此处：检查 trades 数量、win_rate 阈值、必填字段。
        """
        return (result.status == "completed"
                and result.output.get("status", "valid") == "valid"
                and result.business.get("status", "passed") == "passed")


# ── BacktestRunner: 兼容现有回测流程 ──────────────────────────

@dataclass
class _BacktestTrade:
    """回测交易记录（兼容现有 backtest_adapter.BacktestResult）。"""
    signal_pattern: str = ""
    market_condition: str = "unknown"
    pnl: float = 0.0
    failure_reason: str = ""
    entry_condition: str = ""
    stop_loss: str = ""
    take_profit: str = ""
    position_size: str = ""
    entry_price: float = 0.0
    entry_time: str = ""


class BacktestRunner(TaskRunner):
    """回测任务执行器：包装现有 backtest_adapter.run_backtest()。

    将 BacktestResult 转换为通用 TaskResult，使回测可以和其他任务类型
    共享同一套 OODA + 问题队列 + 模式学习流程。
    """

    # 回测信号必填字段
    REQUIRED_SIGNAL_FIELDS = ["signal_pattern"]

    def __init__(self, bt_settings: dict | None = None, exec_gate=None,
                 policy: ExceptionPolicy | None = None):
        self.bt_settings = bt_settings or {}
        self.exec_gate = exec_gate
        # G-5 (cycle-10): opt-in per-step exception policy.  The default
        # ExceptionPolicy() is byte-for-byte the legacy behaviour (a single
        # attempt that re-raises), so callers that pass nothing are unaffected.
        self.policy = policy if policy is not None else ExceptionPolicy()

    def validate_input(self, signals: list[dict]) -> list[dict]:
        """验证回测信号：过滤缺少 signal_pattern 的无效信号。"""
        valid = []
        for s in signals:
            if not isinstance(s, dict):
                continue
            if all(f in s for f in self.REQUIRED_SIGNAL_FIELDS):
                valid.append(s)
        return valid

    def validate_output(self, result: TaskResult) -> bool:
        """验证回测输出：必须 completed 且有 trades 数据。"""
        if result.status != "completed":
            return False
        metrics = result.metrics or {}
        return (metrics.get("trades_count", 0) > 0
                and result.output.get("status", "valid") == "valid"
                and result.business.get("status", "passed") == "passed")

    def run(self, input: TaskInput) -> TaskResult:
        from .backtest_adapter import BacktestInput, run_backtest

        signals = input.signals or []
        if not signals:
            return TaskResult(status="skipped", execution={"status": "not_started"},
                              output={"status": "not_run"}, business={"status": "not_evaluated"},
                              errors=[{
                "signature": "no_signals",
                "params_snapshot": {},
                "fix_recipe": "提供有效的信号文件 (--signals path.json)",
                "evidence": "TaskInput.signals 为空",
            }])

        try:
            outcome = apply_policy(
                self.policy,
                lambda: run_backtest(BacktestInput(
                    signals=signals,
                    success_starting_points=input.params.get("success_starts", []),
                ), settings=self.bt_settings or None, exec_gate=self.exec_gate),
            )
        except Exception as e:
            return TaskResult(status="error", execution={"status": "failed", "stage": "runner"},
                              output={"status": "not_available"}, business={"status": "not_evaluated"},
                              errors=[{
                "signature": "backtest_exception",
                "params_snapshot": {"signal_count": len(signals)},
                "fix_recipe": f"检查回测脚本和 I/O 契约: {e}",
                "evidence": str(e)[:500],
            }])

        if not outcome.ok:
            # G-5: a fallback policy (EXCEPTION_BRANCH / RETURN_DEFAULT)
            # exhausted the attempts without raising.  Mirror coze's
            # isSuccess=true marker: the step counts as completed for
            # downstream branching, but the raw error is preserved and the
            # output is deliberately left "not_verified" so the verifier can
            # never promote it to a business success.
            return TaskResult(
                status="completed",
                execution={"status": "succeeded", "stage": "runner",
                           "code": "step_policy_fallback",
                           "route": outcome.route, "attempts": outcome.attempts,
                           "is_success": bool(outcome.is_success)},
                output={"status": "not_verified"},
                business={"status": "not_evaluated"},
                provenance={"adapter": "backtest", "entry": "BacktestRunner"},
                errors=[{
                    "signature": "backtest_step_policy_fallback:" + str(outcome.route),
                    "params_snapshot": {"signal_count": len(signals)},
                    "fix_recipe": ("Step exhausted after %d attempt(s); a fallback "
                                   "policy suppressed the raise - inspect the raw error."
                                   % outcome.attempts),
                    "evidence": str(outcome.error or "")[:500],
                }],
                raw_output=outcome.value,
            )

        bt = outcome.value
        errors = []
        if bt.status == "error":
            code = (bt.execution or {}).get("code", "backtest_error")
            errors.append({
                "signature": f"backtest_execution:{code}",
                "params_snapshot": {"signal_count": len(signals)},
                "fix_recipe": "检查回测执行阶段和输出契约",
                "evidence": bt.error or code,
            })
        for t in bt.trades:
            pnl = t.get("pnl", 0) or 0
            if pnl < 0:
                sp = str(t.get("signal_pattern", "unknown"))
                mc = str(t.get("market_condition", "unknown"))
                reason = str(t.get("failure_reason", ""))
                errors.append({
                    "signature": f"backtest_loss:{sp}",
                    "params_snapshot": {"signal_pattern": sp, "market_condition": mc, "pnl": pnl},
                    "fix_recipe": f"排除模式: {reason}" if reason else "待分析",
                    "evidence": f"回测亏损 {pnl:.4f}: {sp} @ {mc}, 原因: {reason or '未知'}",
                })

        metrics = {
            "trades_count": len(bt.trades),
            "win_rate": bt.win_rate,
            "sharpe": bt.sharpe,
            "total_pnl": bt.pnl.get("total", 0) if bt.pnl else 0,
        }
        metrics.update(getattr(bt, "extra_metrics", {}) or {})

        task_result = TaskResult(
            status="completed" if bt.status != "error" else "error",
            execution=bt.execution,
            output=bt.output,
            business=(bt.business if bt.status == "error" else {
                "status": "passed" if len(bt.trades) > 0 else "failed",
                "criteria": {"trades_count": {"operator": "gt", "threshold": 0}},
                "actual": {"trades_count": len(bt.trades)},
            }),
            provenance=bt.provenance,
            errors=errors,
            metrics=metrics,
            raw_output=bt,
        )
        if outcome.attempts > 1:
            # G-5 observability: recorded only when a retry actually happened,
            # so the single-attempt default stays byte-identical.
            task_result.provenance["step_attempts"] = outcome.attempts
        return task_result
