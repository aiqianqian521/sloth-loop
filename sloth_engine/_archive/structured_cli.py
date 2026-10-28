"""结构化 CLI 执行器 — 移植自 DSH shell 包的 subprocess 管理模式。

封装 subprocess 调用，提供超时/管道/环境变量/输出捕获。

移植自 DSH packages/shell/ (Bash execution capability)
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CLIResult:
    """CLI 执行结果。"""
    status: str                           # "completed" | "timeout" | "error"
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: float = 0
    error: str = ""


def run(cmd: str | list[str],
        timeout_sec: int = 300,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        input_data: str | None = None,
        encoding: str = "utf-8") -> CLIResult:
    """执行 shell 命令，带超时和错误处理。

    参考 DSH 的 runHook() — 超时、stdin、环境变量注入。

    Args:
        cmd: 命令字符串或参数列表
        timeout_sec: 超时秒数
        cwd: 工作目录
        env: 额外环境变量（合并到当前环境）
        input_data: stdin 输入
        encoding: 输出编码
    """
    import time
    start = time.time()

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)
        proc = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            input=input_data,
            encoding=encoding,
            errors="replace",
        )
        elapsed = (time.time() - start) * 1000
        return CLIResult(
            status="completed" if proc.returncode == 0 else "error",
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            elapsed_ms=elapsed,
            error=(proc.stderr or proc.stdout or "")[:500] if proc.returncode != 0 else "",
        )
    except subprocess.TimeoutExpired:
        elapsed = (time.time() - start) * 1000
        return CLIResult(
            status="timeout",
            error=f"命令超时 (>{timeout_sec}s): {cmd if isinstance(cmd, str) else ' '.join(cmd)}",
            elapsed_ms=elapsed,
        )
    except (OSError, ValueError) as e:
        elapsed = (time.time() - start) * 1000
        return CLIResult(
            status="error",
            error=f"命令执行失败: {e}",
            elapsed_ms=elapsed,
        )


def run_with_retry(cmd: str | list[str],
                   max_retries: int = 2,
                   timeout_sec: int = 300,
                   longer_timeout: int = 600,
                   **kwargs) -> tuple[CLIResult, list[dict]]:
    """带重试的执行：standard → longer_timeout → skip。

    参考 loop L1 三策略重试模型。
    """
    attempts: list[dict] = []
    for attempt in range(max_retries + 1):
        t = longer_timeout if attempt == 1 else timeout_sec
        result = run(cmd, timeout_sec=t, **kwargs)
        attempts.append({"attempt": attempt + 1, "timeout": t,
                         "ok": result.status == "completed"})
        if result.status == "completed":
            return result, attempts
    return result, attempts