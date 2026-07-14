"""Чанкинг текста.

Абзацная стратегия (``ParagraphChunker``) унаследована дословно из зрелой линии
(``lib_vec`` / ``kb_vec``): режем по абзацам, не превышая ``size``; слишком длинный абзац —
скользящим окном с ``overlap``. Доменные стратегии (например, по статьям закона в
local-rag) реализует потребитель через протокол ``Chunker`` — в ядро они не входят
(граница экстракции ADR-027: доменный чанкинг = L2, надстройка потребителя).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE


@runtime_checkable
class Chunker(Protocol):
    """Стратегия разбиения текста на чанки."""

    def split(self, text: str) -> list[str]: ...


class ParagraphChunker:
    """Абзацный сплиттер. Параметризован — ядро не навязывает один размер (ADR-027)."""

    def __init__(
        self, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP
    ) -> None:
        if size <= 0:
            raise ValueError("size должен быть > 0")
        if overlap < 0 or overlap >= size:
            raise ValueError("overlap должен быть в [0, size)")
        self.size = size
        self.overlap = overlap

    def split(self, text: str) -> list[str]:
        if len(text) <= self.size:
            return [text] if text.strip() else []
        parts: list[str] = []
        buf = ""
        for para in text.split("\n\n"):
            if len(buf) + len(para) + 2 <= self.size:
                buf = (buf + "\n\n" + para) if buf else para
            else:
                if buf:
                    parts.append(buf)
                if len(para) <= self.size:
                    buf = para
                else:
                    step = self.size - self.overlap
                    for j in range(0, len(para), step):
                        parts.append(para[j : j + self.size])
                    buf = ""
        if buf:
            parts.append(buf)
        return [p for p in parts if p.strip()]


def strip_frontmatter(raw: str) -> str:
    """Убрать ведущий YAML-frontmatter (``---`` … ``---``), если есть. Общий помощник;
    доменный препроцессинг (drop спец-секций) — ответственность потребителя."""
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            return raw[end + 4 :].strip()
    return raw.strip()
