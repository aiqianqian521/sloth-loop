"""Strict input-signal schema validation for the Loop orchestrator.

Opt-in, fail-closed validator that rejects malformed candidate signals with a
stable error_code instead of silently dropping them. It validates:

- core fields: ``signal_pattern`` (required, non-empty str), ``market_condition``
  (optional str, defaults to ``"unknown"``)
- task-specific schema from ``task.signal_schema`` (optional): {field: {required,
  type, default}}
- ``success_criteria`` metric consistency: every metric referenced by the task
  must be present on the signal, or belong to a known wrapper-output metric set
  (trades_count / win_rate / sharpe / pnl / signals_tested / total_pnl). Metrics missing from both are
  reported (error when strict, warn otherwise).

Use: ``validate_signals(signals, task_cfg, strict=False) -> dict``
Returns ``{"valid": bool, "accepted": [...], "rejected": [{index, code, reason}],
"warnings": [...]}``. Zero dependencies.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

log = logging.getLogger("sloth_engine.signal-schema")

# metrics the wrapper may compute (verifier.py + task_runner.py actually emit:
# trades_count / win_rate / sharpe / pnl / signals_tested / total_pnl).
# ``filtered_count`` is a ghost the wrapper never produces -> removed so strict
# criteria on real output fields are not mis-rejected.
WRAPPER_METRICS = {
    "trades_count", "win_rate", "sharpe", "pnl",
    "signals_tested", "total_pnl",
}


def _field_value(field_spec: dict, value: Any):
    """Return normalized value or None if invalid (by type)."""
    ftype = field_spec.get("type", "string")
    if value is None:
        return field_spec.get("default")
    if ftype == "string":
        if isinstance(value, str):
            return value
        # coerce numbers to string is not allowed (strict)
        return None
    if ftype == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        return None
    if ftype == "bool":
        if isinstance(value, bool):
            return value
        return None
    return value


def validate_signals(signals: Iterable, task_cfg: dict | None = None,
                     strict: bool = False) -> dict:
    """Validate a candidate signal list against core + task schema.

    strict=False: malformed entries are reported as errors but still dropped
    (current lenient-by-default is preserved); accepted list excludes them.
    strict=True: any error marks ``valid=False`` (caller may fail the round).
    """
    task_cfg = task_cfg or {}
    schema = (task_cfg.get("signal_schema") or {}).get("fields", {})
    criteria = (task_cfg.get("success_criteria")
                or (task_cfg.get("task") or {}).get("success_criteria") or [])

    accepted: list[dict] = []
    rejected: list[dict] = []
    warnings: list[str] = []

    for index, signal in enumerate(list(signals or [])):
        issues: list[str] = []
        ok = True
        if not isinstance(signal, dict):
            rejected.append({"index": index, "code": "SIG_INVALID_TYPE",
                             "reason": "signal not a JSON object"})
            continue
        item = dict(signal)
        # core: signal_pattern
        sp = item.get("signal_pattern")
        if sp is None:
            ok = False
            issues.append("missing signal_pattern")
        elif not isinstance(sp, str) or not sp.strip():
            ok = False
            issues.append("signal_pattern must be non-empty string")
        elif not isinstance(sp, str):
            ok = False
            issues.append("signal_pattern must be string")
        # core: market_condition
        mc = item.get("market_condition")
        if mc is None:
            item["market_condition"] = "unknown"
        elif not isinstance(mc, str):
            ok = False
            issues.append("market_condition must be string")
        # task schema fields
        for field, spec in (schema or {}).items():
            req = bool(spec.get("required", False))
            has = field in item
            val = _field_value(spec, item.get(field) if has else None)
            if val is None and (req or has):
                ok = False
                issues.append(f"{field} invalid/missing (type={spec.get('type','string')})")
            elif has and val is not None:
                item[field] = val
        if not ok:
            rejected.append({"index": index, "code": "SIG_SCHEMA_FIELD",
                             "reason": "; ".join(issues)})
        else:
            accepted.append(item)

    # success_criteria metric consistency
    for criterion in (criteria or []):
        metric = (criterion or {}).get("metric")
        if not metric:
            continue
        if metric in WRAPPER_METRICS:
            continue  # wrapper-computed, cannot check at input time
        on_signal = all(metric in sig for sig in accepted)
        if not accepted:
            warnings.append(f"criteria.metric '{metric}': no accepted signals to check")
        elif not on_signal:
            msg = (f"criteria.metric '{metric}' absent from all accepted signals "
                   "and not a wrapper metric -> may fail silently")
            warnings.append(msg)
            if strict:
                rejected.append({"index": "all", "code": "SIG_CRITERIA_METRIC",
                                 "reason": msg})

    # strict: any rejected entry fails the whole batch (fail-closed).
    valid = (len(rejected) == 0) if strict else True
    return {
        "valid": valid,
        "accepted": accepted,
        "rejected": rejected,
        "warnings": warnings,
    }
