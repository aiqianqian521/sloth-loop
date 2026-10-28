"""
配置加载工具 —— 零依赖优先。

背景 (OODA R1 发现):
  原实现 memory_store.py 顶层 `import yaml`，导致未装 PyYAML 的机器上
  `python orchestrator.py --once` 直接 ModuleNotFoundError 崩溃，
  用户第一步就跑不起来。

策略:
  1. 有 PyYAML → 用 PyYAML（完整能力）
  2. 没有     → 用内置极简解析器（覆盖本项目 config.yaml 的两层结构）
  3. .json 配置直接原生支持

极简解析器支持范围（够用即可，不追求通用）:
  - `#` 注释、空行
  - 两级缩进的 `key:` / `key: value`
  - 标量自动转型: int / float / true / false / null / 带引号字符串
  - 简单行内列表 `key: [a, b]`
不支持: 多行列表、锚点、多文档、复杂嵌套 —— 需要时请装 PyYAML。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
    HAS_YAML = True
except ImportError:  # pragma: no cover - 取决于运行环境
    yaml = None  # type: ignore
    HAS_YAML = False


def _cast(v: str) -> Any:
    v = v.strip()
    if not v:
        return None
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_cast(x) for x in inner.split(",")] if inner else []
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def parse_simple_yaml(text: str) -> dict:
    """极简 YAML 解析：只处理本项目 config.yaml 这种两层 key/value 结构。"""
    root: dict = {}
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.strip().startswith("#") else ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, val = line.strip().partition(":")
        key = key.strip()
        if indent == 0:
            if val.strip() == "":
                current = {}
                root[key] = current
            else:
                root[key] = _cast(val)
                current = None
        else:
            if current is None:          # 缩进但没有父节点 → 容错放到根
                root[key] = _cast(val)
            else:
                current[key] = _cast(val)
    return root


def load_config(path: str | Path, defaults: dict | None = None,
                require_exists: bool = False) -> dict:
    """载入配置。找不到文件时返回 defaults（不抛异常，保证 MVP 可跑）。"""
    # D4-FIX: fail-closed switch. Callers (CLI entry) may pass
    # require_exists=True so a missing config file raises instead of silently
    # falling back to defaults and then surfacing a misleading
    # ContainmentError (path escape) unrelated to the real cause.
    p = Path(path)
    if not p.exists():
        if require_exists:
            raise FileNotFoundError(f"Config file not found: {p}")
        return dict(defaults or {})
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        return json.loads(text)
    if HAS_YAML:
        data = yaml.safe_load(text)          # type: ignore[union-attr]
        return data if isinstance(data, dict) else dict(defaults or {})
    return parse_simple_yaml(text)


def deep_merge(base: dict, override: dict) -> dict:
    """两层深合并：用户配置缺失的键回落到默认值，避免 KeyError。"""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def atomic_write(path: str | Path, data: str, encoding: str = "utf-8"):
    """原子写入：先写临时文件，再 rename。防止写入中断导致文件损坏。

    参考 DSH util/atomic-writes 模式。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(data, encoding=encoding)
    os.replace(tmp, p)  # Windows/Linux 原子操作


def load_layered_config(base_path: str | Path, *overlay_paths: str | Path) -> dict:
    """分层加载配置：base + overlay1 + overlay2 ... 后层覆盖前层。

    参考 DSH settings 的分层配置模式（schema default → base → user override）。

    返回: (config: dict, sources: list[str]) — sources 记录每层的来源路径。
    """
    config: dict = {}
    sources: list[str] = []
    for path in [Path(base_path)] + [Path(p) for p in overlay_paths]:
        if path.exists():
            layer = load_config(path)
            config = deep_merge(config, layer)
            sources.append(str(path))
    return config, sources


DEFAULT_CONFIG: dict = {
    "memory": {
        "sqlite_path": "data/patterns.db",
        "kb_failure_md": "",
        "kb_success_md": "",
    },
    "loop": {
        "max_rounds": 20,
        "token_budget": 500000,
        "no_progress_stop": 3,
        "meta_analyze_every": 20,
        # L3 cycle-4 A4 (adopted C2): treat an explicit defer/backpressure
        # round as a non-failure (do not consume the consecutive-error
        # budget). Default on; set false to fall back to count-everything.
        "backpressure_defer_enabled": True,
        # L3 cycle-5 A4 (adopted C1): bounded multiplicative rerank for the
        # RAG recall stack (Hindsight combined_score = base * recency_boost *
        # proof_count_boost). alphas default 0.0 -> identity (legacy order).
        "rerank_recency_alpha": 0.0,
        "rerank_proof_alpha": 0.0,
        "rerank_halflife_days": 30.0,
        "rerank_recency_mode": "exponential",
    },
    "backtest": {
        "script": "../backtest/mock_backtest.py",
        "timeout_sec": 3600,
        "python": "",
        "cwd": "",
    },
    "budget": {
        "hard": {
            "max_rounds": 20,
            "max_runtime_minutes": 30,
            "max_consecutive_failures": 2,
        },
        "soft": {
            "max_tokens_per_round": 50000,
            "max_sub_agents": 3,
        },
    },
    "stop": {
        "completion": ["all_criteria_met", "max_rounds_reached"],
        "safety": ["budget_exhausted", "consecutive_failures", "denylist_hit"],
    },
    "task": {
        "name": "sandbox",
        "scope": {
            "allow": ["projects/", "data/", "signals/", "backtest/", "sloth_engine/", "_data/"],
            "deny": ["secrets/", "keys/", "production/", ".env"],
        },
    },
    "zones": {
        "green": ["batch_size", "timeout_sec"],
        "yellow": ["exclusion_rule", "success_criteria"],
        "red": ["hard_constraints"],
    },
    "consumer": {
        "min_queue_size": 3,
        "min_same_type": 3,
        "high_confidence": 5,
    },
}
