"""DSH gap-fill plugin contract tests (Batch 1-3, G2..G11).

Self-contained contract suite for the 9 newly translated DSH-concept plugins
(dsh-context, dsh-agent-teams, dsh-workflow, modsearch, modlens, dsh-browser,
dsh-genui, dsh-at-file, dsh-handbook). Style mirrors test_plugin_system.py:
real PluginHost.load_all + activate_roster, dispatch with a payload dict,
assert ok + legacy fields. Keeps the 20-test baseline untouched (isolation).
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

from tool_registry import ToolRegistry


def _write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _host(cfg):
    from plugin_loader import PluginHost
    from plugin_roster import PluginRoster
    reg = ToolRegistry()
    host = PluginHost(ENGINE / "plugins", reg, roster=PluginRoster.from_config(cfg), config=cfg)
    host.discover()
    host.load_all()
    host.activate_roster()
    return reg, host


# G2 - dsh-context ---------------------------------------------------------
def test_dsh_context_tools():
    tmp = HERE / "_tmp_context"
    ev = tmp / "events"
    _write(ev / "r1.jsonl",
           json.dumps({"type": "loop_round", "ts": 1, "tokens": 1200}) + "\n" +
           json.dumps({"type": "task", "ts": 2, "total_tokens": 800}) + "\n")
    cfg = {"plugins": {"context": {"events_dir": str(ev), "usd_per_1k": 0.002},
                       "roster": [{"id": "dsh-context", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    for n in ("context_stats", "context_events", "context_tokens"):
        assert reg.get(n) is not None, n
    st = reg.dispatch("context_stats", {})
    assert st.get("ok") is True and st.get("event_count", 0) >= 2
    ev_out = reg.dispatch("context_events", {"limit": 5})
    assert ev_out.get("ok") is True and ev_out.get("count", 0) >= 2
    tk = reg.dispatch("context_tokens", {})
    assert tk.get("ok") is True and tk.get("estimated_tokens", 0) > 0
    assert isinstance(tk.get("estimated_cost_usd"), (int, float))


# G3 - dsh-agent-teams ------------------------------------------------------
def test_dsh_agent_teams_tools():
    cfg = {"plugins": {"roster": [{"id": "dsh-agent-teams", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    assert reg.get("team_plan") is not None
    assert reg.get("team_status") is not None
    p = reg.dispatch("team_plan", {"goal": "optimize ETH trailing exit"})
    assert p.get("ok") is True
    assert p.get("captain") and len(p.get("members", [])) >= 1
    assert len(p.get("tasks", [])) == len(p.get("members", []))
    assert reg.dispatch("team_status", {}).get("teams") is not None


# G4 - dsh-workflow ---------------------------------------------------------
def test_dsh_workflow_tools():
    cfg = {"plugins": {"roster": [{"id": "dsh-workflow", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    for n in ("workflow_create", "workflow_run", "workflow_get"):
        assert reg.get(n) is not None, n
    steps = [{"id": "S1", "name": "scene"},
             {"id": "S2", "name": "signal", "deps": ["S1"]},
             {"id": "S6", "name": "risk", "deps": ["S2"]}]
    cr = reg.dispatch("workflow_create", {"steps": steps})
    assert cr.get("ok") is True and cr.get("workflow_id")
    wid = cr["workflow_id"]
    assert cr.get("wf_status") == "created" and len(cr.get("steps", [])) == 3
    rr = reg.dispatch("workflow_run", {"workflow_id": wid})
    assert rr.get("ok") is True and rr.get("wf_status") == "ran"
    gr = reg.dispatch("workflow_get", {"workflow_id": wid})
    assert gr.get("ok") is True


# G6 - modsearch ------------------------------------------------------------
def test_modsearch_tools():
    tmp = HERE / "_tmp_modsearch"
    corpus = tmp / "corpus"
    _write(corpus / "eth.md",
           "ETH price action May 2026 shows a range breakdown with lower lows, "
           "then a squeeze. May 2026 ETH traded 2400 to 2900.")
    _write(corpus / "btc.md", "Bitcoin ranged sideways in low volatility months.")
    cfg = {"plugins": {"modsearch": {"corpus_dir": str(corpus)},
                       "roster": [{"id": "modsearch", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    assert reg.get("web_search") is not None
    assert reg.get("fetch_page") is not None
    sr = reg.dispatch("web_search", {"query": "ETH price action 2026", "topK": 5})
    assert sr.get("ok") is True and sr.get("count", 0) >= 1
    assert sr["results"][0]["score"] > 0 and "snippet" in sr["results"][0]
    fp = reg.dispatch("fetch_page", {"url": "https://example.com/x"})
    assert fp.get("ok") is False  # backend not configured (honest contract)


# G7 - modlens --------------------------------------------------------------
def test_modlens_tools():
    cfg = {"plugins": {"roster": [{"id": "modlens", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    assert reg.get("describe_image") is not None
    out = reg.dispatch("describe_image", {"path": str(HERE / "_nope_" / "missing.png")})
    # offline default + nonexistent path => backend-not-configured contract
    assert out.get("ok") is False
    assert "backend not configured" in str(out.get("error", ""))


# G8 - dsh-browser ----------------------------------------------------------
def test_dsh_browser_tools():
    cfg = {"plugins": {"roster": [{"id": "dsh-browser", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    for n in ("browser_read", "browser_click", "browser_status"):
        assert reg.get(n) is not None, n
    st = reg.dispatch("browser_status", {})
    assert st.get("ok") is False  # backend not configured
    rd = reg.dispatch("browser_read", {"url": "https://example.com"})
    assert rd.get("ok") is False and rd.get("target") == "https://example.com"
    ck = reg.dispatch("browser_click", {"selector": "a.buy"})
    assert ck.get("ok") is False and ck.get("selector") == "a.buy"


# G9 - dsh-genui ------------------------------------------------------------
def test_dsh_genui_tools():
    cfg = {"plugins": {"roster": [{"id": "dsh-genui", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    assert reg.get("render_panel") is not None
    out = reg.dispatch("render_panel", {"title": "PM loop 2026-05",
        "rows": [{"label": "month", "value": "2026-05"},
                 {"label": "net", "value": 3.5, "kind": "float"}]})
    assert out.get("ok") is True and out.get("row_count") == 2
    assert "PM loop 2026-05" in out.get("panel", "")
    assert "2026-05" in out.get("panel", "")


# G10 - dsh-at-file ---------------------------------------------------------
def test_dsh_at_file_tools():
    tmp = HERE / "_tmp_atfile"
    ws = tmp / "ws"
    _write(ws / "signals" / "sig.json", json.dumps({"side": "long"}))
    _write(ws / "data" / "csv" / "trades.csv", "ts,side\n")
    cfg = {"plugins": {"at_file": {"workspace_root": str(ws)},
                       "roster": [{"id": "dsh-at-file", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    assert reg.get("resolve_path") is not None
    assert reg.get("list_paths") is not None
    rp = reg.dispatch("resolve_path", {"ref": "signals/sig.json"})
    assert rp.get("ok") is True and rp.get("exists") is True and rp.get("is_file") is True
    lp = reg.dispatch("list_paths", {"pattern": "*.json"})
    assert lp.get("ok") is True and lp.get("count", 0) >= 1
    assert any(p.endswith("signals/sig.json") for p in lp.get("paths", []))


# G11 - dsh-handbook --------------------------------------------------------
def test_dsh_handbook_tools():
    cfg = {"plugins": {"roster": [{"id": "dsh-handbook", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    assert reg.get("handbook") is not None
    h = reg.dispatch("handbook", {"topic": "exit"})
    assert h.get("ok") is True and "EXIT" in h.get("markdown", "")
    bad = reg.dispatch("handbook", {"topic": "zzz-not-a-topic"})
    assert bad.get("ok") is False and len(bad.get("available", [])) >= 1
    empty = reg.dispatch("handbook", {})
    assert empty.get("ok") is False



# ===== Completion tests: G3/G4/G6/G7/G8 (real run + pluggable backends) =====

# G3-complete: team_run offline + pluggable executor_fn
def test_dsh_agent_teams_run_offline():
    cfg = {"plugins": {"roster": [{"id": "dsh-agent-teams", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    p = reg.dispatch("team_plan", {"goal": "optimize ETH trailing exit"})
    run = reg.dispatch("team_run", {"team_id": p["team_id"]})
    assert run.get("ok") is True
    assert run.get("run_state") == "done"
    assert run.get("tasks_done") == len(p["tasks"])
    assert set(run.get("results", {}).keys()) == {t["id"] for t in p["tasks"]}


def test_dsh_agent_teams_run_pluggable_executor():
    seen = []
    def exec_fn(member, task, prior):
        seen.append((task["id"], list(prior.keys())))
        return "did:" + task["task"][:8]
    cfg = {"plugins": {"agent-teams": {"executor_fn": exec_fn},
                       "roster": [{"id": "dsh-agent-teams", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    p = reg.dispatch("team_plan", {"goal": "optimize ETH trailing exit"})
    run = reg.dispatch("team_run", {"team_id": p["team_id"]})
    assert run.get("ok") is True and run.get("tasks_done") == len(p["tasks"])
    assert len(seen) == len(p["tasks"])
    assert all(v.startswith("did:") for v in run["results"].values())
    first = p["tasks"][0]["id"]
    assert any(tid != first and first in pkeys for tid, pkeys in seen)


# G4-complete: workflow_run respects deps (topo) + pluggable step_fn
def test_dsh_workflow_run_respects_deps_offline():
    cfg = {"plugins": {"roster": [{"id": "dsh-workflow", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    steps = [{"id": "S1", "name": "scene"}, {"id": "S2", "name": "signal", "deps": ["S1"]},
             {"id": "S3", "name": "filter", "deps": ["S2"]}]
    cr = reg.dispatch("workflow_create", {"steps": steps})
    rr = reg.dispatch("workflow_run", {"workflow_id": cr["workflow_id"]})
    assert rr.get("ok") is True and rr.get("wf_status") == "ran"
    order = rr.get("order", [])
    assert order.index("S1") < order.index("S2") < order.index("S3")
    assert set(rr.get("results", {}).keys()) == {"S1", "S2", "S3"}


def test_dsh_workflow_run_pluggable_stepfn():
    log = []
    def step_fn(step, prior):
        log.append((step["id"], list(prior.keys())))
        return "R:" + step["id"]
    cfg = {"plugins": {"dsh-workflow": {"step_fn": step_fn},
                       "roster": [{"id": "dsh-workflow", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    steps = [{"id": "S1", "name": "scene"}, {"id": "S2", "name": "signal", "deps": ["S1"]}]
    cr = reg.dispatch("workflow_create", {"steps": steps})
    rr = reg.dispatch("workflow_run", {"workflow_id": cr["workflow_id"]})
    assert rr.get("ok") is True
    assert rr.get("results") == {"S1": "R:S1", "S2": "R:S2"}
    assert any(i == "S2" and "S1" in p for i, p in log)


# G6-complete: pluggable search_fn backend + local-file fetch_page
def test_modsearch_pluggable_search_backend():
    def s_fn(query, topK):
        return [{"title": "canned", "url": "http://x", "snippet": "live: " + query, "score": 9.9}]
    cfg = {"plugins": {"modsearch": {"search_fn": s_fn},
                       "roster": [{"id": "modsearch", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    sr = reg.dispatch("web_search", {"query": "ETH", "topK": 3})
    assert sr.get("ok") is True and sr.get("engine") == "injected"
    assert sr["results"][0]["snippet"] == "live: ETH"


def test_modsearch_fetch_local_file():
    tmp = HERE / "_tmp_modsearch_fetch"
    f = tmp / "page.html"
    _write(f, "<html>local page</html>")
    cfg = {"plugins": {"modsearch": {}, "roster": [{"id": "modsearch", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    fp = reg.dispatch("fetch_page", {"url": str(f)})
    assert fp.get("ok") is True and "local page" in fp.get("body", "")


# G7-complete: pluggable describe_fn vision backend
def test_modlens_pluggable_describe_backend():
    def d_fn(path, question):
        return {"caption": "a bearish breakdown chart", "labels": ["trendline", "support"]}
    cfg = {"plugins": {"modlens": {"describe_fn": d_fn},
                       "roster": [{"id": "modlens", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    out = reg.dispatch("describe_image", {"path": "x.png", "question": "trend?"})
    assert out.get("ok") is True and out.get("caption") == "a bearish breakdown chart"
    assert "trendline" in out.get("labels", [])


# G8-complete: pluggable browser backend_fn (status/read/click)
def test_dsh_browser_pluggable_backend():
    def b_fn(action, target=None, selector=None):
        if action == "status":
            return {"alive": True, "url": "about:blank"}
        if action == "read":
            return {"html": "<html>live " + str(target) + "</html>", "title": "T"}
        if action == "click":
            return {"clicked": selector}
        return {"ok": False}
    cfg = {"plugins": {"dsh-browser": {"backend_fn": b_fn},
                       "roster": [{"id": "dsh-browser", "enabled": True, "trusted": True}]}}
    reg, host = _host(cfg)
    st = reg.dispatch("browser_status", {})
    assert st.get("ok") is True and st.get("alive") is True
    rd = reg.dispatch("browser_read", {"url": "https://eth"})
    assert rd.get("ok") is True and "live" in rd.get("html", "")
    ck = reg.dispatch("browser_click", {"selector": "a"})
    assert ck.get("ok") is True and ck.get("clicked") == "a"
