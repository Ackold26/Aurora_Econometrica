"""
Sales decomposition engine.
Breaks down total sales into baseline + channel contributions.

P0-3/4/10 fix (math-fix-v1.0.13, Phase 3):
Pre-fix: contribution = |β|/Σ|β| × (total - baseline) → ignored adstock,
saturation, time. Baseline = sum(actual - predicted) + 0.3 × predicted.mean × n.
Post-fix: contribution_per_period = β × hill(adstock(x)/mean) × y_std.
Baseline = intercept × y_std + y_mean × n + control_effect × y_std.
"""
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any

from utils.adstock import apply_adstock, geometric_adstock_batch
from utils.saturation import hill_function, hill_function_batch, hill_function_batch_2d
from utils.posterior_propagation import (
    compute_ci_hdi,
    load_posterior_samples,
    per_channel_samples,
)


# Hybrid ROI thresholds (Phase 0.2 — plan immutable-bouncing-noodle §0.2, L4).
# Calibration sources documented в docs/ROI_THRESHOLDS.md.
ROI_DEEP_LOSS = 0.5         # < 0.5× = глубоко убыточный
ROI_LOSS = 0.8              # < 0.8× = убыточный
ROI_BREAKEVEN = 1.0         # < 1.0× = на грани окупаемости
ROI_HIGH_ABS = 5.0          # > 5× = высокоэффективен (small-N absolute fallback)
ROI_UNIT_SMELL_FLOOR = 50.0 # > 50× при unit_smell = "не рубли?" (preserved)
ROI_ARTIFACT = 100.0        # > 100× = artifact warning (regardless of unit_smell)
GAP_OVERSAT = -10.0         # пп — перенасыщен
GAP_UNDER = -5.0            # пп — слабее своей доли
GAP_HIGH = 10.0             # пп — высокоэффективен по share
GAP_GOOD = 5.0              # пп — эффективен по share
QUANTILE_MIN_N = 20         # ниже — relative quantile mode disabled


def compute_roi_verdict(
    roi: float,
    efficiency_gap: float,
    *,
    category: str = 'mixed',
    unit_smell: bool = False,
    roi_ci_low: float | None = None,
    roi_ci_high: float | None = None,
    n_channels: int = 0,
    category_quantiles: dict[str, dict[str, float]] | None = None,
) -> tuple[str, str]:
    """Hybrid ROI verdict combining absolute + relative + posterior CI.

    Per plan immutable-bouncing-noodle §0.2 (L4 fix), and L2 (math-fix v1.4
    Section C, 2026-04-29) re-ordering:

      Pre-fix (L4): Step 1 — wide CI → 'Высокая неопределённость' (suppressed
        ALL informative labels на small-N data — customer never saw «Перенасыщен»
        / «Высокоэффективен» when CI was wide regardless of point estimate).
      Post-fix (L2): wide CI → suffix « (низкая уверенность)» appended к
        existing label. Keeps informative descriptive verdict (mROAS-derived)
        while honestly disclosing CI uncertainty. Customer sees full picture.

    Order:
      Step 1 — posterior uncertainty flag (computed, applied at end as suffix)
      Step 2 — absolute hard caps (artifact/glubokaya-ubitochnost regardless of category)
      Step 3 — relative quantile (only if N ≥ 20 portfolio data + category mapping)
      Step 4 — efficiency gap fallback (small-N safe per-channel)

    Args:
      roi: канальный ROI (contribution_money / spend_money), unitless.
      efficiency_gap: share_of_effect - share_of_spend (пп).
      category: 'brand_reach' / 'performance' / 'mixed' (для quantile lookup).
      unit_smell: True если канал в TRP/clicks/impressions (не деньги) и unit_cost=1.
      roi_ci_low, roi_ci_high: posterior 90% CI bounds (Phase 1.9 — пока None).
      n_channels: total channels в выборке (для quantile-mode gating).
      category_quantiles: {category: {p10, p25, p75, p90}} portfolio benchmarks.

    Returns:
      (verdict_label, verdict_tone) where tone ∈ {good, warn, bad, neutral}.
    """
    # Step 1 (L2 refactor): compute wide-CI flag для последующего suffix.
    # Pre-fix: this was the FIRST gate suppressing all informative labels.
    # Post-fix: descriptive verdict computed first, CI uncertainty added как
    # honest disclosure suffix (customer sees what AND how confident).
    wide_ci = (
        roi_ci_low is not None
        and roi_ci_high is not None
        and roi > 0
        and (roi_ci_high - roi_ci_low) > roi
    )

    def _apply_ci_suffix(label, tone):
        # Подпись смягчена 2026-05-02: было "(низкая уверенность)" — эмоционально
        # воспринималось как недоверие модели целиком (особенно когда R²/MAPE отличные).
        # Стало "(широкий ROI-интервал)" — нейтральное техническое описание:
        # ROI следует трактовать как диапазон, не как точное число. Качество модели
        # оценивается отдельно через R² / MAPE / R-hat (см. Эксперт-панель Train).
        if wide_ci:
            return (f"{label} (широкий ROI-интервал)", 'warn' if tone == 'good' else tone)
        return (label, tone)

    # Step 2 — absolute hard caps (regardless of category)
    if roi > ROI_UNIT_SMELL_FLOOR and unit_smell:
        return _apply_ci_suffix('ROI завышен (не рубли?)', 'warn')
    if roi > ROI_ARTIFACT:
        return _apply_ci_suffix('ROI нереалистичен (артефакт)', 'warn')
    if roi < ROI_DEEP_LOSS:
        return _apply_ci_suffix('Глубоко убыточный', 'bad')
    if roi < ROI_LOSS:
        return _apply_ci_suffix('Убыточный', 'bad')
    if roi < ROI_BREAKEVEN:
        return _apply_ci_suffix('На грани окупаемости', 'warn')

    # Step 3 — category-relative quantile (gated by min N)
    if (
        n_channels >= QUANTILE_MIN_N
        and category_quantiles
        and category in category_quantiles
    ):
        q = category_quantiles[category]
        p10 = q.get('p10')
        p25 = q.get('p25')
        p75 = q.get('p75')
        p90 = q.get('p90')
        if p10 is not None and roi < p10:
            return _apply_ci_suffix('Bottom-10% по категории', 'bad')
        if p90 is not None and roi >= p90:
            return _apply_ci_suffix('Top-10% по категории', 'good')
        if p75 is not None and roi >= p75:
            return _apply_ci_suffix('Top-25% по категории', 'good')
        if p25 is not None and roi < p25:
            return _apply_ci_suffix('Bottom-25% по категории', 'warn')
        return _apply_ci_suffix('Средний по категории', 'neutral')

    # Step 4 — efficiency gap fallback (per-channel small-N safe)
    if roi > ROI_HIGH_ABS and not unit_smell:
        return _apply_ci_suffix('Высокоэффективен', 'good')
    if efficiency_gap <= GAP_OVERSAT:
        return _apply_ci_suffix('Перенасыщен', 'warn')
    if efficiency_gap <= GAP_UNDER:
        return _apply_ci_suffix('Слабее своей доли', 'warn')
    if efficiency_gap >= GAP_HIGH:
        return _apply_ci_suffix('Высокоэффективен', 'good')
    if efficiency_gap >= GAP_GOOD:
        return _apply_ci_suffix('Эффективен', 'good')
    return _apply_ci_suffix('Сбалансирован', 'neutral')


def decompose(
    project_dir: str,
    unit_costs_override: dict | None = None,
    unit_cost_inflation_pct: dict | None = None,
) -> dict[str, Any]:
    """Decompose sales into baseline + channel contributions using trained model.

    Args:
        project_dir: Path to project with models/latest.pkl
        unit_costs_override: Если задан — используется вместо config.unit_costs из pickle.
            Нужно, когда user изменил CPP/CPM после тренировки модели.

    Returns:
        JSON with waterfall data, ROI, share of spend vs effect
    """
    project_path = Path(project_dir)
    model_path = project_path / 'models' / 'latest.pkl'

    if not model_path.exists():
        return {
            'status': 'error',
            'error_code': 'MODEL_NOT_FOUND',
            'message': 'Модель не найдена. Сначала обучите модель в кабинете «Данные и Модель».',
        }

    # Trust Level 3: централизованный pickle compat helper.
    # Auto-injects channel_categories={} для pre-v1.3 pickles.
    from engines.persistence import load_model_with_compat
    model_data = load_model_with_compat(model_path)

    # P0-1/2/9 fix: pickle compat detection.
    # Sprint 2: '1.0-ols' accepted as small-data fallback path (treats как v1.1
    # downstream — point estimates only, no posterior CI, frequentist β CI на channel level).
    model_version = model_data.get('model_version', '1.0')
    if model_version == '1.0':
        return {
            'status': 'error',
            'error_code': 'MODEL_OUTDATED',
            'message': 'Модель обучена до v1.0.13. Нормализация изменилась — переобучите модель в кабинете "Модель".',
        }

    config = model_data['config']
    channel_params = model_data['channel_params']
    norm = model_data['normalization']
    # Phase 1.9: posterior samples for honest CI on contribution/ROI per channel.
    # None for v1.0/v1.1 pickles → ch dict skips ci_low/ci_high → compute_roi_verdict
    # Step 1 silently falls through (point-estimate verdict path preserved).
    posterior_samples = load_posterior_samples(model_data)
    y_actual = np.array(model_data['y_actual'])
    y_predicted_saved = np.array(model_data.get('y_predicted', []) or [])
    media_cols = config['media_columns']
    control_cols = config.get('control_columns', []) or []
    # A1 fix (post-audit v1.2): for decomposition we still report untrained channels
    # but their contribution will be ~0 (training data was constant → β·sat·y_std≈0).
    # No need to filter — they self-zero in the per-period contribution math.
    untrained_channels = set(model_data.get('normalization', {}).get('untrained_channels', []) or [])
    # Override > config. Передан ли override (даже {}) — клиент управляет явно.
    unit_costs = unit_costs_override if unit_costs_override is not None else (config.get('unit_costs', {}) or {})

    # Read original data for spend totals + adstock + control effects
    data_file = config['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
    # Материализация виртуальных каналов (если были merge_rules при train)
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config.get('merge_rules'))

    # Phase 2 audit pass 4 — per-channel inflation: customer entered current
    # cost (latest training year) + annual_inflation_pct → adjust к training-
    # period weighted average. ROI/mROAS теперь reflect actual training prices.
    if unit_cost_inflation_pct:
        from utils.unit_cost_inflation import apply_inflation_to_unit_costs
        unit_costs = apply_inflation_to_unit_costs(
            unit_costs=unit_costs,
            inflation_pct_per_channel=unit_cost_inflation_pct,
            df=df,
            date_column=config.get('date_column', 'date'),
        )

    n_periods = len(df)
    total_sales = float(y_actual.sum())

    # Normalization params
    y_mean = float(norm.get('y_mean', 0))
    y_std = float(norm.get('y_std', 1)) or 1
    intercept_mean = float(norm.get('intercept_mean', 0))
    control_betas_mean = norm.get('control_betas_mean', []) or []
    media_means = norm.get('media_means', {}) or {}
    control_means = norm.get('control_means', {}) or {}
    control_stds = norm.get('control_stds', {}) or {}

    adstock_config = config.get('adstock_config', {}) or {}

    # ─────────────────────────────────────────────────────────────────────
    # P0-3/4/10 fix: per-channel per-period contribution = β × hill(adstock(x)/mean) × y_std
    # ─────────────────────────────────────────────────────────────────────
    channels = []
    time_series_channels: dict[str, list[float]] = {}
    total_media_contribution = 0.0

    for col in media_cols:
        params = channel_params[col]
        # H-OLS-2 (audit 2026-04-27): explicit guard для untrained channels.
        # OLS engine marks channels with zero training variance via 'untrained': True flag.
        # Pre-fix: such channels могли silently get spurious contribution когда production
        # spend non-zero (mean fallback к 1.0 → x_norm = adstocked/1.0 = full raw → Hill saturation).
        # Post-fix: explicit zero contribution + skip CI computation.
        #
        # Phase 5 follow-up audit (2026-05-03): Bayesian engine marks untrained channels
        # only через `normalization.untrained_channels` list (not channel_params.untrained).
        # OLS marks both. Без поддержки norm-list path, Bayesian-trained pickles с zero-
        # variance channels gave spurious contributions (decomposer не skipped). Fix:
        # secondary check — col в untrained_channels list.
        if params.get('untrained') or col in untrained_channels:
            from engines.narrative_adapter import _normalize_channel_name as _norm
            ch_dict_untr = {
                'name': col,
                'display_name': _norm(col) or col,
                'spend': 0.0,
                'raw_spend': 0.0,
                'unit_cost': float(unit_costs.get(col, 1.0) or 1.0),
                'contribution': 0.0,
                'contribution_pct': 0,
                'roi': 0.0,
                'beta': 0.0,
                'verdict': 'Не обучен',
                'verdict_tone': 'neutral',
                'untrained': True,
                'ci_skip_reason': 'untrained_channel',
                'mroi_current': 0.0,
            }
            channels.append(ch_dict_untr)
            continue
        beta = float(params.get('beta', 0))
        alpha = max(float(params.get('alpha', 1)), 1e-6)
        gamma = max(float(params.get('gamma', 0.5)), 1e-6)

        raw_spend_series = df[col].fillna(0).values.astype(float)
        raw_spend_total = float(raw_spend_series.sum())

        # 1. Adstock (matches training).
        # adstock_config schema: dict[channel, str] — type only ('geometric' or 'weibull').
        # Defensive read: tolerate dict-with-'type' format from older pickles or
        # rare configs, but standardize on str. Hyperparameters use library defaults
        # (matching modeler.py training-time apply_adstock signature).
        raw_at = adstock_config.get(col)
        if isinstance(raw_at, dict):
            a_type = raw_at.get('type', 'geometric')
        elif isinstance(raw_at, str):
            a_type = raw_at
        else:
            a_type = 'geometric'

        # Phase 1.1: when v1.2 pickle, use posterior mean decay from channel_params.
        # Falls back to library default (0.5/2.0/3.0) для v1.0/v1.1/v1.1.5 pickles.
        decay_point = params.get('decay')  # None for legacy pickles
        adstock_params_override = {'alpha': float(decay_point)} if decay_point is not None else None
        x_adstock = apply_adstock(raw_spend_series, a_type, adstock_params_override)

        # 2. Normalize spend/mean (matches Phase 2 fix).
        # C1 fix (audit 2026-04-26): prefer in-model adstock_mean_posterior (Phase 1.1+ v1.2 pickles)
        # for math consistency with training. Fallback to pre-computed media_means для legacy
        # pickles (v1.0-ols, v1.1, v1.1.5) where this field absent.
        mean_posterior = params.get('adstock_mean_posterior')
        mean = float(mean_posterior) if mean_posterior is not None else float(media_means.get(col, 1)) or 1
        x_norm = x_adstock / max(mean, 1e-10)

        # 3. Hill saturation
        sat = hill_function(np.maximum(x_norm, 0), alpha=alpha, gamma=gamma)

        # 4. Per-period contribution in original KPI units
        contrib_per_period = beta * sat * y_std
        channel_total = float(contrib_per_period.sum())
        total_media_contribution += channel_total

        time_series_channels[col] = [round(float(v), 1) for v in contrib_per_period]

        # Money & ROI
        unit_cost = float(unit_costs.get(col, 1.0) or 1.0)
        spend_money = raw_spend_total * unit_cost

        roi = channel_total / spend_money if spend_money > 0 else 0

        # L4 (math-fix v1.4 Section C, 2026-04-28): mroi_current at current allocation
        # via single-source-of-truth helper. Optimize UI miROASMap reads this field
        # in idle state (pre-optimize) instead of broken JS fallback `marginalROI`
        # which was missing /unit_cost /mean /adstock_factor → mixed units (Kagocel
        # TRPs showed 110.93× pre-optimize vs 0.0285× post-optimize).
        from engines.optimizer import _compute_mroas_money
        mroi_current_pt = float(_compute_mroas_money(
            current_spend_native=raw_spend_total,
            n_periods=n_periods,
            mean=mean,
            alpha=alpha,
            gamma=gamma,
            beta=beta,
            adstock_type=a_type,
            y_std=y_std,
            unit_cost=unit_cost,
            decay=decay_point,
        ))

        # L11 (math-fix v1.4 Section C, 2026-04-29): display_name strips Excel
        # column-header noise («Performance Бюджет до НДС до АК» → «Performance»).
        # `name` field preserved for data lookups; `display_name` для UI rendering
        # consistency (interpretation block, charts, narrative tooltips).
        from engines.narrative_adapter import _normalize_channel_name
        display_name = _normalize_channel_name(col) or col

        ch_dict = {
            'name': col,
            'display_name': display_name,
            'spend': round(spend_money, 0),
            'raw_spend': round(raw_spend_total, 2),
            'unit_cost': unit_cost,
            'contribution': round(channel_total, 0),
            'contribution_pct': 0,  # filled after total computed below
            'roi': round(roi, 2),
            'mroi_current': round(mroi_current_pt, 4),
            'beta': beta,
            'verdict': '',
            'verdict_tone': 'neutral',
            # Trust Level 3 (v1.1.0): adstock decay posterior summary для UI display.
            # Decompose grouping panel показывает effective half-life per channel.
            'adstock_decay_mean': float(decay_point) if decay_point is not None else None,
        }

        # F1 fix (audit 2026-04-27): per-sample training adstock mean for math
        # consistency with in-model `adstock_full[s,:].mean()` normalization.
        # Pre-fix used scalar `adstock_mean_posterior` for all samples → CI
        # distribution shape distorted when decay varies across draws (which is
        # the whole point of hierarchical learnable adstock — Phase 1.1).
        # Same class-of-bug as C1 (audit 2026-04-26), but missed by C1 fix
        # which closed only the POINT estimate path.
        # Phase 1.9 + 1.1: posterior CI on contribution and ROI via vectorized chain.
        # C3 fix (audit 2026-04-26): explicit CI semantics для spend=0 channels.
        # Pre-fix: spend=0 channels skipped from CI (asymmetric — point estimate populated
        # как roi=0 но без ci_low/ci_high → UI shows "ROI 0× (no CI)" without explanation).
        # Post-fix: explicit ci_low=ci_high=0 with marker 'ci_skip_reason' = 'zero_spend'
        # so UI can render "Канал без бюджета — ROI = 0 (CI неприменим)".
        if posterior_samples is not None and spend_money <= 0:
            ch_dict['contribution_ci_low'] = 0.0
            ch_dict['contribution_ci_high'] = 0.0
            ch_dict['roi_ci_low'] = 0.0
            ch_dict['roi_ci_high'] = 0.0
            ch_dict['ci_skip_reason'] = 'zero_spend'
            ch_dict['ci_method'] = 'unavailable_zero_spend'

        # Sprint 2 extension (small-data path): for '1.0-ols' pickles, populate
        # roi_ci_low/high from stored bootstrap CI (no posterior_samples available).
        # This gives OLS path same UI semantics as Bayesian — UI renders brackets
        # uniformly without engine-specific code paths.
        if posterior_samples is None and spend_money > 0:
            roi_ci_low_boot = params.get('roi_ci_low_bootstrap')
            roi_ci_high_boot = params.get('roi_ci_high_bootstrap')
            if roi_ci_low_boot is not None and roi_ci_high_boot is not None:
                ch_dict['roi_ci_low'] = round(float(roi_ci_low_boot), 4)
                ch_dict['roi_ci_high'] = round(float(roi_ci_high_boot), 4)
                ch_dict['ci_method'] = 'frequentist_bootstrap'
        # Phase 1.1 path: when ch_samples has 'decay', x_norm varies per sample
        # via geometric_adstock_batch — use hill_function_batch_2d.
        # Phase 1.9 path (v1.1.5 pickles): decay constant, use hill_function_batch (1D x_norm).
        if posterior_samples is not None and spend_money > 0:
            ch_samples = per_channel_samples(posterior_samples, col)
            if ch_samples is not None:
                decay_samples = ch_samples.get('decay')
                if decay_samples is not None and a_type == 'geometric':
                    # Phase 1.1: per-sample adstock + Hill, joint correlation preserved.
                    x_adstock_2d = geometric_adstock_batch(raw_spend_series, decay_samples)
                    # F1 fix: in decomposer, raw_spend_series IS training data (df reloaded
                    # from config.data_file at line 180), so x_adstock_2d.mean(axis=1) is
                    # the per-sample training adstock mean — exactly what model used during
                    # training. Use as per-sample divisor to restore math consistency.
                    mean_per_sample = np.maximum(
                        x_adstock_2d.mean(axis=1, keepdims=True), 1e-10
                    )
                    x_norm_2d = x_adstock_2d / mean_per_sample
                    sat_samples = hill_function_batch_2d(
                        x_norm_2d, ch_samples['alpha'], ch_samples['gamma']
                    )
                else:
                    # Phase 1.9 fallback (v1.1.5 pickles or weibull channels) — decay
                    # constant across samples, so scalar `mean` is consistent with training.
                    sat_samples = hill_function_batch(
                        x_norm, ch_samples['alpha'], ch_samples['gamma']
                    )
                # contribution per period × sample, summed over time → (n_samples,)
                contrib_total_samples = (
                    ch_samples['beta'].reshape(-1, 1).astype(np.float64)
                    * sat_samples
                    * y_std
                ).sum(axis=1)
                _, contrib_ci_low, contrib_ci_high, _method_c = compute_ci_hdi(contrib_total_samples)
                ch_dict['contribution_ci_low'] = round(float(contrib_ci_low), 0)
                ch_dict['contribution_ci_high'] = round(float(contrib_ci_high), 0)

                # ROI distribution: contribution / spend_money (constant denominator)
                roi_samples = contrib_total_samples / spend_money
                _, roi_ci_low, roi_ci_high, _method_r = compute_ci_hdi(roi_samples)
                ch_dict['roi_ci_low'] = round(float(roi_ci_low), 4)
                ch_dict['roi_ci_high'] = round(float(roi_ci_high), 4)
                # F5 fix: ci_method reflects ACTUAL HDI computation (not silent fallback).
                # A2 audit-of-audit (2026-04-27): conservative OR semantic — flag '_pct'
                # if EITHER contrib OR roi fell back к percentile (in case arviz fails on
                # one but not the other due to numerical edge cases).
                _is_pct = (_method_c == 'percentile_fallback') or (_method_r == 'percentile_fallback')
                if decay_samples is not None:
                    base = 'bayesian_hdi_phase11_pct' if _is_pct else 'bayesian_hdi_phase11'
                    # Trust Level 3: 50% CI для decay (Critical Audit issue M).
                    # 95% would показывать decay 0.30-0.95 → uninterpretable. 50% (q25/q75) tighter.
                    try:
                        import numpy as _np2
                        ds = _np2.asarray(decay_samples, dtype=float)
                        ch_dict['adstock_decay_mean'] = float(_np2.mean(ds))
                        ch_dict['adstock_decay_ci_low'] = float(_np2.quantile(ds, 0.25))
                        ch_dict['adstock_decay_ci_high'] = float(_np2.quantile(ds, 0.75))
                    except Exception:
                        pass
                else:
                    base = 'bayesian_hdi_pct' if _is_pct else 'bayesian_hdi'
                ch_dict['ci_method'] = base

        channels.append(ch_dict)

    # Fill contribution_pct relative to total media contribution
    for ch in channels:
        ch['contribution_pct'] = round(
            ch['contribution'] / total_media_contribution * 100, 1
        ) if total_media_contribution > 0 else 0

    # ─────────────────────────────────────────────────────────────────────
    # Baseline = intercept_mean × y_std + y_mean (per period) + control effect
    # ─────────────────────────────────────────────────────────────────────
    intercept_per_period = np.full(n_periods, intercept_mean * y_std + y_mean, dtype=float)

    control_effect_per_period = np.zeros(n_periods, dtype=float)
    if control_cols and control_betas_mean and len(control_betas_mean) == len(control_cols):
        # Reconstruct control normalization (z-score retained for controls — non-Hill linear)
        c_means = np.array([float(control_means.get(c, 0)) for c in control_cols])
        c_stds = np.array([float(control_stds.get(c, 1)) or 1 for c in control_cols])
        X_control_raw = df[control_cols].fillna(0).astype(float).values
        X_control_norm = (X_control_raw - c_means) / c_stds
        beta_c = np.array(control_betas_mean, dtype=float)
        # control_effect normalised → multiply by y_std for original-unit
        control_effect_per_period = (X_control_norm @ beta_c) * y_std

    # Energy conservation (post-audit fix): baseline absorbs residual variance
    # so that sum(baseline) + sum(channels) == sum(y_actual) exactly.
    # Standard MMM convention (Robyn, LightweightMMM, Meridian): residual goes
    # into baseline since by construction it's "unexplained by media".
    # Compute model-predicted per period (sum of intercept + media + controls):
    media_contrib_per_period = np.zeros(n_periods, dtype=float)
    for col in media_cols:
        ts = time_series_channels.get(col, [])
        for t, v in enumerate(ts):
            if t < n_periods:
                media_contrib_per_period[t] += float(v)
    raw_baseline = intercept_per_period + control_effect_per_period
    model_predicted_per_period = raw_baseline + media_contrib_per_period
    # Residual = actual - model_predicted; absorbed into baseline
    if len(y_actual) >= n_periods:
        residual_per_period = y_actual[:n_periods] - model_predicted_per_period
    else:
        residual_per_period = np.zeros(n_periods, dtype=float)
    baseline_per_period = raw_baseline + residual_per_period
    baseline_total = float(baseline_per_period.sum())
    baseline_ts = [round(float(v), 1) for v in baseline_per_period]

    # Sort by ROI descending
    channels.sort(key=lambda x: x['roi'], reverse=True)

    # Share of Spend vs Share of Effect
    total_spend = sum(c['spend'] for c in channels) or 1
    for ch in channels:
        ch['share_of_spend'] = round(ch['spend'] / total_spend * 100, 1)
        ch['share_of_effect'] = ch['contribution_pct']
        ch['efficiency_gap'] = round(ch['share_of_effect'] - ch['share_of_spend'], 1)

    # Category + unit_smell detection (used by hybrid verdict)
    # Trust Level 3: prefer explicit channel_categories из pickle (training-time
    # decision); fallback к heuristic для pre-v1.3 pickles.
    from engines.persistence import get_channel_categories
    explicit_categories = get_channel_categories(model_data, fallback_heuristic=False)

    UNIT_HINTS = ('TRP', 'GRP', 'OTS', 'IMPRESSION', 'CLICK', 'ПОКАЗ', 'КЛИК', 'ПРОСМОТР', 'ВИЗИТ', 'ПУНКТ', 'ОХВАТ', 'РЕЙТИНГ')
    # Heuristic fallback hints — single source of truth = utils/channel_categorization.py.
    from utils.channel_categorization import auto_suggest_category

    # Optional portfolio quantiles (Phase 1+ groundwork — None until aggregator ships).
    category_quantiles = config.get('category_quantiles') if isinstance(config, dict) else None
    n_channels = len(channels)

    for ch in channels:
        # Phase 5 follow-up audit (2026-05-03): untrained channels preserve their
        # honest 'Не обучен' verdict — without skip, downstream compute_roi_verdict
        # overwrote с 'Глубоко убыточный' (roi=0 < 0.5 threshold), which is wrong
        # diagnostic (no data ≠ deep loss).
        if ch.get('untrained'):
            ch.setdefault('category', 'mixed')
            ch.setdefault('unit_smell', False)
            ch.setdefault('share_of_spend', 0.0)
            ch.setdefault('share_of_effect', 0.0)
            ch.setdefault('efficiency_gap', 0.0)
            continue
        name = ch['name'] or ''
        name_upper = name.upper()
        looks_like_non_money = any(hint in name_upper for hint in UNIT_HINTS)
        # Trust Level 3 mapping: 'brand' → 'brand_reach' (preserves verdict thresholds API).
        if name in explicit_categories:
            cat_v3 = explicit_categories[name]
            if cat_v3 == 'brand':
                ch['category'] = 'brand_reach'
            elif cat_v3 == 'performance':
                ch['category'] = 'performance'
            else:
                ch['category'] = 'mixed'
        else:
            # Heuristic fallback for pre-v1.3 pickles (single source = utils/channel_categorization).
            sug = auto_suggest_category(name)
            if sug['category'] == 'brand' and sug['confidence'] >= 0.7:
                ch['category'] = 'brand_reach'
            elif sug['category'] == 'performance' and sug['confidence'] >= 0.7:
                ch['category'] = 'performance'
            else:
                ch['category'] = 'mixed'
        ch['unit_smell'] = bool(looks_like_non_money and abs(ch['unit_cost'] - 1.0) < 1e-9)

        # Hybrid verdict (absolute + relative + posterior CI) — see compute_roi_verdict docstring
        verdict_label, verdict_tone = compute_roi_verdict(
            roi=ch['roi'],
            efficiency_gap=ch['efficiency_gap'],
            category=ch['category'],
            unit_smell=ch['unit_smell'],
            roi_ci_low=ch.get('roi_ci_low'),
            roi_ci_high=ch.get('roi_ci_high'),
            n_channels=n_channels,
            category_quantiles=category_quantiles,
        )
        ch['verdict'] = verdict_label
        ch['verdict_tone'] = verdict_tone

    # L4 (math-fix v1.4 Section C, 2026-04-28): decorate каждый channel с
    # prescriptive action fields через single-source-of-truth helper. Same
    # compute_channel_action used в optimizer.py + narrative_adapter.py →
    # three-way alignment (decompose UI ↔ optimize UI ↔ HTML/PPTX commentary).
    # При idle state (pre-optimize) optimal_spend отсутствует → action falls back
    # к mROAS-only heuristic. После optimize backend overrides с optimizer signal.
    from engines.channel_action import compute_channel_action
    for ch in channels:
        # Phase 5 follow-up audit: untrained channels — fixed action vocabulary
        # вместо compute_channel_action которая инфер из mROAS=0 (low confidence).
        if ch.get('untrained'):
            ch.setdefault('action', 'Uncertain')
            ch.setdefault('action_label', 'Не обучен')
            ch.setdefault('action_tone', 'neutral')
            ch.setdefault('action_reasoning', 'Канал имел нулевую вариативность в обучающих данных — модель не обучилась на нём.')
            ch.setdefault('action_priority', 0)
            ch.setdefault('action_confidence', 'high')
            continue
        # alias mroi_current → mroas для compute_channel_action API contract
        action_input = {**ch, 'mroas': ch.get('mroi_current')}
        action = compute_channel_action(action_input)
        ch['action'] = action.key
        ch['action_label'] = action.label_ru
        ch['action_tone'] = action.tone
        ch['action_reasoning'] = action.reasoning
        ch['action_priority'] = action.priority
        ch['action_confidence'] = action.confidence

    # Insight generation (template, 0 tokens).
    # B3 fix (post-audit v1.2): removed magic-0.5 lift estimate. Pre-fix code computed
    # `lift = |efficiency_gap| × 0.5` then claimed "ожидаемый прирост +X% продаж" —
    # without basis in model. Replaced with descriptive text only; for actual lift
    # estimate user should run scenario or optimize step (which DO compute against model).
    top = channels[0] if channels else None
    worst = channels[-1] if channels else None
    insight = ''
    if top and worst:
        insight = (
            f"{top['name']} — самый эффективный канал (ROI {top['roi']:.1f}×). "
            f"{worst['name']} — наименее эффективный (ROI {worst['roi']:.1f}×)."
        )
        if top['efficiency_gap'] > 5 and worst['efficiency_gap'] < -5:
            insight += (
                f" Канал {worst['name']} использует больше бюджета чем даёт эффекта "
                f"(gap {worst['efficiency_gap']:+.0f} пп) — рассмотрите перераспределение "
                f"в {top['name']}. Точную оценку прироста см. в шаге «Оптимизация»."
            )

    # Per-period dates
    date_col = config.get('date_column', 'date')
    if date_col in df.columns:
        dates = [str(d)[:10] for d in df[date_col].tolist()]
    else:
        dates = [str(i + 1) for i in range(n_periods)]

    # Smell-детектор для banner доверия
    smell_flags = []
    positive_rois = [c['roi'] for c in channels if c['roi'] > 0]
    any_unit_smell = any(c.get('unit_smell') for c in channels)
    if positive_rois and any_unit_smell:
        roi_max = max(positive_rois)
        roi_min = min(positive_rois)
        if roi_max > 50:
            top_ch = max(channels, key=lambda c: c['roi'])
            smell_flags.append({
                'type': 'roi_max',
                'channel': top_ch['name'],
                'value': round(roi_max, 1),
                'severity': 'high' if roi_max > 200 else 'medium',
            })
        if roi_min > 0 and roi_max / roi_min > 50:
            smell_flags.append({
                'type': 'roi_spread',
                'value': round(roi_max / roi_min, 1),
                'severity': 'high' if roi_max / roi_min > 200 else 'medium',
            })
    unit_smell_channels = [c['name'] for c in channels if c.get('unit_smell')]
    if unit_smell_channels:
        smell_flags.append({
            'type': 'unit_smell',
            'channels': unit_smell_channels,
            'severity': 'medium',
        })

    # Phase 1.1: model_version warning — flag legacy pickles for re-training.
    # v1.1.5 pickles use hardcoded adstock decay (0.5) — CI not honest about
    # carryover uncertainty. UI can render banner suggesting re-train for v1.2.
    # Sprint 2: '1.0-ols' = small-data fallback, frequentist semantics (no posterior CI).
    model_warning = None
    if model_version == '1.0-ols':
        n_obs_ols = len(y_actual) if isinstance(y_actual, (list, np.ndarray)) else 0
        model_warning = (
            f'OLS-режим (small data fallback): n={n_obs_ols} наблюдений. '
            f'Hill α=1.5, γ=0.5, decay=0.5 — фиксированы (не обучаются). '
            f'Доверительные интервалы — frequentist на β-коэффициенты + predictive '
            f'intervals на y. Posterior CI на ROI/mROAS недоступны (нужен n≥30 для '
            f'Bayesian). Соберите больше данных для премиум-модели.'
        )
    elif model_version == '1.1.5':
        model_warning = (
            'Эта модель обучена с фиксированным adstock-затуханием (0.5). '
            'Доверительные интервалы не учитывают неопределённость carryover. '
            'Переобучите модель для получения honest CI на adstock (Phase 1.1, v1.2).'
        )
    elif model_version == '1.1':
        model_warning = (
            'Эта модель обучена до Phase 1.9 — посterior samples отсутствуют. '
            'Доверительные интервалы недоступны. Переобучите модель для CI поддержки.'
        )

    result = {
        'status': 'ok',
        'model_version': model_version,
        'model_warning': model_warning,  # None for v1.2 (current production), banner string for legacy
        'smell_flags': smell_flags,
        'total_sales': round(total_sales, 0),
        'baseline': round(baseline_total, 0),
        'baseline_pct': round(baseline_total / total_sales * 100, 1) if total_sales else 0,
        'media_contribution': round(total_media_contribution, 0),
        'channels': channels,
        'insight': insight,
        'waterfall': {
            'labels': ['Baseline'] + [c['name'] for c in channels] + ['Итого'],
            'values': [round(baseline_total, 0)] + [round(c['contribution'], 0) for c in channels] + [round(total_sales, 0)],
            'types': ['baseline'] + ['channel'] * len(channels) + ['total'],
        },
        'time_series': {
            'dates': dates,
            'baseline': baseline_ts,
            'channels': time_series_channels,
        },
        # Trust Level 3 (v1.1.0): hierarchical metadata для UI banner.
        # Empty / use_hierarchical=False для legacy + non-hierarchical models.
        'hierarchical': {
            'enabled': bool(model_data.get('use_hierarchical')),
            'channel_categories': dict(model_data.get('channel_categories') or {}),
            'categorization_warnings': list(model_data.get('categorization_warnings') or []),
            'priors_summary': dict(model_data.get('hierarchical_priors') or {}),
        },
    }

    # Save
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'decomposition.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result
