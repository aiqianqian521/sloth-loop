"""Feature flag system (port of Codex features five-stage lifecycle).

Codex models feature flags with an explicit lifecycle so a flag is never just a
boolean in the dark. This module adapts that design to sloth-loop:

  Stage.UNDEFINED -> not declared anywhere (treated as off, WARN on read)
  Stage.ENABLED   -> declared and on for this process
  Stage.DISABLED  -> declared and off for this process
  Stage.DEPRECATED-> still honour-able but scheduled for removal (WARN on read)
  Stage.REMOVED   -> hard-gone; reading it is an error

Resolution order (first hit wins):
  1. explicit process override  (enable()/disable()/set_stage())
  2. environment  LOOP_FEATURE_<NAME>=0/1
  3. config file  features.<name>.stage  (via load_config)
  4. the registered default stage

The whole thing is dependency-free and must never raise on read: an unknown flag
is reported as OFF with a debug log, matching the "features must not be able to
crash the loop" invariant.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

_log = logging.getLogger("sloth_engine")


class Stage(str, Enum):
    """Lifecycle stage of a feature (mirrors Codex FeatureStage)."""

    UNDEFINED = "undefined"
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"
    REMOVED = "removed"


_OFF_STAGES = {Stage.DISABLED, Stage.REMOVED, Stage.UNDEFINED}


@dataclass
class Feature:
    """A single named capability with a lifecycle stage and metadata."""

    name: str
    stage: Stage = Stage.DISABLED
    description: str = ""
    since: str = ""
    replaced_by: str = ""

    def is_on(self) -> bool:
        return self.stage in (Stage.ENABLED, Stage.DEPRECATED)


@dataclass
class FeatureConfigSource:
    """Where a flag's value came from (for diagnostics / audit)."""

    source: str  # "override" | "env" | "config" | "default"
    raw: Any = None


class Features:
    """Registry + resolver for feature flags.

    Usage::

        feats = Features()
        feats.register("context_fragment", stage=Stage.ENABLED)
        if feats.on("context_fragment"):
            ...
    """

    ENV_PREFIX = "LOOP_FEATURE_"

    def __init__(self, config: dict | None = None):
        self._features: dict[str, Feature] = {}
        self._overrides: dict[str, Stage] = {}
        self._config = (config or {}).get("features", {}) if config else {}

    # ---- registration ----
    def register(self, name: str, *, stage: Stage = Stage.DISABLED,
                 description: str = "", since: str = "",
                 replaced_by: str = "") -> Feature:
        feat = Feature(name=name, stage=stage, description=description,
                       since=since, replaced_by=replaced_by)
        self._features[name] = feat
        return feat

    def register_many(self, specs: Iterable[dict]) -> None:
        for spec in specs:
            self.register(
                spec["name"],
                stage=Stage(spec.get("stage", "disabled")),
                description=spec.get("description", ""),
                since=spec.get("since", ""),
                replaced_by=spec.get("replaced_by", ""),
            )

    # ---- overrides (process-level, highest priority) ----
    def enable(self, name: str) -> None:
        self._overrides[name] = Stage.ENABLED

    def disable(self, name: str) -> None:
        self._overrides[name] = Stage.DISABLED

    def set_stage(self, name: str, stage: Stage) -> None:
        self._overrides[name] = stage

    def clear_override(self, name: str) -> None:
        self._overrides.pop(name, None)

    def clear_all_overrides(self) -> None:
        self._overrides.clear()

    # ---- resolution ----
    def stage_of(self, name: str) -> Stage:
        if name in self._overrides:
            return self._overrides[name]

        env_key = self.ENV_PREFIX + name.upper()
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if env_val.strip() in ("1", "true", "on", "yes"):
                return Stage.ENABLED
            if env_val.strip() in ("0", "false", "off", "no"):
                return Stage.DISABLED

        cfg = self._config.get(name)
        if isinstance(cfg, dict) and "stage" in cfg:
            try:
                return Stage(str(cfg["stage"]).lower())
            except ValueError:
                _log.warning("[features] bad config stage for %s: %r", name, cfg["stage"])
        elif isinstance(cfg, bool):
            return Stage.ENABLED if cfg else Stage.DISABLED

        feat = self._features.get(name)
        if feat is None:
            _log.debug("[features] read of unregistered feature %r -> OFF", name)
            return Stage.UNDEFINED
        return feat.stage

    def source_of(self, name: str) -> FeatureConfigSource:
        if name in self._overrides:
            return FeatureConfigSource("override", self._overrides[name].value)
        env_key = self.ENV_PREFIX + name.upper()
        if os.environ.get(env_key) is not None:
            return FeatureConfigSource("env", os.environ.get(env_key))
        if name in self._config:
            return FeatureConfigSource("config", self._config[name])
        return FeatureConfigSource("default", None)

    def on(self, name: str) -> bool:
        """True if the feature is active. Never raises."""
        stage = self.stage_of(name)
        if stage == Stage.DEPRECATED:
            feat = self._features.get(name)
            rep = f" replaced_by={feat.replaced_by}" if feat and feat.replaced_by else ""
            _log.warning("[features] %s is DEPRECATED but still enabled.%s", name, rep)
        elif stage == Stage.REMOVED:
            _log.warning("[features] %s is REMOVED; treating as OFF", name)
        return stage in (Stage.ENABLED, Stage.DEPRECATED)

    def off(self, name: str) -> bool:
        return not self.on(name)

    # ---- introspection ----
    def snapshot(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for name in self._features:
            st = self.stage_of(name)
            out[name] = {
                "stage": st.value,
                "on": st in (Stage.ENABLED, Stage.DEPRECATED),
                "source": self.source_of(name).source,
                "description": self._features[name].description,
            }
        return out

    def enabled_names(self) -> list[str]:
        return [n for n in self._features if self.on(n)]

    def assert_no_removed(self) -> None:
        """Raise if any feature is read as REMOVED (used in strict test mode)."""
        for name in self._features:
            if self.stage_of(name) == Stage.REMOVED:
                raise RuntimeError(f"feature {name!r} is REMOVED but still referenced")
