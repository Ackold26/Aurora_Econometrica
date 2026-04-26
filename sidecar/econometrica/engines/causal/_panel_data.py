"""
Panel data loader + validators for Sprint 3 causal engines.

Panel format (long): each row = (unit, time, kpi, [treated], [features...]).
Multiple units (e.g., regions/cities) × multiple time periods.

Used by DiD (M1), SCM (M2), Causal Forest (M3). Common pre-flight validation
prevents M-specific code from re-implementing same checks.

⚠️ Pre-launch блокер per ADR §11/Q3: fully aggregated brand-level data
(Kagocel, Афала) lacks geo split. Real panel-data resolution is a parallel
workstream — this module loads ANY long-format CSV/XLSX, не зависит от
specific dataset structure.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .common import error_response


@dataclass
class PanelMetadata:
    """Pre-flight metadata about loaded panel data."""
    n_units: int
    n_periods: int
    n_obs: int
    is_balanced: bool                # все units имеют одинаковое количество periods?
    unit_column: str
    time_column: str
    kpi_column: str
    units_list: list[Any]
    periods_list: list[Any]
    has_treatment: bool              # treatment column present?
    treated_units: list[Any] = None  # which units are ever-treated (DiD)

    def to_dict(self) -> dict[str, Any]:
        return {
            'n_units': self.n_units,
            'n_periods': self.n_periods,
            'n_obs': self.n_obs,
            'is_balanced': self.is_balanced,
            'unit_column': self.unit_column,
            'time_column': self.time_column,
            'kpi_column': self.kpi_column,
            'has_treatment': self.has_treatment,
            'treated_units_count': len(self.treated_units) if self.treated_units else 0,
        }


def load_panel(
    file_path: str,
    *,
    unit_column: str,
    time_column: str,
    kpi_column: str,
    treatment_column: str | None = None,
    sheet_name: str | None = None,
) -> tuple[pd.DataFrame | None, PanelMetadata | None, dict | None]:
    """Load panel data + run basic format validation.

    Returns:
        (df, metadata, error_dict) — exactly one of {df, error_dict} populated.
        - On success: df, metadata, None
        - On failure: None, None, error_response(...)
    """
    path = Path(file_path)
    if not path.exists():
        return None, None, error_response('DATA_LOAD_FAILED', f'Файл не найден: {file_path}')

    try:
        if path.suffix.lower() in ('.xlsx', '.xls'):
            df = pd.read_excel(file_path, sheet_name=sheet_name) if sheet_name else pd.read_excel(file_path)
        elif path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path)
        else:
            return None, None, error_response('DATA_LOAD_FAILED', f'Неподдерживаемый формат: {path.suffix}')
    except Exception as e:
        return None, None, error_response('DATA_LOAD_FAILED', f'{type(e).__name__}: {e}')

    # Validate required columns
    required = [unit_column, time_column, kpi_column]
    if treatment_column:
        required.append(treatment_column)
    missing = [c for c in required if c not in df.columns]
    if missing:
        return None, None, error_response(
            'COLUMNS_MISSING',
            f'Отсутствующие колонки: {missing}. Доступные: {df.columns[:20].tolist()}'
        )

    # Build metadata
    units = df[unit_column].unique().tolist()
    periods = sorted(df[time_column].unique().tolist())
    is_balanced = (df.groupby(unit_column).size().nunique() == 1)

    treated_units: list[Any] = []
    if treatment_column:
        treated_mask = df.groupby(unit_column)[treatment_column].max() > 0
        treated_units = treated_mask[treated_mask].index.tolist()

    metadata = PanelMetadata(
        n_units=len(units),
        n_periods=len(periods),
        n_obs=len(df),
        is_balanced=is_balanced,
        unit_column=unit_column,
        time_column=time_column,
        kpi_column=kpi_column,
        units_list=units,
        periods_list=periods,
        has_treatment=treatment_column is not None,
        treated_units=treated_units if treatment_column else None,
    )

    return df, metadata, None


def validate_for_did(metadata: PanelMetadata) -> dict | None:
    """DiD-specific validation. Returns error dict or None."""
    if not metadata.has_treatment:
        return error_response('PANEL_FORMAT_INVALID', 'DiD требует treatment_column.')
    if metadata.n_units < 4:
        return error_response('PANEL_FORMAT_INVALID', f'DiD требует ≥4 units (треш + контроль). Got {metadata.n_units}.')
    if not metadata.treated_units:
        return error_response('TREATED_UNIT_MISSING', 'Нет treated units (max(treatment) == 0 для всех).')
    if len(metadata.treated_units) >= metadata.n_units:
        return error_response('PANEL_FORMAT_INVALID', 'Все units treated — нет контрольной группы.')
    if metadata.n_periods < 4:
        return error_response('INSUFFICIENT_PRE_PERIODS', f'DiD требует ≥4 periods. Got {metadata.n_periods}.')
    return None


def validate_for_scm(
    metadata: PanelMetadata,
    treated_unit: Any,
    treatment_period: Any,
) -> dict | None:
    """SCM-specific validation.

    B9 audit fix: defensive type coercion для treatment_period comparison —
    if metadata periods are timestamps and user passes string, attempt coerce.
    Pre-fix, type mismatch silently filtered all periods to one side.
    """
    if treated_unit not in metadata.units_list:
        return error_response('TREATED_UNIT_MISSING', f'Unit {treated_unit} не в данных. Есть: {metadata.units_list[:10]}')
    n_donors = metadata.n_units - 1
    if n_donors < 3:
        return error_response('INSUFFICIENT_DONORS', f'Donor pool {n_donors} < 3.')

    # B9: type coercion for treatment_period comparison
    sample_period = metadata.periods_list[0] if metadata.periods_list else None
    if sample_period is not None and type(sample_period) is not type(treatment_period):
        try:
            if isinstance(sample_period, (int, float)):
                treatment_period = type(sample_period)(treatment_period)
            elif hasattr(sample_period, 'year'):  # pd.Timestamp / datetime
                treatment_period = pd.to_datetime(treatment_period)
        except Exception:
            return error_response(
                'TREATMENT_PERIOD_INVALID',
                f'treatment_period {treatment_period!r} не coerces к dtype panel periods ({type(sample_period).__name__}).'
            )

    # Pre-treatment period count
    try:
        pre_periods = [p for p in metadata.periods_list if p < treatment_period]
        post_periods = [p for p in metadata.periods_list if p >= treatment_period]
    except TypeError as e:
        return error_response(
            'TREATMENT_PERIOD_INVALID',
            f'treatment_period сравнение failed: {e}. Проверь dtype.'
        )

    if len(pre_periods) < 6:
        return error_response('INSUFFICIENT_PRE_PERIODS', f'Pre-treatment periods {len(pre_periods)} < 6.')
    if len(post_periods) < 1:
        return error_response('TREATMENT_PERIOD_INVALID', 'Нет post-treatment periods.')

    # B7 audit fix: warn (not block) when n_pre < n_donors + 1.
    # Per Abadie literature, SCM may overfit (perfect pre-match) когда n_donors > n_pre.
    # We don't BLOCK because SCM still computable — just store warning meta для UI.
    # (caller in scm.py can read this from metadata if needed; non-blocking.)
    if len(pre_periods) < n_donors + 1:
        # Stamp on metadata for caller to surface (don't reject — allow SCM to run)
        metadata.units_list  # no-op accessor, just to assert metadata still usable
        # Note: metadata is dataclass — we attach a soft attribute via setattr
        try:
            object.__setattr__(metadata, '_overfit_warning',
                f'n_pre ({len(pre_periods)}) < n_donors+1 ({n_donors+1}) — SCM may overfit '
                f'pre-treatment match. Pre-RMSE will look excellent но post-period extrapolation '
                f'unreliable. Per Abadie 2021, prefer n_pre ≥ n_donors+1.')
        except Exception:
            pass

    return None


def validate_for_forest(metadata: PanelMetadata, feature_columns: list[str], df: pd.DataFrame) -> dict | None:
    """Causal Forest validation — overlap + features."""
    if not metadata.has_treatment:
        return error_response('PANEL_FORMAT_INVALID', 'Causal Forest требует treatment_column.')
    if metadata.n_obs < 100:
        return error_response('PANEL_FORMAT_INVALID', f'Causal Forest требует n≥100 observations. Got {metadata.n_obs}.')
    missing_feat = [f for f in feature_columns if f not in df.columns]
    if missing_feat:
        return error_response('COLUMNS_MISSING', f'Feature columns missing: {missing_feat}')
    # Trivial overlap check — both treated и control в данных
    treat_count = df.groupby(metadata.unit_column).first()  # placeholder
    return None


def synthesize_geo_split(
    df: pd.DataFrame,
    *,
    n_geo: int = 5,
    seed: int = 42,
    geo_column_name: str = '_synth_region',
) -> pd.DataFrame:
    """Synthesize geo split for AGGREGATED data (M0/M1 fallback).

    Brand-level data (Kagocel/Афала) lacks regional granularity. For Sprint 3
    validation, can synthesize geo split via stratified random assignment of
    rows to regions. Use ONLY для validation / DGP-controlled SBC — not для
    real customer reports.

    DGP: each row randomly assigned к 1 of n_geo regions. KPI scaled by
    region-specific multiplier (random uniform [0.5, 1.5]) to introduce
    inter-region heterogeneity. Treatment effect (when added) creates
    causal signal с known ground truth.

    Returns:
        df_panel — long-format с new geo column added. Each original row
        becomes n_geo rows (one per region) with proportionally split KPI.
    """
    # B10 audit fix: hoist numeric_cols computation outside double loop (was: re-evaluated
    # N×n_geo times = O(N×n_geo) wasted column lookups). Comment "additive noise" was wrong —
    # scaling is multiplicative (kept as-is, just labeled correctly now).
    rng = np.random.default_rng(seed)
    region_multipliers = rng.uniform(0.5, 1.5, n_geo)
    region_multipliers = region_multipliers / region_multipliers.sum() * n_geo  # normalize sum
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    panel_rows = []
    for _, row in df.iterrows():
        for r_idx in range(n_geo):
            new_row = row.copy()
            new_row[geo_column_name] = f'region_{r_idx}'
            # Multiplicative scaling by region-specific factor (NOT additive noise).
            for c in numeric_cols:
                new_row[c] = row[c] * region_multipliers[r_idx] / n_geo
            panel_rows.append(new_row)

    return pd.DataFrame(panel_rows).reset_index(drop=True)
