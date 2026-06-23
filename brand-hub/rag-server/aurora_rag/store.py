"""Векторное хранилище — обёртка над LanceDB.

Сведено из ``vector_store.py`` (brand-hub) + зрелых аудит-уроков ``kb_vec`` / ``lib_vec``:
- **имя поля категории параметризовано** (``category_field``) — потребители с иной схемой
  (brand-hub хранит ``cabinet``) садятся на ядро БЕЗ миграции существующих индексов;
- удаление по СОСТАВНОМУ ключу ``(source, category)`` — НЕ только по ``source``: одноимённые
  файлы в разных категориях иначе тихо стираются (боевой урок);
- экранирование одинарной кавычки во ВСЕХ SQL-фильтрах LanceDB (апостроф в имени → ошибка);
- кэш handle таблицы (иначе ``list_tables`` + ``open_table`` на каждый поиск);
- гард пустого списка перед ``create_table`` / ``add`` (LanceDB валит ``ValueError`` на ``[]``);
- **запись сериализована замком** (``add`` / ``create`` / ``delete`` под ``Lock``) — sidecar
  обрабатывает запросы конкурентно; чтение (``search``) берёт локальную ссылку на handle
  и устойчиво к параллельной записи (LanceDB версионирует таблицу).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from .config import DEFAULT_TABLE, DEFAULT_TOP_K
from .types import Hit

if TYPE_CHECKING:
    from lancedb.db import DBConnection
    from lancedb.table import Table

# Строка LanceDB: vector + текст + метки. ``Any`` — значения разнотипны.
Row = dict[str, Any]


def _esc(value: str) -> str:
    """Экранировать одинарную кавычку для SQL-фильтра LanceDB."""
    return value.replace("'", "''")


class VectorStore:
    """LanceDB-хранилище одной таблицы документов.

    ``category_field`` — имя колонки категории в таблице (по умолчанию ``category``;
    brand-hub передаёт ``cabinet`` для совместимости со своими существующими индексами).
    """

    def __init__(
        self, db_path: str, table_name: str = DEFAULT_TABLE, *, category_field: str = "category"
    ) -> None:
        self.db_path = db_path
        self.table_name = table_name
        self.category_field = category_field
        self._db: DBConnection | None = None
        self._table: Table | None = None
        self._write_lock = threading.Lock()

    def _connect(self) -> DBConnection:
        if self._db is None:
            import lancedb

            self._db = lancedb.connect(self.db_path)
        return self._db

    def open_table(self, *, refresh: bool = False) -> Table | None:
        """Вернуть handle таблицы (кэш). ``None``, если таблицы ещё нет."""
        if refresh:
            self._table = None
        if self._table is None:
            db = self._connect()
            listed = db.list_tables()
            # lancedb 0.33: ListTablesResponse(tables=[...]); старые версии — просто список.
            names = getattr(listed, "tables", listed)
            self._table = db.open_table(self.table_name) if self.table_name in names else None
        return self._table

    def create(self, rows: list[Row]) -> None:
        """Пересоздать таблицу из строк (overwrite). Пустой список — no-op (гард)."""
        if not rows:
            return
        with self._write_lock:
            db = self._connect()
            # Кэшируем handle напрямую — без лишнего list_tables через refresh.
            self._table = db.create_table(self.table_name, data=rows, mode="overwrite")

    def add(self, rows: list[Row]) -> None:
        """Добавить строки. Создаёт таблицу, если её ещё нет. Пустой список — no-op."""
        if not rows:
            return
        with self._write_lock:
            table = self.open_table()
            if table is None:
                db = self._connect()
                self._table = db.create_table(self.table_name, data=rows, mode="overwrite")
            else:
                table.add(rows)

    def delete_by_source(self, source: str, category: str) -> None:
        """Удалить строки по составному ключу ``(source, category)`` (аудит-урок)."""
        with self._write_lock:
            table = self.open_table()
            if table is None:
                return
            table.delete(
                f"source = '{_esc(source)}' AND {self.category_field} = '{_esc(category)}'"
            )

    def delete_category(self, category: str) -> None:
        """Удалить все строки категории (идемпотентная переиндексация темы)."""
        with self._write_lock:
            table = self.open_table()
            if table is None:
                return
            table.delete(f"{self.category_field} = '{_esc(category)}'")

    def delete_by_source_all(self, source: str) -> None:
        """Удалить ВСЕ строки с данным source, независимо от категории. Для потребителей,
        где source глобально уникален (brand-hub: один файл = один source во всех кабинетах).
        Где категории значимы — пользуйся ``delete_by_source(source, category)``."""
        with self._write_lock:
            table = self.open_table()
            if table is None:
                return
            table.delete(f"source = '{_esc(source)}'")

    def count(self) -> int:
        table = self.open_table()
        return 0 if table is None else int(table.count_rows())

    def search(
        self,
        query_vector: list[float],
        *,
        k: int = DEFAULT_TOP_K,
        categories: list[str] | None = None,
        threshold: float = 0.0,
        fetch: int | None = None,
    ) -> list[Hit]:
        """Векторный поиск. ``categories`` — фильтр (IN по ``category_field``); ``threshold`` —
        отсев по косинусу (сравнение ДО округления — паритет с продуктовым поведением);
        ``fetch`` — сколько достать до отсева/переранжировки (по умолчанию = ``k``)."""
        # Локальная ссылка на handle — устойчива к параллельной перезаписи таблицы.
        table = self.open_table()
        if table is None:
            return []
        query = table.search(query_vector)
        if categories:
            joined = ", ".join("'" + _esc(c) + "'" for c in categories)
            query = query.where(f"{self.category_field} IN ({joined})")
        rows: list[Row] = query.limit(fetch or k).to_list()
        hits: list[Hit] = []
        for row in rows:
            score = 1.0 - float(row.get("_distance", 1.0))  # сравниваем с порогом ДО округления
            if score < threshold:
                continue
            hits.append(
                Hit(
                    source=str(row["source"]),
                    category=str(row.get(self.category_field, ".")),
                    score=round(score, 4),
                    text=str(row["text"]),
                    chunk_index=int(row.get("chunk_index", 0)),
                )
            )
        return hits[:k]
