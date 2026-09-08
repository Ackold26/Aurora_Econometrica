# -*- coding: utf-8 -*-
"""Вклад событийной колонки, названной КЛИЕНТОМ, в будущие периоды прогноза.

История вопроса (две итерации одного дня, 2026-09-08):

1. Утром: `_compute_scenario_holidays` сверяла имя контроля напрямую с колонками
   `generate_holiday_dummies`. `control_columns` несёт сырые имена клиента
   («Чёрная пятница»), дамми — канонические машинные (`holiday_black_friday`),
   поэтому проверка не совпадала никогда и вклад клиентски названной событийной
   колонки в прогнозе молча оставался нулевым. Правка научила движок разрешать имя
   и ПОДСТАВЛЯТЬ каноническую дамми под коэффициент клиентской колонки.

2. Вечером, внешний аудит: подстановка некорректна в принципе, и никакая проверка
   свойств клиентской колонки этого не чинит.
     • Шкала. В режиме `fraction` каноническая дамми — ДОЛЯ дней события в периоде
       (0,133 в ноябре, 0,323 в декабре на месячной сетке), а β оценивалась на
       клиентской колонке 0/1. Замер на боевом наборе `synth_retail_ecom.xlsx`
       (β=0,30, y_std=1 000 000 ₽): ноябрь получал 53 782 ₽ вместо следующих из
       истории 986 661 ₽, а масса события уезжала в декабрь (+257 536 ₽).
     • Сроки. Каноническое окно события не обязано совпадать с тем, что клиент
       разметил единицами у себя.
     • Режим `binary_point` (умолчание для старых pickle без ключа) на месячной
       сетке даёт каноническую дамми тождественно нулевой — событие исчезало
       целиком, расхождение −1 076 357 ₽ за 18 периодов.

   Поэтому подстановка отменена: колонка, чьё имя НЕ совпадает с каноническим,
   вклада в будущие периоды не даёт вовсе — как и до утренней правки, но теперь
   причина пишется в журнал, а не молчит.

Договор, который проверяет этот набор:
  • имя колонки == каноническому (авто-инжект modeler'а) → вклад считается как
    считался, ни на йоту иначе;
  • имя клиентское, событие узнано → тождественный ноль во ВСЕХ будущих периодах
    (именно ноль, а не постоянный сдвиг — сдвиг был бы уверенно неверным числом);
  • имя не разрешилось однозначно или не событийное → ноль, как и раньше.

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
# «Holiday Black-Friday» — НЕ клиентское имя: `normalize_holiday_name` сводит его
# к той же форме, что и канон (lower + без разделителей), подстановки тут нет.
CANON_BF_WRITTEN = 'Holiday Black-Friday'
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


class TestClientNamedHolidayHasNoFutureContribution:
    """Колонка с клиентским названием события в будущее не проецируется.

    Ровно перевёрнутые утверждения прежнего класса
    `TestClientNamedHolidayContributes`: тот проверял, что подстановка состоялась,
    этот — что её нет. Прежние проверки не удалены ради зелени, они утверждали
    отменённый договор и заменены проверками нового.
    """

    def test_client_named_column_is_identically_zero(self):
        """Замена `test_client_named_column_is_not_silently_zero`.

        Ноль здесь не «молчаливый», а осознанный: значений будущих периодов для
        клиентской колонки нет, а календарная дамми ей не подходит ни шкалой,
        ни окном.
        """
        contrib = _run(_model([CLIENT_BF], [0.35]))
        assert np.all(contrib == 0.0), (
            'клиентски названная событийная колонка не должна получать вклад '
            f'подстановкой календарной дамми, получено {contrib.tolist()}'
        )

    def test_client_named_does_not_borrow_canonical_contribution(self):
        """Замена `test_client_named_matches_canonical_contribution`.

        Вклад клиентского имени НЕ равен вкладу канонического: канон считается,
        клиентское имя — нет.
        """
        client = _run(_model([CLIENT_BF], [0.35]))
        canon = _run(_model([CANON_BF], [0.35]))
        assert np.any(np.abs(canon) > 1.0), 'канонический путь обязан считаться'
        assert not np.allclose(client, canon, rtol=0, atol=1e-6), (
            'клиентское имя не должно наследовать вклад канонического столбца'
        )
        assert np.all(client == 0.0), client.tolist()

    def test_no_constant_shift_in_quiet_months(self):
        """Замена `test_contribution_lands_in_event_months`.

        Всплеска в окне события больше нет — проверять его распределение нечего.
        Взамен сторожим то, что важнее: отсутствие ПОСТОЯННОГО сдвига. Нормировка
        (0 − mean)/std даёт ненулевую константу во всех периодах, если колонка
        всё-таки попадёт в сумму, — это и было бы уверенно неверным числом.
        """
        contrib = _run(_model([CLIENT_BF], [0.35]))
        months = [pd.Timestamp(d).month for d in FUTURE_DATES]
        quiet = [i for i, m in enumerate(months) if m not in (11, 12)]
        assert quiet, 'в выборке дат должны быть месяцы вне окна события'
        assert all(contrib[i] == 0.0 for i in quiet), (
            f'спокойные месяцы обязаны быть ровно нулём, получено {contrib.tolist()}'
        )

    @pytest.mark.parametrize('name', ['Чёрная пятница', 'black_friday',
                                      'promo_black_friday_2024'])
    def test_written_variants_all_give_zero(self, name):
        """Замена `test_written_variants_all_resolve`.

        Разные написания клиента по-прежнему разрешаются в одно событие
        (`TestResolverSSOT` это стережёт), но разрешение теперь нужно только для
        журнальной записи — в расчёт будущего ни одно из них не идёт.
        """
        contrib = _run(_model([name], [0.35]))
        assert np.all(contrib == 0.0), (name, contrib.tolist())

    def test_canonically_written_name_is_not_a_substitution(self):
        """Имя, совпадающее с каноном по норм-форме, — не подстановка.

        `normalize_holiday_name` сводит 'Holiday Black-Friday' и
        'holiday_black_friday' к одной форме, значит это тот же авто-инжектированный
        столбец, записанный иначе, и его шкала с обучением согласована.
        """
        np.testing.assert_allclose(
            _run(_model([CANON_BF_WRITTEN], [0.35])),
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
    """Одно событие входит в будущую сумму ровно один раз.

    После отмены подстановки клиентский синоним отсеивается раньше — на самой
    проверке имени, а не защитой от двойного счёта. Проверки оставлены: договор
    «событие не считается дважды» тот же, а защита по-прежнему нужна для пары
    написаний, которые обе сводятся к канону (см. `TestCanonicalUnchanged`).
    """

    def test_canonical_and_client_synonym_counted_once(self):
        """Каноническая колонка считается, клиентский синоним рядом — нет."""
        both = _run(_model([CANON_BF, CLIENT_BF], [0.35, 0.20]))
        canon_only = _run(_model([CANON_BF], [0.35]))
        np.testing.assert_allclose(both, canon_only, rtol=0, atol=1e-6)
        # И это НЕ сумма двух вкладов — иначе двойной счёт.
        doubled = _expected(CANON_BF, 0.35) + _expected(CANON_BF, 0.20)
        assert not np.allclose(both, doubled, rtol=0, atol=1e-6), (
            'вклад события посчитан дважды'
        )

    def test_two_client_synonyms_without_owner_are_skipped(self):
        """Владельца нет, оба имени клиентские — вклад нулевой."""
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
    """Разрешитель имён — тонкая проекция уже существующего дедупа, не второй справочник.

    Он остался в работе и после отмены подстановки: по нему пишется журнальная
    запись «колонка распознана как событие X, но её вклад в прогноз не включён».
    """

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


class TestNoSubstitutionAtAll:
    """🔴 Вторая итерация аудита 08.09: подстановки нет ни при каких свойствах колонки.

    Прежний класс `TestSubstitutionRefusesForeignScale` допускал подстановку для
    колонки со статистиками признака 0/1 (`_looks_like_binary_flag`). Проверка
    смотрела не на ту сторону равенства: двоичность КЛИЕНТСКОЙ колонки ничего не
    говорит о шкале и окне ПОДСТАВЛЯЕМОЙ канонической дамми. Первый тест здесь —
    ровно перевёрнутый `test_binary_client_column_still_contributes`.
    """

    def test_binary_client_column_also_gives_zero(self):
        """Признак 0/1 — тот самый случай, ради которого подстановку и вводили."""
        md = _model([CLIENT_BF], [0.35], mean=0.0833, std=0.2767)
        out = _run(md)
        assert np.all(out == 0.0), (
            'даже строго двоичная клиентская колонка не получает календарную дамми: '
            f'вклад {out.tolist()}')

    def test_money_scale_client_column_gives_zero(self):
        """Колонка события в рублях: вклад ноль во ВСЕХ периодах."""
        md = _model([CLIENT_BF], [0.35], mean=5_000_000.0, std=12_000_000.0)
        out = _run(md)
        assert np.all(out == 0.0), (
            'колонка события со шкалой рублей не должна получать календарную дамми: '
            f'вклад {out.tolist()}')

    def test_canonical_column_not_affected(self):
        """Авто-инжектированный столбец с каноническим именем считается всегда.

        У него своя шкала (доля дней окна), согласованная с обучением, и вид его
        статистик к делу не относится — это рабочий путь.
        """
        md = _model([CANON_BF], [0.35], mean=0.0400, std=0.1100)
        out = _run(md)
        assert not np.allclose(out, 0.0), (
            'канонический столбец обязан считаться независимо от вида его статистик')

    def test_degenerate_stats_give_zero(self):
        """Вырожденные статистики клиентской колонки — тот же ноль, что и любые."""
        for mean, std in ((0.0, 0.0), (1.0, 0.0), (0.5, 0.0), (-3.0, 2.0)):
            md = _model([CLIENT_BF], [0.35], mean=mean, std=std)
            assert np.all(_run(md) == 0.0), (
                f'вырожденные статистики (среднее {mean}, разброс {std}) '
                'не должны давать подстановку')


class TestMonthlyGridRegressionGuard:
    """🔴 Сторож дефекта, снятого 08.09 на боевом наборе synth_retail_ecom.xlsx.

    Воспроизводит его условия: месячная сетка, клиентская колонка строго 0/1
    (событие в одном месяце из двенадцати → mean=1/12, std=sqrt(p·(1−p))), оба
    режима генерации дамми. Прежнее поведение в этих условиях:
      • `fraction` — вклад ноября 5,5 % от следующего из истории, масса события
        в декабре, за 18 периодов сдвиг вниз на 585 646 ₽;
      • `binary_point` — каноническая месячная дамми тождественно нулевая,
        событие исчезает, а во всех периодах остаётся постоянный сдвиг.
    Обе картины ловятся требованием тождественного нуля.

    Мутация (проверена 08.09): если вернуть подстановку в `_compute_scenario_holidays`,
    оба режима краснеют — `fraction` ненулевыми значениями в окне события,
    `binary_point` постоянным сдвигом −(β·mean/std·y_std) во всех периодах.
    """

    # Месячная сетка на 18 периодов — как хвост плана в боевом наборе.
    MONTHLY = [d.strftime('%Y-%m-%d')
               for d in pd.date_range('2026-01-31', periods=18, freq='ME')]
    P = 1.0 / 12.0
    SD = float(np.sqrt(P * (1.0 - P)))

    @pytest.mark.parametrize('mode', ['fraction', 'binary_point'])
    def test_binary_client_column_on_monthly_grid_contributes_nothing(self, mode):
        md = _model([CLIENT_BF], [0.30], mode=mode, mean=self.P, std=self.SD)
        out = _compute_scenario_holidays(
            md, md['normalization'], self.MONTHLY, len(self.MONTHLY))
        assert out.shape == (len(self.MONTHLY),)
        assert np.all(out == 0.0), (
            f'режим {mode}: вклад клиентской колонки обязан быть тождественно нулевым, '
            f'получено {out.tolist()}')

    @pytest.mark.parametrize('mode', ['fraction', 'binary_point'])
    def test_guard_is_not_vacuous_canonical_still_moves(self, mode):
        """Сторож не пустой: в тех же условиях канонический столбец даёт числа.

        Иначе ноль клиентской колонки ничего не доказывал бы — он мог бы взяться
        из пустого календаря или сломанной генерации дамми.
        """
        md = _model([CANON_BF], [0.30], mode=mode, mean=self.P, std=self.SD)
        out = _compute_scenario_holidays(
            md, md['normalization'], self.MONTHLY, len(self.MONTHLY))
        assert np.any(np.abs(out) > 1.0), (
            f'режим {mode}: канонический столбец обязан давать ненулевой вклад, '
            f'иначе сторож ничего не стережёт: {out.tolist()}')
