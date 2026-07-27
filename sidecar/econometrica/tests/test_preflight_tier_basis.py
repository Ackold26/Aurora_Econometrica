"""Разметка источника в предварительной проверке (задача 2026-07-26).

Баннер предварительной проверки говорит клиенту, надёжна ли модель на его
данных, и на этом основании клиент решает, запускать ли расчёт. До этой
правки баннер не сообщал, ЧЕМ уровень получен: быстрая оценка данных и
полная проверка предположений модели давали одинаковую формулировку, а
пропущенная (или упавшая) проверка не отличалась от пройденной — то есть
ОТСУТСТВИЕ проверки читалось как её успешный результат.

Тот же класс дефекта, что несчитанная метрика качества, показанная нулём:
результат без основания выглядит как измерение. Здесь фиксируется, что
основание доезжает до ответа и что пропуск назван явно и своей причиной.
"""
import pytest

from server import aggregate_preflight_tier
from engines.ols_modeler import recommend_engine


def _call(**kw):
    base = dict(
        recommend={'banner_tone': 'good', 'n_obs_tone': 'good'},
        quick_proxy={'tier': 'reliable'},
        prior_predictive=None,
        # Регресс-находка 2026-07-27: параметр переименован из recommended_mode
        # в actual_mode - потребитель здесь спрашивает «чем реально пойдёт
        # обучение», а не «что советует recommend_engine» (см. server.py::
        # aggregate_preflight_tier docstring).
        actual_mode='bayesian',
        skip_prior_predictive=False,
    )
    base.update(kw)
    return aggregate_preflight_tier(**base)


def test_tier_is_worst_of_sources():
    """Консервативная агрегация сохранена: уровень — худшее из оснований."""
    tier, _ = _call(
        recommend={'banner_tone': 'warn'},
        quick_proxy={'tier': 'insufficient'},
        prior_predictive={'status': 'pass'},
    )
    assert tier == 'insufficient'


def test_decided_by_names_the_source_of_the_verdict():
    """Клиент видит, КАКОЕ основание дало итоговый уровень, а не только уровень."""
    tier, basis = _call(
        recommend={'banner_tone': 'good'},
        quick_proxy={'tier': 'reliable'},
        prior_predictive={'status': 'fail'},
    )
    assert tier == 'insufficient'
    assert basis['decided_by'] == ['prior_predictive']
    assert basis['by_source'] == {
        'n_obs': 'reliable', 'quick_proxy': 'reliable',
        'prior_predictive': 'insufficient',
    }
    assert basis['skipped'] == {}


def test_several_sources_may_share_the_verdict():
    _, basis = _call(
        recommend={'banner_tone': 'warn', 'n_obs_tone': 'warn'},
        quick_proxy={'tier': 'directional'},
        prior_predictive={'status': 'pass'},
    )
    assert basis['decided_by'] == ['n_obs', 'quick_proxy']


@pytest.mark.parametrize("kwargs,reason", [
    ({'actual_mode': 'ols'}, 'engine_not_bayesian'),
    ({'skip_prior_predictive': True}, 'disabled_by_user'),
    ({}, 'failed'),
])
def test_skipped_source_is_named_with_its_own_reason(kwargs, reason):
    """Пропуск печатается явно и различает причины.

    Три причины дают разный клиентский смысл: неприменимо к способу расчёта /
    отключено пользователем / не удалось на этих данных. Слитые в одну
    формулировку, они бы скрыли отказ проверки за видом настройки.
    """
    _, basis = _call(**kwargs)
    assert basis['skipped'] == {'prior_predictive': reason}
    assert 'prior_predictive' not in basis['by_source']


def test_absent_check_never_improves_the_verdict():
    """Пропущенная проверка не добавляет уровню надёжности.

    Гарантия против обратного прочтения «не проверяли, значит хорошо»:
    уровень при пропуске равен худшему из ОСТАВШИХСЯ оснований, и то, что
    проверки не было, видно в ответе.
    """
    tier_skipped, basis = _call(
        quick_proxy={'tier': 'directional'}, skip_prior_predictive=True,
    )
    tier_passed, _ = _call(
        quick_proxy={'tier': 'directional'}, prior_predictive={'status': 'pass'},
    )
    assert tier_skipped == tier_passed == 'directional'
    assert basis['skipped'] == {'prior_predictive': 'disabled_by_user'}


def test_unknown_source_values_do_not_silently_pass_as_reliable_verdict():
    """Неизвестный код источника не должен ухудшать/улучшать вывод молча.

    Значение по умолчанию — 'reliable' (сохранено из прежней реализации),
    поэтому важно, что оно ЗАПИСАНО в by_source: клиент и разработчик видят,
    что источник дал неразобранный ответ, а не что он подтвердил надёжность.
    """
    _, basis = _call(recommend={'n_obs_tone': 'какой-то новый тон'})
    assert basis['by_source']['n_obs'] == 'reliable'
    assert 'n_obs' in basis['decided_by']


# ─── Находка 6 (2026-07-26): override не должен обелять малый n ────────────
#
# recommend_engine при активном override (явный выбор движка ИЛИ
# _validate_mode's None→'bayesian' default) коротко замыкается и раньше
# отдавал banner_tone='good' независимо от n — по этому полю
# aggregate_preflight_tier решал 'n_obs' источник. На n=12 (n<20, порог
# «данных недостаточно») это превращало insufficient-вердикт в directional/
# reliable, и в skipped пропуск проверки не отмечался — то есть отсутствие
# проверки читалось как её успешный результат. Объём наблюдений — свойство
# ДАННЫХ, не движка: явный выбор не делает 12 строк достаточными.


class TestHonestNObsToneIgnoresOverride:
    """recommend_engine: n_obs_tone — только от n, независимо от override."""

    @pytest.mark.parametrize("n_obs,expected_tone", [
        (5, 'bad'), (12, 'bad'), (19, 'bad'),
        (20, 'warn'), (25, 'warn'), (29, 'warn'),
        (30, 'good'), (100, 'good'),
    ])
    def test_n_obs_tone_follows_thresholds_without_override(self, n_obs, expected_tone):
        assert recommend_engine(n_obs)['n_obs_tone'] == expected_tone

    @pytest.mark.parametrize("n_obs,expected_tone", [
        (5, 'bad'), (12, 'bad'), (19, 'bad'),
        (20, 'warn'), (29, 'warn'),
        (30, 'good'), (100, 'good'),
    ])
    @pytest.mark.parametrize("override", ['ols', 'bayesian'])
    def test_n_obs_tone_unaffected_by_override(self, n_obs, expected_tone, override):
        """Ключевой кейс находки 6: override не меняет честный тон по n."""
        result = recommend_engine(n_obs, override=override)
        assert result['n_obs_tone'] == expected_tone
        # banner_tone (UI-подсказка "ваш выбор принят") остаётся 'good' —
        # это НЕ трогаем, это отдельный канал сообщения.
        assert result['banner_tone'] == 'good'
        assert result['override_active'] is True


def test_n_obs_source_reflects_honest_tone_even_with_explicit_ols_override():
    """Сквозной сценарий находки 6 через aggregate_preflight_tier.

    Пользователь явно выбрал OLS на 12 строках (n<20). banner_tone от
    override — 'good', но n_obs_tone честно 'bad' → источник 'n_obs' должен
    дать 'insufficient', а не 'reliable'.
    """
    recommend = recommend_engine(12, override='ols')
    assert recommend['banner_tone'] == 'good'  # предпосылка бага, если бы её читали
    tier, basis = _call(recommend=recommend)
    assert basis['by_source']['n_obs'] == 'insufficient'
    assert tier == 'insufficient'
    assert 'n_obs' in basis['decided_by']
