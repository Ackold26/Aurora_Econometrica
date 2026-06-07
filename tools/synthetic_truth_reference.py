"""
Synthetic-truth REFERENCE — независимый «второй аудитор» для проверки честности движка.

Зачем: в аудите числовой честности самый вероятный лжец — аудитор (я мог посчитать
истину неверно → ложно обвинить/оправдать движок). Поэтому ожидаемую истину выводим
ДВУМЯ независимыми способами и держим движок ТОЛЬКО к тому, на чём оба согласны:

  Способ 1 (аналитический): знаки/доминирование, заложенные в data-generating process
           (GROUND_TRUTH_* из synthetic_pilot_data.py).
  Способ 2 (эмпирический): мой СОБСТВЕННЫЙ OLS-референс на РЕАЛЬНОМ файле с диска
           (независим от движка), в двух вариантах:
             A. naive   — z-score сырых колонок (без adstock/hill);
             B. dgp-xform — истинные adstock(decay)+hill(alpha,gamma=0.6) на медиа,
                            z-score контролей. «Оракульные» трансформы → лучший случай
                            восстановимости знака.

Робастная истина = знак контроля, на котором GROUND_TRUTH И OLS (хотя бы dgp-xform,
значимо) СОГЛАСНЫ. Где не согласны (конфаундинг / опущенная переменная / слабый сигнал)
— истина НЕ восстановима из датасета → движок за «неправильный» знак обвинять НЕЛЬЗЯ.

Запуск:  python tools/synthetic_truth_reference.py [otc|fmcg|retail|real_estate|all]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import synthetic_pilot_data as gen  # noqa: E402

PILOTS = Path(__file__).parent / 'synthetic_pilots'
GAMMA_MID = 0.6

# Конфиг каждого датасета: target, media (decay,alpha из GROUND_TRUTH), controls (coef, kind).
DATASETS = {
    'otc': {
        'file': 'synth_otc_pharma.xlsx',
        'generator': 'generate_otc_pharma',
        'gt': 'GROUND_TRUTH_OTC_PHARMA',
        'target': 'sales_packs',
        'media': {
            'tv_trp': ('tv_decay', 'tv_alpha'),
            'apteka_ooh_contacts': ('apteka_ooh_decay', 'apteka_ooh_alpha'),
            'digital_spend': ('digital_decay', 'digital_alpha'),
            'performance_clicks': ('performance_decay', 'performance_alpha'),
        },
        'controls': {
            'competitor_trp': ('competitor_coef', 'signed_competitor'),
            'weather_temp_low': ('weather_temp_low_coef', 'signed_weather'),
            'holiday_newyear': ('holiday_newyear_coef', 'holiday'),
        },
        'note': 'SSOT 2026-06-07: независимые каналы (старый competitor↔TV +0.93 устранён); seasonal_lift снижен до 0.15.',
    },
    'fmcg': {
        'file': 'synth_fmcg_brand.xlsx',
        'generator': 'generate_fmcg_brand',
        'gt': 'GROUND_TRUTH_FMCG',
        'target': 'sales_rub',
        'media': {
            'tv_spend': ('tv_decay', 'tv_alpha'),
            'digital_spend': ('digital_decay', 'digital_alpha'),
            'ooh_trp': ('ooh_decay', 'ooh_alpha'),
            'performance_clicks': ('performance_decay', 'performance_alpha'),
        },
        'controls': {
            'competitor_trp': ('competitor_coef', 'signed_competitor'),
            'price_index': ('price_coef', 'signed_price'),
            'holiday_newyear': ('holiday_newyear_coef', 'holiday'),
        },
        'note': 'monetary KPI → движок стартует с competitor prior -0.3.',
    },
    'retail': {
        'file': 'synth_retail_ecom.xlsx',
        'generator': 'generate_retail_ecom',
        'gt': 'GROUND_TRUTH_RETAIL_ECOM',
        'target': 'sales_rub',
        'media': {
            'tv_spend': ('tv_decay', 'tv_alpha'),
            'digital_spend': ('digital_decay', 'digital_alpha'),
            'ooh_contacts': ('ooh_decay', 'ooh_alpha'),
            'retail_media_spend': ('retail_media_decay', 'retail_media_alpha'),
        },
        'controls': {
            'promo_indicator': ('promo_coef', 'control'),
            'competitor_promo': ('competitor_promo_coef', 'signed_competitor'),
            'holiday_blackfriday': ('holiday_blackfriday_coef', 'holiday'),
            'holiday_newyear': ('holiday_newyear_coef', 'holiday'),
        },
        'note': 'SSOT 2026-06-07: retail_ecom (KPI ₽ + retail_media), N=36, независимые каналы.',
    },
    'real_estate': {
        'file': 'synth_real_estate.xlsx',
        'generator': 'generate_real_estate',
        'gt': 'GROUND_TRUTH_REAL_ESTATE',
        'target': 'leads',
        'media': {
            'tv_spend': ('tv_decay', 'tv_alpha'),
            'ooh_contacts': ('ooh_decay', 'ooh_alpha'),
            'digital_spend': ('digital_decay', 'digital_alpha'),
            'performance_clicks': ('performance_decay', 'performance_alpha'),
        },
        'controls': {
            'competitor_activity': ('competitor_coef', 'signed_competitor'),
            'macro_cpi': ('macro_cpi_coef', 'signed_macro'),
            'holiday_newyear': ('holiday_newyear_coef', 'holiday'),
        },
        'note': 'SSOT 2026-06-07: single macro_cpi (без cumulative-дубля); Q1/Q4 baked; holiday_newyear — модель. dummy.',
    },
}


def _normalize(x):
    s = x.std()
    return (x - x.mean()) / s if s > 1e-10 else x - x.mean()


def ols(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    dof = max(n - k, 1)
    sigma2 = float(resid @ resid) / dof
    XtX_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(sigma2 * XtX_inv), 0.0))
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(se > 0, beta / se, 0.0)
    return beta, se, t


def check_consistency(name, cfg, df_disk):
    """Сверить файл на диске с текущим генератором (директива #3: истина от реального файла)."""
    gen_fn = getattr(gen, cfg['generator'])
    df_fresh = gen_fn()
    common = [c for c in df_disk.columns if c in df_fresh.columns]
    if list(df_disk.columns) != list(df_fresh.columns):
        return f'КОЛОНКИ РАЗЛИЧАЮТСЯ disk={list(df_disk.columns)} gen={list(df_fresh.columns)}'
    num = [c for c in common if c != 'date']
    a = df_disk[num].to_numpy(dtype=float)
    b = df_fresh[num].to_numpy(dtype=float)
    if a.shape != b.shape:
        return f'ФОРМА РАЗЛИЧАЕТСЯ disk={a.shape} gen={b.shape}'
    max_rel = float(np.max(np.abs(a - b) / (np.abs(b) + 1e-9)))
    return f'on-disk ≡ генератор (max rel diff {max_rel:.2e})' if max_rel < 1e-6 else f'РАСХОЖДЕНИЕ max rel diff {max_rel:.3e}'


def analyze(name):
    cfg = DATASETS[name]
    gt = getattr(gen, cfg['gt'])
    path = PILOTS / cfg['file']
    df = pd.read_excel(path)
    print(f'\n{"="*78}\n{name.upper()}  ({cfg["file"]}, n={len(df)})\n{"="*78}')
    print(f'Консистентность: {check_consistency(name, cfg, df)}')
    print(f'Заметка DGP: {cfg["note"]}')

    target = cfg['target']
    y = df[target].to_numpy(dtype=float)
    y_norm = _normalize(y)

    media_cols = list(cfg['media'].keys())
    ctrl_cols = list(cfg['controls'].keys())

    # ── Способ 1: аналитическая истина (знаки из GROUND_TRUTH) ──
    print('\n[Способ 1 — аналитика DGP] знаки контролей (заложенные):')
    analytic_sign = {}
    for c, (coef_key, kind) in cfg['controls'].items():
        coef = gt[coef_key]
        s = '+' if coef > 0 else ('-' if coef < 0 else '0')
        analytic_sign[c] = s
        print(f'  {c:<28} coef={coef:+.3f}  знак={s}  ({kind})')
    # доминирование базы (аналитически): base / mean(y)
    base_key = [k for k in gt if k.startswith('base_')][0]
    base = gt[base_key]
    base_share = base / float(np.mean(y))
    print(f'  base ({base_key}) = {base:,.0f}; base/mean(y) = {base_share:.1%}  → база доминирует: {base_share > 0.5}')

    # ── Способ 2A: naive OLS (z-score сырых) ──
    def build_and_fit(media_transform):
        cols = []
        names = []
        for mc in media_cols:
            x = df[mc].to_numpy(dtype=float)
            cols.append(media_transform(mc, x))
            names.append(mc)
        for cc in ctrl_cols:
            x = df[cc].to_numpy(dtype=float)
            # holiday/dummy оставляем как есть (0/1), остальное z-score
            kind = cfg['controls'][cc][1]
            cols.append(x if kind == 'holiday' else _normalize(x))
            names.append(cc)
        X = np.column_stack([np.ones(len(y))] + cols)
        beta, se, t = ols(X, y_norm)
        return dict(zip(['(intercept)'] + names, zip(beta, se, t)))

    naive = build_and_fit(lambda mc, x: _normalize(x))

    def dgp_xform(mc, x):
        decay_key, alpha_key = cfg['media'][mc]
        xn = _normalize(x)
        ads = gen._geometric_adstock(xn, gt[decay_key])
        return gen._hill(ads, gt[alpha_key], GAMMA_MID)

    dgpx = build_and_fit(dgp_xform)

    def fmt(res, c):
        b, se, t = res[c]
        sig = '***' if abs(t) > 2.6 else ('**' if abs(t) > 2.0 else ('*' if abs(t) > 1.7 else ''))
        return f'β={b:+.3f} se={se:.3f} t={t:+.2f}{sig}'

    print('\n[Способ 2 — мой OLS-референс на РЕАЛЬНОМ файле]')
    print(f'{"контроль":<28} {"naive (raw z)":<32} {"dgp-xform (true adstock+hill)":<34}')
    robust = {}
    for c in ctrl_cols:
        bn = naive[c][0]; tn = naive[c][2]
        bd = dgpx[c][0]; td = dgpx[c][2]
        sn = '+' if bn > 0 else '-'
        sd = '+' if bd > 0 else '-'
        print(f'  {c:<26} {fmt(naive, c):<32} {fmt(dgpx, c):<34}')
        # СТРОГО (директива #2 «две независимые истины»): робастно ТОЛЬКО если ОБА OLS
        # (naive БЕЗ трансформов И dgp-xform с oracle-трансформами) согласны со знаком
        # аналитики И ОБА значимы (|t|>2). Транзформ-зависимые (только oracle-OLS) НЕ
        # робастны: движок ОЦЕНИВАЕТ adstock/hill (не знает истинных) → держать его к
        # знаку, восстановимому лишь с истинными трансформами = ложное обвинение.
        agree_dgp = (analytic_sign[c] == sd) and (abs(td) > 2.0)
        agree_naive = (analytic_sign[c] == sn) and (abs(tn) > 2.0)
        if agree_dgp and agree_naive:
            robust[c] = analytic_sign[c]
            verdict = 'РОБАСТНО (оба OLS согл. → движок ОБЯЗАН)'
        elif agree_dgp:
            verdict = 'transform-dependent (только oracle-OLS значим; движок НЕ обязан)'
        elif agree_naive:
            verdict = 'naive-only (хрупко; движок НЕ обязан)'
        else:
            verdict = 'НЕ восстановимо (не обвинять)'
        print(f'      → аналитика={analytic_sign[c]} naive={sn}(t={tn:+.1f}) dgp={sd}(t={td:+.1f})  ВЕРДИКТ: {verdict}')

    print('\n[РОБАСТНАЯ ИСТИНА — держим движок ТОЛЬКО к этому]:')
    print(f'  знаки контролей: {robust if robust else "(нет однозначно восстановимых)"}')
    print(f'  база доминирует: {base_share > 0.5} (~{base_share:.0%})')
    print(f'  физ.единицы (unit_smell ожидается): {[m for m in media_cols if any(k in m for k in ("trp","contacts","clicks","indicator"))]}')
    return robust, base_share


if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'otc'
    targets = list(DATASETS.keys()) if which == 'all' else [which]
    for t in targets:
        analyze(t)
