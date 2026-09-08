# -*- coding: utf-8 -*-
"""Вклад событийной колонки, названной КЛИЕНТОМ, в будущие периоды прогноза.

Дефект (2026-09-08): `_compute_scenario_holidays` сверяла имя контроля напрямую
с колонками `generate_holiday_dummies`. `control_columns` несёт сырые имена
клиента («Чёрная пятница»), дамми — канонические машинные
(`holiday_black_friday`), поэтому проверка не совпадала НИКОГДА и вклад любой
клиентски названной событийной колонки в прогнозе молча оставался нулевым.
Роль при этом распознавалась верно (`is_holiday_like_name` → True) — узнавание
работало, сопоставление данных нет.

Проверяем ровно сопоставление имён: генерация дамми, β, нормировка и решатель
не при чём и берутся как есть.
"""
import numpy as np
import pandas as pd
import pytest

from engines.scenario import _compute_scenario_holidays
from utils.holiday_calendar_ru import generate_holiday_dummies

Y_STD = 1_000_000.0
CANON_BF = 'holiday_black_friday'
CLIENT_BF = 'Чёрная пятница'
# Ноябрь-декабрь 2026: окно Чёрной пятницы (старт — последняя пятница ноября).
FUTURE_DATES = [d.strftime('%Y-%m-%d')
                for d in pd.date_range('2026-09-30', periods=6, freq='ME')]
N_PERIODS = len(FUTURE_DATES)


def _model(control_columns, betas, *, fourier=None, mode='fraction',
           mean=0.0833, std=0.2787):
    """Минимальная модель для функции: только то, что она реально читает."""
    return {
        'config': {'control_columns': list(control_columns)},
        'fourier_seasonality': {'columns': list(fourier or [])},
        'normalization': {
            'control_betas_mean': list(betas),
            'control_means': {c: mean for c in control_columns},
            'control_stds': {c: std for c in control_columns},
            'y_std': Y_STD,
            'holiday_dummies_mode': mode,
        },
    }


def _expected(dummy_col, beta, *, mode='fraction', mean=0.0833, std=0.2787):
    """Эталон вклада, посчитанный от SSOT-дамми напрямую."""
    hd = generate_holiday_dummies(pd.Series(pd.to_datetime(FUTURE_DATES)), mode=mode)
    dummy = hd[dummy_col].values.astype(float)[:N_PERIODS]
    return beta * ((dummy - mean) / std) * Y_STD


def _run(md):
    return _compute_scenario_holidays(md, md['normalization'], FUTURE_DATES, N_PERIODS)


class TestClientNamedHolidayContributes:
    """Колонка с русским клиентским названием события даёт вклад в правильные месяцы."""

    def test_client_named_column_is_not_silently_zero(self):
        md = _model([CLIENT_BF], [0.35])
        contrib = _run(md)
        assert np.any(np.abs(contrib) > 1.0), (
            'клиентски названная событийная колонка обязана давать НЕнулевой '
            f'будущий вклад, получено {contrib.tolist()}'
        )

    def test_client_named_matches_canonical_contribution(self):
        """Вклад клиентского имени совпадает с вкладом канонического — до копейки."""
        client = _run(_model([CLIENT_BF], [0.35]))
        canon = _run(_model([CANON_BF], [0.35]))
        np.testing.assert_allclose(client, canon, rtol=0, atol=1e-6)

    def test_contribution_lands_in_event_months(self):
        """Всплеск приходится на окно события, а не размазан ровно по всем месяцам."""
        contrib = _run(_model([CLIENT_BF], [0.35]))
        months = [pd.Timestamp(d).month for d in FUTURE_DATES]
        event = [i for i, m in enumerate(months) if m in (11, 12)]
        quiet = [i for i, m in enumerate(months) if m not in (11, 12)]
        assert min(contrib[i] for i in event) > max(contrib[i] for i in quiet), (
            f'месяцы окна события {[FUTURE_DATES[i] for i in event]} должны быть '
            f'выше остальных: {contrib.tolist()}'
        )

    @pytest.mark.parametrize('name', ['Чёрная пятница', 'black_friday',
                                      'promo_black_friday_2024', 'Holiday Black-Friday'])
    def test_written_variants_all_resolve(self, name):
        """Разные написания одного события ведут к одному столбцу дамми."""
        np.testing.assert_allclose(
            _run(_model([name], [0.35])),
            _expected(CANON_BF, 0.35),
            rtol=0, atol=1e-6,
        )


class TestCanonicalUnchanged:
    """Поведение колонок с каноническими именами не меняется ни на йоту."""

    def test_canonical_equals_reference_formula(self):
        contrib = _run(_model([CANON_BF], [0.35]))
        np.testing.assert_allclose(contrib, _expected(CANON_BF, 0.35), rtol=0, atol=1e-6)

    def test_canonical_binary_point_mode_preserved(self):
        """Legacy-режим бинарных дамми читается по-прежнему из normalization."""
        contrib = _run(_model([CANON_BF], [0.35], mode='binary_point'))
        np.testing.assert_allclose(
            contrib, _expected(CANON_BF, 0.35, mode='binary_point'), rtol=0, atol=1e-6)

    def test_non_holiday_controls_still_zero(self):
        """Обычные контроли не трогаем: их будущее — среднее (z=0), вклад нулевой."""
        contrib = _run(_model(['Промо-активность', 'Акции конкурентов'], [0.2, -0.1]))
        assert np.all(contrib == 0.0), contrib


class TestNoDoubleCount:
    """Одно событие входит в будущую сумму ровно один раз."""

    def test_canonical_and_client_synonym_counted_once(self):
        """Каноническая колонка — владелец события; синоним рядом пропускается."""
        both = _run(_model([CANON_BF, CLIENT_BF], [0.35, 0.20]))
        canon_only = _run(_model([CANON_BF], [0.35]))
        np.testing.assert_allclose(both, canon_only, rtol=0, atol=1e-6)
        # И это НЕ сумма двух вкладов — иначе двойной счёт.
        doubled = _expected(CANON_BF, 0.35) + _expected(CANON_BF, 0.20)
        assert not np.allclose(both, doubled, rtol=0, atol=1e-6), (
            'вклад события посчитан дважды'
        )

    def test_two_client_synonyms_without_owner_are_skipped(self):
        """Владельца нет, претендентов двое — выбор был бы догадкой, берём ноль."""
        contrib = _run(_model([CLIENT_BF, 'promo_black_friday_2024'], [0.35, 0.20]))
        assert np.all(contrib == 0.0), contrib


class TestNoGuessing:
    """Не разрешилось однозначно — прежнее поведение (ноль), а не догадка."""

    def test_ambiguous_name_covering_two_events_gives_zero(self):
        """«Новый год» покрывает и предновогодние закупки, и январские распродажи."""
        contrib = _run(_model(['Новый год'], [0.35]))
        assert np.all(contrib == 0.0), (
            f'неоднозначное имя обязано дать ноль, а не догадку: {contrib.tolist()}'
        )

    def test_unrecognized_name_gives_zero(self):
        contrib = _run(_model(['Активность дистрибьютора'], [0.35]))
        assert np.all(contrib == 0.0), contrib

    def test_client_name_shadowed_by_fourier_excluded(self):
        """A9 распространяется и на клиентские имена: задвоение с Фурье → ноль."""
        contrib = _run(_model([CLIENT_BF], [0.35], fourier=[CLIENT_BF]))
        assert np.all(contrib == 0.0), contrib


class TestResolverSSOT:
    """Разрешитель имён — тонкая проекция уже существующего дедупа, не второй справочник."""

    def test_resolver_agrees_with_dedup_used_at_training(self):
        from utils.holiday_calendar_ru import (
            resolve_holiday_column, user_covered_auto_holidays,
        )
        for name in (CLIENT_BF, CANON_BF, 'black_friday', '8 марта',
                     'Новый год', 'Промо-активность'):
            covered = user_covered_auto_holidays([name])
            resolved = resolve_holiday_column(name)
            if len(covered) == 1:
                assert resolved == next(iter(covered)), name
            else:
                assert resolved is None, (name, covered)


class TestSubstitutionRefusesForeignScale:
    """🔴 Находка внешнего аудита 08.09 (wrap-up).

    Подстановка канонической дамми под коэффициент, оценённый на КЛИЕНТСКОЙ колонке,
    законна только если клиентская колонка — признак события 0/1. Если клиент подал
    ту же «Чёрную пятницу» ДЕНЬГАМИ (бюджет промо в рублях), нормировка применит его
    среднее и разброс к дамми 0/1: во всех будущих периодах, включая непраздничные,
    получится постоянный сдвиг. Прежде вклад был тождественно нулевым — то есть
    правка превратила бы молчаливый ноль в уверенно неверное число.

    Проверка обязана краснеть: сними условие масштаба в `scenario.py` — первый тест
    здесь покажет ненулевой вклад в спокойных месяцах.
    """

    def test_money_scale_client_column_gives_zero(self):
        """Колонка события в рублях: подстановки нет, вклад ноль во ВСЕХ периодах."""
        md = _model(['Чёрная пятница'], [0.35], mean=5_000_000.0, std=12_000_000.0)
        out = _run(md)
        assert np.allclose(out, 0.0), (
            'колонка события со шкалой рублей не должна получать календарную дамми: '
            f'вклад {out}')

    def test_binary_client_column_still_contributes(self):
        """Признак 0/1 (доля событийных периодов 1/12) по-прежнему работает."""
        md = _model(['Чёрная пятница'], [0.35], mean=0.0833, std=0.2767)
        out = _run(md)
        assert not np.allclose(out, 0.0), 'признак 0/1 обязан давать вклад'

    def test_canonical_column_not_affected_by_scale_check(self):
        """Авто-инжектированный столбец с каноническим именем проверке не подлежит.

        У него своя шкала (доля дней окна), и требование двоичности сломало бы
        рабочий путь. Имя совпадает с каноническим → подстановки нет.
        """
        md = _model(['holiday_black_friday'], [0.35], mean=0.0400, std=0.1100)
        out = _run(md)
        assert not np.allclose(out, 0.0), (
            'канонический столбец обязан считаться независимо от вида его статистик')

    def test_degenerate_stats_give_zero(self):
        """Среднее вне (0;1) или нулевой разброс — отказ, а не догадка."""
        for mean, std in ((0.0, 0.0), (1.0, 0.0), (0.5, 0.0), (-3.0, 2.0)):
            md = _model(['Чёрная пятница'], [0.35], mean=mean, std=std)
            assert np.allclose(_run(md), 0.0), (
                f'вырожденные статистики (среднее {mean}, разброс {std}) '
                'не должны давать подстановку')
