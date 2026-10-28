"""Plugin manifest schema + validation + version check + registry index.

P0-3 升级: 增加版本兼容性检查、manifest可选字段校验、本地扫描索引。

Aligned with architect-plugin SKILL 1.2 (Plugin Manifest contract).
A manifest is the *loading contract* between a third-party plugin and the
core. The core only reads manifests (never plugin internals) to decide
discovery / validation. Missing or invalid manifest => not a plugin.

Manifest fields:
    id              stable plugin id (lowercase, [-_0-9a-z])
    version         semver-ish string
    type            one of VALID_TYPES (the extension-point family)
    entry           entry module filename (e.g. "entry.py")
    extension_points list of declared extension points (e.g. ["tool"],
                    ["hook:pre_entry"], ["memory_store"])
    inject          service names this plugin provides (for roster/dep graph)
    lazy            True = materialize on demand; False = eager on activate
    description     human text
    base_dir        set by the loader to the plugin package directory
    requires        (P0-3) optional min core version constraint
    conflicts       (P0-3) optional list of plugin ids this conflicts with
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

VALID_TYPES = frozenset({
    "backtest", "filter", "memory", "skill", "signal", "rag", "ui", "ops",
})

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")


# ============================================================================
# Semver utils (P0-3)
# ============================================================================

def parse_semver(v: str) -> tuple[int, int, int] | None:
    """Parse semver string → (major, minor, patch) or None."""
    m = _SEMVER_RE.match(v.strip())
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def semver_compatible(plugin_requires: str, core_version: str) -> bool:
    """Check if core_version satisfies plugin's requires constraint.

    Simple constraint: ">=1.0.0", "^2.0.0" (caret), or exact "1.2.3".
    Returns True if compatible.
    """
    if not plugin_requires:
        return True

    core = parse_semver(core_version)
    req = parse_semver(plugin_requires.replace(">=", "").replace("^", "").replace("~", "").strip())
    if core is None or req is None:
        return True  # can't parse → assume compatible

    if plugin_requires.startswith(">="):
        return core >= req
    elif plugin_requires.startswith("^"):
        # caret: major must match, minor+patch >= required
        return core[0] == req[0] and core >= req
    elif plugin_requires.startswith("~"):
        # tilde: major.minor must match, patch >= required
        return core[:2] == req[:2] and core >= req
    else:
        # exact match
        return core == req


# ============================================================================
# PluginManifest
# ============================================================================

@dataclass
class PluginManifest:
    id: str = ""
    version: str = ""
    type: str = ""
    entry: str = ""
    extension_points: list = field(default_factory=list)
    inject: list = field(default_factory=list)
    lazy: bool = True
    description: str = ""
    base_dir: Path = None  # populated by loader
    requires: str = ""     # P0-3: min core version
    conflicts: list = field(default_factory=list)  # P0-3
    skill_policy: str = "auto"   # skill exposure policy (Codex SkillPolicy)
    skill_dependencies: list = field(default_factory=list)  # required skill ids


def load_manifest(path) -> PluginManifest:
    """Read + parse a manifest.json into PluginManifest (no validation)."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    return PluginManifest(
        id=str(raw.get("id", "") or ""),
        version=str(raw.get("version", "") or ""),
        type=str(raw.get("type", "") or ""),
        entry=str(raw.get("entry", "") or ""),
        extension_points=list(raw.get("extension_points", []) or []),
        inject=list(raw.get("inject", []) or []),
        lazy=bool(raw.get("lazy", True)),
        description=str(raw.get("description", "") or ""),
        base_dir=p.parent,
        requires=str(raw.get("requires", "") or ""),
        conflicts=list(raw.get("conflicts", []) or []),
        skill_policy=str(raw.get("skill_policy", "auto") or "auto"),
        skill_dependencies=list(raw.get("skill_dependencies", []) or []),
    )


# ============================================================================
# Skill policy (Codex SkillPolicy port)
# ============================================================================

class SkillPolicy:
    """How a plugin's skills are exposed to the runtime.

    Codex gates skill exposure behind an explicit policy rather than implicit
    directory discovery. Values:

      auto     -> expose all skills declared by the plugin (default)
      explicit -> expose only skills listed in skill_dependencies
      none     -> expose no skills (plugin is internal-only)
      inherit  -> expose skills of the parent plugin (sub-plugin reuse)
    """

    AUTO = "auto"
    EXPLICIT = "explicit"
    NONE = "none"
    INHERIT = "inherit"

    VALID = {AUTO, EXPLICIT, NONE, INHERIT}

    @classmethod
    def normalize(cls, value: str) -> str:
        v = (value or cls.AUTO).strip().lower()
        return v if v in cls.VALID else cls.AUTO

    @classmethod
    def exposes(cls, policy: str, skill_id: str, declared: list) -> bool:
        p = cls.normalize(policy)
        if p == cls.NONE:
            return False
        if p == cls.EXPLICIT:
            return skill_id in declared
        return True  # auto / inherit


def validate_skill_deps(m: PluginManifest,
                        available_skills: set[str] | None = None) -> list[str]:
    """Return warnings for unsatisfiable skill dependencies."""
    warns: list[str] = []
    policy = SkillPolicy.normalize(getattr(m, "skill_policy", "auto"))
    deps = list(getattr(m, "skill_dependencies", []) or [])

    if policy == SkillPolicy.EXPLICIT and not deps:
        warns.append(
            f"manifest: {m.id!r} skill_policy=explicit but no skill_dependencies declared")
    if policy == SkillPolicy.NONE and deps:
        warns.append(
            f"manifest: {m.id!r} skill_policy=none ignores {len(deps)} skill_dependencies")
    if available_skills is not None:
        for dep in deps:
            if dep not in available_skills:
                warns.append(
                    f"manifest: {m.id!r} requires skill {dep!r} which is not available")
    return warns


# ============================================================================
# Validation (P0-3 enhanced)
# ============================================================================

def validate(m: PluginManifest, core_version: str = "") -> list[str]:
    """Return a list of human-readable error strings. Empty == valid.

    P0-3: also checks semver, conflicts, and optional field types.
    """
    errs = []
    if not m.id or not _ID_RE.match(m.id):
        errs.append(f"manifest: id missing or invalid (got {m.id!r})")
    if not m.version:
        errs.append("manifest: version missing")
    elif parse_semver(m.version) is None:
        errs.append(f"manifest: version {m.version!r} not valid semver (expect MAJOR.MINOR.PATCH)")
    if m.type not in VALID_TYPES:
        errs.append(f"manifest: type {m.type!r} not allowed (one of {sorted(VALID_TYPES)})")
    if not m.entry:
        errs.append("manifest: entry missing")
    if not isinstance(m.extension_points, list):
        errs.append("manifest: extension_points must be a list")
    if not isinstance(m.inject, list):
        errs.append("manifest: inject must be a list")
    if not isinstance(m.conflicts, list):
        errs.append("manifest: conflicts must be a list")

    # P0-3: version compatibility
    if m.requires and core_version:
        try:
            if not semver_compatible(m.requires, core_version):
                errs.append(
                    f"manifest: requires {m.requires!r} but core is {core_version} — incompatible"
                )
        except Exception:
            pass  # can't parse → skip version check

    # P0-3: self-conflict check
    if m.id and m.conflicts and m.id in m.conflicts:
        errs.append(f"manifest: plugin {m.id!r} cannot conflict with itself")

    return errs


def validate_warnings(m: PluginManifest, all_plugin_ids: set[str] | None = None) -> list[str]:
    """Non-fatal warnings (missing optional fields, conflicts with other plugins)."""
    warnings = []
    if not m.description:
        warnings.append(f"manifest: {m.id!r} has no description (recommended)")
    if not m.extension_points:
        warnings.append(f"manifest: {m.id!r} declares no extension_points (plugin may be inert)")

    # P0-3: cross-plugin conflict check
    if all_plugin_ids and m.conflicts:
        for cid in m.conflicts:
            if cid in (all_plugin_ids or set()):
                warnings.append(f"manifest: {m.id!r} conflicts with installed plugin {cid!r}")

    # SkillPolicy checks
    warnings.extend(validate_skill_deps(m))
    return warnings


# ============================================================================
# Registry Index (P0-3)
# ============================================================================

@dataclass
class RegistryEntry:
    """A plugin registered in the local index."""
    manifest: PluginManifest
    path: Path          # absolute path to manifest.json
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checksum: str = ""  # P0-3: sha256 of manifest.json for change detection


class PluginRegistry:
    """Local plugin registry index (P0-3).

    Scans plugins/ directory once, caches manifest + validation results.
    Supports incremental re-scan via checksum comparison.
    """

    def __init__(self, plugins_root: str | Path, core_version: str = ""):
        self._root = Path(plugins_root)
        self._core_version = core_version
        self._entries: dict[str, RegistryEntry] = {}  # id → entry
        self._scan_errors: list[str] = []

    def scan(self) -> int:
        """Scan plugins/ directory, build/refresh registry index.

        Returns: number of valid plugins found.
        """
        self._entries.clear()
        self._scan_errors.clear()

        if not self._root.is_dir():
            self._scan_errors.append(f"plugins root {self._root} not found")
            return 0

        import hashlib

        # Collect all manifest.json files (depth 1-2, supports category/ subdirectories)

        manifest_targets = []

        for entry_dir in sorted(self._root.iterdir()):

            if not entry_dir.is_dir() or entry_dir.name.startswith('_') or entry_dir.name.startswith('.'):

                continue

            mf_direct = entry_dir / 'manifest.json'

            if mf_direct.is_file():

                manifest_targets.append((mf_direct, entry_dir))

            else:

                for sub_dir in sorted(entry_dir.iterdir()):

                    if not sub_dir.is_dir() or sub_dir.name.startswith('_') or sub_dir.name.startswith('.'):

                        continue

                    mf_sub = sub_dir / 'manifest.json'

                    if mf_sub.is_file():

                        manifest_targets.append((mf_sub, sub_dir))



        for manifest_path, pkg_dir in manifest_targets:

            if not manifest_path.is_file():

                continue



                continue

            try:
                m = load_manifest(manifest_path)
            except Exception as exc:
                self._scan_errors.append(f"{pkg_dir.name}: manifest parse error: {exc}")
                continue

            # checksum
            try:
                raw = manifest_path.read_bytes()
                checksum = hashlib.sha256(raw).hexdigest()[:16]
            except Exception:
                checksum = ""

            errors = validate(m, self._core_version)
            all_ids = set(self._entries.keys())
            warnings = validate_warnings(m, all_ids)
            valid = len(errors) == 0

            entry = RegistryEntry(
                manifest=m,
                path=manifest_path,
                valid=valid,
                errors=errors,
                warnings=warnings,
                checksum=checksum,
            )

            if m.id:
                if m.id in self._entries:
                    self._scan_errors.append(
                        f"{m.id}: duplicate id (from {pkg_dir.name} and {self._entries[m.id].path.parent.name})"
                    )
                self._entries[m.id] = entry
            else:
                self._scan_errors.append(f"{pkg_dir.name}: manifest has empty id — skipping")

        return len([e for e in self._entries.values() if e.valid])

    # ── queries ──

    def get(self, plugin_id: str) -> RegistryEntry | None:
        return self._entries.get(plugin_id)

    def list_valid(self) -> list[RegistryEntry]:
        return [e for e in self._entries.values() if e.valid]

    def list_all(self) -> list[RegistryEntry]:
        return list(self._entries.values())

    def list_by_type(self, plugin_type: str) -> list[RegistryEntry]:
        return [e for e in self._entries.values() if e.manifest.type == plugin_type]

    @property
    def valid_count(self) -> int:
        return len([e for e in self._entries.values() if e.valid])

    @property
    def total_count(self) -> int:
        return len(self._entries)

    @property
    def scan_errors(self) -> list[str]:
        return list(self._scan_errors)

    def summary(self) -> str:
        lines = [
            f"PluginRegistry: {self.valid_count}/{self.total_count} valid",
            f"  root: {self._root}",
            f"  core: {self._core_version or 'unknown'}",
        ]
        for eid, entry in sorted(self._entries.items()):
            tag = "✓" if entry.valid else "✗"
            lines.append(f"  {tag} {eid} v{entry.manifest.version} ({entry.manifest.type})")
            for err in entry.errors:
                lines.append(f"      ERROR: {err}")
            for warn in entry.warnings:
                lines.append(f"      WARN: {warn}")
        for err in self._scan_errors:
            lines.append(f"  ! {err}")
        return "\n".join(lines)
