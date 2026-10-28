"""Runtime path resolution for isolated Loop runs.

The live repository historically derived runtime files from ``PROJECT_ROOT``.
That made project-mode useful for task data, but not safe for concurrent
development or multiple long-running instances.  ``RuntimePaths`` centralises
all mutable run artifacts behind one explicit root while preserving the legacy
paths when no ``runtime`` section is configured.

W2-BOUNDARY-01 / H2 Slice 1-PATH adds fail-closed runtime containment: paths
executed/read by subprocess sinks are validated against ``root`` via
``assert_under_root`` / ``assert_interpreter``; on violation the decision itself
raises after invoking an outbound ``on_violation`` port (no I/O in this
module). ``from_config`` keeps the legacy and configured branches fail-open at
the ``_resolve`` layer so existing absolute-path configs keep working; the
explicit guard API is what Orchestrator calls at the runtime sinks.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


class ContainmentError(Exception):
    """Raised when a runtime path or interpreter escapes the runtime root.

    RuntimePaths is fail-closed: a violation is reported through the injected
    ``on_violation`` outbound port and then re-raised so the calling decision
    path aborts.
    """

    def __init__(self, path: Path, root: Path, kind: str = "path", *,
                 detail: str = "") -> None:
        self.path = Path(path)
        self.root = Path(root)
        self.kind = kind
        self.detail = detail
        super().__init__(self._render())

    def _render(self) -> str:
        if self.kind == "guardian":
            # A Guardian policy decision is NOT a path escape.  Rendering it with
            # the generic template produced the misleading
            # ``guardian . escapes runtime root .`` and sent forensic agents
            # after a containment bug that did not exist (D-G2, 2026-10-25).
            return ("guardian policy denied the command (security gate; no path "
                    "escape): %s" % (self.detail or "unspecified risk"))
        base = f"{self.kind} {self.path} escapes runtime root {self.root}"
        return f"{base} ({self.detail})" if self.detail else base


# Outbound port: the orchestrator composition root injects a sink that records
# who/when/what/base/result. RuntimePaths only invokes it defensively -- the
# audit sink must never be allowed to break a fail-closed decision (mirrors the
# CircuitBreaker on_transition pattern).
OnViolation = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved, immutable paths for one Loop runtime instance."""

    root: Path
    db_path: Path
    io_dir: Path
    events_dir: Path
    logs_dir: Path
    state_file: Path
    handoff_file: Path
    # W2-BOUNDARY-01 / H2 Slice 1-PATH: runtime containment ports.
    # allowed_interpreters enables deny-by-default interpreter allow-listing at
    # subprocess sinks (from_config default: the single current interpreter).
    # on_violation is an outbound port for the audit sink; it is invoked just
    # before a ContainmentError is raised so the violation is observable even
    # when the decision path aborts.
    allowed_interpreters: frozenset[Path] = field(default_factory=frozenset)
    on_violation: OnViolation | None = None

    @staticmethod
    def _resolve(value: str | Path, base: Path) -> Path:
        path = Path(value)
        # Resolve both relative and absolute paths.  On Windows, temporary
        # directories may contain 8.3 short names (``ADMINI~1``); normalising
        # here keeps equality checks and cross-process hand-off deterministic.
        return (path if path.is_absolute() else (base / path)).resolve()

    def assert_under(self, path: str | Path, root: str | Path,
                     *, kind: str = "path") -> Path:
        """Resolve path and guarantee it stays under an explicit boundary.

        ``root`` is the containment boundary supplied by the caller: the repo
        root for trusted playbook/exec assets (backtest script, callback,
        regression tests) and the runtime root for run artifacts (db / io /
        events / logs). Symlinks are followed by resolve(), so the check
        always happens on the real target; on escape the on_violation audit
        port records who/where, then ContainmentError is raised (fail-closed).
        """
        base = Path(root).resolve()
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(base):
            self._report(kind, str(resolved), str(base))
            raise ContainmentError(resolved, base, kind)
        return resolved

    def assert_under_root(self, path: str | Path, *, kind: str = "path") -> Path:
        """Contain path to the runtime root (sandbox / run artifacts)."""
        return self.assert_under(path, self.root, kind=kind)

    def assert_interpreter(self, exe: str | Path, *, kind: str = "interpreter") -> Path:
        """Deny-by-default interpreter allow-list (H2 sys.executable allow-list).

        An empty allow-list opts out (defence used before the allow-list
        landed, or for non-subprocess callers). A non-empty list enforces
        minimum privilege: only the listed interpreters may run subprocess
        sinks.
        """
        resolved = Path(exe).resolve()
        allowed = self.allowed_interpreters
        if not allowed:
            return resolved
        if resolved not in allowed:
            self._report(kind, str(resolved), ",".join(sorted(str(a) for a in allowed)))
            raise ContainmentError(resolved, self.root, kind)
        return resolved

    def _report(self, kind: str, what: str, base: str) -> None:
        if self.on_violation is None:
            return
        try:
            self.on_violation({"kind": kind, "path": what, "base": base, "result": "denied"})
        except Exception:
            # Audit sink failure must not leak into the fail-closed decision.
            pass

    @classmethod
    def from_config(cls, config: dict, project_root: Path,
                    engine_root: Path, *,
                    on_violation: OnViolation | None = None,
                    allowed_interpreters: frozenset[Path] | None = None,
                    ) -> "RuntimePaths":
        runtime = config.get("runtime") or {}
        configured = bool(runtime)

        # Resolve deny-by-default interpreter allow-list. Default is the single
        # current interpreter unless config explicitly widens it
        # (runtime.interpreters) or the caller passes its own frozenset.
        if allowed_interpreters is None:
            configured_interpreters = (
                runtime.get("interpreters") if isinstance(runtime, dict) else None
            )
            if configured_interpreters:
                allowed_interpreters = frozenset(
                    {Path(i).resolve() for i in configured_interpreters})
            else:
                allowed_interpreters = frozenset({Path(sys.executable).resolve()})
        else:
            allowed_interpreters = frozenset(allowed_interpreters)

        # Without a runtime section retain the current on-disk layout.  This
        # keeps existing live jobs backwards compatible until they opt in.
        if not configured:
            root = project_root
            return cls(
                root=root,
                db_path=cls._resolve(
                    (config.get("memory") or {}).get("sqlite_path", "data/patterns.db"),
                    engine_root,
                ),
                io_dir=project_root / "_data",
                events_dir=project_root / "work_ooda",
                logs_dir=project_root / "logs",
                state_file=engine_root / "STATE.md",
                handoff_file=engine_root / "data" / "handoff.json",
                allowed_interpreters=allowed_interpreters,
                on_violation=on_violation,
            )

        root = cls._resolve(runtime.get("root", project_root), project_root)
        db_value = runtime.get("db") or (config.get("memory") or {}).get(
            "sqlite_path", "db/patterns.db")
        return cls(
            root=root,
            db_path=cls._resolve(db_value, root),
            io_dir=cls._resolve(runtime.get("io", "io/_data"), root),
            events_dir=cls._resolve(runtime.get("events", "runs"), root),
            logs_dir=cls._resolve(runtime.get("logs", "logs"), root),
            state_file=cls._resolve(runtime.get("state", "state/STATE.md"), root),
            handoff_file=cls._resolve(
                runtime.get("handoff", "state/handoff.json"), root),
            allowed_interpreters=allowed_interpreters,
            on_violation=on_violation,
        )

    def ensure(self) -> "RuntimePaths":
        """Create directories needed by a run; return self for fluent setup."""
        for path in (
            self.root,
            self.db_path.parent,
            self.io_dir,
            self.events_dir,
            self.logs_dir,
            self.state_file.parent,
            self.handoff_file.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "db_path": str(self.db_path),
            "io_dir": str(self.io_dir),
            "events_dir": str(self.events_dir),
            "logs_dir": str(self.logs_dir),
            "state_file": str(self.state_file),
            "handoff_file": str(self.handoff_file),
            "allowed_interpreters": ",".join(
                sorted(str(a) for a in self.allowed_interpreters)),
        }
