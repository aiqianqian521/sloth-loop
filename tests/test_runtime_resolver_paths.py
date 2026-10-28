"""Contract tests for the portable task runtime path resolver.

These tests intentionally import ``backtest.runtime_resolver`` instead of
the ``backtest`` task bridge itself.  The resolver is a dependency-free seam, so path
selection can be verified without importing an external task runtime (or
running a backtest).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backtest.runtime_resolver import (
    DataResolutionError,
    RuntimeResolutionError,
    resolve_data_path,
    resolve_runtime_root,
)


def _runtime(root: Path) -> Path:
    """Create the minimum trusted runtime layout required by the contract."""
    for name in ("core", "signals", "backtest", "kline_data"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _csv(root: Path, name: str, *, mtime_ns: int | None = None) -> Path:
    (root / "kline_data").mkdir(parents=True, exist_ok=True)
    path = root / "kline_data" / name
    path.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def test_runtime_environment_has_priority(tmp_path: Path) -> None:
    env_runtime = _runtime(tmp_path / "from-env")
    fallback = _runtime(tmp_path / "fallback")

    resolved = resolve_runtime_root(
        env={"LOOP_RUNTIME": str(env_runtime)},
        candidates=[fallback],
    )

    assert resolved == env_runtime.resolve()


def test_explicit_runtime_has_priority_over_environment(tmp_path: Path) -> None:
    explicit = _runtime(tmp_path / "explicit")
    from_env = _runtime(tmp_path / "from-env")

    resolved = resolve_runtime_root(
        explicit,
        env={"LOOP_RUNTIME": str(from_env)},
        candidates=[],
    )

    assert resolved == explicit.resolve()


def test_invalid_explicit_runtime_fails_closed(tmp_path: Path) -> None:
    invalid = tmp_path / "missing-runtime"

    with pytest.raises(RuntimeResolutionError, match="invalid"):
        resolve_runtime_root(invalid, candidates=[])


def test_invalid_environment_runtime_does_not_silently_fallback(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-runtime"
    fallback = _runtime(tmp_path / "fallback")

    with pytest.raises(RuntimeResolutionError, match="invalid"):
        resolve_runtime_root(env={"LOOP_RUNTIME": str(invalid)}, candidates=[fallback])


def test_runtime_without_environment_uses_first_valid_candidate(tmp_path: Path) -> None:
    valid = _runtime(tmp_path / "valid")

    assert resolve_runtime_root(env={}, candidates=[tmp_path / "nope", valid]) == valid.resolve()


def test_explicit_data_has_priority_over_environment_and_discovery(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    discovered = _csv(runtime, "ETH_USDC_5m_discovered.csv", mtime_ns=10)
    env_data = _csv(tmp_path, "ETH_USDC_5m_env.csv", mtime_ns=20)
    explicit = tmp_path / "explicit.csv"
    explicit.write_text("close\n1\n", encoding="utf-8")

    resolved = resolve_data_path(
        explicit,
        runtime_root=runtime,
        env={"LOOP_KLINE_DATA": str(env_data)},
    )

    assert resolved == explicit.resolve()
    assert resolved != discovered and resolved != env_data


def test_environment_data_is_used_before_runtime_discovery(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    _csv(runtime, "ETH_USDC_5m_discovered.csv", mtime_ns=30)
    env_data = _csv(tmp_path, "ETH_USDC_5m_env.csv", mtime_ns=20)

    assert resolve_data_path(
        runtime_root=runtime,
        env={"LOOP_KLINE_DATA": str(env_data)},
    ) == env_data.resolve()


def test_latest_runtime_csv_is_selected_by_mtime_with_name_tiebreak(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    older = _csv(runtime, "ETH_USDC_5m_2026-01-01.csv", mtime_ns=100)
    latest = _csv(runtime, "ETH_USDC_5m_2026-02-01.csv", mtime_ns=200)

    assert resolve_data_path(runtime_root=runtime, env={}) == latest.resolve()
    assert latest != older


def test_latest_runtime_csv_uses_filename_as_stable_tiebreak(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    first = _csv(runtime, "ETH_USDC_5m_a.csv", mtime_ns=500)
    second = _csv(runtime, "ETH_USDC_5m_b.csv", mtime_ns=500)

    assert resolve_data_path(runtime_root=runtime, env={}) == second.resolve()
    assert first != second


def test_runtime_discovery_ignores_unrelated_csv_files(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    unrelated = runtime / "kline_data" / "BTC_USDC_1m.csv"
    unrelated.write_text("close\n1\n", encoding="utf-8")

    with pytest.raises(DataResolutionError, match="No K-line CSV"):
        resolve_data_path(runtime_root=runtime, env={}, legacy_path=tmp_path / "none.csv")


def test_missing_explicit_data_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")

    with pytest.raises(DataResolutionError, match="--data"):
        resolve_data_path(tmp_path / "does-not-exist.csv", runtime_root=runtime)


def test_missing_data_and_legacy_fallback_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")

    with pytest.raises(DataResolutionError, match="No K-line CSV"):
        resolve_data_path(runtime_root=runtime, env={}, legacy_path=tmp_path / "legacy.csv")


def test_legacy_path_is_final_compatibility_fallback(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "runtime")
    legacy = tmp_path / "legacy.csv"
    legacy.write_text("close\n1\n", encoding="utf-8")

    assert resolve_data_path(runtime_root=runtime, env={}, legacy_path=legacy) == legacy.resolve()
