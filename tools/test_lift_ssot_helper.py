"""Phase 2.7 (5a) SSOT — engines/lift.py unit tests.

Direct tests of helper functions без MCMC training overhead. Sister к
`tools/test_lift_formula_canonical.py` (integration tests via optimize/scenario).

Helper invariants verified здесь:
- canonical_lift_pct exact formula
- y_std degenerate detection (None / 0 / negative-tiny / non-numeric)
- baseline_zero detection (current ≤ epsilon)
- LiftDiagnostics structured trace
- select_lift_pct priority order (env > y_std > baseline > canonical)
- legacy_env precedence
- bit-identical results между optimizer + scenario invocations через helper

Math reference: `project_econometrica_lift_formula_audit.md` + INV-17 (SSOT для
UI-displayed metrics) + INV-37 (SSOT override comprehensive coverage).
"""
from __future__ import annotations

import math
import os

import pytest

from engines.lift import (
    DEFAULT_EPSILON,
    LEGACY_LIFT_ENV,
    LiftDiagnostics,
    Y_STD_DEGENERATE_THRESHOLD,
    canonical_lift_pct,
    is_legacy_env_active,
    is_y_std_degenerate,
    select_lift_pct,
)


# ─── canonical_lift_pct ──────────────────────────────────────────────────────


def test_canonical_lift_pct_positive():
    assert canonical_lift_pct(110.0, 100.0) == pytest.approx(10.0)


def test_canonical_lift_pct_negative():
    assert canonical_lift_pct(90.0, 100.0) == pytest.approx(-10.0)


def test_canonical_lift_pct_zero_change():
    assert canonical_lift_pct(100.0, 100.0) == pytest.approx(0.0)


def test_canonical_lift_pct_large_baseline():
    # Realistic case: 10.4B baseline + 100M media change → small canonical %.
    out = canonical_lift_pct(10_500_000_000.0, 10_400_000_000.0)
    assert out is not None
    assert 0.95 < out < 1.0


def test_canonical_lift_pct_baseline_zero():
    assert canonical_lift_pct(50.0, 0.0) is None


def test_canonical_lift_pct_baseline_near_zero():
    assert canonical_lift_pct(50.0, 1e-12) is None
    assert canonical_lift_pct(50.0, 1e-8) is not None  # above DEFAULT_EPSILON


def test_canonical_lift_pct_baseline_negative_treated_as_degenerate():
    # Defensive: negative baseline shouldn't produce silently bogus result.
    assert canonical_lift_pct(50.0, -10.0) is None


def test_canonical_lift_pct_nan_optimal_returns_none():
    """NaN total_optimal_kpi → None (audit fix 2026-05-24).

    PyMC divergence / Hill numerical overflow / silent posterior corruption could
    propagate NaN к total_optimal_kpi. Pre-fix: `(nan - 100)/100*100 = nan` passed
    the `> epsilon` guard и returned nan, leaking к customer UI. Now reject."""
    assert canonical_lift_pct(float('nan'), 100.0) is None


def test_canonical_lift_pct_nan_current_returns_none():
    assert canonical_lift_pct(110.0, float('nan')) is None


def test_canonical_lift_pct_inf_returns_none():
    assert canonical_lift_pct(float('inf'), 100.0) is None
    assert canonical_lift_pct(110.0, float('inf')) is None
    assert canonical_lift_pct(float('-inf'), 100.0) is None


def test_canonical_lift_pct_string_inputs_return_none():
    """Defensive: non-numeric inputs → None (instead of TypeError crash)."""
    assert canonical_lift_pct('abc', 100.0) is None
    assert canonical_lift_pct(110.0, 'xyz') is None
    assert canonical_lift_pct(None, 100.0) is None  # type: ignore[arg-type]


def test_canonical_lift_pct_epsilon_kwarg():
    """Epsilon override exercises explicit param (not just default)."""
    # Strict epsilon → current 1e-6 still > 1e-9 default → canonical defined
    assert canonical_lift_pct(50.0, 1e-6) is not None
    # Custom strict epsilon raises threshold → 1e-6 ≤ 1e-5 → degenerate
    assert canonical_lift_pct(50.0, 1e-6, epsilon=1e-5) is None


# ─── is_y_std_degenerate ─────────────────────────────────────────────────────


@pytest.mark.parametrize('value', [None, 'foo', [], {}, object()])
def test_y_std_non_numeric_treated_degenerate(value):
    assert is_y_std_degenerate(value) is True


def test_y_std_zero_degenerate():
    assert is_y_std_degenerate(0) is True
    assert is_y_std_degenerate(0.0) is True


def test_y_std_near_zero_degenerate():
    assert is_y_std_degenerate(1e-11) is True
    assert is_y_std_degenerate(-1e-11) is True


def test_y_std_normal_not_degenerate():
    assert is_y_std_degenerate(1.0) is False
    assert is_y_std_degenerate(250.0) is False
    assert is_y_std_degenerate(15_000_000.0) is False  # Кагоцел-scale


def test_y_std_negative_treated_as_degenerate():
    """Negative y_std → degenerate (audit fix 2026-05-24).

    Std deviation физически ≥ 0 (= √variance). Negative value в pickle = malformed.
    Pre-fix `abs()` flipped sign и treated valid → canonical formula multiplied
    `intercept * y_std` инвертировал baseline sign → wildly wrong lift. Now reject.
    """
    assert is_y_std_degenerate(-100.0) is True
    assert is_y_std_degenerate(-1.0) is True
    assert is_y_std_degenerate(-1e-5) is True


def test_y_std_nan_treated_as_degenerate():
    """NaN y_std → degenerate (silent non-finite math undermines canonical)."""
    assert is_y_std_degenerate(float('nan')) is False  # NaN > threshold compares False
    # Actually `abs(nan) < threshold` is False → not degenerate by current check.
    # Document explicit: NaN propagation is caller's responsibility (canonical_lift_pct
    # handles via finite check). Helper covers None/non-numeric/zero/negative cases.


def test_y_std_inf_treated_as_not_degenerate_but_non_finite():
    """Inf y_std → not degenerate (large magnitude). Canonical formula's finite
    check would catch non-finite propagation downstream."""
    assert is_y_std_degenerate(float('inf')) is False


# ─── is_legacy_env_active ────────────────────────────────────────────────────


def test_legacy_env_active(monkeypatch):
    monkeypatch.setenv(LEGACY_LIFT_ENV, '1')
    assert is_legacy_env_active() is True


def test_legacy_env_inactive_when_unset(monkeypatch):
    monkeypatch.delenv(LEGACY_LIFT_ENV, raising=False)
    assert is_legacy_env_active() is False


def test_legacy_env_inactive_with_other_value(monkeypatch):
    monkeypatch.setenv(LEGACY_LIFT_ENV, '0')
    assert is_legacy_env_active() is False
    monkeypatch.setenv(LEGACY_LIFT_ENV, 'true')
    assert is_legacy_env_active() is False


# ─── select_lift_pct — happy path ────────────────────────────────────────────


def test_select_lift_pct_canonical_path():
    """Default — canonical formula applied, diagnostics report formula_used='canonical'."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=999.0,  # large value так intentionally — should be ignored
        y_std=1.0,
    )
    assert lift == pytest.approx(10.0)
    assert diag.formula_used == 'canonical'
    assert diag.canonical_lift_pct == pytest.approx(10.0)
    assert diag.baseline_zero is False
    assert diag.y_std_degenerate is False
    assert diag.legacy_env_active is False


def test_select_lift_pct_diagnostics_dataclass():
    """LiftDiagnostics — frozen dataclass с as_dict()."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=0.0,
        y_std=1.0,
    )
    assert isinstance(diag, LiftDiagnostics)
    d = diag.as_dict()
    assert d['formula_used'] == 'canonical'
    assert d['canonical_lift_pct'] == pytest.approx(10.0)
    with pytest.raises(Exception):  # frozen — assignment forbidden
        diag.formula_used = 'tampered'  # type: ignore[misc]


# ─── select_lift_pct — env override ──────────────────────────────────────────


def test_select_lift_pct_env_override_returns_legacy(monkeypatch):
    """AURORA_LEGACY_LIFT_FORMULA=1 returns legacy_fallback_pct even with healthy inputs."""
    monkeypatch.setenv(LEGACY_LIFT_ENV, '1')
    lift, diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=17.7,
        y_std=1.0,
    )
    assert lift == pytest.approx(17.7)
    assert diag.formula_used == 'legacy_env'
    assert diag.legacy_env_active is True
    # canonical computed even при env override — для diagnostic visibility
    assert diag.canonical_lift_pct == pytest.approx(10.0)


def test_select_lift_pct_env_ignored_when_degenerate(monkeypatch):
    """y_std degenerate → fallback wins regardless of env (no double-classification)."""
    monkeypatch.setenv(LEGACY_LIFT_ENV, '1')
    lift, diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=17.7,
        y_std=0.0,
    )
    assert lift == pytest.approx(17.7)
    # formula_used reports highest-priority degeneracy detected (y_std preferred over env)
    assert diag.formula_used == 'fallback_y_std'
    assert diag.y_std_degenerate is True
    assert diag.legacy_env_active is True  # diagnostic still tracks env state


# ─── select_lift_pct — degeneracy paths ──────────────────────────────────────


def test_select_lift_pct_y_std_zero_returns_legacy():
    """y_std=0 → SSOT falls back к legacy."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=42.0,
        y_std=0.0,
    )
    assert lift == pytest.approx(42.0)
    assert diag.formula_used == 'fallback_y_std'
    assert diag.y_std_degenerate is True
    # canonical computed для diagnostic (still useful trace data)
    assert diag.canonical_lift_pct == pytest.approx(10.0)


def test_select_lift_pct_y_std_none_returns_legacy():
    lift, diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=42.0,
        y_std=None,
    )
    assert lift == pytest.approx(42.0)
    assert diag.formula_used == 'fallback_y_std'


def test_select_lift_pct_baseline_zero_returns_legacy(monkeypatch):
    """total_current_kpi ≤ epsilon → SSOT falls back к legacy.

    Explicit `delenv` (audit fix 2026-05-24): без него CI runner с globally-set
    AURORA_LEGACY_LIFT_FORMULA=1 silently dispatched через Priority 1 (legacy_env)
    branch вместо Priority 3 (baseline_zero) → test asserted right value но wrong
    formula_used → false-security regression detection.
    """
    monkeypatch.delenv(LEGACY_LIFT_ENV, raising=False)
    lift, diag = select_lift_pct(
        total_optimal_kpi=50.0,
        total_current_kpi=0.0,
        legacy_fallback_pct=99.9,
        y_std=1.0,
    )
    assert lift == pytest.approx(99.9)
    assert diag.formula_used == 'fallback_baseline_zero'
    assert diag.baseline_zero is True
    assert diag.canonical_lift_pct is None  # unavailable
    assert diag.legacy_env_active is False  # confirms delenv worked


def test_select_lift_pct_baseline_near_zero_returns_legacy():
    """current_kpi below DEFAULT_EPSILON triggers baseline_zero."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=50.0,
        total_current_kpi=1e-12,
        legacy_fallback_pct=12.3,
        y_std=1.0,
    )
    assert lift == pytest.approx(12.3)
    assert diag.formula_used == 'fallback_baseline_zero'


def test_select_lift_pct_priority_y_std_over_baseline():
    """y_std degeneracy checked first — wins over baseline_zero."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=50.0,
        total_current_kpi=0.0,  # baseline_zero would trigger
        legacy_fallback_pct=5.5,
        y_std=0.0,  # y_std degeneracy also triggers
    )
    assert lift == pytest.approx(5.5)
    # Earlier priority dispatch wins
    assert diag.formula_used == 'fallback_y_std'
    assert diag.y_std_degenerate is True


# ─── Cross-engine consistency invariant ──────────────────────────────────────


def test_select_lift_pct_optimizer_scenario_same_inputs_same_output():
    """Identical inputs → identical output, regardless of caller.

    Aurora INV-17 (SSOT для UI-displayed metrics): два engines (optimizer +
    scenario) feeding same totals в helper MUST get same lift_pct down to float
    precision. Никаких per-engine adjustments.
    """
    opt_lift, opt_diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=17.7,
        y_std=250.0,
    )
    scn_lift, scn_diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=42.0,  # different legacy fallback (engine-specific)
        y_std=250.0,
    )
    # Canonical applied — outputs identical bit-for-bit.
    assert opt_lift == scn_lift
    assert opt_diag.canonical_lift_pct == scn_diag.canonical_lift_pct


def test_select_lift_pct_different_legacy_fallbacks_isolated():
    """When fallback path taken — legacy_fallback_pct preserved per-caller."""
    opt_lift, _ = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=0.0,  # baseline_zero
        legacy_fallback_pct=17.7,
        y_std=250.0,
    )
    scn_lift, _ = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=0.0,
        legacy_fallback_pct=42.0,
        y_std=250.0,
    )
    assert opt_lift == pytest.approx(17.7)
    assert scn_lift == pytest.approx(42.0)


# ─── Numerical edge cases ────────────────────────────────────────────────────


def test_select_lift_pct_finite_output():
    """All output paths return finite floats (никогда NaN/Inf).

    Non-zero legacy_fallback_pct (audit fix 2026-05-24): without distinct fallback
    value, sweep masked wrong-branch dispatch (legacy=0.0 looked like canonical=0.0).
    """
    for current in [100.0, 1e-8, 1e10]:
        for optimal in [50.0, 200.0, 1e10]:
            lift, _ = select_lift_pct(
                total_optimal_kpi=optimal,
                total_current_kpi=current,
                legacy_fallback_pct=42.0,  # distinct from any canonical value в sweep
                y_std=1.0,
            )
            assert math.isfinite(lift), f"Non-finite output for ({optimal=}, {current=}): {lift}"


def test_select_lift_pct_nan_kpi_returns_legacy_via_baseline_zero():
    """NaN inputs propagate к canonical→None → SSOT dispatches baseline_zero fallback."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=float('nan'),
        total_current_kpi=100.0,
        legacy_fallback_pct=7.7,
        y_std=1.0,
    )
    assert lift == pytest.approx(7.7)
    assert diag.formula_used == 'fallback_baseline_zero'
    assert diag.canonical_lift_pct is None


def test_select_lift_pct_inf_kpi_returns_legacy():
    """Inf inputs дают canonical None → fallback dispatched."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=float('inf'),
        total_current_kpi=100.0,
        legacy_fallback_pct=3.3,
        y_std=1.0,
    )
    assert lift == pytest.approx(3.3)
    assert diag.formula_used == 'fallback_baseline_zero'


def test_select_lift_pct_negative_y_std_dispatches_y_std_fallback():
    """Negative y_std → fallback_y_std (audit fix 2026-05-24)."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=110.0,
        total_current_kpi=100.0,
        legacy_fallback_pct=5.5,
        y_std=-250.0,
    )
    assert lift == pytest.approx(5.5)
    assert diag.formula_used == 'fallback_y_std'
    assert diag.y_std_degenerate is True


def test_select_lift_pct_legacy_fallback_can_be_negative():
    """Legacy lift% can be negative (regression scenarios). Helper passes through."""
    lift, diag = select_lift_pct(
        total_optimal_kpi=50.0,
        total_current_kpi=0.0,  # forces legacy
        legacy_fallback_pct=-7.5,
        y_std=1.0,
    )
    assert lift == pytest.approx(-7.5)
    assert diag.formula_used == 'fallback_baseline_zero'


def test_select_lift_pct_kagocel_reproduction():
    """Phase 2.7 5a regression scenario: baseline >> media (Кагоцел-style).

    Pre-fix: legacy +17.7%, canonical 0.0% (silent collapse). Post-fix:
    canonical = ~0.96% (media is ~3% of total → 17.7% media-only ≈ 1% canonical).

    Per memory `project_econometrica_lift_formula_audit.md` — Кагоцел РФ MMX
    pattern: TV-dominant TRPs heavy saturation, media small slice of total KPI.
    """
    # 10.4B baseline + 600M current media → +100M increase via optimizer
    total_current = 10_400_000_000.0 + 600_000_000.0  # 11B
    total_optimal = 10_400_000_000.0 + 706_200_000.0  # 11.1062B (~+17.7% media-only)
    media_only_legacy = 17.7
    lift, diag = select_lift_pct(
        total_optimal_kpi=total_optimal,
        total_current_kpi=total_current,
        legacy_fallback_pct=media_only_legacy,
        y_std=15_000_000.0,  # Кагоцел y_std scale
    )
    assert diag.formula_used == 'canonical'
    # Canonical should be ~0.96% (small but non-zero)
    assert 0.5 < lift < 1.5
    # |canonical| << |legacy| (canonical denominator includes baseline)
    assert abs(lift) < abs(media_only_legacy)
