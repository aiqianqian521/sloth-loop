# Contributing to sloth-loop

Thanks for your interest!  sloth-loop is an **LLM-free orchestration engine**
— please keep that boundary intact in any change: no LLM SDKs, no credentials,
no network LLM calls inside the engine.

## Before you open a pull request

1. Read `README.md` (the three marks: intent / what it is / how it differs from
   an agent) and `CLAUDE.md` (the engineering rules of this repo).
2. Run the local gate — it must be green:

   ```
   .venv/Scripts/python -m pytest tests sloth_engine/tests -q
   .venv/Scripts/python scripts/run_gate.py
   ```

   The gate runs the full suite (currently **1760 passed / 0 xfailed /
   coverage 79.49%**, `fail_under=70`) plus the docs-baseline consistency
   check (`scripts/docs_baseline.py`) and the orphan-mechanism check.
3. Keep current-state docs (README, START.md, ROADMAP, AS-BUILT, QUICKSTART,
   USAGE, DEV-SETUP, GRAND-LOOP, sloth_engine/README, 项目介绍与规划)
   in sync with `docs/baseline.json` — the guard fails closed otherwise.
4. Don't leave scratch files in the tree: `scripts/tmp/` is the only legal
   scratch location (gitignored).

## Commit style

Cycle-based, prefixed messages, e.g. `test(cycle-43 A): ...`, `docs(cycle-43
C/D): ...`.  One logical change per commit; the design note goes under
`docs/design/`.

## Reuse and licensing

By contributing you agree your contribution is licensed under Apache-2.0.
The project name / marks are reserved — see `TRADEMARK.md`.
