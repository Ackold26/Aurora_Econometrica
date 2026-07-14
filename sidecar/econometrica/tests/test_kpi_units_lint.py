"""Фаза 4 — Гейт 1: Унит-линт «нет денег на результате».

Прогоняет ключевые фразо/подпись-функции на трёх режимах (count/effectiveness/monetary)
и ассертит ОТСУТСТВИЕ запрещённых «денежных» токенов в result-фразах для count/effectiveness,
и НАЛИЧИЕ этих токенов для monetary (чтобы гейт не переусердствовал).

Охват:
  - utils.kpi_labels.target_axis_label / metric_label / format_metric
  - aurora_pptx.kpi_helpers.lift_phrase / hero_vs_leader_quote / fmt_metric
  - engines.channel_action.compute_channel_action(...).reasoning

Запрещённые токены (для count/effectiveness result-фраз):
  - 'ROAS', 'mROAS', 'каждый рубль', 'Продажи, ₽', 'рубля продаж'
  - reasoning для count/effectiveness: не должен содержать breakeven-фразы
    с денежной семантикой (okupаемость по ROI, не CPU) — зафиксировано текущее поведение.

Monetary-контрольные тесты: 'ROI' / 'ROAS' / '₽' ДОЛЖНЫ присутствовать.
"""
import sys
import os
from pathlib import Path

# Bootstrap — cwd-независим (canonical pattern из test_channel_action_kpi_aware.py)
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from utils.kpi_labels import (  # noqa: E402
    target_axis_label,
    metric_label,
    format_metric,
)
from aurora_pptx.kpi_helpers import (  # noqa: E402
    lift_phrase,
    hero_vs_leader_quote,
    fmt_metric,
    kpi_view,
)
from engines.channel_action import compute_channel_action  # noqa: E402


# ─── Вспомогательные константы ───────────────────────────────────────────────

# Токены, запрещённые в result-фразах для count/effectiveness KPI.
# Ограничение: НЕ применять к строкам про ЗАТРАТЫ (там ₽ корректно).
_FORBIDDEN_IN_RESULT = ('ROAS', 'mROAS', 'каждый рубль', 'Продажи, ₽', 'рубля продаж')

# kpi-dict для тестов kpi_helpers (через kpi_view)
def _make_kpi_view_count_leads():
    """kpi_view-результат для count 'leads'."""
    return kpi_view({
        'kpi': {
            'kpi_kind': 'count',
            'derived_mode': 'roi',
            'kpi_type': 'leads',
            'value_per_count_unit': 500.0,
            'value_per_count_unit_label': '₽/лид',
            'labels': {},
        }
    })


def _make_kpi_view_count_sales_packs():
    """kpi_view-результат для count 'sales_packs'."""
    return kpi_view({
        'kpi': {
            'kpi_kind': 'count',
            'derived_mode': 'roi',
            'kpi_type': 'sales_packs',
            'value_per_count_unit': 200.0,
            'value_per_count_unit_label': '₽/упак.',
            'labels': {},
        }
    })


def _make_kpi_view_effectiveness():
    """kpi_view-результат для effectiveness (derived_mode='effectiveness')."""
    return kpi_view({
        'kpi': {
            'kpi_kind': 'monetary',
            'derived_mode': 'effectiveness',
            'kpi_type': None,
            'labels': {
                'metric_label': 'Доля %',
                'metric_short_label': 'Доля',
                'target_unit_label': '%',
                'target_axis_label': 'Доля эффекта',
                'methodology_label': '',
            },
        }
    })


def _make_kpi_view_monetary():
    """kpi_view-результат для monetary (legacy ROI)."""
    return kpi_view({
        'kpi': {
            'kpi_kind': 'monetary',
            'derived_mode': 'roi',
            'kpi_type': None,
            'labels': {
                'metric_label': 'ROI',
                'metric_short_label': 'ROI',
                'target_unit_label': '₽',
                'target_axis_label': 'Продажи, ₽',
                'methodology_label': '',
            },
        }
    })


def _make_channel(mroas=1.0, current_spend=1_000_000.0, optimal_spend=None):
    ch = {'mroas': mroas, 'current_spend': current_spend, 'efficiency_gap': 0.0, 'untrained': False}
    if optimal_spend is not None:
        ch['optimal_spend'] = optimal_spend
    return ch


def _assert_no_forbidden(text: str, label: str):
    """Проверяет отсутствие всех запрещённых токенов в result-фразе."""
    for token in _FORBIDDEN_IN_RESULT:
        assert token not in text, (
            f"{label}: найден запрещённый токен '{token}' в result-фразе: {text!r}"
        )


# ─── ГЕЙТ 1a: utils.kpi_labels — target_axis_label / metric_label / format_metric ──

class TestKpiLabelsNoMoneyOnResult:
    """utils.kpi_labels: подписи осей/метрик для count/effectiveness не содержат денежных токенов."""

    # ── count 'leads' (vpcu задан) ───────────────────────────────────────────

    def test_target_axis_count_leads_no_rub(self):
        result = target_axis_label(kpi_kind='count', kpi_type='leads')
        _assert_no_forbidden(result, "target_axis_label(count/leads)")

    def test_metric_label_count_leads_no_roas(self):
        result = metric_label(kpi_kind='count', mode='roi', kpi_type='leads')
        _assert_no_forbidden(result, "metric_label(count/leads/roi)")
        # Дополнительно: должен содержать 'CPU' и паспортную единицу
        assert 'CPU' in result, f"metric_label(count/leads/roi) должен содержать 'CPU': {result!r}"
        assert '₽/лид' in result, f"metric_label(count/leads/roi) должен содержать '₽/лид': {result!r}"

    def test_format_metric_count_leads_no_roas(self):
        result = format_metric(0.0125, kpi_kind='count', mode='roi', kpi_type='leads')
        _assert_no_forbidden(result, "format_metric(count/leads/roi, 0.0125)")
        assert '₽/лид' in result, f"format_metric count/leads должен давать '₽/лид': {result!r}"

    # ── count 'leads' (vpcu НЕ задан — backward-compat path) ─────────────────

    def test_target_axis_count_no_kpi_type_no_rub(self):
        """count без kpi_type: ось не должна быть 'Продажи, ₽'."""
        result = target_axis_label(kpi_kind='count')
        assert result != 'Продажи, ₽', (
            f"target_axis_label(count) без kpi_type не должен давать 'Продажи, ₽': {result!r}"
        )

    def test_metric_label_count_no_kpi_type_no_roas(self):
        result = metric_label(kpi_kind='count', mode='roi')
        _assert_no_forbidden(result, "metric_label(count/roi, no kpi_type)")
        assert 'CPU' in result, f"metric_label(count/roi, no kpi_type) должен содержать 'CPU': {result!r}"

    # ── count 'sales_packs' ────────────────────────────────────────────────────

    def test_target_axis_sales_packs_no_rub(self):
        result = target_axis_label(kpi_kind='count', kpi_type='sales_packs')
        _assert_no_forbidden(result, "target_axis_label(count/sales_packs)")

    def test_metric_label_sales_packs_no_roas(self):
        result = metric_label(kpi_kind='count', mode='roi', kpi_type='sales_packs')
        _assert_no_forbidden(result, "metric_label(count/sales_packs/roi)")
        assert 'CPU' in result

    def test_format_metric_sales_packs_no_roas(self):
        result = format_metric(0.01, kpi_kind='count', mode='roi', kpi_type='sales_packs')
        _assert_no_forbidden(result, "format_metric(count/sales_packs/roi, 0.01)")

    # ── effectiveness ──────────────────────────────────────────────────────────

    def test_metric_label_effectiveness_no_roas(self):
        result = metric_label(kpi_kind='monetary', mode='effectiveness')
        _assert_no_forbidden(result, "metric_label(monetary/effectiveness)")
        assert 'Доля' in result, f"metric_label(effectiveness) должен содержать 'Доля': {result!r}"

    def test_format_metric_effectiveness_no_roas(self):
        result = format_metric(0.25, kpi_kind='monetary', mode='effectiveness')
        _assert_no_forbidden(result, "format_metric(effectiveness, 0.25)")
        assert '%' in result, f"format_metric(effectiveness) должен давать '%': {result!r}"

    # ── monetary — контроль: ROI/ROAS/₽ ДОЛЖНЫ присутствовать ────────────────

    def test_target_axis_monetary_has_rub(self):
        result = target_axis_label(kpi_kind='monetary')
        assert '₽' in result, f"monetary target_axis_label должен содержать '₽': {result!r}"

    def test_metric_label_monetary_has_roi(self):
        result = metric_label(kpi_kind='monetary', mode='roi')
        assert 'ROI' in result, f"monetary metric_label должен содержать 'ROI': {result!r}"

    def test_format_metric_monetary_has_multiplier(self):
        result = format_metric(1.5, kpi_kind='monetary', mode='roi')
        assert '×' in result, f"monetary format_metric должен давать '×': {result!r}"


# ─── ГЕЙТ 1b: aurora_pptx.kpi_helpers — lift_phrase / hero_vs_leader_quote / fmt_metric ──

class TestKpiHelpersNoMoneyOnResult:
    """aurora_pptx.kpi_helpers: фразы и метрики count/effectiveness не содержат денежных токенов."""

    # ── count 'leads' ─────────────────────────────────────────────────────────

    def test_lift_phrase_count_leads_no_roas(self):
        kpi = _make_kpi_view_count_leads()
        result = lift_phrase(3.5, kpi)
        for token in ('ROAS', 'mROAS', 'каждый рубль', 'рубля продаж'):
            assert token not in result, (
                f"lift_phrase(count/leads): найден запрещённый токен '{token}': {result!r}"
            )
        # Должен содержать числовое значение
        assert '3.5' in result, f"lift_phrase(count/leads) должен содержать '3.5': {result!r}"

    def test_lift_phrase_count_leads_none_no_roas(self):
        """lift_phrase(None, count/leads) не должен содержать ROAS."""
        kpi = _make_kpi_view_count_leads()
        result = lift_phrase(None, kpi)
        for token in ('ROAS', 'mROAS', 'каждый рубль'):
            assert token not in result, (
                f"lift_phrase(None, count/leads): найден '{token}': {result!r}"
            )

    def test_hero_vs_leader_count_leads_no_ruble_phrase(self):
        kpi = _make_kpi_view_count_leads()
        result = hero_vs_leader_quote('Digital', 'TV', kpi)
        assert 'каждый рубль' not in result.lower(), (
            f"hero_vs_leader_quote(count/leads): содержит 'каждый рубль': {result!r}"
        )
        assert 'ROAS' not in result, (
            f"hero_vs_leader_quote(count/leads): содержит 'ROAS': {result!r}"
        )
        assert 'Digital' in result and 'TV' in result

    def test_fmt_metric_count_leads_no_roas(self):
        kpi = _make_kpi_view_count_leads()
        result = fmt_metric(0.0125, kpi)
        _assert_no_forbidden(result, "fmt_metric(count/leads, 0.0125)")
        assert '₽/лид' in result, f"fmt_metric(count/leads) должен давать '₽/лид': {result!r}"

    # ── count 'sales_packs' ───────────────────────────────────────────────────

    def test_lift_phrase_count_sales_packs_no_roas(self):
        kpi = _make_kpi_view_count_sales_packs()
        result = lift_phrase(2.0, kpi)
        for token in ('ROAS', 'mROAS', 'каждый рубль'):
            assert token not in result, (
                f"lift_phrase(count/sales_packs): найден '{token}': {result!r}"
            )

    def test_hero_vs_leader_count_sales_packs_no_ruble(self):
        kpi = _make_kpi_view_count_sales_packs()
        result = hero_vs_leader_quote('TV', 'Digital', kpi)
        assert 'каждый рубль' not in result.lower(), (
            f"hero_vs_leader_quote(count/sales_packs): содержит 'каждый рубль': {result!r}"
        )

    # ── effectiveness ──────────────────────────────────────────────────────────

    def test_lift_phrase_effectiveness_no_roas(self):
        kpi = _make_kpi_view_effectiveness()
        result = lift_phrase(2.5, kpi)
        for token in ('ROAS', 'mROAS', 'каждый рубль'):
            assert token not in result, (
                f"lift_phrase(effectiveness): найден '{token}': {result!r}"
            )
        assert 'доля' in result.lower() or 'эффект' in result.lower(), (
            f"lift_phrase(effectiveness) должен упоминать долю/эффект: {result!r}"
        )

    def test_hero_vs_leader_effectiveness_no_ruble(self):
        kpi = _make_kpi_view_effectiveness()
        result = hero_vs_leader_quote('Digital', 'TV', kpi)
        assert 'каждый рубль' not in result.lower(), (
            f"hero_vs_leader_quote(effectiveness): содержит 'каждый рубль': {result!r}"
        )

    # ── monetary — контроль: ROAS/рубль ДОЛЖНЫ присутствовать ────────────────

    def test_lift_phrase_monetary_has_roas(self):
        kpi = _make_kpi_view_monetary()
        result = lift_phrase(5.0, kpi)
        assert 'ROAS' in result, (
            f"lift_phrase(monetary) должен содержать 'ROAS': {result!r}"
        )

    def test_hero_vs_leader_monetary_has_ruble(self):
        kpi = _make_kpi_view_monetary()
        result = hero_vs_leader_quote('Digital', 'TV', kpi)
        assert 'рубль' in result.lower(), (
            f"hero_vs_leader_quote(monetary) должен содержать 'рубль': {result!r}"
        )


# ─── ГЕЙТ 1c: engines.channel_action.compute_channel_action — reasoning ────────

class TestChannelActionReasoningNoMoneyOnResult:
    """compute_channel_action.reasoning для count/effectiveness не содержит денежных маркеров результата.

    Ассертим поведение reasoning для счётной метрики:
    - НЕ содержит 'ROAS', 'mROAS' (ошибочные денежные термины для count)
    - НЕ содержит 'рубля продаж' (имеется в виду форфраза результата, не затрат)
    - МОЖЕТ содержать 'рубль' в контексте затрат/убытка (корректно: 'каждый рубль приносит убыток')
    - ДОЛЖЕН содержать cpu_per_label ('₽/лид') при vpcu задан

    Примечание: «каждый рубль приносит убыток» в reasoning — КОРРЕКТНО (это про затраты).
    Запрет на 'Продажи, ₽' не применяется к reasoning напрямую (там нет подписей осей).
    """

    def test_count_vpcu_reasoning_no_mroas_token(self):
        """count + vpcu: reasoning не содержит 'mROAS'."""
        ch = _make_channel(mroas=0.0125, optimal_spend=1_100_000.0)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        assert 'mROAS' not in result.reasoning, (
            f"reasoning count+vpcu не должен содержать 'mROAS': {result.reasoning!r}"
        )

    def test_count_vpcu_reasoning_no_roas_token(self):
        """count + vpcu: reasoning не содержит 'ROAS'."""
        ch = _make_channel(mroas=0.0125)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        assert 'ROAS' not in result.reasoning, (
            f"reasoning count+vpcu не должен содержать 'ROAS': {result.reasoning!r}"
        )

    def test_count_vpcu_reasoning_contains_cpu_per_label(self):
        """count + vpcu: reasoning содержит cpu_per_label ('₽/лид')."""
        ch = _make_channel(mroas=0.005)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        assert '₽/лид' in result.reasoning, (
            f"reasoning count+vpcu должен содержать '₽/лид': {result.reasoning!r}"
        )

    def test_count_no_vpcu_reasoning_no_mroas_token(self):
        """count без vpcu (деградация): reasoning не содержит 'mROAS'."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_000_000.0)
        result = compute_channel_action(
            ch, kpi_kind='count', money_roi_unavailable=True, cpu_per_label='₽/лид'
        )
        assert 'mROAS' not in result.reasoning, (
            f"reasoning count (деградация) не должен содержать 'mROAS': {result.reasoning!r}"
        )

    def test_effectiveness_reasoning_no_mroas_token(self):
        """effectiveness (money_roi_unavailable=True): reasoning не содержит 'mROAS'."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_000_000.0)
        result = compute_channel_action(
            ch, kpi_kind='count', money_roi_unavailable=True,
            metric_short='Доля', cpu_per_label='%'
        )
        assert 'mROAS' not in result.reasoning, (
            f"reasoning effectiveness не должен содержать 'mROAS': {result.reasoning!r}"
        )

    def test_effectiveness_reasoning_no_roas_token(self):
        """effectiveness: reasoning не содержит 'ROAS'."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_000_000.0)
        result = compute_channel_action(
            ch, kpi_kind='count', money_roi_unavailable=True,
            metric_short='Доля', cpu_per_label='%'
        )
        assert 'ROAS' not in result.reasoning, (
            f"reasoning effectiveness не должен содержать 'ROAS': {result.reasoning!r}"
        )

    # ── monetary — контроль: '×' ДОЛЖЕН быть ─────────────────────────────────

    def test_monetary_reasoning_contains_multiplier(self):
        """monetary reasoning содержит '×' (или breakeven), не содержит '₽/лид'."""
        ch = _make_channel(mroas=0.5)
        result = compute_channel_action(ch, kpi_kind='monetary')
        assert '×' in result.reasoning or 'breakeven' in result.reasoning, (
            f"monetary reasoning должен содержать '×' или 'breakeven': {result.reasoning!r}"
        )
        assert '₽/лид' not in result.reasoning, (
            f"monetary reasoning не должен содержать '₽/лид': {result.reasoning!r}"
        )


# ─── ГЕЙТ 1d: полный матричный прогон ────────────────────────────────────────

class TestFullModeMatrix:
    """Матрица (mode × kpi_type) × функция — быстрый прогон без избыточности."""

    CASES = [
        # (kpi_kind, kpi_type, mode, vpcu, cpu_per_label)
        ('count', 'leads',       'roi',           80.0,  '₽/лид'),
        ('count', 'leads',       'roi',           None,  '₽/лид'),   # vpcu=None
        ('count', 'sales_packs', 'roi',           200.0, '₽/упак.'),
        ('count', None,          'effectiveness', None,  '%'),
    ]

    def test_target_axis_not_rub_mln(self):
        for kpi_kind, kpi_type, mode, vpcu, cpu in self.CASES:
            result = target_axis_label(kpi_kind=kpi_kind, kpi_type=kpi_type)
            assert result != 'Продажи, ₽', (
                f"target_axis_label({kpi_kind}/{kpi_type}/{mode}) вернул 'Продажи, ₽'"
            )
            for token in ('ROAS', 'mROAS'):
                assert token not in result, (
                    f"target_axis_label({kpi_kind}/{kpi_type}/{mode}): найден '{token}': {result!r}"
                )

    def test_metric_label_not_roas(self):
        for kpi_kind, kpi_type, mode, vpcu, cpu in self.CASES:
            result = metric_label(kpi_kind=kpi_kind, mode=mode, kpi_type=kpi_type)
            for token in ('ROAS', 'mROAS'):
                assert token not in result, (
                    f"metric_label({kpi_kind}/{kpi_type}/{mode}): найден '{token}': {result!r}"
                )
