"""Global plugin bootstrap - single source of truth (sloth-loop v4 plugin-ification).

Re: "plugins should be GLOBALLY enabled and SHARED across all tasks", not set up
per-task. Mechanism truth: backtest_adapter runs wrapper.py in a SUBPROCESS, so
the orchestrator's in-memory PluginHost cannot literally cross into the wrapper
process. "Global + shared" is therefore realized as:
  - roster defined ONCE in plugin_config.yaml;
  - persistent shared stores at FIXED paths (mneme / kb / events / ws) so memory
    and RAG accumulate across tasks AND across runs (loop essence at scale);
  - orchestrator AND every analysis wrapper each reconstruct a PluginHost from the
    SAME global config (per-process instances, SHARED config + SHARED stores).

Category boundary (NOT a per-task switch): the deterministic sim subprocess
(paper_trading_simulator, BASE2) is NEVER given plugins (determinism invariant).
Analysis/decision tier (orchestrator OODA + analysis wrappers) uses plugins.

API (stable surface):
  load_global_config() -> dict            # raw yaml of plugin_config.yaml
  shared_store_root(config=None) -> Path   # fixed shared-store root
  has_roster(config) -> bool               # does config declare its own roster?
  merge_global_into(config) -> config       # in-place: if config has NO roster, fold
                                            #   in the global plugin block (roster+stores)
                                            #   so the orchestrator activates globally.
                                            #   Backward compatible + reversible; project
                                            #   keeps its own roster if it declares one.
  load_global_host(store_root_override=None, plugins_root=None, seams=None
                   ) -> (ToolRegistry, PluginHost, cfg)
                                            # single rebuild entry for analysis
                                            #   wrappers. `seams` = list of
                                            #   (plugin_id, key, callable) backend seams
                                            #   the CALLER injects (task-specific glue);
                                            #   global config supplies roster + stores.
"""
from __future__ import annotations
import copy
import logging
import json
import os
import sys
from pathlib import Path

_log = logging.getLogger("sloth_engine")
_ENGINE = Path(__file__).resolve().parent  # sloth_engine
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

GLOBAL_CONFIG = _ENGINE / "plugin_config.yaml"
DEFAULT_STORE_ROOT = Path(os.environ.get(
                                         "LOOP_PLUGIN_STORE_ROOT",
                                         _ENGINE.parent / "rt" / "plugin-global"))


def _load_yaml(path):
    try:
        import yaml
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_global_config():
    if not GLOBAL_CONFIG.is_file():
        return {}
    return resolve_global_paths(_load_yaml(GLOBAL_CONFIG))


def resolve_global_paths(cfg, engine=None):
    """Resolve relative store/workspace paths to this repo root so the
    global plugin config is self-contained (no hard-coded source-machine
    paths). Values already absolute are left untouched; env wins."""
    engine = engine or _ENGINE
    base = engine.parent  # repo root
    if not cfg:
        return cfg
    if not cfg.get("store_root"):
        cfg["store_root"] = str(shared_store_root(cfg))
    def _abs(v):
        if not isinstance(v, str):
            return v
        if Path(v).is_absolute():
            return v
        return str((base / Path(v)).resolve())
    cfg["store_root"] = _abs(cfg.get("store_root", ""))
    plugins = cfg.get("plugins") or {}
    for section, keys in (("memory", ("mneme_store", "mneme_md")),
                          ("context", ("events_dir",)),
                          ("rag", ("store_path",)),
                          ("at_file", ("workspace_root",)),
                          ("modsearch", ("corpus_dir",)),
                          ("find", ("root",))):
        sec = plugins.get(section) or {}
        for k in keys:
            if k in sec and isinstance(sec[k], str):
                sec[k] = _abs(sec[k])
    return cfg

def shared_store_root(config=None):
    # deploy-level env override wins, then explicit config, then global, then default
    env = os.environ.get("LOOP_PLUGIN_STORE_ROOT")
    if env:
        return Path(env)
    if config and config.get("store_root"):
        return Path(config["store_root"])
    g = load_global_config()
    return Path(g.get("store_root") or DEFAULT_STORE_ROOT)


def has_roster(config):
    return bool((config.get("plugins") or {}).get("roster"))


def merge_global_into(config):
    """Backward-compat global fold for the orchestrator.

    If `config` already declares its own plugins.roster, it wins (project override).
    Otherwise, if a global plugin_config.yaml exists with a roster, fold the global
    plugin block (roster + store paths) into `config` in place. If no global file or
    no global roster, leave `config` untouched (legacy no-op).
    """
    if has_roster(config):
        return config
    g = load_global_config()
    gp = g.get("plugins") or {}
    if not gp.get("roster"):
        return config
    plugins = dict(config.get("plugins") or {})
    merged = {k: v for k, v in gp.items()}
    for k, v in plugins.items():
        if k == "roster":
            continue
        merged[k] = v
    merged["roster"] = gp["roster"]
    config["plugins"] = merged
    if g.get("store_root") and "store_root" not in config:
        config["store_root"] = g["store_root"]
    return config


def _ensure_dirs(cfg):
    p = cfg.get("plugins", {})
    for key in ("mneme_store", "mneme_md"):
        v = (p.get("memory") or {}).get(key)
        if v:
            Path(v).parent.mkdir(parents=True, exist_ok=True)
    ev = (p.get("context") or {}).get("events_dir")
    if ev:
        Path(ev).mkdir(parents=True, exist_ok=True)
    rd = (p.get("rag") or {}).get("store_path")
    if rd:
        Path(rd).parent.mkdir(parents=True, exist_ok=True)


def _seed_events(cfg):
    ev = (cfg.get("plugins", {}).get("context", {}) or {}).get("events_dir")
    if not ev:
        return
    evp = Path(ev)
    if not evp.exists() or not any(evp.iterdir()):
        evp.mkdir(parents=True, exist_ok=True)
        (evp / "seed.jsonl").write_text(
            json.dumps({"type": "seed", "ts": 0, "tokens": 0,
                        "note": "global plugin event seed"}) + "\n",
            encoding="utf-8")


def build_host(registry, cfg, gate=None):
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    _ensure_dirs(cfg)
    _seed_events(cfg)
    plugins_root = ((cfg.get("plugins") or {}).get("find") or {}).get("root") \
        or str(_ENGINE / "plugins")
    host = PluginHost(plugins_root, registry,
                      roster=PluginRoster.from_config(cfg), config=cfg)
    host.discover()
    host.load_all()
    host.activate_roster()
    _register_mcp_tools(registry, cfg, gate=gate)
    return host


def _register_mcp_tools(registry, cfg, gate=None):
    """Opt-in: discover tools from configured MCP servers into the registry.

    Config shape (all optional)::

        plugins:
          mcp:
            enabled: true
            servers:
              - name: filesystem
                command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                namespace: "mcp/"

    Disabled by default (feature flag `mcp_tools` OFF). Any failure is logged and
    never breaks plugin bootstrap.

    cycle-35 A: the MCP server spawn goes through the ExecGate, so a host with
    no gate cannot start MCP servers at all (fail-closed: no ungated spawn).
    """
    mcp_cfg = ((cfg.get("plugins") or {}).get("mcp") or {})
    if not mcp_cfg.get("enabled"):
        return 0
    servers = mcp_cfg.get("servers") or []
    if not servers:
        return 0
    if gate is None:
        _log.warning("[mcp] %d server(s) configured but no ExecGate was "
                     "provided; refusing to spawn (fail-closed)", len(servers))
        return 0
    total = 0
    try:
        from mcp_client import MCPClient
    except Exception as exc:
        _log.warning("[mcp] client unavailable: %s", exc)
        return 0
    for spec in servers:
        client = None
        try:
            client = MCPClient(gate)
            client.connect(spec.get("command") or [])
            n = registry.discover_from_mcp(client, namespace=spec.get("namespace", ""))
            total += n
            _log.info("[mcp] %s: registered %d tool(s)", spec.get("name", "mcp"), n)
        except Exception as exc:
            _log.warning("[mcp] server %r failed: %s", spec.get("name"), exc)
        finally:
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
    return total


def load_global_host(store_root_override=None, plugins_root=None, seams=None):
    """Single rebuild entry for analysis wrappers.

    seams: list of (plugin_id, key, callable) injected into cfg BEFORE activate so
    plugins registering a backend seam (dsh-workflow.step_fn /
    dsh-agent-teams.executor_fn / modsearch.search_fn / ...) pick them up. The
    callable should late-bind the registry (e.g. via a holder) since registry is
    created here and closures are consumed at register() time but CALLED later.
    """
    cfg = copy.deepcopy(load_global_config())
    if ssh := store_root_override:
        sr = Path(ssh)
        sr.mkdir(parents=True, exist_ok=True)
        cfg["store_root"] = str(sr)
        m = cfg["plugins"]["memory"]
        m["mneme_store"] = str(sr / "mneme.json")
        m["mneme_md"] = str(sr / "mneme.md")
        cfg["plugins"]["rag"]["store_path"] = str(sr / "kb.json")
        cfg["plugins"]["context"]["events_dir"] = str(sr / "events")
    if plugins_root:
        cfg.setdefault("plugins", {}).setdefault("find", {})["root"] = plugins_root
    if seams:
        for pid, key, fn in seams:
            cfg.setdefault("plugins", {}).setdefault(pid, {})[key] = fn
    from tool_registry import ToolRegistry
    reg = ToolRegistry()
    host = build_host(reg, cfg, gate=gate)
    return reg, host, cfg


if __name__ == "__main__":
    reg, host, cfg = load_global_host()
    act = [r for r in host.activate_roster()]  # already activated; re-handed for report
    recs = {pid: host.get(pid).state for pid in
            ["dsh-mneme", "dsh-context", "dsh-agent-teams", "dsh-workflow",
             "dsh-find-plugin", "modsearch", "modlens", "dsh-browser", "dsh-genui",
             "dsh-at-file", "dsh-handbook", "dsh-rag-kb",
             "example-strategy", "example-rule", "example-backend", "rag-vector"]}
    active = sorted(k for k, v in recs.items() if v == "activated")
    print("global store_root:", cfg.get("store_root"))
    print("roster ids:", len(cfg.get("plugins", {}).get("roster", [])))
    print("active:", len(active), active)
    print("tools:", len(reg.tool_names), sorted(reg.tool_names))

