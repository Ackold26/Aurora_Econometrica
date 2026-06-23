"""GENERATED-shim: векторное хранилище переехало в общее ядро aurora_rag (ADR-027).

РАГ-движок (RoSBERTa + LanceDB + индексация) теперь живёт в каноне
aurora-platform-core/aurora_rag и синкается рядом как `aurora_rag/` (sync_to_products.py).
Публичный API `VectorStore` сохранён переходником ниже — server.py / brand_manager НЕ меняются.

НЕ редактировать логику здесь: правь канон в platform-core, перекатывай синк.
"""

from aurora_rag.adapters.brandhub import VectorStore  # noqa: F401
