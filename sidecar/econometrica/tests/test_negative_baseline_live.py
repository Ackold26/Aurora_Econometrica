"""Перекрёстная сверка проверки канона с декомпозером — живое обучение (P0.6).

Почему отдельным файлом:
    в CI нет PyMC (тяжёлые зависимости сайдкара там не ставятся), а этот тест
    обязан реально обучить модель и реально её декомпозировать. Структурная
    часть проверки живёт в `test_negative_baseline.py` — она идёт в CI и PyMC
    не требует. Разделение намеренное, как у теста детерминизма: сторож,
    который в CI молча пропускается, не сторож.

Что доказывается:
    1. база, посчитанная по апостериорным выборкам при обучении, совпадает с
       базой, которую показывает декомпозиция, — иначе проверка канона гейтила
       бы одну величину, а пользователь видел бы другую (ровно тот класс
       дефекта, который чинили в P0.3 и в аудите починки);
    2. ключ реально доезжает до сохранённой диагностики, а не только считается;
    3. на здоровых данных проверка молчит — сторож, который срабатывает всегда,
       бесполезен так же, как тот, что не срабатывает никогда.

Допуск сверки. Декомпозиция досыпает в базу остаток подгонки ради тождества
разложения (`baseline = intercept + контроли + residual`), у которого
апостериорного распределения нет. Замер на этой же фикстуре: расхождение 0,12%.
Допуск взят 5% — с запасом на короткий прогон, но достаточно узко, чтобы
поймать подмену величины (перепутанный масштаб даёт разницу в разы: без
восстановления `y_std`/`y_mean` база оказывается −0,5 вместо 6528).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip('pymc', reason='PyMC недоступен – живой прогон невозможен')

MCMC_OVERRIDE = {'chains': 2, 'draws': 200, 'tune': 200}
SEED = 555
ДОПУСК = 0.05


def _данные(путь: Path, n: int = 60) -> Path:
    """Синтетика с положительной базой и контролем-конкурентом."""
    rng = np.random.RandomState(7)
    tv = rng.uniform(200, 900, n)
    digital = rng.uniform(100, 600, n)
    competitor = rng.uniform(300, 1200, n)
    distribution = rng.uniform(60, 95, n)
    продажи = (
        4000
        + 1.8 * tv ** 0.75
        + 1.2 * digital ** 0.75
        - 0.9 * competitor
        + 40 * distribution
        + rng.normal(0, 250, n)
    )
    df = pd.DataFrame({
        'Дата': pd.date_range('2024-01-01', periods=n, freq='W'),
        'Продажи': продажи,
        'ТВ': tv,
        'Диджитал': digital,
        'Продажи конкурента': competitor,
        'Дистрибуция': distribution,
    })
    файл = путь / 'data.xlsx'
    df.to_excel(файл, index=False)
    return файл


@pytest.fixture(scope='module')
def обученный_проект(tmp_path_factory):
    """Одно обучение на весь модуль — оно занимает секунды, но не бесплатно."""
    from engines.modeler import train_model

    каталог = tmp_path_factory.mktemp('negbase_live')
    файл = _данные(каталог)
    config = {
        'data_file': str(файл),
        'kpi_column': 'Продажи',
        'media_columns': ['ТВ', 'Диджитал'],
        'control_columns': ['Продажи конкурента', 'Дистрибуция'],
        'date_column': 'Дата',
        'adstock_config': {},
        'mcmc_override': MCMC_OVERRIDE,
        'seed': SEED,
        'use_holidays': False,
    }
    результат = train_model(config, str(каталог))
    assert результат.get('status') == 'ok', результат
    return каталог


def test_ключ_доезжает_до_сохранённой_диагностики(обученный_проект):
    """«Функция есть» ≠ «функция подключена»: проверяем файл, не возврат."""
    путь = Path(обученный_проект) / 'results' / 'model-diagnostics.json'
    diag = json.loads(путь.read_text(encoding='utf-8'))
    nb = diag.get('negative_baseline')
    assert nb is not None, 'проверка канона не доехала до диагностики'
    # Имя честное: считается величина ДО выноса факторов (аудит блока, Low).
    assert nb['basis'] == 'baseline_before_factor_breakout_mean'
    assert nb['n_draws'] > 0


def test_здоровые_данные_не_дают_ложной_тревоги(обученный_проект):
    """База заведомо положительна → проверка молчит.

    🔴 На этой фикстуре вердикт именно `not_applicable`, а не `ok`, и это
    правильно: разброс продаж мал относительно среднего, поэтому база не могла
    уйти в минус в принципе (нужны 26 сигм приора свободного члена). Замер и
    три живых прогона на заведомо больных наборах подтвердили нечувствительность.
    Выдавать здесь «годно» значило бы утверждать, что проверка что-то доказала.
    """
    путь = Path(обученный_проект) / 'results' / 'model-diagnostics.json'
    nb = json.loads(путь.read_text(encoding='utf-8'))['negative_baseline']
    assert nb['verdict'] in ('ok', 'not_applicable'), nb
    assert nb['prob_negative'] < 0.2
    assert nb['baseline_mean'] > 0
    # Чувствительность объявлена явно — читатель не должен её угадывать.
    assert 'detectable' in nb and 'sigmas_needed' in nb
    if not nb['detectable']:
        assert nb['verdict'] == 'not_applicable', (
            'проверка объявила «годно» там, где провалиться не могла'
        )


def test_база_совпадает_с_декомпозицией(обученный_проект):
    """🔴 Перекрёстная сверка, требуемая планом.

    Мутация «убрать восстановление масштаба» (`· y_std + y_mean`) красит тест
    по адресу: без неё база оказывается около −0,5 вместо тысяч, то есть
    проверка канона объявила бы провал на здоровой модели.
    """
    from engines.decomposer import decompose

    путь = Path(обученный_проект) / 'results' / 'model-diagnostics.json'
    nb = json.loads(путь.read_text(encoding='utf-8'))['negative_baseline']

    dec = decompose(str(обученный_проект), save_results=False)
    assert dec.get('status') == 'ok', dec
    серии = dec['decomposition_series']['series']
    база = np.asarray(
        next(s for s in серии if s['role'] == 'baseline')['data'], dtype=float)
    факторы = [
        np.asarray(s['data'], dtype=float) for s in серии if s['role'] == 'factor']
    # До выноса факторов — та же величина, что считает проверка канона.
    показанная = float((база + (sum(факторы) if факторы else 0)).mean())

    расхождение = abs(показанная - nb['baseline_mean']) / max(abs(показанная), 1e-9)
    assert расхождение < ДОПУСК, (
        f'база проверки канона {nb["baseline_mean"]:.1f} разошлась с показанной '
        f'{показанная:.1f} на {расхождение * 100:.1f}% — проверка гейтит не ту '
        f'величину, которую видит пользователь'
    )
