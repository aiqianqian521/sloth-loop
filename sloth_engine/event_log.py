"""事件溯源会话日志 — 一行自解释的 OODA 事件日志。

v3.0 重构: 从 DSH 的 {seq, time, type, data} 信封改为自包含扁平结构。
每行 JSON 包含: 时间(ISO8601+毫秒)、任务名、轮次、步骤、状态(PASS/FAIL/WARN/SKIP/START)、
人类可读消息、错误详情、耗时。不依赖外部字典即可理解任何一行日志。

格式示例:
{"ts":"2026-08-18 14:30:25.123","task":"demo-backtest-loop","round":3,
 "step":"observe","status":"PASS","message":"in=5 excl=0 lib=18 failures",
 "error":"","elapsed_ms":333}

状态枚举:
  START - 步骤开始
  PASS  - 步骤成功
  FAIL  - 步骤失败（含 error 字段说明具体错误）
  WARN  - 步骤警告（非阻塞性问题）
  SKIP  - 步骤跳过

移植自 DSH packages/session/ (事件溯源模式)，针对 loop 运维场景重新设计。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hook_events import HookEvent
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# ============================================================================
# 状态枚举
# ============================================================================

EventStatus = Literal["START", "PASS", "FAIL", "WARN", "SKIP", "UNKNOWN"]

# ============================================================================
# ContextSnapshot — Wave2: 上下文可观察性
# ============================================================================

@dataclass
class ContextSnapshot:
    """一次 Decide/Act/Verify 可见上下文的安全摘记。

    Wave2 原则: 记录“模型/任务看到了什么”的溯源，但不落明文敏感——正文只存摘要，
    指针用 hash。所有字段均可选且可安全序列化。

    Attributes:
        context_type:   快照类型, 如 observe/decide/act/verify。
        input_hash:     输入信号的 sha256 摘要(前 16 位)。
        config_hash:    配置块的 sha256 摘要。
        pattern_ids:    本轮加载/命中的模式库 id 列表(只存 id，不存规则正文)。
        correction_ids: 命中的前置矫正规则 id 列表。
        sources:        上下文来源清单: [{kind, path, summary?}]。
        summary:        一条人类可读的中性摘要(不含敏感值)。
    """
    context_type: str
    input_hash: str = ""
    config_hash: str = ""
    pattern_ids: list = field(default_factory=list)
    correction_ids: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"context_type": self.context_type}
        if self.input_hash:
            d["input_hash"] = self.input_hash
        if self.config_hash:
            d["config_hash"] = self.config_hash
        if self.pattern_ids:
            d["pattern_ids"] = self.pattern_ids
        if self.correction_ids:
            d["correction_ids"] = self.correction_ids
        if self.sources:
            d["sources"] = self.sources
        if self.summary:
            d["summary"] = self.summary
        return d


def build_context_snapshot(*, context_type: str, input_data=None,
                           config=None, pattern_ids=None,
                           correction_ids=None, sources=None,
                           summary: str = "") -> ContextSnapshot:
    """根据原始输入构建脱敏快照：正文只留 hash/摘要，避免记录敏感明文。

    input_data/config 仅用于求可重复 hash(传 None 则省略对应 hash)。
    sources 形如 [{kind, path, summary}]，只写入中性摘要，不记录原文。
    """
    import hashlib

    def _hash(obj) -> str:
        if obj is None:
            return ""
        try:
            payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            payload = str(obj)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    return ContextSnapshot(
        context_type=context_type,
        input_hash=_hash(input_data),
        config_hash=_hash(config),
        pattern_ids=list(pattern_ids or []),
        correction_ids=list(correction_ids or []),
        sources=[dict(s) if isinstance(s, dict) else {"summary": str(s)}
                 for s in (sources or [])],
        summary=summary,
    )



# ============================================================================
# OODA 步骤名常量
# ============================================================================

STEP_UNDERSTAND = "understand"
STEP_OBSERVE    = "observe"
STEP_ORIENT     = "orient"
STEP_DECIDE     = "decide"
STEP_ACT        = "act"
STEP_VERIFY     = "verify"
STEP_LEARN       = "learn"

# Act 子步骤
SUBSTEP_ACT_EXECUTE = "act:execute"
SUBSTEP_ACT_RESULT  = "act:result"
SUBSTEP_ACT_RETRY   = "act:retry"

# 步骤名 → 人类可读标签

# ============================================================================
# CTX-05: Surface/Log layering constants
# Surface events enter model context; Log events are audit-only.
# ============================================================================

# Events that enter the model context window (OODA core steps)
SURFACE_EVENT_TYPES: frozenset[str] = frozenset({
    STEP_OBSERVE, STEP_ORIENT, STEP_DECIDE, STEP_ACT,
})

# Max message length for surface events (truncate longer messages)
SURFACE_MESSAGE_MAX_LEN: int = 500
STEP_LABELS: dict[str, str] = {
    STEP_UNDERSTAND: "Understand Task",
    STEP_OBSERVE:    "Observe State",
    STEP_ORIENT:     "Diagnose Root Cause",
    STEP_DECIDE:     "Make Decision",
    STEP_ACT:        "Execute Action",
    STEP_VERIFY:     "Verify Results",
    STEP_LEARN:       "Record Lessons",
    SUBSTEP_ACT_EXECUTE: "Execute",
    SUBSTEP_ACT_RESULT:  "Result",
    SUBSTEP_ACT_RETRY:   "Retry",
}

# ============================================================================
# 兼容层 — 保留旧事件类型常量（orchestrator 中引用）
# ============================================================================

EVT_ROUND_START   = "round/start"
EVT_ROUND_END     = "round/end"
EVT_ACT_EXECUTE   = "act/execute"
EVT_ACT_RESULT    = "act/result"
EVT_ACT_RETRY     = "act/retry"
EVT_DIAGNOSIS     = "orient/diagnosis"
EVT_DECISION      = "decide/action"
EVT_VERIFY_RESULT = "verify/result"
EVT_LEARN_RECORD  = "learn/record"
EVT_SUB_TASK_START = "subtask/start"
EVT_SUB_TASK_END   = "subtask/end"

KNOWN_OODA_EVENT_TYPES: set[str] = {
    EVT_ROUND_START, EVT_ROUND_END,
    "step/understand/start", "step/understand/end",
    "step/observe/start", "step/observe/end",
    "step/orient/start", "step/orient/end",
    "step/decide/start", "step/decide/end",
    "step/act/start", "step/act/end",
    "step/verify/start", "step/verify/end",
    "step/learn/start", "step/learn/end",
    EVT_ACT_EXECUTE, EVT_ACT_RESULT, EVT_ACT_RETRY,
    EVT_DIAGNOSIS, EVT_DECISION,
    EVT_VERIFY_RESULT, EVT_LEARN_RECORD,
    EVT_SUB_TASK_START, EVT_SUB_TASK_END,
    "circuit/transition",
    # P3-E2: HookEvent 生命周期事件
    "hook/install", "hook/uninstall",
    "hook/pre", "hook/post",
    "hook/error",
    "tool/pre", "tool/post", "tool/error",
    "lifecycle/init", "lifecycle/shutdown",
}

STEP_EVENT_MAP = {
    "understand": ("step/understand/start", "step/understand/end"),
    "observe":    ("step/observe/start",    "step/observe/end"),
    "orient":     ("step/orient/start",     "step/orient/end"),
    "decide":     ("step/decide/start",     "step/decide/end"),
    "act":        ("step/act/start",        "step/act/end"),
    "verify":     ("step/verify/start",     "step/verify/end"),
    "learn":      ("step/learn/start",      "step/learn/end"),
}

def step_start_event(phase: str) -> str:
    return f"step/{phase}/start"

def step_end_event(phase: str) -> str:
    return f"step/{phase}/end"


# ============================================================================
# LoopEvent — v3.0 自包含事件
# ============================================================================

@dataclass
class LoopEvent:
    """OODA 循环中的单个不可变事件。

    v3.0: 从 {seq, time, type, data} 重构为自包含扁平结构。
    每个字段名即自解释——不需要先查 type 枚举才能理解 data 内容。

    兼容性: .to_dict() 输出新格式；保留 seq/time/type/data 字段供旧代码读取。
    """

    # ── 核心标识（一行自解释）─────────────────────
    ts: str            # "2026-08-18 14:30:25.123" 本地时间 ISO8601 + 毫秒
    task: str          # 任务名，如 "demo-backtest-loop"
    round: int         # 轮次号，从 1 开始
    step: str          # 步骤: understand|observe|orient|decide|act|act:retry|verify|learn
    status: EventStatus  # START | PASS | FAIL | WARN | SKIP

    # ── 详细信息 ─────────────────────────────────
    message: str = ""  # 人类可读的一行描述
    error: str = ""    # 错误详情（status=FAIL 时必有内容）
    elapsed_ms: float = 0  # 步骤耗时（毫秒）

    # ── 扩展 ─────────────────────────────────────
    data: dict = field(default_factory=dict)  # 额外结构化数据
    # ── Wave2 上下文快照（可观察性溯源，默认 None 以兼容旧卷）────
    ctx: ContextSnapshot | None = None


    # ── 兼容层（保留给旧代码）────────────────────
    seq: int = 0       # 单调递增序号（软弃用，用于事件关联）
    time: float = 0.0  # epoch 秒（软弃用，用 ts 替代）

    @staticmethod
    def now_ts() -> str:
        """生成当前本地时间的 ISO8601+毫秒 字符串。"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
               f"{int(time.time() * 1000) % 1000:03d}"

    def to_dict(self) -> dict:
        """序列化为 JSON 行。v3.0 扁平格式。"""
        d: dict[str, Any] = {
            "seq": self.seq,
            "time": self.time,
            "ts": self.ts,
            "task": self.task,
            "round": self.round,
            "step": self.step,
            "status": self.status,
            "message": self.message,
        }
        if self.error:
            d["error"] = self.error
        if self.elapsed_ms > 0:
            d["elapsed_ms"] = self.elapsed_ms
        if self.data:
            d["data"] = self.data
        if self.ctx is not None:
            d["ctx"] = self.ctx.to_dict()
        return d


# ============================================================================
# EventLog — v3.0 JSONL 持久化
# ============================================================================

class EventLog:
    """不可变事件日志，JSONL 持久化。

    v3.0: 每行 JSON 自包含——ts/task/round/step/status 五个字段即可理解上下文。
    追加写入，支持完整回放和跨轮查询。
    """

    def __init__(self, path: Path | str, task_name: str = "", auto_load: bool = True):
        """事件日志（JSONL，只追加）。

        Args:
            path: 事件日志文件路径。
            task_name: 任务名（新写入的事件默认归属）。
            auto_load: 构造时是否加载已有文件中的事件，使 .count/.events/.as_dicts()
                立即可用。默认 True；追加写入不受影响（新事件 seq 从已加载的最大值继续）。
        """
        self._path = Path(path)
        self._task_name = task_name
        self._seq = 0
        self._events: list[LoopEvent] = []
        self._surface_events: list[LoopEvent] = []  # CTX-05: model-visible events
        self._lock = threading.RLock()  # C-1: _write_event behind a reentrant lock
        self._last_replay_malformed = 0  # F6@replay: surface bad/incomplete lines, never silent 0
        if auto_load:
            loaded = self.replay()
            if loaded:
                self._events = loaded
                # CTX-05: also populate surface events on reload
                self._surface_events = [e for e in loaded if e.step and e.step.split(':')[0] in SURFACE_EVENT_TYPES]
                self._seq = max(e.seq for e in loaded)
                if not self._task_name and loaded:
                    self._task_name = loaded[-1].task

    # ── 核心写入 ─────────────────────────────────

    def append(self, event_type: str, data: dict | None = None) -> LoopEvent:
        """追加事件（兼容旧接口）。

        根据 event_type 自动拆解为新的扁平字段。
        兼容性: 保留 seq/time/type/data 供旧代码读取。

        Args:
            event_type: 事件类型字符串。自动映射到 step/status。
            data: 事件 payload。特殊键 'round'/'status'/'error'/'elapsed_ms' 会被提取。
        """
        data = data or {}

        # 自动拆解
        step = self._event_type_to_step(event_type)
        status = self._event_type_to_status(event_type, data)
        message = self._build_message(event_type, data)
        error_msg = data.get("error", "")
        elapsed = data.get("elapsed_ms", 0)
        round_num = data.get("round", 0)

        # C-1: _seq 自增 + 构造 + 写入在同一 RLock 内原子化(防并发重复 seq/撕裂行)
        with self._lock:
            self._seq += 1
            event = LoopEvent(
                seq=self._seq,
                time=time.time(),
                ts=LoopEvent.now_ts(),
                task=self._task_name,
                round=round_num,
                step=step,
                status=status,
                message=message,
                error=error_msg,
                elapsed_ms=elapsed,
                data={"_type": event_type, **{k: v for k, v in data.items()
                      if k not in ("round", "status", "error", "elapsed_ms", "ctx")}},
                ctx=self._ctx_from(data or {}),
            )
            self._events.append(event)
            # CTX-05: also track surface events separately
            if step and step.split(':')[0] in SURFACE_EVENT_TYPES:
                self._surface_events.append(event)
            self._write_event(event)
        return event

    def append_step(self, step: str, status: EventStatus,
                    message: str = "", round_num: int = 0,
                    error: str = "", elapsed_ms: float = 0,
                    data: dict | None = None,
                    ctx: ContextSnapshot | None = None) -> LoopEvent:
        """直接追加步骤事件（v3.0 推荐接口）。

        跳过 event_type 拆解，直接提供扁平字段。
        """
        with self._lock:
            self._seq += 1
            event = LoopEvent(
                seq=self._seq,
                time=time.time(),
                ts=LoopEvent.now_ts(),
                task=self._task_name,
                round=round_num,
                step=step,
                status=status,
                message=message,
                error=error,
                elapsed_ms=elapsed_ms,
                data=data or {},
                ctx=ctx,
            )
            self._events.append(event)
            # CTX-05: also track surface events separately
            if step and step.split(':')[0] in SURFACE_EVENT_TYPES:
                self._surface_events.append(event)
            self._write_event(event)
        return event

    # ── event_type → 字段拆解（内部）─────────────

    @staticmethod
    def _event_type_to_step(event_type: str) -> str:
        """从 event_type 字符串提取步骤名。"""
        if "/" not in event_type:
            return event_type

        parts = event_type.split("/")
        # "step/observe/end" → "observe"
        if parts[0] == "step" and len(parts) >= 2:
            return parts[1]
        # "act/execute" → "act:execute"
        if parts[0] == "act":
            return f"act:{parts[1]}" if len(parts) >= 2 else "act"
        # "round/start" → "round"
        if parts[0] == "round":
            return f"round:{parts[1]}" if len(parts) >= 2 else "round"
        # "orient/diagnosis" → "orient"
        # "verify/result" → "verify"
        # "learn/record" → "learn"
        # "decide/action" → "decide"
        return parts[0]

    # ── P3-E2: HookEvent 类型支持 ─────────────────
    def append_hook_event(self, event: "HookEvent", data: dict | None = None) -> LoopEvent:
        """追加 HookEvent 生命周期事件（标准化 schema）。

        HookEvent 枚举值如 "round/start"、"tool/pre" 等，
        自动映射到 step/status/message。
        """
        return self.append(event.value, data)

    def validate_event_type(self, event_type: str) -> bool:
        """校验事件类型是否在已知集合中。"""
        return event_type in KNOWN_OODA_EVENT_TYPES

    @staticmethod
    def _event_type_to_status(event_type: str, data: dict) -> EventStatus:
        """从 event_type 推断状态。"""
        # 步骤 end 事件 → 根据 data 判断
        if "/end" in event_type:
            err = data.get("error", "")
            if err:
                return "FAIL"
            if data.get("complete") is False:
                return "WARN"
            return "PASS"
        # 步骤 start → START
        if "/start" in event_type:
            return "START"
        # act/result → 根据 status 判断
        if event_type == EVT_ACT_RESULT:
            s = data.get("status", "")
            if s == "error":
                return "FAIL"
            if s == "skipped":
                return "SKIP"
            return "PASS"
        # act/retry → 根据 ok 判断
        if event_type == EVT_ACT_RETRY:
            return "FAIL" if not data.get("ok") else "PASS"
        # verify/result → 根据 fail_count 判断
        if event_type == EVT_VERIFY_RESULT:
            return "FAIL" if data.get("fail_count", 0) > 0 else "PASS"
        # round/end → PASS
        if event_type == EVT_ROUND_END:
            return "PASS"
        # round/start → START
        if event_type == EVT_ROUND_START:
            return "START"
        return "PASS"

    @staticmethod
    def _ctx_from(data: dict) -> ContextSnapshot | None:
        """从事件 dict（含顶层 ctx）中还原 ContextSnapshot；无则返回 None。"""
        raw = data.get("ctx")
        if isinstance(raw, dict):
            import dataclasses
            fields = {f.name for f in dataclasses.fields(ContextSnapshot)}
            return ContextSnapshot(**{k: v for k, v in raw.items() if k in fields})
        return None

    @staticmethod
    def _build_message(event_type: str, data: dict) -> str:
        """从 event_type + data 构建人类可读消息。"""
        # step end 消息
        if "/end" in event_type:
            parts = []
            for k, v in data.items():
                if k in ("complete", "round"):
                    continue
                if isinstance(v, (int, float, str, bool)):
                    parts.append(f"{k}={v}")
            return " | ".join(parts[:4])
        # act/result
        if event_type == EVT_ACT_RESULT:
            status = data.get("status", "")
            trades = data.get("trades", 0)
            error = data.get("error", "")
            elapsed = data.get("elapsed_ms", 0)
            msg = f"status={status} trades={trades}"
            if elapsed:
                msg += f" {elapsed:.0f}ms"
            if error:
                msg += f" | ERROR: {error[:200]}"
            return msg
        # act/retry
        if event_type == EVT_ACT_RETRY:
            strategy = data.get("strategy", "")
            note = data.get("note", "")
            if note:
                return f"{strategy} — {note[:150]}"
            return strategy
        # round/start
        if event_type == EVT_ROUND_START:
            return f"signals_in={data.get('signals_input', '?')}"
        # round/end
        if event_type == EVT_ROUND_END:
            return f"events={data.get('total_events', '?')}"
        return ""

    # ── 文件 I/O ─────────────────────────────────

    def _write_event(self, event: LoopEvent) -> None:
        # C-1: 单一写入出口 + RLock 串行化(append 已持同锁, RLock 可重入; 直调也安全)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def replay(self, from_seq: int = 0) -> list[LoopEvent]:
        """从文件重放事件。"""
        self._last_replay_malformed = 0  # F6@replay: 坏/残缺行计数, 不静默吞
        if not self._path.exists():
            return []
        events: list[LoopEvent] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    self._last_replay_malformed += 1  # 坏 JSON: 计数暴露, 不静默丢
                    continue
                if obj.get("seq", 0) >= from_seq:
                    events.append(LoopEvent(
                        seq=obj.get("seq", 0),
                        time=obj.get("time", 0),
                        ts=obj.get("ts", ""),
                        task=obj.get("task", ""),
                        round=obj.get("round", 0),
                        step=obj.get("step", ""),
                        status=obj.get("status", "UNKNOWN"),
                        message=obj.get("message", ""),
                        error=obj.get("error", ""),
                        elapsed_ms=obj.get("elapsed_ms", 0),
                        data=obj.get("data", {}),
                        ctx=EventLog._ctx_from(obj),
                    ))
        return events

    def filter(self, event_type: str | None = None,
               from_seq: int = 0) -> list[LoopEvent]:
        """按旧 type 过滤（兼容层: 用 step 字段匹配）。"""
        events = self.replay(from_seq)
        if event_type is None:
            return events
        return [e for e in events if event_type in (e.data.get("_type", ""), e.step)]

    # ── 查询方法 ─────────────────────────────────

    def last_event(self, event_type: str | None = None) -> LoopEvent | None:
        """查找最后一个匹配类型的旧事件（兼容层）。"""
        if not self._events:
            return None
        if event_type is None:
            return self._events[-1]
        for e in reversed(self._events):
            if event_type in (e.data.get("_type", ""), e.step):
                return e
        return None

    def last_event_by_step(self, step: str) -> LoopEvent | None:
        """按新 step 字段查找最后一个匹配事件。"""
        for e in reversed(self._events):
            if e.step == step:
                return e
        return None

    def last_event_by_status(self, status: EventStatus) -> LoopEvent | None:
        """查找最后一个指定状态的事件。"""
        for e in reversed(self._events):
            if e.status == status:
                return e
        return None

    def events_in_range(self, from_seq: int, to_seq: int) -> list[LoopEvent]:
        return [e for e in self._events if from_seq <= e.seq <= to_seq]

    def get_round_events(self, round_num: int) -> list[LoopEvent]:
        """获取指定轮的所有事件。"""
        return [e for e in self._events if e.round == round_num]

    def get_last_act_result(self) -> dict | None:
        evt = self.last_event(EVT_ACT_RESULT)
        if evt is None:
            return None
        return {"status": evt.status, "error": evt.error, "message": evt.message}

    def get_last_verify_result(self) -> dict | None:
        evt = self.last_event(EVT_VERIFY_RESULT)
        if evt is None:
            return None
        return {"status": evt.status, "error": evt.error, "message": evt.message}

    def get_last_diagnosis(self) -> dict | None:
        evt = self.last_event(EVT_DIAGNOSIS)
        if evt is None:
            return None
        return {"status": evt.status, "message": evt.message}

    def get_retry_history(self, round_num: int | None = None) -> list[dict]:
        events = self.filter(EVT_ACT_RETRY)
        if round_num is not None:
            events = [e for e in events if e.round == round_num]
        return [{"strategy": e.message.split(" —")[0] if e.message else "",
                 "ok": e.status == "PASS", "note": e.message} for e in events]

    def get_summary(self) -> dict:
        """返回日志摘要：总事件数、状态分布。"""
        status_counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0, "START": 0}
        for e in self._events:
            status_counts[e.status] = status_counts.get(e.status, 0) + 1
        return {
            "total_events": self._seq,
            "status_counts": status_counts,
            "rounds": len(set(e.round for e in self._events if e.round > 0)),
            "failures": [{"round": e.round, "step": e.step, "error": e.error[:200]}
                         for e in self._events if e.status == "FAIL"],
        }

    # ── 属性 ─────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    @property
    def count(self) -> int:
        return self._seq

    @property
    def events(self) -> list[LoopEvent]:
        return list(self._events)

    # -- CTX-05: Surface/Log layering queries ---------------------------

    def get_surface_events(self, last_n: int | None = None) -> list[LoopEvent]:
        """Return model-visible (surface) events.

        Surface events = OODA core steps (observe, orient, decide, act).
        These are the events that should enter the model context window.
        Messages are length-limited to SURFACE_MESSAGE_MAX_LEN.
        """
        events = self._surface_events
        if last_n is not None:
            events = events[-last_n:]
        return list(events)

    def get_log_events(self, last_n: int | None = None) -> list[LoopEvent]:
        """Return audit-only (log) events that should NEVER enter model context.

        Log events = infrastructure/internal events (round transitions,
        learn records, verify results, etc.). These are for debugging/audit only.
        """
        events = [e for e in self._events if e.step and e.step.split(':')[0] not in SURFACE_EVENT_TYPES]
        if last_n is not None:
            events = events[-last_n:]
        return events

    def get_surface_text(self, last_n: int | None = None, separator: str = '\n---\n') -> str:
        """Return surface events as a compact text blob for model context injection.

        Each event is formatted as: [round:step] status message
        Messages exceeding SURFACE_MESSAGE_MAX_LEN are truncated with '...'.
        """
        truncated = 0
        parts: list[str] = []
        events = self.get_surface_events(last_n)
        for e in events:
            msg = e.message or ''
            original_len = len(msg)
            if len(msg) > SURFACE_MESSAGE_MAX_LEN:
                msg = msg[:SURFACE_MESSAGE_MAX_LEN] + '...'
                truncated += 1
            parts.append(f'[{e.round}:{e.step}] {e.status} {msg}')
        if truncated:
            parts.append(f'# {truncated} surface event(s) truncated')
        return separator.join(parts)

    @property
    def surface_count(self) -> int:
        """Number of surface (model-visible) events."""
        return len(self._surface_events)

    @property
    def log_count(self) -> int:
        """Number of log (audit-only) events."""
        return len(self._events) - len(self._surface_events)
    def diagnose(self) -> "EventDiagnostics":
        """创建诊断器并执行完整诊断。

        新增于 P1-N3 (EventLog 可诊断化)。
        """
        from event_diagnostics import EventDiagnostics
        return EventDiagnostics(self)

    def diagnose_summary(self) -> dict:
        """快速获取诊断摘要字典。

        新增于 P1-N3 (EventLog 可诊断化)。
        """
        from event_diagnostics import EventDiagnostics
        return EventDiagnostics(self).summary_dict()

    def as_dicts(self) -> list[dict]:
        return [e.to_dict() for e in self._events]

