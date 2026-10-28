"""dsh-fs 插件单元测试 (fenced read/write/edit/stat)。"""
from __future__ import annotations

import importlib.util as _ilu
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = _ilu.spec_from_file_location(
        "t_dsh_fs", _ROOT / "sloth_engine/plugins/skill/dsh-fs/entry.py")
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fs(tmp_path):
    m = _load()
    fs = m._Fs({"plugins": {"fs": {"workspace_root": str(tmp_path)}}})
    m._FS = fs
    return m, fs


def test_fs_write_create_and_read_line_numbers(tmp_path):
    m, fs = _fs(tmp_path)
    r = fs.write("a.txt", "line1\nline2\nline3\n")
    assert r["ok"] and r["action"] == "created"
    rr = fs.read("a.txt")
    assert rr["ok"] and rr["total_lines"] == 3
    assert "1\tline1" in rr["content"]


def test_fs_read_pagination_and_limit(tmp_path):
    m, fs = _fs(tmp_path)
    fs.write("a.txt", "l1\nl2\nl3\nl4\nl5\n")
    rr = fs.read("a.txt", offset=2, limit=2)
    assert rr["shown"] == 2 and rr["total_lines"] == 5
    assert "[lines 2-3 of 5" in rr["content"]


def test_fs_read_missing_and_not_a_file(tmp_path):
    m, fs = _fs(tmp_path)
    r = m._fs_read({"file_path": "nope.txt"})
    assert r["ok"] is False and r["code"] == "FS_NOT_FOUND"
    (tmp_path / "adir").mkdir()
    r2 = m._fs_read({"file_path": "adir"})
    assert r2["ok"] is False and r2["code"] == "FS_NOT_A_FILE"


def test_fs_write_atomic_and_overwrite_flag(tmp_path):
    m, fs = _fs(tmp_path)
    fs.write("a.txt", "v1")
    fs.write("a.txt", "v2")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "v2"
    r = m._fs_write({"file_path": "a.txt", "content": "v3", "overwrite": False})
    assert r["ok"] is False and r["code"] == "FS_EXISTS"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "v2"


def test_fs_edit_unique_and_replace_all(tmp_path):
    m, fs = _fs(tmp_path)
    fs.write("a.txt", "foo bar foo\n")
    r = fs.edit("a.txt", "bar", "BAR")
    assert r["ok"] and r["replacements"] == 1
    r2 = fs.edit("a.txt", "foo", "FOO", replace_all=True)
    assert r2["ok"] and r2["replacements"] == 2
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "FOO BAR FOO\n"


def test_fs_edit_ambiguous_and_no_match(tmp_path):
    m, fs = _fs(tmp_path)
    fs.write("a.txt", "abc abc\n")
    try:
        fs.edit("a.txt", "abc", "x")
        assert False, "expected FS_AMBIGUOUS"
    except m.FsError as exc:
        assert exc.code == "FS_AMBIGUOUS"
    try:
        fs.edit("a.txt", "zzz", "x")
        assert False, "expected FS_NO_MATCH"
    except m.FsError as exc:
        assert exc.code == "FS_NO_MATCH"


def test_fs_path_fencing_rejects_escape(tmp_path):
    m, fs = _fs(tmp_path)
    (tmp_path / "ok.txt").write_text("hi", encoding="utf-8")
    # relative path stays inside
    assert fs.stat("ok.txt")["exists"] is True
    # absolute path outside the fence is refused
    escaped = tmp_path.parent / "outside.txt"
    r = m._fs_read({"file_path": str(escaped)})
    assert r["ok"] is False and r["code"] == "FS_OUT_OF_SCOPE"


def test_fs_stat_missing_returns_exists_false(tmp_path):
    m, fs = _fs(tmp_path)
    r = fs.stat("none.txt")
    assert r["ok"] is True and r["exists"] is False


def test_fs_bad_args(tmp_path):
    m, fs = _fs(tmp_path)
    fs.write("a.txt", "x\n")
    for bad in ({"file_path": "", "content": "x"}, {"file_path": "a.txt", "content": None}):
        r = m._fs_write(bad)
        assert r["ok"] is False
    r = m._fs_read({"file_path": "a.txt", "offset": 0})
    assert r["ok"] is False and r["code"] == "FS_BAD_ARG"
