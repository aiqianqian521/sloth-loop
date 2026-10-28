# sloth_engine/plugins/

Drop-in plugin packages for sloth-loop. Aligned with `architect-plugin` SKILL
(soft-pluggable: drop a package here, list it in `config.plugins.roster`,
core wires it with zero core edits).

## Package layout

```
plugins/<type>/<name>/
  manifest.json   # loading contract (id/version/type/entry/extension_points/inject/lazy)
  entry.py        # def register(ctx): ...   # register factory, no side effects
```

`<type>` is one of: backtest | filter | memory | skill | signal | rag | ui.

## Extension points (existing, reused - do NOT modify)

- `tool`            -> ctx.register_tool(ToolDefinition(...))   [tool_registry]
- `hook:pre_entry`  -> ctx.add_pre_hook(fn)                     [tool_registry pre-hook]
- `hook:post_*`     -> ctx.add_post_hook(fn)
- `memory_store`    -> ctx.register_memory_store(cls)           [memory_store_abc family]

## Roster (mount decision)

`config.yaml`:
```
plugins:
  roster:
    - id: example-strategy
      enabled: true
      trusted: true
```
No `plugins` key => empty roster => nothing activated (legacy projects undisturbed).

## Lifecycle

load (register factory, NO materialize) -> activate (call register(ctx), wire
extensions) -> unload (clear this plugin's tools/hooks) -> reload.

## Purity gate

`PluginHost.purity_check()` AST-scans entry.py and rejects `import plugins.*`
(cross-plugin value coupling). Use the core-exposed services via ctx instead.

## Examples

- backtest/example-strategy  : registers a `example_strategy` tool (no-op)
- filter/example-rule        : registers an observe-only pre_hook
- memory/example-backend     : registers a DemoBackend store class stub
