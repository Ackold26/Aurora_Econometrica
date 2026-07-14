"""Эмбеддер ru-en-RoSBERTa — обёртка над sentence-transformers.

Инварианты (унаследованы из зрелой линии + ADR-026 / INV-38):
- **0-egress по умолчанию.** ``HF_HUB_OFFLINE`` / ``TRANSFORMERS_OFFLINE`` выставлены на
  уровне модуля ДО любого импорта transformers — иначе hub-клиент инициализируется online
  на импорте (источник предупреждений «unauthenticated requests to HF Hub»). Модель берётся
  только из локального HF-кэша. Потребителю нужна разовая загрузка из сети (setup) →
  ``Embedder(offline=False)``.
- **Lazy singleton.** Тяжёлая модель (~1.5 ГБ + torch) грузится при первом обращении.
- **Асимметрия.** Документы и запрос префиксуются по-разному (MTR-схема RoSBERTa),
  векторы L2-нормированы → косинус как ``1 − _distance`` в LanceDB.
- **Windows OpenMP.** torch (libiomp5) и Arrow/LanceDB тянут разные OpenMP-рантаймы в один
  процесс → segfault. ``KMP_DUPLICATE_LIB_OK`` выставлен ЖЁСТКО на Windows до загрузки torch.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from .config import DEFAULT_MODEL, EMBED_BATCH_SIZE, PREFIX_DOCUMENT, PREFIX_QUERY

# 0-egress по умолчанию — ДО любого импорта sentence_transformers/transformers.
# setdefault: setup-сценарий (Embedder(offline=False)) переопределяет до загрузки.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# Windows OpenMP-коллизия torch+LanceDB → segfault. ЖЁСТКО (не setdefault): обход обязателен
# и должен стоять до загрузки torch (этот модуль импортируется раньше первого _load).
if sys.platform == "win32":
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sentence_transformers import SentenceTransformer


class Embedder:
    """RoSBERTa-эмбеддер. ``offline=True`` (дефолт) — только локальный кэш, 0 сети."""

    def __init__(self, model_name: str = DEFAULT_MODEL, *, offline: bool = True) -> None:
        self._model_name = model_name
        self._offline = offline
        self._model: SentenceTransformer | None = None

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            # Подтверждаем/снимаем offline ДО импорта (setup: offline=False тянет из сети).
            os.environ["HF_HUB_OFFLINE"] = "1" if self._offline else "0"
            os.environ["TRANSFORMERS_OFFLINE"] = "1" if self._offline else "0"
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed_documents(
        self, texts: Sequence[str], *, batch_size: int = EMBED_BATCH_SIZE
    ) -> list[list[float]]:
        """Эмбеддинг корпуса (префикс ``search_document:``, L2-норма)."""
        if not texts:
            return []
        model = self._load()
        vecs = model.encode(
            [PREFIX_DOCUMENT + t for t in texts],
            normalize_embeddings=True,
            batch_size=batch_size,
            show_progress_bar=False,
        )
        # .tolist() — C-оптимизированная конверсия numpy→list (быстрее поэлементного map(float)).
        result: list[list[float]] = vecs.tolist()
        return result

    def embed_query(self, text: str) -> list[float]:
        """Эмбеддинг запроса (префикс ``search_query:``, L2-норма)."""
        model = self._load()
        vec = model.encode(
            [PREFIX_QUERY + text], normalize_embeddings=True, show_progress_bar=False
        )[0]
        result: list[float] = vec.tolist()
        return result

    @property
    def dimension(self) -> int:
        """Размерность вектора — от модели (RoSBERTa = 1024). Хардкода нет."""
        model = self._load()
        # st 5.x: get_embedding_dimension; старые версии: get_sentence_embedding_dimension.
        getter = getattr(model, "get_embedding_dimension", None)
        if callable(getter):
            return int(getter())
        dim = model.get_sentence_embedding_dimension()
        return int(dim) if dim is not None else 1024
