"""Pickle persistence helpers for Aurora Econometrica models.

Trust Level 3 (v1.1.0) added `model_version='1.3'` с polem `channel_categories`.
Этот модуль централизует pickle compat - все downstream consumers (decomposer,
optimizer, scenario, narrative_adapter, backtest, html_export) должны use
`load_model_with_compat()` вместо direct pickle.load().

Migration ladder:
- v1.0       - initial OLS path (rejected by decomposer guard, MODEL_OUTDATED)
- v1.0-ols   - Sprint 2 small-data fallback (point estimates, no posterior CI)
- v1.1       - v1.0.13+ Bayesian baseline (z-score → spend/mean Hill normalization)
- v1.1.1     - Phase 1.1 hierarchical adstock decay (logit-normal, sampled per channel)
- v1.2       - v1.0.16 baseline (post-audit fixes, three-way alignment)
- v1.3       - Trust Level 3 (Brand vs Performance Split, channel_categories field)
- v2.0       - v1.2.0 (Awareness KPI + Weibull learnable). Additive optional fields:
               * kpi_type, kpi_likelihood, ceiling
               * awareness_aggregation_mode
               * channel_adstock_types, weibull_params_per_channel
               * comparison_baseline_posterior (для ROI shift dual-posterior)
               * feature_flags_used (telemetry)
               * Phase 2 additions (Planning Mode, audit pass 2 2026-05-02):
                 - training_granularity: 'D'|'W'|'M'|'Q'|'Y' (auto-detected)
                 - train_x_norm_quantiles: dict[channel, {p50,p75,p90,p95,p99}]
                 - seasonality_detected: dict | None ({period, autocorr})
                 Pickles trained pre-Phase-2 lack these fields; G2 inference
                 helpers (infer_*_at_load) compute lazily on first need.
                 S8 lock - no reserved future fields, additive evolution only.
- v2.0.0     - Aurora MMM Optimizer v2.0.0 (ADR-019, PRE_FLIGHT N13). Additive
               diagnostics caching fields (all None/empty defaults for v1.3.x
               backward compat):
               * signed_factor_priors_used: dict — priors applied per factor
               * holiday_dummies_injected: list[str] — 12 hardcoded holiday names
               * mcmc_diagnostics: dict — r_hat_max, ess_min, per-param breakdown
               * backtest_results: dict — holdout metrics + predictions
               * ppc_results: dict — R², Durbin-Watson, residuals, predicted
               * sensitivity_tornado_cache: dict | None — on-demand cache
               * analysis_mode: str — 'roi'|'effectiveness'|'mixed'
               Methods: save_v20_diagnostics(), load_v20_diagnostics(),
               clear_sensitivity_cache(), is_v20_compatible().
               Atomic save: temp file + rename (OS-level atomicity).
"""

from __future__ import annotations

import logging
import os
import pickle
import re
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sprint Buffer #43 (2026-05-23): observable counter for y_actual repair operations.
# INV-27 — operator observability. Counter incremented в _repair_y_actual_against_data_file
# per terminal state. Exposed via get_repair_stats() / reset_repair_stats() для unit tests
# + future /metrics endpoint. Module-level state acceptable: sidecar single-process, repair
# не реентрабелен (called sequentially из load_model_with_compat).
_REPAIR_COUNTERS: dict[str, int] = {
    'repaired': 0,           # successful repair applied (y_actual mutated)
    'skipped_current': 0,    # pickle length == data_file rows (no-op, expected steady state)
    'skipped_missing_meta': 0,  # data_file / kpi_column absent в config
    'skipped_file_gone': 0,  # data_file path не существует на диске
    'skipped_col_missing': 0,  # kpi_column отсутствует в data_file columns
    'skipped_nan_values': 0,   # data_file KPI col contains NaN — preserve pickle
    'skipped_shorter_file': 0,  # data_file rows ≤ pickle y_actual (user trimmed)
    'skipped_empty_pickle': 0,  # y_actual length 0 — different bug
    'skipped_read_error': 0,   # exception при pandas read_excel/read_csv
    'skipped_unsized': 0,      # y_actual neither sized nor None (scalar/generator)
}


def get_repair_stats() -> dict[str, int]:
    """Return snapshot of y_actual repair counters since process start (или last reset)."""
    return dict(_REPAIR_COUNTERS)


def reset_repair_stats() -> None:
    """Reset all repair counters к 0. Test helper — production не вызывает."""
    for k in _REPAIR_COUNTERS:
        _REPAIR_COUNTERS[k] = 0


# Semantic version comparison helper (avoids stdlib `packaging` dep)
_VERSION_RE = re.compile(r'(\d+)\.(\d+)(?:\.(\d+))?')


def _parse_version(v: str) -> tuple[int, int, int]:
    """Parse 'X.Y' or 'X.Y.Z' (with optional suffix like '1.0-ols') → (X, Y, Z) tuple.

    Returns (0, 0, 0) для unparseable strings (defensive default - treated as
    legacy pre-v1.0).

    Why: string `<` comparison broken - '1.10' < '1.3' lexicographically (audit fix).
    """
    if not isinstance(v, str):
        return (0, 0, 0)
    m = _VERSION_RE.match(v)
    if not m:
        return (0, 0, 0)
    major, minor, patch = m.groups()
    return (int(major), int(minor), int(patch) if patch else 0)


def load_model_with_compat(model_path: Path | str) -> dict[str, Any]:
    """Load модель с backward-compat fields injected.

    v2.1.0: маршрутизирует между двумя форматами:
      * `aurora-model` (ZIP, безопасный) — новые модели начиная с v2.1.0
      * `pickle` (legacy) — модели обученные в v2.0.x и ранее

    Trust Level 3 contract:
    - `channel_categories` always present (empty dict если pre-v1.3 pickle).
    - `model_version` always present (default '1.0' если field missing - legacy).
    - Old fields preserved verbatim.

    NB: Не infers categories автоматически - оставляет `{}` для downstream choice.
    Decomposer/optimizer/etc. могут сами вызвать `infer_categories_heuristic()`
    если им нужны категории, но НЕ persists in pickle (читаем-only access pattern).

    Raises:
        FileNotFoundError если path не существует.
        pickle.UnpicklingError на corrupt legacy pickle.
        SafeModelFormatError на corrupt aurora-model archive.
    """
    p = Path(model_path)
    from engines.persistence_safe import detect_format, load_model_safe

    fmt = detect_format(p)

    if fmt == 'aurora-model':
        # Новый безопасный формат: zip CRC32 + manifest sha256_data/sha256_arrays
        # дают tamper detection внутри ZIP. SH-AM-12: SHA-256 sidecar
        # тоже верифицируется, если присутствует — добавочная защита.
        integrity_ok, integrity_reason = verify_pkl_sha256_sidecar(p)
        if not integrity_ok:
            logger.critical(
                'aurora-model integrity FAILED для %s: %s. Загружается но возможна '
                'tamper. SH-AM-12.', p, integrity_reason,
            )
        model_data = load_model_safe(p)
    elif fmt == 'pickle':
        # Legacy pickle — verify SHA-256 sidecar перед deserialize.
        # Pickle.load deserializes arbitrary bytecode → если malicious `.pkl`
        # подменён в shared folder, RCE при load. Sidecar hash — short-term
        # mitigation. Полный переход на aurora-model устраняет RCE-surface.
        integrity_ok, integrity_reason = verify_pkl_sha256_sidecar(p)
        if not integrity_ok:
            logger.critical(
                'pickle integrity FAILED для %s: %s. Pickle загружается но возможна '
                'tamper / RCE. Phase 1 — warn only; Phase 2+ может strict-block.',
                p, integrity_reason,
            )
        with open(p, 'rb') as f:
            model_data = pickle.load(f)

        # Phase 2.7 followup audit fix (2026-05-24): repair y_actual ДО migration,
        # чтобы saved aurora-model имел repaired full series. Без этого ordering
        # migration сохраняла truncated y_actual → каждый subsequent load
        # re-triggered repair → data_file re-read perpetually (~100ms per endpoint
        # hit для legacy projects). Repair idempotent — function-end call (для
        # aurora-model branch) автоматически no-op после persistence.
        _repair_y_actual_against_data_file(model_data)

        # Lazy migration: переписываем legacy pickle в aurora-model сразу при load.
        # Это устраняет окно атаки — следующий load уже идёт через безопасный путь.
        # Errors при миграции не должны мешать загрузке (read-only FS, EACCES и т.д.).
        try:
            _lazy_migrate_to_safe(p, model_data)
        except Exception as exc:
            logger.warning(
                'Lazy migration legacy pickle %s в aurora-model не удалась: %s. '
                'Загрузка продолжается, модель работает в read-only режиме до '
                'следующего успешного save.',
                p, exc,
            )
    else:
        # Неопознанный формат — не существует, пустой, или garbage.
        if not p.exists():
            raise FileNotFoundError(f'Файл модели не найден: {p}')
        raise pickle.UnpicklingError(
            f'{p} не aurora-model и не pickle. Файл повреждён или неподдерживаемого формата.'
        )

    # Defensive defaults (v1.0 legacy may lack these fields entirely)
    model_data.setdefault('model_version', '1.0')
    model_data.setdefault('channel_categories', {})

    # v2.0 additive fields (default к pre-v2.0 behavior)
    model_data.setdefault('kpi_type', 'sales')
    model_data.setdefault('kpi_likelihood', 'normal')
    model_data.setdefault('awareness_aggregation_mode', None)
    model_data.setdefault('channel_adstock_types', {})       # default per-channel = 'geometric'
    model_data.setdefault('weibull_params_per_channel', {})  # learned (peak_week, tail_decay)
    model_data.setdefault('comparison_baseline_posterior', None)  # для ROI shift toggle
    model_data.setdefault('feature_flags_used', [])          # telemetry

    # Phase 2 (Planning Mode) - pre-Phase-2 pickles get None defaults; G2 inference
    # helpers compute lazily when planning mode actually queries them.
    model_data.setdefault('training_granularity', None)
    model_data.setdefault('train_x_norm_quantiles', None)
    model_data.setdefault('seasonality_detected', None)
    # Автосезонность (2026-07-04): что инжектировано как Фурье-контроли (period/K/
    # columns) — decomposer переинжектит. None для pre-фичи pickle (модели до
    # автосезонности праздники учитывали, Фурье-волну нет — decomposer их пропустит).
    model_data.setdefault('fourier_seasonality', None)

    # v1.3.0 additive fields (per ADR-017 - schema bump skipped, in-memory inject only).
    # Defaults match v1.2 behavior: monetary KPI, all channels in ₽, mode=roi, no goal-seek history.
    _inject_v13_defaults(model_data)

    # v2.0.0 additive diagnostics caching fields (PRE_FLIGHT N13, ADR-019 §10).
    # All default to None/empty for v1.3.x backward compat — never crash on absent field.
    _inject_v20_defaults(model_data)

    # Phase 2.7 followup (2026-05-24): repair truncated y_actual in legacy pickles.
    # No-op для current pickles + для cases where data_file inaccessible / shorter.
    _repair_y_actual_against_data_file(model_data)

    return model_data


def _repair_y_actual_against_data_file(model_data: dict[str, Any]) -> None:
    """Phase 2.7 followup — repair truncated y_actual in legacy pickles by reading data_file.

    Aurora Econometrica < v1.0.16 (некоторые training paths) saved truncated `y_actual`
    к pickle — last full year only (52 weeks вместо 156 за 3 года для Кагоцел и т.п.).
    `/compute/forecast-context` endpoint reads `train_n = len(model_data['y_actual'])`,
    из-за чего customer-facing planning budget suggestions использовали wrong horizon
    coefficient (52/52 = 1.0 при customer expectation 52/156 = 0.333).

    Frontend OptimizeStep.svelte:1311 уже имеет workaround через
    `dData.time_series.dates.length`, но root fix живёт здесь — он эликвидирует
    discrepancy для всех downstream consumers (planning preview, scenario CI,
    seasonality detection при load).

    Repair policy:
    - `len(y_actual) < data_file row count` → repair (legacy truncation suspected).
    - `len(y_actual) == data_file row count` → no-op (current pickle correct).
    - `len(y_actual) > data_file row count` → no-op (user trimmed data_file
      post-training; pickle = canonical training state, не повреждать).
    - `data_file` отсутствует/перемещён/корректно нечитаем → no-op (preserve pickle).

    Idempotent: повторный вызов на repaired pickle = no-op (length matches data_file).

    Side effects:
        Logs warning при repair applied (operator visibility).
        Mutates `model_data['y_actual']` in place (in-memory only — pickle на диске
        не перезаписывается helper'ом; следующий `save_model_safe` зафиксирует).

    Sister к INV-17 (SSOT для UI-displayed metrics): forecast_context endpoint
    train_n_periods derived от единственного pickle field, repair обеспечивает
    consistent semantics с frontend workaround.

    Reference: `project_econometrica_y_actual_truncation_investigation.md` (2026-05-04).
    """
    y_actual = model_data.get('y_actual')
    # Defensive: legacy pickles могут saved y_actual как list / numpy array / tuple.
    # `not np.ndarray` raises ValueError (not bool truthy), `not list[0.0]` is False
    # (truthy non-empty). Explicit length check survives all container types.
    try:
        y_actual_len = len(y_actual) if y_actual is not None else 0
    except TypeError:
        _REPAIR_COUNTERS['skipped_unsized'] += 1
        return  # not sized (scalar / generator) — different bug.
    if y_actual_len == 0:
        _REPAIR_COUNTERS['skipped_empty_pickle'] += 1
        return  # truly empty pickle — different bug, не Phase 2.7 scope.

    config = model_data.get('config') or {}
    data_file = config.get('data_file')
    kpi_col = config.get('kpi_column') or config.get('kpi_col')
    if not data_file or not kpi_col:
        _REPAIR_COUNTERS['skipped_missing_meta'] += 1
        return  # cannot verify без data_file metadata.

    try:
        data_path = Path(data_file)
        if not data_path.exists():
            _REPAIR_COUNTERS['skipped_file_gone'] += 1
            return  # file deleted/moved post-training → preserve pickle state.
        import pandas as _pd
        if str(data_file).lower().endswith(('.xlsx', '.xls')):
            df = _pd.read_excel(data_file)
        else:
            df = _pd.read_csv(data_file)
        if kpi_col not in df.columns:
            _REPAIR_COUNTERS['skipped_col_missing'] += 1
            return  # column renamed/dropped → preserve pickle.
        # Apply merge_rules для consistency с modeler.py path (merge_rules затрагивают
        # media columns, не KPI, но порядок строк не меняется → row count safe).
        try:
            from utils.merge_rules import apply_merge_rules as _apply_merge
            _apply_merge(df, config.get('merge_rules'))
        except Exception:
            pass  # merge_rules optional — fallback к raw df row count.
        kpi_series = df[kpi_col]
        # NaN-KPI tail filter: обрезаем ТОЛЬКО хвост медиаплана (trailing NaN после
        # конца истории), иначе хвост раздул бы y_actual и дал ложный repair. Серединные
        # NaN СОХРАНЯЕМ — их наличие = порча истории, детектируется ниже (аудит-фикс
        # 2026-05-24). ⚠️ Прежняя notna()-маска убирала И серединные NaN → детектор
        # порчи не срабатывал → silent corruption y_actual (регресс, чинится 2026-07-13).
        # Invariant: хвоста нет → last_valid = конец ряда → loc[:last_valid] = no-op.
        try:
            last_valid = kpi_series.last_valid_index()
            if last_valid is not None:
                kpi_series = kpi_series.loc[:last_valid]
        except AttributeError:
            pass  # non-Series fallback — defensive
        try:
            if kpi_series.isna().any():
                _REPAIR_COUNTERS['skipped_nan_values'] += 1
                logger.warning(
                    'y_actual repair skipped: data_file column %r contains %d NaN values '
                    'even after tail filter. Preserving pickle y_actual (length=%d).',
                    kpi_col, int(kpi_series.isna().sum()), y_actual_len,
                )
                return
        except AttributeError:
            pass  # non-Series fallback — defensive, не блокирует
        full_y = kpi_series.astype(float).tolist()
        if len(full_y) == y_actual_len:
            _REPAIR_COUNTERS['skipped_current'] += 1
            return  # current pickle — lengths match.
        if len(full_y) < y_actual_len:
            _REPAIR_COUNTERS['skipped_shorter_file'] += 1
            return  # data_file shorter — user trimmed post-training; preserve pickle.
        _REPAIR_COUNTERS['repaired'] += 1
        logger.warning(
            'y_actual repair: legacy pickle has y_actual length=%d, data_file has %d rows. '
            'Replacing с full series для consistent train_n_periods (Phase 2.7 followup).',
            y_actual_len, len(full_y),
        )
        model_data['y_actual'] = full_y
    except Exception as exc:
        _REPAIR_COUNTERS['skipped_read_error'] += 1
        logger.warning('y_actual repair skipped (data_file read error): %s', exc)


def _lazy_migrate_to_safe(legacy_path: Path, model_data: dict[str, Any]) -> bool:
    """v2.1.0: переписывает legacy pickle в aurora-model сразу при load.

    Безопасность: устраняет окно атаки между текущим load и следующим save.
    Если новый файл записан успешно — следующий load идёт через безопасный путь
    (json.load + np.load с allow_pickle=False), без pickle.load.

    Backup сохраняется с суффиксом `.pre_safe_migration` рядом с исходником.

    Идемпотентность: повторный вызов на уже мигрированный файл no-op (formato
    aurora-model — выходим без записи).

    Args:
        legacy_path: путь к .pkl файлу.
        model_data: уже загруженный dict (избегаем повторный pickle.load).

    Returns:
        True если миграция выполнена, False если no-op (уже aurora-model).

    Raises:
        OSError на disk failure (caller swallows + logs).
    """
    from engines.persistence_safe import detect_format, save_model_safe

    # Двойная проверка — caller мог вызвать миграцию на свежеобновлённом файле.
    if detect_format(legacy_path) == 'aurora-model':
        return False

    # Backup legacy pickle перед перезаписью. shutil.copy2 сохраняет mtime,
    # что важно для диагностики «когда модель была впервые обучена».
    backup = legacy_path.with_suffix(legacy_path.suffix + '.pre_safe_migration')
    if not backup.exists():
        import shutil
        shutil.copy2(legacy_path, backup)
        logger.info('Lazy migration: backup сохранён %s', backup)

    # Запись в новом формате. save_model_safe атомарно заменяет файл
    # через temp+rename, так что неуспех не повредит данные.
    save_model_safe(model_data, legacy_path, extra_manifest={
        'migrated_from': 'legacy_pickle',
        'migration_kind': 'lazy_on_load',
    })
    # Обновляем SHA-256 sidecar для нового файла (legacy sidecar становится невалидным).
    write_pkl_sha256_sidecar(legacy_path)
    logger.info('Lazy migration: %s переписан в aurora-model', legacy_path)
    return True


def _inject_v13_defaults(model_data: dict[str, Any]) -> None:
    """Inject v1.3.0 additive fields with defaults derived from v1.2 state.

    Per ADR-017 (Bundle schema v1.3 additive). Mutates dict in place.

    - kpi_kind: derived from kpi_type via registry. 'sales' → monetary, 'awareness' → proportional,
      count KPIs → count.
    - per_channel_input: dict {channel: 'monetary'|'physical'}. Derived from старый
      analysisObjective field (frontend) или by default - все каналы как monetary.
    - derived_mode: 'roi'|'effectiveness'|'manual'. Computed from per_channel_input.
    - value_per_count_unit, label, source: None defaults; populated в Validate UI для count KPIs.
    - goal_seek_history: append-only log, empty list default.
    """
    kpi_type = model_data.get('kpi_type') or 'sales'

    # kpi_kind from registry (graceful fallback to 'monetary' if KPI not registered).
    if 'kpi_kind' not in model_data:
        try:
            from utils.kpi_registry import get_kpi_config
            kpi_kind = get_kpi_config(kpi_type).kpi_kind
        except (ValueError, ImportError):
            kpi_kind = 'monetary'  # safe fallback
        model_data['kpi_kind'] = kpi_kind

    # per_channel_input: default - all media columns as 'monetary'.
    if 'per_channel_input' not in model_data:
        config = model_data.get('config') or {}
        # Audit fix v1.3.0: explicit null-check (was: `config.get('media_columns', []) or []`
        # could mask `media_columns: None` corruption).
        media_cols_raw = config.get('media_columns')
        media_cols = list(media_cols_raw) if media_cols_raw else []
        # Старый frontend store analysisObjective не сохранялся в pickle, но мог быть
        # передан через config['analysis_objective'] (legacy field).
        legacy_objective = config.get('analysis_objective', 'roi')
        if legacy_objective == 'effectiveness':
            default_metric = 'physical'
        else:
            default_metric = 'monetary'  # 'roi' и 'manual' → default monetary (manual override приходит из bundle)
        model_data['per_channel_input'] = {ch: default_metric for ch in media_cols}

    # derived_mode: lazy compute через mode_inference if absent.
    if 'derived_mode' not in model_data:
        try:
            from utils.mode_inference import derive_mode
            model_data['derived_mode'] = derive_mode(model_data['per_channel_input'])
        except (ValueError, ImportError):
            model_data['derived_mode'] = 'roi'  # safe fallback

    # value_per_count_unit: None default; populated by user in Validate UI.
    model_data.setdefault('value_per_count_unit', None)
    model_data.setdefault('value_per_count_unit_label', '')
    model_data.setdefault('value_per_count_unit_source', None)  # 'auto'|'manual'|'imported'|None

    # goal_seek_history: append-only log of past goal-seek runs.
    model_data.setdefault('goal_seek_history', [])

    # safe_corridor_cache: lazy invalidate on retrain.
    model_data.setdefault('safe_corridor_cache', None)


def _inject_v20_defaults(model_data: dict[str, Any]) -> None:
    """Inject v2.0.0 additive diagnostics fields with None/empty defaults.

    Per ADR-019 §10 + PRE_FLIGHT N13. Mutates dict in-place.

    All fields default to None or empty — v1.3.x pickles load silently without
    these fields; callers check `is_v20_compatible()` before accessing them.

    Fields:
    - signed_factor_priors_used: dict of {factor_name: prior_spec} recorded at
      train time so diagnostics UI can show «which prior was applied».
    - holiday_dummies_injected: list of holiday dummy column names that were
      actually present in the training dataset (subset of the 12 hardcoded РФ
      holidays). Useful for diagnostics display + certificate.
    - mcmc_diagnostics: dict with keys r_hat_max, ess_min, r_hat_per_param,
      ess_per_param. Cached so Diagnostics page loads instantly post Save/Load.
    - backtest_results: dict from engines/backtest.py run_backtest(). Keys:
      holdout_periods, metrics (mape/rmse/r2), evaluation (status/message),
      predictions (actual/predicted lists).
    - ppc_results: dict from posterior predictive check. Keys: r2,
      durbin_watson, residuals (list), predicted (list).
    - sensitivity_tornado_cache: output of compute_sensitivity_tornado(),
      or None if not yet computed / explicitly invalidated.
    - analysis_mode: 'roi'|'effectiveness'|'mixed' — v2.0.0 explicit mode
      recorded at train time (ADR-019). None для pre-v2.0.0 pickles.
    """
    model_data.setdefault('signed_factor_priors_used', {})
    model_data.setdefault('holiday_dummies_injected', [])
    model_data.setdefault('mcmc_diagnostics', None)
    model_data.setdefault('backtest_results', None)
    model_data.setdefault('ppc_results', None)
    model_data.setdefault('sensitivity_tornado_cache', None)
    model_data.setdefault('analysis_mode', None)


def get_kpi_type(model_data: dict[str, Any]) -> str:
    """Return KPI type из pickle. Default 'sales' для backward compat."""
    return str(model_data.get('kpi_type') or 'sales')


def is_awareness_model(model_data: dict[str, Any]) -> bool:
    """True если pickle обучен в awareness mode."""
    return get_kpi_type(model_data) == 'awareness'


def get_adstock_type(model_data: dict[str, Any], channel: str) -> str:
    """Return adstock type для конкретного канала.

    Returns:
        'geometric' (default) or 'weibull'.
    """
    types = model_data.get('channel_adstock_types') or {}
    return str(types.get(channel) or 'geometric')


def get_weibull_params(
    model_data: dict[str, Any], channel: str
) -> dict[str, float] | None:
    """Return learned Weibull params для канала, None если geometric.

    Defensive: если adstock_type='weibull' но params missing - log warning
    + return None (downstream silently falls back к geometric - better than crash,
    but warning surfaces malformed pickle).

    Returns:
        {'peak_week_median', 'tail_decay_median', 'lam_median', 'k_median'} or None.
    """
    if get_adstock_type(model_data, channel) != 'weibull':
        return None
    params = model_data.get('weibull_params_per_channel') or {}
    channel_params = params.get(channel)
    if channel_params is None:
        # Malformed pickle: declares Weibull но params missing
        import warnings
        warnings.warn(
            f"Channel '{channel}' marked as Weibull в pickle, но params missing в "
            f"weibull_params_per_channel. Falling back к geometric. "
            f"Возможна corrupted pickle или incomplete training.",
            RuntimeWarning,
            stacklevel=2,
        )
    return channel_params


def has_baseline_posterior(model_data: dict[str, Any]) -> bool:
    """True если pickle содержит cached single-prior baseline для ROI shift comparison."""
    return model_data.get('comparison_baseline_posterior') is not None


def get_baseline_posterior(model_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return cached baseline posterior summary, или None."""
    return model_data.get('comparison_baseline_posterior')


def get_feature_flags(model_data: dict[str, Any]) -> list[str]:
    """Return telemetry feature flags used during training."""
    flags = model_data.get('feature_flags_used') or []
    return list(flags)


def get_channel_categories(
    model_data: dict[str, Any],
    fallback_heuristic: bool = True,
) -> dict[str, str]:
    """Get channel categories из pickle, optionally with heuristic fallback.

    Args:
        model_data: loaded pickle dict
        fallback_heuristic: если True и categories пусты - derive из имён каналов
                          через auto-suggestion confidence ≥ 0.7

    Returns:
        {channel_name: 'brand'|'performance'|'mixed'}
    """
    categories = dict(model_data.get('channel_categories') or {})
    if categories:
        return categories
    if not fallback_heuristic:
        return {}
    # Lazy import (avoid cyclic если utils imports from engines).
    # v2.1.0 (пилот 2026-05-16, sidecar 500 fix): абсолютный путь
    # `from econometrica.utils...` падал с ImportError на шаге Оптимизация,
    # потому что sidecar запускается с cwd=sidecar/econometrica и пакет
    # «econometrica» не зарегистрирован на sys.path. Relative-импорт
    # совпадает с конвенцией остальных модулей в этом файле.
    from utils.channel_categorization import infer_categories_heuristic
    media_cols = model_data.get('media_columns') or model_data.get('config', {}).get('media_columns', [])
    if not media_cols:
        return {}
    return infer_categories_heuristic(list(media_cols))


# ─── Phase 2 (Planning Mode) - at-load-time inference helpers (G2 plan gap) ───
#
# For pre-Phase-2 customer pickles (v1.3 = current ship), the new Phase 2
# fields are absent. Rather than force re-train, infer lazily when planning
# mode actually queries them. Caller is responsible for caching на pickle
# basis (computation is non-trivial для quantiles + seasonality).
# ──────────────────────────────────────────────────────────────────────────


def get_training_granularity(model_data: dict[str, Any]) -> str | None:
    """Phase 2 - return persisted training_granularity или infer from data_file.

    Persisted-first; falls back к infer_granularity_at_load() для legacy pickles.
    Returns None если cannot infer (no data file accessible, e.g., moved/deleted).
    """
    persisted = model_data.get('training_granularity')
    if persisted:
        return str(persisted)
    return infer_granularity_at_load(model_data)


def infer_granularity_at_load(model_data: dict[str, Any]) -> str | None:
    """G2 - infer granularity from model_data.config.data_file at load time.

    Heavy I/O - каллер should cache. Returns None when data_file inaccessible.
    """
    config = model_data.get('config') or {}
    data_file = config.get('data_file')
    date_col = config.get('date_column', 'date')
    if not data_file:
        return None
    try:
        import pandas as pd
        df = pd.read_excel(data_file) if str(data_file).endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
        if date_col not in df.columns:
            return None
        from utils.forecast_validation import detect_granularity
        result = detect_granularity(df[date_col])
        return result['granularity'] if result['confidence'] >= 0.4 else None
    except Exception:
        return None


def get_seasonality(model_data: dict[str, Any]) -> dict | None:
    """Phase 2 - return persisted seasonality_detected или infer at load.

    Persisted-first; falls back к infer_seasonality_at_load() для legacy pickles.
    """
    persisted = model_data.get('seasonality_detected')
    if persisted is not None:
        return persisted if isinstance(persisted, dict) else None
    return infer_seasonality_at_load(model_data)


def infer_seasonality_at_load(model_data: dict[str, Any]) -> dict | None:
    """G2 - infer seasonality from training y_actual at load time.

    Uses y_actual stored в diagnostics.actual_vs_predicted (always present
    в v1.1+ pickles). Returns None when unavailable.
    """
    diagnostics = model_data.get('diagnostics') or {}
    avp = diagnostics.get('actual_vs_predicted') or {}
    y_actual = avp.get('actual')
    if not y_actual:
        return None
    granularity = get_training_granularity(model_data) or 'W'
    try:
        from utils.forecast_validation import detect_seasonality
        return detect_seasonality(y_actual, granularity=granularity)
    except Exception:
        return None


def get_x_norm_quantiles(
    model_data: dict[str, Any], channel: str,
) -> dict[str, float] | None:
    """Phase 2 - return persisted x_norm quantiles per channel или infer.

    Persisted-first; falls back к infer_x_norm_quantiles_at_load() для legacy.
    Returns None when channel missing OR inference impossible (no posterior + raw spend).
    """
    persisted = model_data.get('train_x_norm_quantiles')
    if persisted and channel in persisted:
        return persisted[channel]
    inferred = infer_x_norm_quantiles_at_load(model_data)
    return inferred.get(channel) if inferred else None


def infer_x_norm_quantiles_at_load(
    model_data: dict[str, Any],
) -> dict[str, dict[str, float]] | None:
    """G2 - recompute x_norm quantiles from training adstock + posterior decay.

    For each channel:
      adstock_series = geometric_adstock(raw_train_spend, decay_posterior_mean)
      x_norm_series = adstock_series / adstock_mean_posterior
      quantiles = {p50, p75, p90, p95, p99}

    Heavy: reads training data, applies adstock per channel. Caller cache.
    Returns None when raw spend OR posterior decay inaccessible.
    """
    config = model_data.get('config') or {}
    data_file = config.get('data_file')
    if not data_file:
        return None
    channel_params = model_data.get('channel_params') or {}
    if not channel_params:
        return None

    try:
        import pandas as pd
        df = pd.read_excel(data_file) if str(data_file).endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
        from utils.merge_rules import apply_merge_rules
        apply_merge_rules(df, config.get('merge_rules'))
        from utils.adstock import apply_adstock
        from utils.forecast_validation import compute_x_norm_quantiles
    except Exception:
        return None

    out: dict[str, dict[str, float]] = {}
    for col, p in channel_params.items():
        if col not in df.columns:
            continue
        raw_spend = df[col].fillna(0).values.astype(float)
        if raw_spend.size == 0:
            continue
        decay = p.get('decay')
        a_type = get_adstock_type(model_data, col)
        params = {'alpha': float(decay)} if decay is not None else None
        try:
            adstock_series = apply_adstock(raw_spend, a_type, params)
        except Exception:
            continue
        # Mean - prefer adstock_mean_posterior, fallback к media_means
        norm = (model_data.get('normalization') or {})
        mean_post = p.get('adstock_mean_posterior')
        if mean_post is not None:
            mean = float(mean_post)
        else:
            mean = float(norm.get('media_means', {}).get(col, 1.0) or 1.0)
        if mean <= 0:
            continue
        out[col] = compute_x_norm_quantiles(adstock_series, mean)
    return out if out else None


def is_hierarchical_model(model_data: dict[str, Any]) -> bool:
    """True если pickle обучен hierarchical (v1.3+ с непустыми categories).

    Audit fix (2026-04-28): semantic version compare - string `<` ломалось на '1.10'
    vs '1.3' (lex order: '1.10' < '1.3' = True, semantically False).
    """
    version = _parse_version(str(model_data.get('model_version') or ''))
    if version < (1, 3):
        return False
    cats = model_data.get('channel_categories') or {}
    if not cats:
        return False
    n_brand = sum(1 for c in cats.values() if c == 'brand')
    n_perf = sum(1 for c in cats.values() if c == 'performance')
    return n_brand >= 2 or n_perf >= 2


# ─── v2.0.0 Diagnostics Caching API (ADR-019 §10, PRE_FLIGHT N13) ────────────
#
# After training completes the sidecar writes diagnostics into the same pickle
# via save_v20_diagnostics(). The UI then reads them back instantly on
# Save/Load without re-running MCMC or backtest. Fields are additive — v1.3.x
# pickles simply lack them (load_model_with_compat injects None defaults).
#
# Atomic write pattern: dump to <file>.tmp then os.replace() — POSIX-atomic
# on Linux (rename(2)); on Windows replace() uses MoveFileExW which is
# effectively atomic for same-volume moves. Avoids corrupt pickle on crash.
# ─────────────────────────────────────────────────────────────────────────────


def _model_path_for_project(project_dir: str | Path) -> Path:
    """Return canonical latest.pkl path for a project directory."""
    return Path(project_dir) / 'models' / 'latest.pkl'


def is_v20_compatible(model_data: dict[str, Any]) -> bool:
    """Return True если pickle был сохранён движком v2.0.0+.

    Позволяет UI показать banner «Модель обучена в v1.3.x. Диагностика
    недоступна — рекомендуется re-train для full v2.0.0 features.» только
    для старых pickles, и не показывать для v2.0.0+ pickles.

    Contract:
    - v2.0.0+ pickle: model_version >= (2, 0, 0) AND analysis_mode is not None.
    - v1.3.x pickle: either condition fails.

    Note: version field '2.0' (two-part) сравнивается как (2, 0, 0) через
    _parse_version, so '2.0' и '2.0.0' оба считаются compatible.
    """
    version = _parse_version(str(model_data.get('model_version') or ''))
    if version < (2, 0, 0):
        return False
    # Additional guard: analysis_mode must be explicitly set (not just version bump)
    return model_data.get('analysis_mode') is not None


def _pkl_sha256_sidecar_path(pkl_path: Path) -> Path:
    """Canonical sidecar path для pickle SHA-256 hash file."""
    return pkl_path.with_suffix(pkl_path.suffix + '.sha256')


def write_pkl_sha256_sidecar(pkl_path: Path) -> str:
    """C-05a: compute SHA-256 of pickle file + write к sidecar file.

    Called immediately после `os.replace(tmp, target)` finalize. Provides
    integrity baseline для tamper detection при subsequent pickle.load.

    Returns SHA-256 hex digest.
    """
    from utils.safe_io import compute_file_sha256
    sha = compute_file_sha256(pkl_path)
    sidecar = _pkl_sha256_sidecar_path(pkl_path)
    # Atomic-ish: write tmp then replace. Sidecar self не критичен — если
    # write fails, load_model_with_compat downgrades к 'no sidecar' warn.
    tmp = sidecar.with_suffix(sidecar.suffix + '.tmp')
    try:
        tmp.write_text(sha + '\n', encoding='utf-8')
        os.replace(tmp, sidecar)
    except OSError as exc:
        logger.warning('pkl sidecar hash write failed: %s', exc)
    return sha


def verify_pkl_sha256_sidecar(pkl_path: Path) -> tuple[bool, str]:
    """C-05a: verify pickle SHA-256 matches sidecar file.

    Returns:
        (ok, reason). ok=True если match OR sidecar absent (pre-Phase-2 pickle).
        ok=False только если sidecar exists и hash mismatch — потенциальный
        tamper / RCE attack signal per Aurora Launch retro 2026-05-15.
    """
    from utils.safe_io import compute_file_sha256
    sidecar = _pkl_sha256_sidecar_path(pkl_path)
    if not sidecar.exists():
        return True, 'no sidecar (pre-Phase-2 pickle, legacy compat)'
    try:
        stored = sidecar.read_text(encoding='utf-8').strip()
    except OSError as exc:
        return True, f'sidecar read failed: {exc} (degraded)'
    if not stored or len(stored) != 64:
        return False, f'malformed sidecar content: {stored!r}'
    actual = compute_file_sha256(pkl_path)
    if actual == stored:
        return True, 'pickle integrity OK'
    return False, f'pickle hash MISMATCH: stored={stored[:8]}.., actual={actual[:8]}..'


def _normalize_numpy(obj: Any) -> Any:
    """H-05: Recursively convert numpy types к Python primitives.

    Saved diagnostics dicts (backtest_results, ppc_results) могут содержать
    numpy.ndarray, numpy.float64, numpy.int64 etc. — эти типы не JSON-serializable.
    После save_v20_diagnostics → load_v20_diagnostics → JSONResponse(...) FastAPI
    raises TypeError. Применяется при save (clean storage) + при load (defensive
    для legacy pickles).
    """
    import numpy as np
    if isinstance(obj, dict):
        return {k: _normalize_numpy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_numpy(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        # NaN / Inf — JSON-illegal. Return None для downstream safety.
        v = float(obj)
        if v != v or v in (float('inf'), float('-inf')):
            return None
        return v
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def save_v20_diagnostics(project_dir: str | Path, diagnostics: dict[str, Any]) -> None:
    """Append v2.0.0 diagnostics into existing latest.pkl atomically.

    Reads the current pickle, merges diagnostics fields, bumps model_version
    to '2.0.0', then atomically replaces the file via temp-rename pattern.

    Args:
        project_dir: project directory containing models/latest.pkl
        diagnostics: dict with any subset of v2.0.0 diagnostics fields:
            - signed_factor_priors_used: dict
            - holiday_dummies_injected: list[str]
            - mcmc_diagnostics: dict with r_hat_max, ess_min,
              r_hat_per_param, ess_per_param
            - backtest_results: dict with holdout_periods, metrics,
              evaluation, predictions
            - ppc_results: dict with r2, durbin_watson, residuals, predicted
            - sensitivity_tornado_cache: dict | None
            - analysis_mode: 'roi' | 'effectiveness' | 'mixed'
          Unknown keys are ignored (strict allowlist to prevent field pollution).

    Raises:
        FileNotFoundError: если latest.pkl отсутствует.
        pickle.UnpicklingError: на corrupt pickle.
        OSError: на disk I/O failure.
    """
    _V20_ALLOWED_FIELDS = frozenset({
        'signed_factor_priors_used',
        'holiday_dummies_injected',
        'mcmc_diagnostics',
        'backtest_results',
        'ppc_results',
        'sensitivity_tornado_cache',
        'analysis_mode',
    })

    model_path = _model_path_for_project(project_dir)
    if not model_path.exists():
        raise FileNotFoundError(
            f"latest.pkl не найден: {model_path}. "
            f"Обучите модель перед сохранением диагностики."
        )

    # C-02 multi-tab race protection (audit H-06): backtest и sensitivity
    # invalidation могут стрелять одновременно → второй reads pre-write state,
    # перетирает первый. Lock на entire read-modify-write.
    from utils.file_lock import project_lock
    with project_lock(Path(project_dir), timeout=5.0):
        # Load existing pickle (через compat helper чтобы v1.3 defaults уже были)
        model_data = load_model_with_compat(model_path)

        # Merge only allowed fields (strict allowlist prevents field pollution)
        # H-05: sanitize numpy types к Python primitives перед storage чтобы
        # downstream JSONResponse не падал на ndarray / float32 / int64.
        applied_fields: list[str] = []
        for key, value in diagnostics.items():
            if key in _V20_ALLOWED_FIELDS:
                model_data[key] = _normalize_numpy(value)
                applied_fields.append(key)
            else:
                logger.warning(
                    "save_v20_diagnostics: unknown field %r ignored (allowlist)", key
                )

        # Bump model_version to '2.0.0' (additive — old code ignores new fields)
        model_data['model_version'] = '2.0.0'

        # v2.1.0: переход на безопасный формат aurora-model.
        # save_model_safe сам выполняет атомарную запись (temp + os.replace).
        from engines.persistence_safe import save_model_safe
        save_model_safe(model_data, model_path)
        # SHA-256 sidecar остаётся для legacy compatibility с verify path,
        # но при load aurora-model sidecar не требуется (zip CRC32 + structural validation).
        write_pkl_sha256_sidecar(model_path)

        logger.info(
            "save_v20_diagnostics: persisted fields %s to %s (model_version→2.0.0, aurora-model)",
            applied_fields, model_path,
        )


def load_v20_diagnostics(project_dir: str | Path) -> dict[str, Any]:
    """Return cached v2.0.0 diagnostics fields from latest.pkl.

    Safe for v1.3.x pickles — returns a dict with all v2.0.0 diagnostics keys
    present but set to their default (None / empty) values. Callers should
    check `is_v20_compatible(model_data)` to decide whether to show «re-train»
    banner.

    Returns:
        dict with keys:
          - signed_factor_priors_used: dict (empty dict если absent)
          - holiday_dummies_injected: list[str] (empty list если absent)
          - mcmc_diagnostics: dict | None
          - backtest_results: dict | None
          - ppc_results: dict | None
          - sensitivity_tornado_cache: dict | None
          - analysis_mode: str | None
          - _v20_compatible: bool — convenience flag (True если model v2.0.0+)

    Raises:
        FileNotFoundError: если latest.pkl отсутствует.
    """
    model_path = _model_path_for_project(project_dir)
    if not model_path.exists():
        raise FileNotFoundError(
            f"latest.pkl не найден: {model_path}."
        )

    model_data = load_model_with_compat(model_path)

    # H-05: defensive numpy sanitize при load для legacy v1.x pickles, которые
    # содержали ndarray в diagnostics fields. Новые pickles уже sanitized at save.
    return _normalize_numpy({
        'signed_factor_priors_used': model_data.get('signed_factor_priors_used') or {},
        'holiday_dummies_injected': model_data.get('holiday_dummies_injected') or [],
        'mcmc_diagnostics': model_data.get('mcmc_diagnostics'),
        'backtest_results': model_data.get('backtest_results'),
        'ppc_results': model_data.get('ppc_results'),
        'sensitivity_tornado_cache': model_data.get('sensitivity_tornado_cache'),
        'analysis_mode': model_data.get('analysis_mode'),
        '_v20_compatible': is_v20_compatible(model_data),
    })


def clear_sensitivity_cache(project_dir: str | Path) -> bool:
    """Invalidate cached sensitivity_tornado_cache in latest.pkl.

    Called when sensitivity parameters change (e.g., budget range updated,
    channel spend constraints edited) so the next Sensitivity tab access
    triggers a fresh compute_sensitivity_tornado() call.

    Uses same atomic temp-rename pattern as save_v20_diagnostics().

    Args:
        project_dir: project directory containing models/latest.pkl

    Returns:
        True если cache was present and cleared.
        False если cache was already None (no-op, но не error).

    Raises:
        FileNotFoundError: если latest.pkl отсутствует.
    """
    model_path = _model_path_for_project(project_dir)
    if not model_path.exists():
        raise FileNotFoundError(
            f"latest.pkl не найден: {model_path}."
        )

    # C-02 multi-tab race protection: same lock as save_v20_diagnostics —
    # filelock.is_singleton делает re-entrant safe в рамках процесса.
    from utils.file_lock import project_lock
    with project_lock(Path(project_dir), timeout=5.0):
        model_data = load_model_with_compat(model_path)
        had_cache = model_data.get('sensitivity_tornado_cache') is not None

        if not had_cache:
            logger.debug(
                "clear_sensitivity_cache: cache already None for %s — no-op", project_dir
            )
            return False

        model_data['sensitivity_tornado_cache'] = None

        # v2.1.0: переход на безопасный формат aurora-model.
        from engines.persistence_safe import save_model_safe
        save_model_safe(model_data, model_path)
        write_pkl_sha256_sidecar(model_path)

    logger.info("clear_sensitivity_cache: cache cleared for %s", project_dir)
    return True
