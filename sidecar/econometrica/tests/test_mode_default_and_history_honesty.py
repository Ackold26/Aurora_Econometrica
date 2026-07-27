"""Регресс-тесты на три находки координатора (2026-07-27):

1. Дефолт движка выдавал себя за явный выбор пользователя. `_validate_mode(None)`
   всегда подставлял 'bayesian' - и этот дефолт уезжал в `recommend_engine(override=...)`
   как признак явного выбора. Итог: /compute/preflight НИКОГДА не отдавал честную
   n_obs-рекомендацию, когда пользователь ничего не выбирал - override был активен
   всегда, даже на n=5 строках, где нужен строгий OLS. Плюс английский текст
   'User explicit choice' в reason, который может доехать до клиента.
2. Объяснение вердикта (`recommend['reason']`) глушилось по `banner_tone`, который
   при активном override всегда 'good' - поэтому баннер «данных недостаточно»
   уходил клиенту без единого слова объяснения ровно тогда, когда режим выбран
   явно. Нужно ветвить по честному `n_obs_tone`.
3. /compute/model_history подставлял 0 вместо отсутствующих r_squared/mape -
   несчитанная метрика неотличима от измеренного нуля. Балл MQS рядом уже был
   честным (`mqs.get('score')` без дефолта) - r_squared/mape приведены к тому же
   поведению.
"""
from __future__ import annotations

import json

import pytest

from engines.ols_modeler import recommend_engine
from server import (
    ModelHistoryRequest,
    PreflightRequest,
    _validate_mode,
    model_history,
    preflight,
)


def _body(response) -> dict:
    """JSONResponse -> dict (эндпоинты сервера возвращают starlette JSONResponse)."""
    return json.loads(response.body)


def _write_csv(path, n_obs: int) -> None:
    """Крошечный, но валидный датасет: date/kpi/2 media-канала, n_obs строк.

    tv/digital намеренно НЕ линейны друг от друга (разные модули в генераторе) -
    два линейных ряда на маленьком n почти коллинеарны после центрирования,
    condition number улетает в inf, а server.py:preflight не санирует non-finite
    перед JSONResponse (это отдельная, не наша находка) - тест ловил бы её
    вместо целевого поведения.
    """
    lines = ['date,sales,tv,digital']
    for i in range(n_obs):
        tv = 100 + (i * 37) % 90
        digital = 40 + (i * 53) % 70
        lines.append(f'2026-01-{(i % 28) + 1:02d},{1000 + i * 37},{tv},{digital}')
    path.write_text('\n'.join(lines), encoding='utf-8')


# ─── Задача 1: дефолт движка ≠ явный выбор пользователя ──────────────────────

class TestValidateModeDefaultIsolation:
    """_validate_mode: параметр default разделяет «не указано» и «дефолт для роутинга»."""

    def test_default_none_mode_resolves_to_bayesian_for_engine_routing(self):
        """/compute/train и /compute/train/start зовут БЕЗ override - им нужен
        резолвленный дефолт, иначе некуда роутить обучение. Поведение сохранено."""
        mode, err = _validate_mode(None)
        assert err is None
        assert mode == 'bayesian'

    def test_default_none_kwarg_keeps_none_as_none(self):
        """/compute/preflight зовёт c default=None: «не указано» остаётся None,
        а не подменяется дефолтом движка - иначе recommend_engine примет его за
        явный выбор пользователя."""
        mode, err = _validate_mode(None, default=None)
        assert err is None
        assert mode is None

    def test_explicit_mode_unaffected_by_default_kwarg(self):
        """Настоящий явный выбор не зависит от default - валидируется как есть."""
        mode, err = _validate_mode('ols', default=None)
        assert err is None
        assert mode == 'ols'


class TestPreflightDoesNotFakeExplicitChoiceFromDefault:
    """Сквозной сценарий через /compute/preflight: mode_override не задан."""

    def test_unspecified_mode_gets_honest_small_n_recommendation(self, tmp_path):
        """n=5 (n<20), mode_override не передан. Честная рекомендация - OLS,
        banner_tone 'bad', override НЕ активен.

        До правки (default='bayesian' в _validate_mode на месте вызова из
        preflight): mode_override резолвился в 'bayesian' ДАЖЕ когда
        пользователь ничего не выбирал, recommend_engine получал override=
        'bayesian' и врал override_active=True/banner_tone='good' на 5 строках -
        именно там, где по канону (n<20) допустим только OLS.
        """
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path, 5)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            skip_prior_predictive=True,
        )
        content = _body(preflight(req))
        assert content['status'] == 'ok'
        engine_recommend = content['breakdown']['engine_recommend']

        assert content['recommended_mode'] == 'ols', (
            f'n=5 без явного выбора должен рекомендовать OLS, а не Bayesian '
            f'(дефолт движка не должен маскироваться под выбор пользователя): '
            f'{engine_recommend}'
        )
        assert engine_recommend['banner_tone'] == 'bad'
        assert engine_recommend['override_active'] is False
        assert engine_recommend['allowed'] == ['ols']

    def test_explicit_choice_still_recognized_as_override(self, tmp_path):
        """Регресс-контроль: настоящий явный выбор пользователя по-прежнему
        доезжает до recommend_engine как override, а не теряется вместе с
        дефолтом-подстановкой."""
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path, 40)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            mode_override='ols',
            skip_prior_predictive=True,
        )
        content = _body(preflight(req))
        engine_recommend = content['breakdown']['engine_recommend']
        assert content['recommended_mode'] == 'ols'
        assert engine_recommend['override_active'] is True
        assert engine_recommend['banner_tone'] == 'good'


# ─── Задача 1b: reason override-ветки — русский текст, без англицизма ────────

class TestRecommendEngineOverrideReasonIsRussian:

    def test_no_english_leftover_in_reason(self):
        result = recommend_engine(50, override='bayesian')
        assert 'User explicit choice' not in result['reason']
        assert 'Явный выбор пользователя' in result['reason']

    def test_reason_stays_short_when_n_obs_honest_tone_is_good(self):
        """При n>=30 override не нуждается в честной приписке - и так всё хорошо."""
        result = recommend_engine(50, override='ols')
        assert result['reason'] == 'Явный выбор пользователя: OLS.'

    def test_reason_explains_small_n_even_with_override_active(self):
        """При n<20 (n_obs_tone='bad') reason обязан объяснять риск, а не только
        констатировать факт выбора - иначе задача 2 (снятие глушения) выдаёт
        клиенту бессмысленное «выбор принят» вместо объяснения вердикта."""
        result = recommend_engine(12, override='bayesian')
        assert 'Явный выбор пользователя' in result['reason']
        assert 'n=12' in result['reason']
        assert result['n_obs_tone'] == 'bad'


# ─── Задача 2: объяснение вердикта не глушится тоном override ────────────────

class TestPreflightWarningFollowsHonestTone:

    def test_explicit_override_on_small_n_still_explains_the_verdict(self, tmp_path):
        """Пользователь явно выбрал OLS на 5 строках. banner_tone от override -
        'good', но n_obs_tone честно 'bad' - объяснение обязано дойти до клиента
        через warnings.

        До правки: `if recommend['banner_tone'] != 'good'` было False (override
        всегда 'good') -> reason НЕ попадал в all_warnings, клиент получал
        вердикт «insufficient» без единого слова объяснения.
        """
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path, 5)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            mode_override='ols',
            skip_prior_predictive=True,
        )
        content = _body(preflight(req))
        engine_recommend = content['breakdown']['engine_recommend']

        assert engine_recommend['banner_tone'] == 'good'  # предпосылка бага
        assert engine_recommend['n_obs_tone'] == 'bad'  # честный тон не обелён

        assert engine_recommend['reason'] in content['warnings'], (
            f'Объяснение вердикта должно дойти до клиента, когда n_obs_tone '
            f'нечестно скрыт за override-баннером \'good\'. warnings={content["warnings"]}'
        )

    def test_natural_recommendation_reason_unaffected(self, tmp_path):
        """Регресс: без override поведение прежнее - reason при плохом тоне
        по-прежнему в warnings, при хорошем - по-прежнему отсутствует."""
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path, 5)
        req = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            skip_prior_predictive=True,
        )
        content = _body(preflight(req))
        engine_recommend = content['breakdown']['engine_recommend']
        assert engine_recommend['reason'] in content['warnings']

        csv_path2 = tmp_path / 'data2.csv'
        _write_csv(csv_path2, 40)
        req2 = PreflightRequest(
            project_dir=str(tmp_path),
            file_path=str(csv_path2),
            media_columns=['tv', 'digital'],
            kpi_column='sales',
            skip_prior_predictive=True,
        )
        content2 = _body(preflight(req2))
        engine_recommend2 = content2['breakdown']['engine_recommend']
        assert engine_recommend2['reason'] not in content2['warnings']


# ─── Задача 3: model_history - нет числа, нет подписи (r_squared/mape) ───────

def _write_history_entry(history_dir, ts: str, diagnostics: dict) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'diagnostics': diagnostics,
        'channel_params': {'tv': {}, 'digital': {}},
        'config': {'kpi_column': 'sales'},
    }
    (history_dir / f'params-{ts}.json').write_text(
        json.dumps(payload, ensure_ascii=False), encoding='utf-8',
    )


class TestModelHistoryHonestAbsence:

    def test_missing_metrics_stay_absent_not_zero(self, tmp_path):
        """Версия без посчитанных метрик (diagnostics без 'metrics' и без
        top-level r_squared/mape) - до правки получала r_squared=0/mape=0,
        неотличимо от реально измеренного нуля."""
        history_dir = tmp_path / 'models' / 'history'
        _write_history_entry(history_dir, '20260101_000000', diagnostics={
            'mqs': {'score': None, 'tier_label': ''},
        })
        content = model_history(ModelHistoryRequest(project_dir=str(tmp_path)))
        assert content['status'] == 'ok'
        v = content['versions'][0]
        assert v['r_squared'] is None, f'Несчитанный r_squared должен остаться None, получено {v["r_squared"]!r}'
        assert v['mape'] is None, f'Несчитанный mape должен остаться None, получено {v["mape"]!r}'

    def test_real_zero_metric_survives_as_zero(self, tmp_path):
        """Регресс: настоящий измеренный ноль (вырожденная модель) - валидное
        значение, не должен потеряться из-за фикса отсутствия."""
        history_dir = tmp_path / 'models' / 'history'
        _write_history_entry(history_dir, '20260102_000000', diagnostics={
            'mqs': {'score': 0, 'tier_label': 'Ненадёжное'},
            'metrics': {'r_squared': 0.0, 'mape_pct': 0.0},
        })
        content = model_history(ModelHistoryRequest(project_dir=str(tmp_path)))
        v = content['versions'][0]
        assert v['r_squared'] == 0.0
        assert v['mape'] == 0.0

    def test_legacy_top_level_fields_still_read_as_fallback(self, tmp_path):
        """Регресс: старые архивные версии без вложенного 'metrics' (поля прямо
        в diagnostics) по-прежнему читаются - fallback-цепочка сохранена."""
        history_dir = tmp_path / 'models' / 'history'
        _write_history_entry(history_dir, '20260103_000000', diagnostics={
            'mqs': {'score': 62, 'tier_label': 'Приемлемое'},
            'r_squared': 0.75,
            'mape': 12.3,
        })
        content = model_history(ModelHistoryRequest(project_dir=str(tmp_path)))
        v = content['versions'][0]
        assert v['r_squared'] == 0.75
        assert v['mape'] == 12.3

    def test_normal_computed_metrics_unaffected(self, tmp_path):
        """Регресс: обычная посчитанная версия показывает реальные числа как раньше."""
        history_dir = tmp_path / 'models' / 'history'
        _write_history_entry(history_dir, '20260104_000000', diagnostics={
            'mqs': {'score': 87, 'tier_label': 'Хорошее'},
            'metrics': {'r_squared': 0.9134, 'mape_pct': 6.7},
        })
        content = model_history(ModelHistoryRequest(project_dir=str(tmp_path)))
        v = content['versions'][0]
        assert v['r_squared'] == 0.9134
        assert v['mape'] == 6.7
