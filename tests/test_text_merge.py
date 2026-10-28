"""重叠感知保守文本拼接契约测试（对标 WeKnora internal/searchutil/chunkmerge.go）。

被验证机制：sloth_engine/text_merge.py。
接线断言：rag_layers.LayeredMemory.consolidate 的 observation 文本必须走该机制
（包含折叠 / 有界重叠去除），而不是简单 join。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = _ROOT / "sloth_engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import rag_layers as rl  # noqa: E402
import text_merge as tm  # noqa: E402


SHORT_SUPERSET = "BTC breakout above 84000 with volume"
LONG_SUPERSET = "BTC breakout above 84000 with volume surge"


# ── ① 空输入 ────────────────────────────────────────────────

def test_empty_inputs_yield_empty():
    assert tm.merge_texts([]) == ""
    assert tm.merge_texts(["", "   "]) == ""
    assert tm.join_adjacent("", "") == ""


# ── ② 完全包含折叠 ──────────────────────────────────────────

def test_exact_duplicate_collapses():
    text = "BTC breakout above 84000"
    assert tm.merge_texts([text, text]) == text


def test_superset_containment_collapses_both_orders():
    assert tm.merge_texts([SHORT_SUPERSET, LONG_SUPERSET]) == LONG_SUPERSET
    assert tm.merge_texts([LONG_SUPERSET, SHORT_SUPERSET]) == LONG_SUPERSET


def test_short_substring_is_not_treated_as_containment():
    out = tm.merge_texts(["volume", LONG_SUPERSET])
    # 6 字符 < MIN_OVERLAP_CHARS，不能因为碰巧是子串就把 "volume" 静默丢掉
    assert out.count("volume") == 2
    assert tm.DEFAULT_SEPARATOR in out


def test_contains_text_boundaries():
    assert tm.contains_text("abcdefghijklmnop", "abcdefghijklmnop") is True
    assert tm.contains_text("abcdefghijklmnop", "cdef") is False  # 太短
    assert tm.contains_text("", "x") is False
    assert tm.contains_text("x", "") is False


# ── ③ 有界后缀/前缀重叠去除 ─────────────────────────────────

def test_suffix_prefix_overlap_is_removed():
    a = "partial overlap marker ALPHA-BETA-GAMMA end"
    b = "ALPHA-BETA-GAMMA end of the second chunk"
    out = tm.join_adjacent(a, b)
    assert out == "partial overlap marker ALPHA-BETA-GAMMA end of the second chunk"
    assert tm.DEFAULT_SEPARATOR not in out


def test_overlap_below_minimum_is_conservatively_kept():
    a = "abcdefghijkl"
    b = "klmnopqrstuv"  # 与 a 只重叠 2 个字符
    out = tm.join_adjacent(a, b)
    assert tm.DEFAULT_SEPARATOR in out
    assert out.endswith(b) and out.startswith(a)


def test_search_window_is_bounded_by_max_overlap_chars():
    assert tm.MAX_OVERLAP_CHARS == 400
    # 用 500 个互异码位构造非周期串，避免周期性巧合让窗口外重叠被误判命中。
    x = "".join(chr(0x4E00 + i) for i in range(500))
    acc = "A" * 500 + x
    nxt = x + "B" * 500
    out = tm.join_adjacent(acc, nxt)
    # 真实重叠 500 > 窗口上限 400 => 检测不到 => 保守按分隔符拼接（不静默裁内容）
    assert out == acc + tm.DEFAULT_SEPARATOR + nxt


def test_cjk_overlap_uses_codepoints():
    a = "研究结论显示该策略在趋势市表现优异而震荡市回撤明显"
    b = "该策略在趋势市表现优异而震荡市回撤明显且换手偏高"
    out = tm.join_adjacent(a, b)
    assert out == "研究结论显示该策略在趋势市表现优异而震荡市回撤明显且换手偏高"
    assert tm.DEFAULT_SEPARATOR not in out


# ── ④ 保守性与不变量 ───────────────────────────────────────

def test_join_adjacent_empty_sides():
    assert tm.join_adjacent("", "abc") == "abc"
    assert tm.join_adjacent("abc", "") == "abc"


def test_disjoint_texts_are_both_retained():
    out = tm.merge_texts(
        ["alpha one two three four five six", "bravo seven eight nine ten eleven"]
    )
    assert "alpha one" in out and "bravo seven" in out


def test_merge_is_idempotent_on_its_own_result():
    parts = [
        "chunk one content that is long enough",
        "content that is long enough and continues here",
        "and continues here with more tail text",
    ]
    once = tm.merge_texts(parts)
    assert tm.merge_texts(parts + [once]) == once


def test_default_separator_matches_rag_layers_pipe():
    assert tm.DEFAULT_SEPARATOR == " \u2223 "


def test_adversarial_large_input_is_bounded():
    big_a = "x" * 200000
    big_b = "y" * 200000
    t0 = time.time()
    out = tm.join_adjacent(big_a, big_b)
    elapsed = time.time() - t0
    assert elapsed < 2.0, "bounded window must not degrade to quadratic work"
    assert out.startswith("x") and out.endswith("y")


# ── ⑤ 接线：rag_layers.consolidate 必须走本机制 ─────────────

def test_rag_layers_consolidate_uses_overlap_merge():
    mem = rl.LayeredMemory()
    mem.add_many([
        rl.MemoryUnit(id="r1", text=SHORT_SUPERSET),
        rl.MemoryUnit(id="r2", text=LONG_SUPERSET),
    ])
    obs = mem.consolidate(threshold=0.85, min_group=2)
    assert len(obs) == 1
    assert sorted(obs[0].source_ids) == ["r1", "r2"]
    assert obs[0].text == LONG_SUPERSET, "observation 应折叠为超集文本而非分隔符拼接"


def test_rag_layers_source_imports_text_merge():
    src = (_ENGINE / "rag_layers.py").read_text(encoding="utf-8")
    assert "text_merge" in src, "rag_layers 必须接 text_merge（N-1 无调用方门禁）"