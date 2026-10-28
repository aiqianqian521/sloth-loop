"""W1-CB-01 Slice 1: CircuitBreaker on_transition port + orchestrator flush.

Guards decided by the architect-skills swarm (lenses: test/data/design/review):

* the outbound port fires exactly once per real transition edge, including the
  stealth OPEN->HALF_OPEN side-effect inside allow_request (F-A1);
* record_success CLOSED->CLOSED is suppressed, no audit noise (F-A4);
* the port is never serialised into snapshot(), and restore() is silent, the
  W1-RESUME-01 resume-idempotency seam (F-A3);
* a callback that raises never escapes into the safety-decision path
  (F-A2 / production-decision-unchanged);
* the orchestrator binds the port, stages a transition as a pending slot, and
  flushes it to a run-level EventLog exactly once after a checkpoint; the
  re-flush is a no-op and restore stages nothing -> no duplicate, no replay.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from circuit_breaker import CircuitBreaker  # noqa: E402


def _ported(seen):
    return CircuitBreaker(failure_threshold=2, cooldown_seconds=0.0,
                          on_transition=lambda o, n, i: seen.append((o, n, i["trigger"])))


def test_port_fires_once_per_edge_including_stealth():
    seen = []
    cb = _ported(seen)
    cb.record_failure(now=0.0)
    assert seen == [], "CLOSED->CLOSED suppressed"
    cb.record_failure(now=1.0)
    assert seen == [("CLOSED", "OPEN", "record_failure")], "threshold -> OPEN"
    cb.allow_request(now=2.0)
    assert seen == [("CLOSED", "OPEN", "record_failure"),
                    ("OPEN", "HALF_OPEN", "allow_request")], "stealth captured at source"
    cb.record_failure(now=3.0)
    assert seen[-1] == ("HALF_OPEN", "OPEN", "record_failure"), "probe failure re-opens"


def test_record_success_noise_suppressed():
    seen = []
    cb = _ported(seen)
    cb.record_failure(now=0.0)
    cb.record_failure(now=1.0)
    cb.allow_request(now=2.0)
    cb.record_success()
    assert seen[-1] == ("HALF_OPEN", "CLOSED", "record_success")
    cb.record_success()
    assert len(seen) == 3, "CLOSED->CLOSED must not spam the audit"


def test_snapshot_excludes_port_and_restore_is_silent():
    seen = []
    cb = _ported(seen)
    cb.record_failure(now=0.0)
    cb.record_failure(now=1.0)
    snap = cb.snapshot()
    assert "on_transition" not in snap, "port never serialised (F-A3 guardrail)"
    json.dumps(snap)  # payload serialisable without the callable
    seen.clear()
    cb.restore(snap)
    assert seen == [], "restore must not fire the port"
    assert cb.state == "OPEN"


def test_callback_exception_does_not_break_decision_path():
    def boom(o, n, i):
        raise IOError("disk full")
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.0, on_transition=boom)
    assert cb.record_failure(now=0.0) == "CLOSED"
    assert cb.record_failure(now=1.0) == "OPEN", "boom swallowed, decision unchanged"
    assert cb.allow_request(now=2.0) is True
    assert cb.record_failure(now=3.0) == "OPEN"
    assert cb.snapshot()["state"] == "OPEN"


def test_no_port_means_silent():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.0)
    cb.record_failure(now=0.0)
    cb.record_failure(now=1.0)
    assert cb.state == "OPEN"


def _tiny_cfg(td):
    from config_util import deep_merge, DEFAULT_CONFIG  # noqa: E402
    db = Path(td) / "p.db"
    sig = Path(td) / "signals.json"
    sig.write_text(json.dumps(
        [{"signal_pattern": "fail-me-please", "market_condition": "m"}]),
        encoding="utf-8")
    return deep_merge(DEFAULT_CONFIG, {
        "runtime": {"root": str(td), "db": str(db)},
        "memory": {"sqlite_path": str(db)},
        "loop": {"max_rounds": 1, "no_progress_stop": 3,
                 "meta_analyze_every": 100, "batch_size": 0, "max_seconds": 0,
                 "signals": str(sig)},
        "backtest": {"script": "backtest/does_not_exist.py", "extra_args": ""},
    })


def _log_lines(path):
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_orchestrator_flush_writes_one_and_is_replay_safe(tmp_path):
    from orchestrator import Orchestrator  # noqa: E402
    from event_log import EventLog  # noqa: E402

    o = Orchestrator(_tiny_cfg(str(tmp_path)))
    o._run_id = "cb-test-run"
    log_path = Path(str(tmp_path)) / ("circuit-" + o._run_id + ".jsonl")
    o._breaker_log = EventLog(log_path, task_name="cb-test")
    o._pending_circuit_transition = None

    assert o.circuit.on_transition is not None, "port bound at composition root"
    assert callable(o.circuit.on_transition)

    o.circuit.failure_threshold = 1
    o.circuit.record_failure(now=0.0)              # port -> stage slot
    assert o._pending_circuit_transition is not None

    o._flush_circuit_transition(1)                  # after-checkpoint flush writes once
    assert o._pending_circuit_transition is None
    rows = [json.loads(ln) for ln in _log_lines(log_path)]
    assert len(rows) == 1
    ev = rows[0]
    assert ev["step"] == "circuit"
    assert ev["status"] == "PASS"
    assert ev["round"] == 1
    assert ev["data"]["_type"] == "circuit/transition"
    assert (ev["data"]["state_from"], ev["data"]["state_to"], ev["data"]["trigger"]) == (
        "CLOSED", "OPEN", "record_failure")

    o._flush_circuit_transition(1)                  # idempotent: no pending -> no-op
    assert len(_log_lines(log_path)) == 1

    snap = o.circuit.snapshot()
    assert "on_transition" not in snap
    o.circuit.restore(snap)                          # the resume seam; must not stage
    o._flush_circuit_transition(1)
    assert len(_log_lines(log_path)) == 1, "restore must not replay a transition"

    # W1-CB-01 Slice 2: a bare record_success on an OPEN breaker is fail-closed
    # -- it must NOT stage a transition (must admit a probe first).
    o.circuit.record_success()
    o._flush_circuit_transition(2)
    assert len(_log_lines(log_path)) == 1, "OPEN record_success must not fire"

    # Open the probe path (instant cooldown): OPEN -> HALF_OPEN -> CLOSED (N=1).
    o.circuit.cooldown_seconds = 0.0
    assert o.circuit.allow_request() is True         # OPEN -> HALF_OPEN -> stage
    o._flush_circuit_transition(3)
    assert o.circuit.record_success() == "CLOSED"    # HALF_OPEN -> CLOSED -> stage
    o._flush_circuit_transition(4)
    rows = [json.loads(ln) for ln in _log_lines(log_path)]
    assert len(rows) == 3
    assert (rows[2]["data"]["state_from"], rows[2]["data"]["state_to"],
            rows[2]["data"]["trigger"]) == ("HALF_OPEN", "CLOSED", "record_success")
    assert rows[2]["data"]["consecutive_probe_success"] == 1  # flush records the N that closed (not 0/None)



def _half_open(threshold, seen):
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0,
                        probe_success_threshold=threshold,
                        on_transition=lambda o, n, i: seen.append((o, n, i["trigger"])))
    cb.record_failure(now=0.0)
    assert cb.state == "OPEN"
    cb.allow_request(now=1.0)
    assert cb.state == "HALF_OPEN"
    return cb


def test_half_open_requires_n_probe_successes():
    seen = []
    cb = _half_open(3, seen)
    seen.clear()
    assert cb.record_success() == "HALF_OPEN"      # counter=1
    assert cb.consecutive_probe_success == 1
    cb.allow_request(now=2.0)
    assert cb.record_success() == "HALF_OPEN"      # counter=2 (N-1 boundary)
    assert cb.state == "HALF_OPEN"
    assert seen == [], "intermediate HALF_OPEN probe successes emit no edge"
    cb.allow_request(now=3.0)
    assert cb.record_success() == "CLOSED"         # counter=3 (N) -> close
    assert seen == [("HALF_OPEN", "CLOSED", "record_success")]


def test_probe_failure_resets_counter():
    cb = _half_open(3, [])
    cb.record_success()                              # counter=1
    cb.allow_request(now=2.0)
    cb.record_success()                              # counter=2 (N-1 boundary)
    assert cb.state == "HALF_OPEN"
    cb.allow_request(now=3.0)
    assert cb.record_failure(now=4.0) == "OPEN"     # probe failure at N-1 boundary re-opens
    assert cb.consecutive_probe_success == 0          # counter reset to 0
    cb.allow_request(now=5.0)
    assert cb.state == "HALF_OPEN"
    assert cb.record_success() == "HALF_OPEN"        # recovery restarts at counter=1
    cb.allow_request(now=6.0)
    assert cb.record_success() == "HALF_OPEN"        # counter=2 (not close)
    cb.allow_request(now=7.0)
    assert cb.record_success() == "CLOSED"           # counter=3 -> full N restart to close


def test_probe_count_persists_across_restart():
    cb = _half_open(3, [])
    cb.record_success()                              # counter=1
    cb.allow_request(now=2.0)
    cb.record_success()                              # counter=2 (N-1)
    assert cb.state == "HALF_OPEN"
    snap = cb.snapshot()
    assert snap["consecutive_probe_success"] == 2
    assert snap["probe_success_threshold"] == 3
    assert "on_transition" not in snap
    cb2 = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0,
                         probe_success_threshold=5)
    cb2.restore(snap)
    assert (cb2.state, cb2.consecutive_probe_success) == ("HALF_OPEN", 2)
    assert cb2.probe_success_threshold == 3, "restore must adopt the snapshot threshold (unmasked)"
    cb2.allow_request(now=3.0)
    assert cb2.record_success() == "CLOSED"          # counter=3 >= restored 3 (not constructed 5)


def test_record_success_on_open_is_fail_closed():
    seen = []
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0,
                        on_transition=lambda o, n, i: seen.append((o, n, i["trigger"])))
    cb.record_failure(now=0.0)                       # CLOSED -> OPEN
    assert cb.state == "OPEN"
    assert cb.record_success() == "OPEN"             # fail-closed: stays OPEN
    assert cb.state == "OPEN"
    assert seen == [("CLOSED", "OPEN", "record_failure")], \
        "OPEN record_success emits no transition"
    assert cb.allow_request(now=1.0) is False        # within cooldown: fail-closed
    assert cb.state == "OPEN"
    cb.cooldown_seconds = 0.0
    assert cb.allow_request(now=2.0) is True         # OPEN -> HALF_OPEN
    assert cb.record_success() == "CLOSED"          # HALF_OPEN -> CLOSED (N=1 default)



def test_close_event_records_probe_success_count():
    seen = []
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0,
                        probe_success_threshold=3,
                        on_transition=lambda o, n, i: seen.append((o, n, i["trigger"], i["consecutive_probe_success"])))
    cb.record_failure(now=0.0)
    cb.allow_request(now=1.0)
    cb.record_success(); cb.allow_request(now=2.0)
    cb.record_success(); cb.allow_request(now=3.0)
    cb.record_success()                              # close at N=3
    close = [e for e in seen if e[1] == "CLOSED"]
    assert len(close) == 1
    assert close[0][3] == 3, "close event must record the N that closed (not the post-reset 0)"
    assert cb.consecutive_probe_success == 0          # reset after the event


def test_probe_success_threshold_default_and_clamp():
    assert CircuitBreaker(probe_success_threshold=0).probe_success_threshold == 1
    assert CircuitBreaker(probe_success_threshold=-5).probe_success_threshold == 1
    assert CircuitBreaker().probe_success_threshold == 1
    assert CircuitBreaker(probe_success_threshold=4).consecutive_probe_success == 0


def test_orchestrator_wires_probe_success_threshold_from_config(tmp_path):
    cfg = _tiny_cfg(str(tmp_path))
    cfg["loop"]["circuit_probe_success_threshold"] = 3
    from orchestrator import Orchestrator  # noqa: E402
    o = Orchestrator(cfg)
    assert o.circuit.probe_success_threshold == 3, "composition-root wires config.circuit_probe_success_threshold"


def test_orchestrator_probe_success_threshold_default_is_one(tmp_path):
    from orchestrator import Orchestrator  # noqa: E402
    o = Orchestrator(_tiny_cfg(str(tmp_path)))
    assert o.circuit.probe_success_threshold == 1, "default (no knob) preserves the legacy single-probe close"



def test_restore_pre_slice2_snapshot_missing_new_keys_is_safe():
    # A pre-Slice-2 checkpoint writes a 7-key breaker snapshot with NEITHER new
    # key. Resuming that run on new code (run_loop.py:62-65 restores the breaker
    # on every resume) must restore safely (no crash, no false close) and inherit
    # the constructed threshold, then require the full N probe sequence.
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.0,
                        probe_success_threshold=3)
    old_snap = {
        "state": "HALF_OPEN",
        "consecutive_failures": 2,
        "failure_threshold": 2,
        "cooldown_seconds": 60.0,
        "opened_at": 0.0,
        "opened_at_wall": 0.0,
        "probe_in_flight": False,
    }
    cb.restore(old_snap)
    assert cb.state == "HALF_OPEN"
    assert cb.consecutive_probe_success == 0, "missing new key -> default 0 (no false close)"
    assert cb.probe_success_threshold == 3, "missing new key inherits the constructed threshold"
    cb.allow_request(now=1.0)
    assert cb.record_success() == "HALF_OPEN"   # counter=1 of N=3 -> stays HALF_OPEN
    assert cb.consecutive_probe_success == 1
