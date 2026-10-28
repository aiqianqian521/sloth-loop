# ADR-008: Circuit breaker HALF_OPEN probe-recovery (P1.2 W1-CB-01 Slice 2)

- Status: Accepted (extends W1-CB-01 Slice 1)
- Date: 2026-08-31
- Branch: codex/w0-w2
- N Commit: 9c8a13a feat(circuit): P1.2 W1-CB-01 slice 2 (+ swarm-fold)
- Annotated tag: p1.2-w1cb-half-open-probe

## Context
W1-CB-01 Slice 1 added the on_transition outbound port so breaker transitions are audited to a
run-level EventLog after each checkpoint (circuit_state.py stage->save_checkpoint->flush); the
breaker state (CLOSED/OPEN/HALF_OPEN) is restored across restart. Slice 1 did not implement HALF_OPEN
probe *recovery*: record_success (circuit_breaker.py:103-112) closed the breaker unconditionally on
any single success; a crash-during-OPEN had no explicit fail-closed guard beyond state-restore. The
roadmap (sloth-loop剩余开发计划-2026-08-30.md section 1, P1.2) required: HALF_OPEN probe-success N times ->
CLOSED (currently unconditional); crash-during-OPEN fail-closed (must not transit to CLOSED before
probing); the probe-count persists across restart; N-1/N boundary tests; the guard stays a pure
decision (the on_transition port is the only I/O seam).

## Architect-skill analysis
CircuitBreaker is a deep module (small public interface: allow_request/record_success/
record_failure/snapshot/restore; I/O only via the injected on_transition port, bound at the
composition root). The change is a port-adapter + composition-root hardening, not a god-file or
paradigm split. record_success is the probe-recovery decision; under the port-adapter rule its
decision path stays I/O-free (the port _notify wraps the sink defensively ->
production-decision-unchanged). The new probe_success_threshold is a composition-root dependency
(wired at orchestrator.py:176-180 from config, defaulted to 1) so an unconfigured deployment
preserves the legacy single-probe close. The persistence crosses the existing W1-RESUME-01 path:
_checkpoint_payload (circuit_state.py:90) already stores self.circuit.snapshot(), so adding the 2
keys to snapshot()/restore() makes the probe count durable across the run-loop checkpoint with no
new flush-ordering change.

## Swarm evaluation (read-only red team, codebase = sloth-loop; baseline via `git show HEAD`)
Three lenses were launched (data/contract=Archimedes, test/red-team=Bacon, design/review=Halley)
reading the HEAD=18f1038 baseline via `git show` to avoid working-tree races with the in-progress
patch. All three reached a final status.

- design/review (Halley): completed; the verdict text did not surface via wait_agent (returned
  `completed:null`). Its focal concerns were closed by authoritative self-evidence + the other two
  lenses (port-adapter purity: record_success/record_failure/allow_request perform no I/O, the
  HALF_OPEN->CLOSED-after-N path goes through _notify; composition-root DI: only orchestrator.py:176
  constructs the breaker, threshold wired from config default 1; W1-RESUME: the stage->save->flush
  ordering is unchanged, and a crash mid-probe restores the partial count and does not falsely close
  -- proven by test_probe_count_persists_across_restart).

- test/red-team (Bacon): CONDITIONAL PASS, medium①. Confirmed the exactly-one breaking test
  (tests/test_circuit_breaker.py::test_orchestrator_flush_writes_one_and_is_replay_safe, breaking
  record_success-on-OPEN at L152 / assert L157) and rewrote it in-slice; confirmed "production never
  calls record_success on OPEN" (sole prod caller loop_controller.py:27, reached only via
  run_loop.py:202, gated by allow_round->allow_request at run_loop.py:135; --once/run_once_pipeline/
  doctor/status/review/reset/mcp-server are breaker-free). Found a masked BUG (M5) and 4 verification
  end-step gaps (M1/M2/M4).
  * M5 (folded): the close event recorded consecutive_probe_success == 0 because the counter reset ran
    BEFORE _notify. Fix: move the reset to AFTER _notify (record_success HALF_OPEN close branch), so the
    close event records the N that closed. Verified by test_close_event_records_probe_success_count.
  * M1 (folded): unmasked the threshold-restore -- cb2 is now constructed at a DIFFERENT threshold (5) so
    the snapshot's threshold (3) must be adopted; strengthened probe-failure to the N-1 boundary (M2).
  * M4 (folded): added threshold default/clamp tests + orchestrator config-knob wiring +
    default-is-one tests.

- data/contract (Archimedes): CONDITIONAL+PASS, medium①. Q2/Q3/Q4 PASS (persistence round-trip via
  _checkpoint_payload -> payload opaque JSON; no exact-dict snapshot == assertions; sole prod
  record_success caller is production-inert). Q1 CONDITIONAL: the restore intent was correct but the
  AC suite omitted the backward-compat end-step (restoring a pre-Slice-2 7-key snapshot, which
  run_loop.py:62-65 reaches on every resume of an in-flight pre-Slice-2 run and which
  check_compatibility does NOT refuse since no payload-shape schema is bumped). The CODE already uses
  the pinned defensive form (snapshot.get("probe_success_threshold", self.probe_success_threshold)
  clamped >=1; snapshot.get("consecutive_probe_success", 0)). Q1 (folded): added
  test_restore_pre_slice2_snapshot_missing_new_keys_is_safe (restore 7-key snapshot -> state HALF_OPEN,
  counter 0, threshold inherited=N, 1 success stays HALF_OPEN). Q2 sub-note (folded): the flush event
  carries the populated counter (asserted in the updated flush test; enabled by adding
  consecutive_probe_success to _notify's info dict).

## Decision
Apply the probe-recovery hardening to the pure breaker state machine (no new file):
1. circuit_breaker.py: add probe_success_threshold (default 1) + consecutive_probe_success (default
   0). record_success in HALF_OPEN increments the counter and closes only at threshold via _notify
   (the counter reset runs AFTER _notify so the close event records N; intermediate HALF_OPEN->HALF_OPEN
   emits nothing, old==new); record_success on OPEN stays OPEN (fail-closed); record_success on CLOSED
   resets counters (idle). record_failure resets consecutive_probe_success to 0. snapshot()/restore()
   persist both new keys with the defensive `.get(key, default)` form (counter default 0; threshold
   fallback = the constructed value clamped >=1) so an old pre-Slice-2 7-key snapshot restores safely.
2. orchestrator.py:176-180 composition root: wire
   probe_success_threshold=int(loop.get("circuit_probe_success_threshold", 1)).
3. circuit_state.py _flush: add "consecutive_probe_success" to the circuit/transition audit event
   (populated from _notify's info dict); the stage->save->flush ordering is unchanged.
4. tests/test_circuit_breaker.py: update test_orchestrator_flush_writes_one_and_is_replay_safe to the
   probe path (OPEN fail-closed -> allow_request -> HALF_OPEN -> record_success N=1 -> CLOSED; asserts
   the flush event carries consecutive_probe_success=1); +9 new tests covering the N-1 boundary,
   probe-failure-resets-counter, persistence-across-restart (incl. unmasked threshold-restore),
   OPEN fail-closed, close-event-records-N, threshold default/clamp, orchestrator config-knob wiring,
   default-is-one, and pre-Slice-2 7-key-snapshot backward-compat.

## Consequences
- record_success/record_failure semantics: HALF_OPEN now needs N consecutive probe successes
  (configurable via circuit_probe_success_threshold, default 1 -- legacy preserved) to close; a
  bare success on OPEN is fail-closed (stays OPEN until allow_request admits a probe after cooldown);
  any failure resets the N-counter. The on_transition port still fires exactly once per real edge;
  intermediate HALF_OPEN successes emit nothing; the close event records the N that closed.
- Backward-compat: old (pre-Slice-2) snapshots restore safely (counter 0, threshold inherited from
  the constructed value). The round-trip through the run-loop checkpoint (W1-RESUME-01) carries the
  partial probe count, so resume after a crash mid-probe does not falsely close.
- Gate: 364 passed + 1 W1-STORE flake (xpassed, strict=False), coverage 70.43% (monotonic up from
  70.21% baseline; circuit_breaker.py 97%, circuit_state.py 91%). ratchet ok (fail_under=64, HEAD
  coverage floor preserved). Each commit GREEN; final feat = 9c8a13a.

## Alternatives considered
- Leave record_success unconditional and add a probe-success counter only at the loop_controller
  layer (do not touch the pure state machine). Rejected: the breaker is the safety primitive; the
  half-open recovery decision belongs IN the state machine (testable, I/O-free, single source),
  not in the run-loop glue.
- Gate the close on a real wall-clock "N successes within a window" rather than a pure monotonic
  counter. Rejected (YAGNI): no window requirement in the roadmap; a pure monotonic counter +
  reset-on-failure is the minimal correct semantics and it persists trivially.

## Follow-ups (not blocking)
- mcp-server/tools.py subprocess sink hardening (critical②) remains a P4 prerequisite; untouched here.
- EventLog fsync/atomic-write (critical③ potential) untouched here.
- P2.3 HookPipeline 4th-level ask (next phase per roadmap section 3) needs a GuardPort seam (not
  left by P2.1/P2.2); create it as part of the P2.3 slice.
