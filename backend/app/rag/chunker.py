"""文本切分：面向代码/中文技术文档的轻量分块器。

两个关键点：
1. 代码围栏必须整体保留，不能从中间切开；
2. 长度按「还原后的真实文本」计算，避免占位符导致切块过大。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FENCE = re.compile(r"```.*?```", re.S)
_PLACEHOLDER = re.compile(r"\u0000FENCE(\d+)\u0000")


@dataclass(slots=True)
class Chunk:
    index: int
    text: str
    heading: str | None = None


def _split_long(block: str, max_chars: int) -> list[str]:
    """按行累积切分超长纯文本块。"""
    if len(block) <= max_chars:
        return [block]
    parts: list[str] = []
    buf = ""
    for line in block.splitlines(keepends=True):
        if len(buf) + len(line) > max_chars and buf:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return [p for p in parts if p.strip()]


def _segments(text: str) -> list[tuple[str, bool]]:
    """拆成 (片段, 是否为代码块) 的序列。"""
    fences: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        fences.append(match.group(0))
        return f"\n\u0000FENCE{len(fences) - 1}\u0000\n"

    protected = _FENCE.sub(_stash, text)
    segments: list[tuple[str, bool]] = []
    for block in re.split(r"\n\s*\n", protected):
        block = block.strip()
        if not block:
            continue
        for piece in re.split(r"(\u0000FENCE\d+\u0000)", block):
            piece = piece.strip()
            if not piece:
                continue
            match = _PLACEHOLDER.fullmatch(piece)
            if match:
                segments.append((fences[int(match.group(1))], True))
            else:
                segments.extend((part, False) for part in _split_long(piece, 700))
    return segments


def chunk_text(text: str, *, max_chars: int = 700, overlap: int = 0) -> list[Chunk]:
    """按段落/标题切块，代码块整体保留。"""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []

    segments = _segments(text)
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    heading: str | None = None

    def flush() -> None:
        nonlocal buf, buf_len
        body = "\n\n".join(buf).strip()
        if body:
            chunks.append(Chunk(len(chunks), body, heading))
        if overlap and len(body) > overlap:
            tail = body[-overlap:]
            buf = [tail]
            buf_len = len(tail)
        else:
            buf = []
            buf_len = 0

    for piece, is_code in segments:
        head_match = None
        if not is_code:
            head_match = re.match(r"^(#{1,6})\s+(.+)$", piece.splitlines()[0]) if piece else None
        if head_match:
            heading = head_match.group(2).strip()

        # 单块就超过上限：先冲刷已有内容，再独立成块
        if piece and len(piece) > max_chars and not is_code:
            if buf:
                flush()
                buf, buf_len = [], 0
            for part in _split_long(piece, max_chars):
                chunks.append(Chunk(len(chunks), part.strip(), heading))
            continue

        if buf and buf_len + len(piece) + 2 > max_chars:
            flush()

        buf.append(piece)
        buf_len += len(piece) + 2

    if buf:
        body = "\n\n".join(buf).strip()
        if body:
            chunks.append(Chunk(len(chunks), body, heading))

    # 去重 + 过滤空块
    seen: set[str] = set()
    result: list[Chunk] = []
    for chunk in chunks:
        key = chunk.text[:80]
        if not chunk.text.strip() or key in seen:
            continue
        seen.add(key)
        result.append(Chunk(len(result), chunk.text, chunk.heading))
    return result