"""Tests для utils/kpi_labels.py - v1.3.0 KPI/mode-aware labels (ADR-016)."""
from __future__ import annotations

import sys
from pathlib import Path
SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from utils.kpi_labels import (
    metric_label,
    metric_short_label,
    target_unit_label,
    target_axis_label,
    format_metric,
    cover_metric_summary,
    verdict_loss_threshold_label,
)


# ─── metric_label ───────────────────────────────────────────────────────────

def test_metric_label_monetary_roi():
    assert metric_label(kpi_kind='monetary', mode='roi') == 'ROI'


def test_metric_label_count_roi():
    assert 'CPU' in metric_label(kpi_kind='count', mode='roi')


def test_metric_label_effectiveness_overrides_kpi_kind():
    """Mode=effectiveness → share, irrespective of kpi_kind."""
    assert 'Доля' in metric_label(kpi_kind='monetary', mode='effectiveness')
    assert 'Доля' in metric_label(kpi_kind='count', mode='effectiveness')


def test_metric_label_default():
    assert metric_label() == 'ROI'


def test_metric_short_label():
    assert metric_short_label('monetary', 'roi') == 'ROI'
    assert metric_short_label('count', 'roi') == 'CPU'
    assert metric_short_label('monetary', 'effectiveness') == 'Доля'


# ─── target_unit_label ──────────────────────────────────────────────────────

def test_target_unit_label_monetary():
    assert target_unit_label('monetary') == '₽'


def test_target_unit_label_count():
    assert target_unit_label('count') == 'упак / ед.'


def test_target_axis_label_monetary():
    assert 'Продажи' in target_axis_label('monetary')
    assert '₽' in target_axis_label('monetary')


def test_target_axis_label_count():
    assert 'Продажи' in target_axis_label('count')
    assert 'упак' in target_axis_label('count')


# ─── format_metric ──────────────────────────────────────────────────────────

def test_format_metric_monetary_roi():
    assert format_metric(1.5, 'monetary', 'roi') == '1.50×'


def test_format_metric_count_inverts_to_cpu():
    """B4 audit fix (v1.3.2): backend convention puts mathematical units/₽
    in per-channel mroas. format_metric inverts to CPU display.

    Pre-fix: assumed input был ready CPU → format appended unit. После
    consistency audit обнаружено: backend (decomposer/narrative_adapter)
    pass raw units/₽. Helper now responsible для inversion.
    """
    # 0.0125 units/₽ → CPU = 1/0.0125 = 80 ₽/ед.
    assert format_metric(0.0125, 'count', 'roi') == '80 ₽/ед.'
    # 0.01 → 100
    assert format_metric(0.01, 'count', 'roi') == '100 ₽/ед.'
    # 0 / negative - no signal fallback
    assert format_metric(0, 'count', 'roi') == '-'
    assert format_metric(-0.5, 'count', 'roi') == '-'


def test_format_metric_effectiveness():
    assert format_metric(0.25, 'monetary', 'effectiveness') == '25.0%'


def test_format_metric_none_returns_dash():
    assert format_metric(None, 'monetary', 'roi') == '-'


# ─── cover_metric_summary ───────────────────────────────────────────────────

def test_cover_summary_monetary_roi():
    summary = cover_metric_summary(1.5, 'monetary', 'roi')
    assert 'ROI' in summary
    assert '1.50×' in summary


def test_cover_summary_count_with_value():
    """B4 audit: avg_metric receives mathematical units/₽; cover_summary
    inverts via format_metric для CPU display."""
    # avg_metric = 0.0125 units/₽ → CPU 80, value_per_count_unit = 80 ₽
    summary = cover_metric_summary(0.0125, 'count', 'roi', value_per_count_unit=80)
    assert 'CPU' in summary
    assert '80 ₽/ед.' in summary
    assert '80 ₽' in summary  # value mention (also)


def test_cover_summary_count_without_value():
    """B4 audit: 0.0125 units/₽ → CPU 80; без vpcu - нет «(vs ценность)»."""
    summary = cover_metric_summary(0.0125, 'count', 'roi', value_per_count_unit=None)
    assert 'CPU' in summary
    assert 'value' not in summary.lower()


def test_cover_summary_effectiveness_mentions_share():
    summary = cover_metric_summary(0.25, 'monetary', 'effectiveness')
    assert 'доля' in summary.lower()


# ─── verdict_loss_threshold_label ───────────────────────────────────────────

def test_methodology_label_monetary_explains_roi():
    label = verdict_loss_threshold_label('monetary')
    assert 'ROI' in label
    assert '1.0' in label or '> 1.0' in label or '1.0 = канал' in label


def test_methodology_label_count_explains_cpu_vs_value():
    label = verdict_loss_threshold_label('count')
    assert 'CPU' in label
    assert 'value' in label.lower() or 'ценност' in label.lower() or 'ценность' in label.lower()
