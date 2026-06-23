"""Слой совместимости brand-hub/rag-server поверх aurora_rag (S1).

Продуктовый РАГ-sidecar (Creative Hub / Media / DocMaster / Econometrica) переходит на
каноническое ядро заменой ДВУХ импортов — `server.py` / `brand_manager.py` / `chunker.py`
(langchain, остаётся как L2-стратегия потребителя) НЕ меняются:

    # было:  from embedder import Embedder ; from vector_store import VectorStore
    # стало:
    from aurora_rag.adapters.brandhub import Embedder, VectorStore

Сохранён публичный API продуктовых классов. **Поле категории = `cabinet`** (как в исходной
схеме brand-hub) — передаётся ядру через `category_field`, поэтому СУЩЕСТВУЮЩИЕ индексы
`vectors.lance` читаются и пополняются без миграции. Поведение паритетно (доказано
`scripts/parity_brandhub.py`): тот же RoSBERTa, тот же порог 0.15, тот же LanceDB.
Бонусом против оригинала: экранирование SQL в удалении по source и общий движок.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_rag.embedder import Embedder as _CoreEmbedder
from aurora_rag.search import SemanticSearch
from aurora_rag.store import VectorStore as _CoreStore

if TYPE_CHECKING:
    from pathlib import Path

    from sentence_transformers import SentenceTransformer

# Дефолты продуктового brand-hub/rag-server/config.py.
DEFAULT_TOP_K = 10
SIMILARITY_THRESHOLD = 0.15
# Имя колонки категории в схеме brand-hub (исторически — cabinet, НЕ category).
CABINET_FIELD = "cabinet"


class Embedder:
    """API-совместимый с brand-hub ``embedder.py`` (singleton поверх ядра)."""

    _instance: Embedder | None = None
    _core: _CoreEmbedder

    def __new__(cls) -> Embedder:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._core = _CoreEmbedder()
        return cls._instance

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._core.embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._core.embed_query(query)

    def embed_for_classification(self, texts: list[str]) -> list[list[float]]:
        """Совместимость с оригинальным API. Ядро не различает classification-префикс —
        делегируем в document-эмбеддинг (для brand-hub этот метод нигде не вызывается)."""
        return self._core.embed_documents(texts)

    @property
    def model(self) -> SentenceTransformer:
        """Совместимость: прямой доступ к загруженной модели (оригинал имел ``.model``)."""
        return self._core._load()

    @property
    def dimension(self) -> int:
        return self._core.dimension


class VectorStore:
    """API-совместимый с brand-hub ``vector_store.py``. Поле категории — ``cabinet``."""

    def __init__(self, brand_dir: Path) -> None:
        db_path = brand_dir / "hub" / "vectors.lance"
        self._store = _CoreStore(
            str(db_path), table_name="brand_knowledge", category_field=CABINET_FIELD
        )
        self._embedder = Embedder()
        self._search = SemanticSearch(self._embedder._core, self._store)

    def add_documents(self, chunks: list[dict[str, object]], cabinet: str = "docs") -> int:
        """chunks: list[{text, source?, chunk_index?}] — как у продуктового chunker.py."""
        if not chunks:
            return 0
        texts = [str(c["text"]) for c in chunks]
        vectors = self._embedder.embed_documents(texts)
        rows: list[dict[str, object]] = [
            {
                "vector": vec,
                "text": str(chunk["text"]),
                "source": str(chunk.get("source", "")),
                CABINET_FIELD: cabinet,  # схема brand-hub: колонка cabinet
                "chunk_index": chunk.get("chunk_index", 0),
            }
            for vec, chunk in zip(vectors, chunks, strict=True)
        ]
        self._store.add(rows)
        return len(rows)

    def search(
        self, query: str, top_k: int = DEFAULT_TOP_K, cabinet: str | None = None
    ) -> list[dict[str, object]]:
        """Возвращает list[{text, source, cabinet, score}] — форма ответа продукта."""
        categories = [cabinet] if cabinet else None
        hits = self._search.search(
            query, k=top_k, categories=categories, threshold=SIMILARITY_THRESHOLD
        )
        out: list[dict[str, object]] = []
        for h in hits:
            out.append(
                {"text": h.text, "source": h.source, "cabinet": h.category, "score": h.score}
            )
        return out

    def count(self) -> int:
        return self._store.count()

    def delete_by_source(self, source: str) -> None:
        """Удалить файл из индекса по source (во всех кабинетах) — как продуктовый API,
        но с экранированием SQL (оригинал слал сырую подстановку)."""
        self._store.delete_by_source_all(source)
