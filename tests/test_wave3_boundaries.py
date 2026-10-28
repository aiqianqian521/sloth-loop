"""Standalone boundary regressions for the Wave 3 extractions."""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
sys.path.insert(0, str(ENGINE))

from cli_router import CliDependencies, CliRouter  # noqa: E402
from l2_analyzer import L2Analyzer, L2Config  # noqa: E402
from run_reporter import RunReporter  # noqa: E402


class _Logger:
    def warning(self, *_args):
        pass


class _Lock:
    def __init__(self, _path):
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.exited = True


class _BadLock(_Lock):
    def __enter__(self):
        raise RuntimeError("locked")


class _TrackingLock(_Lock):
    last = None

    def __init__(self, path):
        super().__init__(path)
        type(self).last = self


def _router(lock_cls, tee_cls=lambda stream, _path: stream):
    return CliRouter(CliDependencies(
        build_orchestrator=lambda _config: None,
        inspection_service=lambda _wd: SimpleNamespace(
            inspect_handler=lambda *_: None, trace_handler=lambda *_: None),
        show_history=lambda *_: None,
        run_lock_cls=lock_cls, tee_cls=tee_cls,
        logger=_Logger()))


class _L2Store:
    def __init__(self):
        self.analyses = [{"health_score": 10}]

    def get_queue_stats(self):
        return {"total": 1, "by_status": {}, "by_type": {}}

    def get_rounds(self):
        return []

    def get_last_l2_analysis(self):
        return self.analyses[-1]

    def pull_problems(self, **_kwargs):
        return []

    def insert_l2_analysis(self, value):
        self.analyses.append(value)


class _ReporterStore:
    def get_rounds(self):
        return [{"input_count": 2, "excluded_count": 2, "new_failures": 0,
                 "new_successes": 0} for _ in range(3)]

    def get_queue_stats(self):
        return {"total": 1, "by_status": {"queued": 1},
                "by_type": {"execution_error": 1}}

    def get_active_exclusion_rules(self):
        return [{}] * 6


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="loop-cli-boundary-") as td:
        runtime = SimpleNamespace(root=Path(td), logs_dir=Path(td))
        ok_orch = SimpleNamespace(runtime=runtime, run=lambda _signals: None)
        assert _router(_Lock)._run_continuous(ok_orch, SimpleNamespace(signals=None)) == 0
        assert _router(_BadLock)._run_continuous(ok_orch, SimpleNamespace(signals=None)) == 2

        def fail_run(_signals):
            raise RuntimeError("engine failure")
        failed_orch = SimpleNamespace(runtime=runtime, run=fail_run)
        try:
            _router(_Lock)._run_continuous(failed_orch, SimpleNamespace(signals=None))
            raise AssertionError("engine RuntimeError must not be reported as lock conflict")
        except RuntimeError as exc:
            assert str(exc) == "engine failure"

        calls = 0
        created = []
        class ClosableTee:
            def __init__(self, stream):
                self.stream = stream
                self.closed = False
            def close(self):
                self.closed = True
        def broken_tee(stream, _path):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("tee failure")
            wrapper = ClosableTee(stream)
            created.append(wrapper)
            return wrapper
        try:
            _router(_TrackingLock, broken_tee)._run_continuous(
                ok_orch, SimpleNamespace(signals=None))
            raise AssertionError("tee failure must propagate")
        except OSError:
            pass
        assert _TrackingLock.last.exited
        assert created[0].closed

    store = _L2Store()
    analysis = L2Analyzer(store, L2Config()).health_check({
        "recent_new_patterns": 0, "queue_total": 1, "queue_recurring": 1}, "anomaly_signal")
    assert analysis["stop_signal"] == "suggest_terminate"

    output = io.StringIO()
    reporter = RunReporter(_ReporterStore(), SimpleNamespace())
    with contextlib.redirect_stdout(output):
        reporter.diagnose_stop("no progress", 3)
    rendered = output.getvalue()
    assert "High exclusion rate" in rendered
    assert "Zero new patterns" in rendered
    assert "Execution errors present" in rendered
    assert "Many exclusion rules active" in rendered

    print("PASS RunReporter/L2Analyzer/CliRouter boundary regressions")


def test_contract():
    """Pytest entry (cycle-16 A): keep these assertions inside the gate.

    This file used to be a manual script (``python tests/<file>``): pytest
    collected zero tests from it, so its assertions were never enforced by
    ``run_gate.py``.  The body is unchanged -- this wrapper only makes the very
    same checks run under pytest.
    """
    main()


if __name__ == "__main__":
    main()
