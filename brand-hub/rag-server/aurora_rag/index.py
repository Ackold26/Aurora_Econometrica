"""Индексатор: full / add / incremental с mtime-state и атомарной записью STATE.

Сведено из зрелой линии (``kb_vec`` / ``lib_vec``) — у продуктового ``brand-hub`` инкрементальной
индексации НЕТ (полная переиндексация при каждой загрузке). Унаследованные уроки:
- **incremental по mtime-state:** delete+reembed ТОЛЬКО изменённых/удалённых файлов; смена
  категории при том же пути тоже считается изменением (старая строка удаляется по СТАРОЙ
  категории, новая пишется по новой);
- **атомарная запись STATE** (уникальный tmp + ``os.replace``): фиксированное имя tmp ловит
  гонку при конкурентной индексации одного корпуса → берём ``tmp`` с pid+счётчиком;
- **битый STATE логируется и бэкапится** (``.json.corrupt``), а не молча роняет в полный реэмбед;
- **удаление по составному ключу** ``(source, category)`` (через ``VectorStore``);
- **категория хранится в STATE** рядом с mtime — у удалённого файла её из пути не восстановить.

Имя поля категории берётся из ``store.category_field`` (brand-hub = ``cabinet``).
Ядро НЕ знает раскладку файлов потребителя: источник — список ``FileRef`` + функция чтения.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from .chunker import Chunker, ParagraphChunker, strip_frontmatter
from .config import EMBED_BATCH_SIZE
from .types import IndexStats

if TYPE_CHECKING:
    from .embedder import Embedder
    from .store import Row, VectorStore

ReadText = Callable[[str], str]

logger = logging.getLogger("aurora_rag.index")

# Монотонный счётчик для уникальных tmp-имён STATE в рамках процесса (без global-стейтмента).
_tmp_seq = itertools.count()


class StateEntry(TypedDict):
    """Запись STATE: время модификации + категория (для удаления при пропаже/смене)."""

    m: float
    c: str


@dataclass(frozen=True)
class FileRef:
    """Ссылка на файл корпуса: нормализованный путь-ключ, категория, время модификации."""

    path: str
    category: str
    mtime: float


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _read_md(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


class Indexer:
    """Строит и поддерживает индекс корпуса в ``VectorStore``."""

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        chunker: Chunker | None = None,
        state_path: str | None = None,
        preprocess: Callable[[str], str] = strip_frontmatter,
        batch_size: int = EMBED_BATCH_SIZE,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.chunker: Chunker = chunker or ParagraphChunker()
        self.state_path = state_path
        self.preprocess = preprocess
        self.batch_size = batch_size

    # ── STATE ──
    def _load_state(self) -> dict[str, StateEntry]:
        if not self.state_path:
            return {}
        path = Path(self.state_path)
        if not path.exists():
            return {}
        try:
            raw: dict[str, StateEntry] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "STATE повреждён (%s): %s — будет полная переиндексация", self.state_path, exc
            )
            # сохраним битый файл для разбора, не теряем молча
            with contextlib.suppress(OSError):
                path.replace(path.with_suffix(".json.corrupt"))
            return {}
        else:
            return raw

    def _save_state(self, state: dict[str, StateEntry]) -> None:
        if not self.state_path:
            return
        path = Path(self.state_path)
        # Уникальный tmp (pid+счётчик): фиксированное имя ловило бы гонку конкурентной индексации.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{next(_tmp_seq)}.tmp")
        try:
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

    @staticmethod
    def _state_of(refs: list[FileRef]) -> dict[str, StateEntry]:
        return {r.path: {"m": r.mtime, "c": r.category} for r in refs}

    # ── эмбеддинг файлов в строки ──
    def _embed(self, refs: list[FileRef], read_text: ReadText) -> tuple[list[Row], int]:
        texts: list[str] = []
        sources: list[str] = []
        categories: list[str] = []
        chunk_idx: list[int] = []
        for ref in refs:
            try:
                body = self.preprocess(read_text(ref.path))
            except (OSError, ValueError):
                continue
            if not body.strip():
                continue
            for i, chunk in enumerate(self.chunker.split(body)):
                texts.append(chunk)
                sources.append(_stem(ref.path))
                categories.append(ref.category)
                chunk_idx.append(i)
        if not texts:
            return [], 0
        vectors = self.embedder.embed_documents(texts, batch_size=self.batch_size)
        cat_field = self.store.category_field
        rows: list[Row] = [
            {"vector": v, "text": t, "source": s, cat_field: c, "chunk_index": i}
            for v, t, s, c, i in zip(vectors, texts, sources, categories, chunk_idx, strict=True)
        ]
        return rows, len(rows)

    # ── full ──
    def index_full(self, refs: list[FileRef], read_text: ReadText = _read_md) -> IndexStats:
        rows, chunks = self._embed(refs, read_text)
        if rows:
            self.store.create(rows)
        self._save_state(self._state_of(refs))
        return IndexStats(added=len(refs), total_files=len(refs), chunks=chunks)

    # ── add (идемпотентно по категориям) ──
    def index_add(
        self, refs: list[FileRef], categories: list[str], read_text: ReadText = _read_md
    ) -> IndexStats:
        catset = set(categories)
        scoped = [r for r in refs if r.category in catset]
        for category in sorted(catset):
            self.store.delete_category(category)
        rows, chunks = self._embed(scoped, read_text)
        self.store.add(rows)
        state = self._load_state()
        state = {p: e for p, e in state.items() if e["c"] not in catset}
        state.update(self._state_of(scoped))
        self._save_state(state)
        return IndexStats(added=len(scoped), total_files=len(scoped), chunks=chunks)

    # ── incremental (по mtime-state + смене категории) ──
    def index_incremental(self, refs: list[FileRef], read_text: ReadText = _read_md) -> IndexStats:
        state = self._load_state()
        current = {r.path: r for r in refs}
        changed: list[FileRef] = []
        for ref in refs:
            prev = state.get(ref.path)
            if prev is None or abs(prev["m"] - ref.mtime) > 1e-6 or prev["c"] != ref.category:
                changed.append(ref)
        removed = [(p, e["c"]) for p, e in state.items() if p not in current]
        # удаляем устаревшие/изменённые по СТАРОЙ категории (из STATE) — иначе смена категории
        # оставит дубль в старой категории
        for path, category in removed:
            self.store.delete_by_source(_stem(path), category)
        for ref in changed:
            prev = state.get(ref.path)
            old_category = prev["c"] if prev else ref.category
            self.store.delete_by_source(_stem(ref.path), old_category)
        rows, chunks = self._embed(changed, read_text)
        self.store.add(rows)
        new_state = {p: e for p, e in state.items() if p in current}
        new_state.update(self._state_of(refs))
        self._save_state(new_state)
        return IndexStats(
            changed=len(changed),
            removed=len(removed),
            total_files=len(refs),
            chunks=chunks,
        )
