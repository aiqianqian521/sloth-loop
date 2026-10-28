# ADR-006: Orchestrator god-file split into per-responsibility mixins (P2.1 C1-C4)

- Status: Accepted (2026-08-30)
- Slice: P2.1 orchestrator refactor (slices C1-C4)
- Depends on: ADR-005 (local fail-closed gate, the green umbrella), ADR-002 (resume-idempotency seam), ADR-003 (result/contract boundary)
- Retires: the single-file Orchestrator god-class as the home for project-loading, circuit-state, L2-meta, and run-state behavior.

## Context
At the P2.1 entry point (commit 57d5bb4, after slices A/B1/D had already extracted
StatusBar/_Tee/_RunLock, OODASteps, and purged dead *_legacy code),
`sloth_engine/orchestrator.py` was 2158 lines with an `Orchestrator` class of
~1850 lines. The class fused five disjoint responsibilities: project/task
loading, circuit-breaker transition + checkpoint state machine, L2 meta-analysis
delegation, run-state/reporting, and the OODA run-loop driver. The proposal
(orchestrator-split-proposal.md) graded this a god-file; the architect-skills
swarm folded 12 corrections into the plan (mixin not pure-function, _legacy_main
exception, decorator handling, _STEP_INDEX duplication to stay cycle-free,
monkeypatch-seam preservation). This ADR records the executed split, the
contract decisions, and the deferred follow-ups.

## Decision
Split the Orchestrator class into **mixin** bases (NOT pure-function modules),
one per responsibility, verbatim-moving method bodies so `self.*` instance
attributes and monkeypatch seams stay intact. Each slice is its own GREEN commit
under the ADR-005 gate (in-memory `compile()` before any write; byte-level utf-8
preservation of the original Chinese comments).

Final composition (sloth_engine/orchestrator.py):

    class Orchestrator(ProjectLoader, CircuitState, L2Meta, RunState): ...

Per-responsibility modules extracted in P2.1 C1-C4 (sloth_engine/):

| Slice | Commit  | Module            | Methods moved (verbatim)                                                              | Lines |
|-------|---------|-------------------|---------------------------------------------------------------------------------------|-------|
| C1    | a791688 | project_loader.py  | _interactive_confirm, generate_signals, _load_pool, _load_task_file, _load_project    | 235   |
| C2    | 823fc1d | circuit_state.py   | _stage_circuit_transition, _flush_circuit_transition, _checkpoint_payload, _check_contract_limits, _check_scope_violation, _all_criteria_met | 177   |
| C3    | 2537760 | l2_meta.py         | meta_analyze, _l2_auto_suggest, _l2_read_progress, _l2_check_triggers, _l2_health_check, _l2_verify_suggestions | 34    |
| C4    | 722af63 | run_state.py      | _write_state_md, _recover_state, _write_handoff, _read_handoff, _stop_diagnosis, _archive_run, _report_context, _next_steps, _check_scope, _produce_problems, _produce_defect_report, _classify_defect | 350   |

Contract decisions enforced each slice:

1. **Mixin over pure-function.** Self.* and signatures stay; methods are moved
   verbatim (same indent) into a `class X:` under the same sloth_engine path. This
   preserves the test seams: instance-attribute monkeypatch (test_circuit_breaker
   `o._breaker_log = EventLog(...)`), UI monkeypatch (test_v2_p1p2
   `Orchestrator._interactive_confirm`), and class-level non-idempotent-producer
   monkeypatch (test_resume_step `Orchestrator._produce_defect_report = crash_once`).
2. **self.* associates and wiring stay in Orchestrator.__init__/run().** The call
   sites that stage or flush behavior (the on_transition binding, the
   save_checkpoint-then-_flush ordering, the run-loop learn-phase calls) remain in
   orchestrator.py and resolve moved methods via MRO. Bindings such as
   `self.circuit.on_transition = self._stage_circuit_transition` keep working because
   the mixin base is accessed through Orchestrator.
3. **Decorator co-moving.** `_classify_defect` is `@staticmethod` (no `self`); its
   span is pulled up to include the decorator and moves as one unit. Keeps the
   binding-free static call (`self._classify_defect(sp, rc, fm)` stays 3-arg, no
   self-binding). Verified post-move: `isinstance(RunState.__dict__["_classify_defect"], staticmethod)` and the signature has 3 params, no self.
4. **Import-cycle-free mixin.** circuit_state duplicates the OODA 7-step
   `_STEP_INDEX` token table locally (a 7-entry tuple) rather than importing it
   from orchestrator, because orchestrator imports circuit_state. The tokens are
   protocol-stable (event_log step events); an equality smoke at import asserts
   the copy still matches orchestrator's.
5. **The swarm-flagged critical seams were verified post-move**, not asserted-only:
   `_classify_defect` staticmethod descriptor + 3-arg signature; class-level
   readability of `Orchestrator._produce_defect_report` for the monkeypatch read;
   MRO resolution of all 5 circuit and 6 l2 methods; mixin-bases order
   `[ProjectLoader, CircuitState, L2Meta, RunState]`.
6. **B2 deferred.** OODASteps self-calls (`_act_with_retry` -> `OODASteps._act`,
   `_verify_assertions` -> `OODASteps._run_callback`/`_resolve_field`) through the
   facade make a per-phase split of ooda_pipeline.py need a deferred-import seam;
   pure hygiene with a bounded 892-line ooda_pipeline, deferred to P2.2.
7. **Orphan section comments preserved.** Removed methods leave their
   `# -- section --` header comments behind as a conservative, contract-safe
   choice (no over-deletion); tidy is a follow-up, not part of P2.1.

## Consequences
- Positive: `orchestrator.py` 2158 -> 1468 lines; `Orchestrator` class
  1850 -> 1156 lines (well past the <1500 P2.1 STOP). The class now reads as the
  OODA run-loop driver composed of four thin single-responsibility mixin bases.
  Coverage rose monotonically 68.70% -> 68.77% -> 68.81% -> 68.83% -> 68.86%
  (D -> C1 -> C2 -> C3 -> C4). Every slice passed the gate (355 passed + the
  documented W1-STORE-01 xfail/xpass flake; strict=False; zero regressions). All
  monkeypatch seams preserved (test_v2_p1p2, test_circuit_breaker, test_resume_step,
  test_resume, test_resume_idempotency, test_runtime_containment).
- Negative / accepted: this is NOT the P2.2 <800 goal. orchestrator.py is 1468
  lines, class 1156. The remaining bulk is the OODA run-loop (`run_once`) and the
  CLI. B2 (ooda_pipeline per-phase split) is deferred. `_legacy_main` is retained
  (slice D) for the argparse source-contract probe that scans
  `orchestrator.__file__` for `--min-win-rate`; migrate argparse into a live
  `main()` then prune. The W1-STORE-01 sqlite "database is locked" flake under
  full-suite load remains xfailed per ADR-005; the transient C1 xpass blip was
  that flake passing under load, not a behavioral change caused by the split.
- Follow-up:
  (a) P2.2: orchestrator.py <800 ? extract `run_once` step-level checkpoint
      plumbing (critical?) as its own slice; move build_orchestrator/_show_history
      to cli_main.py (main argparse stays in orchestrator);
  (b) B2: refactor OODASteps self-calls to a shared dispatch then split into phase
      modules;
  (c) migrate `_legacy_main` argparse into a live main() so the dead block can be
      deleted;
  (d) tidy the orphan section comments left by the removed methods;
  (e) C5 optional tail: doctor/review/status -> orch_cli_cmds.py mixin
      (`run_parallel` stays in Orchestrator for the introspection probe; separate
      latent bug: `_ENGINE` undefined in `run_parallel` worker `_run_one` ->
      NameError swallowed per-window, not P2.1);
  (f) W1-STORE-01 concurrency robustness (ADR-005).
