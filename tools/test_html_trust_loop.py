"""E1-E4 HTML (2026-07-04): секция «Петля доверия» в интерактивном отчёте.

Контракт: без живых артефактов секции НЕТ (и пункта в TOC нет); с ними —
все четыре под-блока с честными строками (включая расхождение калибровки
и «не сбылось»), 0 wireframe-маркеров.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_goalseek_honesty import _build_project  # noqa: E402
from test_pptx_backtest_slide import (  # noqa: E402
    _backtest_fixture,
    _gen_compare_fixture,
)
from test_report_fidelity_live import WIREFRAME_MARKERS  # noqa: E402


@pytest.fixture(scope='module')
def html_pair(tmp_path_factory):
    """Два HTML: без артефактов петли и со всеми четырьмя."""
    tmp = tmp_path_factory.mktemp('html_trust')
    pdir = _build_project(tmp, 'trust', beta_sd=0.2, seed=7)

    from engines.decomposer import decompose
    from engines.optimizer import optimize
    dec = decompose(str(pdir), save_results=False)
    assert dec.get('status') != 'error', dec.get('message')
    dec = dict(dec)
    dec.setdefault('project_dir', str(pdir))
    opt = optimize({'min_pct': 0.0, 'max_pct': 100.0}, str(pdir))
    assert opt.get('status', 'ok') != 'error', opt.get('message')

    model_data = {'diagnostics': {
        'metrics': {'r_squared': 0.81, 'mape_pct': 12.3, 'r_hat_max': 1.004,
                    'ess_bulk_min': 812.0, 'ess_tail_min': 640.0},
        'mqs': {'score': 71.0, 'tier_label': 'Хорошее'},
        'checks': {},
    }}
    model_calib = json.loads(json.dumps(model_data))
    ch_name = (dec.get('channels') or [{}])[0].get('name')
    model_calib['diagnostics']['calibration_applied'] = [{
        'channel': ch_name, 'test_type': 'geo_lift',
        'date_from': '2026-01-01', 'date_to': '2026-03-01', 'lift_abs': 500.0,
    }]
    model_calib['diagnostics']['calibration_check'] = [{
        'channel': ch_name, 'test_type': 'geo_lift',
        'date_from': '2026-01-01', 'date_to': '2026-03-01',
        'test_lift': 500.0, 'test_sigma': 60.0,
        'model_contrib_mean': 320.0, 'model_contrib_ci90': [280.0, 360.0],
        'within_ci': False,
    }]
    promises = [
        {'status': 'kept', 'status_ru': 'сбылось',
         'action_text': 'Бюджет 12 000 000 ₽ на Q3', 'verdict_note': 'Факт в интервале.'},
        {'status': 'missed', 'status_ru': 'не сбылось',
         'action_text': 'Сдвиг 10% в TV', 'verdict_note': 'Факт вне интервала.'},
    ]

    from engines.html_export import build_html
    bare = str(tmp / 'bare.html')
    r1 = build_html(model_data, dec, opt, bare, scenarios=[], project_id='trust_t')
    assert r1.get('status') == 'ok', r1.get('message')

    full = str(tmp / 'full.html')
    r2 = build_html(
        model_calib, dec, opt, full, scenarios=[], project_id='trust_t',
        backtest=_backtest_fixture(),
        generation_compare=_gen_compare_fixture(),
        promises=promises,
    )
    assert r2.get('status') == 'ok', r2.get('message')

    return (Path(bare).read_text(encoding='utf-8'),
            Path(full).read_text(encoding='utf-8'))


def test_bare_html_has_no_trust_section(html_pair):
    bare, _ = html_pair
    assert '<section id="trust"' not in bare
    assert 'data-toc-target="trust"' not in bare, 'пункт TOC не должен вести в пустоту'
    # NB: сырая строка «Петля доверия» допустима в инлайновом strings-JSON
    # (весь словарь секций уходит в JS) — контракт именно про рендер и TOC.


def test_full_html_has_all_four_blocks(html_pair):
    _, full = html_pair
    assert '<section id="trust"' in full
    assert 'data-toc-target="trust"' in full
    # E1: витрина
    assert 'Проверка на истории' in full
    assert '4 из 4 кварталов' in full
    # E3: сравнение поколений (headline с CI)
    assert 'Что изменилось с прошлого квартала' in full
    assert 'был 3.2 [2.6–3.9]' in full
    assert 'резкий сдвиг' in full
    # E2: калибровка + честное расхождение
    assert 'откалиброван тестом' in full
    assert 'Модель и тест расходятся' in full
    # E4: сбывшиеся с честным «не сбылось»
    assert 'Сбылось 1 · не сбылось 1' in full
    assert 'не сбылось' in full


def test_full_html_no_wireframe_markers(html_pair):
    _, full = html_pair
    leaked = [m for m in WIREFRAME_MARKERS if m in full]
    assert not leaked, f'Wireframe в HTML: {leaked}'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
