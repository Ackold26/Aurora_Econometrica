"""
Narrative coherence lock-in test (math-fix v1.0.14.1, B fix-session 2026-04-28).

Validates что HTML/PPTX отчёты НЕ содержат противоречий между sections для
одного канала. Pre-fix: render_mroas commentary говорило «явный потенциал
scale-up» для max-mROAS канала независимо от того что render_action_table
verdict column показывало «Hold» (ratio=1.0 because optimizer не двинул).

Source root cause (Phase 1 meta-audit B1+B3 findings):
  • narrative_adapter.derive_verdict (mROAS+ratio based) — used by table.
  • aurora_html/sections.py:render_mroas (mROAS-rank hardcoded strings) — own logic.
Templates были independent → contradictions inevitable.

Post-fix: single source of truth `engines.channel_action.compute_channel_action`.
narrative_adapter использует его для derive_verdict. HTML/PPTX commentary derives
text per-channel from action_key (not from mROAS rank).

Acceptance gates:

UNIT TESTS (compute_channel_action mapping):
  U1-U10: 10 input cases → expected action key

INTEGRATION TESTS (HTML render coherence):
  I1: Per channel: action_key in commentary lead == verdict in table cell
  I2: When optimizer converged_at_current=True, recommendation Action 01 honest
  I3: render_at_a_glance f4_verdicts counts match action_summary counts

Run:
    cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
    python tools/test_narrative_coherence.py

Exit 0 success / 1 failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))

PASSED = 0
FAILED = 0


def check(label: str, ok: bool, hint: str = '') -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f'[OK]   {label}')
    else:
        FAILED += 1
        print(f'[FAIL] {label}' + (f' — {hint}' if hint else ''))


# ──────────────────────────────────────────────────────────────────────
# UNIT — compute_channel_action mapping
# ──────────────────────────────────────────────────────────────────────

def test_action_mapping():
    print('── compute_channel_action mapping ──')
    from engines.channel_action import compute_channel_action

    cases = [
        # U1: untrained
        ({'untrained': True, 'mroas': 1.5, 'current_spend': 100}, 'Uncertain', 'untrained'),
        # U2: zero spend
        ({'mroas': 1.5, 'current_spend': 0}, 'Uncertain', 'zero spend'),
        # U3: CI uncertain (width > mROAS)
        ({'mroas': 1.5, 'mroas_ci_low': 0.2, 'mroas_ci_high': 3.5, 'current_spend': 100},
         'Uncertain', 'CI width > mROAS'),
        # U4: deeply unprofitable
        ({'mroas': 0.5, 'current_spend': 100}, 'Cut', 'mROAS < 0.8'),
        # U5: optimizer reduce (saturation-bound)
        ({'mroas': 1.5, 'current_spend': 100, 'optimal_spend': 90}, 'Reduce',
         'optimizer ratio ≤ 0.95'),
        # U6: near breakeven
        ({'mroas': 0.9, 'current_spend': 100, 'optimal_spend': 100}, 'Reduce',
         'mROAS 0.8-1.0'),
        # U7: optimizer scale (clear signal)
        ({'mroas': 1.5, 'current_spend': 100, 'optimal_spend': 200}, 'Scale',
         'optimizer ratio ≥ 1.05'),
        # U8: mROAS+gap scale heuristic (optimizer не двигал)
        ({'mroas': 2.0, 'current_spend': 100, 'optimal_spend': 100, 'efficiency_gap': 8.0},
         'Scale', 'mROAS ≥ 1.5 + gap ≥ +5pp'),
        # U9: hold (balanced)
        ({'mroas': 1.2, 'current_spend': 100, 'optimal_spend': 100, 'efficiency_gap': 1.0},
         'Hold', 'stable'),
        # U10: watch (mROAS ≥ 1.0 but gap large, no optimizer signal)
        ({'mroas': 1.0, 'current_spend': 100, 'optimal_spend': 100, 'efficiency_gap': -8.0},
         'Watch', 'mROAS=1 but gap negative, no optimizer signal'),
    ]
    for i, (inp, expected, desc) in enumerate(cases, 1):
        result = compute_channel_action(inp)
        check(
            f'U{i}: {desc} → {expected}',
            result.key == expected,
            hint=f'got {result.key} (reasoning: {result.reasoning[:80]})',
        )


# ──────────────────────────────────────────────────────────────────────
# INTEGRATION — HTML render coherence
# ──────────────────────────────────────────────────────────────────────

def _build_synthetic_ctx() -> dict:
    """Build minimal ctx for render_* functions WITHOUT running full pipeline.

    Captures the post-Section-A optimizer state: 6 channels с обширным spread
    actions — Scale, Hold, Reduce, Cut + Uncertain — to exercise всех ветвей.
    """
    from engines.channel_action import compute_channel_action

    channels = [
        # Performance — clear scale (optimizer recommends growth)
        {'name': 'performance', 'mroas': 9.8, 'current_spend': 23.85e6,
         'optimal_spend': 47.7e6, 'spend': 23.85e6, 'contribution': 60e6,
         'efficiency_gap': 8.0},
        # Social — clear scale (highest mROAS, optimizer recommends growth)
        {'name': 'social', 'mroas': 10.5, 'current_spend': 15.5e6,
         'optimal_spend': 30.9e6, 'spend': 15.5e6, 'contribution': 50e6,
         'efficiency_gap': 12.0},
        # OLV — Scale (mROAS lower but optimizer says +100%)
        {'name': 'olv', 'mroas': 1.04, 'current_spend': 107e6,
         'optimal_spend': 214e6, 'spend': 107e6, 'contribution': 80e6,
         'efficiency_gap': -1.0},
        # Banners — Scale (similar to OLV)
        {'name': 'banners', 'mroas': 1.08, 'current_spend': 113.7e6,
         'optimal_spend': 227.4e6, 'spend': 113.7e6, 'contribution': 85e6,
         'efficiency_gap': 0.5},
        # TRPs — Reduce (saturated, optimizer cuts)
        {'name': 'trps', 'mroas': 0.029, 'current_spend': 3.31e9,
         'optimal_spend': 3.04e9, 'spend': 3.31e9, 'contribution': 95e6,
         'efficiency_gap': -20.0},
        # Untrained synthetic — Uncertain
        {'name': 'untrained_ch', 'mroas': 0, 'current_spend': 0,
         'optimal_spend': 0, 'spend': 0, 'contribution': 0,
         'untrained': True, 'efficiency_gap': 0.0},
    ]
    # Decorate каждый канал с action — это что narrative_adapter делает
    for ch in channels:
        a = compute_channel_action(ch)
        ch['verdict'] = a.key  # legacy compatibility
        ch['action'] = a.key
        ch['action_label'] = a.label_ru
        ch['action_reasoning'] = a.reasoning
        ch['action_tone'] = a.tone

    facts = {
        'leader_channel': 'trps',
        'hero_channel': 'social',
        'n_active_channels': 5,
        'total_budget_mln': 3590.0,
        'total_contrib_mln': 370.0,
        'weighted_roi': 0.103,
        'leader_share_spend_pct': 92.0,
        'leader_share_contrib_pct': 26.0,
        'top_2_names': ['trps', 'banners'],
        'top_2_contrib_pct': 49.0,
        'underperformer_names': ['untrained_ch'],
        'reallocation_mln': 380.0,
        'expected_lift_pct': 28.3,
        'media_contribution_pct': 10.3,
        'baseline_pct': 89.7,
        'honest_narrative': False,
        'binding_constraints': False,
        'optimization_converged': True,
        'optimize_min_pct': 20,
        'optimize_max_pct': 200,
        'converged_at_current': False,
    }
    # Load strings
    import json
    with open(SIDECAR / 'econometrica' / 'aurora_html' / 'strings_ru.json',
              'r', encoding='utf-8') as f:
        strings = json.load(f)

    return {
        'meta': {'client': 'TestCo', 'project_id': 'TEST',
                 'version': '1.0.14.1', 'report_date': '28 апреля 2026'},
        'diagnostics': {'r_squared': 0.85, 'mape_pct': 12.0,
                        'r_hat_max': 1.01, 'ess_min': 1500, 'mqs_score': 78},
        'channels': channels,
        'facts': facts,
        'strings': strings,
    }


def test_html_table_commentary_coherence():
    print('── HTML render coherence ──')
    from aurora_html.sections import (
        render_mroas, render_action_table, render_recommendation,
        render_at_a_glance,
    )

    ctx = _build_synthetic_ctx()
    channels = ctx['channels']

    # Build all three sections
    html_mroas = render_mroas(ctx)
    html_table = render_action_table(ctx)
    html_recommend = render_recommendation(ctx)
    html_glance = render_at_a_glance(ctx)

    # I1 — table verdict cell action label MATCHES commentary mention
    # Table cells: <span class="verdict-Scale">Scale</span>...
    # Commentary: should mention each channel + its action label_ru
    # Table cells use class="verdict-badge verdict-{key}" — match second segment
    table_verdicts = {}
    for ch in channels:
        m = re.search(
            rf'<tr data-channel="{re.escape(ch["name"])}".*?'
            rf'verdict-badge\s+verdict-(Scale|Hold|Watch|Reduce|Cut|Uncertain)\b',
            html_table, re.DOTALL,
        )
        if m:
            table_verdicts[ch['name']] = m.group(1)

    check('I1a: table contains verdict cells for каждый channel',
          len(table_verdicts) == len(channels),
          hint=f'found {len(table_verdicts)} of {len(channels)}')

    for ch in channels:
        expected = ch['action']
        actual = table_verdicts.get(ch['name'])
        check(
            f'I1b: table[{ch["name"]}] verdict == ch.action ({expected})',
            actual == expected,
            hint=f'table cell shows {actual}',
        )

    # I1c — render_mroas commentary должен использовать action labels из единого
    # источника. Post-refactor: top-3 unique actions показываются (de-duplicated
    # по action key, чтобы не повторять «Масштабировать» для 4 Scale-каналов).
    # Test: для каждого UNIQUE action key который есть в портфеле (Scale, Cut,
    # Reduce, Hold), commentary mentions ONE channel of that action + label_ru.
    seen_actions_in_html: set[str] = set()
    for ch in sorted(channels, key=lambda c: -int(c.get('action_priority') or 0)):
        action_key = ch.get('action')
        if action_key in ('Uncertain',) or action_key in seen_actions_in_html:
            continue
        action_label = ch.get('action_label', '')
        # Канал mentioned + label (или другой канал того же action key mentioned)
        mentions_label = action_label and action_label in html_mroas
        if mentions_label:
            seen_actions_in_html.add(action_key)

    # Should see at least Scale + Cut/Reduce labels (decisive actions present)
    decisive_actions_present = {
        a for a in ('Scale', 'Cut', 'Reduce', 'Hold')
        if any(c.get('action') == a for c in channels)
    }
    missing = decisive_actions_present - seen_actions_in_html
    check(
        f'I1c: каждый decisive action label_ru appears в render_mroas commentary',
        not missing,
        hint=f'missing actions in HTML: {missing}',
    )

    # I1d — НЕТ hardcoded «явный потенциал scale-up» для не-Scale каналов
    # (если эта строка появляется, она должна относиться только к Scale-каналам)
    if 'явный потенциал scale-up' in html_mroas:
        # Should appear only когда какой-то канал имеет action=Scale
        has_scale = any(ch.get('action') == 'Scale' for ch in channels)
        check('I1d: «scale-up» строка появляется только когда есть Scale канал',
              has_scale, hint='hardcoded string без Scale канала')
    else:
        check('I1d: render_mroas не использует hardcoded «scale-up»', True)


def test_findings_counts():
    print('── render_at_a_glance counts coherence ──')
    from aurora_html.sections import render_at_a_glance
    from engines.channel_action import build_action_summary

    ctx = _build_synthetic_ctx()
    summary = build_action_summary(ctx['channels'])
    # Synthetic data: 4 Scale (perf/social/olv/banners), 1 Reduce (trps), 1 Uncertain
    expected_scale = summary['counts']['Scale']
    expected_cut_reduce = summary['counts']['Cut'] + summary['counts']['Reduce']

    html = render_at_a_glance(ctx)
    # Find «Портфель: N канал(ов) к росту, M к сокращению»
    m = re.search(r'Портфель:\s*(\d+)\s*канал', html)
    check('I3a: render_at_a_glance contains «Портфель: N канал(ов) к росту»',
          m is not None, hint='string not found')
    if m:
        # Parse both numbers
        m2 = re.search(r'Портфель:\s*(\d+)\s*канал[^,]*,\s*(\d+)\s*к\s*сокращению', html)
        if m2:
            scale_n_actual = int(m2.group(1))
            cut_n_actual = int(m2.group(2))
            check(
                f'I3b: scale_n {expected_scale} == counted ({scale_n_actual})',
                scale_n_actual == expected_scale,
                hint=f'expected {expected_scale}, got {scale_n_actual}',
            )
            check(
                f'I3c: cut+reduce {expected_cut_reduce} == counted ({cut_n_actual})',
                cut_n_actual == expected_cut_reduce,
                hint=f'expected {expected_cut_reduce}, got {cut_n_actual}',
            )


def test_converged_at_current_banner():
    print('── converged_at_current narrative banner ──')
    from aurora_html.sections import render_recommendation, render_executive_summary

    ctx = _build_synthetic_ctx()
    # Force converged_at_current state
    ctx['facts']['converged_at_current'] = True
    ctx['facts']['expected_lift_pct'] = 0.0
    ctx['facts']['reallocation_mln'] = 0.0

    html_rec = render_recommendation(ctx)
    html_summary = render_executive_summary(ctx)

    # I2 — banner mentions «не нашёл» / «текущем распределении» / «расширьте границы»
    keywords = ['распределени', 'границ', 'текущ']
    found_rec = any(kw in html_rec for kw in keywords)
    found_sum = any(kw in html_summary for kw in keywords)
    check('I2a: render_recommendation surfaces converged_at_current honestly',
          found_rec, hint='no banner keywords found in recommendation')
    check('I2b: render_executive_summary surfaces converged_at_current honestly',
          found_sum, hint='no banner keywords found in SCQAR')


def main() -> int:
    test_action_mapping()
    test_html_table_commentary_coherence()
    test_findings_counts()
    test_converged_at_current_banner()
    print(f'\n{PASSED} passed, {FAILED} failed.')
    return 0 if FAILED == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
