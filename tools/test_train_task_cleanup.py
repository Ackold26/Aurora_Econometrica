"""Train task cleanup — характеризующие тесты мат-аудита 2026-07-02 (F-21).

Прежний cleanup удалял только задачи с consumed_at (>5 мин). Терминальные
задачи, чей result никто не забрал (фронт закрыт до done / error не прочитан /
cancelled — его result вообще не читается), НЕ имели consumed_at и жили в
памяти вечно вместе с полным result. Теперь: терминальные без consumed_at
старше 60 мин тоже чистятся (модель не теряется — она на диске).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_tasks():
    saved = dict(server._training_tasks)
    server._training_tasks.clear()
    yield
    server._training_tasks.clear()
    server._training_tasks.update(saved)


NOW = 1_000_000.0


def _task(status, started_ago, consumed_ago=None):
    t = {'status': status, 'phase': 'x', 'pct': 100,
         'elapsed_sec': 1.0, 'started_at': NOW - started_ago,
         'result': {'big': 'payload'}, 'error': None}
    if consumed_ago is not None:
        t['consumed_at'] = NOW - consumed_ago
    return t


def test_consumed_older_5min_removed():
    server._training_tasks['a'] = _task('done', 7200, consumed_ago=400)
    server._training_tasks['b'] = _task('done', 7200, consumed_ago=60)
    removed = server._cleanup_stale_training_tasks(now=NOW)
    assert removed == 1
    assert 'a' not in server._training_tasks
    assert 'b' in server._training_tasks  # consumed недавно — окно ретраев


def test_terminal_unconsumed_older_1h_removed():
    """Ядро F-21: done/error/cancelled без consumed_at старше часа — чистятся."""
    server._training_tasks['done_old'] = _task('done', 7200)
    server._training_tasks['err_old'] = _task('error', 7200)
    server._training_tasks['cancel_old'] = _task('cancelled', 7200)
    server._training_tasks['done_fresh'] = _task('done', 600)
    removed = server._cleanup_stale_training_tasks(now=NOW)
    assert removed == 3
    assert set(server._training_tasks) == {'done_fresh'}


def test_running_never_removed():
    """Работающая задача не чистится, сколько бы ни шла (MCMC бывает долгим)."""
    server._training_tasks['run_old'] = _task('running', 7200)
    removed = server._cleanup_stale_training_tasks(now=NOW)
    assert removed == 0
    assert 'run_old' in server._training_tasks


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
