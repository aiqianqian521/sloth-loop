"""测试 step 级任务追踪 — P1-N2: TodoWrite 模式。"""

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from task_tracker import (
    TaskTracker, TaskItem, TaskStatus, TaskPriority,
)


# ── 基本操作 ──

def test_add_and_retrieve():
    """添加任务 → 查找。"""
    tracker = TaskTracker("test", round_num=1)
    tracker.add_task("T1", "Observe signals", priority=TaskPriority.HIGH)
    t = tracker.all_tasks[0]
    assert t.id == "T1"
    assert t.content == "Observe signals"
    assert t.priority == TaskPriority.HIGH


def test_add_duplicate_raises():
    """重复 id 抛异常。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "task 1")
    try:
        tracker.add_task("T1", "task 1 dup")
        assert False, "Should raise ValueError"
    except ValueError:
        pass


# ── 状态流转 ──

def test_start_complete_step():
    """开始 → 完成。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "do something")
    tracker.start_step("T1")
    assert tracker.all_tasks[0].status == TaskStatus.IN_PROGRESS
    tracker.complete_step("T1")
    assert tracker.all_tasks[0].status == TaskStatus.COMPLETED


def test_fail_and_retry():
    """失败 → RETRY (未超最大重试)。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "risky", max_retries=3)
    tracker.complete_step("T1", status=TaskStatus.FAILED)
    t = tracker.all_tasks[0]
    assert t.status == TaskStatus.RETRY
    assert t.retry_count == 1

    # 再次失败
    tracker.start_step("T1")
    tracker.complete_step("T1", status=TaskStatus.FAILED)
    assert t.retry_count == 2
    assert t.status == TaskStatus.RETRY

    # 第三次失败 → 最终 FAILED
    tracker.start_step("T1")
    tracker.complete_step("T1", status=TaskStatus.FAILED)
    assert t.retry_count == 3
    assert t.status == TaskStatus.FAILED


def test_fail_no_retry():
    """max_retries=1 → 直接 FAILED。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "no retry", max_retries=1)
    tracker.complete_step("T1", status=TaskStatus.FAILED)
    assert tracker.all_tasks[0].status == TaskStatus.FAILED


# ── 查询 ──

def test_find_failed():
    """查找失败/需重试任务。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "pass")
    tracker.add_task("T2", "fail", max_retries=1)
    tracker.add_task("T3", "retry", max_retries=3)
    tracker.complete_step("T1")
    tracker.complete_step("T2", status=TaskStatus.FAILED)
    tracker.complete_step("T3", status=TaskStatus.FAILED)

    failed = tracker.find_failed()
    assert len(failed) == 2  # T2 (FAILED) + T3 (RETRY)
    retry = [t for t in tracker.all_tasks if t.status == TaskStatus.RETRY]
    assert len(retry) == 1
    assert retry[0].id == "T3"


def test_find_pending():
    """待处理任务。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "done")
    tracker.add_task("T2", "waiting")
    tracker.complete_step("T1")
    pending = tracker.find_pending()
    assert len(pending) == 1
    assert pending[0].id == "T2"


def test_get_failed_substep():
    """获取第一个需重试的失败子步骤。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "fail", max_retries=3)
    tracker.complete_step("T1", status=TaskStatus.FAILED)
    item = tracker.get_failed_substep()
    assert item is not None
    assert item.id == "T1"
    assert item.status == TaskStatus.RETRY


# ── 工具调用关联 ──

def test_record_tool():
    """记录工具调用。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "task")
    tracker.record_tool("T1", "bash:001")
    tracker.record_tool("T1", "write:002")
    assert tracker.all_tasks[0].tool_calls == ["bash:001", "write:002"]


# ── 备注 ──

def test_add_note():
    """添加备注。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "task")
    tracker.add_note("T1", "first attempt")
    tracker.add_note("T1", "retry with different params")
    assert tracker.all_tasks[0].notes == ["first attempt", "retry with different params"]


# ── 父任务层级 ──

def test_parent_child():
    """父子任务关系。"""
    tracker = TaskTracker("test")
    tracker.add_task("T1", "parent")
    tracker.add_task("T1.1", "child", parent_id="T1")
    tracker.add_task("T1.2", "child2", parent_id="T1")
    children = tracker.find_by_parent("T1")
    assert len(children) == 2
    assert {c.id for c in children} == {"T1.1", "T1.2"}


# ── 进度 ──

def test_progress():
    """进度计算。"""
    tracker = TaskTracker("test", round_num=2)
    tracker.add_task("T1", "a")
    tracker.add_task("T2", "b")
    tracker.add_task("T3", "c")
    tracker.add_task("T4", "d")
    tracker.complete_step("T1")
    tracker.complete_step("T2")
    p = tracker.progress()
    assert p["total"] == 4
    assert p["completed"] == 2
    assert p["progress_pct"] == 50.0
    assert p["pending"] == 2


def test_empty_progress():
    """空任务列表进度。"""
    tracker = TaskTracker("test")
    p = tracker.progress()
    assert p["total"] == 0
    assert p["progress_pct"] == 0


# ── 序列化 ──

def test_to_dict():
    """序列化为字典。"""
    tracker = TaskTracker("test", round_num=1)
    tracker.add_task("T1", "task1")
    tracker.add_task("T2", "task2")
    tracker.complete_step("T1")
    d = tracker.to_dict()
    assert d["task_name"] == "test"
    assert d["round"] == 1
    assert len(d["tasks"]) == 2
    assert d["progress"]["completed"] == 1


# ── 摘要 ──

def test_summary():
    """人类可读摘要。"""
    tracker = TaskTracker("demo-loop", round_num=3)
    tracker.add_task("T1", "a")
    tracker.add_task("T2", "b")
    tracker.complete_step("T1")
    s = tracker.summary()
    assert "demo-loop" in s
    assert "round=3" in s
    assert "1/2" in s


# ── 批量添加 ──

def test_add_tasks_batch():
    """批量添加。"""
    tracker = TaskTracker("test")
    items = tracker.add_tasks([
        ("a", "first", TaskPriority.HIGH),
        ("b", "second", TaskPriority.LOW),
    ])
    assert len(items) == 2
    assert tracker.task_count == 2

