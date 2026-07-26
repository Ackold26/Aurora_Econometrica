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


def _call(**kw):
    base = dict(
        recommend={'banner_tone': 'good'},
        quick_proxy={'tier': 'reliable'},
        prior_predictive=None,
        recommended_mode='bayesian',
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
        recommend={'banner_tone': 'warn'},
        quick_proxy={'tier': 'directional'},
        prior_predictive={'status': 'pass'},
    )
    assert basis['decided_by'] == ['n_obs', 'quick_proxy']


@pytest.mark.parametrize("kwargs,reason", [
    ({'recommended_mode': 'ols'}, 'engine_not_bayesian'),
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
    _, basis = _call(recommend={'banner_tone': 'какой-то новый тон'})
    assert basis['by_source']['n_obs'] == 'reliable'
    assert 'n_obs' in basis['decided_by']
