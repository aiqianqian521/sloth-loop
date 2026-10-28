# ADR-007: Orchestrator run/CLI split (P2.2) - extract run_once + run to mixins and delete dead _legacy_main

- Status: Accepted (extends ADR-006)
- Date: 2026-08-31
- Branch: codex/w0-w2
- Commits: E1 388f172, E2 bf1b0f2, E3 8318000
- Annotated tag: p2.2-orchestrator-run-cli-split

## Context
ADR-006 split the orchestrator god-class by responsibility (project_loader / circuit_state / l2_meta / run_state mixins, P2.1; orchestrator.py 2158 -> 1468). The file remained above the 800-line single-file structural-health baseline, dominated by two large run-loop methods - run_once (single-round OODA 7-step pipeline + W1-RESUME step-level checkpoint/resume, 372 lines) and run (continuous-round controller, 223 lines) - and a dead _legacy_main argparse duplicate (98 lines, 0 callers; the live CLI already delegates to cli_router.CliRouter).

## Architect-skill analysis
Single file > 800 lines = god-file (architect-skill baseline). The two run methods are a state-machine-step axis (paradigm 2): each step (run once / run loop) is an independent handler; the orchestrator should only hold the composition root + class composition. Paradigm 1 (responsibility) was applied in P2.1 for the helper mixins; P2.2 applies paradigm 2 to the remaining pipeline body.

## Swarm evaluation (read-only red team, codebase = sloth-loop)
- Gibbs (data/contract) F1/F2: the proposal's E1/E2 import lists were INCOMPLETE - run_once additionally uses EVT_ACT_RESULT, build_context_snapshot, date, _STEP_INDEX; run additionally uses time, date, check_compatibility, compute_pool_hash, pool_matches, _STEP_INDEX. _STEP_INDEX/_STEP_ORDER are module globals (not importable back from orchestrator without a cycle) -> copied verbatim into each mixin module (C2 circuit_state precedent) under an equality smoke. F3 MRO: no collision/shadow across the 6 mixins; retention contracts for _run_once_legacy and _safe_run_component (staticmethod). F4: no domain->infra reverse edge (backtest hits are string/dict keys only).
- Sartre (red-team/test): F1 two mixins not one (run calls run_once once; shared helpers already in CircuitState/RunState). F2 build_orchestrator constructs Orchestrator at runtime and coheses with module-locals _HERE/PROJECT_ROOT/DEFAULT_CONFIG/HAS_YAML -> STAYS in orchestrator (Option a); main() already DI-injects into CliRouter. F3 the live parser is CliRouter.build_parser() (cli_router.py:45 registers --min-win-rate); _legacy_main is dead (0 callers) with a stale duplicate parser; deleting it + retargeting test_cli_min_win_rate_flag to CliRouter is smaller and safer than migrating argparse into main() or creating cli_main.py. F4 no decorators on run_once/run; logger = getLogger("sloth_engine"); _HERE bootstrap replicated. F5 deleting _legacy_main alone reaches 758-781 < 800 - build_orchestrator and _show_history need NOT move.
- Aristotle (Euclid/read-only): F1 confirmed verbatim migration has zero residual risk on closure binding / time singleton / adjacent save_checkpoint->flush order; F2 deferred test-adds for the run() else-branch round_start/round_end recovery and a --resume subprocess e2e (backlog, not blocking); F3/F5 confirmed the _legacy_main text-scan test is brittle and the most-likely E1 RED is an import omission (avoided by the Gibbs-closed import sets). (Aristotle's reported line numbers drift +5..+11 vs physical; implementation anchored on AST and printed source, not on its line numbers.)

## Decision
Apply paradigm 2 (state-machine-step split) - extract the two run-loop steps into peer mixins verbatim, then remove the dead CLI duplicate.

1. E1 - run_once -> sloth_engine/run_once_pipeline.py::RunOnceMixin (verbatim). Bare-name lookups (time/date, StatusBar, EventLog, OODASteps, RoundContext, step_start_event/step_end_event, EVT_*, build_context_snapshot, _log, _STEP_INDEX) resolve against the mixin module globals; _STEP_ORDER/_STEP_INDEX are verbatim local copies (C2 circuit_state precedent) equal-by-value under an equality smoke. Import set closed via the Gibbs AST audit.
2. E2 - run -> sloth_engine/run_loop.py::RunLoopMixin (verbatim). Bare names (time, date, EventLog, RoundContext, check_compatibility, compute_pool_hash, pool_matches, _log, _STEP_INDEX) resolve against mixin globals; import set closed via Gibbs F2. run calls self.run_once exactly once (one-directional coupling); shared helpers live in CircuitState/RunState (no mixin-to-mixin body dependency).
3. E3 - delete dead _legacy_main (0 callers verified across orchestrator/, tests/, scripts/, sloth_engine/); the live main() already delegates to CliRouter (cli_router.py build_parser registers --min-win-rate at L45). Retarget tests/test_loop_new.py::test_cli_min_win_rate_flag from a text-scan of orchestrator.__file__ (brittle existence check satisfied only by the dead duplicate) to a behavioral assertion on CliRouter.build_parser()._actions.

class Orchestrator(ProjectLoader, CircuitState, L2Meta, RunState, RunOnceMixin, RunLoopMixin) - no MRO collision (each mixin owns disjoint method names); _run_once_legacy and _safe_run_component (staticmethod) retention contracts preserved.

### Circular-import verdict (design fork)
build_orchestrator constructs Orchestrator at runtime (return Orchestrator(...)), not merely in an annotation, and is cohesive with orchestrator module-locals (_HERE, PROJECT_ROOT, DEFAULT_CONFIG, HAS_YAML, _log); main() already injects it into CliRouter via DI. Relocating it would create a needless bidirectional cycle and expose >=4 module-locals to a new module. Decision (Sartre F2): build_orchestrator STAYS in orchestrator.py (Option a). _show_history is Orchestrator-free (sqlite3/PROJECT_ROOT/_log only) and is already DI-injected, but was NOT moved - not STOP-driving (Sartre F5: deleting _legacy_main alone reaches 758-781 < 800).

## Consequences
- orchestrator.py 1468 -> 781 lines (< 800 god-file baseline; class 555 < 1500 god-class baseline). Module-level surface: Orchestrator, build_orchestrator, _show_history, main.
- Mixin composition (final, lines): ProjectLoader(235) - CircuitState(177) - L2Meta(34) - RunState(350) - RunOnceMixin(418, run_once) - RunLoopMixin(257, run). Orchestrator retains __init__(143) / _run_once_legacy(48) / run_parallel(32) / _safe_run_component(15, staticmethod) / doctor(99) / status(100) / review(59) / reset(10).
- Each slice committed independently GREEN: 355 passed + 1 W1-STORE flake (strict=False), coverage 68.92 -> 68.98 -> 70.21% (monotonic; dead-code removal raised it), ratchet ok (fail_under=64 HEAD=64), probes pass. Verbatim extraction preserved closure binding, the adjacent save_checkpoint -> _flush round_start/round_end order (Aristotle F1), and the _save_step step-checkpoint semantics.
- Test retarget converted a brittle text-scan into a behavior assertion on the live parser; --min-win-rate behavior is additionally covered by test_review_min_win_rate.

## Alternatives considered
- Merge run_once + run into one RunPipeline mixin - rejected (Sartre F1): two distinct change-axes (round-internal OODA vs loop/stop policy); a ~611-line mixin would recreate a god-mixin.
- Relocate build_orchestrator / _show_history to a new cli_main.py - rejected (Sartre F2/F5): circular-import risk; not STOP-driving.
- Migrate argparse into main() - rejected (Sartre F3): main already delegates to CliRouter; _legacy_main's parser was a stale duplicate.

## Follow-ups (not blocking)
- Aristotle F2: add a direct test for run() recovery from a pure round_start/round_end checkpoint (else-branch total_rounds); add an orchestrator.py --resume subprocess end-to-end.
- Cosmetic: E1 commit subject carries a \ufeff BOM (stdin-pipe artifact); left un-remediated (rebase risk outweighs cosmetic benefit on a local unpushed branch).
