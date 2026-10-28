"""
Loop v2.0 Web Dashboard — FastAPI 完整后台

依赖: pip install fastapi uvicorn
启动: python webui.py [--port 8080]
浏览器打开 http://127.0.0.1:8080（默认 host 0.0.0.0）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from memory_store import PatternStore
from fastapi import FastAPI, Query, Header, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(title="Loop v2.0 Dashboard", version="2.0")

# ── Database ──────────────────────────────────────────────

# Configurable data dir + optional bearer-token auth.
#  - data dir: env LOOP_WEBUI_DATA_DIR or CLI --data-dir (default _HERE/data)
#  - write-auth token: env LOOP_WEBUI_TOKEN or CLI --token (absent = no auth, backward compat)
DEFAULT_HOST = "127.0.0.1"
_DEFAULT_DATA_DIR = str(_HERE / "data")
_API_TOKEN = None
_DATA_DIR = None


def set_token(token):
    """Enable/disable write-endpoint auth. None/empty -> auth off (backward compat)."""
    global _API_TOKEN
    _API_TOKEN = token if token else None


def set_data_dir(path):
    """Override _store() data dir. None -> fall back to default (_HERE/data)."""
    global _DATA_DIR
    _DATA_DIR = str(path) if path else None


def _data_dir():
    return _DATA_DIR or os.environ.get("LOOP_WEBUI_DATA_DIR") or _DEFAULT_DATA_DIR


def _store():
    return PatternStore(str(Path(_data_dir()) / "patterns.db"))


def _effective_token():
    """Effective auth token: programmatic set_token() first, then env fallback.

    Symmetric with _data_dir() env fallback so an operator can enable write-auth
    purely via LOOP_WEBUI_TOKEN without passing --token.
    """
    return _API_TOKEN or os.environ.get("LOOP_WEBUI_TOKEN") or None


async def _require_token(authorization: str = Header(default="")):
    """FastAPI dependency: when a token is configured, require it on protected routes."""
    token = _effective_token()
    if token is None:
        return
    if authorization != "Bearer " + token:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── API: Dashboard ─────────────────────────────────────────

@app.get("/api/dashboard")
def api_dashboard():
    s = _store()
    failures = s.load_failure_patterns()
    successes = s.load_success_patterns()
    rounds = s.get_rounds()
    runs = s.get_run_history(10)
    qstats = s.get_queue_stats()
    active = s.get_active_exclusion_rules()
    last_l2 = s.get_last_l2_analysis()

    freq = {}
    for f in failures:
        m = f.get("failure_mode", "UNKNOWN")
        freq[m] = freq.get(m, 0) + 1

    return {
        "total_rounds": len(rounds),
        "total_failures": len(failures),
        "total_successes": len(successes),
        "active_rules": len(active),
        "open_failures": len([f for f in failures if f.get("status") == "open"]),
        "resolved_failures": len([f for f in failures if f.get("status") == "resolved"]),
        "problem_queue": qstats,
        "health_score": last_l2.get("health_score", 0) if last_l2 else 0,
        "health_details": last_l2,
        "mode_frequency": freq,
        "recent_runs": runs[:5],
        "last_round": rounds[-1] if rounds else None,
    }


@app.get("/api/rounds")
def api_rounds(limit: int = Query(30, ge=1, le=200)):
    return _store().get_rounds()[-limit:]


@app.get("/api/failures")
def api_failures():
    return _store().load_failure_patterns()


@app.get("/api/successes")
def api_successes():
    return _store().load_success_patterns()


@app.get("/api/rules")
def api_rules():
    return _store().get_active_exclusion_rules()


@app.get("/api/queue")
def api_queue():
    s = _store()
    return {"stats": s.get_queue_stats(), "items": s.pull_problems(["queued", "recurring"], min_count=0)}


@app.get("/api/health")
def api_health(limit: int = Query(20, ge=1, le=100)):
    return _store().get_l2_analysis(limit)


@app.get("/api/runs")
def api_runs(limit: int = Query(20, ge=1, le=100)):
    return _store().get_run_history(limit)


@app.get("/api/corrections")
def api_corrections():
    return _store().load_corrections()


# ── API: Actions ───────────────────────────────────────────

@app.post("/api/rules/{rule_id}/approve", dependencies=[Depends(_require_token)])
def api_approve_rule(rule_id: str):
    s = _store()
    s.update_failure_status(rule_id, "resolved")
    return {"ok": True, "id": rule_id, "status": "resolved"}


@app.post("/api/rules/{rule_id}/reject", dependencies=[Depends(_require_token)])
def api_reject_rule(rule_id: str):
    s = _store()
    s.update_failure_status(rule_id, "monitoring")
    return {"ok": True, "id": rule_id, "status": "monitoring"}


@app.post("/api/patterns/{pattern_id}", dependencies=[Depends(_require_token)])
def api_update_pattern(pattern_id: str, body: dict):
    s = _store()
    exclusion_rule = body.get("exclusion_rule")
    status = body.get("status")
    if exclusion_rule or status:
        s.update_failure_status(pattern_id, status or "open",
                                exclusion_rule=exclusion_rule)
    return {"ok": True, "id": pattern_id}


@app.delete("/api/queue/{problem_id}", dependencies=[Depends(_require_token)])
def api_dismiss_problem(problem_id: str):
    s = _store()
    s.update_problem_status(problem_id, "resolved")
    return {"ok": True, "id": problem_id}


@app.post("/api/suggestions/{suggestion_id}/apply", dependencies=[Depends(_require_token)])
def api_apply_suggestion(suggestion_id: str):
    s = _store()
    s.update_suggestion_status(suggestion_id, "applied")
    return {"ok": True, "id": suggestion_id}


@app.get("/api/suggestions")
def api_suggestions():
    return _store().get_pending_suggestions()


# ── HTML Dashboard ─────────────────
# Front-end is a standalone static file (sloth_engine/webui/static/index.html).
# This decouples the UI from the backend JSON API; all /api/* endpoints are unchanged.
# Serve / and static assets via StaticFiles, paths resolved relative to _HERE
# (no host-absolute paths, per provenance rule).
_STATIC_DIR = _HERE / "webui" / "static"

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(_STATIC_DIR / "index.html"))


# ── CLI ────────────────────────────────────────────────────

def _build_parser():
    ap = argparse.ArgumentParser(description="Loop v2.0 Web Dashboard")
    ap.add_argument("--port", type=int, default=8080, help="Server port (default 8080)")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help="Bind host (default loopback %s; use 0.0.0.0 to expose)" % DEFAULT_HOST)
    ap.add_argument("--token", default=None,
                    help="Require this bearer token on write endpoints (env LOOP_WEBUI_TOKEN)")
    ap.add_argument("--data-dir", default=None,
                    help="Data dir for patterns.db (env LOOP_WEBUI_DATA_DIR; default sloth_engine/data)")
    return ap


def main():
    args = _build_parser().parse_args()
    os.environ.setdefault("LOOP_WEBUI_TOKEN", args.token or "")
    os.environ.setdefault("LOOP_WEBUI_DATA_DIR", args.data_dir or "")
    set_token(args.token)
    set_data_dir(args.data_dir)

    print("\n  Loop v2.0 Dashboard")
    print(f"  http://{args.host}:{args.port}")
    auth = "enabled" if _effective_token() else "disabled (no --token / LOOP_WEBUI_TOKEN)"
    print(f"  write-endpoint auth: {auth}")
    print("  Press Ctrl+C to stop\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()