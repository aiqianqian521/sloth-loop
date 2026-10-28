"""Example memory backend plugin stub.

Registers a store-class candidate for future substitution of the pattern
store (memory_store_abc.BasePatternStore). Produces no real storage;
illustrative only - shows the 'memory' extension point.
"""
class DemoBackend:
    backend = "demo"

    def __init__(self, *a, **k):
        pass


def register(ctx):
    ctx.register_memory_store(DemoBackend)
    return {"memory": "demo"}
