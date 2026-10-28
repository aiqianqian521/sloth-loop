"""W2-BOUNDARY-01 / H2 Slice 2-SHELL: ExecGate sanctioned-spawn contracts.

ExecGate is the de-shell + interpreter-allow-list + resource-axis chokepoint
centralised so new sinks are safe-by-construction (swarm 4-lens verdict B).
These contracts pin the folded hard constraints:

- de-shell by construction: shell is ALWAYS False on every Popen path
  (str -> shlex.split), closing shell-injection (critical-2).
- interpreter allow-list: assert_interpreter resolves argv[0] (bare name ->
  shutil.which) and denies-by-default -> ContainmentError BEFORE any spawn
  (proof: a denied interpreter records zero Popen calls). kind="interpreter".
- resource axis: deterministic stored-slice output cap; timeout -> timed_out.
- purity: ExecGate holds a runtime ref but does no I/O; audit flows through
  runtime.on_violation; the guard return never enters checkpoints/settings.
- fail-closed: a denied interpreter raises ContainmentError; callers catch it
  (see test_runtime_containment.test_backtest_sink_deny_spawn_via_gate) and
  convert to a fail-closed result, never letting it raise into run().

Standalone: `python tests/test_runtime_exec.py`. Pytest collects test_*.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from runtime_exec import ExecGate, ExecResult, DEFAULT_OUT_CAP  # noqa: E402
from runtime_paths import RuntimePaths, ContainmentError  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"FAIL {label}: {detail}")


def _gate(td: Path, *, allow=None, out_cap_bytes=DEFAULT_OUT_CAP):
    audits: list[dict] = []

    def on_v(payload):
        audits.append(payload)

    rp = RuntimePaths.from_config(
        {"runtime": {"root": str(td), "db": "db/patterns.db"}},
        ROOT, ENGINE, allowed_interpreters=allow, on_violation=on_v).ensure()
    gate = ExecGate(rp, out_cap_bytes=out_cap_bytes)
    return gate, audits


class _FakeProc:
    """Minimal Popen stand-in: communicate() returns canned text."""

    def __init__(self, out: str = "", err: str = "", code: int = 0):
        self.returncode = code
        self._out = out
        self._err = err

    def communicate(self, input=None, timeout=None):
        return (self._out, self._err)

    def kill(self):
        self.returncode = -9


def test_to_argv_de_shell_str_and_list() -> None:
    check("str -> shlex split",
          ExecGate._to_argv('a b "c d"') == ["a", "b", "c d"])
    check("list -> str-cast passthrough",
          ExecGate._to_argv(["x", 1, Path("y")]) == ["x", "1", "y"])


def test_run_allow_and_exec() -> None:
    td = Path(tempfile.mkdtemp(prefix="execgate-allow-"))
    try:
        gate, _ = _gate(td)
        r = gate.run([sys.executable, "-c", "print(11)"], assert_interpreter=True)
        check("allow interpreter: returncode 0", r.returncode == 0, repr(r))
        check("allow interpreter: stdout captured", "11" in r.stdout, r.stdout)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_deny_no_spawn() -> None:
    td = Path(tempfile.mkdtemp(prefix="execgate-deny-"))
    try:
        gate, audits = _gate(
            td, allow=frozenset({Path("C:/nope/python.exe").resolve()}))
        spawned: list = []

        def recorder(*a, **k):
            spawned.append(a)
            return _FakeProc()

        raised = False
        with mock.patch.object(subprocess, "Popen", recorder):
            try:
                gate.run([sys.executable, "-c", "print(1)"], assert_interpreter=True)
            except ContainmentError:
                raised = True
        check("denied interpreter raises ContainmentError", raised)
        check("denied interpreter spawns ZERO subprocess", len(spawned) == 0,
              f"spawned={spawned}")
        check("denied interpreter audited via on_violation",
              any(a.get("kind") == "interpreter" and a.get("result") == "denied"
                  for a in audits), str(audits))
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_str_command_de_shell_shell_always_false() -> None:
    td = Path(tempfile.mkdtemp(prefix="execgate-deshell-"))
    try:
        gate, _ = _gate(td)
        seen: dict = {}

        def recorder(*a, **k):
            seen["argv"] = a[0] if a else None
            seen["shell"] = k.get("shell")
            return _FakeProc(out="3\n")

        exe = Path(sys.executable).as_posix()
        cmd = f'"{exe}" -c "print(3)"'
        with mock.patch.object(subprocess, "Popen", recorder):
            r = gate.run(cmd, assert_interpreter=False)
        check("str command shlex-split to argv list",
              isinstance(seen["argv"], list), str(seen.get("argv")))
        check("str command NEVER passes shell=True", seen["shell"] is False,
              f"shell={seen.get('shell')!r}")
        check("de-shelled result still returns captured stdout", "3" in r.stdout,
              r.stdout)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_output_cap_deterministic_truncation() -> None:
    td = Path(tempfile.mkdtemp(prefix="execgate-cap-"))
    try:
        gate, _ = _gate(td, out_cap_bytes=40)
        r = gate.run(
            [sys.executable, "-c", "import sys; sys.stdout.write('z' * 100000)"],
            assert_interpreter=False)
        check("output above cap flagged truncated", r.truncated is True, repr(r))
        check("stored stdout sliced to <= cap", len(r.stdout) <= 40,
              f"len={len(r.stdout)}")
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_popen_allow_and_pipes() -> None:
    td = Path(tempfile.mkdtemp(prefix="execgate-popen-"))
    try:
        gate, _ = _gate(td)
        proc = gate.popen(
            [sys.executable, "-c", "import sys; sys.stdout.write('p')"])
        out, _err = proc.communicate()
        check("popen allow-listed interpreter writes to stdout", "p" in out, out)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_never_shell_true_on_run_and_popen() -> None:
    td = Path(tempfile.mkdtemp(prefix="execgate-noshell-"))
    try:
        gate, _ = _gate(td)
        shells: list = []

        def recorder(*a, **k):
            shells.append(k.get("shell"))
            return _FakeProc()

        with mock.patch.object(subprocess, "Popen", recorder):
            gate.run([sys.executable, "-c", "print(1)"], assert_interpreter=True)
            gate.popen([sys.executable, "-c", "print(2)"])
        check("run path shell is False", len(shells) >= 1 and shells[0] is False,
              str(shells))
        check("popen path shell is False", len(shells) >= 2 and shells[1] is False,
              str(shells))
        check("no Popen path ever passes shell=True",
              all(s is False for s in shells), str(shells))
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_timeout_flags_timed_out() -> None:
    td = Path(tempfile.mkdtemp(prefix="execgate-timeout-"))
    try:
        gate, _ = _gate(td)
        r = gate.run([sys.executable, "-c", "import time; time.sleep(5)"],
                     timeout=1, assert_interpreter=False)
        check("timeout raises timed_out flag", r.timed_out is True, repr(r))
    finally:
        shutil.rmtree(td, ignore_errors=True)


def main() -> None:
    test_to_argv_de_shell_str_and_list()
    test_run_allow_and_exec()
    test_deny_no_spawn()
    test_str_command_de_shell_shell_always_false()
    test_output_cap_deterministic_truncation()
    test_popen_allow_and_pipes()
    test_never_shell_true_on_run_and_popen()
    test_timeout_flags_timed_out()
    print("test_runtime_exec: all PASS")


if __name__ == "__main__":
    main()
