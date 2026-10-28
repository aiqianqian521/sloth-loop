"""P1-1: 并发工具调度 — 对标 DSH tool-calls.ts (exclusive barrier + bounded parallel pool)。

设计:
1. ToolDefinition 新增 is_concurrency_safe(input) -> bool 字段（per-input判断，对标CC）
2. ToolRegistry 新增 partition_tool_calls() — 按并发安全性分组
3. ToolRegistry 新增 execute_concurrent() — exclusive barrier + bounded parallel pool
4. 默认 fail-closed: 未声明 is_concurrency_safe 则视为串行
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger("sloth_engine.tool-concurrency")

# ── 默认常量 ──────────────────────────────────────────

DEFAULT_MAX_PARALLEL = 10  # 对标 DSH maxParallelToolCalls=10


# ── 并发安全判断 ──────────────────────────────────────

@dataclass
class ConcurrencyConfig:
    """工具并发配置 — 对标 DSH tool executionMode。"""

    # 输入依赖的并发安全判断函数
    # None → 使用 is_safe field (静态)
    # Callable → per-input 动态判断 (对标 CC isConcurrencySafe(input))
    is_concurrency_safe_fn: Optional[Callable[[dict], bool]] = None

    # 静态并发安全标志 (默认 False = fail-closed)
    is_concurrency_safe: bool = False

    def check(self, params: dict | None = None) -> bool:
        """检查是否可以并发执行。

        Args:
            params: 工具输入参数（用于 per-input 判断）

        Returns:
            True 如果该调用可以并发
        """
        if self.is_concurrency_safe_fn is not None and params is not None:
            try:
                return self.is_concurrency_safe_fn(params)
            except Exception:
                return False  # fail-closed
        return self.is_concurrency_safe


# ── 工具分区 ──────────────────────────────────────────

def partition_tool_calls(
    calls: list[dict],
    concurrency_map: dict[str, ConcurrencyConfig],
) -> list[list[dict]]:
    """按并发安全性分组成批。

    对标 DSH tool-calls.ts: exclusive calls form barriers;
    parallel-safe calls use bounded rolling pool.

    Args:
        calls: 工具调用列表 [{name, params, ...}]
        concurrency_map: 工具名 → ConcurrencyConfig 映射

    Returns:
        批次列表 — 每批内部可并发，批之间串行（exclusive barrier）
    """
    batches: list[list[dict]] = []
    current_batch: list[dict] = []

    for call in calls:
        name = call.get("name", "")
        cfg = concurrency_map.get(name)

        if cfg is None or not cfg.check(call.get("params")):
            # 串行工具 → flush 当前批 + 独占一批
            if current_batch:
                batches.append(current_batch)
                current_batch = []
            batches.append([call])  # exclusive barrier
        else:
            current_batch.append(call)

    if current_batch:
        batches.append(current_batch)

    return batches


# ── 并发执行器 ────────────────────────────────────────

@dataclass
class ConcurrentResult:
    """并发执行结果。"""
    call: dict
    result: Any
    error: Optional[str] = None
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


def execute_batch_parallel(
    batch: list[dict],
    executor_fn: Callable[[dict], Any],
    max_workers: int = DEFAULT_MAX_PARALLEL,
    timeout_per_call: float = 30.0,
    abort_on_first_error: bool = False,
) -> list[ConcurrentResult]:
    """并行执行一个批次。

    对标 DSH: bounded rolling pool, 提交顺序≠完成顺序,
    但结果按提交顺序返回（对标 CC: 提交顺序 yield）。

    Args:
        batch: 同批工具调用
        executor_fn: 执行函数 call -> result
        max_workers: 最大并发数
        timeout_per_call: 每个调用超时
        abort_on_first_error: True=首个错误取消所有 (对标 CC Bash error → cancel siblings)

    Returns:
        按提交顺序的 ConcurrentResult 列表
    """
    if len(batch) == 1:
        # 单工具 → 直接串行，避免线程开销
        call = batch[0]
        import time
        t0 = time.time()
        try:
            result = executor_fn(call)
            return [ConcurrentResult(call=call, result=result,
                                     elapsed_ms=(time.time() - t0) * 1000)]
        except Exception as exc:
            return [ConcurrentResult(call=call, result=None, error=str(exc),
                                     elapsed_ms=(time.time() - t0) * 1000)]

    import time
    results: dict[int, ConcurrentResult] = {}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(batch))) as pool:
        futures: dict[Any, int] = {}
        for i, call in enumerate(batch):
            futures[pool.submit(_safe_execute, executor_fn, call, timeout_per_call)] = i

        for future in as_completed(futures):
            idx = futures[future]
            try:
                result, error, elapsed = future.result()
                results[idx] = ConcurrentResult(
                    call=batch[idx], result=result, error=error, elapsed_ms=elapsed)
                if abort_on_first_error and error:
                    # 对标 CC: Bash error → cancel siblings
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    _log.warning("[concurrency] aborting batch after error in call %d: %s", idx, error)
                    break
            except Exception as exc:  # pragma: no cover - defensive:
                # _safe_execute() already turns every tool failure into a
                # (None, error, elapsed) tuple, so future.result() raising here
                # means the worker itself died (e.g. MemoryError / a broken
                # Future). Kept as a fail-soft guard.
                results[idx] = ConcurrentResult(
                    call=batch[idx], result=None, error=str(exc))

    # 按提交顺序返回，缺失的补 error
    ordered = []
    for i in range(len(batch)):
        if i in results:
            ordered.append(results[i])
        else:
            ordered.append(ConcurrentResult(
                call=batch[i], result=None, error="cancelled (sibling error)"))

    return ordered


def _safe_execute(
    executor_fn: Callable[[dict], Any],
    call: dict,
    timeout: float,
) -> tuple[Any, Optional[str], float]:
    """安全执行单个调用，返回 (result, error, elapsed_ms)。"""
    import time
    t0 = time.time()
    try:
        result = executor_fn(call)
        elapsed = (time.time() - t0) * 1000
        return result, None, elapsed
    except Exception as exc:
        elapsed = (time.time() - t0) * 1000
        return None, str(exc), elapsed


# ── 完整批次执行 ──────────────────────────────────────

def execute_all_batches(
    batches: list[list[dict]],
    executor_fn: Callable[[dict], Any],
    max_workers: int = DEFAULT_MAX_PARALLEL,
    abort_on_first_error: bool = False,
) -> list[ConcurrentResult]:
    """执行所有批次 — 批间串行(exclusive barrier)，批内并发。

    对标 DSH tool-calls.ts full scheduler.

    Returns:
        所有调用的结果（按原始提交顺序）
    """
    all_results: list[ConcurrentResult] = []
    for batch_idx, batch in enumerate(batches):
        batch_results = execute_batch_parallel(
            batch, executor_fn, max_workers=max_workers,
            abort_on_first_error=abort_on_first_error,
        )
        all_results.extend(batch_results)

        # 如果有错误且设置了 abort，停止后续批次
        if abort_on_first_error and any(not r.ok for r in batch_results):
            _log.warning("[concurrency] stopping after batch %d due to error", batch_idx)
            break

    return all_results
