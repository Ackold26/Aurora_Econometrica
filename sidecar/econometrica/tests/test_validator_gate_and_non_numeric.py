"""Сторожа валидатора по находкам внешнего аудита блока P0.2–P0.5 (2026-08-03).

Две находки, обе про одно — про число, которое видит пользователь.

**High.** Пороги `issues`/`warnings` считаются по самому мягкому знаменателю
(OLS) сознательно: валидация идёт ДО выбора режима, и объявлять «критически
мало» проекту, который в OLS считается нормально, значит отнять у него режим,
созданный для коротких рядов. Но в ТЕКСТ сообщения подставлялось то же мягкое
число, а экран рядом показывал байесовское — пользователь видел «Ratio 2.7:1 –
ниже минимума» от движка и «1,3 – критически мало» в карточке над ним. Движок
режима не знает и знать не может, поэтому говорит качественно; число показывает
экран, который режим знает. Само число уезжает отдельным полем `ratio_gate` —
по нему фронт гейтит кнопку и сверяется с движком.

**Medium, уточнён зондом в худшую сторону.** Блок `stats` считался только для
числовых колонок, и пять экранов через `?? 0` показывали «0% пропусков» именно
на самой битой колонке. Зонд поведения обучения: текстовая ячейка («н/д») вообще
не пропуск — `isna()` даёт ноль, — а `modeler.py` делает
`df[col].fillna(0).values.astype(float)` и падает с ValueError на первой же
нечисловой ячейке. То есть пользователь спокойно проходил валидацию и получал
отказ на обучении, без объяснения причины.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


def _validate(data_file: Path) -> dict:
    from engines.validator import validate_data
    return validate_data(str(data_file))


def _build(tmp_path: Path, n: int = 40, n_media: int = 8, **extra) -> Path:
    """Датасет на n наблюдений с n_media медиа-каналами."""
    rng = np.random.RandomState(0)
    data = {
        'Дата': pd.date_range('2024-01-01', periods=n, freq='W'),
        'sales_rub': rng.uniform(100, 1000, n),
    }
    for i in range(n_media):
        data[f'tv_spend_{i}'] = rng.uniform(50, 500, n)
    data.update(extra)
    df = pd.DataFrame(data)
    f = tmp_path / 'data.xlsx'
    df.to_excel(f, index=False)
    return f


# ── High: число не печатается в тексте, но уезжает полем ────────────────────

def test_gate_ratio_отдаётся_отдельным_полем(tmp_path):
    """Фронт гейтит кнопку этим числом — без него он гадал бы сам."""
    res = _validate(_build(tmp_path, n=40, n_media=8))
    detected = res['detected']
    assert 'ratio_gate' in detected, 'поле гейта пропало — фронту нечем сверяться с движком'
    # Зеркало формулы движка: наблюдения / (предикторы + свободный член).
    expected = 40 / detected['n_params_effective_ols']
    assert abs(detected['ratio_gate'] - round(expected, 1)) < 0.11


def test_тексты_порогов_не_несут_числа(tmp_path):
    """Мутация «вернуть f'Ratio {ratio_gate:.1f}:1'» красит этот тест.

    Предмет охраны — не формулировка, а сам факт: в сообщении, которое видит
    пользователь, не должно стоять число запаса данных. Иначе на одном экране
    снова окажутся два разных числа одной величины.
    """
    # 12 наблюдений на 8 медиа — гарантированно ниже всех трёх порогов.
    res = _validate(_build(tmp_path, n=12, n_media=8))
    messages = [m['message'] for m in res['issues'] + res['warnings']]
    гейтовые = [
        m for m in messages
        if 'наблюдений на параметр' in m.lower() or 'ratio' in m.lower()
    ]
    assert гейтовые, 'ни одно сообщение о запасе данных не выдано — проверка потеряла предмет'
    for m in гейтовые:
        assert ':1' not in m, f'в тексте снова стоит число запаса данных: {m}'
        assert not any(ch.isdigit() for ch in m), f'в тексте появилось число: {m}'


def test_сообщение_о_нехватке_данных_всё_ещё_выдаётся(tmp_path):
    """Снятие числа не должно превратиться в снятие предупреждения."""
    res = _validate(_build(tmp_path, n=12, n_media=8))
    types = {m['type'] for m in res['issues'] + res['warnings']}
    assert types & {'insufficient_data', 'low_data', 'borderline_data'}


# ── Medium: нечисловая колонка ──────────────────────────────────────────────

def test_нечисловая_колонка_получает_долю_непригодных_значений(tmp_path):
    """Раньше `stats` не было вовсе → пять экранов показывали «0% пропусков»."""
    n = 40
    rng = np.random.RandomState(1)
    broken = [str(round(v, 2)) for v in rng.uniform(10, 100, n)]
    broken[3] = 'н/д'
    broken[7] = 'нет данных'
    f = _build(tmp_path, n=n, n_media=3, digital_spend=broken)

    res = _validate(f)
    col = next(c for c in res['columns'] if c['name'] == 'digital_spend')
    assert col.get('stats'), 'у нечисловой колонки снова нет статистики'
    assert col['stats']['missing_pct'] > 0, 'доля непригодных значений показана нулём'
    assert col['stats']['nulls'] == 2
    assert col['stats']['missing_pct'] == 5.0  # 2 из 40


def test_нечисловая_колонка_объявлена_прямо_а_не_молча(tmp_path):
    """Обучение на такой колонке падает — молчать об этом нельзя.

    Мутация «убрать issue, оставив только stats» красит тест: пользователь
    снова доходил бы до обучения и получал ValueError без объяснения.
    """
    n = 40
    rng = np.random.RandomState(1)
    broken = [str(round(v, 2)) for v in rng.uniform(10, 100, n)]
    broken[5] = 'н/д'
    res = _validate(_build(tmp_path, n=n, n_media=3, digital_spend=broken))

    issue = next(
        (i for i in res['issues'] if i.get('type') == 'non_numeric_values'), None
    )
    assert issue is not None, 'нечисловая колонка прошла валидацию молча'
    assert issue['column'] == 'digital_spend'
    assert issue['severity'] == 'critical'
    # Пользователю говорится и что случится, и что делать.
    assert 'не запустится' in issue['message']
    assert 'н/д' in issue['message'], 'пример непригодного значения не показан'


def test_здоровая_колонка_молчит(tmp_path):
    """Проверка тишины: сторож не должен красить нормальные данные."""
    res = _validate(_build(tmp_path, n=40, n_media=8))
    assert not [i for i in res['issues'] if i.get('type') == 'non_numeric_values']
    for c in res['columns']:
        if c.get('role') in ('media', 'control', 'kpi'):
            assert not c.get('stats', {}).get('non_numeric')
