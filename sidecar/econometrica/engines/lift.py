"""Phase 2.7 (5a) canonical lift% — single source of truth.

Both `engines.optimizer.optimize()` and `engines.scenario.predict_scenario()`
MUST apply final formula selection через `select_lift_pct()` ниже. Это держит
identical degeneracy guards (y_std, baseline_zero), identical env override
(`AURORA_LEGACY_LIFT_FORMULA=1`), и identical canonical formula (`(new - old) /
old × 100`) — без drift между движками.

Inputs differ by engine (optimizer evaluates через `_objective_fn`, scenario
reconstructs через Hill+adstock на `data_file`), но финальная formula application
живёт здесь — это enforce'ит INV-17 (SSOT для UI-displayed metrics) + INV-37
(SSOT override comprehensive coverage).

Math reference: `project_econometrica_lift_formula_audit.md`, Phase 2.7 5a plan.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

LEGACY_LIFT_ENV = 'AURORA_LEGACY_LIFT_FORMULA'
DEFAULT_EPSILON = 1e-9
Y_STD_DEGENERATE_THRESHOLD = 1e-10


@dataclass(frozen=True)
class LiftDiagnostics:
    """Structured selection trace для post-hoc debugging."""
    formula_used: str  # canonical|legacy_env|fallback_y_std|fallback_baseline_zero
    canonical_lift_pct: float | None
    baseline_zero: bool
    y_std_degenerate: bool
    legacy_env_active: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_y_std_degenerate(y_std: Any, threshold: float = Y_STD_DEGENERATE_THRESHOLD) -> bool:
    """True если y_std missing / non-numeric / near-zero / negative.

    Negative `y_std` физически бессмыслен (std deviation = √variance ≥ 0). Если
    pickle когда-либо имеет `y_std < 0` → canonical formula `intercept * y_std + y_mean`
    инвертирует знак money-axis baseline → wildly wrong lift. Treat negative как
    degenerate fallback к legacy.
    """
    if not isinstance(y_std, (int, float)):
        return True
    try:
        value = float(y_std)
    except (TypeError, ValueError):
        return True
    if value < 0:
        return True
    return abs(value) < threshold


def canonical_lift_pct(
    total_optimal_kpi: float,
    total_current_kpi: float,
    *,
    epsilon: float = DEFAULT_EPSILON,
) -> float | None:
    """Phase 2.7 (5a) canonical formula.

    Returns:
        (total_optimal - total_current) / total_current × 100, или None при degenerate
        baseline (total_current ≤ epsilon) ИЛИ при NaN/Inf inputs (silent non-finite
        propagation undermines customer-facing numbers — caller falls back к legacy).
    """
    import math as _math
    try:
        opt_f = float(total_optimal_kpi)
        cur_f = float(total_current_kpi)
    except (TypeError, ValueError):
        return None
    if not (_math.isfinite(opt_f) and _math.isfinite(cur_f)):
        return None
    if cur_f > epsilon:
        return (opt_f - cur_f) / cur_f * 100.0
    return None


def is_legacy_env_active() -> bool:
    """True если AURORA_LEGACY_LIFT_FORMULA=1 — emergency revert flag."""
    return os.environ.get(LEGACY_LIFT_ENV) == '1'


def select_lift_pct(
    *,
    total_optimal_kpi: float,
    total_current_kpi: float,
    legacy_fallback_pct: float,
    y_std: Any,
    epsilon: float = DEFAULT_EPSILON,
) -> tuple[float, LiftDiagnostics]:
    """Pick final lift_pct enforcing Phase 2.7 (5a) SSOT semantics.

    Selection priority:
    1. `AURORA_LEGACY_LIFT_FORMULA=1` env → `legacy_fallback_pct` (no questions asked).
    2. y_std degenerate → `legacy_fallback_pct` (canonical math undefined).
    3. baseline_zero (total_current ≤ epsilon) → `legacy_fallback_pct`.
    4. Otherwise → canonical formula.

    Args:
        total_optimal_kpi: Optimal scenario KPI total (money axis).
        total_current_kpi: Current scenario KPI total (money axis, same units).
        legacy_fallback_pct: Engine-specific legacy formula result используется в fallback
            paths. Optimizer uses media-only ratio (Δmedia / current_media). Scenario uses
            incremental-over-baseline (incremental_total / baseline_only).
        y_std: Training y std из normalization (`norm['y_std']`). Degenerate flags fallback.
        epsilon: Numerical threshold для baseline_zero detection.

    Returns:
        Tuple (lift_pct: float, diagnostics: LiftDiagnostics). Caller responsible
        за rounding для display (helper preserves full precision).
    """
    legacy_env_active = is_legacy_env_active()
    y_std_degenerate = is_y_std_degenerate(y_std)
    canonical = canonical_lift_pct(total_optimal_kpi, total_current_kpi, epsilon=epsilon)
    baseline_zero = canonical is None

    # Priority 1 — emergency env override (operator can force-revert без redeploy).
    if legacy_env_active and not y_std_degenerate and not baseline_zero:
        logger.info(
            "%s=1 — using legacy lift_pct=%.4f (canonical=%.4f).",
            LEGACY_LIFT_ENV, float(legacy_fallback_pct), float(canonical or 0.0),
        )
        return float(legacy_fallback_pct), LiftDiagnostics(
            formula_used='legacy_env',
            canonical_lift_pct=canonical,
            baseline_zero=False,
            y_std_degenerate=False,
            legacy_env_active=True,
        )

    # Priority 2 — y_std degenerate (canonical math depends on money-axis scaling).
    if y_std_degenerate:
        if legacy_env_active:
            # Operator выставил env override но canonical math undefined из-за y_std.
            # Surface visibility: дублирует priority 1 / 2 dispatch без silent suppression.
            logger.warning(
                "lift_pct: %s=1 set, но y_std degenerate (%r) тоже triggered — Priority 2 "
                "fallback dispatched. Env-override effectively no-op (same legacy result).",
                LEGACY_LIFT_ENV, y_std,
            )
        logger.warning(
            "lift_pct: y_std degenerate (%r) — canonical formula falls back к legacy ratio (%.4f).",
            y_std, float(legacy_fallback_pct),
        )
        return float(legacy_fallback_pct), LiftDiagnostics(
            formula_used='fallback_y_std',
            canonical_lift_pct=canonical,
            baseline_zero=baseline_zero,
            y_std_degenerate=True,
            legacy_env_active=legacy_env_active,
        )

    # Priority 3 — baseline_zero (total_current ≤ ε ИЛИ non-finite inputs).
    if baseline_zero:
        if legacy_env_active:
            logger.warning(
                "lift_pct: %s=1 set, но baseline_zero (total_current_kpi ≤ %s или NaN/Inf) "
                "тоже triggered — Priority 3 fallback dispatched. Env-override no-op.",
                LEGACY_LIFT_ENV, epsilon,
            )
        logger.warning(
            "lift_pct: total_current_kpi ≤ %s — canonical undefined. Fallback к legacy (%.4f).",
            epsilon, float(legacy_fallback_pct),
        )
        return float(legacy_fallback_pct), LiftDiagnostics(
            formula_used='fallback_baseline_zero',
            canonical_lift_pct=None,
            baseline_zero=True,
            y_std_degenerate=False,
            legacy_env_active=legacy_env_active,
        )

    # Priority 4 — canonical applied.
    return float(canonical), LiftDiagnostics(
        formula_used='canonical',
        canonical_lift_pct=float(canonical),
        baseline_zero=False,
        y_std_degenerate=False,
        legacy_env_active=legacy_env_active,
    )


__all__ = [
    'LEGACY_LIFT_ENV',
    'DEFAULT_EPSILON',
    'Y_STD_DEGENERATE_THRESHOLD',
    'LiftDiagnostics',
    'is_y_std_degenerate',
    'canonical_lift_pct',
    'is_legacy_env_active',
    'select_lift_pct',
]
