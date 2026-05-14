"""Cross-platform file locking helper — Phase 1.7.

Wraps filelock.FileLock для защиты project.json read/write от конкурентных
записей при одновременном открытии проекта в нескольких вкладках.

Usage:
    from utils.file_lock import project_lock, LockTimeout

    with project_lock(project_dir):
        data = read_project_json(project_dir)
        data['key'] = value
        write_project_json(project_dir, data)
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from utils.log_config import setup_module_logger, log_event

logger = setup_module_logger(__name__)

# Lock file name — hidden dot-file рядом с project.json.
_LOCK_FILENAME = '.aurora.lock'


class LockTimeout(Exception):
    """Не удалось получить блокировку файла в отведённое время.

    Причина: другой процесс или вкладка браузера держит блокировку.
    Подождите и повторите операцию.
    """


@contextmanager
def project_lock(project_dir: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Контекстный менеджер — эксклюзивная блокировка каталога проекта.

    Создаёт lock-файл <project_dir>/.aurora.lock на время блока.
    Повторный вход из того же процесса (re-entrant) безопасен:
    filelock.FileLock использует счётчик рекурсии.

    Args:
        project_dir: путь к каталогу проекта (должен существовать).
        timeout: максимальное время ожидания в секундах (default 5.0).

    Raises:
        LockTimeout: если блокировка не получена за timeout секунд.
        ImportError: если пакет filelock не установлен (диагностическое).
    """
    try:
        import filelock
    except ImportError as exc:
        raise ImportError(
            'Пакет filelock не установлен. '
            'Добавьте filelock>=3.13 в requirements.txt и выполните pip install.'
        ) from exc

    lock_path = Path(project_dir) / _LOCK_FILENAME
    # is_singleton=True — один объект FileLock на lock_path в рамках процесса.
    # Это даёт re-entrant semantics: повторный acquire из того же процесса
    # увеличивает внутренний счётчик вместо deadlock-а.
    # Timeout НЕ передаётся конструктору (singleton требует идентичных аргументов
    # при каждом вызове). Вместо этого timeout передаётся в acquire().
    fl = filelock.FileLock(str(lock_path), is_singleton=True)

    log_event(
        logger,
        'file_lock_acquire_attempt',
        level=logging.DEBUG,
        lock_path=str(lock_path),
        timeout=timeout,
    )
    try:
        fl.acquire(timeout=timeout)
    except filelock.Timeout as exc:
        log_event(
            logger,
            'file_lock_timeout',
            level=logging.WARNING,
            lock_path=str(lock_path),
            timeout=timeout,
        )
        raise LockTimeout(
            f'Не удалось получить блокировку файла за {timeout:.1f} с: {lock_path}. '
            'Другой процесс или вкладка удерживает блокировку. '
            'Подождите и повторите операцию.'
        ) from exc

    log_event(
        logger,
        'file_lock_acquired',
        level=logging.DEBUG,
        lock_path=str(lock_path),
    )
    try:
        yield
    finally:
        fl.release()
        log_event(
            logger,
            'file_lock_released',
            level=logging.DEBUG,
            lock_path=str(lock_path),
        )


def lock_path_for(project_dir: Path) -> Path:
    """Возвращает путь к lock-файлу для проекта (вспомогательная функция)."""
    return Path(project_dir) / _LOCK_FILENAME
