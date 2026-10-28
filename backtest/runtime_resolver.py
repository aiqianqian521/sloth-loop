"""Portable runtime and market-data resolution for loop tasks.

The bridge is executed by Loop from several working directories.  Keeping
resolution in this dependency-free module makes the boundary deterministic
and testable without importing an external task runtime.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence


REQUIRED_RUNTIME_DIRS = ("core", "signals", "backtest")
DEFAULT_RUNTIME_CANDIDATES = (
    Path(r"<RUNTIME_ROOT>"),
)
LEGACY_DATA_PATH = Path(r"<DATA_ROOT>\ETH_USDC_5m_2024-01-05_2026-07-29.csv")
DATA_GLOB = "ETH_USDC_5m_*.csv"
RESOLVER_VERSION = "loop_runtime.v1"


class RuntimeResolutionError(RuntimeError):
    """Raised when no runtime with the required module layout is available."""


class DataResolutionError(FileNotFoundError):
    """Raised when an explicitly requested or discoverable data file is absent."""


def _resolve_path(value: str | os.PathLike[str], *, base_dir: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    return path.resolve(strict=False)


def _absolute_unresolved(value: str | os.PathLike[str], *, base_dir: Path | None = None) -> Path:
    """Return an absolute path without following symlinks."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    return path.absolute()


def _symlink_component(path: Path) -> Path | None:
    """Find the first existing symlink component in a path, if any."""
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            return current
    return None


def _valid_runtime(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_dir() for name in REQUIRED_RUNTIME_DIRS)


def resolve_runtime_root(
    runtime: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    candidates: Sequence[str | os.PathLike[str]] | None = None,
) -> Path:
    """Resolve a trusted task runtime root using explicit, deterministic priority.

    An explicitly supplied ``runtime`` or ``LOOP_RUNTIME`` is never silently
    replaced by a fallback when invalid; a misconfigured deployment should
    fail at the boundary with an actionable error.
    """

    environ = os.environ if env is None else env
    explicit = runtime if runtime is not None else environ.get("LOOP_RUNTIME")
    if explicit:
        raw = _absolute_unresolved(explicit)
        link = _symlink_component(raw)
        if link is not None:
            raise RuntimeResolutionError(
                f"LOOP_RUNTIME cannot contain symlink component: {link}"
            )
        path = raw.resolve(strict=False)
        if _valid_runtime(path):
            return path
        missing = [name for name in REQUIRED_RUNTIME_DIRS if not (path / name).is_dir()]
        raise RuntimeResolutionError(
            f"Task runtime is invalid: {path} (missing directories: {', '.join(missing)})"
        )

    pool = DEFAULT_RUNTIME_CANDIDATES if candidates is None else tuple(candidates)
    checked: list[str] = []
    for candidate in pool:
        raw = _absolute_unresolved(candidate)
        checked.append(str(raw))
        if _symlink_component(raw) is not None:
            continue
        path = raw.resolve(strict=False)
        if _valid_runtime(path):
            return path
    raise RuntimeResolutionError(
        "No valid task runtime found; set LOOP_RUNTIME to a directory containing "
        f"{', '.join(REQUIRED_RUNTIME_DIRS)}. Checked: {', '.join(checked)}"
    )


# Short public alias for callers that model the bridge as ``resolve_runtime``.
resolve_runtime = resolve_runtime_root


def _require_file(path: Path, *, source: str) -> Path:
    raw = _absolute_unresolved(path)
    link = _symlink_component(raw)
    if raw.suffix.lower() != ".csv":
        raise DataResolutionError(f"K-line data from {source} must be a CSV file: {raw}")
    if raw.is_file() and link is None:
        return raw.resolve(strict=False)
    if link is not None:
        raise DataResolutionError(f"K-line data from {source} cannot be a symlink: {raw}")
    raise DataResolutionError(f"K-line data from {source} does not exist: {raw}")


def resolve_data_path(
    explicit: str | os.PathLike[str] | None = None,
    *,
    runtime_root: str | os.PathLike[str] | Path | None = None,
    env: Mapping[str, str] | None = None,
    legacy_path: str | os.PathLike[str] | Path = LEGACY_DATA_PATH,
) -> Path:
    """Resolve a K-line CSV using explicit → env → runtime discovery priority."""

    environ = os.environ if env is None else env
    if explicit:
        return _require_file(_absolute_unresolved(explicit), source="--data")

    configured = environ.get("LOOP_KLINE_DATA")
    if configured:
        return _require_file(_absolute_unresolved(configured), source="LOOP_KLINE_DATA")

    root = _resolve_path(runtime_root) if runtime_root is not None else resolve_runtime_root(env=environ)
    data_dir = root / "kline_data"
    matches = [
        p for p in data_dir.glob(DATA_GLOB)
        if p.is_file() and _symlink_component(p) is None
    ]
    if matches:
        # mtime is the operational meaning of "latest"; name is a stable tie-breaker.
        return max(matches, key=lambda p: (p.stat().st_mtime_ns, p.name))

    legacy = _absolute_unresolved(legacy_path)
    if legacy.is_file() and legacy.suffix.lower() == ".csv" and _symlink_component(legacy) is None:
        return legacy.resolve(strict=False)
    raise DataResolutionError(
        f"No K-line CSV found under {data_dir} matching {DATA_GLOB}; "
        f"legacy fallback is also absent: {legacy}"
    )


def fingerprint_file(path: str | os.PathLike[str] | Path) -> dict[str, int | str]:
    """Return a deterministic, non-secret fingerprint for one regular file."""
    raw = _absolute_unresolved(path)
    if _symlink_component(raw) is not None:
        raise DataResolutionError(f"Cannot fingerprint symlink path: {raw}")
    if not raw.is_file():
        raise FileNotFoundError(f"Cannot fingerprint missing file: {raw}")
    stat = raw.stat()
    digest = sha256()
    with raw.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = raw.stat()
    if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
        raise DataResolutionError(
            f"K-line data changed while fingerprinting: {raw}"
        )
    return {
        "path": str(raw.resolve(strict=False)),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": digest.hexdigest(),
    }


def fingerprint_runtime(root: str | os.PathLike[str] | Path) -> dict[str, int | str]:
    """Fingerprint runtime source code without scanning its large data/cache trees."""
    raw = _absolute_unresolved(root)
    link = _symlink_component(raw)
    if link is not None:
        raise RuntimeResolutionError(f"Cannot fingerprint symlink runtime: {link}")
    resolved = raw.resolve(strict=False)
    if not _valid_runtime(resolved):
        raise RuntimeResolutionError(f"Cannot fingerprint invalid runtime: {resolved}")

    files: list[Path] = []
    for dirname in REQUIRED_RUNTIME_DIRS:
        directory = resolved / dirname
        for candidate in directory.rglob("*.py"):
            if not candidate.is_file():
                continue
            if "__pycache__" in candidate.relative_to(resolved).parts:
                continue
            if _symlink_component(candidate) is not None:
                raise RuntimeResolutionError(
                    f"Cannot fingerprint runtime with symlink source: {candidate}"
                )
            files.append(candidate)
    files.sort(key=lambda item: item.relative_to(resolved).as_posix())
    digest = sha256()
    total_size = 0
    latest_mtime = 0
    for path in files:
        stat = path.stat()
        relative = path.relative_to(resolved).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        total_size += stat.st_size
        latest_mtime = max(latest_mtime, stat.st_mtime_ns)
    manifest = digest.hexdigest()
    return {
        "path": str(resolved),
        "root": str(resolved),
        "resolved": str(resolved),
        "size_bytes": int(total_size),
        "total_bytes": int(total_size),
        "mtime_ns": int(latest_mtime),
        "sha256": manifest,
        "manifest_sha256": manifest,
        "source_file_count": len(files),
        "file_count": len(files),
    }


def build_provenance(
    runtime_root: str | os.PathLike[str] | Path,
    data_path: str | os.PathLike[str] | Path,
    *,
    source: str = "runtime_discovery",
) -> dict[str, object]:
    """Build the bridge provenance extension consumed by TaskResult."""
    runtime = fingerprint_runtime(runtime_root)
    data = fingerprint_file(data_path)
    payload: dict[str, object] = {
        "schema": "loop.provenance.v1",
        "provenance_schema": "v1",
        "hash_algorithm": "sha256",
        "resolver": RESOLVER_VERSION,
        "data_source": source,
        "runtime": runtime,
        "data": data,
    }
    # The digest intentionally excludes host paths and volatile mtimes: it is
    # suitable for resume/idempotency, while the full metadata remains useful
    # for diagnostics and evidence.
    stable = {
        "resolver": payload["resolver"],
        "runtime": {k: runtime[k] for k in ("manifest_sha256", "file_count", "total_bytes")},
        "data": {k: data[k] for k in ("sha256", "size_bytes")},
    }
    payload["provenance_digest"] = sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload
