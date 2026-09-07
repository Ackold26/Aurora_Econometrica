"""Сторож (2026-09-07): предполётная проверка обязана передавать даты в
`prior_predictive_check`, и даты обязаны описывать РОВНО те строки, что попали
в `y_observed`.

Дефект, который сторож закрывает
--------------------------------
`utils/reliability_a4.prior_predictive_check` умеет строить симуляцию с теми же
контрольными регрессорами, что обучение инжектирует автоматически (праздники РФ
`modeler.py:486`, Фурье-сезонность `modeler.py:568`) — но только если ей передать
даты. Оба вызова в продукте дат не передавали, поэтому симуляция сравнивала
данные с заведомо НЕПОЛНОЙ моделью и вердикт систематически занижался:
демо-проект продукта (104 недели) давал покрытие 0,548 «warn» → вердикт
`directional` («модель будет ориентировочной») вместо 0,827 «pass» → `reliable`.
Это вердикт, который видит клиент, — то есть продукт наговаривал на себя.

Почему второе утверждение (совпадение длин) не менее важно первого
-----------------------------------------------------------------
Строки медиаплана вперёд (KPI пуст, инвестиции заполнены) не являются
наблюдениями и обрезаются до расчёта (L-08, `server.py` preflight;
`modeler.py:365`). Если даты обрезаны НЕ синхронно с `y_observed`,
Фурье-компоненты и праздники встанут не на свои наблюдения — покрытие получится
тихо неверным, а не заметно сломанным. Такой дефект хуже исходного, поэтому
сверка длин вынесена в отдельное утверждение и продублирована громким отказом
в самой функции.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import utils.reliability_a4 as a4
from server import PreflightRequest, preflight

N_HISTORY = 60   # недель факта
N_PLAN = 14      # недель медиаплана вперёд (KPI пуст)
FIRST_DATE = '2024-01-01'


def _body(response) -> dict:
    return json.loads(response.body)


def _write_csv_with_plan_tail(path: Path) -> pd.DataFrame:
    """Файл «как у клиента»: факт + хвост медиаплана с пустым KPI.

    tv/digital не коллинеарны (иначе quick_proxy пометит набор по своей
    причине и сторож перестанет проверять именно передачу дат).
    """
    n = N_HISTORY + N_PLAN
    dates = pd.date_range(FIRST_DATE, periods=n, freq='W-MON')
    tv = [100 + (i * 37) % 90 for i in range(n)]
    digital = [40 + (i * 53) % 70 for i in range(n)]
    sales = [1000 + i * 23 + (tv[i] % 17) * 3 for i in range(N_HISTORY)] + [None] * N_PLAN
    df = pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'sales': sales,
        'tv': tv,
        'digital': digital,
    })
    df.to_csv(path, index=False, encoding='utf-8')
    return df


def _request(tmp_path: Path, csv_path: Path) -> PreflightRequest:
    """Ровно те поля, что шлёт интерфейс (ConfigPanel.svelte:474-483):
    mode_override=None (инженерный дефолт Bayesian), skip_prior_predictive=False."""
    return PreflightRequest(
        project_dir=str(tmp_path),
        file_path=str(csv_path),
        media_columns=['tv', 'digital'],
        kpi_column='sales',
        date_column='date',
        mode_override=None,
        skip_prior_predictive=False,
    )


class TestPreflightPassesDatesToPriorPredictive:

    def test_preflight_passes_dates_aligned_with_y_observed(self, tmp_path, monkeypatch):
        """Главное утверждение сторожа: даты переданы И совпадают с y_observed
        по длине и по содержимому (обрезаны синхронно с хвостом медиаплана)."""
        csv_path = tmp_path / 'data.csv'
        _write_csv_with_plan_tail(csv_path)

        captured: dict = {}
        real = a4.prior_predictive_check

        def spy(y_observed, media_matrix, *args, **kwargs):
            captured['y'] = np.asarray(y_observed)
            captured['dates'] = kwargs.get('dates')
            return real(y_observed, media_matrix, *args, **kwargs)

        # server.py импортирует функцию внутри тела эндпоинта, поэтому подмена
        # атрибута модуля перехватывает вызов боевого пути.
        monkeypatch.setattr(a4, 'prior_predictive_check', spy)

        content = _body(preflight(_request(tmp_path, csv_path)))
        assert content['status'] == 'ok'
        assert captured, 'prior_predictive_check вообще не вызвана — сторож не проверил путь'

        dates = captured['dates']
        assert dates is not None, (
            'Предполётная проверка не передала даты в prior_predictive_check: '
            'симуляция пойдёт БЕЗ праздников РФ и Фурье-сезонности, которые '
            'обучение инжектирует всегда, и вердикт надёжности у клиента будет '
            'систематически занижен (демо-проект: 0,548 warn вместо 0,827 pass)'
        )

        y = captured['y']
        assert len(dates) == len(y), (
            f'Длина dates ({len(dates)}) не совпадает с y_observed ({len(y)}): '
            'сезонность и праздники встанут не на свои наблюдения, покрытие '
            'будет тихо неверным'
        )
        assert len(y) == N_HISTORY, (
            f'y_observed содержит {len(y)} строк вместо {N_HISTORY}: хвост '
            'медиаплана не обрезан (L-08)'
        )

        # Даты — именно история, а не «первые N строк файла целиком».
        expected = pd.date_range(FIRST_DATE, periods=N_HISTORY, freq='W-MON')
        assert pd.Timestamp(dates[0]) == expected[0]
        assert pd.Timestamp(dates[-1]) == expected[-1], (
            'Последняя дата не совпадает с последним наблюдением истории — '
            'обрезка дат рассинхронизирована с обрезкой y_observed'
        )

    def test_dates_actually_reach_the_simulation(self, tmp_path):
        """Сквозная проверка: даты не просто переданы, а реально дали контрольные
        регрессоры в симуляции (иначе передача была бы формальной)."""
        csv_path = tmp_path / 'data.csv'
        _write_csv_with_plan_tail(csv_path)

        content = _body(preflight(_request(tmp_path, csv_path)))
        pp = content['breakdown']['prior_predictive']
        assert pp is not None, 'проверка приоров не выполнилась'
        assert pp.get('control_components'), (
            'В результате нет control_components: симуляция построена без '
            'контрольных регрессоров, хотя даты переданы'
        )

    def test_missing_date_column_degrades_to_old_behaviour(self, tmp_path, monkeypatch):
        """Нет колонки дат — откат к прежнему поведению (dates=None), а не отказ:
        предполётная проверка не имеет права ронять контур."""
        csv_path = tmp_path / 'data.csv'
        df = _write_csv_with_plan_tail(csv_path)
        df.drop(columns=['date']).to_csv(csv_path, index=False, encoding='utf-8')

        captured: dict = {}
        real = a4.prior_predictive_check

        def spy(y_observed, media_matrix, *args, **kwargs):
            captured['dates'] = kwargs.get('dates')
            return real(y_observed, media_matrix, *args, **kwargs)

        monkeypatch.setattr(a4, 'prior_predictive_check', spy)
        content = _body(preflight(_request(tmp_path, csv_path)))

        assert content['status'] == 'ok'
        assert captured.get('dates') is None
        assert content['breakdown']['prior_predictive'] is not None, (
            'проверка приоров упала без колонки дат — деградация обязана быть мягкой'
        )

    def test_unparseable_dates_degrade_to_old_behaviour(self, tmp_path, monkeypatch):
        """Колонка дат есть, но не разбирается — тот же мягкий откат."""
        csv_path = tmp_path / 'data.csv'
        df = _write_csv_with_plan_tail(csv_path)
        df['date'] = ['не дата'] * len(df)
        df.to_csv(csv_path, index=False, encoding='utf-8')

        captured: dict = {}
        real = a4.prior_predictive_check

        def spy(y_observed, media_matrix, *args, **kwargs):
            captured['dates'] = kwargs.get('dates')
            return real(y_observed, media_matrix, *args, **kwargs)

        monkeypatch.setattr(a4, 'prior_predictive_check', spy)
        content = _body(preflight(_request(tmp_path, csv_path)))

        assert content['status'] == 'ok'
        assert captured.get('dates') is None
        assert content['breakdown']['prior_predictive'] is not None


class TestPriorPredictiveRejectsMisalignedDates:

    def test_length_mismatch_raises_not_silently_truncates(self):
        """Второй рубеж внутри самой функции: рассогласование длин — громкий
        отказ. Молчаливое выравнивание дало бы правдоподобное, но неверное
        покрытие — дефект хуже исходного."""
        rng = np.random.default_rng(0)
        n = 30
        y = 1000 + rng.normal(0, 50, n)
        X = np.abs(rng.normal(500, 100, size=(n, 2)))
        short_dates = pd.date_range('2024-01-01', periods=n - 1, freq='W-MON').values

        with pytest.raises(ValueError, match='dates'):
            a4.prior_predictive_check(y, X, n_samples=20, dates=short_dates)

    def test_matching_length_is_accepted(self):
        rng = np.random.default_rng(0)
        n = 30
        y = 1000 + rng.normal(0, 50, n)
        X = np.abs(rng.normal(500, 100, size=(n, 2)))
        dates = pd.date_range('2024-01-01', periods=n, freq='W-MON').values

        out = a4.prior_predictive_check(y, X, n_samples=20, dates=dates)
        assert out['status'] in ('pass', 'warn', 'fail')


class TestInTrainPreflightPassesDates:
    """Второй вызов в продукте — проверка внутри обучения (`modeler.py`).
    Прогонять обучение ради этого дорого, поэтому сторож читает исходник:
    вызов обязан передавать `dates`. Снятие аргумента красит тест."""

    def test_modeler_call_has_dates_keyword(self):
        src_path = Path(__file__).resolve().parents[1] / 'engines' / 'modeler.py'
        tree = ast.parse(src_path.read_text(encoding='utf-8'))

        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'prior_predictive_check'
        ]
        assert calls, 'вызов prior_predictive_check в modeler.py не найден'
        for call in calls:
            kwargs = {kw.arg for kw in call.keywords}
            assert 'dates' in kwargs, (
                f'modeler.py:{call.lineno}: prior_predictive_check вызвана без dates — '
                'проверка внутри обучения снова сравнивает данные с неполной моделью'
            )
