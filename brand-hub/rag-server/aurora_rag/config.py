"""Дефолтные параметры РАГ-ядра.

Значения — общий знаменатель зрелой линии (``kb_vec`` / ``lib_vec``) и продуктового
``brand-hub``. Потребитель переопределяет нужное при создании движка; ядро ничего не
навязывает (размеры чанка осмысленно различаются под разный корпус — см. ADR-027).
"""

from __future__ import annotations

# Эмбеддер. ru-en-RoSBERTa — единственная модель во всех воплощениях экосистемы.
DEFAULT_MODEL: str = "ai-forever/ru-en-RoSBERTa"
# Переранжировщик (L1, opt-in). Cross-encoder, мультиязычный.
DEFAULT_RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"

# MTR-префиксы RoSBERTa: асимметричный поиск (запрос ≠ документ).
PREFIX_DOCUMENT: str = "search_document: "
PREFIX_QUERY: str = "search_query: "

# Чанкинг по умолчанию (продуктовый профиль brand-hub: 1000/150).
DEFAULT_CHUNK_SIZE: int = 1000
DEFAULT_CHUNK_OVERLAP: int = 150

# Поиск.
DEFAULT_TOP_K: int = 10
# Глубина невода перед переранжировкой. 30 хватает (урок lib_vec): reranker реально
# работает там, где совпадение настоящее; кросс-язык он не вытаскивает — это решается
# двуязычным запросом на векторном уровне, а не глубиной невода.
DEFAULT_RERANK_FETCH: int = 30
# Порог отсева по косинусу. Ядро НЕ отсекает по умолчанию (0.0); продукты задают свой
# (brand-hub исторически 0.15).
DEFAULT_SIMILARITY_THRESHOLD: float = 0.0

# Батч эмбеддинга. 32 — дефолт sentence-transformers (паритет с продуктовым stack'ом);
# на CPU крупнее батч = меньше overhead вызовов трансформера.
EMBED_BATCH_SIZE: int = 32

# Имя таблицы LanceDB по умолчанию.
DEFAULT_TABLE: str = "documents"
