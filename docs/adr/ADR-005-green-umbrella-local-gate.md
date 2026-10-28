# ADR-005: Local fail-closed pre-commit gate for the green umbrella (P3.2)

- Status: Accepted (2026-08-30)
- Slice: P3.2 GREEN umbrella (hard precondition for the P2.1 god-file split)
- Retires: the orphan lefthook `.git/hooks/prepare-commit-msg` shim (fail-open).

## Context
Before P3.2 the project had no enforced local gate: a stale lefthook
`prepare-commit-msg` shim fail-opened ("Can't find lefthook" -> exit 0), and
several test files used print-only `check()` that never raised under pytest
(false green). The handoff's "354/0" was not reproducible (one real load-flake
plus hidden false greens). P2.1 will refactor a god-file; it needs a trustworthy
regression umbrella first.

## Decision
Add `scripts/run_gate.py` as the single local pre-commit chokepoint, invoked by
`.git/hooks/pre-commit` (ASCII relative venv path `../loop/.venv/...`). Properties:

1. Path-scoped: runs only when staged changes touch `sloth_engine/`, `tests/`,
   `scripts/`, `pyproject.toml`, or `requirements-dev.txt` (docs-only skip).
2. Fail-closed on missing test deps: reject + print bootstrap, NEVER exit 0
   (anti the fail-open lefthook shim it replaces).
3. Ratchet: `fail_under` in pyproject must not drop below HEAD; measured
   coverage must meet the committed floor (enforced by pytest-cov addopts).
4. Pure precondition: never imports sloth_engine modules (orchestrator /
   memory_store / event_log / PatternStore); stays out of the checkpoint/write
   path.
5. Single source of truth: pytest + coverage config live only in `pyproject.toml`
   (bare `--cov` reads `[tool.coverage.run].source`); no pytest.ini / .coveragerc.

Delete the orphan lefthook `prepare-commit-msg` shim. Quarantine the
out-of-scope W1-STORE-01 load-flake via `@pytest.mark.xfail(strict=False,
run=True)` with a recorded follow-up, rather than weakening the assertion.

## Consequences
- Positive: bad commits (red tests, coverage below floor) are blocked locally;
  the green baseline is honest and ratcheted; P2.1 can refactor under the
  umbrella. Three falsifiable probes pass (failing assert -> rejected; coverage
  floor 100 -> rejected; --no-verify -> bypassed then reset --soft).
- Negative / accepted: this is NOT fail-closed CI. Three bypass surfaces remain
  and are documented: `--no-verify`, `core.hooksPath` override (a global aliyun
  hook wrapper is observed on this host), and fresh clones with no hooks. Real
  fail-closed requires pre-receive or hosted CI (deferred: no remote configured).
- Follow-up: (a) host a remote + pre-receive/CI to make it truly fail-closed;
  (b) W1-STORE-01 concurrency robustness (the xfailed test: database-is-locked
  under full-suite load; candidate root = per-connection `PRAGMA journal_mode=WAL`
  re-issue without busy_timeout, or 30s starvation);
  (c) ratchet-lowering probe re-test once HEAD carries `fail_under=64`;
  (d) P3.2 remainder: golden>=20 (P3.1), test_loop parametrize, threshold 70->80,
  conftest/pythonpath convergence.
