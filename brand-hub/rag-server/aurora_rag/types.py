"""Лёгкие типы РАГ-ядра (stdlib dataclasses — без рантайм-зависимостей)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Hit:
    """Один результат поиска. ``rerank_score`` дописывается переранжировщиком (L1)."""

    source: str
    category: str
    score: float  # косинус = 1 − _distance
    text: str
    chunk_index: int = 0
    rerank_score: float | None = None


@dataclass(frozen=True, slots=True)
class IndexStats:
    """Итог операции индексации."""

    added: int = 0
    changed: int = 0
    removed: int = 0
    total_files: int = 0
    chunks: int = 0


@dataclass(frozen=True, slots=True)
class Document:
    """Единица корпуса до чанкинга: текст + метки источника/категории."""

    text: str
    source: str
    category: str = "."
