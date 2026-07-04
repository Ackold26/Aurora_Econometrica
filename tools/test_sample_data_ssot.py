"""
SSOT gate для customer-facing sample-data (static/sample-data/synth_*.xlsx).

Анти-дрейф (2026-06-07): шаблоны спроектировали 6 июня, примеры не перегенерили →
3 расходящихся артефакта + колонки, которые собственный авто-детект программы не
распознаёт (ooh `*_ots`, macro `mortgage`, `seasonality_*`) + reference-leak дубли
(avg_temp ≡ -weather_temp_low; macro_cpi_cumulative ≡ cumprod(monthly)), раздувающие
номинальные параметры → бьющие по честному MQS. Этот гейт фиксирует контракт, чтобы
дрейф ловился в CI, а не у клиента в «Попробовать на примере».

Контракт на каждый served sample:
  1. Каждая колонка распознаётся классификатором (classify_column ≠ 'unknown')
     и роль ровно та, что задумана (EXPECTED_SCHEMA).
  2. N ≥ 36 (monthly) — статистически достаточно для adstock+Hill+контролей.
  3. Нет функционально-зависимых / коллинеарных пар (|corr| < 0.95) и нет
     известных reference-leak колонок (FORBIDDEN_COLUMNS).
  4. KPI не плоский (spread ≥ 12%) — декомпозиция будет не пустой.

NB: критерии 4/5 acceptance (ground-truth recovery + MQS-бэнд) требуют фита MMM —
они в tools/validate_sample_data.py (медленный harness), не в этом быстром гейте.
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest

_REPO = Path(__file__).resolve().parent.parent
_SIDECAR = _REPO / 'sidecar' / 'econometrica'
if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

from utils.column_detection import classify_column  # noqa: E402

SAMPLE_DIR = _REPO / 'static' / 'sample-data'

# Канонический SSOT-контракт: {файл: {колонка: ожидаемая роль}}.
# Менять ТОЛЬКО синхронно с tools/synthetic_pilot_data.py + шаблонами в
# src-tauri/help-econometrica/ (один источник истины на категорию).
EXPECTED_SCHEMA = {
    'synth_fmcg_brand.xlsx': {
        'date': 'date',
        'sales_rub': 'target_monetary',
        'tv_spend': 'monetary',           'tv_trp': 'physical',
        'digital_spend': 'monetary',      'digital_impressions': 'physical',
        'ooh_spend': 'monetary',          'ooh_contacts': 'physical',
        'performance_spend': 'monetary',  'performance_clicks': 'physical',
        'competitor_trp': 'signed_competitor',
        'price_index': 'signed_price',
        'category_sales': 'category',
    },
    'synth_otc_pharma.xlsx': {
        'date': 'date',
        'sales_packs': 'target_count',
        'tv_spend': 'monetary',           'tv_trp': 'physical',
        'apteka_spend': 'monetary',       'apteka_contacts': 'physical',
        'digital_spend': 'monetary',      'digital_impressions': 'physical',
        'performance_spend': 'monetary',  'performance_clicks': 'physical',
        'competitor_trp': 'signed_competitor',
        'weather_temp_low': 'signed_weather',
        'category_sales': 'category',
    },
    'synth_retail_ecom.xlsx': {
        'date': 'date',
        'sales_rub': 'target_monetary',
        'tv_spend': 'monetary',            'tv_trp': 'physical',
        'digital_spend': 'monetary',       'digital_impressions': 'physical',
        'ooh_spend': 'monetary',           'ooh_contacts': 'physical',
        'retail_media_spend': 'monetary',  'retail_media_impressions': 'physical',
        'promo_indicator': 'control',
        'competitor_promo': 'signed_competitor',
        'holiday_blackfriday': 'holiday',
    },
    'synth_real_estate.xlsx': {
        'date': 'date',
        'leads': 'target_count',
        'tv_spend': 'monetary',           'tv_grp': 'physical',
        'ooh_spend': 'monetary',          'ooh_contacts': 'physical',
        'digital_spend': 'monetary',      'digital_impressions': 'physical',
        'performance_spend': 'monetary',  'performance_clicks': 'physical',
        'competitor_activity': 'signed_competitor',
        'macro_cpi': 'signed_macro',
    },
}

# ПАРЫ spend↔natural (решение Антона 2026-07-05): канал несёт бюджет И Media KPI,
# чтобы юзер мог пройти обе модели (ROI / Эффективность). Пара by-design сильно
# коррелирована (spend = physical × CPP_t) — исключается из анти-коллинеарной
# проверки; в МОДЕЛЬ одновременно идёт одна колонка пары (под-шаг «Метрики каналов»).
PAIRED_COLUMNS = {
    'synth_fmcg_brand.xlsx': [
        ('tv_spend', 'tv_trp'), ('digital_spend', 'digital_impressions'),
        ('ooh_spend', 'ooh_contacts'), ('performance_spend', 'performance_clicks'),
    ],
    'synth_otc_pharma.xlsx': [
        ('tv_spend', 'tv_trp'), ('apteka_spend', 'apteka_contacts'),
        ('digital_spend', 'digital_impressions'), ('performance_spend', 'performance_clicks'),
    ],
    'synth_retail_ecom.xlsx': [
        ('tv_spend', 'tv_trp'), ('digital_spend', 'digital_impressions'),
        ('ooh_spend', 'ooh_contacts'), ('retail_media_spend', 'retail_media_impressions'),
    ],
    'synth_real_estate.xlsx': [
        ('tv_spend', 'tv_grp'), ('ooh_spend', 'ooh_contacts'),
        ('digital_spend', 'digital_impressions'), ('performance_spend', 'performance_clicks'),
    ],
}

# Reference-leak / устаревшие имена, которые НЕ должны вернуться в sample-data.
FORBIDDEN_COLUMNS = {
    'avg_temp',                # ≡ -weather_temp_low (коллинеар)
    'macro_cpi_monthly',       # парный с cumulative
    'macro_cpi_cumulative',    # ≡ cumprod(macro_cpi_monthly)
    'seasonality_q1', 'seasonality_q4', 'seasonality_flu', 'seasonality',
    'ooh_ots', 'apteka_ooh_ots',   # 'ots' не распознаётся → unknown
    'macro_mortgage_rate',     # 'mortgage' не распознаётся → unknown
    'traffic_visits',          # старый retail-chain KPI (заменён на sales_rub e-com)
    'holiday_newyear',         # НГ теперь авто (holiday_calendar_ru); ручная dummy = двойной учёт
}

MIN_ROWS = 36
MAX_PAIR_CORR = 0.95
MIN_KPI_SPREAD = 0.12

# SSOT: каждый пример имеет парный пустой шаблон с ТЕМИ ЖЕ колонками.
TEMPLATE_DIR = _REPO / 'src-tauri' / 'help-econometrica'
TEMPLATE_FILES = {
    'synth_fmcg_brand.xlsx': 'template_fmcg.xlsx',
    'synth_otc_pharma.xlsx': 'template_pharma_otc.xlsx',
    'synth_retail_ecom.xlsx': 'template_retail_ecom.xlsx',
    'synth_real_estate.xlsx': 'template_realestate_b2b.xlsx',
}


def _load(path: Path):
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = [r for r in ws.iter_rows(values_only=True)]
    header = list(rows[0])
    data = [r for r in rows[1:] if any(c is not None for c in r)]
    return header, data


def _corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    return cov / (va * vb) if va and vb else 0.0


@pytest.mark.parametrize('fname', sorted(EXPECTED_SCHEMA))
def test_sample_exists(fname):
    assert (SAMPLE_DIR / fname).exists(), f'Missing served sample {fname} — run tools/synthetic_pilot_data.py'


@pytest.mark.parametrize('fname', sorted(EXPECTED_SCHEMA))
def test_columns_recognized_and_correct_role(fname):
    header, _ = _load(SAMPLE_DIR / fname)
    expected = EXPECTED_SCHEMA[fname]
    assert set(header) == set(expected), (
        f'{fname}: schema drift. got={header} expected={list(expected)}'
    )
    wrong = {c: classify_column(c) for c in header if classify_column(c) != expected[c]}
    assert not wrong, f'{fname}: columns mis-detected by program classifier: {wrong}'


@pytest.mark.parametrize('fname', sorted(EXPECTED_SCHEMA))
def test_no_forbidden_columns(fname):
    header, _ = _load(SAMPLE_DIR / fname)
    bad = FORBIDDEN_COLUMNS & set(header)
    assert not bad, f'{fname}: forbidden reference-leak/unrecognized columns present: {bad}'


@pytest.mark.parametrize('fname', sorted(EXPECTED_SCHEMA))
def test_min_rows(fname):
    _, data = _load(SAMPLE_DIR / fname)
    assert len(data) >= MIN_ROWS, f'{fname}: N={len(data)} < {MIN_ROWS}'


@pytest.mark.parametrize('fname', sorted(EXPECTED_SCHEMA))
def test_no_collinear_pairs(fname):
    header, data = _load(SAMPLE_DIR / fname)
    numidx = [i for i in range(len(header))
              if all(isinstance(r[i], (int, float)) for r in data)]
    offenders = []
    for ii in range(len(numidx)):
        for jj in range(ii + 1, len(numidx)):
            i, j = numidx[ii], numidx[jj]
            a, b = header[i], header[j]
            declared = {frozenset(p) for p in PAIRED_COLUMNS.get(fname, [])}
            if frozenset((a, b)) in declared:
                continue  # пара spend↔natural одного канала — коллинеарна by design
            c = _corr([r[i] for r in data], [r[j] for r in data])
            if abs(c) >= MAX_PAIR_CORR:
                offenders.append((a, b, round(c, 3)))
    assert not offenders, f'{fname}: functionally-dependent/collinear pairs: {offenders}'


@pytest.mark.parametrize('fname', sorted(EXPECTED_SCHEMA))
def test_kpi_not_flat(fname):
    _, data = _load(SAMPLE_DIR / fname)
    kpi = [r[1] for r in data]  # col index 1 = KPI by SSOT convention
    spread = (max(kpi) - min(kpi)) / (sum(kpi) / len(kpi))
    assert spread >= MIN_KPI_SPREAD, f'{fname}: KPI spread {spread:.1%} < {MIN_KPI_SPREAD:.0%} (flat)'


@pytest.mark.parametrize('fname', sorted(EXPECTED_SCHEMA))
def test_template_matches_sample_columns(fname):
    """SSOT: пустой шаблон и заполненный пример имеют ОДИН набор колонок (анти-дрейф F1)."""
    sample_cols, _ = _load(SAMPLE_DIR / fname)
    tpl_cols, _ = _load(TEMPLATE_DIR / TEMPLATE_FILES[fname])
    assert set(tpl_cols) == set(sample_cols), (
        f'{fname}: template {TEMPLATE_FILES[fname]} != sample columns (SSOT drift). '
        f'template_only={set(tpl_cols) - set(sample_cols)} '
        f'sample_only={set(sample_cols) - set(tpl_cols)}'
    )


@pytest.mark.parametrize('fname', sorted(EXPECTED_SCHEMA))
def test_served_file_matches_generator(fname):
    """Served xlsx == свежий вывод генератора (ловит stale/ручной дрейф served-файла, F2)."""
    import importlib
    tools_dir = str(_REPO / 'tools')
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    gen = importlib.import_module('synthetic_pilot_data')
    genfn = {f'{n}.xlsx': fn for n, fn in gen.GENERATORS}[fname]
    df_fresh = genfn()
    header, data = _load(SAMPLE_DIR / fname)
    assert list(df_fresh.columns) == header, (
        f'{fname}: served columns != generator (регенерируй: python tools/synthetic_pilot_data.py)'
    )
    import numpy as np
    fresh = df_fresh.drop(columns=['date']).to_numpy(dtype=float)
    disk = np.array([[r[i] for i in range(1, len(header))] for r in data], dtype=float)
    assert fresh.shape == disk.shape, f'{fname}: shape mismatch served vs generator'
    maxrel = float(np.max(np.abs(fresh - disk) / (np.abs(disk) + 1e-9)))
    assert maxrel < 1e-6, (
        f'{fname}: served file != generator output (max rel diff {maxrel:.2e}) — регенерируй'
    )
