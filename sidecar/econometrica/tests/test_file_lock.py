"""Tests для utils/file_lock.py — Phase 1.7."""
from __future__ import annotations

import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest


# ── Module-level helper для multiprocessing.spawn (cannot pickle local fns) ──

def _mp_child_try_acquire(lock_dir: str, result_queue) -> None:
    """Дочерний процесс пытается захватить лок с timeout=0."""
    # sys.path нужен в spawn-процессе (нет наследования)
    sidecar = str(Path(lock_dir).parent.parent)
    if sidecar not in sys.path:
        sys.path.insert(0, sidecar)
    from utils.file_lock import project_lock, LockTimeout  # noqa: PLC0415
    try:
        with project_lock(Path(lock_dir), timeout=0):
            result_queue.put('acquired')
    except LockTimeout:
        result_queue.put('timeout')
    except Exception as e:
        result_queue.put(f'error:{e}')

# Guard: skip all tests если filelock не установлен.
filelock = pytest.importorskip(
    'filelock',
    reason='filelock не установлен; добавьте filelock>=3.13 в requirements.txt',
)

from utils.file_lock import project_lock, lock_path_for, LockTimeout, _LOCK_FILENAME


class TestProjectLockBasic:
    def test_acquire_release_roundtrip(self, tmp_path):
        """Acquire + release без ошибок — базовый happy path."""
        with project_lock(tmp_path):
            pass  # должно войти и выйти без исключений

    def test_lock_file_path_correct(self, tmp_path):
        """Lock-файл создаётся в project_dir под именем .aurora.lock."""
        with project_lock(tmp_path):
            lock_file = tmp_path / _LOCK_FILENAME
            assert lock_file.exists(), f'lock file не существует: {lock_file}'

    def test_lock_file_path_helper(self, tmp_path):
        """lock_path_for() возвращает корректный путь."""
        expected = tmp_path / '.aurora.lock'
        assert lock_path_for(tmp_path) == expected

    def test_released_after_context_exit(self, tmp_path):
        """После выхода из контекста лок освобождён — второй acquire немедленно успешен."""
        with project_lock(tmp_path):
            pass
        # Если лок НЕ освобождён — следующий acquire повиснет до timeout.
        with project_lock(tmp_path, timeout=1.0):
            pass

    def test_body_executes(self, tmp_path):
        """Код внутри блока выполняется."""
        sentinel = tmp_path / 'sentinel.txt'
        with project_lock(tmp_path):
            sentinel.write_text('ok')
        assert sentinel.read_text() == 'ok'


class TestProjectLockReentrant:
    def test_nested_context_same_process(self, tmp_path):
        """Вложенный вход из одного процесса (re-entrant) безопасен."""
        with project_lock(tmp_path):
            # Второй acquire из того же процесса — должно пройти без deadlock.
            with project_lock(tmp_path, timeout=1.0):
                pass

    def test_triple_nested(self, tmp_path):
        """Три уровня вложенности не вызывают ошибок."""
        with project_lock(tmp_path):
            with project_lock(tmp_path, timeout=1.0):
                with project_lock(tmp_path, timeout=1.0):
                    pass


class TestProjectLockTimeout:
    def test_timeout_raises_lock_timeout(self, tmp_path):
        """Попытка acquire заблокированного файла из другого потока → LockTimeout."""
        import threading

        inner_acquired = threading.Event()
        hold_until = threading.Event()

        def hold_lock():
            with project_lock(tmp_path, timeout=5.0):
                inner_acquired.set()
                hold_until.wait(timeout=5.0)

        t = threading.Thread(target=hold_lock, daemon=True)
        t.start()
        inner_acquired.wait(timeout=5.0)

        try:
            with pytest.raises(LockTimeout):
                # timeout=0 — немедленно упасть если занято
                with project_lock(tmp_path, timeout=0):
                    pass
        finally:
            hold_until.set()
            t.join(timeout=5.0)

    def test_lock_timeout_is_exception_subclass(self):
        """LockTimeout наследует Exception — базовое требование."""
        assert issubclass(LockTimeout, Exception)

    def test_lock_timeout_message_russian(self, tmp_path):
        """Сообщение LockTimeout содержит информацию на русском."""
        import threading

        inner_acquired = threading.Event()
        hold_until = threading.Event()

        def hold_lock():
            with project_lock(tmp_path, timeout=5.0):
                inner_acquired.set()
                hold_until.wait(timeout=5.0)

        t = threading.Thread(target=hold_lock, daemon=True)
        t.start()
        inner_acquired.wait(timeout=5.0)

        try:
            with pytest.raises(LockTimeout) as exc_info:
                with project_lock(tmp_path, timeout=0):
                    pass
            msg = str(exc_info.value)
            assert 'блокировк' in msg.lower() or 'lock' in msg.lower(), (
                f'Сообщение не содержит упоминания блокировки: {msg!r}'
            )
        finally:
            hold_until.set()
            t.join(timeout=5.0)


class TestProjectLockConcurrent:
    def test_mutual_exclusion_threads(self, tmp_path):
        """Два потока не могут держать лок одновременно."""
        import threading

        overlap_detected = []
        lock_held = threading.Event()
        errors = []

        counter_file = tmp_path / 'counter.txt'
        counter_file.write_text('0')

        def worker(worker_id: int):
            try:
                with project_lock(tmp_path, timeout=5.0):
                    # Читаем + пишем без гонки — если МЭ работает, значения консистентны
                    val = int(counter_file.read_text())
                    counter_file.write_text(str(val + 1))
            except Exception as e:
                errors.append((worker_id, e))

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert not errors, f'Ошибки в потоках: {errors}'
        final = int(counter_file.read_text())
        assert final == 5, f'Ожидалось 5 инкрементов без гонки, получили {final}'

    def test_concurrent_acquire_serialized(self, tmp_path):
        """Несколько потоков выстраиваются в очередь, а не вылетают с ошибкой."""
        import threading

        results = []

        def worker():
            try:
                with project_lock(tmp_path, timeout=10.0):
                    results.append('ok')
            except LockTimeout:
                results.append('timeout')

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert results.count('ok') == 3, f'Ожидалось 3 успеха, получили: {results}'


class TestProjectLockMultiprocessing:
    def test_lock_blocks_second_process(self, tmp_path):
        """Дочерний процесс не может получить лок, пока родитель держит его."""
        import multiprocessing

        ctx = multiprocessing.get_context('spawn')
        result_q = ctx.Queue()

        with project_lock(tmp_path, timeout=5.0):
            proc = ctx.Process(
                target=_mp_child_try_acquire,
                args=(str(tmp_path), result_q),
                daemon=True,
            )
            proc.start()
            proc.join(timeout=10.0)

        result = result_q.get(timeout=5.0) if not result_q.empty() else 'no_result'
        assert result == 'timeout', (
            f'Дочерний процесс должен был получить LockTimeout, получил: {result!r}'
        )
