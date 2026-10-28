"""W2-BOUNDARY-01 / H2 Slice 1-PATH: runtime path containment contracts.

RuntimePaths.assert_under / assert_under_root / assert_interpreter are
deny-by-default; orchestrator exec sinks (callback, regression) reject an
escaping path or a non-allow-listed interpreter and do NOT spawn a subprocess.
run-id components are flattened to kill path-traversal writes, and the
Z-beta module-global singleton (_ACTIVE_INSPECT_WORK_DIR) is gone.

Exec/playbook paths are contained to the repo (PROJECT_ROOT); runtime
artifacts (db/io/events/logs) to the runtime sandbox root.

Standalone: `python tests/test_runtime_containment.py`. Pytest collects test_*.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
if str(ENGINE / "_archive") not in sys.path:
    sys.path.insert(0, str(ENGINE / "_archive"))  # archived legacy modules

import subprocess  # noqa: E402
import orchestrator  # noqa: E402
from orchestrator import OODASteps, ContainmentError  # noqa: E402
from runtime_paths import RuntimePaths  # noqa: E402
from inspection_service import InspectionService  # noqa: E402
from cli_router import CliDependencies  # noqa: E402

from runtime_exec import ExecGate  # noqa: E402
from adapters.backtest_adapter import BacktestInput, run_backtest  # noqa: E402
import structured_cli  # noqa: E402

PROJECT_ROOT = orchestrator.PROJECT_ROOT  # sloth-loop repo root, the exec-script boundary


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"FAIL {label}: {detail}")
    print(f"PASS {label}")


def _runtime(td: Path, *, allow=None):
    audits: list[dict] = []

    def on_v(payload):
        audits.append(payload)
    rp = RuntimePaths.from_config(
        {"runtime": {"root": str(td), "db": "db/patterns.db"}},
        ROOT, ENGINE, allowed_interpreters=allow, on_violation=on_v).ensure()
    return rp, audits


def test_assert_under_and_root_and_interpreter() -> None:
    td = Path(tempfile.mkdtemp(prefix="contain-rp-"))
    try:
        rp, audits = _runtime(td)
        check("in-root under runtime.root",
              rp.assert_under_root(td / "inside.txt") == (td / "inside.txt").resolve())
        sib = td.parent / "sibling_escape.txt"
        try:
            rp.assert_under_root(sib)
            check("escape root raises", False)
        except ContainmentError as e:
            check("escape root captured", e.kind == "path")
        check("escape root audited", bool(audits) and audits[-1].get("result") == "denied")
        audits.clear()

        repo_file = ROOT / "README.md"
        if not repo_file.exists():
            repo_file = ENGINE / "runtime_paths.py"
        check("repo asset under PROJECT_ROOT",
              rp.assert_under(repo_file, PROJECT_ROOT, kind="repo") == repo_file.resolve())
        try:
            rp.assert_under(td / "x.txt", PROJECT_ROOT, kind="tmp-escape")
            check("tmp escape PROJECT_ROOT raises", False)
        except ContainmentError:
            check("tmp escape PROJECT_ROOT raised", True)

        check("default interpreter allowed",
              rp.assert_interpreter(sys.executable) == Path(sys.executable).resolve())
        rp_bad, audits2 = _runtime(td, allow=frozenset({Path("C:/nope/python.exe").resolve()}))
        try:
            rp_bad.assert_interpreter(sys.executable, kind="bad-interpreter")
            check("non-allowed interpreter raises", False)
        except ContainmentError:
            check("non-allowed interpreter denied", True)
            check("non-allowed interpreter audited",
                  bool(audits2) and audits2[-1].get("result") == "denied")
    finally:
        shutil.rmtree(td, ignore_errors=True)


class _RecordingGate:
    """A gate stand-in that records every spawn request (cycle-36 A)."""

    def __init__(self):
        self.calls: list = []

    def run(self, *a, **k):
        self.calls.append((a, k))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="", timed_out=False)


def test_callback_sink_deny_spawn() -> None:
    td = Path(tempfile.mkdtemp(prefix="contain-cb-"))
    try:
        rp, _ = _runtime(td)
        gate = _RecordingGate()

        repo_script = str(ENGINE / "runtime_paths.py")
        ok, detail = OODASteps._run_callback(repo_script, {"trades": []},
                                             runtime=rp, exec_gate=gate)
        check("in-root callback routes through the gate",
              ok is True and len(gate.calls) == 1, detail)

        ok2, detail2 = OODASteps._run_callback(str(td / "evil.py"), {"trades": []},
                                               runtime=rp, exec_gate=gate)
        check("escape callback denied", ok2 is False and "denied" in detail2.lower(), detail2)
        check("escape callback not spawned", len(gate.calls) == 1)

        rp_bad, _ = _runtime(td, allow=frozenset({Path("C:/nope/python.exe").resolve()}))
        ok3, detail3 = OODASteps._run_callback(repo_script, {"trades": []},
                                               runtime=rp_bad, exec_gate=gate)
        check("non-allowed interpreter callback denied",
              ok3 is False and "denied" in detail3.lower(), detail3)
        check("non-allowed interpreter callback not spawned", len(gate.calls) == 1)

        # cycle-36 A: no gate at all -> refuse to spawn (fail-closed).
        ok4, detail4 = OODASteps._run_callback(repo_script, {"trades": []}, runtime=None)
        check("callback without a gate is fail-closed",
              ok4 is False and "gate" in detail4.lower(), detail4)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_regression_sink_deny_spawn() -> None:
    td = Path(tempfile.mkdtemp(prefix="contain-rg-"))
    try:
        rp, _ = _runtime(td)
        gate = _RecordingGate()

        res = OODASteps._verify_regression({"tests": [str(td / "escape_test.py")]},
                                           bar=None, runtime=rp, exec_gate=gate)
        check("regression escape counted as fail",
              res["fail_count"] == 1 and res["pass_count"] == 0)
        check("regression escape not spawned", len(gate.calls) == 0)
        check("regression escape detail denied",
              "denied" in res["details"][0]["detail"].lower())

        res2 = OODASteps._verify_regression({"tests": [str(ENGINE / "runtime_paths.py")]},
                                            bar=None, runtime=rp, exec_gate=gate)
        check("regression in-root routes through the gate", len(gate.calls) == 1)
        check("regression in-root passes", res2["pass_count"] == 1)

        # cycle-36 A: no gate at all -> refuse to spawn (fail-closed).
        res3 = OODASteps._verify_regression({"tests": [str(ENGINE / "runtime_paths.py")]},
                                            bar=None, runtime=None)
        check("regression without a gate is fail-closed",
              res3["fail_count"] == 1 and "gate" in res3["details"][0]["detail"].lower())
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_safe_run_component() -> None:
    f = orchestrator.Orchestrator._safe_run_component
    cases = {"../../evil": "evil", "../x": "x", "loop.v2": "loop.v2",
             "/etc/passwd": "etc_passwd", None: "loop", "": "loop",
             "a" + chr(0) + "b": "a_b"}
    for inp, want in cases.items():
        got = f(inp)
        check(f"sanitize {inp!r} -> {want!r}", got == want, f"got {got!r}")
        check(f"sanitize {inp!r} no traversal",
              "/" not in got and "\\" not in got and ".." not in got)


def test_module_state() -> None:
    check("orchestrator singleton removed",
          not hasattr(orchestrator, "_ACTIVE_INSPECT_WORK_DIR"))
    check("orchestrator _set_active_inspect_work_dir removed",
          not hasattr(orchestrator, "_set_active_inspect_work_dir"))
    check("orchestrator _inspect_runs free func removed",
          not hasattr(orchestrator, "_inspect_runs"))
    check("ContainmentError importable from orchestrator",
          hasattr(orchestrator, "ContainmentError"))
    check("InspectionService importable", InspectionService is not None)
    fields = CliDependencies.__dataclass_fields__
    check("cli_router seam: inspection_service present",
          "inspection_service" in fields)
    check("cli_router seam: set_inspect_work_dir absent",
          "set_inspect_work_dir" not in fields)
    check("cli_router seam: inspect_handler dep absent",
          "inspect_handler" not in fields)


def test_backtest_sink_deny_spawn_via_gate() -> None:
    td = Path(tempfile.mkdtemp(prefix="contain-bt-shell-"))
    try:
        rp_deny, _ = _runtime(
            td, allow=frozenset({Path("C:/nope/python.exe").resolve()}))
        gate_deny = ExecGate(rp_deny)
        spawned: list = []

        def recorder(*a, **k):
            spawned.append(a)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        mock_script = str(ROOT / "backtest" / "mock_backtest.py")
        settings = {
            "script": mock_script,
            "input_path": str(td / "in.json"),
            "output_path": str(td / "out.json"),
            "python": sys.executable,
            "cwd": str(ROOT),
            "timeout_sec": 30,
        }
        with mock.patch.object(subprocess, "Popen", recorder):
            result = run_backtest(
                BacktestInput(
                    signals=[{"signal_pattern": "x", "market_condition": "y"}]),
                settings, exec_gate=gate_deny)
        check("backtest via gate: denied interpreter -> error status",
              result.status == "error", result.status)
        check("backtest via gate: denied -> interpreter_denied code",
              getattr(result, "error_code", None) == "interpreter_denied",
              str(getattr(result, "error_code", None)))
        check("backtest via gate: denied text in error",
              "\u62d2\u7edd" in (result.error or ""), result.error)
        check("backtest via gate: denied interpreter spawns ZERO",
              len(spawned) == 0, f"spawned={spawned}")
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_structured_cli_de_shell_invariant() -> None:
    seen: dict = {}

    def recorder(*a, **k):
        seen["cmd"] = a[0] if a else None
        seen["shell"] = k.get("shell")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    exe = Path(sys.executable).as_posix()
    cmd = f'"{exe}" -c "print(1)"'
    with mock.patch.object(subprocess, "run", recorder):
        structured_cli.run(cmd, timeout_sec=10)
    check("structured_cli shlex-splits str command to argv list",
          isinstance(seen["cmd"], list), str(seen.get("cmd")))
    check("structured_cli NEVER passes shell=True", seen["shell"] is False,
          f"shell={seen.get('shell')!r}")


def main() -> None:
    test_assert_under_and_root_and_interpreter()
    test_callback_sink_deny_spawn()
    test_regression_sink_deny_spawn()
    test_safe_run_component()
    test_module_state()
    test_backtest_sink_deny_spawn_via_gate()
    test_structured_cli_de_shell_invariant()
    print("test_runtime_containment: all PASS")


if __name__ == "__main__":
    main()
