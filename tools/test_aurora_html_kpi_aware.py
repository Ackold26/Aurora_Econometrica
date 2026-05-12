"""
KPI/mode-aware HTML sections render tests (v1.3.2).

Validates что labels внутри HTML отчёта корректно подменяются для
3 базовых режимов: legacy monetary roi / count roi / monetary effectiveness.

Backward compat: legacy ctx (без 'kpi' block) → render как v1.2, без CPU/Доля
mentions. Pre-fix: hardcoded "ROI"/"mROAS" в sections.py никогда не учитывали
kpi_kind/derived_mode - для count KPI отчёт показывал бессмысленные ROI×.

Pattern: build minimal synthetic ctx, render каждую секцию, assert наличие/
отсутствие labels.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))


def _strings() -> dict:
    return json.loads(
        (SIDECAR / 'econometrica' / 'aurora_html' / 'strings_ru.json').read_text(encoding='utf-8')
    )


def _ctx(kpi_kind: str = 'monetary', mode: str = 'roi', with_kpi: bool = True) -> dict:
    """Build minimal synthetic ctx covering всех существенных полей.

    with_kpi=False → ctx без `kpi` блока (legacy v1.2 caller path).
    """
    base = {
        'meta': {'client': 'TestCo', 'report_date': '2026-Q2', 'version': '1.3.2'},
        'strings': _strings(),
        'channels': [
            {
                'name': 'TV', 'spend': 50_000_000, 'contribution': 30_000_000,
                'mroas': 1.2, 'verdict': 'Hold', 'action': 'Hold',
                'action_label': 'Удержать', 'action_priority': 4,
                'action_reasoning': 'mROAS в стабильном диапазоне.',
                'mroas_ci_low': 1.0, 'mroas_ci_high': 1.4,
                'current_spend': 50_000_000, 'optimal_spend': 50_000_000,
            },
            {
                'name': 'Digital', 'spend': 30_000_000, 'contribution': 25_000_000,
                'mroas': 0.8, 'verdict': 'Cut', 'action': 'Cut',
                'action_label': 'Сократить', 'action_priority': 0,
                'action_reasoning': 'mROAS ниже breakeven.',
                'mroas_ci_low': 0.6, 'mroas_ci_high': 1.0,
                'current_spend': 30_000_000, 'optimal_spend': 20_000_000,
            },
        ],
        'facts': {
            'total_budget_mln': 80, 'total_contrib_mln': 55,
            'weighted_roi': 0.69 if kpi_kind == 'monetary' else 0.0125,
            'leader_channel': 'TV', 'hero_channel': 'TV',
            'leader_share_spend_pct': 62, 'leader_share_contrib_pct': 55,
            'reallocation_mln': 10, 'expected_lift_pct': 5,
            'optimization_converged': True, 'binding_constraints': False,
            'cut_source_channel': 'Digital', 'scale_destination_channel': 'TV',
            'underperformer_names': [],
            'n_active_channels': 2,
            'action_counts': {'Scale': 0, 'Hold': 1, 'Cut': 1, 'Watch': 0, 'Reduce': 0, 'Uncertain': 0},
            'media_contribution_pct': 50, 'baseline_pct': 30, 'honest_narrative': False,
            'budget_dominator_channel': 'TV',
            'budget_dominator_spend_pct': 62, 'budget_dominator_contrib_pct': 55,
        },
        'diagnostics': {'mqs_score': 70, 'mqs_tier_label': 'Хорошее'},
    }
    if with_kpi:
        base['kpi'] = {
            'kpi_kind': kpi_kind, 'derived_mode': mode,
            'value_per_count_unit': 80.0 if kpi_kind == 'count' else None,
            'value_per_count_unit_label': '80 ₽/упак' if kpi_kind == 'count' else '',
            'labels': {
                'metric_label': (
                    'CPU, ₽/ед.' if kpi_kind == 'count'
                    else ('Доля %' if mode == 'effectiveness' else 'ROI')
                ),
                'metric_short_label': (
                    'CPU' if kpi_kind == 'count'
                    else ('Доля' if mode == 'effectiveness' else 'ROI')
                ),
                'target_unit_label': 'упак / ед.' if kpi_kind == 'count' else '₽',
                'target_axis_label': 'Продажи, упак' if kpi_kind == 'count' else 'Продажи, ₽',
                'methodology_label': '',
            },
        }
    return base


# ───── Helpers ─────────────────────────────────────────────────────────


def _import_sections():
    from aurora_html.sections import (
        render_at_a_glance, render_key_message, render_mroas,
        render_action_table, render_recommendation, render_executive_summary,
        _kpi_view,
    )
    return {
        'glance': render_at_a_glance,
        'key': render_key_message,
        'mroas': render_mroas,
        'table': render_action_table,
        'recommend': render_recommendation,
        'summary': render_executive_summary,
        'view': _kpi_view,
    }


# ───── Backward compat (legacy ctx) ────────────────────────────────────


def test_legacy_ctx_without_kpi_block_renders_roi():
    """Legacy v1.2 caller без ctx['kpi'] → ROI/mROAS labels intact."""
    s = _import_sections()
    ctx = _ctx(with_kpi=False)
    view = s['view'](ctx)
    assert view['is_legacy']
    assert view['kpi_kind'] == 'monetary'
    assert view['mode'] == 'roi'

    html = s['table'](ctx)
    assert 'mROAS' in html, 'legacy ctx must render mROAS column header'
    assert 'CPU' not in html, 'legacy ctx must NOT mention CPU'
    assert '₽/ед.' not in html


def test_legacy_monetary_roi_renders_roi_labels():
    """Explicit kpi=monetary,mode=roi → same backward-compat path."""
    s = _import_sections()
    ctx = _ctx('monetary', 'roi')
    html_table = s['table'](ctx)
    html_glance = s['glance'](ctx)
    html_key = s['key'](ctx)

    assert 'mROAS' in html_table
    assert 'ROI портфеля' in html_key
    assert 'CPU' not in html_table
    assert 'Доля портфеля' not in html_glance


# ───── Count KPI (CPU labels) ──────────────────────────────────────────


def test_count_kpi_action_table_shows_cpu_column():
    s = _import_sections()
    ctx = _ctx('count', 'roi')
    html = s['table'](ctx)
    assert 'CPU' in html, 'count KPI must show CPU column header'
    assert '₽/ед.' in html, 'count KPI must show ₽/ед. unit'
    assert 'mROAS' not in html, 'count KPI must NOT show mROAS'


def test_count_kpi_mroas_section_shows_cpu_chart():
    s = _import_sections()
    ctx = _ctx('count', 'roi')
    html = s['mroas'](ctx)
    assert 'CPU' in html
    assert 'мультипликатор' not in html, 'count KPI: chart title не должен говорить мультипликатор'


def test_count_kpi_key_message_shows_cpu_portfolio():
    s = _import_sections()
    ctx = _ctx('count', 'roi')
    html = s['key'](ctx)
    assert 'CPU портфеля' in html, 'count KPI: key_message portfolio metric = CPU'
    assert 'ROI портфеля' not in html


def test_count_kpi_recommendation_uses_cpu_breakeven_phrase():
    s = _import_sections()
    ctx = _ctx('count', 'roi')
    # Force at least 1 saturated channel - Digital mROAS=0.8 < 1.0
    html = s['recommend'](ctx)
    # «mROAS < 1×» replaced by «CPU > value» phrase
    assert 'mROAS < 1' not in html
    assert 'CPU' in html
    # Impact card label adapted
    assert 'упак / ед.' in html or 'Прогнозный прирост продаж' in html


def test_count_kpi_summary_situation_replaces_weighted_roi():
    s = _import_sections()
    ctx = _ctx('count', 'roi')
    html = s['summary'](ctx)
    assert 'Weighted ROI' not in html
    # narrative_adapter returns wr=0.0125 (units/₽); CPU = 1/wr = 80
    assert 'CPU портфеля' in html


def test_count_kpi_glance_replaces_breakeven_text():
    s = _import_sections()
    ctx = _ctx('count', 'roi')
    # Honest narrative not active by default → standard f1_leader_support path
    html = s['glance'](ctx)
    assert 'CPU' in html
    # f1_leader_support template ROI × replaced by KPI-aware phrase
    assert 'ROI {' not in html  # template format string не должна утечь


# ───── Effectiveness mode (Доля %) ─────────────────────────────────────


def test_effectiveness_mode_action_table_shows_share_column():
    s = _import_sections()
    ctx = _ctx('monetary', 'effectiveness')
    html = s['table'](ctx)
    assert 'Доля эффекта' in html
    assert 'mROAS' not in html
    # Totals row = 100% by construction
    assert '100%' in html or '100' in html


def test_effectiveness_mode_summary_uses_share_phrase():
    s = _import_sections()
    ctx = _ctx('monetary', 'effectiveness')
    html = s['summary'](ctx)
    assert 'Средняя доля каналов в портфеле' in html
    assert 'ROI портфеля' not in html


def test_effectiveness_mode_mroas_section_shows_share_chart():
    s = _import_sections()
    ctx = _ctx('monetary', 'effectiveness')
    html = s['mroas'](ctx)
    assert 'Доля' in html
    assert 'мультипликатор' not in html


def test_effectiveness_mode_recommendation_impact_label():
    s = _import_sections()
    ctx = _ctx('monetary', 'effectiveness')
    html = s['recommend'](ctx)
    assert 'Прогнозный прирост доли' in html
    assert 'Прогнозный ROAS' not in html


# ───── KPI view helper unit tests ──────────────────────────────────────


def test_kpi_view_defaults_when_kpi_block_missing():
    s = _import_sections()
    ctx = {'meta': {}, 'strings': _strings()}
    view = s['view'](ctx)
    assert view['kpi_kind'] == 'monetary'
    assert view['mode'] == 'roi'
    assert view['is_legacy']
    assert view['metric_label'] == 'ROI'
    assert view['target_unit'] == '₽'


def test_kpi_view_reads_labels_from_ctx():
    s = _import_sections()
    ctx = {
        'meta': {}, 'strings': _strings(),
        'kpi': {
            'kpi_kind': 'count', 'derived_mode': 'roi',
            'value_per_count_unit': 80.0,
            'labels': {
                'metric_label': 'CPU, ₽/ед.',
                'metric_short_label': 'CPU',
                'target_unit_label': 'упак',
                'target_axis_label': 'Продажи, упак',
                'methodology_label': '',
            },
        },
    }
    view = s['view'](ctx)
    assert view['kpi_kind'] == 'count'
    assert view['mode'] == 'roi'
    assert not view['is_legacy']
    assert view['metric_short'] == 'CPU'
    assert view['vpcu'] == 80.0


# ───── Metric formatter unit tests ─────────────────────────────────────


def test_fmt_metric_monetary_roi():
    from aurora_html.sections import _fmt_metric, _kpi_view
    ctx = {'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'roi', 'labels': {}}}
    kpi = _kpi_view(ctx)
    assert _fmt_metric(1.5, kpi) == '1.50×'
    assert _fmt_metric(None, kpi) == '-'


def test_fmt_metric_count_inverts_to_cpu():
    """B4 audit fix: c.mroas от backend = units/₽; _fmt_metric inverts → CPU.

    Pre-fix: format showed «X ₽/ед.» literal X - semantically wrong для
    mathematical units/₽ input. Post-fix: invert before display.
    """
    from aurora_html.sections import _fmt_metric, _kpi_view
    ctx = {'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}}
    kpi = _kpi_view(ctx)
    # units/₽ → CPU = 1/x
    assert _fmt_metric(0.0125, kpi) == '80 ₽/ед.'  # 1/0.0125 = 80
    assert _fmt_metric(0.01, kpi) == '100 ₽/ед.'   # 1/0.01 = 100
    # Zero or negative → fallback (canonical no-signal)
    assert _fmt_metric(0, kpi) == '-'
    assert _fmt_metric(-0.5, kpi) == '-'


def test_fmt_metric_effectiveness_fraction():
    from aurora_html.sections import _fmt_metric, _kpi_view
    ctx = {'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness', 'labels': {}}}
    kpi = _kpi_view(ctx)
    # fraction (0..1) → % normalized
    assert _fmt_metric(0.25, kpi) == '25.0%'
    # already percent (>1) → keep as %
    assert _fmt_metric(25, kpi) == '25%'


def test_under_breakeven_phrase_per_mode():
    from aurora_html.sections import _under_breakeven_phrase, _kpi_view
    legacy = _kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'roi', 'labels': {}}})
    count_kpi = _kpi_view({
        'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'value_per_count_unit': 80.0, 'labels': {}}
    })
    eff = _kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness', 'labels': {}}})

    assert _under_breakeven_phrase(legacy) == 'mROAS < 1×'
    assert 'CPU >' in _under_breakeven_phrase(count_kpi)
    assert _under_breakeven_phrase(eff) == 'доля < бенчмарка'


def test_table_metric_header_per_mode():
    from aurora_html.sections import _table_metric_header, _kpi_view
    legacy = _kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'roi', 'labels': {}}})
    count_kpi = _kpi_view({'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}})
    eff = _kpi_view({'kpi': {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness', 'labels': {}}})

    assert _table_metric_header(legacy) == ('mROAS', '×')
    assert _table_metric_header(count_kpi) == ('CPU', '₽/ед.')
    assert _table_metric_header(eff) == ('Доля эффекта', '%')


def test_weighted_summary_phrase_count_inverts_to_cpu():
    from aurora_html.sections import _weighted_summary_phrase, _kpi_view
    count_kpi = _kpi_view({'kpi': {'kpi_kind': 'count', 'derived_mode': 'roi', 'labels': {}}})
    # weighted_roi = 0.0125 units/₽ → CPU = 80 ₽/ед.
    phrase = _weighted_summary_phrase(0.0125, count_kpi)
    assert 'CPU' in phrase
    assert '80' in phrase
    assert '₽/ед.' in phrase
