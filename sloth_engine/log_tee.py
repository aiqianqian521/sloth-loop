"""Console-to-log tee (long-running batch sessions).

Extracted from orchestrator.py (P2.1 Slice A). Behavior unchanged.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

class _Tee:
    """Tee console output to log file (for long-running batch sessions)."""
    def __init__(self, stream, path: Path):
        self.stream = stream
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")
        self.fh.write(f"\n{'=' * 70}\n[session] {datetime.now().isoformat()}\n")

    def write(self, s):
        self.stream.write(s)
        self.fh.write(s)
        self.fh.flush()

    def flush(self):
        self.stream.flush()
        self.fh.flush()

    def isatty(self):
        return getattr(self.stream, "isatty", lambda: False)()

    def close(self):
        self.fh.close()
