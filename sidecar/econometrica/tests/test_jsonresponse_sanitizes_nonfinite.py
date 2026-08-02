"""Non-finite в ответах server.py (находка 2026-07-27, побочный эффект тестов A6/A7).

/compute/preflight падал 500-кой 'Out of range float values are not JSON
compliant: inf' на коллинеарных данных (quick_proxy_check::condition_number
после центрирования = inf) - starlette JSONResponse кидает ValueError при
попытке сериализовать non-finite float (RFC 8259 запрещает NaN/Inf в JSON).
Клиент (ConfigPanel.svelte) на этой ошибке fail-open проезжает БЕЗ гейта
честности - без единого предупреждения ровно там, где мультиколлинеарность
делает предупреждение нужнее всего.

Аудит (грепом всех JSONResponse(content=...) в server.py): 62 вызова, только 2
(train_model, decompose_sales) явно санировали результат sanitize_nonfinite
вручную - 60 были уязвимы к тому же классу при любом вычислении, дающем
inf/NaN. Решение - не 60 точечных правок (риск повторить историю MQS-нуля,
см. commit 70b5d99), а локальный подкласс `JSONResponse` в server.py,
дезинфицирующий content в render() один раз для всех вызовов.
"""
from __future__ import annotations

import json

import pytest

from server import JSONResponse, PreflightRequest, preflight


def _body(response) -> dict:
    return json.loads(response.body)


def _write_collinear_csv(path, n_obs: int = 5) -> None:
    """tv и digital - линейно зависимые ряды (digital = tv - 50), поэтому после
    центрирования condition number матрицы улетает в inf/очень большое число -
    ровно тот вход, который уронил preflight() на 500-ке до правки."""
    lines = ['date,sales,tv,digital']
    for i in range(n_obs):
        tv = 100 + i * 11
        digital = tv - 50
        lines.append(f'2026-01-{i + 1:02d},{1000 + i * 37},{tv},{digital}')
    path.write_text('\n'.join(lines), encoding='utf-8')


def _write_well_conditioned_csv(path, n_obs: int = 40) -> None:
    lines = ['date,sales,tv,digital']
    for i in range(n_obs):
        tv = 100 + (i * 37) % 90
        digital = 40 + (i * 53) % 70
        lines.append(f'2026-01-{(i % 28) + 1:02d},{1000 + i * 37},{tv},{digital}')
    path.write_text('\n'.join(lines), encoding='utf-8')


# ─── Юнит: подкласс JSONResponse дезинфицирует контент независимо от эндпоинта ─

class TestJSONResponseSubclassSanitizes:

    def test_inf_and_nan_become_null_finite_values_survive(self):
        resp = JSONResponse(content={
            'a': float('inf'),
            'b': float('-inf'),
            'c': float('nan'),
            'd': 1.5,
            'e': 0,
            'f': 'text',
            'g': None,
            'nested': {'h': [float('inf'), 2.0, 'x']},
        })
        body = _body(resp)
        assert body['a'] is None
        assert body['b'] is None
        assert body['c'] is None
        assert body['d'] == 1.5
        assert body['e'] == 0
        assert body['f'] == 'text'
        assert body['g'] is None
        assert body['nested']['h'] == [None, 2.0, 'x']


# ─── Сквозной сценарий: /compute/preflight на коллинеарных данных ─────────────

class TestPreflightSurvivesNonFiniteQuickProxy:

    def test_collinear_data_no_longer_crashes_preflight(self, tmp_path):
        """До правки: ValueError при построении JSONResponse внутри preflight()
        - исключение уходит в глобальный обработчик, клиент получает 500 и
        (по коду ConfigPanel.svelte) тихо остаётся БЕЗ гейта честности."""
        csv_path = tmp_path / 'data.csv'
        _write_collinear_csv(csv_path)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            skip_prior_predictive=True,
        )
        content = _body(preflight(req))  # не должно кидать ValueError
        assert content['status'] == 'ok'

    def test_non_finite_condition_number_reaches_client_as_null_not_infinity(self, tmp_path):
        """Честное отсутствие, а не число: inf - это не измерение, оно
        превращается в None (JSON null), а не в JS Infinity/строку 'Infinity'."""
        csv_path = tmp_path / 'data.csv'
        _write_collinear_csv(csv_path)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            skip_prior_predictive=True,
        )
        content = _body(preflight(req))
        cond = content['breakdown']['quick_proxy']['checks'].get('condition_number', {})
        assert cond.get('value') is None, (
            f'condition_number должен дойти до клиента как честное отсутствие (null), '
            f'а не как inf/строка: {cond}'
        )
        # Вердикт по этой проверке (fail) должен остаться честным несмотря на
        # то, что числовое значение спрятано - санация не должна обелять тир.
        assert content['overall_tier'] == 'insufficient'

    def test_well_conditioned_data_keeps_real_condition_number(self, tmp_path):
        """Регресс: обычные (не коллинеарные) данные по-прежнему показывают
        реальное число - санация не трогает конечные значения."""
        csv_path = tmp_path / 'data.csv'
        _write_well_conditioned_csv(csv_path)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            skip_prior_predictive=True,
        )
        content = _body(preflight(req))
        cond = content['breakdown']['quick_proxy']['checks'].get('condition_number', {})
        assert isinstance(cond.get('value'), (int, float))
        assert cond['value'] not in (None,)
