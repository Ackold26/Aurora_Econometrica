"""Ветка v2.0 сертификата не заверяет подставленное загрузчиком (C-1b).

Находка проверки класса C-1 (2026-08-17, зонд на живых моделях). Ветка
`_extract_v20_fields` собирала заверяемые величины через `or 0`:

    mcmc_diagnostics  → {'r_hat_max': 0.0, 'ess_min': 0.0}
    backtest_results  → {'mape': 0.0, 'rmse': 0.0, 'r2': 0.0}
    ppc_results       → {'r2': 0.0, 'durbin_watson': 0.0}
    holiday_dummies_injected → []
    analysis_mode     → 'roi'

Ни одного из этих полей обучение не пишет вовсе (свип по `modeler.py`: ноль
упоминаний `mcmc_diagnostics`, `holiday_dummies_injected`, `analysis_mode`), их
кладёт загрузчик как заглушки. То есть клиент читал в ЗАВЕРЕННОМ документе
«ошибка ретро-проверки 0 %, R² 0, R-hat 0» — модель, идеальная по построению.

Комментарий в модуле называл ветку недостижимой. Зонд 2026-08-17 показал
обратное: `is_v20_compatible` отвечает True при `model_version='2.0.0'` и
записанном `analysis_mode` — ровно то состояние, в которое модель приводит
`save_v20_diagnostics`. Живых вызывающих у неё сегодня нет, поэтому это не
пожар, а мина под первым же включением диагностики v2.0.

Правило блока: подставленное загрузчиком и незаписанное никем — оба НЕ
попадают в payload вовсе (ключ опускается). Ноль в заверенной величине —
утверждение об измерении, которого не было.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.methodology_cert import (  # noqa: E402
    _extract_v20_fields,
    build_cert_payload,
    generate_methodology_certificate,
)
from engines.persistence import LOADER_DEFAULTS_KEY  # noqa: E402

ПОЛЯ_ДИАГНОСТИКИ = ('mcmc_diagnostics', 'backtest_results', 'ppc_results',
                    'holiday_dummies_injected')


def _модель_v20(*, подставлено=(), **переопределения):
    """Модель, которую сертификат считает v2.0-совместимой.

    `подставлено` — имена полей, которые загрузчик положил сам: они лежат в
    словаре со своими заглушками И перечислены в следе, ровно как после
    `load_model_with_compat`.
    """
    данные = {
        'model_version': '2.0.0',
        'analysis_mode': 'effectiveness',
        'kpi_type': 'sales',
        'kpi_likelihood': 'normal',
        'config': {'kpi_type': 'sales', 'kpi_likelihood': 'normal'},
        'channel_params': {'ТВ': {}, 'Диджитал': {}},
        'channel_adstock_types': {'ТВ': 'geometric', 'Диджитал': 'weibull'},
        'diagnostics': {},
    }
    for имя in подставлено:
        данные.setdefault(имя, [] if имя.endswith('injected') else None)
    if подставлено:
        данные[LOADER_DEFAULTS_KEY] = list(подставлено)
    данные.update(переопределения)
    return данные


def _разбивка():
    return {
        'status': 'ok',
        'total_sales': 10000.0,
        'baseline': 6000.0,
        'channels': [
            {'name': 'ТВ', 'contribution': 3000.0, 'roi': 2.5},
            {'name': 'Диджитал', 'contribution': 1000.0, 'roi': 1.4},
        ],
    }


def _манифест():
    return {
        'format': 'aurora-model',
        'format_version': '1',
        'created_at': '2026-08-17T04:00:00+00:00',
        'array_count': 7,
        'model_version': '2.0.0',
        'sha256_data': 'a' * 64,
        'sha256_arrays': 'b' * 64,
    }


# ── Ветка достижима: без этого остальные проверки ничего не значат ───────────

def test_ветка_v20_достижима():
    """Опровержение комментария «ветка недостижима» (зонд 2026-08-17).

    Достаточно версии схемы 2.0.0 и записанного режима анализа — состояния,
    в которое модель приводит `save_v20_diagnostics`.
    """
    итог = generate_methodology_certificate(_модель_v20(), _разбивка(), _манифест())
    assert итог['certificate_version'] == '2.0.0'
    assert 'analysisMode' in итог['payload'], 'записанный режим обязан заверяться'
    assert итог['payload']['analysisMode'] == 'effectiveness'


# ── Подставленное загрузчиком не заверяется ──────────────────────────────────

@pytest.mark.parametrize('поле', ПОЛЯ_ДИАГНОСТИКИ)
def test_подставленная_загрузчиком_диагностика_не_уезжает_нулём(поле):
    """Ключа в payload нет вовсе. Ноль читался бы как измеренная величина."""
    модель = _модель_v20(подставлено=(поле,))
    payload = _extract_v20_fields(модель, _разбивка())
    assert поле not in payload, (
        f'подставленное загрузчиком поле {поле} уехало в заверенный документ '
        f'значением {payload.get(поле)!r}'
    )


@pytest.mark.parametrize('поле', ПОЛЯ_ДИАГНОСТИКИ)
def test_незаписанная_никем_диагностика_тоже_не_уезжает_нулём(поле):
    """Модель без следа (собрана в памяти, прочитана мимо загрузчика).

    Поля нет — значит его нет, а не «ноль». Отличать этот случай от
    подставленного клиенту незачем: заверять нечего в обоих.
    """
    модель = _модель_v20()
    модель.pop(поле, None)
    payload = _extract_v20_fields(модель, _разбивка())
    assert поле not in payload, f'ненаписанное поле {поле} вышло значением'


def test_режим_анализа_не_подставляется_на_roi():
    """`analysis_mode or 'roi'` объявлял режимом окупаемости любую модель.

    Достижимо запасным путём определения версии (`build_cert_payload`,
    ImportError у `is_v20_compatible`): там проверки записанного режима нет.
    """
    модель = _модель_v20(подставлено=('analysis_mode',))
    payload = _extract_v20_fields(модель, _разбивка())
    assert 'analysisMode' not in payload, (
        f'подставленный режим уехал в заверенный документ: {payload.get("analysisMode")!r}'
    )


# ── Записанное обучением по-прежнему заверяется ──────────────────────────────

def test_записанная_диагностика_заверяется_целиком():
    """Обратная сторона: сторож не должен вырезать настоящие измерения."""
    модель = _модель_v20(
        mcmc_diagnostics={'r_hat_max': 1.01, 'ess_min': 812.0},
        backtest_results={'metrics': {'mape': 12.4, 'rmse': 3300.0, 'r2': 0.78}},
        ppc_results={'r2': 0.81, 'durbin_watson': 1.94},
        holiday_dummies_injected=['ny', 'may_holidays'],
    )
    payload = _extract_v20_fields(модель, _разбивка())
    assert payload['mcmc_diagnostics'] == {'r_hat_max': 1.01, 'ess_min': 812.0}
    assert payload['backtest_results'] == {'mape': 12.4, 'rmse': 3300.0, 'r2': 0.78}
    assert payload['ppc_results'] == {'r2': 0.81, 'durbin_watson': 1.94}
    assert payload['holiday_dummies_injected'] == ['may_holidays', 'ny']


def test_настоящий_ноль_остаётся_нулём():
    """`or 0` съедал и настоящий ноль тоже — величина исчезала бы из документа.

    Ноль по Дарбину-Уотсону и нулевая ошибка ретро-проверки — величины
    вырожденные, но записанные: их обязано быть видно.
    """
    модель = _модель_v20(
        ppc_results={'r2': 0.0, 'durbin_watson': 0.0},
        backtest_results={'mape': 0.0, 'rmse': 0.0, 'r2': 0.0},
    )
    payload = _extract_v20_fields(модель, _разбивка())
    assert payload['ppc_results'] == {'r2': 0.0, 'durbin_watson': 0.0}
    assert payload['backtest_results'] == {'mape': 0.0, 'rmse': 0.0, 'r2': 0.0}


def test_половина_величин_записана_половины_нет():
    """Частичная запись: выходит записанное, отсутствующее не достраивается.

    Прежний код на такой модели напечатал бы `ess_min: 0.0` рядом с настоящим
    `r_hat_max` — и читатель не отличил бы одно от другого.
    """
    модель = _модель_v20(mcmc_diagnostics={'r_hat_max': 1.02})
    payload = _extract_v20_fields(модель, _разбивка())
    assert payload['mcmc_diagnostics'] == {'r_hat_max': 1.02}
    assert 'ess_min' not in payload['mcmc_diagnostics']


def test_пустой_словарь_диагностики_не_становится_нулями():
    """Ключ есть, содержимого нет — заверять всё равно нечего."""
    модель = _модель_v20(mcmc_diagnostics={}, ppc_results={})
    payload = _extract_v20_fields(модель, _разбивка())
    assert 'mcmc_diagnostics' not in payload
    assert 'ppc_results' not in payload


# ── Сквозная проверка через сборку payload ───────────────────────────────────

def test_сквозь_сертификат_подставленное_в_хеш_не_попадает():
    подставленная = _модель_v20(подставлено=ПОЛЯ_ДИАГНОСТИКИ)
    payload = build_cert_payload(подставленная, _разбивка(), _манифест())
    assert payload['certificate_version'] == '2.0.0'
    for поле in ПОЛЯ_ДИАГНОСТИКИ:
        assert поле not in payload, f'{поле} уехало в хешируемый payload'
    # Заверять при этом есть что: описание модели и разбивка на месте.
    assert payload['model_spec']['kpi_type'] == 'sales'
    assert payload['decomposition_summary']['Base']['contribution_pct'] == 60.0


def test_хеш_различает_записанное_и_подставленное():
    """Иначе заверение бессмысленно: два разных состояния дали бы одну подпись."""
    записанная = generate_methodology_certificate(
        _модель_v20(mcmc_diagnostics={'r_hat_max': 1.01, 'ess_min': 812.0}),
        _разбивка(), _манифест(),
    )
    подставленная = generate_methodology_certificate(
        _модель_v20(подставлено=('mcmc_diagnostics',)), _разбивка(), _манифест(),
    )
    assert записанная['hash'] != подставленная['hash']
