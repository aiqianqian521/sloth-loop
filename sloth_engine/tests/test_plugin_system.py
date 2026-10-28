"""Plugin system contract tests - test-before-fix (red first, then green).

Defines the behavior contract for sloth-loop's plugin architecture BEFORE
implementation. Tests MUST fail (red) until plugin_manifest /
plugin_roster / plugin_loader are implemented and wired to the existing
extension points (tool_registry / hook_protocol / memory_store_abc).

Aligned with architect-plugin SKILL 8 principles:
  soft-pluggable / Manifest contract / register-vs-materialize /
  extension-points / isolation-purity-gate / lifecycle / roster / failure-isolation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from tool_registry import ToolRegistry, ToolDefinition  # existing extension point


def _write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _manifest(pid, ptype, ext_points, extra=None):
    m = {"id": pid, "version": "0.1.0", "type": ptype, "entry": "entry.py",
         "extension_points": ext_points, "inject": [], "lazy": True,
         "description": "example"}
    if extra:
        m.update(extra)
    return m


def make_backtest_plugin(root, pid="bt-example"):
    root = Path(root)
    _write(root / "manifest.json", json.dumps(_manifest(pid, "backtest", ["tool"]), indent=2))
    tname = pid.replace("-", "_") + "_tool"
    body = (
        '"""example backtest plugin entry (register(ctx) contract)."""\n'
        "REGISTER_CALLS = []\n"
        "def register(ctx):\n"
        "    REGISTER_CALLS.append('called')\n"
        "    def handler(payload=None, **kw):\n"
        "        return {'status': 'ok', 'trades': [], 'metrics': {'trades_count': 1}}\n"
        "    from tool_registry import ToolDefinition\n"
        "    ctx.register_tool(ToolDefinition(name='" + tname + "', source='backtest', handler=handler, description='example'))\n"
        "    return {'tool': 'ok'}\n"
    )
    _write(root / "entry.py", body)
    return root


def make_filter_plugin(root, pid="fl-block"):
    root = Path(root)
    _write(root / "manifest.json", json.dumps(_manifest(pid, "filter", ["hook:pre_entry"], {"lazy": False}), indent=2))
    body = (
        '"""filter plugin entry: registers a pre_hook returning None (block)."""\n'
        "def register(ctx):\n"
        "    def gate(tool_name, params):\n"
        "        if tool_name == 'forbidden_tool':\n"
        "            return None\n"
        "        return params\n"
        "    ctx.add_pre_hook(gate)\n"
        "    return {'hook': 'installed'}\n"
    )
    _write(root / "entry.py", body)
    return root


def make_memory_plugin(root, pid="mem-vector"):
    root = Path(root)
    _write(root / "manifest.json", json.dumps(_manifest(pid, "memory", ["memory_store"], {"inject": ["vector"]}), indent=2))
    body = (
        '"""memory plugin entry: registers a store-class for later substitution."""\n'
        "class VectorStore:\n"
        "    backend = 'vector'\n"
        "    def __init__(self, *a, **k):\n"
        "        pass\n"
        "def register(ctx):\n"
        "    ctx.register_memory_store(VectorStore)\n"
        "    return {'memory_class': 'VectorStore'}\n"
    )
    _write(root / "entry.py", body)
    return root


def make_bad_plugin(root, pid="bt-bad"):
    root = Path(root)
    _write(root / "manifest.json", json.dumps(_manifest(pid, "backtest", ["tool"]), indent=2))
    body = (
        '"""bad plugin: register() raises -> failure isolation must catch."""\n'
        "def register(ctx):\n"
        "    raise RuntimeError('boom on materialize')\n"
    )
    _write(root / "entry.py", body)
    return root


def make_cross_import_plugin(root, pid="bt-sib"):
    root = Path(root)
    _write(root / "manifest.json", json.dumps(_manifest(pid, "backtest", ["tool"]), indent=2))
    body = (
        '"""bad plugin: imports a sibling plugin package (cross-plugin coupling)."""\n'
        "import plugins.backtest.bt_other.entry as _sibling  # cross-plugin import\n"
        "def register(ctx):\n"
        "    return {}\n"
    )
    _write(root / "entry.py", body)
    return root


# 1. Manifest contract ------------------------------------------------------
def test_manifest_load_and_validate_ok():
    from plugin_manifest import load_manifest, validate
    tmp = HERE / "_tmp_manifest_ok"
    make_backtest_plugin(tmp, "bt-m1")
    m = load_manifest(tmp / "manifest.json")
    assert m.id == "bt-m1"
    assert m.type == "backtest"
    assert m.entry == "entry.py"
    assert validate(m) == []


def test_manifest_rejects_missing_id():
    from plugin_manifest import load_manifest, validate
    tmp = HERE / "_tmp_manifest_bad"
    _write(tmp / "manifest.json", json.dumps({"version": "1", "type": "backtest", "entry": "e.py"}))
    m = load_manifest(tmp / "manifest.json")
    assert any("id" in e for e in validate(m))


def test_manifest_rejects_bad_type():
    from plugin_manifest import load_manifest, validate
    tmp = HERE / "_tmp_manifest_type"
    _write(tmp / "manifest.json", json.dumps({"id": "x", "version": "1", "type": "nonexistent", "entry": "e.py"}))
    m = load_manifest(tmp / "manifest.json")
    assert any("type" in e for e in validate(m))


# 2. register vs materialize ------------------------------------------------
def test_load_all_registers_factory_without_materializing():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_loadonly" / "plugins"
    make_backtest_plugin(pdir / "backtest" / "bt-example", "bt-example")
    reg = ToolRegistry()
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover()
    host.load_all()
    rec = host.get("bt-example")
    assert rec is not None and rec.state == "registered"
    assert reg.get("bt_example_tool") is None


def test_activate_materializes_and_wires_tool():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_act" / "plugins"
    make_backtest_plugin(pdir / "backtest" / "bt-example", "bt-example")
    reg = ToolRegistry()
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all()
    rec = host.activate("bt-example")
    assert rec.state == "activated"
    assert reg.get("bt_example_tool") is not None
    out = reg.dispatch("bt_example_tool", {"looks": "live"})
    assert out.get("status") == "completed"  # handler ok -> normalized completed


# 3. Roster -----------------------------------------------------------------
def test_roster_only_activates_enabled():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_roster" / "plugins"
    make_backtest_plugin(pdir / "backtest" / "bt-a", "bt-a")
    make_backtest_plugin(pdir / "backtest" / "bt-b", "bt-b")
    cfg = {"plugins": {"roster": [{"id": "bt-a", "enabled": True, "trusted": True}, {"id": "bt-b", "enabled": False}]}}
    reg = ToolRegistry()
    roster = PluginRoster.from_config(cfg)
    assert roster.is_enabled("bt-a") and not roster.is_enabled("bt-b")
    host = PluginHost(pdir, reg, roster=roster)
    host.discover(); host.load_all(); host.activate_roster()
    assert host.get("bt-a").state == "activated"
    assert host.get("bt-b").state == "registered"


def test_roster_empty_when_no_plugins_key_backcompat():
    from plugin_roster import PluginRoster
    r = PluginRoster.from_config({"loop": {"max_rounds": 5}})
    assert r.is_enabled("anything") is False


# 4. Lifecycle --------------------------------------------------------------
def test_unload_clears_extensions():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_unload" / "plugins"
    make_backtest_plugin(pdir / "backtest" / "bt-example", "bt-example")
    reg = ToolRegistry()
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all(); host.activate("bt-example")
    assert reg.get("bt_example_tool") is not None
    host.unload("bt-example")
    assert reg.get("bt_example_tool") is None
    assert host.get("bt-example").state == "unloaded"


def test_reload_re_registers():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_reload" / "plugins"
    make_backtest_plugin(pdir / "backtest" / "bt-example", "bt-example")
    reg = ToolRegistry()
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all(); host.activate("bt-example")
    host.reload("bt-example")
    assert host.get("bt-example").state == "activated"
    assert reg.get("bt_example_tool") is not None


def test_unload_filter_removes_hook():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_hookunload" / "plugins"
    make_filter_plugin(pdir / "filter" / "fl-block", "fl-block")
    reg = ToolRegistry()
    n_before = len(reg._pre_hooks)
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all(); host.activate("fl-block")
    assert len(reg._pre_hooks) == n_before + 1
    host.unload("fl-block")
    assert len(reg._pre_hooks) == n_before


# 5. isolation / purity gate ------------------------------------------------
def test_purity_check_blocks_cross_plugin_import():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_purity" / "plugins"
    make_backtest_plugin(pdir / "backtest" / "bt-other", "bt-other")
    make_cross_import_plugin(pdir / "backtest" / "bt-sib", "bt-sib")
    reg = ToolRegistry()
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover()
    violations = host.purity_check()
    assert any("bt-sib" in v for v in violations), f"expected cross-plugin violation: {violations}"


# 6. failure isolation ------------------------------------------------------
def test_failure_isolation_bad_plugin_does_not_crash_others():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_fail" / "plugins"
    make_backtest_plugin(pdir / "backtest" / "bt-good", "bt-good")
    make_bad_plugin(pdir / "backtest" / "bt-bad", "bt-bad")
    reg = ToolRegistry()
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all()
    rec_bad = host.activate("bt-bad")
    assert rec_bad.state == "error"
    rec_good = host.activate("bt-good")
    assert rec_good.state == "activated"
    assert reg.get("bt_good_tool") is not None


# 7. soft-pluggable: core unchanged, no break -------------------------------
def test_existing_tool_registry_unchanged_when_no_plugins():
    reg = ToolRegistry()
    reg.register_script("legacy", lambda **k: {"status": "ok"})
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    empty = HERE / "_tmp_empty" / "plugins"
    empty.mkdir(parents=True, exist_ok=True)
    host = PluginHost(empty, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all(); host.activate_roster()
    assert "legacy" in reg.tool_names
    assert reg.dispatch("legacy").get("status") == "completed"  # ok -> normalized completed


# 8. extension-point wiring -------------------------------------------------
def test_filter_plugin_blocks_forbidden_tool():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_filter" / "plugins"
    make_filter_plugin(pdir / "filter" / "fl-block", "fl-block")
    reg = ToolRegistry()
    reg.register_script("forbidden_tool", lambda **k: {"status": "ok"})
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all(); host.activate("fl-block")
    assert reg.dispatch("forbidden_tool").get("status") == "skipped"  # blocked -> normalized skipped


def test_memory_plugin_registers_store_class():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_mem" / "plugins"
    make_memory_plugin(pdir / "memory" / "mem-vector", "mem-vector")
    reg = ToolRegistry()
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all(); host.activate("mem-vector")
    assert host.get("mem-vector").state == "activated"
    stores = host.memory_stores()
    assert any(getattr(s, "backend", None) == "vector" for s in stores)


def test_context_provides_config_and_trust():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_ctx" / "plugins"
    _write(pdir / "backtest" / "bt-ctx" / "manifest.json", json.dumps(_manifest("bt-ctx", "backtest", ["tool"]), indent=2))
    _write(pdir / "backtest" / "bt-ctx" / "entry.py",
        '"""ctx probe plugin."""\n'
        "SEEN = {}\n"
        "def register(ctx):\n"
        "    SEEN['plugin_id'] = ctx.plugin_id\n"
        "    SEEN['trusted'] = ctx.trusted\n"
        "    SEEN['has_config'] = isinstance(ctx.config, dict)\n"
        "    SEEN['config_dyn'] = ctx.config.get('dyn')\n"
        "    return {}\n"
    )
    cfg = {"dyn": 42, "plugins": {"roster": [{"id": "bt-ctx", "enabled": True, "trusted": True}]}}
    reg = ToolRegistry()
    roster = PluginRoster.from_config(cfg)
    host = PluginHost(pdir, reg, roster=roster, config=cfg)
    host.discover(); host.load_all(); host.activate("bt-ctx")
    assert host.get("bt-ctx").state == "activated"
    mod = host.module_of("bt-ctx")
    assert mod.SEEN["plugin_id"] == "bt-ctx"
    assert mod.SEEN["trusted"] is True
    assert mod.SEEN["has_config"] is True
    assert mod.SEEN["config_dyn"] == 42


# 9. memory factory substitution (Upgrade-Law: memory plugin replaces store) --
def test_memory_factory_registered_and_callable():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    pdir = HERE / "_tmp_memfact" / "plugins"
    _write(pdir / "memory" / "mf" / "manifest.json",
           json.dumps(_manifest("mf", "memory", ["memory_store", "pattern_store_factory"]), indent=2))
    body = (
        "# mf plugin\n"
        "class Demo:\n"
        "    backend='mf'\n"
        "    def __init__(self, config, db_path):\n"
        "        self.config=config; self.db_path=db_path\n"
        "def register(ctx):\n"
        "    ctx.register_memory_factory(lambda config, db_path: Demo(config, db_path))\n"
        "    return {'mf':1}\n"
    )
    _write(pdir / "memory" / "mf" / "entry.py", body)
    reg = ToolRegistry()
    host = PluginHost(pdir, reg, roster=PluginRoster.from_config({}))
    host.discover(); host.load_all(); host.activate("mf")
    f = host.memory_factory("mf")
    assert f is not None and callable(f)
    inst = f({"x": 1}, "/tmp/_mf_demo.db")
    assert inst.backend == "mf" and inst.config["x"] == 1


# 10. real translated DSH plugin: dsh-rag-kb (kb_search/kb_index/kb_status) ---
def test_dsh_rag_kb_tools_via_real_plugin():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    import tempfile
    tmp = HERE / "_tmp_rag"
    docs = tmp / "docs"
    _write(docs / "note.txt",
        "sloth-loop rag plugin test. semantic search retrieval over a local "
        "knowledge base built from text chunks with hashed bigram embeddings "
        "and cosine scoring.")
    _write(docs / "readme.md",
        "# RAG\nTranslate DSH plugin ideas into sloth-loop plugins. drop a "
        "package, roster-enable, register tools.")
    store = tmp / "store.json"
    cfg = {"plugins": {"rag": {"store_path": str(store)},
                       "roster": [{"id": "dsh-rag-kb", "enabled": True, "trusted": True}]}}
    reg = ToolRegistry()
    host = PluginHost(ENGINE / "plugins", reg, roster=PluginRoster.from_config(cfg), config=cfg)
    host.discover(); host.load_all(); host.activate_roster()
    assert reg.get("kb_search") is not None
    assert reg.get("kb_index") is not None
    assert reg.get("kb_status") is not None
    idx = reg.dispatch("kb_index", {"path": str(docs), "kbTitle": "rag-test"})
    assert idx.get("ok") is True and idx.get("chunkCount", 0) > 0
    st = reg.dispatch("kb_status", {})
    assert st.get("ok") is True and any(k.get("title") == "rag-test" for k in st.get("kbs", []))
    sr = reg.dispatch("kb_search", {"query": "semantic search retrieval", "topK": 3})
    assert sr.get("ok") is True and isinstance(sr.get("results"), list) and len(sr["results"]) > 0
    assert "score" in sr["results"][0] and "snippet" in sr["results"][0]


# 11. dsh-mneme semantic memory tools (real translated plugin) ---
def test_dsh_mneme_memory_tools():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    tmp = HERE / "_tmp_mneme"
    store = tmp / "mneme.json"
    md = tmp / "mneme.md"
    cfg = {"plugins": {"memory": {"mneme_store": str(store), "mneme_md": str(md)},
                       "roster": [{"id": "dsh-mneme", "enabled": True, "trusted": True}]}}
    reg = ToolRegistry()
    host = PluginHost(ENGINE / "plugins", reg, roster=PluginRoster.from_config(cfg), config=cfg)
    host.discover(); host.load_all(); host.activate_roster()
    for n in ("memory_remember", "memory_search", "memory_timeline", "memory_status"):
        assert reg.get(n) is not None, n
    r1 = reg.dispatch("memory_remember", {"text": "The PM regime filter uses a 1H TrendGate to decide market regime.", "tags": ["regime", "trend"]})
    assert r1.get("ok") is True and "TrendGate" in r1.get("entities")
    r2 = reg.dispatch("memory_remember", {"text": "R6 entry filter blocks counter-trend signals in trending markets."})
    assert r2.get("ok") is True
    s = reg.dispatch("memory_search", {"query": "regime trend gate", "topK": 5})
    assert s.get("ok") is True and isinstance(s.get("results"), list) and len(s["results"]) >= 1
    tl = reg.dispatch("memory_timeline", {"entity": "regime"})
    assert tl.get("ok") is True and isinstance(tl.get("timeline"), list)
    st = reg.dispatch("memory_status", {})
    assert st.get("ok") is True and st.get("count") >= 2
    assert store.exists() and md.exists()

# 12. dsh-find-plugin discovery tools (real translated plugin) ---
def test_dsh_find_plugin_tools():
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    cfg = {"plugins": {"root": str(ENGINE / "plugins"),
                       "roster": [{"id": "dsh-find-plugin", "enabled": True, "trusted": True}]}}
    reg = ToolRegistry()
    host = PluginHost(ENGINE / "plugins", reg, roster=PluginRoster.from_config(cfg), config=cfg)
    host.discover(); host.load_all(); host.activate_roster()
    for n in ("find_plugins", "plugin_list", "plugin_doctor"):
        assert reg.get(n) is not None, n
    lst = reg.dispatch("plugin_list", {})
    assert lst.get("ok") is True and lst.get("count", 0) >= 6
    found = reg.dispatch("find_plugins", {"query": "rag"})
    assert found.get("ok") is True and any("rag" in p["id"] for p in found.get("plugins", []))
    doc = reg.dispatch("plugin_doctor", {})
    assert doc.get("ok") is True and doc.get("total", 0) == lst.get("count")
