"""Сертификат методологии — живой прогон (P0.7 шаг 14).

Почему отдельным файлом: в CI нет PyMC, а этот сторож обязан реально обучить
модель и реально её декомпозировать. Структурная часть — в
`test_methodology_cert.py`, она идёт в CI. Разделение то же, что у проверки
отрицательной базы и у теста детерминизма.

Что доказывается (и чего структурный тест доказать не может):
    1. **«Функция подключена»** — сертификат доезжает до
       `results/decomposition.json`, то есть до артефакта, который читают
       отчёты, а не только до возвращаемого словаря. Именно этой проверки не
       хватало модулю, который 360 строк пролежал без единого вызывающего;
    2. статус `issued` достижим на свежей модели — у неё есть паспорт
       воспроизводимости (P0.2), в отличие от всех моделей, обученных раньше;
    3. хеш считается по НАСТОЯЩЕМУ манифесту файла модели, а не по выдумке:
       сверяем с манифестом, прочитанным из файла напрямую.
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


def _данные(путь: Path, n: int = 60) -> Path:
    rng = np.random.RandomState(7)
    tv = rng.uniform(200, 900, n)
    digital = rng.uniform(100, 600, n)
    competitor = rng.uniform(300, 1200, n)
    продажи = (
        4000
        + 1.8 * tv ** 0.75
        + 1.2 * digital ** 0.75
        - 0.9 * competitor
        + rng.normal(0, 250, n)
    )
    df = pd.DataFrame({
        'Дата': pd.date_range('2024-01-01', periods=n, freq='W'),
        'Продажи': продажи,
        'ТВ': tv,
        'Диджитал': digital,
        'Продажи конкурента': competitor,
    })
    файл = путь / 'data.xlsx'
    df.to_excel(файл, index=False)
    return файл


@pytest.fixture(scope='module')
def обученный_проект(tmp_path_factory):
    from engines.modeler import train_model

    каталог = tmp_path_factory.mktemp('cert_live')
    файл = _данные(каталог)
    результат = train_model({
        'data_file': str(файл),
        'kpi_column': 'Продажи',
        'media_columns': ['ТВ', 'Диджитал'],
        'control_columns': ['Продажи конкурента'],
        'date_column': 'Дата',
        'adstock_config': {},
        'mcmc_override': MCMC_OVERRIDE,
        'seed': SEED,
        'use_holidays': False,
    }, str(каталог))
    assert результат.get('status') == 'ok', результат
    return каталог


@pytest.fixture(scope='module')
def сертификат_из_файла(обученный_проект):
    """Читаем сохранённый на диск результат — не возврат функции."""
    from engines.decomposer import decompose

    итог = decompose(str(обученный_проект))
    assert итог['status'] == 'ok', итог
    путь = Path(обученный_проект) / 'results' / 'decomposition.json'
    сохранённое = json.loads(путь.read_text(encoding='utf-8'))
    return сохранённое.get('methodology_certificate')


def test_сертификат_доезжает_до_сохранённого_результата(сертификат_из_файла):
    """Главное доказательство подключения: он есть в файле, который читают отчёты."""
    assert сертификат_из_файла is not None, (
        'сертификата нет в results/decomposition.json — значит он снова '
        'посчитан и потерян по дороге'
    )
    assert сертификат_из_файла['hash']
    assert len(сертификат_из_файла['hash']) == 64


def test_свежая_модель_заверена_полностью(сертификат_из_файла):
    """Статус `issued` достижим, и зерно в паспорте — то самое, что задали."""
    assert сертификат_из_файла['status'] == 'issued', сертификат_из_файла.get('reason')
    паспорт = сертификат_из_файла['reproducibility']
    assert паспорт['status'] == 'recorded'
    assert паспорт['seed'] == SEED
    assert паспорт['seed_source'] == 'config'


def test_хеш_привязан_к_настоящему_манифесту_модели(обученный_проект, сертификат_из_файла):
    """Поле `bundle_manifest_hash` считается по манифесту файла модели.

    Бандла (выгрузки данных с manifest.json) в продукте не существует —
    решение владельца 2026-08-03: поле наполняется манифестом артефакта
    модели, реальным и с контрольными суммами. Здесь это и проверяется:
    берём манифест из файла независимо и сверяем хеш.
    """
    from engines.methodology_cert import compute_cert_hash
    from engines.persistence_safe import read_manifest

    манифест = read_manifest(Path(обученный_проект) / 'models' / 'latest.pkl')
    assert манифест.get('sha256_data'), 'манифест без контрольной суммы данных'
    ожидаемый = compute_cert_hash(
        {k: v for k, v in манифест.items() if not str(k).startswith('_cert')}
    )
    assert сертификат_из_файла['payload']['bundle_manifest_hash'] == ожидаемый


def test_в_величинах_нет_подставленных_нулей(сертификат_из_файла):
    """Ни одна доля и ни один ROI не равны нулю от подстановки."""
    payload = сертификат_из_файла['payload']
    сводка = payload['decomposition_summary']
    assert сводка, 'разбивка пуста'
    assert all(v['value'] != 0 for v in сводка.values())
    assert abs(sum(v['contribution_pct'] for v in сводка.values()) - 100.0) < 0.5
    for канал, запись in payload['channel_roi'].items():
        assert запись['roi'] != 0, канал
        if 'roi_ci_low' in запись:
            assert 'roi_ci_high' in запись, канал


def test_статус_проверки_базы_сходится_с_диагностикой(обученный_проект, сертификат_из_файла):
    """Долг P0.6: «пройдена» только если проверка МОГЛА провалиться.

    Сверяем не с ожиданием, а с фактом: берём диагностику самой модели и
    требуем, чтобы сертификат говорил ровно то же. Если проверка на этих
    данных нечувствительна (`detectable=False`), «passed» в сертификате —
    ложное утверждение о заверенном качестве.
    """
    путь = Path(обученный_проект) / 'results' / 'model-diagnostics.json'
    диагностика = json.loads(путь.read_text(encoding='utf-8'))
    nb = диагностика.get('negative_baseline')
    состояние = сертификат_из_файла['checks']['negative_baseline']

    if not nb:
        assert состояние == 'absent'
        return

    if not nb.get('detectable', True):
        assert состояние == 'not_applicable', (
            f'проверка была нечувствительна (detectable={nb.get("detectable")}, '
            f'нужно {nb.get("sigmas_needed")} сигм), а сертификат говорит '
            f'«{состояние}»'
        )
    else:
        ожидание = {'ok': 'passed', 'watch': 'watch', 'fail': 'failed',
                    'not_applicable': 'not_applicable'}[nb['verdict']]
        assert состояние == ожидание
