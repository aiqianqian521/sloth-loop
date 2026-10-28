"""P1-3: 子代理增强 — AgentContext + 字段隔离 + model_override。

增强现有 dsh-agent-teams 插件:
1. AgentContext dataclass: 对标 CC createSubagentContext 字段隔离
2. 四类字段策略: 共享引用 / 隔离副本 / bubble升级 / 禁止访问
3. model_override: 每个子代理可指定不同模型
4. 并行执行: run_parallel() 多子代理并行

对标 CC: 15步 runAgent() 生命周期 (简化适配 Python)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── 字段隔离策略 ───────────────────────────────────────

class FieldPolicy:
    """字段策略 — 对标 CC 4类字段隔离。"""

    SHARED = "shared"        # 共享引用（父代理修改影响子代理）
    ISOLATED = "isolated"    # 隔离副本（子代理独立副本）
    BUBBLE = "bubble"        # bubble升级（子代理操作升级到父代理）
    FORBIDDEN = "forbidden"  # 禁止访问（子代理不可见）

# ── AgentContext ────────────────────────────────────────

@dataclass
class AgentContext:
    """子代理上下文 — 对标 CC ToolUseContext 和 createSubagentContext。

    每个字段标记隔离策略，对标 CC 的子代理 context 构造时的字段选择。
    """

    agent_id: str = ""
    parent_id: Optional[str] = None
    task: str = ""

    # 模型配置
    model: str = "default"
    provider: str = "default"
    max_tokens: int = 4096
    reasoning_effort: str = "medium"

    # 工具/权限 (对标 CC tools/disallowedTools)
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"  # default|plan|dontAsk|bypass|bubble

    # cycle-8 A4-cand-B: 计划待批准队友上下文（AGE-17）。additive，默认值 => 行为不变。
    plan_required_teammate: bool = False
    teammate_name: str = ""

    # 生命周期 (对标 CC AbortController)
    timeout_seconds: float = 300.0
    max_iterations: int = 10

    # 字段策略: 字段名 → FieldPolicy
    field_policies: dict[str, str] = field(default_factory=lambda: {
        "messages": FieldPolicy.SHARED,
        "tool_results": FieldPolicy.ISOLATED,
        "config": FieldPolicy.SHARED,
        "permissions": FieldPolicy.BUBBLE,
        "secrets": FieldPolicy.FORBIDDEN,
    })

    # cycle-8 A4-cand-A: additive liveness watchdog handle (set only while a
    # stall-guarded run is in flight). repr/compare excluded so dataclass
    # equality/repr are unchanged; never serialized by to_dict().
    watchdog: Any = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "parent_id": self.parent_id,
            "task": self.task,
            "model": self.model,
            "permission_mode": self.permission_mode,
            "timeout_s": self.timeout_seconds,
            "max_iterations": self.max_iterations,
        }


# ── 子代理执行结果 ─────────────────────────────────────

@dataclass
class SubAgentResult:
    """子代理执行结果 — 对标 CC Terminal 联合类型。"""

    agent_id: str
    status: str  # completed | max_turns | timeout | error | aborted | stalled
    output: Any = None
    error: Optional[str] = None
    elapsed_seconds: float = 0.0
    iterations: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "completed"


# ── 子代理执行器 ───────────────────────────────────────

def run_subagent(
    context: AgentContext,
    executor_fn: Callable[[AgentContext], Any],
    stall_ms: int = 0,
) -> SubAgentResult:
    """运行单个子代理。

    对标 CC: runAgent() 15步生命周期（简化）。

    流程:
    1. 创建隔离上下文 (对标 CC createSubagentContext)
    2. 注入允许的工具集 (对标 CC assembleToolPool for subagent)
    3. 设置权限模式 (对标 CC permissionMode)
    4. 执行 (对标 CC query() 单一路径)
    5. 收集结果
    """
    import time
    t0 = time.time()

    if context.timeout_seconds <= 0:
        return SubAgentResult(
            agent_id=context.agent_id,
            status="error",
            error="invalid timeout",
        )

    try:
        if stall_ms and int(stall_ms) > 0:
            # cycle-8 A4-cand-A: wall-clock no-progress guard. Additive and
            # opt-in (stall_ms<=0 keeps the legacy single call). The watchdog
            # is exposed via context.watchdog so a cooperative executor can
            # signal activity() / hold() (tool in flight). Retries are
            # stall-only; a deterministic failure still propagates to the
            # outer handlers below (status=error/timeout).
            from stall_watchdog import run_stall_resilient

            def _attempt(watchdog):
                context.watchdog = watchdog
                return executor_fn(context)

            try:
                result = run_stall_resilient(
                    _attempt, int(stall_ms), label=context.agent_id or "subagent")
            except RuntimeError as stall_exc:
                if "stalled on all" in str(stall_exc):
                    return SubAgentResult(
                        agent_id=context.agent_id,
                        status="stalled",
                        error=str(stall_exc),
                        elapsed_seconds=time.time() - t0,
                    )
                raise
            finally:
                context.watchdog = None
            return SubAgentResult(
                agent_id=context.agent_id,
                status="completed",
                output=result,
                elapsed_seconds=time.time() - t0,
                iterations=getattr(result, "iterations", 1) if hasattr(result, "iterations") else 1,
            )
        result = executor_fn(context)
        elapsed = time.time() - t0
        return SubAgentResult(
            agent_id=context.agent_id,
            status="completed",
            output=result,
            elapsed_seconds=elapsed,
            iterations=getattr(result, "iterations", 1) if hasattr(result, "iterations") else 1,
        )
    except TimeoutError:
        return SubAgentResult(
            agent_id=context.agent_id,
            status="timeout",
            elapsed_seconds=time.time() - t0,
        )
    except Exception as exc:
        return SubAgentResult(
            agent_id=context.agent_id,
            status="error",
            error=str(exc),
            elapsed_seconds=time.time() - t0,
        )


def run_subagents_parallel(
    contexts: list[AgentContext],
    executor_fn: Callable[[AgentContext], Any],
    max_workers: int = 5,
    stall_ms: int = 0,
) -> dict[str, SubAgentResult]:
    """并行运行多个子代理。

    对标 CC: 多个 Task agent 并行启动。

    Returns:
        {agent_id: SubAgentResult}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[str, SubAgentResult] = {}
    cap = min(max_workers, len(contexts)) if contexts else 0
    if cap <= 0:
        return results

    # Bounded registry gives an explicit, auditable concurrency ceiling (Codex
    # registry analogue). The executor is sized to the same cap so the registry
    # never becomes the bottleneck while still bounding slot accounting.
    registry = AgentRegistry(max_concurrent=cap)

    def _run_reserved(ctx: AgentContext) -> SubAgentResult:
        res = registry.try_reserve(ctx.agent_id)
        if res is None:  # pragma: no cover - cap==pool size makes this unreachable
            return SubAgentResult(agent_id=ctx.agent_id, status="error",
                                  error="agent registry full")
        try:
            return run_subagent(ctx, executor_fn, stall_ms=stall_ms)
        finally:
            res.release()

    with ThreadPoolExecutor(max_workers=cap) as pool:
        futures = {pool.submit(_run_reserved, ctx): ctx.agent_id for ctx in contexts}
        for future in as_completed(futures):
            agent_id = futures[future]
            try:
                results[agent_id] = future.result()
            except Exception as exc:
                results[agent_id] = SubAgentResult(
                    agent_id=agent_id, status="error", error=str(exc))

    return results


# ?? RAII SpawnReservation + InputQueue (port of Codex agent/registry + session) ??

class SpawnReservation:
    """RAII slot reservation for concurrent sub-agent spawning.

    Port of Codex's SpawnReservation: acquiring a slot is an explicit,
    reversible act; forgetting to release it is impossible because the slot is
    returned in __exit__ (or __del__ as a last resort). This replaces the
    "count-then-submit" pattern where a crashed spawn silently leaked a slot.

    Usage::

        reg = AgentRegistry(max_concurrent=4)
        with reg.reserve() as slot:
            ...        # slot is held here
        # slot auto-released (also on exception)
    """

    __slots__ = ("_registry", "agent_id", "_released")

    def __init__(self, registry: "AgentRegistry", agent_id: str = ""):
        self._registry = registry
        self.agent_id = agent_id
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._registry._release(self)

    def __enter__(self) -> "SpawnReservation":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass


class AgentRegistry:
    """Bounded concurrency registry for sub-agents (Codex registry analogue).

    Unlike ThreadPoolExecutor's implicit queue, reserve() fails fast when the
    pool is full so callers can choose to defer, drop, or block deliberately.
    """

    def __init__(self, max_concurrent: int = 5):
        import threading
        self.max_concurrent = max(1, int(max_concurrent))
        self._active: dict[str, SpawnReservation] = {}
        self._lock = threading.Lock()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def try_reserve(self, agent_id: str = "") -> SpawnReservation | None:
        with self._lock:
            if len(self._active) >= self.max_concurrent:
                return None
            res = SpawnReservation(self, agent_id)
            key = agent_id or f"_slot{id(res)}"
            self._active[key] = res
            return res

    def reserve(self, agent_id: str = "", block: bool = True,
                timeout: float | None = None) -> SpawnReservation:
        """Acquire a slot. Raises RuntimeError if full and block=False."""
        import time
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            res = self.try_reserve(agent_id)
            if res is not None:
                return res
            if not block:
                raise RuntimeError(
                    f"agent registry full ({self.active_count}/{self.max_concurrent})")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("timed out reserving agent slot")
            time.sleep(0.01)

    def _release(self, res: SpawnReservation) -> None:
        with self._lock:
            for key, held in list(self._active.items()):
                if held is res:
                    del self._active[key]
                    break


class InputQueue:
    """Two-priority input queue: mailbox (queued) vs steer (interrupt).

    Port of Codex session input handling. "steer" messages are injected into the
    running turn at the next safe point; "mailbox" messages wait for the turn to
    finish. Keeping them separate avoids the classic bug where an urgent user
    correction is stuck behind a backlog of low-priority notes.
    """

    MAILBOX = "mailbox"
    STEER = "steer"

    def __init__(self):
        import threading
        from collections import deque
        self._mailbox: "deque[Any]" = deque()
        self._steer: "deque[Any]" = deque()
        self._lock = threading.Lock()

    def push(self, item: Any, kind: str = MAILBOX) -> None:
        with self._lock:
            if kind == self.STEER:
                self._steer.append(item)
            else:
                self._mailbox.append(item)

    def drain_steer(self) -> list:
        """Return and clear all steer items (checked at every loop boundary)."""
        with self._lock:
            items = list(self._steer)
            self._steer.clear()
            return items

    def pop_mailbox(self) -> Any | None:
        with self._lock:
            return self._mailbox.popleft() if self._mailbox else None

    def drain_mailbox(self) -> list:
        with self._lock:
            items = list(self._mailbox)
            self._mailbox.clear()
            return items

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._steer) + len(self._mailbox)

    def has_steer(self) -> bool:
        with self._lock:
            return bool(self._steer)
