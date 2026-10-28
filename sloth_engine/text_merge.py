"""重叠感知的保守文本拼接 —— 移植自 WeKnora internal/searchutil/chunkmerge.go。

用途：把同一逻辑实体的多段文本（分块、改写、多来源合并）拼成一段，并保证
「宁可保留重复，也不静默丢内容」：

1. 完全包含折叠：一段完整覆盖另一段 → 只留长的那段；
2. 有界后缀/前缀重叠去除：只在 MIN_OVERLAP_CHARS..MAX_OVERLAP_CHARS 码位窗口内
   找可证实的最长重叠，命中则从重叠处接上；
3. 短串不判包含：短于 MIN_OVERLAP_CHARS 的串不参与包含判定（否则 "volume"、
   标点这类常见片段会被误判成包含而丢内容）；
4. 保守回退：无重叠可去时用 separator 直接拼接，绝不裁掉内容。

与 WeKnora 的差异（取舍见蒸馏条目 §③）：
- Go 用 []rune 计长；Python 的 str 本身就是码位序列，等价且无编码截断风险。
- WeKnora 另有依赖 chunk 的 StartAt/EndAt 位置提示的 AppendWithOverlap /
  MergeTextChunks 变体；loop 的调用点（LayeredMemory.consolidate）没有位置坐标，
  故本期不移植该带位置参数的变体（无生产调用点 = 不引入未接线机制）。
"""

from __future__ import annotations

from typing import Iterable

# 参与重叠匹配的最短长度（对标 Go minOverlapRunes=12）。
MIN_OVERLAP_CHARS = 12
# 后缀匹配窗口上限，防止对抗性超长编辑让拼接退化为平方级（对标 defaultSearchSpan=400）。
MAX_OVERLAP_CHARS = 400
# 无可去重叠时的默认分隔符（与 rag_layers 既有 " ∣ " 口径一致）。
DEFAULT_SEPARATOR = " \u2223 "


def contains_text(container: str, contained: str) -> bool:
    """container 是否安全地覆盖 contained（用于折叠完全包含的段落）。

    极短子串不算包含；相等视为包含。
    """
    if not container or not contained:
        return False
    if container == contained:
        return True
    return len(contained) >= MIN_OVERLAP_CHARS and contained in container


def join_adjacent(acc: str, nxt: str, separator: str = DEFAULT_SEPARATOR) -> str:
    """把 nxt 拼到 acc 之后，去掉二者之间可证实（且足够长）的重叠。

    与 Go JoinChunkContent 同口径：不依赖解析器偏移，只按文本匹配。
    无重叠可去时返回 acc + separator + nxt（保守：宁可保留重复）。
    """
    if not acc:
        return nxt
    if not nxt:
        return acc
    if contains_text(acc, nxt):
        return acc
    if contains_text(nxt, acc):
        return nxt

    max_overlap = min(len(acc), len(nxt))
    if max_overlap > MAX_OVERLAP_CHARS:
        max_overlap = MAX_OVERLAP_CHARS
    for overlap in range(max_overlap, MIN_OVERLAP_CHARS - 1, -1):
        if acc[-overlap:] == nxt[:overlap]:
            return acc + nxt[overlap:]
    return acc + separator + nxt


def merge_texts(texts: Iterable[str], separator: str = DEFAULT_SEPARATOR) -> str:
    """按给定顺序左折叠合并多段文本；空段自动跳过，完全重复段被包含折叠吸收。

    结果对「已被更长文本覆盖」的输入不敏感（折叠），但整体顺序仍然影响拼接顺序，
    与 Go JoinChunkContent 的调用语义一致。
    """
    acc = ""
    for raw in texts:
        text = (raw or "").strip()
        if text:
            acc = join_adjacent(acc, text, separator)
    return acc