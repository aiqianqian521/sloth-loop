"""WEBUI 增强：鉴权 / 数据隔离(可配置 data-dir) / 部署(默认 loopback)。

先测后写：本文件先于实现落盘。设计契约：
 - webui.set_token(token)  设置模块鉴权 token（None/空=关闭鉴权，向后兼容）。
 - webui.set_data_dir(dir) 设置 _store() 的数据目录（None=回退默认 _HERE/data）。
 - webui.DEFAULT_HOST == "127.0.0.1"（默认不对外，显式 --host 才绑定外部）。
 - 配置 token 后，写端点缺/错误 Bearer 返回 401；正确 Bearer 返回 200。
 - 读端点保持开放（结合默认 loopback 边界）。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "sloth_engine"))

import webui

# (path, method, json_body_or_None)
WRITE_ENDPOINTS = [
    ("/api/rules/no_such/approve", "post", None),
    ("/api/rules/no_such/reject", "post", None),
    ("/api/patterns/no_such", "post", {}),
    ("/api/queue/no_such", "delete", None),
    ("/api/suggestions/no_such/apply", "post", None),
]


@pytest.fixture(autouse=True)
def _reset_webui(tmp_path):
    webui.set_token(None)
    webui.set_data_dir(str(tmp_path))
    yield
    webui.set_token(None)
    webui.set_data_dir(None)


def _call(client, method, path, body, **kw):
    if body is not None:
        return getattr(client, method)(path, json=body, **kw)
    return getattr(client, method)(path, **kw)


def test_write_endpoints_401_without_token_when_configured():
    webui.set_token("s3cret")
    from fastapi.testclient import TestClient
    client = TestClient(webui.app)
    for path, method, body in WRITE_ENDPOINTS:
        resp = _call(client, method, path, body)
        assert resp.status_code == 401, f"{method.upper()} {path} -> {resp.status_code}"


def test_write_endpoints_401_with_wrong_token():
    webui.set_token("s3cret")
    from fastapi.testclient import TestClient
    client = TestClient(webui.app)
    for path, method, body in WRITE_ENDPOINTS:
        resp = _call(client, method, path, body, headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401, f"{method.upper()} {path} -> {resp.status_code}"


def test_write_endpoints_200_with_correct_bearer():
    webui.set_token("s3cret")
    from fastapi.testclient import TestClient
    client = TestClient(webui.app)
    for path, method, body in WRITE_ENDPOINTS:
        resp = _call(client, method, path, body, headers={"Authorization": "Bearer s3cret"})
        assert resp.status_code == 200, f"{method.upper()} {path} -> {resp.status_code}"


def test_write_endpoints_open_when_no_token_configured():
    from fastapi.testclient import TestClient
    client = TestClient(webui.app)
    for path, method, body in WRITE_ENDPOINTS:
        resp = _call(client, method, path, body)
        assert resp.status_code == 200, f"{method.upper()} {path} -> {resp.status_code}"


def test_store_default_dir_is_here_data(tmp_path):
    webui.set_data_dir(None)
    expected = Path(webui._HERE) / "data" / "patterns.db"
    # Assert the resolved default path directly (cycle-39 A): calling
    # _store() here would create sloth_engine/data/patterns.db inside the
    # checkout as a test side effect.  Same expression _store() uses.
    assert Path(webui._data_dir()) / "patterns.db" == expected


def test_store_uses_configured_data_dir(tmp_path):
    webui.set_data_dir(str(tmp_path))
    store = webui._store()
    db = Path(store.db_path)
    assert str(db).startswith(str(tmp_path))
    assert db.exists()


def test_default_host_is_loopback():
    assert webui.DEFAULT_HOST == "127.0.0.1"


def test_cli_flags_present():
    ap = webui._build_parser()
    ns = ap.parse_args(["--token", "t", "--data-dir", "x", "--host", "0.0.0.0"])
    assert ns.token == "t"
    assert ns.data_dir == "x"
    assert ns.host == "0.0.0.0"


def test_index_still_served():
    webui.set_token("s3cret")
    from fastapi.testclient import TestClient
    client = TestClient(webui.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "html" in resp.headers.get("content-type", "").lower() or "<script" in resp.text


def test_env_token_enables_write_auth(monkeypatch, tmp_path):
    # env LOOP_WEBUI_TOKEN 应像 --token 一样启用写端点鉴权（与 LOOP_WEBUI_DATA_DIR 对称）。
    monkeypatch.setenv("LOOP_WEBUI_TOKEN", "envsecret")
    # 不调用 set_token；鉴权应完全来自 env 回退链
    from fastapi.testclient import TestClient
    client = TestClient(webui.app)
    for path, method, body in WRITE_ENDPOINTS:
        resp = _call(client, method, path, body)
        assert resp.status_code == 401, f"{method.upper()} {path} -> {resp.status_code} (env token not honored)"
        ok = _call(client, method, path, body, headers={"Authorization": "Bearer envsecret"})
        assert ok.status_code == 200, f"{method.upper()} {path} -> {ok.status_code}"
