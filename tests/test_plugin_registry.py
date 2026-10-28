"""测试 PluginRegistry + 增强版 manifest 校验 — P0-3。"""

import json
import sys
import tempfile
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

from plugin_manifest import (
    PluginManifest, PluginRegistry, RegistryEntry,
    load_manifest, validate, validate_warnings,
    parse_semver, semver_compatible,
    VALID_TYPES, _ID_RE,
)


# ── semver ──

def test_parse_semver_valid():
    assert parse_semver("1.2.3") == (1, 2, 3)
    assert parse_semver("0.1.0") == (0, 1, 0)
    assert parse_semver("10.20.30") == (10, 20, 30)


def test_parse_semver_invalid():
    assert parse_semver("not-a-version") is None
    assert parse_semver("1.2") is None
    assert parse_semver("") is None


def test_semver_compatible_exact():
    assert semver_compatible("1.2.3", "1.2.3") is True
    assert semver_compatible("1.2.3", "1.2.4") is False


def test_semver_compatible_gte():
    assert semver_compatible(">=1.0.0", "1.2.3") is True
    assert semver_compatible(">=2.0.0", "1.9.9") is False


def test_semver_compatible_caret():
    assert semver_compatible("^1.0.0", "1.9.9") is True
    assert semver_compatible("^1.0.0", "2.0.0") is False


def test_semver_compatible_empty():
    assert semver_compatible("", "1.0.0") is True
    assert semver_compatible("", "0.0.0") is True


# ── validate enhanced ──

def test_validate_invalid_semver():
    m = PluginManifest(id="test", version="not-semver", type="skill",
                       entry="entry.py", extension_points=["tool"])
    errs = validate(m, "1.0.0")
    assert any("not valid semver" in e for e in errs)


def test_validate_version_mismatch():
    m = PluginManifest(id="test", version="1.0.0", type="skill",
                       entry="entry.py", requires=">=2.0.0")
    errs = validate(m, "1.0.0")
    assert any("incompatible" in e for e in errs)


def test_validate_version_compatible():
    m = PluginManifest(id="test", version="1.0.0", type="skill",
                       entry="entry.py", requires=">=1.0.0")
    errs = validate(m, "1.5.0")
    assert not any("incompatible" in e for e in errs)


def test_validate_self_conflict():
    m = PluginManifest(id="myself", version="1.0.0", type="skill",
                       entry="entry.py", conflicts=["myself"])
    errs = validate(m)
    assert any("conflict with itself" in e for e in errs)


def test_validate_inject_not_list():
    m = PluginManifest(id="test", version="1.0.0", type="skill",
                       entry="entry.py")
    m.inject = "not-a-list"  # type: ignore
    errs = validate(m)
    assert any("inject must be a list" in e for e in errs)


# ── validate_warnings ──

def test_warn_no_description():
    m = PluginManifest(id="test", version="1.0.0", type="skill",
                       entry="entry.py")
    warns = validate_warnings(m)
    assert any("no description" in w for w in warns)


def test_warn_no_extension_points():
    m = PluginManifest(id="test", version="1.0.0", type="skill",
                       entry="entry.py", description="a test")
    warns = validate_warnings(m)
    assert any("no extension_points" in w for w in warns)


def test_warn_conflict_with_installed():
    m = PluginManifest(id="plugin-a", version="1.0.0", type="skill",
                       entry="entry.py", conflicts=["plugin-b"])
    warns = validate_warnings(m, {"plugin-b"})
    assert any("conflicts with installed plugin" in w for w in warns)


def test_no_warn_well_formed():
    m = PluginManifest(id="test", version="1.0.0", type="skill",
                       entry="entry.py", description="well formed",
                       extension_points=["tool"])
    warns = validate_warnings(m)
    assert warns == []


# ── load_manifest ──

def test_load_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "manifest.json"
        p.write_text(json.dumps({
            "id": "my-plugin",
            "version": "1.0.0",
            "type": "memory",
            "entry": "entry.py",
            "requires": ">=0.5.0",
            "conflicts": ["other-plugin"],
        }))
        m = load_manifest(str(p))
        assert m.id == "my-plugin"
        assert m.requires == ">=0.5.0"
        assert m.conflicts == ["other-plugin"]


# ── PluginRegistry ──

def _make_plugin_dir(root: Path, pkg_name: str, manifest_data: dict) -> Path:
    d = root / pkg_name
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps(manifest_data))
    (d / "entry.py").write_text("# stub")
    return d


def test_registry_scan():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_plugin_dir(root, "p1", {
            "id": "plugin-one", "version": "1.0.0",
            "type": "skill", "entry": "entry.py",
            "extension_points": ["tool"],
        })
        _make_plugin_dir(root, "p2", {
            "id": "plugin-two", "version": "2.0.0",
            "type": "memory", "entry": "entry.py",
            "extension_points": ["memory_store"],
        })

        reg = PluginRegistry(root, core_version="1.0.0")
        count = reg.scan()
        assert count == 2
        assert reg.valid_count == 2
        assert reg.total_count == 2


def test_registry_skip_invalid():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_plugin_dir(root, "bad", {
            "id": "bad-plugin", "version": "not-semver",
            "type": "unknown-type", "entry": "",
        })

        reg = PluginRegistry(root)
        count = reg.scan()
        assert count == 0  # invalid
        assert reg.total_count == 1
        entry = reg.get("bad-plugin")
        assert entry is not None
        assert entry.valid is False
        assert len(entry.errors) > 0


def test_registry_list_by_type():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_plugin_dir(root, "sk", {
            "id": "sk1", "version": "1.0.0",
            "type": "skill", "entry": "entry.py",
        })
        _make_plugin_dir(root, "mm", {
            "id": "mm1", "version": "1.0.0",
            "type": "memory", "entry": "entry.py",
        })

        reg = PluginRegistry(root)
        reg.scan()
        skills = reg.list_by_type("skill")
        assert len(skills) == 1
        assert skills[0].manifest.id == "sk1"


def test_registry_no_plugins_dir():
    with tempfile.TemporaryDirectory() as tmp:
        reg = PluginRegistry(Path(tmp) / "nonexistent")
        count = reg.scan()
        assert count == 0
        assert len(reg.scan_errors) > 0


def test_registry_summary():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_plugin_dir(root, "p1", {
            "id": "p1", "version": "1.0.0",
            "type": "skill", "entry": "entry.py",
            "description": "test plugin",
        })

        reg = PluginRegistry(root, core_version="2.0.0")
        reg.scan()
        s = reg.summary()
        assert "p1" in s
        assert "2.0.0" in s
        assert "1/1 valid" in s


def test_registry_duplicate_id():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_plugin_dir(root, "a", {
            "id": "dup", "version": "1.0.0",
            "type": "skill", "entry": "entry.py",
        })
        _make_plugin_dir(root, "b", {
            "id": "dup", "version": "2.0.0",
            "type": "memory", "entry": "entry.py",
        })

        reg = PluginRegistry(root)
        count = reg.scan()
        assert count == 1  # second duplicate id skipped, only first registered
        assert "duplicate id" in str(reg.scan_errors)


def test_registry_checksum():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_plugin_dir(root, "p1", {
            "id": "p1", "version": "1.0.0",
            "type": "skill", "entry": "entry.py",
        })

        reg = PluginRegistry(root)
        reg.scan()
        entry = reg.get("p1")
        assert entry.checksum != ""
        assert len(entry.checksum) == 16  # first 16 hex chars of sha256

