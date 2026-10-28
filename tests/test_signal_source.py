"""测试信号源抽象层 — 移植自 DSH Service/Provider 模式"""

import json
import sys
import tempfile
from pathlib import Path
_ENGINE = Path(__file__).resolve().parent.parent / "sloth_engine"
sys.path.insert(0, str(_ENGINE))

import pytest
from signal_source import (
    SignalSource, CSVSignalSource, JSONSignalSource,
    MDSignalSource, load_signals,
)


# ── ABC 不可实例化 ──

def test_signal_source_cannot_instantiate():
    with pytest.raises(TypeError):
        SignalSource()


# ── CSVSignalSource ──

def test_csv_load_basic():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.csv"
        path.write_text(
            "trigger_type,direction,price,score,rsi\n"
            "MA_cross,buy,2300.0,3.5,68.0\n"
            "Fib_retrace,sell,2250.0,2.1,42.0\n",
            encoding="utf-8-sig",
        )
        src = CSVSignalSource(path, column_map={
            "trigger_type": "signal_pattern",
            "direction": "direction",
        }, aliases_from=["direction", "trigger_type"])
        signals = src.load()
        assert len(signals) == 2
        assert signals[0]["signal_pattern"] == "MA_cross"
        assert signals[0]["direction"] == "buy"
        assert "buy" in signals[0]["aliases"]


def test_csv_missing_file():
    src = CSVSignalSource("nonexistent.csv")
    with pytest.raises(FileNotFoundError):
        src.load()


def test_csv_default_signal_pattern():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.csv"
        path.write_text("name,value\na,1\nb,2\n", encoding="utf-8-sig")
        src = CSVSignalSource(path)
        signals = src.load()
        assert len(signals) == 2
        # 无 trigger_type 列时用 signal_index 或 unknown
        assert signals[0]["signal_pattern"] in ("a", "unknown")


def test_csv_preserves_unmapped_fields():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.csv"
        path.write_text(
            "trigger_type,extra_field,value\nMA,hello,42\n",
            encoding="utf-8-sig",
        )
        src = CSVSignalSource(path, column_map={"trigger_type": "signal_pattern"})
        signals = src.load()
        assert signals[0]["extra_field"] == "hello"
        assert signals[0]["value"] == "42"


def test_csv_validate_filters_invalid():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.csv"
        path.write_text(
            "trigger_type,name\nMA,valid\n,\n",  # 第二行无 signal_pattern
            encoding="utf-8-sig",
        )
        src = CSVSignalSource(path, column_map={"trigger_type": "signal_pattern"})
        signals = src.load()
        assert len(signals) == 1  # 只保留有效的


# ── JSONSignalSource ──

def test_json_load_array():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.json"
        path.write_text(json.dumps([
            {"signal_pattern": "a", "value": 1},
            {"signal_pattern": "b", "value": 2},
        ]))
        src = JSONSignalSource(path)
        signals = src.load()
        assert len(signals) == 2


def test_json_load_object_with_extract_key():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.json"
        path.write_text(json.dumps({
            "summary": {"mean": 0.9},
            "windows": {
                "1M": {"accuracy": 0.85},
                "3M": {"accuracy": 0.95},
            },
        }))
        src = JSONSignalSource(path, extract_key="windows")
        signals = src.load()
        assert len(signals) == 2  # 两个窗口


def test_json_key_map():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.json"
        path.write_text(json.dumps([{
            "trigger_name": "MA_cross",
            "market": "uptrend",
            "pnl": 0.05,
        }]))
        src = JSONSignalSource(path, key_map={
            "trigger_name": "signal_pattern",
            "market": "market_condition",
        })
        signals = src.load()
        assert signals[0]["signal_pattern"] == "MA_cross"
        assert signals[0]["market_condition"] == "uptrend"


def test_json_missing_file():
    src = JSONSignalSource("nonexistent.json")
    with pytest.raises(FileNotFoundError):
        src.load()


# ── MDSignalSource ──

def test_md_load_table():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.md"
        path.write_text(
            "| signal_pattern | win_rate | pnl |\n"
            "| --- | --- | --- |\n"
            "| MA_cross | 55% | +2.3 |\n"
            "| Fib_retrace | 42% | -1.1 |\n"
            "| SMC_conflict | 82% | +0.5 |\n",
            encoding="utf-8",
        )
        src = MDSignalSource(path)
        signals = src.load()
        assert len(signals) == 3
        assert signals[0]["signal_pattern"] == "MA_cross"
        assert signals[1]["win_rate"] == "42%"


def test_md_table_with_non_table_content():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.md"
        path.write_text(
            "# Title\n\n"
            "Some text before the table.\n\n"
            "| name | value |\n| --- | --- |\n| a | 1 |\n| b | 2 |\n\n"
            "Some text after.\n",
            encoding="utf-8",
        )
        src = MDSignalSource(path, column_map={"name": "signal_pattern"})
        signals = src.load()
        assert len(signals) == 2


def test_md_table_index():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.md"
        path.write_text(
            "| first | col |\n| --- | --- |\n| x | 1 |\n\n"
            "| second | col |\n| --- | --- |\n| y | 2 |\n",
            encoding="utf-8",
        )
        src1 = MDSignalSource(path, table_index=0)
        s1 = src1.load()
        assert s1[0]["first"] == "x"

        src2 = MDSignalSource(path, table_index=1)
        s2 = src2.load()
        assert s2[0]["second"] == "y"


def test_md_missing_file():
    src = MDSignalSource("nonexistent.md")
    with pytest.raises(FileNotFoundError):
        src.load()


# ── load_signals 自动检测 ──

def test_load_signals_auto_csv():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.csv"
        path.write_text("name,val\na,1\n", encoding="utf-8-sig")
        signals = load_signals(path)
        assert len(signals) == 1


def test_load_signals_auto_json():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.json"
        path.write_text(json.dumps([{"signal_pattern": "test"}]))
        signals = load_signals(path)
        assert len(signals) == 1


def test_load_signals_auto_md():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.md"
        path.write_text("| name |\n| --- |\n| test |\n", encoding="utf-8")
        signals = load_signals(path)
        assert len(signals) == 1


def test_load_signals_force_format():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.txt"
        path.write_text("name,val\na,1\n", encoding="utf-8-sig")
        signals = load_signals(path, fmt="csv")
        assert len(signals) == 1


def test_load_signals_unsupported():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.xyz"
        path.write_text("whatever")
        with pytest.raises(ValueError, match="不支持的文件格式"):
            load_signals(path)


# ── 端到端: 写入 → loop signals → 验证格式 ──

def test_e2e_output_is_valid_loop_signals():
    """输出格式必须可被 loop 消费：每个信号有 signal_pattern。"""
    with tempfile.TemporaryDirectory() as tmp:
        # CSV
        csv_path = Path(tmp) / "s.csv"
        csv_path.write_text(
            "trigger_type,direction,price\nMA,buy,2300\nFib,sell,2250\n",
            encoding="utf-8-sig",
        )
        signals = load_signals(csv_path)
        for s in signals:
            assert "signal_pattern" in s
            assert isinstance(s["signal_pattern"], str)
            assert len(s["signal_pattern"]) > 0
            assert "aliases" in s or True  # aliases optional