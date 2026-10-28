"""Worker P2-A - WebUI static front-end extraction tests.

After refactor:
 - webui.py no longer embeds a big ``INDEX_HTML`` triple-quoted ``<html>`` block.
 - the front-end lives at sloth_engine/webui/static/index.html.
 - FastAPI routes (``/`` + all ``/api/*``) preserved; ``/`` served from the static file.
"""
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBUI_PY = REPO_ROOT / "sloth_engine" / "webui.py"
STATIC_HTML = REPO_ROOT / "sloth_engine" / "webui" / "static" / "index.html"

sys.path.insert(0, str(REPO_ROOT / "sloth_engine"))


@pytest.fixture(autouse=True)
def _isolate_webui_data(tmp_path):
    """cycle-39 A: never let WebUI tests build sloth_engine/data/patterns.db."""
    import webui
    webui.set_token(None)
    webui.set_data_dir(str(tmp_path))
    yield
    webui.set_token(None)
    webui.set_data_dir(None)


# ---- a) static file presence & no Python-slice remnants --------------------

def test_static_index_exists_and_no_python_slice():
    assert STATIC_HTML.exists(), "missing static index.html"
    html = STATIC_HTML.read_text(encoding="utf-8")
    assert "<html" in html
    bad = re.findall(r"\[\s*:\s*\d+\s*\]", html)
    assert not bad, "Python slice remnants in static html: %s" % bad


def test_static_uses_js_slice():
    html = STATIC_HTML.read_text(encoding="utf-8")
    assert ".slice(0," in html


def test_static_contains_core_js_logic():
    html = STATIC_HTML.read_text(encoding="utf-8")
    for token in ("const API = '/api'", "/dashboard", "switchTab", "loadDashboard", "fetch"):
        assert token in html, "static html missing JS token %r" % token


# ---- b) webui.py no longer embeds the inline html block ---------------------

def test_webui_no_inline_html_in_py():
    src = WEBUI_PY.read_text(encoding="utf-8")
    assert "INDEX_HTML" not in src
    assert "<!DOCTYPE html>" not in src
    assert "<html" not in src


# ---- c) FastAPI routes preserved --------------------------------------------

def test_fastapi_routes_preserved():
    import webui
    paths = [r.path for r in webui.app.routes]
    assert "/" in paths
    for ep in ("/api/dashboard", "/api/rounds", "/api/failures", "/api/successes",
               "/api/rules", "/api/queue", "/api/health", "/api/runs",
               "/api/corrections", "/api/suggestions"):
        assert ep in paths, "route %s missing" % ep


# ---- d) live TestClient against static file (no real DB required) ------------

def test_index_returns_html():
    import webui
    from fastapi.testclient import TestClient
    client = TestClient(webui.app)
    resp = client.get("/")
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "html" in ct
    assert "<html" in resp.text or "<script" in resp.text


def test_api_health_endpoint_not_404():
    import webui
    from fastapi.testclient import TestClient
    client = TestClient(webui.app)
    resp = client.get("/api/health")
    assert resp.status_code != 404
