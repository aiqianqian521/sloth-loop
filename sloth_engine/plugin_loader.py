"""Plugin host: discovery / register-vs-materialize / lifecycle / purity gate.

Aligned with architect-plugin SKILL principles:
  1.1 soft-pluggable   - drop a plugin package (manifest+entry) into plugins/,
                         core wires it with zero core edits
  1.3 register-vs-materialize - load_all() registers the entry's `register`
                         factory WITHOUT calling it; activate() calls it
  1.4 extension-points - plugins wire via existing extension points
                         (tool_registry / hook_protocol / memory_store_abc)
  1.5 isolation/purity - purity_check() AST-scans entry.py for cross-plugin
                         imports; materialize failure of one plugin is caught
  1.6 lifecycle        - load -> activate -> unload -> reload
  1.7 roster           - activate_roster() activates only roster-enabled ids

The host reuses the existing ToolRegistry (register/dispatch/pre_hooks/
post_hooks) and never modifies its source. Plugin ownership is tracked in a
parallel ledger so unload() can cleanly remove a plugin's side effects.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from plugin_manifest import PluginManifest, load_manifest, validate
from plugin_roster import PluginRoster

# Ensure the sloth_engine directory is importable for plugin entries that do
# `from tool_registry import ToolDefinition` etc.
_ENGINE = Path(__file__).resolve().parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))


@dataclass
class PluginRecord:
    manifest: PluginManifest
    factory: object = None          # the entry's register(ctx) callable
    state: str = "discovered"       # discovered|registered|activated|unloaded|error
    error: str = ""
    module_path: str = ""           # sys.modules key under which entry was loaded
    module: ModuleType = None


class PluginContext:
    """Outbound seam handed to a plugin's register(ctx).

    A plugin registers its contributions through these methods only; the host
    records every contribution under the plugin's id so unload() can reverse
    them. The context never exposes core internals beyond the extension points.
    """

    def __init__(self, host: "PluginHost", plugin_id: str, trusted: bool, config: dict):
        self._host = host
        self.plugin_id = plugin_id
        self.trusted = trusted
        self.config = config or {}

    def register_tool(self, tool_def):
        self._host._register_tool(self.plugin_id, tool_def)

    def add_pre_hook(self, fn):
        self._host._add_hook(self.plugin_id, fn, kind="pre")

    def add_post_hook(self, fn):
        self._host._add_hook(self.plugin_id, fn, kind="post")

    def register_memory_store(self, store_cls):
        self._host._register_memory_store(self.plugin_id, store_cls)
    def register_memory_factory(self, factory):
        self._host._register_memory_factory(self.plugin_id, factory)

    def log(self, msg: str):
        self._host._log(f"[{self.plugin_id}] {msg}")


class PluginHost:
    def __init__(self, plugins_root, registry, roster=None, config=None):
        self.root = Path(plugins_root)
        self.registry = registry
        self.roster = roster if roster is not None else PluginRoster()
        self.config = config or {}
        self._records: dict[str, PluginRecord] = {}
        self._modules: dict[str, ModuleType] = {}
        self._mem_factories: dict[str, object] = {}
        # per-plugin ledger: {pid: {"tools":[names], "pre":[fn], "post":[fn], "mem":[cls]}}
        self._owned: dict[str, dict] = defaultdict(
            lambda: {"tools": [], "pre": [], "post": [], "mem": []})

    # -- discovery ---------------------------------------------------------
    def discover(self):
        """Scan <root>/**/manifest.json, load + validate manifests."""
        if not self.root.exists():
            return []
        manifests = []
        for mf in sorted(self.root.rglob("manifest.json")):
            try:
                m = load_manifest(mf)
            except Exception as exc:
                continue
            errs = validate(m)
            if errs:
                # keep an error record so the failure is visible, but do not
                # register a factory for invalid manifests
                rec = PluginRecord(manifest=m, state="error", error="; ".join(errs))
                if m.id:
                    self._records[m.id] = rec
                continue
            self._records[m.id] = PluginRecord(manifest=m, state="discovered")
            manifests.append(m)
        return manifests

    def get(self, plugin_id) -> PluginRecord:
        return self._records.get(plugin_id)

    def module_of(self, plugin_id):
        return self._modules.get(plugin_id)

    def ids(self):
        return list(self._records.keys())

    # -- load (register factory, NO materialize) --------------------------
    def load_all(self):
        for pid in list(self._records.keys()):
            rec = self._records[pid]
            if rec.state in ("error",):
                continue
            if rec.factory is None:
                self._load_one(pid)
        return self._records

    def _load_one(self, pid):
        rec = self._records[pid]
        m = rec.manifest
        entry_path = m.base_dir / m.entry
        if not entry_path.exists():
            rec.state = "error"
            rec.error = f"entry missing: {entry_path}"
            return
        mod_name = f"loop_plugin_{pid.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(mod_name, entry_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(mod_name, None)
            rec.state = "error"
            rec.error = f"entry exec failed: {type(exc).__name__}: {exc}"
            return
        if not hasattr(module, "register") or not callable(module.register):
            sys.modules.pop(mod_name, None)
            rec.state = "error"
            rec.error = "entry has no callable register(ctx)"
            return
        rec.factory = module.register
        rec.module_path = mod_name
        rec.module = module
        self._modules[pid] = module
        rec.state = "registered"

    # -- activate (materialize) -------------------------------------------
    def activate(self, pid) -> PluginRecord:
        rec = self._records.get(pid)
        if rec is None:
            raise KeyError(f"unknown plugin: {pid}")
        if rec.state == "activated":
            return rec
        if rec.factory is None:
            self._load_one(pid)
            rec = self._records[pid]
            if rec.state == "error":
                return rec
        ctx = PluginContext(self, pid, self.roster.is_trusted(pid), self.config)
        try:
            rec.factory(ctx)
        except Exception as exc:
            # failure isolation: a bad materialize must not crash siblings
            rec.state = "error"
            rec.error = f"materialize failed: {type(exc).__name__}: {exc}"
            self._log(f"[{pid}] activate error: {rec.error}")
            return rec
        rec.state = "activated"
        rec.error = ""
        return rec

    def activate_roster(self):
        out = []
        for pid in self.roster.enabled_ids():
            if pid in self._records:
                out.append(self.activate(pid))
        return out

    # -- unload / reload --------------------------------------------------
    def unload(self, pid) -> PluginRecord:
        rec = self._records.get(pid)
        if rec is None:
            raise KeyError(f"unknown plugin: {pid}")
        owned = self._owned.get(pid, {"tools": [], "pre": [], "post": [], "mem": []})
        # tools
        for name in owned.get("tools", []):
            if name in self.registry._tools:
                del self.registry._tools[name]
        # hooks
        for fn in owned.get("pre", []):
            if fn in self.registry._pre_hooks:
                self.registry._pre_hooks.remove(fn)
        for fn in owned.get("post", []):
            if fn in self.registry._post_hooks:
                self.registry._post_hooks.remove(fn)
        # memory classes are not held by the registry; just clear the ledger
        owned["tools"] = []
        owned["pre"] = []
        owned["post"] = []
        owned["mem"] = []
        rec.state = "unloaded"
        return rec

    def reload(self, pid) -> PluginRecord:
        rec = self._records.get(pid)
        if rec is None:
            raise KeyError(f"unknown plugin: {pid}")
        self.unload(pid)
        mod_name = rec.module_path
        if mod_name and mod_name in sys.modules:
            del sys.modules[mod_name]
        self._modules.pop(pid, None)
        rec.factory = None
        rec.module = None
        self._load_one(pid)
        return self.activate(pid)

    # -- purity gate ------------------------------------------------------
    def purity_check(self):
        """AST-scan every entry.py for cross-plugin imports.

        A plugin may not `import plugins.*` (cross-plugin value coupling);
        it must go through a core-exposed service / event / shared context.
        Returns a list of human-readable violation strings.
        """
        violations = []
        for pid, rec in self._records.items():
            if rec.manifest is None:
                continue
            entry_path = rec.manifest.base_dir / rec.manifest.entry
            if not entry_path.exists():
                continue
            try:
                tree = ast.parse(entry_path.read_text(encoding="utf-8-sig"))
            except Exception:
                violations.append(f"{pid}: cannot parse entry.py")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for n in node.names:
                        if n.name == "plugins" or n.name.startswith("plugins."):
                            violations.append(f"{pid}: cross-plugin import {n.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod == "plugins" or mod.startswith("plugins."):
                        violations.append(f"{pid}: cross-plugin from-import {mod}")
        return violations

    # -- extension-point wiring (called by PluginContext) -----------------
    def _register_tool(self, pid, tool_def):
        self.registry.register(tool_def)
        self._owned[pid]["tools"].append(tool_def.name)

    def _add_hook(self, pid, fn, kind):
        if kind == "pre":
            self.registry.add_pre_hook(fn)
            self._owned[pid]["pre"].append(fn)
        else:
            self.registry.add_post_hook(fn)
            self._owned[pid]["post"].append(fn)

    def _register_memory_store(self, pid, store_cls):
        self._owned[pid]["mem"].append(store_cls)
    def _register_memory_factory(self, pid, factory):
        self._mem_factories[pid] = factory

    def memory_factory(self, pid):
        """Return the store factory registered by plugin `pid`, or None."""
        return self._mem_factories.get(pid)

    def memory_stores(self):
        out = []
        for owned in self._owned.values():
            out.extend(owned.get("mem", []))
        return out

    def _log(self, msg):
        # minimal logger; swap for the engine logger when wired into orchestrator
        print(f"[plugin-host] {msg}", file=sys.stderr)

