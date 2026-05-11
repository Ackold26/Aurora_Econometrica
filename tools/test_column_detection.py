"""Tests для utils/column_detection.py — v1.3.0 auto-classify columns (ADR-015)."""
from __future__ import annotations

import sys
from pathlib import Path
SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from utils.column_detection import (
    classify_column,
    classify_columns,
    detect_available_metrics,
    has_ambiguous_channels,
    suggest_default_input_metric,
)


# ─── classify_column — RU patterns ──────────────────────────────────────────

def test_classify_russian_budget():
    assert classify_column('тв_бюджет') == 'monetary'
    assert classify_column('бюджет_тв') == 'monetary'
    assert classify_column('расходы_радио') == 'monetary'
    assert classify_column('маркетинг_затраты') == 'monetary'


def test_classify_russian_impressions():
    assert classify_column('тв_показы') == 'physical'
    assert classify_column('показы_olv') == 'physical'
    assert classify_column('охват_baннер') == 'physical'


def test_classify_russian_grp():
    assert classify_column('тв_грп') == 'physical'
    assert classify_column('грп_w_25_54') == 'physical'


def test_classify_russian_clicks():
    assert classify_column('performance_кликов') == 'physical'


# ─── classify_column — EN patterns ──────────────────────────────────────────

def test_classify_english_budget():
    assert classify_column('tv_spend') == 'monetary'
    assert classify_column('tv_budget') == 'monetary'
    assert classify_column('marketing_cost') == 'monetary'
    assert classify_column('ad_expense') == 'monetary'


def test_classify_english_impressions():
    assert classify_column('tv_impressions') == 'physical'
    assert classify_column('olv_impr') == 'physical'
    assert classify_column('display_views') == 'physical'


def test_classify_english_clicks():
    assert classify_column('performance_clicks') == 'physical'
    assert classify_column('paid_clicks') == 'physical'


def test_classify_english_grp():
    assert classify_column('tv_grp') == 'physical'
    assert classify_column('tv_trp') == 'physical'


# ─── Target metrics ─────────────────────────────────────────────────────────

def test_classify_sales_rub_as_target_monetary():
    assert classify_column('sales_rub') == 'target_monetary'
    assert classify_column('revenue') == 'target_monetary'
    assert classify_column('выручка') == 'target_monetary'
    assert classify_column('продажи_руб') == 'target_monetary'


def test_classify_sales_packs_as_target_count():
    assert classify_column('sales_packs') == 'target_count'
    assert classify_column('продажи_шт') == 'target_count'
    assert classify_column('продажи_упак') == 'target_count'


def test_classify_leads_as_target_count():
    assert classify_column('leads') == 'target_count'
    assert classify_column('лиды') == 'target_count'


def test_classify_registrations_as_target_count():
    assert classify_column('registrations') == 'target_count'
    assert classify_column('signups') == 'target_count'
    assert classify_column('регистрации') == 'target_count'


def test_classify_subscriptions_as_target_count():
    assert classify_column('subscriptions') == 'target_count'
    assert classify_column('подписки') == 'target_count'


# ─── Date columns ───────────────────────────────────────────────────────────

def test_classify_date_columns():
    assert classify_column('date') == 'date'
    assert classify_column('week') == 'date'
    assert classify_column('месяц') == 'date'
    assert classify_column('period') == 'date'


# ─── Unknown / ambiguous ────────────────────────────────────────────────────

def test_classify_unknown_column():
    assert classify_column('weird_obscure_thing') == 'unknown'
    assert classify_column('column_a') == 'unknown'
    assert classify_column('') == 'unknown'


# ─── classify_columns batch ─────────────────────────────────────────────────

def test_classify_columns_batch():
    cols = ['date', 'tv_spend', 'olv_impressions', 'sales_rub']
    result = classify_columns(cols)
    assert result == {
        'date': 'date',
        'tv_spend': 'monetary',
        'olv_impressions': 'physical',
        'sales_rub': 'target_monetary',
    }


# ─── detect_available_metrics ───────────────────────────────────────────────

def test_detect_metrics_for_tv_with_both():
    cols = ['date', 'tv_spend', 'tv_grp', 'olv_impressions']
    result = detect_available_metrics(cols, 'tv')
    assert result['monetary'] == ['tv_spend']
    assert result['physical'] == ['tv_grp']


def test_detect_metrics_for_olv_physical_only():
    cols = ['date', 'tv_spend', 'olv_impressions']
    result = detect_available_metrics(cols, 'olv')
    assert result['monetary'] == []
    assert result['physical'] == ['olv_impressions']


def test_detect_metrics_for_channel_no_columns():
    cols = ['date', 'tv_spend']
    result = detect_available_metrics(cols, 'unknown_channel')
    assert result == {'monetary': [], 'physical': []}


# ─── has_ambiguous_channels ─────────────────────────────────────────────────

def test_ambiguous_when_tv_has_both():
    cols = ['date', 'tv_spend', 'tv_grp', 'olv_impressions', 'sales_rub']
    assert has_ambiguous_channels(cols, ['tv', 'olv'])


def test_not_ambiguous_when_all_single_metric():
    cols = ['date', 'tv_spend', 'olv_spend', 'performance_spend', 'sales_rub']
    assert not has_ambiguous_channels(cols, ['tv', 'olv', 'performance'])


# ─── suggest_default_input_metric ───────────────────────────────────────────

def test_suggest_defaults_mixed():
    cols = ['date', 'tv_spend', 'olv_impressions', 'sales_rub']
    defaults = suggest_default_input_metric(cols, ['tv', 'olv'])
    assert defaults == {'tv': 'monetary', 'olv': 'physical'}


def test_suggest_defaults_monetary_preferred_when_both_available():
    """Если у канала есть и monetary и physical — приоритет monetary."""
    cols = ['date', 'tv_spend', 'tv_grp']
    defaults = suggest_default_input_metric(cols, ['tv'])
    assert defaults == {'tv': 'monetary'}


def test_suggest_defaults_fallback_when_nothing():
    """Если ни одной метрики не найдено — fallback monetary."""
    cols = ['date']
    defaults = suggest_default_input_metric(cols, ['unknown_channel'])
    assert defaults == {'unknown_channel': 'monetary'}
