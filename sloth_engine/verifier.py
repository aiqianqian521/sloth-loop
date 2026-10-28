"""Pure result verification boundary.

Verifier deliberately knows nothing about SQLite, subprocesses, or OODA
status bars.  It evaluates a normalized act-result mapping against business
criteria and returns a serializable report.
"""

from __future__ import annotations


class Verifier:
    @staticmethod
    def verify(act_result: dict, success_criteria: list[dict]) -> dict:
        criteria_results: list[dict] = []
        trades = act_result.get("trades", [])
        total_trades = len(trades)
        wins = sum(1 for trade in trades if trade.get("pnl", 0) > 0)
        win_rate = wins / total_trades if total_trades else 0

        for criterion in success_criteria:
            metric = criterion.get("metric", "")
            operator = criterion.get("operator", "gte")
            threshold = criterion.get("threshold", 0)
            actual = None
            if metric == "win_rate":
                actual = win_rate
            elif metric == "sharpe":
                actual = act_result.get("sharpe", 0)
            elif metric == "signals_tested":
                actual = act_result.get("signals_tested", 0)
            elif metric == "trades_count":
                actual = total_trades
            elif metric in (act_result.get("metrics") or {}):
                actual = act_result["metrics"][metric]
            elif isinstance(act_result.get("task_result"), dict):
                actual = (act_result["task_result"].get("metrics") or {}).get(metric)

            passed = Verifier._compare(actual, operator, threshold)
            criteria_results.append({"metric": metric, "threshold": threshold,
                                     "actual": actual, "operator": operator,
                                     "passed": passed})

        if act_result.get("status") == "error" and total_trades == 0:
            criteria_results.append({"metric": "execution", "threshold": "no_error",
                                     "actual": act_result.get("error", "unknown"),
                                     "operator": "eq", "passed": False,
                                     "note": "Backtest execution error"})

        return {
            "pass_count": sum(1 for item in criteria_results if item["passed"] is True),
            "fail_count": sum(1 for item in criteria_results if item["passed"] is False),
            "unknown": sum(1 for item in criteria_results if item["passed"] is None),
            "total": len(criteria_results),
            "details": criteria_results,
        }

    @staticmethod
    def _compare(actual, operator: str, threshold):
        if actual is None:
            return False
        # P1-FIX (D7): a non-numeric threshold used to raise an uncaught
        # TypeError (e.g. threshold: "abc"), aborting the run with a bare
        # stack trace.  Fail closed like any other bad criterion instead.
        _NUMERIC_OPS = ("gt", "lt", "gte", "lte")
        if operator in _NUMERIC_OPS and not isinstance(threshold, (int, float)):
            return False
        if operator in _NUMERIC_OPS and isinstance(threshold, bool):
            return False
        if operator == "gt":
            return actual > threshold
        if operator == "lt":
            return actual < threshold
        if operator == "gte":
            return actual >= threshold
        if operator == "lte":
            return actual <= threshold
        if operator == "eq":
            return actual == threshold
        # P0-FIX (D6): an unrecognized operator must fail closed, not return
        # None.  A None result was counted as "unknown" and never surfaced as a
        # failure, so a typo/invalid operator silently never blocked a run.
        return False

