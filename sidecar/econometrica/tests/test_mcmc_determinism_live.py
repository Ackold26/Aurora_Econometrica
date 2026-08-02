"""Настоящий прогон детерминизма MMM (P0.2) – живое обучение, не разбор кода.

Почему отдельным файлом и с меткой ``slow``:
    в CI нет PyMC (тяжёлые зависимости сайдкара там не ставятся), а этот тест
    обязан реально обучить модель трижды. Структурный сторож на зерно живёт
    отдельно – ``test_mcmc_seeding_ast.py``, он идёт в CI и PyMC не требует.
    Разделение намеренное: сторож, который в CI молча пропускается, не сторож.

Что доказывается:
    1. два обучения с одним зерном дают в точности одни и те же числа;
    2. обучение с другим зерном даёт другие – иначе «воспроизводимость»
       могла бы оказаться просто нечувствительностью на коротком прогоне,
       и сторож зеленел бы, даже если зерно никуда не доехало;
    3. паспорт воспроизводимости доезжает до результата и называет ярус
       сэмплера, который сработал на самом деле.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pymc = pytest.importorskip('pymc', reason='PyMC недоступен – живой прогон невозможен')

# Короткий прогон: цепей и выборок ровно столько, чтобы различие между
# зёрнами было заведомо видно, а тест оставался в пределах пары минут.
MCMC_OVERRIDE = {'chains': 2, 'draws': 50, 'tune': 50}
SEED_A = 42
SEED_B = 777


def _make_dataset(path: Path) -> None:
    """24 недели синтетики: связь с медиа есть, шум фиксирован.

    Данные обязаны быть одинаковыми во всех трёх обучениях, иначе тест
    сравнивал бы разные задачи. Поэтому свой генератор с постоянным
    зерном – он не имеет отношения к зерну сэмплера, которое и проверяем.
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(20260802)
    n = 24
    tv = rng.uniform(400_000, 1_200_000, n)
    digital = rng.uniform(200_000, 800_000, n)
    sales = (
        5_000_000
        + 1.8 * tv
        + 2.4 * digital
        + rng.normal(0, 150_000, n)
    )
    pd.DataFrame({
        'date': pd.date_range('2025-01-06', periods=n, freq='W-MON'),
        'tv': tv,
        'digital': digital,
        'sales': sales,
    }).to_excel(path, index=False)


def _train_once(tmp_root: Path, data_file: Path, seed: int, tag: str) -> dict:
    """Одно обучение со своим зерном в своей папке проекта."""
    from engines.modeler import train_model

    project_dir = tmp_root / f'project_{tag}'
    project_dir.mkdir(parents=True, exist_ok=True)
    result = train_model({
        'data_file': str(data_file),
        'kpi_column': 'sales',
        'media_columns': ['tv', 'digital'],
        'control_columns': [],
        'date_column': 'date',
        'kpi_type': 'sales',
        'adstock_config': {'tv': 'geometric', 'digital': 'geometric'},
        'mcmc_override': dict(MCMC_OVERRIDE),
        'seed': seed,
    }, str(project_dir))
    assert result.get('status') == 'ok', (
        f'Обучение {tag} не прошло: {result.get("error_code")} '
        f'{result.get("message")}'
    )
    return result


def _fingerprint(result: dict) -> str:
    """Отпечаток апостериорных оценок – то, что видит клиент.

    Сравниваются именно параметры каналов, а не сводные метрики: метрика
    может совпасть у разных выборок случайно, набор параметров – нет.
    """
    import json

    return json.dumps(result['channel_params'], sort_keys=True, default=str)


@pytest.mark.slow
def test_same_seed_reproduces_and_other_seed_differs(tmp_path):
    data_file = tmp_path / 'data.xlsx'
    _make_dataset(data_file)

    first = _train_once(tmp_path, data_file, SEED_A, 'a1')
    second = _train_once(tmp_path, data_file, SEED_A, 'a2')
    third = _train_once(tmp_path, data_file, SEED_B, 'b1')

    fp_first = _fingerprint(first)
    fp_second = _fingerprint(second)
    fp_third = _fingerprint(third)

    assert fp_first == fp_second, (
        'Два обучения с зерном {} дали разные параметры каналов – расчёт '
        'не воспроизводится.\nПервое: {}\nВторое: {}'.format(
            SEED_A, fp_first[:400], fp_second[:400]
        )
    )
    assert fp_first != fp_third, (
        'Обучение с зерном {} дало те же параметры, что и с зерном {}. '
        'Значит зерно до сэмплера не доехало, а совпадение выше ничего не '
        'доказывает.'.format(SEED_B, SEED_A)
    )


@pytest.mark.slow
def test_reproducibility_passport_reaches_result(tmp_path):
    """Паспорт расчёта доезжает до результата и называет фактический ярус."""
    data_file = tmp_path / 'data.xlsx'
    _make_dataset(data_file)
    result = _train_once(tmp_path, data_file, SEED_A, 'passport')

    passport = (result.get('mcmc_info') or {}).get('reproducibility')
    assert isinstance(passport, dict), (
        'В mcmc_info нет паспорта воспроизводимости – снимок среды до '
        'результата не доехал.'
    )
    assert passport['seed'] == SEED_A
    assert passport['seed_source'] == 'config'
    assert passport['sampler_tier'], (
        'Ярус сэмплера в паспорте пуст, хотя обучение прошло. Молчаливый '
        'откат на запасной ярус даёт другие числа при том же зерне – без '
        'записи яруса это неотличимо от дефекта расчёта.'
    )
    assert passport['versions']['pymc'], 'Версия PyMC в паспорте не записана'
    assert passport['mcmc']['chains'] == MCMC_OVERRIDE['chains']

    # Паспорт обязан лежать и в диагностике – её читают server.py и
    # honesty-аудит, для них это единственный источник.
    diag_passport = (result.get('diagnostics') or {}).get('reproducibility')
    assert isinstance(diag_passport, dict), (
        'В diagnostics нет паспорта воспроизводимости'
    )
    assert diag_passport['seed'] == SEED_A
