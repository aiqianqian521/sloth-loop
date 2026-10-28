"""runtime_exec.ExecGate —— the sanctioned spawn chokepoint (Slice 2-SHELL).

H2-C de-shell + interpreter allow-list + H2-B resource axis, centralised so new
sinks are safe-by-construction instead of relying on caller discipline. The Slice
1-PATH verify-doc sink inventory was demonstrably non-exhaustive (it missed
known orchestration call sites), so guard-at-known-call-sites was
red-team否决d: a new caller is a new bypass. ExecGate is the chokepoint for
python-interpreter spawns (assert_interpreter); every shell sink is de-shelled by
construction (shell=False + shlex.split) regardless of the gate.

Swarm 4-lens folded hard constraints:
- de-shell by construction: shell is ALWAYS False; a str command is shlex.split ->
  closes shell-injection (critical-2).
- interpreter allow-list: when assert_interpreter is set, argv[0] is resolved
  (shutil.which for a bare name like "python") and runtime.assert_interpreter is
  invoked -> deny-by-default, on_violation audit, ContainmentError fail-closed.
  kind stays "interpreter" (data-lens #3: never mix shell/command kinds).
- resource axis: output stored-slice cap (deterministic for resume reproducibility,
  data-lens #4); timeout; start_new_session + close_fds; POSIX RLIMIT_NOFILE/RLIMIT_CPU
  via preexec_fn (Windows N/A -> documented best-effort). Network: env scrub only;
  true OS-level net sandbox deferred to P4.
- purity: ExecGate holds a runtime ref but does NO I/O; audit flows through
  runtime.on_violation (mirror Slice 1-PATH containment port). The guard return value
  is never persisted into checkpoints/settings (data-lens #1).
- fail-closed: a denied interpreter raises ContainmentError; callers catch it and
  convert to a fail-closed result, never letting it raise into run() (red-team).
- GuardianLayer (Phase 1-TaskB): layered security review on top of ExecGate.
  Guardian hook in run() performs permission-matrix lookup + risk-pattern scan +
  operation-chain analysis BEFORE any spawn. Deny/escalate raises ContainmentError.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import resource as _resource
except ImportError:  # Windows
    _resource = None

from guardian.risk_assessor import RiskAssessor
from guardian.review_session import ReviewBudget, ReviewContext, ReviewDecision

DEFAULT_OUT_CAP = 1 << 20  # 1 MiB stored-slice ceiling for stdout/stderr
DEFAULT_FD_SOFT = 256      # RLIMIT_NOFILE soft ceiling (POSIX only)
DEFAULT_CPU_SOFT = 60      # RLIMIT_CPU soft ceiling seconds (POSIX only)


@dataclass
class ExecResult:
    """Structured result of ExecGate.run (subprocess.run-style, bounded)."""
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False
    elapsed_ms: float = 0.0


class ExecGate:
    """Sanctioned spawn chokepoint bound to a RuntimePaths (composition root).

    Phase 1 Task B: GuardianLight integration adds RiskAssessor + ReviewBudget
    as a layered security review before any spawn. The Guardian hook runs in
    run() and popen(), performing:
      1. Permission-matrix lookup (RiskLevel.AUTO/CONFIRM/REVIEW/BLOCK)
      2. High-risk command pattern scanning
      3. Operation-chain analysis
      4. Risk-score threshold decision (allow/deny/escalate)

    Denied or escalated commands raise ContainmentError before any subprocess
    is spawned (fail-closed).
    """

    def __init__(self, runtime, *, out_cap_bytes: int = DEFAULT_OUT_CAP,
                 fd_soft: int = DEFAULT_FD_SOFT, cpu_soft: int = DEFAULT_CPU_SOFT):
        self.runtime = runtime
        self.out_cap_bytes = out_cap_bytes
        self.fd_soft = fd_soft
        self.cpu_soft = cpu_soft
        # Phase 1 Task B: GuardianLight integration
        self.guardian = RiskAssessor()
        self._review_budget = ReviewBudget()
        self._session_id: str = getattr(runtime, 'session_id', 'unknown')
        self._operation_history: list[str] = []

    def reset_review_budget(self) -> None:
        """重置审查预算（每轮调用）。

        Guardian 的 ReviewBudget 是"单会话"上限；但 loop 是长时自主循环，
        每轮都会 spawn 回测子进程。若不重置，预算会在第 N 轮耗尽并对
        后续合法 spawn 一律 escalate/deny（表现为 ContainmentError:
        'guardian . escapes runtime root .'），导致熔断停机。
        设计：审查上限按"轮"计量（而非按整个会话），既保留限流语义，
        又不会阻断合法的长循环任务。同时清空操作链，避免跨轮累积风险。
        """
        from guardian.review_session import ReviewBudget as _RB
        self._review_budget = _RB()
        self._operation_history = []

    # ---- argv normalisation: de-shell by construction (shell is never True) ----
    @staticmethod
    def _to_argv(cmd) -> list[str]:
        if isinstance(cmd, str):
            return shlex.split(cmd)
        return [str(a) for a in cmd]

    @staticmethod
    def _is_bare_name(name: str) -> bool:
        # Bare interpreter name (literal "python") -> PATH-resolve so the allow-list
        # compares the real target (closes the known call-site gap).
        return name == Path(name).name and os.sep not in name and "/" not in name

    def _resolve_interpreter(self, exe0: str) -> Path:
        p = Path(exe0)
        if self._is_bare_name(exe0):
            which = shutil.which(exe0)
            if which:
                p = Path(which)
        return p.resolve()

    def _assert_interpreter(self, argv: list[str]) -> None:
        # runtime.assert_interpreter: deny-by-default -> on_violation audit -> raises
        # ContainmentError on deny (fail-closed). kind="interpreter" (data-lens #3).
        resolved = self._resolve_interpreter(argv[0])
        self.runtime.assert_interpreter(resolved, kind="interpreter")

    # ---- GuardianLight hook (Phase 1 Task B) ----
    def _guardian_check(self, cmd, *, tool_name: str = "shell_command") -> None:
        """GuardianLight 分层安全审查入口。

        在 run() / popen() 中所有 spawn 前调用。
        对高风险命令执行权限矩阵查询 + 模式扫描 + 操作链分析。
        拒绝或升级时抛出 ContainmentError（fail-closed）。

        Args:
            cmd:       命令（str 或 list）
            tool_name: 工具名称

        Raises:
            ContainmentError: 审查拒绝或需要升级时
        """
        from runtime_paths import ContainmentError

        # 构造命令参数字符串
        cmd_str = cmd if isinstance(cmd, str) else " ".join(str(a) for a in cmd)

        ctx = ReviewContext(
            session_id=self._session_id,
            tool_name=tool_name,
            tool_args={"command": cmd_str},
            operation_chain=list(self._operation_history),
        )

        decision = self.guardian.assess(ctx, self._review_budget)

        # 记录操作历史（无论结果如何）
        self._operation_history.append(f"{tool_name}:{cmd_str[:80]}")

        if decision.decision == "deny":
            raise ContainmentError(
                Path("."), Path("."), kind="guardian",
                detail=f"{decision.reason} (risk={decision.risk_score:.2f})",
            ) from Exception(f"Guardian denied: {decision.reason}")

        # O-2 (cycle-29 A): escalate short-circuits to deny here too -- there is
        # no review channel to hand the decision to yet (RiskAssessor.llm_review
        # is intentionally NotImplementedError).  Raising ContainmentError is
        # fail-closed *and* honest: the detail names the risk and the level that
        # was requested, so the log can never be mistaken for a silent allow.
        if decision.decision == "escalate":
            raise ContainmentError(
                Path("."), Path("."), kind="guardian",
                detail=f"{decision.reason} (risk={decision.risk_score:.2f})",
            ) from Exception(
                f"Guardian escalated (risk={decision.risk_score:.2f}): {decision.reason}"
            )

    # ---- resource axis (POSIX best-effort; Windows start_new_session/preexec off) ----
    def _posix_kwargs(self) -> dict:
        kw: dict = {"close_fds": True}
        if os.name == "posix":
            kw["start_new_session"] = True
            fd_soft = self.fd_soft
            cpu_soft = self.cpu_soft
            def _preexec():
                try:
                    _resource.setrlimit(_resource.RLIMIT_NOFILE, (fd_soft, fd_soft))
                except Exception:
                    pass
                try:
                    _resource.setrlimit(_resource.RLIMIT_CPU, (cpu_soft, cpu_soft))
                except Exception:
                    pass
            kw["preexec_fn"] = _preexec
        return kw

    def _scrub_env(self, env: dict | None) -> dict:
        base = dict(os.environ)
        if env:
            base.update(env)
        # Network: best-effort proxy scrub. True OS-level net sandbox is P4.
        for k in list(base):
            if k.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
                base.pop(k, None)
        return base

    # ---- sanctioned run (subprocess.run-style, bounded stored-slice) ----
    def run(self, cmd, *, cwd=None, env=None, timeout=300,
            out_cap_bytes=None, assert_interpreter=False, input=None,
            encoding="utf-8") -> ExecResult:
        argv = self._to_argv(cmd)
        if not argv:
            raise ValueError("ExecGate.run: empty command")
        # Phase 1 Task B: GuardianLight hook BEFORE any spawn
        self._guardian_check(cmd, tool_name="shell_command")
        if assert_interpreter:
            self._assert_interpreter(argv)  # may raise ContainmentError (fail-closed)
        cap = self.out_cap_bytes if out_cap_bytes is None else out_cap_bytes
        start = time.time()
        try:
            proc = subprocess.Popen(
                argv, shell=False, cwd=cwd, env=self._scrub_env(env),
                stdin=subprocess.PIPE if input is not None else None,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding=encoding, errors="replace", **self._posix_kwargs())
        except FileNotFoundError as exc:
            return ExecResult(returncode=None, stdout="", stderr=str(exc),
                              elapsed_ms=(time.time() - start) * 1000.0)
        except PermissionError as exc:
            return ExecResult(returncode=None, stdout="", stderr=str(exc),
                              elapsed_ms=(time.time() - start) * 1000.0)
        try:
            out, err, truncated = self._bounded_communicate(proc, cap, timeout, input)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            return ExecResult(returncode=None, stdout="", stderr="", timed_out=True,
                              elapsed_ms=(time.time() - start) * 1000.0)
        return ExecResult(returncode=proc.returncode, stdout=out, stderr=err,
                          truncated=truncated,
                          elapsed_ms=(time.time() - start) * 1000.0)

    def _bounded_communicate(self, proc, cap, timeout, input_text=None):
        # communicate() buffers the full stream; we cap the STORED slice for resume
        # reproducibility and bounded returned memory (data-lens #4). Peak-buffer
        # streaming cap is a documented deferral; FD/timeout/rlimit bound resources.
        out, err = proc.communicate(input=input_text, timeout=timeout)
        def _cap(s):
            s = s or ""
            return (s, False) if len(s) <= cap else (s[:cap], True)
        o, tr_o = _cap(out)
        e, tr_e = _cap(err)
        return o, e, tr_o or tr_e

    # ---- sanctioned popen (Popen + pipes, for MCP handshake) ----
    def popen(self, cmd, *, cwd=None, env=None, encoding="utf-8"):
        argv = self._to_argv(cmd)
        if not argv:
            raise ValueError("ExecGate.popen: empty command")
        # Phase 1 Task B: GuardianLight hook BEFORE any spawn
        self._guardian_check(cmd, tool_name="shell_command")
        self._assert_interpreter(argv)  # MCP server python must be allow-listed
        return subprocess.Popen(
            argv, shell=False, cwd=cwd, env=self._scrub_env(env),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding=encoding, errors="replace", **self._posix_kwargs())

    # ---- convenience: legacy subprocess.run drop-in mapping ----
    @staticmethod
    def result_to_completed(res: ExecResult):
        # Minimal CompletedProcess-like shim for callers that read .returncode/.stdout.
        from types import SimpleNamespace
        return SimpleNamespace(returncode=res.returncode, stdout=res.stdout,
                               stderr=res.stderr, timed_out=res.timed_out)


def local_exec_gate(root=None, *, project_root=None):
    """Build a real ExecGate for a trusted local caller or test.

    cycle-36 A: the backtest adapter and the OODA callback/regression sinks are
    fail-closed -- without a gate there is no spawn.  Tests that genuinely exercise
    the spawn path use this factory instead of relying on a bare subprocess.run.
    The gate is bound to a throwaway RuntimePaths whose interpreter allow-list is
    the *current* interpreter (the production default); production callers still
    pass the run's own gate.  Construction performs no I/O and no spawn.
    """
    from runtime_paths import RuntimePaths

    base = (Path(root) if root is not None
            else Path(tempfile.mkdtemp(prefix="loop-gate-")))
    project_root = (Path(project_root) if project_root is not None
                    else Path(__file__).resolve().parent.parent)
    runtime = RuntimePaths.from_config(
        {"runtime": {"root": str(base)}}, project_root,
        Path(__file__).resolve().parent).ensure()
    return ExecGate(runtime)
