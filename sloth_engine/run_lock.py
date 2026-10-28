"""Process-level mutex (cron + manual run exclusion).

Extracted from orchestrator.py (P2.1 Slice A). Behavior unchanged.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

_log = logging.getLogger("sloth_engine")


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness probe for a PID written into a lock file.

    Returns True only when we are confident the process still exists, and
    False when the process is provably gone.  Ambiguous/permission errors
    return True (fail-safe: never steal a lock we cannot prove is dead).
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Access denied can still mean the process exists (e.g. another
            # user's process).  ERROR_INVALID_PARAMETER (87) means no such
            # PID -> dead.  Treat only the explicit invalid-PID error as dead.
            return kernel32.GetLastError() != 87
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _parse_lock_pid(text: str) -> int | None:
    """Extract the pid from a lock body like ``pid=1234 at=...``."""
    for token in text.replace(";", " ").split():
        if token.startswith("pid="):
            try:
                return int(token[4:])
            except ValueError:
                return None
    return None

class _RunLock:
    """Simple process-level mutex. Prevents cron + manual run from writing
    the same SQLite concurrently."""
    def __init__(self, path: Path, stale_seconds: int = 6 * 3600):
        self.path = path
        self.stale = stale_seconds
        self.acquired = False

    def __enter__(self):
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            owner = self.path.read_text(encoding="utf-8", errors="replace").strip()
            owner_pid = _parse_lock_pid(owner)
            # P0-FIX: a fresh lock whose owning PID is provably dead is stale
            # even if it is younger than ``stale`` seconds.  Previously we only
            # compared age, so a crashed run left a lock that blocked every
            # subsequent run for up to 6h.  We only steal when the PID is
            # parseable AND provably not alive; otherwise fall back to the age
            # rule (never steal a lock we cannot prove is dead).
            pid_dead = owner_pid is not None and not _pid_alive(owner_pid)
            if age < self.stale and not pid_dead:
                raise RuntimeError(
                    f"Another instance is running (lock file {self.path}, "
                    f"created {age / 60:.0f} min ago by {owner}).\n"
                    f"Delete the lock file if no process is active.")
            if pid_dead:
                _log.warning(
                    f" Stale lock: owner pid={owner_pid} is no longer alive "
                    f"({age / 60:.0f} min old), taking over")
            else:
                _log.warning(f" Stale lock ({age / 3600:.1f}h old), taking over")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"pid={os.getpid()} at={datetime.now().isoformat()}",
                             encoding="utf-8")
        self.acquired = True
        return self

    def __exit__(self, *exc):
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass
        return False
