"""Example backtest strategy plugin.

Demonstrates the register(ctx) contract: register a ToolDefinition whose
handler returns a normalized result dict. Drop this package into
plugins/backtest/ and add its id to config.plugins.roster to activate.
A real strategy would consume kline data injected via ctx and emit trades.
"""
def register(ctx):
    from tool_registry import ToolDefinition

    def run(payload=None, **kw):
        return {"status": "ok", "trades": [], "metrics": {"trades_count": 0},
                "note": "example-strategy no-op"}

    ctx.register_tool(ToolDefinition(
        name="example_strategy", source="backtest",
        handler=run, description="example backtest strategy"))
    return {"tool": "example_strategy"}
