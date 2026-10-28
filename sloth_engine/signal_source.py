"""信号源抽象层 — 移植自 DSH 的 Service/Provider 架构模式。

定义 SignalSource 抽象接口，CSV/JSON/MD 三种 Provider 可替换。
消费者 (orchestrator) 只依赖抽象接口，不关心数据来源。

移植自 DSH packages/fs/ (FileSystem Service + Providers)
"""

from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class SignalSource(ABC):
    """信号源抽象接口 — 所有数据源的统一入口。

    新增数据格式只需实现子类，不改消费者代码。
    """

    @abstractmethod
    def load(self) -> list[dict]:
        """加载并返回标准化信号列表。"""
        ...

    def validate(self, signals: list[dict]) -> list[dict]:
        """验证信号格式，过滤无效条目。默认透传。"""
        return [s for s in signals
                if isinstance(s, dict) and s.get("signal_pattern")]


class CSVSignalSource(SignalSource):
    """CSV 文件信号源。

    通过 column_map 将 CSV 列映射到标准信号字段。
    未映射的列保留为领域字段。
    """

    def __init__(self, path: str | Path, column_map: dict[str, str] | None = None,
                 aliases_from: list[str] | None = None,
                 encoding: str = "utf-8-sig"):
        self._path = Path(path)
        self._column_map = column_map or {}
        self._aliases_from = aliases_from or []
        self._encoding = encoding

    def load(self) -> list[dict]:
        if not self._path.exists():
            raise FileNotFoundError(f"CSV 文件不存在: {self._path}")

        with open(self._path, "r", encoding=self._encoding) as f:
            reader = csv.DictReader(f)
            signals = []
            for row in reader:
                sig = self._map_row(row)
                signals.append(sig)
        return self.validate(signals)

    def _map_row(self, row: dict[str, str]) -> dict:
        sig: dict[str, Any] = {}
        for csv_col, sig_field in self._column_map.items():
            if csv_col in row:
                sig[sig_field] = row[csv_col]

        # 未映射的列保留为领域字段
        for k, v in row.items():
            if k not in self._column_map:
                sig[k] = v

        # 生成 signal_pattern（如果没有映射）
        if "signal_pattern" not in sig:
            sig["signal_pattern"] = (
                row.get("trigger_type") or row.get("signal_index") or "unknown"
            )

        # 生成 market_condition
        if "market_condition" not in sig:
            direction = row.get("direction", "unknown")
            ctx = row.get("ctx_before_dir") or "none"
            sig["market_condition"] = f"{direction}_{ctx}"

        # 生成 aliases
        aliases = []
        for col in self._aliases_from:
            if col in row and row[col]:
                aliases.append(str(row[col]))
        sig["aliases"] = aliases if aliases else [sig["signal_pattern"]]

        return sig


class JSONSignalSource(SignalSource):
    """JSON 文件信号源。

    支持顶层数组 (每条信号一个对象) 或单对象 (提取指定 key)。
    """

    def __init__(self, path: str | Path, key_map: dict[str, str] | None = None,
                 aliases_from: list[str] | None = None,
                 extract_key: str | None = None):
        self._path = Path(path)
        self._key_map = key_map or {}
        self._aliases_from = aliases_from or []
        self._extract_key = extract_key

    def load(self) -> list[dict]:
        if not self._path.exists():
            raise FileNotFoundError(f"JSON 文件不存在: {self._path}")

        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if self._extract_key and isinstance(data, dict):
            items = data.get(self._extract_key, [])
            if isinstance(items, dict):
                # 嵌套 dict → 每条 value 作为一个信号
                items = list(items.values())
            elif not isinstance(items, list):
                items = [items]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]

        signals = []
        for item in items:
            if not isinstance(item, dict):
                continue
            sig = self._map_item(item)
            signals.append(sig)

        return self.validate(signals)

    def _map_item(self, item: dict) -> dict:
        sig: dict[str, Any] = {}
        for json_key, sig_field in self._key_map.items():
            if json_key in item:
                sig[sig_field] = item[json_key]

        for k, v in item.items():
            if k not in self._key_map:
                sig[k] = v

        if "signal_pattern" not in sig:
            sig["signal_pattern"] = self._path.stem

        if "aliases" not in sig:
            aliases = [str(item.get(k, "")) for k in self._aliases_from if k in item]
            sig["aliases"] = aliases if aliases else [sig["signal_pattern"]]

        return sig


class MDSignalSource(SignalSource):
    """Markdown 表格信号源。

    解析 Markdown 中的表格（按 table_index 指定第几个表格），
    将表头映射为标准信号字段。
    """

    def __init__(self, path: str | Path, table_index: int = 0,
                 column_map: dict[str, str] | None = None,
                 aliases_from: list[str] | None = None):
        self._path = Path(path)
        self._table_index = table_index
        self._column_map = column_map or {}
        self._aliases_from = aliases_from or []

    def load(self) -> list[dict]:
        if not self._path.exists():
            raise FileNotFoundError(f"MD 文件不存在: {self._path}")

        content = self._path.read_text(encoding="utf-8")
        tables = self._parse_tables(content)

        if not tables or self._table_index >= len(tables):
            return []

        headers, rows = tables[self._table_index]
        signals = []
        for row in rows:
            sig: dict[str, Any] = {}
            for h, v in zip(headers, row):
                if h in self._column_map:
                    sig[self._column_map[h]] = v
                sig[h] = v

            if "signal_pattern" not in sig:
                sig["signal_pattern"] = f"md_row_{signals.__len__() + 1}"

            if "aliases" not in sig:
                aliases = [str(sig.get(k, "")) for k in self._aliases_from if sig.get(k)]
                sig["aliases"] = aliases if aliases else [sig["signal_pattern"]]

            signals.append(sig)

        return self.validate(signals)

    @staticmethod
    def _parse_tables(content: str) -> list[tuple[list[str], list[list[str]]]]:
        """解析 Markdown 中的所有表格。"""
        tables = []
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("|") and line.endswith("|"):
                # 这是表头行
                headers = [h.strip() for h in line.split("|")[1:-1]]
                i += 1
                # 跳过分隔行
                if i < len(lines) and "---" in lines[i]:
                    i += 1
                # 读取数据行
                rows = []
                while i < len(lines):
                    row_line = lines[i].strip()
                    if not (row_line.startswith("|") and row_line.endswith("|")):
                        break
                    values = [v.strip() for v in row_line.split("|")[1:-1]]
                    rows.append(values)
                    i += 1
                tables.append((headers, rows))
            else:
                i += 1
        return tables


# ── 便捷工厂函数 ──

def load_signals(path: str | Path, fmt: str | None = None,
                 column_map: dict | None = None,
                 aliases_from: list[str] | None = None,
                 **kwargs) -> list[dict]:
    """自动检测格式并加载信号。

    Args:
        path: 文件路径
        fmt: 强制指定格式 ("csv" | "json" | "md")，None 则自动检测后缀
        column_map: 字段映射 {source_col: target_field}
        aliases_from: 从哪些列提取别名
    """
    p = Path(path)
    if fmt:
        ext = fmt.lower()
    else:
        ext = p.suffix.lower().lstrip(".")
        if ext in ("txt", "log"):
            # 尝试检测内容
            first_line = p.read_text(encoding="utf-8-sig").split("\n")[0].strip()
            if first_line.startswith("{") or first_line.startswith("["):
                ext = "json"
            elif "\t" in first_line or "," in first_line:
                ext = "csv"
            else:
                ext = "md"

    if ext in ("csv", "tsv"):
        return CSVSignalSource(p, column_map=column_map,
                               aliases_from=aliases_from, **kwargs).load()
    elif ext == "json":
        return JSONSignalSource(p, key_map=column_map,
                                aliases_from=aliases_from, **kwargs).load()
    elif ext == "md":
        return MDSignalSource(p, column_map=column_map,
                              aliases_from=aliases_from, **kwargs).load()
    else:
        raise ValueError(f"不支持的文件格式: {ext}，支持: csv, json, md")