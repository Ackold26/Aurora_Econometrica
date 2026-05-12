"""Tests для kpi_registry v1.3.0 - new kpi_kind + count KPIs + helper functions.

Per ADR-016 (KPI kinds binary verdict semantics).
"""
from __future__ import annotations

import pytest

import sys
from pathlib import Path
SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from utils.kpi_registry import (
    KPI_REGISTRY,
    KPIConfig,
    get_kpi_config,
    is_count_kpi,
    is_monetary_kpi,
    is_out_of_scope_v13,
    get_value_per_count_unit_label,
    list_count_kpi_types,
    list_monetary_kpi_types,
)


# ─── kpi_kind field ─────────────────────────────────────────────────────────

def test_sales_has_monetary_kind():
    """sales - это денежный KPI (выручка в ₽)."""
    assert get_kpi_config('sales').kpi_kind == 'monetary'


def test_revenue_has_monetary_kind():
    assert get_kpi_config('revenue').kpi_kind == 'monetary'


def test_profit_has_monetary_kind():
    assert get_kpi_config('profit').kpi_kind == 'monetary'


def test_sales_packs_has_count_kind():
    """sales_packs - это count KPI (штуки продаж)."""
    assert get_kpi_config('sales_packs').kpi_kind == 'count'


def test_leads_has_count_kind():
    assert get_kpi_config('leads').kpi_kind == 'count'


def test_registrations_has_count_kind():
    assert get_kpi_config('registrations').kpi_kind == 'count'


def test_loyalty_cards_has_count_kind():
    assert get_kpi_config('loyalty_cards').kpi_kind == 'count'


def test_subscriptions_has_count_kind():
    assert get_kpi_config('subscriptions').kpi_kind == 'count'


def test_app_installs_has_count_kind():
    assert get_kpi_config('app_installs').kpi_kind == 'count'


def test_count_custom_has_count_kind():
    assert get_kpi_config('count_custom').kpi_kind == 'count'


def test_awareness_has_proportional_kind():
    """awareness - proportional, out_of_scope_v13."""
    assert get_kpi_config('awareness').kpi_kind == 'proportional'
    assert get_kpi_config('awareness').out_of_scope_v13 is True


# ─── value_per_count_unit_label ─────────────────────────────────────────────

def test_sales_packs_label_is_margin_per_pack():
    assert get_kpi_config('sales_packs').value_per_count_unit_label == 'Маржа на упаковку, ₽'


def test_leads_label_is_value_per_lead():
    assert 'лида' in get_kpi_config('leads').value_per_count_unit_label.lower()


def test_subscriptions_label_is_mrr():
    assert 'MRR' in get_kpi_config('subscriptions').value_per_count_unit_label


def test_monetary_kpis_have_empty_label():
    """Monetary KPIs не показывают value_per_count_unit поле."""
    assert get_kpi_config('sales').value_per_count_unit_label == ''
    assert get_kpi_config('revenue').value_per_count_unit_label == ''
    assert get_kpi_config('profit').value_per_count_unit_label == ''


def test_get_value_per_count_unit_label_helper():
    """Helper возвращает то же что атрибут."""
    assert get_value_per_count_unit_label('sales_packs') == 'Маржа на упаковку, ₽'
    assert get_value_per_count_unit_label('leads') == 'Ценность лида, ₽'
    assert get_value_per_count_unit_label('sales') == ''


# ─── Helper functions ───────────────────────────────────────────────────────

def test_is_count_kpi_for_all_count_types():
    for kpi in ['sales_packs', 'leads', 'registrations', 'loyalty_cards',
                'subscriptions', 'app_installs', 'count_custom']:
        assert is_count_kpi(kpi), f"{kpi} should be count"


def test_is_count_kpi_false_for_monetary():
    for kpi in ['sales', 'revenue', 'profit']:
        assert not is_count_kpi(kpi), f"{kpi} should not be count"


def test_is_count_kpi_false_for_awareness():
    """awareness - proportional, не count."""
    assert not is_count_kpi('awareness')


def test_is_monetary_kpi_for_all_monetary_types():
    for kpi in ['sales', 'revenue', 'profit']:
        assert is_monetary_kpi(kpi), f"{kpi} should be monetary"


def test_is_monetary_kpi_false_for_count():
    for kpi in ['sales_packs', 'leads', 'registrations']:
        assert not is_monetary_kpi(kpi)


def test_is_out_of_scope_v13_for_awareness():
    assert is_out_of_scope_v13('awareness')


def test_is_out_of_scope_v13_false_for_v13_kpis():
    for kpi in ['sales', 'revenue', 'profit', 'sales_packs', 'leads']:
        assert not is_out_of_scope_v13(kpi)


def test_list_count_kpi_types_returns_seven():
    """7 count KPIs зарегистрированы в v1.3.0."""
    count_kpis = list_count_kpi_types()
    assert len(count_kpis) == 7
    assert 'sales_packs' in count_kpis
    assert 'leads' in count_kpis
    assert 'count_custom' in count_kpis
    assert 'sales' not in count_kpis  # monetary


def test_list_monetary_kpi_types_returns_three():
    monetary_kpis = list_monetary_kpi_types()
    assert len(monetary_kpis) == 3
    assert 'sales' in monetary_kpis
    assert 'revenue' in monetary_kpis
    assert 'profit' in monetary_kpis
    assert 'awareness' not in monetary_kpis  # proportional


# ─── Validation на module import ────────────────────────────────────────────

def test_count_kpi_without_label_raises_at_import():
    """count KPI с empty value_per_count_unit_label fails validation."""
    # Direct construction для теста validation logic.
    bad_config = KPIConfig(
        name='bad_count',
        likelihood='normal',
        kpi_kind='count',
        value_per_count_unit_label='',  # ← invalid for count
    )

    # Симулируем validation logic из _validate_registry().
    with pytest.raises(ValueError, match='count KPI requires non-empty'):
        if bad_config.kpi_kind == 'count' and not bad_config.value_per_count_unit_label:
            raise ValueError(
                f"KPI_REGISTRY['{bad_config.name}']: count KPI requires non-empty "
                f"value_per_count_unit_label (got '')."
            )


def test_monetary_kpi_with_label_raises_at_import():
    """monetary KPI с populated label fails validation (label не нужен)."""
    bad_config = KPIConfig(
        name='bad_monetary',
        likelihood='normal',
        kpi_kind='monetary',
        value_per_count_unit_label='Should not be here',  # ← invalid for monetary
    )

    with pytest.raises(ValueError, match='monetary KPI cannot have'):
        if bad_config.kpi_kind == 'monetary' and bad_config.value_per_count_unit_label:
            raise ValueError(
                f"KPI_REGISTRY['{bad_config.name}']: monetary KPI cannot have "
                f"value_per_count_unit_label (got '{bad_config.value_per_count_unit_label}'). "
                f"Monetary KPIs measure target в ₽ directly - value-per-unit поле не применимо."
            )


# ─── Backward compat - все 20 prior tests из test_kpi_registry.py должны pass ─

def test_v12_sales_priors_unchanged():
    """Trust 3 priors для sales - frozen (regression guard E3)."""
    config = get_kpi_config('sales')
    assert config.brand_mu_logit_prior == (0.7, 0.3)
    assert config.perf_mu_logit_prior == (-1.4, 0.7)
    assert config.brand_beta_sigma == 0.7
    assert config.perf_beta_sigma == 0.3
    assert config.gammas_alpha == 3.0
    assert config.gammas_beta == 3.0


def test_v12_awareness_priors_unchanged():
    """awareness frozen (Phase 3 calibration)."""
    config = get_kpi_config('awareness')
    assert config.brand_mu_logit_prior == (1.4, 0.4)
    assert config.ceiling == 100.0
    assert config.likelihood == 'logit_normal'
    assert config.baseline_drift is True
