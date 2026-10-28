# -*- coding: utf-8 -*-
"""第2档自改码沙箱门禁原语 SelfModifyGate 单测."""
import json, sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from self_modify_gate import SelfModifyGate, PATCH_TYPES, DEFAULT_ALLOWED_SLICES


def _gate(tmp_path):
    # 沙箱: 用一个临时项目根(里面建 engine 目录) 避免污染生产
    proj = Path(tmp_path) / "proj"
    (proj / "sloth_engine").mkdir(parents=True, exist_ok=True)
    return proj, SelfModifyGate(proj, gate_tests=("tests",), pytest_timeout=120)

# ── patch 白名单校验 ─────────────────────────────────────────
def test_validate_rejects_unknown_type(tmp_path):
    proj, g = _gate(tmp_path)
    err, clean = g._validate_patch({"type": "exec", "target": "sloth_engine/x.py", "content": "1"})
    assert err and "不允许" in err

def test_validate_rejects_outside_slice(tmp_path):
    proj, g = _gate(tmp_path)
    err, clean = g._validate_patch({"type": "add_file", "target": "docs/x.md", "content": "# hi"})
    assert err and "授权切片" in err

def test_validate_rejects_escape(tmp_path):
    proj, g = _gate(tmp_path)
    # target 带 .. 逃逸
    err, clean = g._validate_patch({"type": "add_file", "target": "sloth_engine/../../x.py", "content": "x"})
    assert err

def test_validate_accepts_add_file_in_slice(tmp_path):
    proj, g = _gate(tmp_path)
    err, clean = g._validate_patch({"type": "add_file", "target": "sloth_engine/_new_util.py", "content": "# ok"})
    assert err is None and clean["type"] == "add_file"

# ── 沙箱暂存 ─────────────────────────────────────────────────
def test_stage_new_file(tmp_path):
    proj, g = _gate(tmp_path)
    p = {"type": "add_file", "target": "sloth_engine/_sandboxed_new.py", "content": "def f(): return 1"}
    sb = g._stage(p)
    assert sb is not None and sb.exists()

def test_stage_skips_existing(tmp_path):
    proj, g = _gate(tmp_path)
    (proj / "sloth_engine").joinpath("_existing.py").write_text("old", encoding="utf-8")
    p = {"type": "add_file", "target": "sloth_engine/_existing.py", "content": "new"}
    assert g._stage(p) is None   # 不改既有文件

# ── propose 门禁: 通过才提交, 失败丢弃 ────────────────────────
def test_propose_commit_on_green(tmp_path, monkeypatch):
    proj, g = _gate(tmp_path)
    patch = {"type": "add_file", "target": "sloth_engine/_ok_module.py", "content": "def ok(): return 1"}
    monkeypatch.setattr(g, "_run_gate", lambda p, sb: {"pass_count": 1, "fail_count": 0, "total": 1, "details": [{"field": "t", "passed": True}]})
    r = g.propose(patch)
    assert r.status == "committed" and r.committed is True
    assert (proj / "sloth_engine" / "_ok_module.py").exists()

def test_propose_reject_on_fail(tmp_path, monkeypatch):
    proj, g = _gate(tmp_path)
    patch = {"type": "add_file", "target": "sloth_engine/_bad_module.py", "content": "def bad(): raise 1"}
    monkeypatch.setattr(g, "_run_gate", lambda p, sb: {"pass_count": 0, "fail_count": 1, "total": 1, "details": [{"field": "t", "passed": False}]})
    r = g.propose(patch)
    assert r.status == "rejected"
    assert not (proj / "sloth_engine" / "_bad_module.py").exists()   # 未写入生产

def test_propose_reject_invalid_patch(tmp_path):
    proj, g = _gate(tmp_path)
    r = g.propose({"type": "exec"})
    assert r.status == "rejected"

# ── 参数/规则类 patch(数据层) ────────────────────────────────
def test_propose_edit_params_json(tmp_path, monkeypatch):
    proj, g = _gate(tmp_path)
    tgt = proj / "sloth_engine" / "params.json"
    tgt.write_text(json.dumps({"window": 20}), encoding="utf-8")
    patch = {"type": "edit_params", "target": "sloth_engine/params.json", "content": {"window": 30}}
    monkeypatch.setattr(g, "_run_gate", lambda p, sb: {"pass_count": 1, "fail_count": 0, "total": 1, "details": []})
    r = g.propose(patch)
    assert r.status == "committed"
    data = json.loads(tgt.read_text(encoding="utf-8"))
    assert data["window"] == 30

def test_propose_add_rule_json(tmp_path, monkeypatch):
    proj, g = _gate(tmp_path)
    tgt = proj / "sloth_engine" / "rules.json"
    tgt.write_text(json.dumps([{"signal_pattern": "a"}]), encoding="utf-8")
    patch = {"type": "add_rule", "target": "sloth_engine/rules.json", "content": {"signal_pattern": "b"}}
    monkeypatch.setattr(g, "_run_gate", lambda p, sb: {"pass_count": 1, "fail_count": 0, "total": 1, "details": []})
    r = g.propose(patch)
    assert r.status == "committed"
    data = json.loads(tgt.read_text(encoding="utf-8"))
    assert len(data) == 2 and data[1]["signal_pattern"] == "b"



# ── C3 read-before-write guard (deer-flow 契约借鉴) ──────────────────
def test_read_mark_rejects_stale_target(tmp_path, monkeypatch):
    """A concurrent write between read-mark and commit must fail closed."""
    proj, g = _gate(tmp_path)
    tgt = proj / "sloth_engine" / "params.json"
    tgt.write_text(json.dumps({"window": 20}), encoding="utf-8")
    patch = {"type": "edit_params", "target": "sloth_engine/params.json", "content": {"window": 30}}
    monkeypatch.setattr(g, "_run_gate", lambda p, sb: {"pass_count": 1, "fail_count": 0, "total": 1, "details": []})
    orig = SelfModifyGate._backup_and_commit
    def race(self, clean, sb):
        tgt.write_text(json.dumps({"window": 999, "intruder": True}), encoding="utf-8")
        return orig(self, clean, sb)
    monkeypatch.setattr(SelfModifyGate, "_backup_and_commit", race)
    r = g.propose(patch)
    assert r.status == "rejected"
    data = json.loads(tgt.read_text(encoding="utf-8"))
    assert data.get("intruder") is True          # concurrent write NOT clobbered
    assert data["window"] == 999                  # gate did not merge over it

def test_read_mark_allows_uncontended_commit(tmp_path, monkeypatch):
    proj, g = _gate(tmp_path)
    tgt = proj / "sloth_engine" / "params.json"
    tgt.write_text(json.dumps({"window": 20}), encoding="utf-8")
    patch = {"type": "edit_params", "target": "sloth_engine/params.json", "content": {"window": 30}}
    monkeypatch.setattr(g, "_run_gate", lambda p, sb: {"pass_count": 1, "fail_count": 0, "total": 1, "details": []})
    r = g.propose(patch)
    assert r.status == "committed"
    assert json.loads(tgt.read_text(encoding="utf-8"))["window"] == 30
