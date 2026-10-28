"""rag-vector memory plugin (third-party-shaped RAG memory backend).

Registers a store factory via the pattern_store_factory extension point
(ctx.register_memory_factory). When the roster enables this plugin AND
config.plugins.memory.active == 'rag-vector', the host swaps PatternStore for
this backend, so the loop's `self.store` becomes the RAG store and ALL
PatternStore operations run through it.

The RAG layer overrides find_failure with a similarity (keyword-overlap) stub
and exposes retrieve_similar(pattern, k). A real implementation would back this
with an embedding model + vector DB (e.g. a downloaded DSH RAG plugin wrapped
behind this same contract).
"""
import re


def _overlap(a, b):
    ta = set(re.findall(r"[A-Za-z_]+", a or ""))
    tb = set(re.findall(r"[A-Za-z_]+", b or ""))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def register(ctx):
    from memory_store import PatternStore

    class RagVectorStore(PatternStore):
        backend = "rag-vector"

        def __init__(self, db_path, *, config=None, **_kw):
            super().__init__(db_path)
            self.plugin_config = config or {}

        # RAG: exact-match miss -> similarity retrieve over stored patterns
        def find_failure(self, signal_pattern, market_condition, failure_mode=None):
            base = super().find_failure(signal_pattern, market_condition, failure_mode)
            if base is not None:
                return base
            best, best_score = None, 0.0
            for f in self.load_failure_patterns():
                score = _overlap(signal_pattern, f.get("signal_pattern", ""))
                if score > best_score:
                    best, best_score = f, score
            return best if best_score >= 0.5 else None

        def retrieve_similar(self, pattern, k=5):
            ranked = sorted(
                self.load_failure_patterns(),
                key=lambda f: _overlap(pattern, f.get("signal_pattern", "")),
                reverse=True,
            )
            return ranked[:k]

    def factory(config, db_path):
        return RagVectorStore(db_path, config=config)

    ctx.register_memory_factory(factory)
    return {"memory_factory": "rag-vector"}
