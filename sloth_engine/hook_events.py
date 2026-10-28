"""
Hook Event Bus — P3-B1: Hook事件体系扩充
============================================
从 pre/post 2个事件扩充到 17 个生命周期事件（对标 DSH 27事件），
并自动联动 EventLog（每个 HookEvent 产生一条 JSONL 记录）。

DSH 27事件对标:
  PreToolUse, PostToolUse, PostToolUseFailure,
  Notification, Stop, SubagentStop,
  PreMessageCompaction, PreCompact, PostCompact,
  PreToolUseApproval, PostToolUseApproval,
  PreHooks, PostHooks,
  SessionStart, SessionEnd, SessionResume,
  TurnStart, TurnEnd,
  StepStart, StepEnd,
  UserPromptSubmit, UserPromptSubmitError,
  ...

sloth-loop 17事件（精选核心 + 可扩展）:
  ── 会话级 ──
  SESSION_START, SESSION_END, SESSION_RESUME,
  ── 轮次级 ──
  ROUND_START, ROUND_END,
  ── 步骤级 ──
  STEP_START, STEP_END, STEP_SKIP,
  ── 工具级 ──
  PRE_TOOL, POST_TOOL, TOOL_ERROR,
  ── 决策级 ──
  DECISION_APPLY, DECISION_REJECT, DECISION_BLOCK,
  ── 进化级 ──
  PATTERN_SAVED, PATTERN_EXCLUDED, PATTERN_EVOLVED,
  ── 系统级 ──
  CIRCUIT_OPEN, CIRCUIT_CLOSE, CHECKPOINT_SAVED,
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger("sloth_engine.hook-bus")

# ---------------------------------------------------------------------------
# 1. HookEvent 枚举（17个生命周期事件）
# ---------------------------------------------------------------------------

class HookEvent(str, enum.Enum):
    """生命周期事件 — 对标 DSH 27事件，精简为核心17个。

    每个事件对应 sloth-loop 运行流程中的一个关键节点。
    EventLog 会自动记录每个事件的触发。
    """

    # ── 会话级 ──
    SESSION_START = "session/start"          # 新会话开始
    SESSION_END = "session/end"              # 会话正常结束
    SESSION_RESUME = "session/resume"        # 从checkpoint恢复

    # ── 轮次级 ──
    ROUND_START = "round/start"              # 新一轮OODA开始
    ROUND_END = "round/end"                  # 本轮结束（含停止原因）

    # ── 步骤级 ──
    STEP_START = "step/start"                # OODA某步开始
    STEP_END = "step/end"                    # OODA某步结束
    STEP_SKIP = "step/skip"                  # 步骤被跳过（fast模式/恢复）

    # ── 工具级 ──
    PRE_TOOL = "tool/pre"                    # 工具执行前（等价DSH PreToolUse）
    POST_TOOL = "tool/post"                  # 工具执行后（等价DSH PostToolUse）
    TOOL_ERROR = "tool/error"                # 工具执行失败

    # ── 决策级 ──
    DECISION_APPLY = "decision/apply"        # 决定执行
    DECISION_REJECT = "decision/reject"      # 决定拒绝
    DECISION_BLOCK = "decision/block"        # 被安全门禁阻止

    # ── 进化级 ──
    PATTERN_SAVED = "pattern/saved"          # 新模式写入PatternStore
    PATTERN_EXCLUDED = "pattern/excluded"    # 信号被排除规则拦截
    PATTERN_EVOLVED = "pattern/evolved"      # 进化闭环产生新规则

    # ── 进化生命周期 (P3-E4) ──
    EVOLUTION_START = "evolution/start"              # 演化开始（配置已加载）
    EVOLUTION_SEED_BUILT = "evolution/seed_built"    # 种子群构建完成
    EVOLUTION_GENERATION_END = "evolution/generation_end"  # 单代演化结束
    EVOLUTION_CANDIDATES_READY = "evolution/candidates_ready"  # 候选产出待审
    EVOLUTION_REVIEW = "evolution/review"            # 候选评审（pending/commit）
    EVOLUTION_APPLIED = "evolution/applied"          # 候选写入信号池
    EVOLUTION_ERROR = "evolution/error"              # 演化失败（降级）

    # ── 系统级 ──
    CIRCUIT_OPEN = "circuit/open"            # 熔断器打开
    CIRCUIT_CLOSE = "circuit/close"          # 熔断器关闭
    CHECKPOINT_SAVED = "checkpoint/saved"    # 检查点持久化

    # ── 兼容别名（映射到旧事件名） ──
    @property
    def legacy_name(self) -> str:
        """返回对应的旧事件名（如果有）。"""
        mapping = {
            HookEvent.ROUND_START: "round/start",
            HookEvent.ROUND_END: "round/end",
            HookEvent.PRE_TOOL: "PreToolUse",
            HookEvent.POST_TOOL: "PostToolUse",
            HookEvent.DECISION_APPLY: "decide/action",
            HookEvent.DECISION_BLOCK: "hook/block",
        }
        return mapping.get(self, self.value)

    @classmethod
    def from_legacy(cls, name: str) -> "HookEvent":
        """从旧事件名反查。"""
        reverse = {
            "round/start": cls.ROUND_START,
            "round/end": cls.ROUND_END,
            "PreToolUse": cls.PRE_TOOL,
            "PostToolUse": cls.POST_TOOL,
            "decide/action": cls.DECISION_APPLY,
            "hook/block": cls.DECISION_BLOCK,
        }
        return reverse.get(name, cls.STEP_START)  # 默认映射

    @property
    def category(self) -> str:
        """事件分类（用于过滤/分组）。"""
        return self.value.split("/")[0]


# ---------------------------------------------------------------------------
# 2. HookPayload — 不可变事件载荷
# ---------------------------------------------------------------------------

@dataclass
class HookPayload:
    """Hook 事件载荷 — 对标 DSH HookContext。

    每个 HookEvent 触发时创建，包含事件元数据 + 可选的业务数据。
    """
    event: HookEvent
    timestamp: float = field(default_factory=time.time)
    task_name: str = ""
    round_num: int = 0
    step_name: str = ""

    # 可选业务数据
    data: dict = field(default_factory=dict)
    # 额外上下文
    error: str = ""
    elapsed_ms: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为 JSON 兼容字典。"""
        d: dict[str, Any] = {
            "event": self.event.value,
            "timestamp": self.timestamp,
            "task": self.task_name,
            "round": self.round_num,
            "step": self.step_name,
        }
        if self.error:
            d["error"] = self.error
        if self.elapsed_ms:
            d["elapsed_ms"] = self.elapsed_ms
        if self.data:
            # 浅层脱敏：只记录 key，不记录完整 value（除非是简单类型）
            safe_data = {}
            for k, v in self.data.items():
                if isinstance(v, (str, int, float, bool)):
                    safe_data[k] = v
                elif isinstance(v, (list, tuple)) and len(v) <= 5:
                    safe_data[k] = str(v)[:100]
                else:
                    safe_data[k] = f"<{type(v).__name__}>"
            d["data"] = safe_data
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @property
    def is_error(self) -> bool:
        return bool(self.error)

    @property
    def category(self) -> str:
        return self.event.category


# ---------------------------------------------------------------------------
# 3. HookListener — 事件监听器协议
# ---------------------------------------------------------------------------

HookListener = Callable[[HookPayload], None]
"""事件监听器签名: (HookPayload) -> None"""


# ---------------------------------------------------------------------------
# 4. HookBus — 事件总线
# ---------------------------------------------------------------------------

class HookBus:
    """事件总线 — 对标 DSH HookManager。

    核心职责：
    1. 注册/注销监听器（按事件类型过滤）
    2. 触发事件（fire）→ 通知所有匹配的监听器
    3. 自动联动 EventLog（每个事件产生一条 JSONL 记录）

    特性：
    - 通配符监听：监听 "*" 可以收到所有事件
    - 滞后绑定：监听器注册时可以指定事件类型列表
    - 异常隔离：一个监听器抛异常不影响其他监听器
    """

    def __init__(self, event_log: Any = None):
        """
        Args:
            event_log: EventLog 实例（可选）。传入后自动联动。
        """
        self._listeners: dict[str, list[HookListener]] = {}
        self._event_log = event_log  # EventLog 实例（用于自动记录）
        self._history: list[HookPayload] = []
        self._max_history = 500

    # ── 注册/注销 ──

    def on(self, event: HookEvent | str, listener: HookListener):
        """注册事件监听器。

        Args:
            event: HookEvent 枚举值 或 "*"（通配符，收到所有事件）
            listener: 回调函数 (HookPayload) -> None
        """
        key = event.value if isinstance(event, HookEvent) else event
        if key not in self._listeners:
            self._listeners[key] = []
        self._listeners[key].append(listener)

    def on_any(self, events: list[HookEvent | str], listener: HookListener):
        """一次注册监听多个事件。"""
        for e in events:
            self.on(e, listener)

    def off(self, event: HookEvent | str, listener: HookListener):
        """注销监听器。"""
        key = event.value if isinstance(event, HookEvent) else event
        if key in self._listeners and listener in self._listeners[key]:
            self._listeners[key].remove(listener)

    # ── 触发 ──

    def fire(
        self,
        event: HookEvent,
        *,
        task_name: str = "",
        round_num: int = 0,
        step_name: str = "",
        data: dict | None = None,
        error: str = "",
        elapsed_ms: float = 0.0,
        metadata: dict | None = None,
    ) -> HookPayload:
        """触发一个事件 → 通知监听器 + 写入 EventLog。

        Returns: 创建的 HookPayload（调用方可以进一步检查）。
        """
        payload = HookPayload(
            event=event,
            task_name=task_name,
            round_num=round_num,
            step_name=step_name,
            data=data or {},
            error=error,
            elapsed_ms=elapsed_ms,
            metadata=metadata or {},
        )

        # 1. 记录历史
        self._add_to_history(payload)

        # 2. 联动 EventLog
        self._log_to_event_log(payload)

        # 3. 通知监听器
        self._notify(event.value, payload)
        self._notify("*", payload)  # 通配符监听器

        return payload

    # ── 快捷方法 ──

    def fire_session_start(self, task_name: str = "", **kwargs):
        return self.fire(HookEvent.SESSION_START, task_name=task_name, **kwargs)

    def fire_session_end(self, task_name: str = "", **kwargs):
        return self.fire(HookEvent.SESSION_END, task_name=task_name, **kwargs)

    def fire_round_start(self, task_name: str = "", round_num: int = 0, **kwargs):
        return self.fire(HookEvent.ROUND_START, task_name=task_name, round_num=round_num, **kwargs)

    def fire_round_end(self, task_name: str = "", round_num: int = 0, **kwargs):
        return self.fire(HookEvent.ROUND_END, task_name=task_name, round_num=round_num, **kwargs)

    def fire_step(self, event: HookEvent, task_name: str = "", round_num: int = 0, step_name: str = "", **kwargs):
        return self.fire(event, task_name=task_name, round_num=round_num, step_name=step_name, **kwargs)

    def fire_tool(self, event: HookEvent, task_name: str = "", tool_name: str = "", **kwargs):
        return self.fire(event, task_name=task_name, data={"tool": tool_name}, **kwargs)

    def fire_pattern(self, event: HookEvent, task_name: str = "", pattern_id: str = "", **kwargs):
        return self.fire(event, task_name=task_name, data={"pattern_id": pattern_id}, **kwargs)

    def fire_evolution(self, event: HookEvent, task_name: str = "", **data):
        """触发进化生命周期事件 (P3-E4)。

        data 可含: generation / population / best_fitness / candidates /
        source_pool_size / candidates_path / committed 等。
        """
        return self.fire(event, task_name=task_name, data=dict(data))

    # ── 查询 ──

    @property
    def history(self) -> list[HookPayload]:
        return list(self._history)

    def filter(self, event: HookEvent | None = None, category: str | None = None) -> list[HookPayload]:
        """过滤历史事件。"""
        results = self._history
        if event is not None:
            results = [p for p in results if p.event == event]
        if category is not None:
            results = [p for p in results if p.category == category]
        return results

    def count(self, event: HookEvent | None = None) -> int:
        """统计事件数。"""
        if event is None:
            return len(self._history)
        return sum(1 for p in self._history if p.event == event)

    @property
    def listener_count(self) -> int:
        return sum(len(v) for v in self._listeners.values())

    # ── 内部 ──

    def _notify(self, key: str, payload: HookPayload):
        """通知匹配的监听器（异常隔离）。"""
        for listener in self._listeners.get(key, []):
            try:
                listener(payload)
            except Exception:
                _log.exception("[hook-bus] listener error for %s", key)

    def _add_to_history(self, payload: HookPayload):
        self._history.append(payload)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def _log_to_event_log(self, payload: HookPayload):
        """将事件写入 EventLog（JSONL）。"""
        if self._event_log is None:
            return
        try:
            self._event_log.append(payload.event.value, payload.to_dict())
        except Exception:
            _log.debug("[hook-bus] event_log write failed", exc_info=True)


# ---------------------------------------------------------------------------
# 5. 内置监听器
# ---------------------------------------------------------------------------

def log_listener(payload: HookPayload):
    """默认监听器：打印到日志。"""
    _log.info("[hook] %s | task=%s round=%s step=%s%s",
              payload.event.value, payload.task_name,
              payload.round_num, payload.step_name,
              f" | err={payload.error[:50]}" if payload.error else "")


def stats_listener():
    """创建统计监听器（闭包，保持 counter）。"""
    counter: dict[str, int] = {}

    def _on_event(payload: HookPayload):
        key = payload.event.value
        counter[key] = counter.get(key, 0) + 1

    _on_event.stats = counter  # type: ignore
    return _on_event


def threshold_guard(event: HookEvent, max_count: int, action: Callable[[], None]):
    """阈值守卫：某事件超过次数触发回调。

    Returns: 监听器函数 + 检查函数。
    """
    count = [0]

    def _on_event(payload: HookPayload):
        if payload.event == event:
            count[0] += 1
            if count[0] >= max_count:
                action()

    def check() -> bool:
        return count[0] >= max_count

    _on_event.check = check  # type: ignore
    return _on_event
