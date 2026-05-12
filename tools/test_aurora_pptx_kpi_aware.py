"""
KPI/mode-aware PPTX builder helpers tests (v1.3.2).

Импортирует aurora_pptx.kpi_helpers — extracted helpers module без зависимости
от aurora_tokens (которая нужна builder.py top-level). Builder.py reuse-ит эти
helpers через alias _kpi_view / _fmt_metric_pptx / etc.

Тесты parallel HTML KPI-aware test suite (tools/test_aurora_html_kpi_aware.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))


# ───── KPI view ────────────────────────────────────────────────────────


def test_kpi_view_defaults_when_no_data():
    from aurora_pptx.kpi_helpers import kpi_view
    view = kpi_view({})
    assert view['kpi_kind'] == 'monetary'
    assert view['mode'] == 'roi'
    assert view['is_legacy']
    assert view['metric_label'] == 'ROI'
    assert view['target_unit'] == '₽'


def test_kpi_view_handles_none_data():
    from aurora_pptx.kpi_helpers import kpi_view
    view = kpi_view(None)
    assert view['is_legacy']
    assert view['metric_short'] == 'ROI'


def test_kpi_view_count_mode_reads_labels():
    from aurora_pptx.kpi_helpers import kpi_view
    data = {
        'kpi': {
            'kpi_kind': 'count', 'derived_mode': 'roi',
            'value_per_count_unit': 80.0,
            'value_per_count_unit_label': '80 ₽/упак',
            'labels': {
                'metric_label': 'CPU, ₽/ед.',
                'metric_short_label': 'CPU',
                'target_unit_label': 'упак / ед.',
                'target_axis_label': 'Продажи, упак',
                'methodology_label': '',
            },
        },
    }
    view = kpi_view(data)
    assert view['kpi_kind'] == 'count'
    assert view['mode'] == 'roi'
    assert not view['is_legacy']
    assert view['metric_short'] == 'CPU'
    assert view['vpcu'] == 80.0
    assert view['target_unit'] == 'упак / ед.'


def test_kpi_view_effectiveness_mode():
    from aurora_pptx.kpi_helpers import kpi_view
    data = {
        'kpi': {
            'kpi_kind': 'monetary', 'derived_mode': 'effectiveness',
            'labels': {
                'metric_label': 'Доля %',
                'metric_short_label': 'Доля',
                'target_unit_label': '₽',
                'target_axis_label': 'Продажи, ₽',
                'methodology_label': '',
            },
        },
    }
    view = kpi_view(data)
    assert view['mode'] == 'effectiveness'
    assert not view['is_legacy']
    assert view['metric_short'] == 'Доля'


# ───── fmt_metric formatter ────────────────────────────────────────────


def test_fmt_metric_monetary_roi():
    from aurora_pptx.kpi_helpers import fmt_metric, kpi_view
    kpi = kpi_view({})
    assert fmt_metric(1.5, kpi) == '1.50×'
    assert fmt_metric(None, kpi) == '-'
    assert fmt_metric('bad', kpi) == '-'


def test_fmt_metric_count_inverts_to_cpu():
    """B4 audit fix: input units/₽ → CPU ₽/ед. via 1/x."""
    from aurora_pptx.kpi_helpers import fmt_metric, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}})
    assert fmt_metric(0.0125, kpi) == '80 ₽/ед.'  # 1/0.0125 = 80
    assert fmt_metric(0.01, kpi) == '100 ₽/ед.'
    # Zero / negative → fallback (no signal)
    assert fmt_metric(0, kpi) == '-'
    assert fmt_metric(-0.5, kpi) == '-'


def test_fmt_metric_effectiveness_fraction():
    from aurora_pptx.kpi_helpers import fmt_metric, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness', 'labels': {}}})
    # fraction (0..1) → percent normalized
    assert fmt_metric(0.25, kpi) == '25.0%'
    # already percent (>1) → keep as %
    assert fmt_metric(25, kpi) == '25%'


# ───── fmt_metric_with_ci_text ─────────────────────────────────────────


def test_fmt_metric_with_ci_legacy():
    from aurora_pptx.kpi_helpers import fmt_metric_with_ci_text, kpi_view
    kpi = kpi_view({})
    out = fmt_metric_with_ci_text(1.5, 1.2, 1.8, kpi)
    assert out == '1.50× [1.20—1.80]'


def test_fmt_metric_with_ci_count_inverts_and_swaps():
    """B4 audit fix: count CI inverts (1/x) и swaps order [lo_cpu — hi_cpu]."""
    from aurora_pptx.kpi_helpers import fmt_metric_with_ci_text, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}})
    # mean=0.0125 → CPU 80
    # ci_low=0.01 → CPU 100 (after invert → high CPU)
    # ci_high=0.0167 → CPU 60 (after invert → low CPU)
    # Display: «80 ₽/ед. [60—100]» (canonical [lo_cpu — hi_cpu]).
    out = fmt_metric_with_ci_text(0.0125, 0.01, 0.01667, kpi)
    assert '80 ₽/ед.' in out
    assert '[60—100]' in out


def test_fmt_metric_with_ci_effectiveness_fraction():
    from aurora_pptx.kpi_helpers import fmt_metric_with_ci_text, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness', 'labels': {}}})
    out = fmt_metric_with_ci_text(0.25, 0.20, 0.30, kpi)
    # mean 25.0%, ci [20.0—30.0]
    assert '25.0' in out
    assert '20.0' in out
    assert '30.0' in out


def test_fmt_metric_with_ci_returns_base_when_no_ci():
    from aurora_pptx.kpi_helpers import fmt_metric_with_ci_text, kpi_view
    kpi = kpi_view({})
    assert fmt_metric_with_ci_text(1.5, None, None, kpi) == '1.50×'
    assert fmt_metric_with_ci_text(1.5, 1.2, None, kpi) == '1.50×'


# ───── weighted_summary_phrase ─────────────────────────────────────────


def test_weighted_summary_phrase_monetary():
    from aurora_pptx.kpi_helpers import weighted_summary_phrase, kpi_view
    kpi = kpi_view({})
    assert weighted_summary_phrase(1.5, kpi) == 'ROI портфеля 1.50×'


def test_weighted_summary_phrase_count_inverts():
    """weighted_roi=0.0125 units/₽ → CPU = 80 ₽/ед. inversion."""
    from aurora_pptx.kpi_helpers import weighted_summary_phrase, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}})
    phrase = weighted_summary_phrase(0.0125, kpi)
    assert phrase == 'CPU портфеля 80 ₽/ед.'


def test_weighted_summary_phrase_count_zero_safe():
    from aurora_pptx.kpi_helpers import weighted_summary_phrase, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}})
    assert weighted_summary_phrase(0, kpi) == 'CPU портфеля недоступен'


def test_weighted_summary_phrase_effectiveness():
    from aurora_pptx.kpi_helpers import weighted_summary_phrase, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness', 'labels': {}}})
    assert weighted_summary_phrase(1.0, kpi) == 'Средняя доля каналов в портфеле'


def test_weighted_summary_phrase_none_safe():
    from aurora_pptx.kpi_helpers import weighted_summary_phrase, kpi_view
    kpi = kpi_view({})
    assert weighted_summary_phrase(None, kpi) == ''


# ───── under_breakeven_phrase ──────────────────────────────────────────


def test_under_breakeven_legacy():
    from aurora_pptx.kpi_helpers import under_breakeven_phrase, kpi_view
    assert under_breakeven_phrase(kpi_view({})) == 'mROAS < 1×'


def test_under_breakeven_count_with_vpcu():
    from aurora_pptx.kpi_helpers import under_breakeven_phrase, kpi_view
    kpi = kpi_view({
        'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi',
                'value_per_count_unit': 80.0, 'labels': {}}
    })
    out = under_breakeven_phrase(kpi)
    assert 'CPU >' in out
    assert '80' in out


def test_under_breakeven_count_without_vpcu():
    from aurora_pptx.kpi_helpers import under_breakeven_phrase, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}})
    out = under_breakeven_phrase(kpi)
    assert 'CPU > ценности' in out


def test_under_breakeven_effectiveness():
    from aurora_pptx.kpi_helpers import under_breakeven_phrase, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness', 'labels': {}}})
    assert under_breakeven_phrase(kpi) == 'доля < бенчмарка'


# ───── table_metric_header ─────────────────────────────────────────────


def test_table_metric_header_legacy():
    from aurora_pptx.kpi_helpers import table_metric_header, kpi_view
    assert table_metric_header(kpi_view({})) == ('mROAS', '×')


def test_table_metric_header_count():
    from aurora_pptx.kpi_helpers import table_metric_header, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}})
    assert table_metric_header(kpi) == ('CPU', '₽/ед.')


def test_table_metric_header_effectiveness():
    from aurora_pptx.kpi_helpers import table_metric_header, kpi_view
    kpi = kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness', 'labels': {}}})
    assert table_metric_header(kpi) == ('Доля эффекта', '%')


# ───── Parity with aurora_html helpers ─────────────────────────────────


def test_pptx_kpi_helpers_parity_with_html():
    """Sanity check: PPTX и HTML _kpi_view contracts identical для общего ctx/data."""
    from aurora_pptx.kpi_helpers import kpi_view as pptx_view
    from aurora_html.sections import _kpi_view as html_view

    data = {
        'kpi': {
            'kpi_kind': 'count', 'derived_mode': 'roi',
            'value_per_count_unit': 80.0,
            'labels': {
                'metric_label': 'CPU',
                'metric_short_label': 'CPU',
                'target_unit_label': 'упак',
                'target_axis_label': 'Продажи, упак',
                'methodology_label': '',
            },
        },
    }
    p = pptx_view(data)
    h = html_view(data)

    # Ключевые поля должны совпадать (PPTX = ctx → data, HTML = ctx).
    assert p['kpi_kind'] == h['kpi_kind']
    assert p['mode'] == h['mode']
    assert p['metric_short'] == h['metric_short']
    assert p['is_legacy'] == h['is_legacy']
    assert p['vpcu'] == h['vpcu']
