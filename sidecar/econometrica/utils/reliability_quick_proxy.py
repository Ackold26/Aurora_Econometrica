"""
A4 Quick Proxy - pre-MCMC reliability checks (~1 sec).

Per ADR §6 + audit Amendment B3: lightweight identifiability checks that catch
80% of problematic data BEFORE running MCMC (which takes 5-30 minutes per
dataset). Full SBC reserved for borderline cases (Phase 1.6+ or A4 ship).

Three checks (all numpy/scipy-fast, no MCMC):
1. **Condition number** of media matrix - detects multicollinearity (>30 = problem)
2. **Pairwise Pearson correlation** - detects confounding pairs (>0.9 = problem)
3. **Channel variance ratio** - detects no-signal channels (<0.05 = problem)

Output: structured dict with tier classification + warnings + recommendation.
Used by validator.py before user clicks Train (gate UI flow).

UX framing per ADR Amendment A8:
- NEVER use "refuse" / "cannot" - always offer override path
- "Aurora paused training because..." constructive language
- Tells user WHAT TO FIX, not blames them

Math reference: docs/SPRINT1_FOUNDATION_ADR.md §6 Phase A4.0
"""
from __future__ import annotations

from typing import Any

import numpy as np


# Threshold defaults (calibrated from MMM literature + Aurora Kagocel/Venarus testing)
COND_NUMBER_OK = 30.0           # >30 = multicollinearity concern
COND_NUMBER_FAIL = 100.0        # >100 = severe - recommend reject
CORR_OK = 0.7                   # <0.7 = independent enough
CORR_WARN = 0.9                 # 0.7-0.9 = directional caution
CORR_FAIL = 0.95                # >0.95 = inseparable
VARIANCE_RATIO_OK = 0.10        # CV ≥ 0.10 = sufficient signal
VARIANCE_RATIO_FAIL = 0.05      # CV <0.05 = essentially constant


def quick_proxy_check(
    media_matrix: np.ndarray,
    channel_names: list[str],
) -> dict[str, Any]:
    """Run all 3 A4 quick proxy checks on media matrix.

    Args:
        media_matrix: shape (n_obs, n_channels) - raw spend per period × channel
        channel_names: ordered list of channel names matching column index

    Returns:
        dict with:
          - tier: 'reliable' | 'directional' | 'insufficient'
          - checks: detailed per-check results
          - warnings: list of human-readable warning strings
          - recommendation: actionable next step for user
          - overrideable: bool - can user proceed anyway with banner?
    """
    arr = np.asarray(media_matrix, dtype=np.float64)
    n_obs, n_channels = arr.shape if arr.ndim == 2 else (0, 0)

    if n_obs == 0 or n_channels == 0:
        return {
            'tier': 'insufficient',
            'checks': {},
            'warnings': ['Пустая матрица media - невозможно проверить identifiability'],
            'recommendation': 'Проверьте что в данных есть строки и media-каналы',
            'overrideable': False,
        }

    if len(channel_names) != n_channels:
        channel_names = [f'ch_{i}' for i in range(n_channels)]

    checks = {}
    warnings = []
    fail_count = 0
    warn_count = 0

    # ── Check 1: Condition number ───────────────────────────────────────
    try:
        # Center + scale columns to make condition number scale-invariant
        col_means = arr.mean(axis=0)
        col_stds = arr.std(axis=0)
        col_stds_safe = np.where(col_stds > 1e-9, col_stds, 1.0)
        scaled = (arr - col_means) / col_stds_safe
        # Singular values of scaled matrix
        s = np.linalg.svd(scaled, compute_uv=False)
        if len(s) > 0 and s[-1] > 1e-9:
            cond = float(s[0] / s[-1])
        else:
            cond = float('inf')
    except Exception as e:
        cond = float('inf')
        checks['condition_number'] = {
            'value': None, 'status': 'error', 'message': f'Computation failed: {e}'
        }
        warnings.append('Не удалось вычислить condition number - возможна проблема с данными')
        fail_count += 1
    else:
        if cond > COND_NUMBER_FAIL:
            status = 'fail'
            fail_count += 1
            warnings.append(
                f'Condition number {cond:.1f} > {COND_NUMBER_FAIL:.0f}: '
                f'каналы сильно линейно зависимы - модель не сможет их разделить'
            )
        elif cond > COND_NUMBER_OK:
            status = 'warn'
            warn_count += 1
            warnings.append(
                f'Condition number {cond:.1f} > {COND_NUMBER_OK:.0f}: '
                f'есть multicollinearity - оценки channel beta могут быть нестабильны'
            )
        else:
            status = 'ok'
        checks['condition_number'] = {
            'value': round(cond, 2),
            'threshold_ok': COND_NUMBER_OK,
            'threshold_fail': COND_NUMBER_FAIL,
            'status': status,
        }

    # ── Check 2: Pairwise correlations ───────────────────────────────────
    try:
        # Compute Pearson correlation matrix on raw spend
        # Avoid /0 by adding tiny noise to constant columns
        non_const_mask = arr.std(axis=0) > 1e-9
        if non_const_mask.sum() < 2:
            corr_pairs = []
        else:
            with np.errstate(invalid='ignore', divide='ignore'):
                corr = np.corrcoef(arr.T)  # (n_ch, n_ch); NaN on constant cols (handled below)
            corr_pairs = []
            for i in range(n_channels):
                for j in range(i + 1, n_channels):
                    if not (non_const_mask[i] and non_const_mask[j]):
                        continue
                    val = float(corr[i, j])
                    if not np.isfinite(val):
                        continue
                    abs_val = abs(val)
                    if abs_val > CORR_FAIL:
                        st = 'fail'
                        fail_count += 1
                        warnings.append(
                            f'Каналы {channel_names[i]} ↔ {channel_names[j]}: '
                            f'корреляция {val:+.2f} > {CORR_FAIL:.2f} - '
                            f'функционально неотличимы для модели'
                        )
                    elif abs_val > CORR_WARN:
                        st = 'warn'
                        warn_count += 1
                        warnings.append(
                            f'Каналы {channel_names[i]} ↔ {channel_names[j]}: '
                            f'корреляция {val:+.2f} > {CORR_WARN:.2f} - '
                            f'высокий confounding риск'
                        )
                    elif abs_val > CORR_OK:
                        st = 'info'
                    else:
                        st = 'ok'
                    if st in ('warn', 'fail', 'info'):
                        corr_pairs.append({
                            'channel_a': channel_names[i],
                            'channel_b': channel_names[j],
                            'correlation': round(val, 3),
                            'status': st,
                        })
        checks['correlations'] = {
            'flagged_pairs': corr_pairs,
            'threshold_warn': CORR_WARN,
            'threshold_fail': CORR_FAIL,
        }
    except Exception as e:
        checks['correlations'] = {
            'flagged_pairs': [], 'status': 'error', 'message': f'{e}'
        }

    # ── Check 3: Variance ratio (CV) per channel ─────────────────────────
    variance_results = []
    for i, name in enumerate(channel_names):
        col = arr[:, i]
        col_mean = float(col.mean())
        col_std = float(col.std())
        if abs(col_mean) < 1e-9:
            cv = 0.0
            st = 'fail'
            fail_count += 1
            warnings.append(
                f'Канал {name}: средний spend ≈ 0 - нет сигнала для обучения'
            )
        else:
            cv = col_std / abs(col_mean)
            if cv < VARIANCE_RATIO_FAIL:
                st = 'fail'
                fail_count += 1
                warnings.append(
                    f'Канал {name}: коэффициент вариации {cv:.3f} < {VARIANCE_RATIO_FAIL:.2f} - '
                    f'spend почти константный, модель не научится отделять эффект'
                )
            elif cv < VARIANCE_RATIO_OK:
                st = 'warn'
                warn_count += 1
                warnings.append(
                    f'Канал {name}: коэффициент вариации {cv:.3f} < {VARIANCE_RATIO_OK:.2f} - '
                    f'мало вариативности, оценка эффекта будет с большой неопределённостью'
                )
            else:
                st = 'ok'
        variance_results.append({
            'channel': name,
            'cv': round(cv, 3),
            'mean': round(col_mean, 2),
            'std': round(col_std, 2),
            'status': st,
        })
    checks['variance_ratio'] = {
        'per_channel': variance_results,
        'threshold_ok': VARIANCE_RATIO_OK,
        'threshold_fail': VARIANCE_RATIO_FAIL,
    }

    # ── Tier classification ──────────────────────────────────────────────
    if fail_count > 0:
        tier = 'insufficient'
        recommendation = (
            'Aurora обнаружила серьёзные проблемы с identifiability вашей выборки. '
            'Модель может выдать недостоверные оценки. Рекомендации: соберите больше '
            'данных, упростите медиа-микс (объедините похожие каналы), либо проведите '
            'experimental lift-study для калибровки. Можно продолжить обучение с '
            'предупреждением, но результаты будут "directional only".'
        )
        overrideable = True  # ADR §3.A8 - always offer override path
    elif warn_count > 0:
        tier = 'directional'
        recommendation = (
            'Данные имеют нюансы (multicollinearity или низкая вариативность каналов). '
            'Модель обучится, но используйте результаты как направление, не точную оценку. '
            'Для повышения точности рекомендуется собрать больше периодов или провести '
            'incrementality-тесты на проблемных каналах.'
        )
        overrideable = True
    else:
        tier = 'reliable'
        recommendation = (
            'Данные прошли все базовые проверки identifiability. '
            'Можно начинать обучение модели - результаты должны быть надёжными.'
        )
        overrideable = True  # Always overrideable; reliable means no override needed

    return {
        'tier': tier,
        'checks': checks,
        'warnings': warnings,
        'recommendation': recommendation,
        'overrideable': overrideable,
        'summary': {
            'fail_count': fail_count,
            'warn_count': warn_count,
            'total_checks': 3,  # cond + corr + variance
        }
    }
