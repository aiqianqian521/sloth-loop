"""Candidate signal pool boundary for the Loop orchestrator.

The pool owns file loading, input normalization, and deterministic rotating
batches.  It has no persistence or backtest concerns, which makes it safe to
test independently and keeps the controller focused on round execution.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("sloth_engine.signal-pool")


class SignalPool:
    def __init__(self, default_path: str | None = None, batch_size: int = 0,
                 fallback_root: Path | None = None,
                 task_cfg: dict | None = None,
                 strict_schema: bool = False):
        self.default_path = default_path
        self.batch_size = max(0, int(batch_size))
        self.fallback_root = fallback_root
        self._task_cfg = task_cfg or {}
        self._strict_schema = bool(strict_schema)
        self._pool: list[dict] | None = None
        self._cursor = 0
        self._rejected: list[dict] = []
        self._schema_valid = True

    def load(self, seed_path: str | None = None) -> list[dict]:
        if self._pool is not None:
            return self._pool
        raw_path = seed_path or self.default_path
        self._pool = []
        if not raw_path:
            return self._pool
        path = Path(raw_path)
        if not path.is_absolute():
            cwd_path = Path.cwd() / path
            path = cwd_path if cwd_path.exists() else ((self.fallback_root / path) if self.fallback_root else path)
        if not path.exists():
            log.warning("Signal file not found: %s", path)
            return self._pool
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            # P1-FIX (D8): a GBK/legacy-encoded signals file used to raise an
            # uncaught UnicodeDecodeError and abort the run with a bare stack.
            # Treat it as an invalid-input error (fail closed), consistent
            # with the JSON-decode branch above.
            log.error("Signal file is not valid JSON: %s (%s)", path, exc)
            return self._pool
        if not isinstance(data, list):
            log.error("Signal file must be a JSON array, got %s", type(data).__name__)
            return self._pool
        if self._strict_schema:
            from signal_schema import validate_signals
            v = validate_signals(data, self._task_cfg, strict=True)
            self._pool = [dict(x) for x in v["accepted"]]
            self._rejected = v["rejected"]
            self._schema_valid = v["valid"]
            if self._rejected:
                log.error("[schema] rejected %d signal(s): %s",
                          len(self._rejected),
                          ", ".join(r.get("code","?") for r in self._rejected))
            if v["warnings"]:
                for w in v["warnings"]:
                    log.warning("[schema] %s", w)
        else:
            for index, signal in enumerate(data):
                if not isinstance(signal, dict) or not signal.get("signal_pattern"):
                    log.warning("Entry #%s missing signal_pattern, skipping: %s", index, signal)
                    continue
                item = dict(signal)
                item.setdefault("market_condition", "unknown")
                self._pool.append(item)
        log.info("Candidate pool: %s signals, %s", len(self._pool),
                 f"batch_size={self.batch_size} rotating" if self.batch_size else "full pool each round")
        return self._pool

    def next_batch(self, seed_path: str | None = None) -> list[dict]:
        pool = self.load(seed_path)
        if not pool or not self.batch_size or self.batch_size >= len(pool):
            return list(pool)
        start = self._cursor % len(pool)
        batch = [pool[(start + offset) % len(pool)] for offset in range(self.batch_size)]
        self._cursor = (start + self.batch_size) % len(pool)
        return batch

    @property
    def cursor(self) -> int:
        return self._cursor

