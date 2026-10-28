"""OODASteps _learn mixin - H1-P2a ooda_pipeline godfile split (behavior-preserving).

_learn (@staticmethod) moved from ooda_pipeline.OODASteps to this mixin; OODASteps
inherits it. Deps: json, datetime.date, memory_store.PatternStore (classify_failure
static), adapters.task_runner.normalize_task_result (deferred import inside method).
"""
from __future__ import annotations

import json
from datetime import date

from memory_store import PatternStore


class OODAStepsLearn:

    @staticmethod
    def _learn(act_result: dict, verified: dict, store) -> dict:
        """[L] Learn — record losses as failures, wins as successes, errors too.

        Deduplication by composite key; IDs allocated by store.next_id.
        """
        new_failures, new_successes = [], []
        bumped_f = bumped_s = 0
        today = date.today().isoformat()
        trades = act_result.get("trades", []) or []
        bt = act_result.get("raw")

        # Phase 0: 通用路径 — 从 TaskResult.errors 提取（所有任务类型）
        task_result = act_result.get("task_result")
        if isinstance(task_result, dict):
            from adapters.task_runner import normalize_task_result
            provenance = task_result.get("provenance") or {}
            task_result = normalize_task_result(
                task_result,
                adapter=str(provenance.get("adapter") or "unknown"),
                entry=str(provenance.get("entry") or ""),
            )
        task_type = ((task_result.provenance or {}).get("task_type", "backtest")
                     if task_result else "backtest")
        verification_passed = (verified.get("pass_count", 0) > 0
                               and verified.get("fail_count", 0) == 0)

        if task_result and task_result.errors:
            for err in task_result.errors:
                sig = err.get("signature", "")
                existing = store.find_failure_by_signature(task_type, sig)
                if existing:
                    # 已知失败再次出现：累加计数
                    store.bump_failure(existing["id"])
                    bumped_f += 1
                    # Phase 0 验证：如果本轮验证通过，说明修复方案可能有效
                    if verification_passed and err.get("fix_recipe"):
                        store.bump_fix_confidence(existing["id"])
                    continue
                rec = {
                    "id": store.next_id("F"), "date": today,
                    "signal_pattern": err.get("signature", ""),
                    "market_condition": err.get("params_snapshot", {}).get("market_condition", "unknown") if isinstance(err.get("params_snapshot"), dict) else "unknown",
                    "failure_mode": "INSUFFICIENT_EVIDENCE",
                    "impact": {"trades": 1, "win_rate": "0%", "total_pnl": "0%"},
                    "root_cause": err.get("evidence", ""),
                    "solution": err.get("fix_recipe", "TBD"),
                    "verification": "verified" if verification_passed else "TBD",
                    "status": "open", "exclusion_rule": "",
                    "task_type": task_type,
                    "error_signature": sig,
                    "error_params": json.dumps(err.get("params_snapshot", {}), ensure_ascii=False),
                    "fix_recipe": err.get("fix_recipe", ""),
                    "fix_confidence": 0.1 if verification_passed else 0.0,
                }
                store.append_failure([rec])
                new_failures.append(rec)

        # Phase 0 后处理：fix_confidence 达标自动升级
        # Confidence is recorded for review only; status transitions require
        # an explicit human approval via ``--review``.

        # 旧路径: 从 trades 提取（保留兼容回测）
        for t in trades:
            pnl = t.get("pnl", 0) or 0
            sp = str(t.get("signal_pattern", "unknown"))
            mc = str(t.get("market_condition", "unknown"))
            if pnl < 0:
                mode = PatternStore.classify_failure(t)
                # 交叉检查: 同时查 sp+mc+mode 和 error_signature，
                # 防止 Path 1 (task_result.errors) 和 Path 2 (trades) 产生重复记录
                existing = store.find_failure(sp, mc, mode)
                if not existing:
                    existing = store.find_failure_by_signature("backtest", f"backtest_loss:{sp}")
                if existing:
                    store.bump_failure(existing["id"])
                    bumped_f += 1
                    if verification_passed:
                        store.bump_fix_confidence(existing["id"])
                    continue
                new_failures.append({
                    "id": store.next_id("F"), "date": today,
                    "signal_pattern": sp, "market_condition": mc,
                    "failure_mode": mode,
                    "impact": {"trades": 1, "win_rate": "0%",
                               "total_pnl": f"{pnl:.2f}%"},
                    "root_cause": t.get("failure_reason", "TBD"),
                    "solution": "TBD", "verification": "TBD",
                    "status": "open", "exclusion_rule": "",
                    "task_type": "backtest",
                    "error_signature": f"backtest_loss:{sp}",
                    "error_params": json.dumps({"signal_pattern": sp, "market_condition": mc, "pnl": pnl}),
                    "fix_recipe": f"排除模式: {t.get('failure_reason', 'TBD')}",
                    "fix_confidence": 0.3,
                })
                store.append_failure([new_failures[-1]])
            elif pnl > 0:
                existing = store.find_success(sp, mc)
                if existing:
                    store.bump_success(existing["id"])
                    bumped_s += 1
                    continue
                new_successes.append({
                    "id": store.next_id("S"), "date": today,
                    "signal_pattern": sp, "market_condition": mc,
                    "parameters": {
                        "entry": t.get("entry_condition", ""),
                        "stop_loss": t.get("stop_loss", ""),
                        "take_profit": t.get("take_profit", ""),
                        "position_size": t.get("position_size", ""),
                    },
                    "performance": {"quarters_tested": 1, "quarters_positive": 1,
                                    "avg_sharpe": (bt.get("sharpe", act_result.get("sharpe", 0))
                                                   if isinstance(bt, dict)
                                                   else getattr(bt, "sharpe", act_result.get("sharpe", 0))
                                                   if bt is not None
                                                   else act_result.get("sharpe", 0)),
                                    "avg_annual_excess": f"{pnl:.2f}%"},
                    "status": "candidate", "reuse_rule": "TBD — cross-quarter validation needed",
                })
                store.append_success([new_successes[-1]])

        # Record backtest execution errors in the library
        if act_result.get("status") == "error" and act_result.get("error") and not trades:
            mode = "BACKTEST_EXECUTION_ERROR"
            existing = store.find_failure("<BACKTEST ERROR>", "<N/A>", mode)
            if existing:
                store.bump_failure(existing["id"], extra_trades=0)
                bumped_f += 1
            else:
                rec = {
                    "id": store.next_id("F"), "date": today,
                    "signal_pattern": "<BACKTEST ERROR>", "market_condition": "<N/A>",
                    "failure_mode": mode,
                    "impact": {"trades": 0, "win_rate": "N/A", "total_pnl": "N/A"},
                    "root_cause": str(act_result.get("error", ""))[:500],
                    "solution": "Fix backtest.script in config.yaml or repair the backtest script",
                    "verification": "TBD", "status": "open", "exclusion_rule": "",
                }
                store.append_failure([rec])
                new_failures.append(rec)

        return {"new_failures": len(new_failures),
                "new_successes": len(new_successes),
                "bumped_failures": bumped_f, "bumped_successes": bumped_s}
