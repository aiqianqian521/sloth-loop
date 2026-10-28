"""Step 级任务追踪 — P1-N2: TodoWrite 模式。

对标 Claude Code TodoWrite: 每个步骤有 id/content/status/priority,
失败恢复粒度从整轮 → 子步骤。

设计:
  TaskTracker 实例绑定到一次 Run（一轮 OODA 循环）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ============================================================================
# 任务状态枚举
# ============================================================================

class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"          # 标记为需要重试


class TaskPriority(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ============================================================================
# TaskItem
# ============================================================================

@dataclass
class TaskItem:
    """单个子步骤任务。"""
    id: str
    content: str                    # 人类可读描述
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    parent_id: str | None = None    # 父任务 id（支持树形结构）
    notes: list[str] = field(default_factory=list)  # 执行过程中的备注
    retry_count: int = 0            # 重试次数
    max_retries: int = 3            # 最大重试次数
    tool_calls: list[str] = field(default_factory=list)  # 关联的工具调用 seq

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status.value,
            "priority": self.priority.value,
            "parent_id": self.parent_id,
            "notes": self.notes,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "tool_calls": self.tool_calls,
        }


# ============================================================================
# TaskTracker
# ============================================================================

class TaskTracker:
    """步骤级任务追踪器。

    使用方式:
        tracker = TaskTracker("demo-backtest-loop", round_num=3)
        tracker.add_task("T1", "Observe signals", priority=TaskPriority.HIGH)
        tracker.start_step("T1")
        # ... 执行工具调用 ...
        tracker.record_tool("T1", "bash:123")
        tracker.complete_step("T1", status=TaskStatus.COMPLETED)
        failed = tracker.find_failed()  # 返回需要重试的任务
    """

    def __init__(self, task_name: str, round_num: int = 0):
        self.task_name = task_name
        self.round_num = round_num
        self._tasks: list[TaskItem] = []
        self._task_index: dict[str, TaskItem] = {}  # id → item

    # ── 任务管理 ───────────────────────────────

    def add_task(self, task_id: str, content: str,
                 priority: TaskPriority = TaskPriority.MEDIUM,
                 parent_id: str | None = None,
                 max_retries: int = 3) -> TaskItem:
        """添加子步骤任务。"""
        if task_id in self._task_index:
            raise ValueError(f"Task {task_id} already exists")
        item = TaskItem(
            id=task_id, content=content, priority=priority,
            parent_id=parent_id, max_retries=max_retries,
        )
        self._tasks.append(item)
        self._task_index[task_id] = item
        return item

    def add_tasks(self, tasks: list[tuple[str, str, TaskPriority]]) -> list[TaskItem]:
        """批量添加任务。每项: (id, content, priority)。"""
        items = []
        for tid, content, priority in tasks:
            items.append(self.add_task(tid, content, priority))
        return items

    def start_step(self, task_id: str) -> None:
        """标记任务为进行中。"""
        task = self._task_index.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        task.status = TaskStatus.IN_PROGRESS

    def complete_step(self, task_id: str, status: TaskStatus = TaskStatus.COMPLETED,
                      note: str = "") -> None:
        """标记任务完成/失败。"""
        task = self._task_index.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        task.status = status
        if note:
            task.notes.append(note)
        if status == TaskStatus.FAILED:
            task.retry_count += 1
            if task.retry_count < task.max_retries:
                task.status = TaskStatus.RETRY

    def record_tool(self, task_id: str, tool_call_seq: str) -> None:
        """记录当前步骤关联的工具调用。"""
        task = self._task_index.get(task_id)
        if task is not None:
            task.tool_calls.append(tool_call_seq)

    def add_note(self, task_id: str, note: str) -> None:
        """添加备注。"""
        task = self._task_index.get(task_id)
        if task is not None:
            task.notes.append(note)

    # ── 查询 ───────────────────────────────────

    def find_failed(self) -> list[TaskItem]:
        """查找所有失败/需重试的任务。"""
        return [t for t in self._tasks
                if t.status in (TaskStatus.FAILED, TaskStatus.RETRY)]

    def find_pending(self) -> list[TaskItem]:
        """查找所有待处理任务。"""
        return [t for t in self._tasks if t.status == TaskStatus.PENDING]

    def find_in_progress(self) -> list[TaskItem]:
        """查找所有进行中任务。"""
        return [t for t in self._tasks if t.status == TaskStatus.IN_PROGRESS]

    def find_by_parent(self, parent_id: str) -> list[TaskItem]:
        """按父任务查找子任务。"""
        return [t for t in self._tasks if t.parent_id == parent_id]

    def get_failed_substep(self) -> TaskItem | None:
        """获取第一个需要重试的失败子步骤（用于恢复）。"""
        failed = self.find_failed()
        return failed[0] if failed else None

    # ── 统计 ───────────────────────────────────

    @property
    def all_tasks(self) -> list[TaskItem]:
        return list(self._tasks)

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    def progress(self) -> dict:
        """任务进度摘要。"""
        total = len(self._tasks)
        if total == 0:
            return {"total": 0, "completed": 0, "failed": 0, "pending": 0,
                    "in_progress": 0, "retry": 0, "progress_pct": 0}

        completed = sum(1 for t in self._tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks if t.status == TaskStatus.FAILED)
        pending = sum(1 for t in self._tasks if t.status == TaskStatus.PENDING)
        in_progress = sum(1 for t in self._tasks if t.status == TaskStatus.IN_PROGRESS)
        retry = sum(1 for t in self._tasks if t.status == TaskStatus.RETRY)

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "in_progress": in_progress,
            "retry": retry,
            "progress_pct": round(completed / total * 100, 1),
        }

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "task_name": self.task_name,
            "round": self.round_num,
            "tasks": [t.to_dict() for t in self._tasks],
            "progress": self.progress(),
        }

    def summary(self) -> str:
        """人类可读的进度摘要。"""
        p = self.progress()
        return (f"[{self.task_name}] round={self.round_num} "
                f"{p['completed']}/{p['total']} ({p['progress_pct']}%) "
                f"failed={p['failed']} retry={p['retry']} pending={p['pending']}")
