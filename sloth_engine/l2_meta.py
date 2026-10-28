"""L2 meta-analysis mixin for the Orchestrator (P2.1 slice C3).

Extracted verbatim from orchestrator.py: meta_analyze plus the _l2_* thin wrappers
that delegate to self.l2_analyzer. Kept as a mixin: self.l2_analyzer stays an
instance attribute wired in Orchestrator.__init__; the run-loop call sites remain
in orchestrator and resolve these methods via self through MRO.
"""
from __future__ import annotations

class L2Meta:

    def meta_analyze(self, *, trigger_type: str = "periodic",
                     progress_data: dict | None = None) -> dict:
        return self.l2_analyzer.meta_analyze(
            trigger_type=trigger_type, progress_data=progress_data)

    def _l2_auto_suggest(self, meta_result: dict) -> list[dict]:
        return self.l2_analyzer.auto_suggest(meta_result)

    def _l2_read_progress(self) -> dict:
        return self.l2_analyzer.read_progress(
            total_rounds=self.total_rounds,
            last_progress_round=self.last_progress_round)

    def _l2_check_triggers(self, progress: dict) -> str | None:
        return self.l2_analyzer.check_triggers(
            progress, total_rounds=self.total_rounds)

    def _l2_health_check(self, progress: dict, trigger_type: str) -> dict:
        return self.l2_analyzer.health_check(progress, trigger_type)

    def _l2_verify_suggestions(self) -> dict:
        return self.l2_analyzer.verify_suggestions()
