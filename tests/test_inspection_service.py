"""W2-BOUNDARY-01 / H2 Slice 1-PATH (Z-beta): InspectionService is per-instance and the orchestrator module singleton is removed.

Standalone: `python tests/test_inspection_service.py`. Pytest collects the test_* functions.
"""
from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from event_log import EventLog  # noqa: E402
from inspection_service import InspectionService  # noqa: E402
import orchestrator  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"FAIL {label}: {detail}")
    print(f"PASS {label}")


def _make_tree(work_dir: Path, runs_date: str, task_name: str, n_events: int) -> None:
    runs = work_dir / f"runs-{runs_date}"
    runs.mkdir(parents=True, exist_ok=True)
    elog = EventLog(runs / f"events-{runs_date}-120000.jsonl", task_name=task_name)
    for i in range(n_events):
        elog.append("act/result", {"round": 1, "status": "PASS",
                                   "message": f"{task_name}-{i}", "elapsed_ms": 1.0})


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs: list[str] = []

    def emit(self, record) -> None:
        self.msgs.append(record.getMessage())


def test_inspection_service_per_instance_isolation() -> None:
    td = Path(tempfile.mkdtemp(prefix="zbeta-isolation-"))
    try:
        treeA = td / "A"
        treeB = td / "B"
        _make_tree(treeA, "2026-08-29", "taskA", 2)
        _make_tree(treeB, "2026-08-28", "taskB", 3)

        cap = _Cap()
        log = logging.getLogger("zbeta-isolation")
        log.addHandler(cap)
        log.setLevel(logging.INFO)
        svcA = InspectionService(treeA, logger=log)
        svcB = InspectionService(treeB, logger=log)

        # find_latest_log is scoped to the instance's work_dir, never the other tree.
        la = svcA.find_latest_log()
        lb = svcB.find_latest_log()
        check("svcA finds log under A", la is not None and la.is_relative_to(treeA), str(la))
        check("svcB finds log under B", lb is not None and lb.is_relative_to(treeB), str(lb))
        check("svcA log not under B", la is not None and not la.is_relative_to(treeB))
        check("svcB log not under A", lb is not None and not lb.is_relative_to(treeA))

        # inspect_timeline surfaces the per-tree task name only -> shows isolation at
        # the output layer too (the old module global would have returned the LAST set
        # work_dir for both calls).
        cap.msgs.clear(); svcA.inspect_timeline(); a_msgs = list(cap.msgs)
        cap.msgs.clear(); svcB.inspect_timeline(); b_msgs = list(cap.msgs)
        log.removeHandler(cap)
        check("A timeline mentions taskA only",
              any("taskA" in m for m in a_msgs) and not any("taskB" in m for m in a_msgs),
              str(a_msgs))
        check("B timeline mentions taskB only",
              any("taskB" in m for m in b_msgs) and not any("taskA" in m for m in b_msgs),
              str(b_msgs))

        # interleaved calls stay isolated (no shared global mutation).
        cap2 = _Cap(); log.addHandler(cap2)
        cap2.msgs.clear(); svcA.inspect_runs()
        a_after = list(cap2.msgs)
        cap2.msgs.clear(); svcB.inspect_runs()
        b_after = list(cap2.msgs)
        log.removeHandler(cap2)
        check("interleaved A sees A events", any("2026-08-29" in m for m in a_after))
        check("interleaved B sees B events", any("2026-08-28" in m for m in b_after))

        # methods exist (byte-equivalent surface).
        for m in ("inspect_handler", "inspect_runs", "inspect_round",
                  "inspect_timeline", "inspect_last_error", "trace_handler",
                  "find_latest_log"):
            check(f"InspectionService has {m}", hasattr(InspectionService, m))
        # inspect_handler dispatch reaches inspect_runs.
        cap3 = _Cap(); log.addHandler(cap3)
        svcA.inspect_handler("runs", None)
        out = list(cap3.msgs); log.removeHandler(cap3)
        check("inspect_handler dispatches runs", len(out) > 0)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_singleton_removed_from_orchestrator() -> None:
    check("no _ACTIVE_INSPECT_WORK_DIR on module",
          not hasattr(orchestrator, "_ACTIVE_INSPECT_WORK_DIR"))
    check("no _set_active_inspect_work_dir free function",
          not hasattr(orchestrator, "_set_active_inspect_work_dir"))
    check("no _inspect_runs free function",
          not hasattr(orchestrator, "_inspect_runs"))


def main() -> None:
    test_inspection_service_per_instance_isolation()
    test_singleton_removed_from_orchestrator()
    print("test_inspection_service: all PASS")


if __name__ == "__main__":
    main()
