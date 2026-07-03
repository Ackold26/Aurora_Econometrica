"""C3-N3 (2026-07-03): устойчивое разрешение пути к файлу данных обучения.

Найдено живым click-path на реальном проекте: pickle хранит АБСОЛЮТНЫЙ путь
к исходному xlsx на момент обучения; клиент переместил/удалил файл (или
открыл проект на другой машине) → goal-seek/оптимизация/декомпозиция падали
сырым «[Errno 2] No such file or directory: C:\\Users\\...» через HTTP 500.

Правило: (1) путь жив — используем; (2) файл с тем же именем лежит в каталоге
проекта — используем его (с логом); (3) иначе — понятная русская ошибка,
которую UI показывает как есть.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger('econometrica')


def resolve_data_file(data_file: str | Path | None, project_dir: str | Path | None = None) -> Path:
    """Вернуть существующий путь к данным обучения или поднять понятную ошибку.

    Args:
        data_file: путь из config/pickle (мог протухнуть).
        project_dir: каталог проекта — фолбэк-поиск по имени файла.

    Raises:
        FileNotFoundError: с русским сообщением для пользователя (без Errno).
    """
    if not data_file:
        raise FileNotFoundError(
            'В модели не сохранён путь к файлу исходных данных. '
            'Импортируйте файл заново и переобучите модель.'
        )
    p = Path(data_file)
    if p.exists():
        return p
    if project_dir:
        cand = Path(project_dir) / p.name
        if cand.exists():
            logger.info(
                'data_file fallback: исходный путь протух (%s), найден файл в проекте: %s',
                p, cand,
            )
            return cand
    raise FileNotFoundError(
        f'Файл исходных данных не найден: «{p.name}» (путь: {p}). '
        f'Файл был перемещён или удалён после обучения модели. '
        f'Верните файл на прежнее место, либо импортируйте его заново и переобучите модель.'
    )
