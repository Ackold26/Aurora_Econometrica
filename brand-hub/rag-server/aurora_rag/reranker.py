"""Переранжировщик (L1, opt-in) — cross-encoder bge-reranker-v2-m3.

Двухступенчатый поиск: вектор достаёт невод кандидатов → cross-encoder читает пару
(запрос, текст) вместе и пересортировывает. Точнее на слабых местах вектора (OCR-шум,
точные тех-совпадения). Урок зрелой линии: кросс-язык reranker НЕ вытаскивает (даёт
околонулевые мусорные скоры) — это решается двуязычным запросом, не переранжировкой.
Дорогой на CPU → по умолчанию выключен у потребителя.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import DEFAULT_RERANK_MODEL

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

    from .types import Hit


class Reranker:
    """Ленивый cross-encoder. ``offline`` наследует политику эмбеддера (0-egress)."""

    def __init__(
        self, model_name: str = DEFAULT_RERANK_MODEL, *, max_length: int = 512, offline: bool = True
    ) -> None:
        self._model_name = model_name
        self._max_length = max_length
        self._offline = offline
        self._model: CrossEncoder | None = None

    def _load(self) -> CrossEncoder:
        if self._model is None:
            if self._offline:
                import os

                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name, max_length=self._max_length)
        return self._model

    def rerank(self, query: str, hits: list[Hit], *, top_k: int) -> list[Hit]:
        """Пересортировать кандидатов по cross-encoder и вернуть ``top_k``."""
        if not hits:
            return []
        scores = self._load().predict([(query, h.text) for h in hits])
        for hit, score in zip(hits, scores, strict=True):
            hit.rerank_score = round(float(score), 4)
        ranked = sorted(
            hits, key=lambda h: h.rerank_score if h.rerank_score is not None else 0.0, reverse=True
        )
        return ranked[:top_k]
