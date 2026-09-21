"""GEO 自己那份资料的切块（Owner 2026-09-21）。

Owner 原话：「geo 上传资料这里也要切块存，只切块就行了」。

所以这里**只**做一件事：把上传/新建时拿到的文本，切成**可引用的段**，连同序号和
字符区间一起存进素材自己那一行 —— 存在 **GEO 自己的库**里，不写企业知识库。

刻意**没做**的（都属于 Owner 说的「后面的」）：
- 不调模型（没有 embedding、没有向量）；
- 不抽实体 / 不抽语义对象（那是知识库与语义的活；GEO 自己再抽一份就是第二套语义）；
- 不投索引、不接检索、不写知识库。

切块规则（确定性，同一段文本任何时候切出来都一样，所以重切是幂等的）：
按空行分段 → 单段超长再按句子边界切 → 攒到 CHUNK_TARGET 字成一块 → 结尾碎块并进上一块。
每块的 ``text`` 是原文本的**逐字切片**（``content[start:end]``），不是重新拼的，
所以引用它不会和原文对不上。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

#: 一块的目标字数（攒到这个量就收一块）
CHUNK_TARGET = 600
#: 单块上限：单段超过它就按句子边界再切
CHUNK_MAX = 900
#: 碎块下限：结尾不足这么多字就并进上一块（并完不超上限才并）
CHUNK_MIN = 80

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])")


def _paragraphs(text: str) -> list[tuple[int, int]]:
    """按空行分段，返回每段在原文本里的 (start, end)。

    首尾空白去掉、但区间仍是原文本里的真实位置 —— 所以后面取 ``text[start:end]``
    拿到的永远是**逐字原文**，不是重新拼出来的字符串。
    """
    bounds: list[tuple[int, int]] = []
    pos = 0
    for match in _PARAGRAPH_SPLIT.finditer(text):
        bounds.append((pos, match.start()))
        pos = match.end()
    bounds.append((pos, len(text)))

    out: list[tuple[int, int]] = []
    for start, end in bounds:
        seg = text[start:end]
        left = len(seg) - len(seg.lstrip())
        right = len(seg.rstrip())
        if right > left:
            out.append((start + left, start + right))
    return out


def _split_long(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """超长的一段：先按句子边界切，仍超长再硬切。返回原文本区间。"""
    seg = text[start:end]
    cuts: list[int] = []
    cursor = 0
    for piece in _SENTENCE_END.split(seg):
        if not piece:
            continue
        cursor += len(piece)
        cuts.append(cursor)
    if not cuts or cuts[-1] != len(seg):
        cuts.append(len(seg))
    out: list[tuple[int, int]] = []
    piece_start = 0
    for cut in cuts:
        while cut - piece_start > max_chars:
            out.append((start + piece_start, start + piece_start + max_chars))
            piece_start += max_chars
        if cut > piece_start:
            out.append((start + piece_start, start + cut))
        piece_start = cut
    # 过短的句子碎块并回上一块（同段内合并，仍不超上限）
    merged: list[tuple[int, int]] = []
    for s, e in out:
        if merged and (e - s) < CHUNK_MIN and (e - merged[-1][0]) <= max_chars:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def chunk_text(
    text: str,
    *,
    target: int = CHUNK_TARGET,
    max_chars: int = CHUNK_MAX,
    min_chars: int = CHUNK_MIN,
) -> list[dict[str, Any]]:
    """把文本切成块：``[{ordinal, start, end, chars, text}]``（text 是原文本的逐字切片）。"""
    raw = str(text or "")
    if not raw.strip():
        return []
    spans: list[tuple[int, int]] = []
    for start, end in _paragraphs(raw):
        if (end - start) > max_chars:
            spans.extend(_split_long(raw, start, end, max_chars))
        else:
            spans.append((start, end))

    grouped: list[list[tuple[int, int]]] = []
    for span in spans:
        if not grouped:
            grouped.append([span])
            continue
        current = grouped[-1]
        width = span[1] - current[0][0]
        if width <= target:
            current.append(span)
        else:
            grouped.append([span])
    # 结尾碎块：并进上一组（并完不超上限才并）
    if len(grouped) >= 2:
        last = grouped[-1]
        width = last[-1][1] - last[0][0]
        if width < min_chars and (last[-1][1] - grouped[-2][0][0]) <= max_chars:
            grouped[-2].extend(grouped.pop())

    out: list[dict[str, Any]] = []
    for i, group in enumerate(grouped):
        start, end = group[0][0], group[-1][1]
        piece = raw[start:end]
        if not piece.strip():
            continue
        out.append({"ordinal": i, "start": start, "end": end, "chars": len(piece), "text": piece})
    return out


def chunk_material(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """给一条素材打上切块（就地改并返回同一个 dict）。

    - ``text_chunks``：逐块 {ordinal, start, end, chars, text}
    - ``chunks``：块数（这个字段以前恒为 0，是个空壳；现在是真的）
    """
    content = str(item.get("content") or "")
    chunks = chunk_text(content)
    mid = str(item.get("id") or "").strip()
    for c in chunks:
        # 稳定 id：素材 id + 段序号。检索命中要能指回「哪份素材的第几段」。
        c["id"] = f"{mid}#{c['ordinal']}" if mid else f"chunk#{c['ordinal']}"
    item["text_chunks"] = chunks
    item["chunks"] = len(chunks)
    item["chunked_at"] = (now or datetime.now(timezone.utc)).isoformat()
    item["chunk_chars"] = len(content)
    return item
