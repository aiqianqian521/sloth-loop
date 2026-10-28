"""Example filter plugin.

Registers a pre_hook that observes (does not block) tools whose name starts
with 'example_'. Demonstrates the filter extension point wired through
tool_registry.add_pre_hook without altering dispatch flow.
"""
def register(ctx):
    def observe(tool_name, params):
        if isinstance(tool_name, str) and tool_name.startswith("example_"):
            # In a real filter, emit a HookOutput('warn', ...) via hook_protocol
            # and let merge_hook_outputs decide. Here we just pass through.
            pass
        return params
    ctx.add_pre_hook(observe)
    return {"hook": "observe"}
