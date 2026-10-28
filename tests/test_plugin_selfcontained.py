"""Forward tests for plugin config self-containment (C2 regression guard)."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "sloth_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import plugin_bootstrap as pb


def test_load_global_config_resolves_relative_paths():
    cfg = pb.load_global_config()
    assert cfg, "global config must load"
    sr = cfg.get("store_root")
    assert sr, "store_root missing"
    assert Path(sr).is_absolute(), ("store_root not absolute: " + sr)
    root = str(pb._ENGINE.parent)
    assert str(Path(sr)).startswith(root), ("store_root escapes repo: " + sr)


def test_plugin_config_has_no_hardcoded_source_machine_paths():
    text = pb.GLOBAL_CONFIG.read_text(encoding="utf-8")
    assert "E:/loop-runtime" not in text, "hard-coded loop-runtime path remains"
    # Any drive-absolute path (E:\..., C:/...) is a source-machine leak: the
    # shipped config must stay relative or placeholder-based.  The guard
    # matches the *shape*, never a machine's literal path.
    m = re.search(r"\b[A-Za-z]:[\\/]", text)
    assert m is None, ("source-machine drive path remains: "
                       + text[max(0, m.start() - 20):m.start() + 40])


def test_shared_store_root_env_override(monkeypatch):
    monkeypatch.setenv("LOOP_PLUGIN_STORE_ROOT", str(pb._ENGINE.parent / "_aux" / "psr"))
    val = pb.shared_store_root({})
    assert val.name == "psr" and val.parent.name == "_aux", val


def test_resolve_global_paths_makes_absolute(tmp_path):
    cfg = {"store_root": "rt/plugin-global",
           "plugins": {"memory": {"mneme_store": "rt/plugin-global/mneme.json"}}}
    out = pb.resolve_global_paths(cfg)
    assert str(Path(out["store_root"])).startswith(str(pb._ENGINE.parent))
    mem = out.get("plugins", {}).get("memory", {})
    assert Path(mem["mneme_store"]).is_absolute()
    assert str(Path(mem["mneme_store"])).startswith(str(pb._ENGINE.parent))
