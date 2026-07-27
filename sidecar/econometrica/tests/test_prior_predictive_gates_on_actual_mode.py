"""Регресс-находка внешнего аудита (2026-07-27): проверка приоров молчала
там, где данных мало и обучение всё равно пойдёт Bayesian.

Наша же правка находки 6 (`server.py::_validate_mode(default=None)`, коммит
158adb2) честно развела «режим не задан» и «явный выбор пользователя» для
`recommend_engine`. Но потребитель prior_predictive-гейта (`preflight()`,
`server.py:1079` было `if recommended_mode == 'bayesian' ...`) спрашивал не
«чем реально пойдёт обучение», а «что советует recommend_engine» - до находки
6 оба вопроса случайно совпадали (дефолт движка 'bayesian' == честная
рекомендация при n<30 была недостижима). После находки 6 при n<30
recommend_engine честно рекомендует 'ols', а интерфейс (ConfigPanel.svelte)
шлёт modeOverride=null для инженерного дефолта Bayesian, но реально обучает
Bayesian (train-config.js передаёт mode=engine буквально) - проверка приоров
пропадала («не выполнялась: неприменима к выбранному способу расчёта», хотя
способ как раз применим) ровно там, где мало данных и она нужнее всего.

Фикс: третий факт actual_mode = mode_override или 'bayesian' (тот же дефолт,
что резолвит _validate_mode в /compute/train на том же сыром входе) - гейт
проверки приоров и skip-причина в aggregate_preflight_tier переведены на
него, recommend_engine's честная рекомендация (recommended_mode) остаётся
отдельно для отображения клиенту.
"""
from __future__ import annotations

import json

import pytest

from server import PreflightRequest, preflight


def _body(response) -> dict:
    return json.loads(response.body)


def _write_small_n_csv(path, n_obs: int = 20) -> None:
    """n<30 (порог recommend_engine), tv/digital НЕ коллинеарны (не линейны
    друг от друга - иначе quick_proxy сам пометит insufficient по другой
    причине и тест перестанет быть чистой проверкой ИМЕННО prior_predictive
    гейта)."""
    lines = ['date,sales,tv,digital']
    for i in range(n_obs):
        tv = 100 + (i * 37) % 90
        digital = 40 + (i * 53) % 70
        sales = 1000 + i * 23 + (tv % 17) * 3
        lines.append(f'2026-01-{(i % 28) + 1:02d},{sales},{tv},{digital}')
    path.write_text('\n'.join(lines), encoding='utf-8')


class TestPriorPredictiveFollowsActualTrainingMode:

    def test_runs_when_mode_unspecified_and_n_below_30(self, tmp_path):
        """Сценарий координатора дословно: n<30, mode_override НЕ передан
        (инженерный дефолт интерфейса - Bayesian), skip_prior_predictive НЕ
        передан (дефолт False). Проверка приоров ОБЯЗАНА выполниться - именно
        этим движком реально пойдёт обучение, что бы ни советовал
        recommend_engine по объёму наблюдений."""
        csv_path = tmp_path / 'data.csv'
        _write_small_n_csv(csv_path, n_obs=20)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            # mode_override не передан -> None (движок обучит Bayesian по
            # умолчанию - ConfigPanel.svelte шлёт именно так для 'bayesian').
            # skip_prior_predictive не передан -> False (дефолт).
        )
        content = _body(preflight(req))
        assert content['status'] == 'ok'

        # Честная рекомендация по n_obs (n=20 < 30) по-прежнему 'ols' -
        # находка 6 не откатывается этим фиксом.
        assert content['recommended_mode'] == 'ols'

        # Но проверка приоров ОБЯЗАНА была выполниться - реально обучаем Bayesian.
        prior_predictive = content['breakdown']['prior_predictive']
        assert prior_predictive is not None, (
            'prior_predictive не выполнилась, хотя обучение реально пойдёт '
            'Bayesian (mode_override не передан = инженерный дефолт интерфейса)'
        )
        assert 'prior_predictive' not in content['tier_basis']['skipped'], (
            f'prior_predictive ошибочно помечена пропущенной: {content["tier_basis"]["skipped"]}'
        )

    def test_skip_flag_still_wins_when_actual_mode_is_bayesian(self, tmp_path):
        """Регресс-контроль: skip_prior_predictive=True по-прежнему пропускает
        проверку (причина - настройка пользователя, а не 'engine_not_bayesian')."""
        csv_path = tmp_path / 'data.csv'
        _write_small_n_csv(csv_path, n_obs=20)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            skip_prior_predictive=True,
        )
        content = _body(preflight(req))
        assert content['breakdown']['prior_predictive'] is None
        assert content['tier_basis']['skipped'].get('prior_predictive') == 'disabled_by_user'

    def test_skipped_as_engine_not_bayesian_only_when_actually_ols(self, tmp_path):
        """Регресс-контроль: причина 'engine_not_bayesian' в skipped теперь
        честна - появляется РОВНО когда реально обучаем OLS (явный выбор), а
        не когда просто n<30 при инженерном дефолте Bayesian."""
        csv_path = tmp_path / 'data.csv'
        _write_small_n_csv(csv_path, n_obs=20)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            mode_override='ols',  # пользователь явно выбрал OLS
        )
        content = _body(preflight(req))
        assert content['breakdown']['prior_predictive'] is None
        assert content['tier_basis']['skipped'].get('prior_predictive') == 'engine_not_bayesian'
