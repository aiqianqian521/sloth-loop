"""
Loop 回测适配器 (Backtest Adapter)

职责: 把「信号集」翻译成回测脚本的调用，并解析结果。
这是编排器与任务代码库之间的唯一耦合点 —— 换回测入口只动这个文件。

OODA R2 修复的三个问题:
  1. 脚本路径硬编码，config.yaml 里的 backtest.script 根本没生效 → 改为 configure() 注入
  2. 用字面量 "python" 调子进程，虚拟环境下会调错解释器 → 改用 sys.executable
  3. 不清理上一轮的 TEMP_OUTPUT，回测失败时会读到陈旧结果当成本轮成功 → 运行前先删

I/O 契约（真实回测脚本照此实现，参考 backtest/mock_backtest.py）:
  调用: <python> <script> --input <in.json> --output <out.json> [extra_args...]
  输入 in.json : {"signals":[...], "params":{...}, "success_starting_points":[...]}
  输出 out.json: {"trades":[{"signal_pattern","market_condition","pnl",
                             "failure_reason"|"entry_condition"...}],
                  "pnl":{"total":..}, "win_rate":"..", "sharpe":..}
  退出码 0 = 成功
"""

import json
import subprocess
from runtime_paths import ContainmentError
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 默认值。运行设置不再存放在可变模块级 dict 中；每个运行上下文拥有
# 自己的 frozen settings，旧版 configure()/run_backtest() 调用通过
# ContextVar 兼容，但不会跨线程/任务共享配置。
_HERE = Path(__file__).resolve().parent
_ENGINE_ROOT = _HERE.parent
_PROJECT_ROOT = _ENGINE_ROOT.parent


@dataclass(frozen=True)
class BacktestSettings:
    """Immutable subprocess settings for one backtest runtime."""

    script: Path
    python: str
    timeout_sec: int
    cwd: Path
    extra_args: tuple[str, ...] = ()
    input_path: Path = Path("_data/loop_backtest_input.json")
    output_path: Path = Path("_data/loop_backtest_output.json")

    def __getitem__(self, key: str) -> Any:
        """Mapping compatibility for existing orchestrator code."""
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def as_dict(self) -> dict[str, Any]:
        return {
            "script": self.script,
            "python": self.python,
            "timeout_sec": self.timeout_sec,
            "cwd": self.cwd,
            "extra_args": list(self.extra_args),
            "input_path": self.input_path,
            "output_path": self.output_path,
        }


_DEFAULT_SETTINGS = BacktestSettings(
    script=_PROJECT_ROOT / "backtest" / "mock_backtest.py",
    python=sys.executable,
    timeout_sec=3600,
    cwd=_PROJECT_ROOT,
    input_path=_PROJECT_ROOT / "_data" / "loop_backtest_input.json",
    output_path=_PROJECT_ROOT / "_data" / "loop_backtest_output.json",
)
_ACTIVE_SETTINGS: ContextVar[BacktestSettings] = ContextVar(
    "loop_backtest_settings", default=_DEFAULT_SETTINGS)


def configure(bt_cfg: dict | None, project_root: Path | None = None,
              workspace: Path | None = None,
              io_dir: Path | None = None,
              runtime_root: Path | None = None) -> BacktestSettings:
    """从 config.yaml 的 backtest 段注入设置。返回生效后的设置（便于打印/自检）。

    workspace: 任务专属工作目录。提供时 I/O 文件落在 workspace/_data/ 下，
               cwd 设为 workspace。
    io_dir: 独立 runtime I/O 目录。没有 workspace 时，输入输出落在此目录。
    """
    root = Path(project_root) if project_root else _PROJECT_ROOT
    # ``runtime_root`` was the pre-W0 keyword; keep it as an alias so older
    # integrations do not silently route artifacts back to the live tree.
    if runtime_root is not None:
        if io_dir is not None and Path(io_dir) != Path(runtime_root):
            raise ValueError("io_dir and runtime_root must point to the same directory")
        io_dir = Path(runtime_root)
    bt_cfg = bt_cfg or {}

    script = bt_cfg.get("script") or str(_DEFAULT_SETTINGS.script)
    script = Path(script)
    if not script.is_absolute():
        script = (root / script).resolve()

    python = str(bt_cfg.get("python") or sys.executable)
    timeout_sec = int(bt_cfg.get("timeout_sec") or 3600)
    if workspace:
        cwd = Path(workspace)
        input_path = cwd / "_data" / "loop_backtest_input.json"
        output_path = cwd / "_data" / "loop_backtest_output.json"
    else:
        cwd_value = bt_cfg.get("cwd")
        cwd = Path(cwd_value) if cwd_value else root
        target_io = Path(io_dir) if io_dir else root / "_data"
        input_path = target_io / "loop_backtest_input.json"
        output_path = target_io / "loop_backtest_output.json"
    extra = bt_cfg.get("extra_args") or []
    if isinstance(extra, str):
        extra = extra.split()
    settings = BacktestSettings(
        script=script,
        python=python,
        timeout_sec=timeout_sec,
        cwd=cwd,
        extra_args=tuple(str(a) for a in extra),
        input_path=input_path,
        output_path=output_path,
    )
    _ACTIVE_SETTINGS.set(settings)
    return settings


def current_settings() -> dict:
    """Return a copy of the active settings for diagnostics/compatibility."""
    return _ACTIVE_SETTINGS.get().as_dict()


def probe_provenance(settings: BacktestSettings | dict | None = None, *, exec_gate=None) -> dict | None:
    """Ask a provenance-aware bridge for its current source digest.

    Bridges that predate ``--provenance-only`` simply return ``None``; their
    legacy checkpoints remain governed by the existing config/pool guards.

    cycle-36 A: without an ExecGate there is no spawn (fail-closed): the probe
    returns ``None`` instead of falling back to a bare ``subprocess.run``.
    """
    active = _coerce_settings(settings)
    probe_output = active.output_path.with_name(
        f"{active.output_path.stem}.provenance_probe.json")
    cmd = [str(active.python), str(active.script),
           "--input", str(active.input_path), "--output", str(probe_output),
           "--provenance-only"]
    if exec_gate is None:
        # cycle-36 A: no gate -> no spawn (fail-closed).  A provenance probe is a
        # real subprocess sink, so it may not fall back to a bare subprocess.run.
        return None
    try:
        probe_output.parent.mkdir(parents=True, exist_ok=True)
        if probe_output.exists():
            probe_output.unlink()
        result = exec_gate.run(cmd, cwd=str(active.cwd),
                               timeout=min(active.timeout_sec, 120),
                               assert_interpreter=True)
        if result.timed_out or result.returncode != 0:
            return None
        payload = json.loads(probe_output.read_text(encoding="utf-8"))
        provenance = payload.get("provenance") if isinstance(payload, dict) else None
        return dict(provenance) if isinstance(provenance, dict) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None
    finally:
        try:
            if probe_output.exists():
                probe_output.unlink()
        except OSError:
            pass


@dataclass
class BacktestInput:
    signals: list[dict]
    params: dict = field(default_factory=dict)
    success_starting_points: list[dict] = field(default_factory=list)


@dataclass
class BacktestResult:
    status: str                    # completed | error
    signals_tested: int = 0
    trades: list[dict] = field(default_factory=list)
    pnl: dict = field(default_factory=dict)
    win_rate: str = ""
    sharpe: float = 0.0
    error: str = ""
    raw_stdout: str = ""
    extra_metrics: dict = field(default_factory=dict)
    # Unified result contract layers.  ``status`` remains the legacy summary.
    execution: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    business: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    error_code: str = ""

    @property
    def metrics(self) -> dict:
        """Compatibility view of non-contract metrics from bridge output."""
        return self.extra_metrics

    def __post_init__(self) -> None:
        self.execution = dict(self.execution or {})
        self.output = dict(self.output or {})
        self.business = dict(self.business or {})
        self.provenance = dict(self.provenance or {})
        self.provenance.setdefault("component", "backtest_adapter")
        if self.execution and self.output:
            return
        if self.status == "completed":
            self.execution = {"status": "succeeded", "exit_code": 0}
            self.output = {"status": "valid", "schema": "backtest.v1",
                           "trade_count": len(self.trades)}
            self.business = {"status": "pending", "criteria": {"trades_count": len(self.trades)}}
            return
        msg = self.error or ""
        code = self.error_code or "runner_error"
        execution_status = "failed"
        output_status = "not_available"
        if "超时" in msg or "timeout" in msg.lower():
            code, execution_status, output_status = "timeout", "timeout", "not_run"
        elif "非零退出" in msg or "nonzero" in msg.lower():
            code, execution_status, output_status = "process_nonzero_exit", "failed", "not_run"
        elif "启动失败" in msg or "start" in msg.lower():
            code, execution_status, output_status = "process_start_failed", "failed", "not_run"
        elif "不存在" in msg or "missing" in msg.lower():
            code, execution_status, output_status = "script_missing", "not_started", "not_run"
        elif "没写输出" in msg or "output" in msg.lower() and "文件" in msg:
            code, execution_status, output_status = "output_missing", "succeeded", "missing"
        elif "JSON" in msg or "json" in msg:
            code, execution_status, output_status = "output_invalid_json", "succeeded", "invalid_json"
        self.execution = {"status": execution_status, "stage": "execution", "code": code,
                          "timed_out": code == "timeout"}
        self.output = {"status": output_status, "code": code,
                       "present": output_status not in {"not_run", "missing", "not_available"},
                       "parseable": output_status not in {"not_run", "not_available", "invalid_json"},
                       "schema_valid": output_status == "valid"}
        self.business = {"status": "not_evaluated", "criteria": {}}


def _coerce_settings(settings: BacktestSettings | dict | None) -> BacktestSettings:
    if settings is None:
        return _ACTIVE_SETTINGS.get()
    if isinstance(settings, BacktestSettings):
        return settings
    base = _ACTIVE_SETTINGS.get()
    values = dict(settings or {})
    extra = values.get("extra_args") if "extra_args" in values else base.extra_args
    return BacktestSettings(
        script=Path(values.get("script") or base.script),
        python=str(values.get("python") or base.python or sys.executable),
        timeout_sec=int(values.get("timeout_sec") or base.timeout_sec),
        cwd=Path(values.get("cwd") or base.cwd),
        extra_args=tuple(str(a) for a in (extra or [])),
        input_path=Path(values.get("input_path") or base.input_path),
        output_path=Path(values.get("output_path") or base.output_path),
    )


def _merge_bridge_provenance(base: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Keep adapter metadata and nest the bridge's versioned source contract."""
    merged = dict(base)
    source = payload.get("provenance")
    if isinstance(source, dict):
        merged["source"] = dict(source)
        if source.get("provenance_digest"):
            merged["provenance_digest"] = source["provenance_digest"]
    return merged


def _legacy_run_backtest(inp: BacktestInput,
                         settings: BacktestSettings | dict | None = None,
                         *, exec_gate=None) -> BacktestResult:
    """执行一次回测。任何异常都转成 BacktestResult(status="error")，绝不向上抛。"""
    active = _coerce_settings(settings)
    script: Path = active.script
    in_path: Path = active.input_path
    out_path: Path = active.output_path
    timeout = active.timeout_sec

    def contract_error(message: str, code: str, *, execution_status: str = "not_started",
                       output_status: str = "not_run", stage: str = "execution",
                       output_extra: dict | None = None, **execution_extra: Any) -> BacktestResult:
        output_payload = {"status": output_status, "code": code,
                          "present": output_status not in {"not_run", "missing", "not_available"},
                          "parseable": output_status not in {"not_run", "not_available", "invalid_json"},
                          "schema_valid": output_status == "valid"}
        output_payload.update(output_extra or {})
        return BacktestResult(
            status="error", signals_tested=len(inp.signals), error=message,
            error_code=code,
            execution={"status": execution_status, "stage": stage, "code": code, **execution_extra},
            output=output_payload,
            business={"status": "not_evaluated"},
            provenance={"script": str(script), "input_path": str(in_path),
                        "output_path": str(out_path)},
        )

    in_path.parent.mkdir(parents=True, exist_ok=True)
    in_path.write_text(
        json.dumps({
            "signals": inp.signals,
            "params": inp.params,
            "success_starting_points": inp.success_starting_points,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 修复3: 清掉上一轮输出，避免脚本失败时读到陈旧结果
    if out_path.exists():
        try:
            out_path.unlink()
        except OSError as e:
            return BacktestResult(status="error", signals_tested=len(inp.signals),
                                  error=f"无法清理上轮输出 {out_path}: {e}")

    if not script.exists():
        return BacktestResult(
            status="error",
            signals_tested=len(inp.signals),
            error=(f"回测脚本不存在: {script}\n"
                   f"请修改 sloth_engine/config.yaml 的 backtest.script 指向真实脚本，"
                   f"或先用演示脚本 backtest/mock_backtest.py 跑通流程"),
        )

    cmd = [str(active.python), str(script),
           "--input", str(in_path), "--output", str(out_path)]
    cmd += [str(a) for a in active.extra_args]

    if exec_gate is None:
        # cycle-36 A: dead legacy path kept for archaeology only -- it must not
        # spawn outside the gate either (fail-closed).
        return BacktestResult(status="error", signals_tested=len(inp.signals),
                              error="exec_gate required (fail-closed): legacy path")
    try:
        _gr = exec_gate.run(cmd, cwd=str(active.cwd), timeout=timeout)
        from types import SimpleNamespace as _SNS
        proc = _SNS(returncode=_gr.returncode, stdout=_gr.stdout, stderr=_gr.stderr)
    except subprocess.TimeoutExpired:
        return BacktestResult(status="error", signals_tested=len(inp.signals),
                              error=f"回测超时(>{timeout}s): {script.name}")
    except (OSError, ValueError) as e:
        return BacktestResult(status="error", signals_tested=len(inp.signals),
                              error=f"回测启动失败: {e}")

    if proc.returncode != 0:
        return BacktestResult(
            status="error", signals_tested=len(inp.signals),
            error=f"回测脚本非零退出({proc.returncode}): {(proc.stderr or '')[:1500]}",
            raw_stdout=(proc.stdout or "")[:1500],
        )

    if not out_path.exists():
        return BacktestResult(
            status="error", signals_tested=len(inp.signals),
            raw_stdout=(proc.stdout or "")[:1500],
            error=(f"回测脚本退出码为0但没写输出文件 {out_path}。"
                   f"请让脚本按契约写 JSON（见 backtest/mock_backtest.py）"),
        )

    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return BacktestResult(status="error", signals_tested=len(inp.signals),
                              error=f"回测输出不是合法 JSON: {e}",
                              raw_stdout=(proc.stdout or "")[:1500])

    if not isinstance(data, dict):
        return BacktestResult(status="error", signals_tested=len(inp.signals),
                              error="回测输出顶层必须是 JSON 对象")

    trades = data.get("trades", [])
    if not isinstance(trades, list):
        return BacktestResult(status="error", signals_tested=len(inp.signals),
                              error="回测输出 trades 字段必须是数组")

    for index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            return BacktestResult(status="error", signals_tested=len(inp.signals),
                                  error=f"回测输出 trades[{index}] 必须是对象")
        if not trade.get("signal_pattern"):
            return BacktestResult(status="error", signals_tested=len(inp.signals),
                                  error=f"回测输出 trades[{index}] 缺少 signal_pattern")
        if not isinstance(trade.get("pnl"), (int, float)):
            return BacktestResult(status="error", signals_tested=len(inp.signals),
                                  error=f"回测输出 trades[{index}].pnl 必须是数字")

    return BacktestResult(
        status="completed", signals_tested=len(inp.signals),
        trades=trades, pnl=data.get("pnl", {}) or {},
        win_rate=str(data.get("win_rate", "")), sharpe=float(data.get("sharpe", 0) or 0),
        raw_stdout=(proc.stdout or "")[:1500],
        extra_metrics={
            k: v for k, v in data.items()
            if k not in {"trades", "pnl", "win_rate", "sharpe", "provenance"}
        },
        provenance=_merge_bridge_provenance(
            {"script": str(script), "input_path": str(in_path),
             "output_path": str(out_path)}, data),
    )


def run_backtest(inp: BacktestInput,
                 settings: BacktestSettings | dict | None = None,
                 *, exec_gate=None) -> BacktestResult:
    """Execute the adapter with one deterministic result-contract boundary.

    The legacy implementation is retained for compatibility archaeology, but all
    current callers use this path so every failure has a stable code and layer
    metadata instead of requiring consumers to parse localized error text.
    """
    active = _coerce_settings(settings)
    script, in_path, out_path = active.script, active.input_path, active.output_path

    def fail(code: str, message: str, *, execution_status: str = "not_started",
             output_status: str = "not_run", **extra: Any) -> BacktestResult:
        output = {
            "status": output_status, "code": code,
            "present": output_status not in {"not_run", "missing", "not_available"},
            "parseable": output_status not in {"not_run", "not_available", "invalid_json"},
            "schema_valid": output_status == "valid",
        }
        return BacktestResult(
            status="error", signals_tested=len(inp.signals), error=message,
            error_code=code,
            execution={"status": execution_status, "stage": "execution", "code": code, **extra},
            output=output, business={"status": "not_evaluated", "criteria": {}},
            provenance={"component": "backtest_adapter", "adapter": "backtest",
                        "script": str(script), "input_path": str(in_path),
                        "output_path": str(out_path)},
        )

    try:
        in_path.parent.mkdir(parents=True, exist_ok=True)
        in_path.write_text(json.dumps({
            "signals": inp.signals,
            "params": inp.params,
            "success_starting_points": inp.success_starting_points,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError) as exc:
        return fail("input_write_failed", f"无法写入回测输入: {exc}")

    try:
        if out_path.exists():
            out_path.unlink()
    except OSError as exc:
        return fail("output_cleanup_failed", f"无法清理上一轮输出: {exc}")

    if not script.exists():
        return fail("script_missing", f"回测脚本不存在: {script}")

    cmd = [str(active.python), str(script), "--input", str(in_path), "--output", str(out_path)]
    cmd.extend(str(a) for a in active.extra_args)
    if exec_gate is None:
        # cycle-36 A: no gate -> no spawn (fail-closed).  The removed bare
        # subprocess.run fallback was the F1 hole: a caller that forgot the gate
        # silently ran unguarded (no guardian check, no scrub_env, no output cap).
        return fail("exec_gate_required",
                    "run_backtest requires an ExecGate (fail-closed): inject the run's gate",
                    execution_status="not_started")
    try:
        proc = exec_gate.run(cmd, cwd=str(active.cwd),
                             timeout=active.timeout_sec, assert_interpreter=True)
        if proc.timed_out:
            return fail("timeout", f"回测超时(>{active.timeout_sec}s): {script.name}",
                        execution_status="timeout", timed_out=True)
        if proc.returncode is None:
            return fail("process_start_failed", f"回测启动失败: {proc.stderr or '' }",
                        execution_status="failed")
    except ContainmentError as exc:
        if getattr(exc, "kind", "") == "guardian":
            return fail("guardian_denied", f"回测被安全策略拒绝: {exc}",
                        execution_status="failed")
        return fail("interpreter_denied", f"回测解释器被拒绝: {exc}", execution_status="failed")
    except subprocess.TimeoutExpired:
        return fail("timeout", f"回测超时(>{active.timeout_sec}s): {script.name}",
                    execution_status="timeout", timed_out=True)
    except (OSError, ValueError) as exc:
        return fail("process_start_failed", f"回测启动失败: {exc}", execution_status="failed")

    stdout = (proc.stdout or "")[:1500]
    if proc.returncode != 0:
        result = fail("process_nonzero_exit", f"回测脚本非零退出({proc.returncode})",
                      execution_status="failed", exit_code=proc.returncode)
        result.raw_stdout = stdout
        return result
    if not out_path.exists():
        result = fail("output_missing", f"回测脚本退出码为 0 但没写输出文件: {out_path}",
                      execution_status="succeeded", output_status="missing", exit_code=0)
        result.raw_stdout = stdout
        return result
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result = fail("output_invalid_json", f"回测输出不是合法 JSON: {exc}",
                      execution_status="succeeded", output_status="invalid_json", exit_code=0)
        result.raw_stdout = stdout
        return result
    if not isinstance(data, dict):
        return fail("output_schema_invalid", "回测输出顶层必须是 JSON 对象",
                    execution_status="succeeded", output_status="invalid_schema", exit_code=0)
    trades = data.get("trades", [])
    if not isinstance(trades, list):
        return fail("trades_not_array", "回测输出 trades 必须是数组",
                    execution_status="succeeded", output_status="invalid_schema", exit_code=0)
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            return fail("trade_not_object", f"trades[{index}] 必须是对象",
                        execution_status="succeeded", output_status="invalid_schema", exit_code=0)
        if not trade.get("signal_pattern"):
            return fail("trade_missing_signal_pattern", f"trades[{index}] 缺少 signal_pattern",
                        execution_status="succeeded", output_status="invalid_schema", exit_code=0)
        if not isinstance(trade.get("pnl"), (int, float)):
            return fail("trade_invalid_pnl", f"trades[{index}].pnl 必须是数字",
                        execution_status="succeeded", output_status="invalid_schema", exit_code=0)

    return BacktestResult(
        status="completed", signals_tested=len(inp.signals), trades=trades,
        pnl=data.get("pnl", {}) or {}, win_rate=str(data.get("win_rate", "")),
        sharpe=float(data.get("sharpe", 0) or 0), raw_stdout=stdout,
        extra_metrics={k: v for k, v in data.items()
                       if k not in {"trades", "pnl", "win_rate", "sharpe", "provenance"}},
        execution={"status": "succeeded", "stage": "execution", "code": "ok",
                   "exit_code": 0, "timed_out": False},
        output={"status": "valid", "code": "ok", "schema": "backtest.v1",
                "present": True, "parseable": True, "schema_valid": True,
                "trade_count": len(trades)},
        business={"status": "pending", "criteria": {"trades_count": len(trades)}},
        provenance=_merge_bridge_provenance(
            {"component": "backtest_adapter", "adapter": "backtest",
             "script": str(script), "input_path": str(in_path),
             "output_path": str(out_path)}, data),
    )
