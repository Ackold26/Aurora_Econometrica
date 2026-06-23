"""Высокоуровневый семантический поиск: эмбеддер + хранилище (+ опц. переранжировщик).

Чистый dense-retrieval с опциональной двухступенчатой переранжировкой. FTS-gating
(гибрид вектор + sqlite bm25, уникальная фича ``kb_vec``) и раздельный поиск по категориям —
расширения L1 для следующего среза (S2, сведение KB): для продуктов (S1) достаточно
вектора + фильтра категорий. Транспорт (HTTP / stdio / демон) ядро не знает — его строит
адаптер потребителя.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import DEFAULT_RERANK_FETCH, DEFAULT_TOP_K

if TYPE_CHECKING:
    from .embedder import Embedder
    from .reranker import Reranker
    from .store import VectorStore
    from .types import Hit


class SemanticSearch:
    """Связывает эмбеддер, хранилище и (необязательно) переранжировщик."""

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        reranker: Reranker | None = None,
        rerank_fetch: int = DEFAULT_RERANK_FETCH,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.reranker = reranker
        self.rerank_fetch = rerank_fetch

    def search(
        self,
        query: str,
        *,
        k: int = DEFAULT_TOP_K,
        categories: list[str] | None = None,
        threshold: float = 0.0,
        rerank: bool = False,
    ) -> list[Hit]:
        """Поиск top-``k``. ``categories`` — фильтр; ``rerank`` — двухступенчатый (нужен
        переранжировщик, иначе флаг игнорируется и возвращается чистый вектор)."""
        if not query or not query.strip():
            return []
        query_vector = self.embedder.embed_query(query)
        use_rerank = rerank and self.reranker is not None
        if use_rerank and self.reranker is not None:
            fetch = max(self.rerank_fetch, k)
            candidates = self.store.search(
                query_vector, k=fetch, categories=categories, threshold=threshold, fetch=fetch
            )
            return self.reranker.rerank(query, candidates, top_k=k)
        return self.store.search(query_vector, k=k, categories=categories, threshold=threshold)
