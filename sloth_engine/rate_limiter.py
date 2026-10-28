"""Rolling-window rate limiter with pluggable backend and memory fallback.

Distilled from open-webui@0.11.3 backend/open_webui/utils/rate_limit.py
(see docs/knowledge-distillation/agent-orchestration/
2026-10-18-open-webui-rolling-window-rate-limiter-redis-memory-fallback.md).

Design (transferable core):
- Fixed small buckets: num_buckets = window // bucket_size. On each check we
  increment the current bucket and sum the last (num_buckets + 1) buckets. This
  avoids server-side atomic scripts (no Lua) at the cost of coarse granularity.
- Pluggable backend via a tiny protocol: any object exposing ``incr(key)``,
  ``expire(key, ttl)`` and ``mget(keys)`` works (Redis-like). When no backend is
  supplied, or the backend raises, we fall back to the in-process memory store.
- Fallback is FAIL-TO-MEMORY, never fail-open-to-unlimited: losing the backend
  degrades precision, it does not silently disable limiting.
- ``enabled=False`` is an explicit bypass that short-circuits to "not limited".

Contract invariants (asserted in tests/test_rate_limiter.py):
1. disabled -> never limited, count 0.
2. under limit -> allowed; the (limit+1)-th event in-window -> limited.
3. backend that raises on incr -> check still works via memory fallback and
   still enforces the limit (does not become unlimited).
4. expired buckets are dropped so the window slides.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Dict, Optional, Protocol, runtime_checkable

_log = logging.getLogger("sloth_engine.rate-limiter")

DEFAULT_BUCKET_SIZE = 60


@runtime_checkable
class RateLimitBackend(Protocol):
    """Minimal Redis-like backend surface required by the limiter."""

    def incr(self, key: str) -> int: ...

    def expire(self, key: str, seconds: int) -> None: ...

    def mget(self, keys: list) -> list: ...


class RollingWindowRateLimiter:
    """Fixed-bucket rolling-window limiter with memory fallback."""

    # In-memory fallback storage (class level, mirroring open-webui).
    _memory_store: Dict[str, Dict[int, int]] = {}

    def __init__(
        self,
        limit: int,
        window: int,
        bucket_size: int = DEFAULT_BUCKET_SIZE,
        enabled: bool = True,
        backend: Optional[RateLimitBackend] = None,
        key_prefix: str = "loop",
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window <= 0:
            raise ValueError("window must be positive")
        if bucket_size <= 0:
            raise ValueError("bucket_size must be positive")
        self.limit = int(limit)
        self.window = int(window)
        self.bucket_size = int(bucket_size)
        self.num_buckets = max(1, self.window // self.bucket_size)
        self.enabled = bool(enabled)
        self.backend = backend
        self.key_prefix = key_prefix
        self._clock = clock or time.time

    # -- key helpers -------------------------------------------------------
    def _bucket_key(self, key: str, bucket_index: int) -> str:
        return f"{self.key_prefix}:ratelimit:{key.lower()}:{bucket_index}"

    def _current_bucket(self) -> int:
        return int(self._clock()) // self.bucket_size

    def _backend_available(self) -> bool:
        return self.backend is not None

    # -- public API --------------------------------------------------------
    def is_limited(self, key: str) -> bool:
        """Return True when *key* has exceeded ``limit`` in the window."""
        if not self.enabled:
            return False
        if self._backend_available():
            try:
                return self._is_limited_backend(key)
            except Exception as exc:  # degrade precision, not protection
                _log.warning(
                    "[rate-limit] backend failed (%s); falling back to memory", exc
                )
                return self._is_limited_memory(key)
        return self._is_limited_memory(key)

    def get_count(self, key: str) -> int:
        if not self.enabled:
            return 0
        if self._backend_available():
            try:
                return self._get_count_backend(key)
            except Exception:
                return self._get_count_memory(key)
        return self._get_count_memory(key)

    def remaining(self, key: str) -> int:
        return max(0, self.limit - self.get_count(key))

    def reset(self, key: str) -> None:
        """Drop all local buckets for *key* (test/maintenance helper)."""
        self._memory_store.pop(key.lower(), None)

    # -- backend path ------------------------------------------------------
    def _is_limited_backend(self, key: str) -> bool:
        now_bucket = self._current_bucket()
        bucket_key = self._bucket_key(key, now_bucket)
        attempts = self.backend.incr(bucket_key)
        if attempts == 1:
            self.backend.expire(bucket_key, self.window + self.bucket_size)
        buckets = [
            self._bucket_key(key, now_bucket - i)
            for i in range(self.num_buckets + 1)
        ]
        counts = self.backend.mget(buckets)
        total = sum(int(c) for c in counts if c)
        return total > self.limit

    def _get_count_backend(self, key: str) -> int:
        now_bucket = self._current_bucket()
        buckets = [
            self._bucket_key(key, now_bucket - i)
            for i in range(self.num_buckets + 1)
        ]
        counts = self.backend.mget(buckets)
        return sum(int(c) for c in counts if c)

    # -- memory path -------------------------------------------------------
    def _is_limited_memory(self, key: str) -> bool:
        now_bucket = self._current_bucket()
        store = self._memory_store.setdefault(key.lower(), {})
        store[now_bucket] = store.get(now_bucket, 0) + 1
        self._drop_expired(store, now_bucket)
        return sum(store.values()) > self.limit

    def _get_count_memory(self, key: str) -> int:
        now_bucket = self._current_bucket()
        store = self._memory_store.get(key.lower())
        if not store:
            return 0
        self._drop_expired(store, now_bucket)
        return sum(store.values())

    def _drop_expired(self, store: Dict[int, int], now_bucket: int) -> None:
        min_bucket = now_bucket - self.num_buckets
        for b in [b for b in store if b < min_bucket]:
            del store[b]
