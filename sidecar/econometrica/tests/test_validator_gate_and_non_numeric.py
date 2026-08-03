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
    # 🔴 Все ТРИ ветки порога, а не одна (внешний аудит починки, Medium,
    # 2026-08-03). Первая версия строила один набор — 12 наблюдений на 8 медиа,
    # гейт 1,3 — и попадала только в `insufficient_data`. Мутация, вернувшая
    # число в `low_data`, проходила зелёной: сторож молчал о двух ветках из трёх.
    # Наборы подобраны так, чтобы гейт попал в каждую: 12/8 → 1,3 (issue),
    # 25/8 → 2,8 (low_data), 40/10 → 3,6 (borderline_data).
    наборы = [
        ('insufficient_data', dict(n=12, n_media=8)),
        ('low_data', dict(n=25, n_media=8)),
        ('borderline_data', dict(n=40, n_media=10)),
    ]
    for ожидаемый_тип, параметры in наборы:
        каталог = tmp_path / ожидаемый_тип
        каталог.mkdir(exist_ok=True)
        res = _validate(_build(каталог, **параметры))
        выданные = res['issues'] + res['warnings']
        типы = {m['type'] for m in выданные}
        assert ожидаемый_тип in типы, (
            f'ветка {ожидаемый_тип} не сработала на наборе {параметры} — '
            f'проверка потеряла предмет; выдано: {sorted(типы)}'
        )
        сообщение = next(m['message'] for m in выданные if m['type'] == ожидаемый_тип)
        assert ':1' not in сообщение, f'в тексте снова стоит число запаса: {сообщение}'
        assert not any(ch.isdigit() for ch in сообщение), (
            f'в тексте появилось число: {сообщение}'
        )


def test_сообщение_о_нехватке_данных_всё_ещё_выдаётся(tmp_path):
    """Снятие числа не должно превратиться в снятие предупреждения."""
    res = _validate(_build(tmp_path, n=12, n_media=8))
    types = {m['type'] for m in res['issues'] + res['warnings']}
    assert types & {'insufficient_data', 'low_data', 'borderline_data'}


# ── Medium: нечисловая колонка ──────────────────────────────────────────────

def test_нечисловая_колонка_получает_долю_непригодных_значений(tmp_path):
    """Раньше `stats` не было вовсе → пять экранов показывали «0% пропусков».

    Внешний аудит починки (Medium, 2026-08-03): пропуски и нечитаемые значения
    разведены. Пустая ячейка — не «нечитаемое значение»: при обучении она станет
    нулём, как и в числовой колонке, и совет «очистите ячейки» противоречил бы
    собственному счёту, если считать их вместе.
    """
    n = 40
    rng = np.random.RandomState(1)
    broken = [str(round(v, 2)) for v in rng.uniform(10, 100, n)]
    broken[3] = 'н/д'
    broken[7] = 'нет данных'
    broken[11] = None
    broken[12] = None
    f = _build(tmp_path, n=n, n_media=3, digital_spend=broken)

    res = _validate(f)
    col = next(c for c in res['columns'] if c['name'] == 'digital_spend')
    assert col.get('stats'), 'у нечисловой колонки снова нет статистики'
    assert col['stats']['non_numeric_pct'] == 5.0, 'нечитаемых ровно два («н/д», «нет данных»)'
    assert col['stats']['nulls'] == 2, 'пустые ячейки считаются отдельно'
    assert col['stats']['missing_pct'] == 5.0, 'доля пропусков — про пустые, не про текст'


def test_пустые_ячейки_не_объявляются_нечитаемыми(tmp_path):
    """Колонка с ОДНИМИ пропусками не должна получать critical.

    Мутация «считать пропуски вместе с текстом» красит тест: одни и те же данные
    получали бы то critical, то мягкое предупреждение — в зависимости от того,
    есть ли рядом текстовая ячейка.
    """
    n = 40
    rng = np.random.RandomState(2)
    vals = [str(round(v, 2)) for v in rng.uniform(10, 100, n)]
    vals[1] = None
    vals[2] = None
    res = _validate(_build(tmp_path, n=n, n_media=3, digital_spend=vals))
    col = next(c for c in res['columns'] if c['name'] == 'digital_spend')
    # Колонка без текста читается как числовая — нечитаемых в ней нет по
    # определению, и путь тот же, что был до правки.
    assert col['stats'].get('non_numeric_pct', 0.0) == 0.0
    assert not [i for i in res['issues'] if i.get('type') == 'non_numeric_values']
    assert not [i for i in res['issues'] if i.get('type') == 'non_numeric_format']
    типы = {w['type'] for w in res['warnings'] if w.get('column') == 'digital_spend'}
    assert 'missing_filled_with_zero' in типы, 'про пропуски продукт обязан сказать'


def test_русская_десятичная_запятая_не_объявляется_текстом(tmp_path):
    """Один парсер числа на всю функцию (внешний аудит починки, Medium).

    Гейт роли `_is_numeric_parseable` принимает «11,35» и валюту, а первая версия
    ветки звала голый `to_numeric` и объявляла те же значения нечитаемыми —
    critical выпадал на КАЖДУЮ денежную колонку файла из русского Excel, с
    советом «замените текст числами», который пользователю нечего исполнить.
    Обучение на такой колонке всё равно падает, поэтому предупреждение остаётся,
    но говорит про ФОРМАТ.
    """
    n = 40
    rng = np.random.RandomState(4)
    ru = [f'{v:.2f}'.replace('.', ',') for v in rng.uniform(10, 90, n)]
    res = _validate(_build(tmp_path, n=n, n_media=3, radio_spend=ru))
    col = next(c for c in res['columns'] if c['name'] == 'radio_spend')
    assert col['stats']['non_numeric_pct'] == 0.0, 'числа с запятой не «текст»'
    assert not [i for i in res['issues'] if i.get('type') == 'non_numeric_values']
    issue = next((i for i in res['issues'] if i.get('type') == 'non_numeric_format'), None)
    assert issue is not None, 'молчать нельзя: обучение на такой колонке упадёт'
    assert 'десятичной запятой' in issue['message']
    assert 'замените текст числами' not in issue['message'].lower()


def test_запятая_как_разделитель_разрядов_тоже_читается(tmp_path):
    """Обе трактовки запятой, а не одна.

    Первый заход этого сторожа мутацию «оставить только десятичную трактовку»
    пропустил зелёной — набор состоял из «11,35», где обе трактовки дают число.
    Различие проявляется на денежных строках вида «3,836,962 ₽»: как десятичная
    запятая они не читаются вовсе, как разделитель разрядов — читаются. Именно
    их принимает гейт роли, и именно на них разъезжались два парсера.
    """
    n = 40
    rng = np.random.RandomState(5)
    money = [f'{int(v):,} ₽'.replace('_', ',') for v in rng.uniform(1_000_000, 9_000_000, n)]
    assert ',' in money[0], 'набор обязан содержать разделитель разрядов'
    res = _validate(_build(tmp_path, n=n, n_media=3, tv_budget=money))
    col = next(c for c in res['columns'] if c['name'] == 'tv_budget')
    assert col['stats'].get('non_numeric_pct', 0.0) == 0.0, (
        'денежные строки с разделителем разрядов объявлены нечитаемыми — '
        'парсер снова разошёлся с гейтом роли'
    )
    assert not [i for i in res['issues'] if i.get('type') == 'non_numeric_values']


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
