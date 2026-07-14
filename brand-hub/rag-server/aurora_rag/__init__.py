"""Aurora RAG Core — каноническое локальное РАГ-ядро экосистемы Aurora.

Эмбеддер ru-en-RoSBERTa + векторное хранилище LanceDB + чанкинг, сведённые из зрелой
линии (``kb_vec`` / ``lib_vec``) с накопленными аудит-уроками. Тонкие транспорты
(HTTP-sidecar продуктов, stdio шлюза, демон KB/библиотеки) строятся поверх как адаптеры.

Граница (ADR-027): здесь — L0 ядро + L1 опции (переранжировщик). Генерация, query-expansion,
доменный чанкинг и транспорты остаются у потребителей.

Базовая установка — без ML-зависимостей; реальный поиск требует extra ``[embed]``
(эмбеддер + LanceDB), переранжировка — ``[rerank]``, извлечение pdf/docx — ``[ingest]``.
"""

from __future__ import annotations

from .chunker import Chunker, ParagraphChunker, strip_frontmatter
from .config import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MODEL,
    DEFAULT_RERANK_MODEL,
    DEFAULT_TOP_K,
    PREFIX_DOCUMENT,
    PREFIX_QUERY,
)
from .embedder import Embedder
from .index import FileRef, Indexer
from .reranker import Reranker
from .search import SemanticSearch
from .store import VectorStore
from .types import Document, Hit, IndexStats

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_MODEL",
    "DEFAULT_RERANK_MODEL",
    "DEFAULT_TOP_K",
    "PREFIX_DOCUMENT",
    "PREFIX_QUERY",
    "Chunker",
    "Document",
    "Embedder",
    "FileRef",
    "Hit",
    "IndexStats",
    "Indexer",
    "ParagraphChunker",
    "Reranker",
    "SemanticSearch",
    "VectorStore",
    "__version__",
    "strip_frontmatter",
]
