"""Session Projection 层 — P2-N3: 对标 DSH session-projection。

从 EventLog 事件流折叠 (fold) 出当前状态快照。
每一个事件被一个 fold 函数处理，产生不可变的状态投影。

对标: DSH packages/session-projection — event-sourced state fold
设计:
  - ProjectionSpec: 定义一个投影 (key + initial_state + fold_fn)
  - SessionProjector: 注册多个 ProjectionSpec → 重放事件 → 产出投影映射
  - 每个投影独立 fold, 互不干扰
  - 投影结果是纯数据 (dict), 可序列化
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# 避免循环导入
if __name__ != "__main__":
    try:
        from event_log import LoopEvent
    except ImportError:
        LoopEvent = None  # type: ignore


# ============================================================================
# ProjectionSpec
# ============================================================================

@dataclass
class ProjectionSpec:
    """定义一个投影：从事件流折叠出的状态视图。

    Attributes:
        key:         投影键名 (如 "todos", "plan", "turn_summary")
        initial_state: 初始状态 (无事件时的默认值)
        fold:         折叠函数 (current_state, event) → new_state
        description:  人类可读描述
    """
    key: str
    initial_state: Any
    fold: Callable[[Any, "LoopEvent"], Any]
    description: str = ""


# ============================================================================
# SessionProjector
# ============================================================================

class SessionProjector:
    """会话投影引擎。

    注册多个 ProjectionSpec → 重放 EventLog 事件 → 产出投影映射。

    使用方式:
        projector = SessionProjector()
        projector.register(ProjectionSpec("turns", 0, lambda s, e: s + 1))
        projector.register(ProjectionSpec("failures", [],
                           lambda s, e: s + [e.error] if e.status == "FAIL" else s))
        state = projector.replay(event_log.events)
        # state == {"turns": 5, "failures": ["disk full", ...]}
    """

    def __init__(self):
        self._specs: dict[str, ProjectionSpec] = {}

    def register(self, spec: ProjectionSpec) -> None:
        """注册一个投影规约。同名覆盖。"""
        self._specs[spec.key] = spec

    def register_many(self, specs: list[ProjectionSpec]) -> None:
        """批量注册。"""
        for spec in specs:
            self.register(spec)

    def remove(self, key: str) -> None:
        """移除一个投影规约。"""
        self._specs.pop(key, None)

    # ── 重放 ──

    def replay(self, events: list) -> dict[str, Any]:
        """从事件列表重放所有投影，返回 {key: projected_state}。

        Args:
            events: LoopEvent 列表（必须按 seq 排序）

        Returns:
            {key: folded_state} 映射
        """
        state: dict[str, Any] = {}
        for spec in self._specs.values():
            state[spec.key] = spec.initial_state

        sorted_events = sorted(events, key=lambda e: e.seq)
        for event in sorted_events:
            for spec in self._specs.values():
                try:
                    state[spec.key] = spec.fold(state[spec.key], event)
                except Exception:
                    # fold 失败不中断其他投影
                    pass

        return state

    def replay_incremental(self, events: list, base_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """增量重放：在已有 base_state 上叠加事件。

        Args:
            events: 新增事件列表
            base_state: 已有投影状态（None 则从 initial_state 开始）

        Returns:
            更新后的 {key: projected_state}
        """
        if base_state is None:
            base_state = {spec.key: spec.initial_state for spec in self._specs.values()}

        sorted_events = sorted(events, key=lambda e: e.seq)
        for event in sorted_events:
            for spec in self._specs.values():
                if spec.key in base_state:
                    try:
                        base_state[spec.key] = spec.fold(base_state[spec.key], event)
                    except Exception:
                        pass

        return base_state

    # ── 查询 ──

    @property
    def spec_keys(self) -> list[str]:
        return list(self._specs.keys())

    def get_spec(self, key: str) -> ProjectionSpec | None:
        return self._specs.get(key)

    # ── 便利方法 ──

    def project(self, event_log: "EventLog") -> dict[str, Any]:
        """对 EventLog 实例执行重放（快捷方式）。

        注意：需要传入 EventLog 实例，避免循环导入。
        """
        return self.replay(event_log.events)


# ============================================================================
# 预置投影工厂
# ============================================================================

def create_default_projector() -> SessionProjector:
    """创建带预置投影的 SessionProjector。

    预置投影:
    - turn_count: 轮次计数
    - failure_count: 失败次数
    - failure_messages: 失败消息列表
    - step_timeline: 步骤时间线 [{"step":..., "status":..., "ts":...}]
    - last_status: 最后一条事件的状态
    - status_breakdown: {PASS: n, FAIL: n, WARN: n, SKIP: n, START: n}
    """
    p = SessionProjector()

    # 轮次计数: 遇到 round > 当前最大值 → 更新
    p.register(ProjectionSpec(
        key="turn_count",
        initial_state=0,
        fold=lambda s, e: max(s, e.round),
        description="已完成的最大轮次号",
    ))

    # 失败消息列表
    p.register(ProjectionSpec(
        key="failure_messages",
        initial_state=[],
        fold=lambda s, e: s + [{
            "seq": e.seq, "round": e.round, "step": e.step,
            "error": e.error[:200], "ts": e.ts,
        }] if e.status == "FAIL" else s,
        description="所有 FAIL 事件的摘要",
    ))

    # 步骤时间线 (最近 20 条)
    p.register(ProjectionSpec(
        key="step_timeline",
        initial_state=[],
        fold=lambda s, e: (s + [{
            "seq": e.seq, "step": e.step, "status": e.status,
            "ts": e.ts, "elapsed_ms": e.elapsed_ms,
        }])[-20:],
        description="最近 20 个步骤的时间线",
    ))

    # 最后状态
    p.register(ProjectionSpec(
        key="last_status",
        initial_state={"status": "UNKNOWN", "step": "", "ts": ""},
        fold=lambda s, e: {"status": e.status, "step": e.step, "ts": e.ts},
        description="最后一条事件的状态",
    ))

    # 状态分布
    p.register(ProjectionSpec(
        key="status_breakdown",
        initial_state={"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0, "START": 0},
        fold=lambda s, e: {**s, e.status: s.get(e.status, 0) + 1},
        description="各状态的事件计数",
    ))

    # 错误分类
    p.register(ProjectionSpec(
        key="error_categories",
        initial_state={},
        fold=lambda s, e: (
            {**s, e.error[:50]: s.get(e.error[:50], 0) + 1}
            if e.status == "FAIL" and e.error else s
        ),
        description="失败错误消息的分类计数",
    ))

    return p
