# -*- coding: utf-8 -*-
"""L3 cycle-6 A4 - rolling-window rate limiter with memory fallback (C4).

Provenance (distilled from open-webui@0.11.3):
  backend/open_webui/utils/rate_limit.py:7-11   (rolling window + memory fallback)
  backend/open_webui/utils/rate_limit.py:47-61  (graceful degrade on backend error)
  backend/open_webui/utils/rate_limit.py:79-93  (incr + expire + mget sum)
  backend/open_webui/utils/rate_limit.py:101-121 (memory buckets + drop expired)

Contract under test (behavioural, not source-grep):
  1. disabled -> never limited, count 0.
  2. under limit -> allowed; crossing limit -> limited.
  3. backend that raises -> memory fallback still enforces the limit.
  4. expiry slides the window (old buckets dropped).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from rate_limiter import RollingWindowRateLimiter  # noqa: E402


class _Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += sec


class _FakeRedis:
    """Minimal Redis-like backend honouring incr/expire/mget."""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key, seconds):
        self.ttls[key] = seconds

    def mget(self, keys):
        return [self.store.get(k) for k in keys]


class _BrokenRedis:
    def incr(self, key):
        raise ConnectionError("redis down")

    def expire(self, key, seconds):  # pragma: no cover - never reached
        raise ConnectionError("redis down")

    def mget(self, keys):  # pragma: no cover - never reached
        raise ConnectionError("redis down")


@pytest.fixture(autouse=True)
def _clean_memory():
    RollingWindowRateLimiter._memory_store.clear()
    yield
    RollingWindowRateLimiter._memory_store.clear()


# -- invariant 1: disabled bypass ------------------------------------------
def test_disabled_never_limited_and_count_zero():
    clk = _Clock()
    rl = RollingWindowRateLimiter(limit=2, window=60, enabled=False, clock=clk)
    for _ in range(10):
        assert rl.is_limited("u") is False
    assert rl.get_count("u") == 0
    assert rl.remaining("u") == 2


# -- invariant 2: limit enforcement (memory path) --------------------------
def test_memory_path_enforces_limit():
    clk = _Clock()
    rl = RollingWindowRateLimiter(limit=3, window=60, bucket_size=60, clock=clk)
    assert rl.is_limited("u") is False  # 1
    assert rl.is_limited("u") is False  # 2
    assert rl.is_limited("u") is False  # 3
    assert rl.is_limited("u") is True   # 4 > 3
    assert rl.get_count("u") == 4
    assert rl.remaining("u") == 0


def test_keys_are_isolated():
    clk = _Clock()
    rl = RollingWindowRateLimiter(limit=1, window=60, clock=clk)
    assert rl.is_limited("a") is False
    assert rl.is_limited("b") is False  # different key, independent
    assert rl.is_limited("a") is True


# -- invariant 3: backend failure degrades to memory, not to unlimited -----
def test_backend_exception_falls_back_and_still_limits():
    clk = _Clock()
    rl = RollingWindowRateLimiter(
        limit=2, window=60, backend=_BrokenRedis(), clock=clk
    )
    assert rl.is_limited("u") is False  # 1
    assert rl.is_limited("u") is False  # 2
    assert rl.is_limited("u") is True   # 3 > 2 -> memory still enforces
    assert rl.get_count("u") == 3


def test_healthy_backend_used_and_enforces_limit():
    clk = _Clock()
    be = _FakeRedis()
    rl = RollingWindowRateLimiter(limit=2, window=60, backend=be, clock=clk)
    assert rl.is_limited("u") is False
    assert rl.is_limited("u") is False
    assert rl.is_limited("u") is True
    assert rl.get_count("u") == 3
    assert be.store  # backend actually used


# -- invariant 4: window slides --------------------------------------------
def test_window_slides_drops_expired_buckets():
    clk = _Clock()
    rl = RollingWindowRateLimiter(limit=1, window=60, bucket_size=60, clock=clk)
    assert rl.is_limited("u") is False
    assert rl.is_limited("u") is True     # within same bucket
    clk.advance(120)                      # two buckets later -> window slid
    assert rl.is_limited("u") is False
    assert rl.get_count("u") == 1


def test_multi_bucket_window_counts_across_buckets():
    clk = _Clock()
    # window 120 / bucket 60 -> 2 buckets; events in adjacent buckets sum
    rl = RollingWindowRateLimiter(limit=2, window=120, bucket_size=60, clock=clk)
    assert rl.is_limited("u") is False  # bucket 0 -> 1
    clk.advance(60)
    assert rl.is_limited("u") is False  # bucket 1 -> total 2
    assert rl.is_limited("u") is True   # total 3 > 2


# -- constructor guards -----------------------------------------------------
@pytest.mark.parametrize("limit,window,bucket", [(0, 60, 60), (-1, 60, 60), (1, 0, 60), (1, 60, 0)])
def test_invalid_constructor_args_rejected(limit, window, bucket):
    with pytest.raises(ValueError):
        RollingWindowRateLimiter(limit=limit, window=window, bucket_size=bucket)


def test_reset_clears_local_buckets():
    clk = _Clock()
    rl = RollingWindowRateLimiter(limit=1, window=60, clock=clk)
    rl.is_limited("u")
    assert rl.get_count("u") == 1
    rl.reset("u")
    assert rl.get_count("u") == 0
