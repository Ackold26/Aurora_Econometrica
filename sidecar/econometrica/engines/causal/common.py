"""
Shared utilities for Sprint 3 Pharma Causal engines.

Contains:
- HonestDisclosure — schema for surfacing method assumptions to UI (per F2/F3
  synergy). Every causal endpoint returns this field.
- ATT — Average Treatment Effect on Treated estimate с CI.
- error codes — uniform across DiD/SCM/Forest endpoints.
- panel-data validation helpers shared by all 3 methods.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal


# Uniform error codes across causal endpoints (analogous к existing MMM
# MISSING_KPI_COLUMN / MODEL_OUTDATED). Surfaced в response['error_code'].
ERROR_CODES = {
    'PANEL_FORMAT_INVALID': 'Данные не в panel-формате (long: unit×time×kpi).',
    'TREATED_UNIT_MISSING': 'Указанный treated_unit не найден в данных.',
    'TREATMENT_PERIOD_INVALID': 'Treatment period не разделяет данные на pre/post.',
    'INSUFFICIENT_PRE_PERIODS': 'Слишком мало pre-treatment периодов (нужно ≥6).',
    'INSUFFICIENT_DONORS': 'Donor pool слишком мал (нужно ≥3 контрольных юнитов).',
    'OVERLAP_VIOLATION': 'Positivity / overlap нарушена — propensity scores на границе.',
    'COLINEARITY': 'Высокая коллинеарность среди features — ATT не идентифицирован.',
    'COMPUTATION_FAILED': 'Численная ошибка в estimator (см. message).',
    'DATA_LOAD_FAILED': 'Не удалось загрузить файл данных.',
    'COLUMNS_MISSING': 'Указанные колонки отсутствуют в файле.',
}


@dataclass
class ATT:
    """Average Treatment Effect on Treated с confidence interval.

    Returned by all causal endpoints. ci_method values:
    - 'frequentist_se' — DiD asymptotic SE × t-quantile
    - 'bootstrap' — empirical bootstrap CI (SCM, Causal Forest fallback)
    - 'honest_split' — Wager-Athey honest CI (Causal Forest primary)
    - 'placebo' — SCM permutation inference
    """
    point: float
    ci_low: float
    ci_high: float
    ci_method: str
    confidence: float = 0.9

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_significant(self) -> bool:
        """True если CI не пересекает 0 (one-sided meaningful effect)."""
        return (self.ci_low > 0 and self.ci_high > 0) or (self.ci_low < 0 and self.ci_high < 0)


@dataclass
class HonestDisclosure:
    """Honest disclosure of method assumptions (F2/F3 synergy).

    Each causal endpoint returns this field. UI surfaces caveats как tooltip
    next к ATT bracket. Aurora Causal honest about assumptions, не "magic
    causal MMM" claim — per ADR §7.

    Examples:
    - DiD: parallel-trends assumption, common-shock, no-anticipation.
    - SCM: convex-hull, donor-pool quality, RMSE pre-treatment.
    - Forest: positivity / overlap, no unobserved confounding (CIA).
    - All: SUTVA (no spillover), exchangeability (caveat for time-series).
    """
    method: str  # 'did_callaway_santanna' | 'scm_abadie_classic' | 'forest_wager_athey'
    assumptions: list[str] = field(default_factory=list)  # human-readable assumption descriptions
    caveats: list[str] = field(default_factory=list)      # data-driven warnings
    diagnostics_passed: list[str] = field(default_factory=list)  # checks that succeeded
    diagnostics_failed: list[str] = field(default_factory=list)  # checks that failed (block ATT?)
    references: list[str] = field(default_factory=list)   # academic refs

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_blocked(self) -> bool:
        """Если хоть один diagnostic FAILED — ATT может быть unreliable."""
        return len(self.diagnostics_failed) > 0


def error_response(code: str, detail: str = '') -> dict[str, Any]:
    """Uniform error response для causal endpoints.

    Args:
        code: one of ERROR_CODES keys.
        detail: appended detail (e.g., specific column name, file path).

    Returns:
        {'status': 'error', 'error_code': code, 'message': base_msg + detail}
    """
    base = ERROR_CODES.get(code, code)
    msg = f'{base} {detail}'.strip()
    return {'status': 'error', 'error_code': code, 'message': msg}


def confidence_to_alpha(confidence: float) -> float:
    """0.9 → 0.1, 0.95 → 0.05. Defensive guard на [0, 1)."""
    if not 0 < confidence < 1:
        raise ValueError(f'confidence must be in (0, 1), got {confidence}')
    return 1.0 - float(confidence)
