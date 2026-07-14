"""C3-N3 (2026-07-03): протухший путь к данным обучения — фолбэк и честная ошибка.

Боевая находка живого click-path: pickle хранил абсолютный Desktop-путь к
исходному xlsx; клиент переместил файл → goal-seek падал сырым
«[Errno 2] No such file or directory» через HTTP 500. Теперь: (1) живой путь
используется как есть; (2) файл с тем же именем в каталоге проекта — фолбэк;
(3) иначе понятная русская ошибка. Вживлено в inverse/optimizer/decomposer
(жёсткие пути) и scenario (мягкая деградация до None).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.data_file_resolver import resolve_data_file  # noqa: E402
from test_goalseek_honesty import _build_project, _moderate_target  # noqa: E402
from optimize.inverse import optimize_inverse  # noqa: E402


def test_live_path_used_as_is(tmp_path):
    f = tmp_path / 'data.csv'
    f.write_text('a,b\n1,2\n')
    assert resolve_data_file(str(f), None) == f


def test_stale_path_falls_back_to_project_dir(tmp_path):
    proj = tmp_path / 'proj'
    proj.mkdir()
    (proj / 'клиентские данные.xlsx').write_bytes(b'x')
    stale = r'C:\Users\ghost\Desktop\перемещённая папка\клиентские данные.xlsx'
    resolved = resolve_data_file(stale, proj)
    assert resolved == proj / 'клиентские данные.xlsx'


def test_missing_everywhere_clear_russian_error(tmp_path):
    with pytest.raises(FileNotFoundError) as ei:
        resolve_data_file(r'C:\nowhere\файл.xlsx', tmp_path)
    msg = str(ei.value)
    assert 'перемещён или удалён' in msg
    assert 'переобучите' in msg
    assert 'Errno' not in msg


def test_none_data_file_clear_error():
    with pytest.raises(FileNotFoundError) as ei:
        resolve_data_file(None, None)
    assert 'Импортируйте файл заново' in str(ei.value)


def test_goalseek_stale_data_file_gives_human_error(tmp_path):
    """E2E жёсткого пути: goal-seek на проекте с протухшим data_file (и без
    копии в проекте) отдаёт человекочитаемую ошибку, не Errno-traceback."""
    pdir = _build_project(tmp_path, 'stale', beta_sd=0.2, seed=7)
    # Протухание: перемещаем данные из проекта (и путь в pickle бьётся).
    (pdir / 'data.csv').rename(tmp_path / 'moved_away.csv')
    with pytest.raises(FileNotFoundError) as ei:
        optimize_inverse(str(pdir), target_sales=1.0, kpi_kind='monetary')
    msg = str(ei.value)
    assert 'перемещён или удалён' in msg, f'Ожидали понятную ошибку: {msg}'
    assert 'Errno' not in msg


def test_goalseek_recovers_via_project_dir_copy(tmp_path):
    """Фолбэк-путь: исходный путь протух, но файл лежит в каталоге проекта
    (имя совпадает) → goal-seek работает."""
    pdir = _build_project(tmp_path, 'recover', beta_sd=0.2, seed=7)
    from engines.persistence import load_model_with_compat
    pkl = pdir / 'models' / 'latest.pkl'
    md = load_model_with_compat(pkl)
    orig = Path(md['config']['data_file'])
    # Протухший путь в pickle; файл с тем же именем остаётся в проекте.
    md['config']['data_file'] = str(Path(r'C:\Users\ghost\Desktop') / orig.name)
    from engines.persistence_safe import save_model_safe
    save_model_safe(md, pkl)
    res = optimize_inverse(str(pdir), target_sales=_moderate_target(pdir), kpi_kind='monetary')
    assert res['achievable'] is True, f'Фолбэк на каталог проекта не сработал: {res}'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
