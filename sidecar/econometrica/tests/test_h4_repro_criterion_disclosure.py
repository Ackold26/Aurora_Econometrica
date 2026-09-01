"""H-4 (внешний аудит 2026-08-16): критерий совпадения двух расчётов считался
движком (`utils/repro_tolerance.py`) и был обёрнут в клиентские витрины
(`engines/methodology_cert.py::строки_критерия_совпадения`/
`пояснение_критерия_совпадения`), но ни разу не печатался клиенту – ни в
HTML-отчёте, ни в PPTX-презентации.

Гейт трёх следствий:
    1. подраздел «Критерий совпадения» есть в HTML-сертификате
       (`aurora_html/sections.py::_render_certificate_block`);
    2. строка «Совпадение расчётов» есть на слайде «Методология» PPTX
       (`aurora_pptx/builder.py::строки_сертификата`);
    3. 🔴 главное – HTML и PPTX называют ОДНУ И ТУ ЖЕ ветвь допуска и ОДНО И ТО
       ЖЕ число на одном и том же сертификате. Оба документа собираются по-
       настоящему (`build_html`/`AuroraPPTXBuilder.build()`), а проверка читает
       текст из готового файла (HTML-строка, распакованный PPTX), а не
       возвращаемое значение функции – ровно то, что увидит клиент.

`engines/methodology_cert.py` этим тестом не покрывается изнутри – модуль
только вызывается, как и в правке рендеров.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.methodology_cert import generate_methodology_certificate  # noqa: E402
from utils.repro_tolerance import FULL_RUN_DRAWS, MODE_STRICT, MODE_TITLES, TOLERANCES  # noqa: E402


def _модель_с_паспортом():
    """Модель с записанным паспортом воспроизводимости: 4 цепи × 2000 = 8000
    итоговых выборок – ровно порог `FULL_RUN_DRAWS`, ветвь допуска детерминирована
    (MODE_STRICT, не MODE_WIDE): числа в тесте не зависят от значения порога."""
    return {
        'model_version': '1.2',
        'kpi_type': 'sales',
        'kpi_likelihood': 'normal',
        'config': {'kpi_type': 'sales', 'kpi_likelihood': 'normal'},
        'channel_params': {'ТВ': {}, 'Диджитал': {}},
        'channel_adstock_types': {'ТВ': 'geometric', 'Диджитал': 'weibull'},
        'diagnostics': {},
        'reproducibility': {
            'seed': 555, 'seed_source': 'config', 'sampler_tier': 'full',
            'mcmc': {'chains': 4, 'draws': FULL_RUN_DRAWS // 4, 'tune': 1000},
            'versions': {'python': '3.11', 'numpy': '1.26', 'pymc': '5.10'},
        },
    }


def _разбивка():
    return {
        'status': 'ok',
        'total_sales': 10000.0,
        'baseline': 6000.0,
        'channels': [
            {'name': 'ТВ', 'contribution': 3000.0, 'roi': 2.5,
             'roi_ci_low': 1.9, 'roi_ci_high': 3.1},
            {'name': 'Диджитал', 'contribution': 1000.0, 'roi': 1.4},
        ],
    }


def _манифест():
    return {
        'format': 'aurora-model',
        'format_version': '1',
        'created_at': '2026-08-17T00:00:00+00:00',
        'array_count': 7,
        'model_version': '1.2',
        'sha256_data': 'a' * 64,
        'sha256_arrays': 'b' * 64,
    }


def _число(значение: float) -> str:
    """Та же логика форматирования, что в `methodology_cert._число` – не
    импортирую приватную функцию, чтобы не завязываться на внутренности модуля,
    который сейчас правит другой исполнитель; повторяю правило независимо."""
    текст = f'{значение:.1f}'.rstrip('0').rstrip('.')
    return текст.replace('.', ',')


@pytest.fixture(scope='module')
def сертификат():
    итог = generate_methodology_certificate(_модель_с_паспортом(), _разбивка(), _манифест())
    assert итог['status'] == 'issued', итог.get('reason')
    репро = итог['repro_tolerance']
    assert репро['status'] == 'declared', репро
    применимая = репро.get('applicable') or {}
    assert применимая.get('mode') == MODE_STRICT, (
        f'фикстура должна давать детерминированную ветвь {MODE_STRICT!r}, '
        f'получено {применимая.get("mode")!r} – проверьте mcmc.chains*draws'
    )
    return итог


ЗАГОЛОВОК_ВЕТВИ = MODE_TITLES[MODE_STRICT]
ЧИСЛО_ДОПУСКА = _число(TOLERANCES[MODE_STRICT]['roi'])


# ── 1. HTML-отчёт ─────────────────────────────────────────────────────────────

def test_критерий_совпадения_в_html_отчёте(сертификат, tmp_path):
    from engines.html_export import build_html

    out = str(tmp_path / 'report.html')
    res = build_html(
        model_data={'diagnostics': {}},
        decompose_data={'methodology_certificate': сертификат},
        optimize_data={},
        output_path=out,
        project_id='h4-test',
    )
    assert res.get('status') == 'ok', res

    html = Path(out).read_text(encoding='utf-8')
    assert 'Критерий совпадения' in html, (
        'подраздел критерия совпадения отсутствует в HTML-сертификате – H-4 не закрыт'
    )
    assert ЗАГОЛОВОК_ВЕТВИ in html, 'ветвь, применимая к расчёту, не названа в отчёте'
    assert f'{ЧИСЛО_ДОПУСКА} %' in html, 'числовой допуск не напечатан в отчёте'


# ── 2. PPTX-презентация ────────────────────────────────────────────────────────

def _pptx_как_текст(prs, out: str) -> str:
    """Распаковать сохранённый .pptx и вернуть весь текст без разметки – то,
    что реально видит клиент, а не то, что вернула функция сборки строк."""
    prs.save(out)
    архив = zipfile.ZipFile(out)
    сырой = ' '.join(
        архив.read(имя).decode('utf-8', 'ignore')
        for имя in архив.namelist() if имя.endswith('.xml')
    )
    return re.sub(r'<[^>]+>', ' ', сырой)


def test_критерий_совпадения_на_слайде_pptx(сертификат, tmp_path):
    from aurora_pptx.builder import AuroraPPTXBuilder
    from engines.narrative_adapter import _map_pipeline_to_builder_data

    decompose_data = {
        'channels': _разбивка()['channels'],
        'methodology_certificate': сертификат,
    }
    payload = _map_pipeline_to_builder_data(
        model_data={'diagnostics': {}}, decompose_data=decompose_data,
        optimize_data={}, scenarios=[], project_id='h4-test',
    )
    assert payload.get('certificate', {}).get('hash') == сертификат['hash'], (
        'презентация получила не тот сертификат, что построен в тесте'
    )

    prs = AuroraPPTXBuilder(payload).build()
    текст = _pptx_как_текст(prs, str(tmp_path / 'report.pptx'))

    assert 'Совпадение расчётов' in текст, (
        'строка критерия совпадения отсутствует на слайде «Методология» – H-4 не закрыт'
    )
    assert ЗАГОЛОВОК_ВЕТВИ in текст, 'ветвь, применимая к расчёту, не названа на слайде'
    assert f'до {ЧИСЛО_ДОПУСКА} %' in текст, 'числовой допуск не напечатан на слайде'


# ── 3. Главное: HTML и PPTX согласны друг с другом, не только с константой ────

def _число_рядом_с_веткой(текст: str, заголовок: str) -> str:
    """Число допуска, напечатанное рядом с названием ветви – читаем из текста
    документа, а не пересчитываем: тест обязан сверять то, что показано клиенту."""
    совпадение = re.search(
        re.escape(заголовок) + r'.{0,200}?(\d+(?:,\d+)?)\s*%', текст, re.S,
    )
    assert совпадение, (
        f'рядом с веткой «{заголовок}» не нашлось числа допуска в пределах 200 символов'
    )
    return совпадение.group(1)


def test_html_и_pptx_показывают_одну_и_ту_же_ветвь_и_число(сертификат, tmp_path):
    """🔴 Риск, названный в разведке (Projects/PULSE_h4h5_recon_2026-08-17.md):
    HTML и PPTX читают критерий из одного `cert['repro_tolerance']`, но каждый –
    своей веткой кода (`подробно=True` в отчёте, `подробно=False` на слайде).
    Совпадение чисел проверяем на артефактах, а не на исходном коде: расхождение
    здесь означало бы, что отчёт и презентация одного расчёта спорят между собой.
    """
    from engines.html_export import build_html
    from aurora_pptx.builder import AuroraPPTXBuilder
    from engines.narrative_adapter import _map_pipeline_to_builder_data

    html_out = str(tmp_path / 'report_cmp.html')
    build_html(
        model_data={'diagnostics': {}},
        decompose_data={'methodology_certificate': сертификат},
        optimize_data={}, output_path=html_out, project_id='h4-test',
    )
    html = Path(html_out).read_text(encoding='utf-8')

    payload = _map_pipeline_to_builder_data(
        model_data={'diagnostics': {}},
        decompose_data={'channels': _разбивка()['channels'], 'methodology_certificate': сертификат},
        optimize_data={}, scenarios=[], project_id='h4-test',
    )
    prs = AuroraPPTXBuilder(payload).build()
    pptx_текст = _pptx_как_текст(prs, str(tmp_path / 'report_cmp.pptx'))

    число_html = _число_рядом_с_веткой(html, ЗАГОЛОВОК_ВЕТВИ)
    число_pptx = _число_рядом_с_веткой(pptx_текст, ЗАГОЛОВОК_ВЕТВИ)
    assert число_html == число_pptx, (
        f'HTML называет допуск {число_html} %, PPTX – {число_pptx} % '
        f'для одной и той же ветви «{ЗАГОЛОВОК_ВЕТВИ}» одного сертификата'
    )
    assert число_html == ЧИСЛО_ДОПУСКА
