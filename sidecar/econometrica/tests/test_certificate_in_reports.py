"""Блок «Воспроизводимость и сертификат» в отчёте и презентации (P0.7 шаг 15).

Стережём следствия:
    1. сертификата нет → блока нет ВОВСЕ (а не прочерки: обещать заверение,
       которого не существует, — тот самый класс дефекта, ради которого шли
       P0.4 и P0.5);
    2. «проверка неприменима» не смягчается до «пройдена» (долг P0.6);
    3. модель без паспорта воспроизводимости не выдаётся за заверенную;
    4. зерно печатается только когда оно записано;
    5. в презентацию сертификат попадает по тому же правилу «только настоящее»,
       что и витрины доверия.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from aurora_html.sections import _render_certificate_block  # noqa: E402
from engines.narrative_adapter import _map_pipeline_to_builder_data  # noqa: E402


def _сертификат(**переопределения):
    основа = {
        'status': 'issued',
        'reason': None,
        'hash': 'a' * 64,
        'certificate_version': '1.3',
        'reproducibility': {
            'status': 'recorded', 'seed': 555, 'seed_source': 'config',
            'mcmc': {'chains': 2, 'draws': 200, 'tune': 200},
        },
        'checks': {'negative_baseline': 'passed'},
    }
    основа.update(переопределения)
    return основа


# ── 1. Нет сертификата — нет блока ───────────────────────────────────────────

def test_без_сертификата_блока_нет():
    for пусто in (None, {}, 'строка', []):
        assert _render_certificate_block({'certificate': пусто}) == ''
    assert _render_certificate_block({}) == ''


def test_с_сертификатом_блок_есть():
    вывод = _render_certificate_block({'certificate': _сертификат()})
    assert 'Воспроизводимость и сертификат' in вывод
    assert 'a' * 64 in вывод, 'отпечаток не напечатан'


# ── 2. Долг P0.6: неприменимая проверка не выдаётся за пройденную ────────────

def test_неприменимая_проверка_не_названа_пройденной():
    вывод = _render_certificate_block({'certificate': _сертификат(
        checks={'negative_baseline': 'not_applicable'},
    )})
    assert 'неприменима' in вывод
    assert 'не завышен' not in вывод, (
        'текст «вклад каналов не завышен» — утверждение о пройденной проверке, '
        'а проверка не могла провалиться на этих данных'
    )


def test_пройденная_проверка_названа_прямо():
    вывод = _render_certificate_block({'certificate': _сертификат()})
    assert 'не завышен' in вывод


def test_проверки_нет_значит_о_ней_молчим():
    вывод = _render_certificate_block({'certificate': _сертификат(
        checks={'negative_baseline': 'absent'},
    )})
    assert 'Базовый уровень' not in вывод


# ── 3. Статус заверения честен ───────────────────────────────────────────────

def test_модель_без_паспорта_не_выдаётся_за_заверенную():
    вывод = _render_certificate_block({'certificate': _сертификат(
        status='not_attested',
        reproducibility={'status': 'absent'},
        reason='зерно не записано',
    )})
    assert 'Заверение неполное' in вывод
    assert 'Расчёт заверен' not in вывод
    assert 'Зерно генератора' not in вывод, (
        'зерна нет — печатать строку о нём значит выдумывать величину'
    )


def test_недоступное_заверение_называет_причину():
    вывод = _render_certificate_block({'certificate': {
        'status': 'unavailable',
        'reason': 'Канонизация JCS недоступна.',
        'hash': None,
        'reproducibility': {'status': 'absent'},
        'checks': {'negative_baseline': 'absent'},
    }})
    assert 'Заверение недоступно' in вывод
    assert 'Канонизация JCS недоступна.' in вывод


def test_зерно_и_его_источник_напечатаны():
    вывод = _render_certificate_block({'certificate': _сертификат()})
    assert '555' in вывод and 'задано в проекте' in вывод


# ── 4. Оговорка охвата обязательна ───────────────────────────────────────────

def test_охват_отпечатка_назван_прямо():
    """Поле хеша унаследовано от несуществующего «бандла» — клиент должен знать,
    что покрывается на самом деле."""
    вывод = _render_certificate_block({'certificate': _сертификат()})
    assert 'файл обученной модели' in вывод
    assert 'выгрузка' in вывод or 'выгрузк' in вывод


# ── 5. В презентацию попадает только настоящий сертификат ────────────────────

def _данные_конвейера(сертификат):
    разбивка = {
        'status': 'ok', 'total_sales': 10000.0, 'baseline': 6000.0,
        'channels': [{'name': 'ТВ', 'contribution': 4000.0, 'roi': 2.5,
                      'spend': 1600.0, 'contribution_pct': 100.0}],
    }
    if сертификат is not None:
        разбивка['methodology_certificate'] = сертификат
    return _map_pipeline_to_builder_data(
        {'diagnostics': {}}, разбивка, {}, None, project_id='проверка',
    )


def test_презентация_получает_настоящий_сертификат():
    данные = _данные_конвейера(_сертификат())
    assert данные.get('certificate', {}).get('hash') == 'a' * 64


def test_презентация_не_получает_пустой_сертификат():
    """Статус `unavailable` без хеша — не повод рисовать строку в слайде."""
    assert 'certificate' not in _данные_конвейера(None)
    без_хеша = _сертификат(status='unavailable', hash=None)
    assert 'certificate' not in _данные_конвейера(без_хеша)
