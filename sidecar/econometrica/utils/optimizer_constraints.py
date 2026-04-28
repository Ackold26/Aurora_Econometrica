"""
Aurora Econometrica — Optimizer constraint resolution (v1.2.0+).

Phase A3.1 — pure logic helpers для per-group + per-channel + global precedence.
3-level precedence: per-channel > per-group > global.

Mixed channels (Trust 3 categorization) → fall back к global (H3 fix — no separate
slider для mixed; cleaner UX).

Pre-flight feasibility validation (H4 fix):
- group_max ≤ global_max enforced
- Σ(channel min × current_money) ≤ budget ≤ Σ(channel max × current_money)

References:
- Plan: bright-wandering-neumann.md → Phase A3.1
- Math reference: docs/MATH_REFERENCE.md → "Per-group Optimizer Constraints"
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Dict, Mapping, Optional


def _freeze_dict(d: Optional[Dict[str, float]]) -> Optional[Mapping[str, float]]:
    """Convert dict → MappingProxyType (read-only view) для defensive immutability.

    Audit fix: frozen=True dataclass предотвращает field reassignment, но
    `bundle.channel_min_pct['TV'] = 0.9` всё равно мутировал shared state.
    """
    if d is None:
        return None
    return MappingProxyType(dict(d))


@dataclass(frozen=True)
class ConstraintBundle:
    """All constraint sliders applicable к single optimization run.

    All `_pct` values fractional (0.5 = 50%, 1.5 = 150%). None = not set.

    Audit fixes (2026-04-28):
    - per-channel dicts wrapped в MappingProxyType (immutable view)
    - __post_init__ validates все pct values finite + non-negative
    """
    # Global (always required)
    global_min_pct: float
    global_max_pct: float

    # Per-group (optional — Trust 3 brand/perf only)
    brand_min_pct: Optional[float] = None
    brand_max_pct: Optional[float] = None
    perf_min_pct: Optional[float] = None
    perf_max_pct: Optional[float] = None

    # Per-channel (optional — expert mode override).
    # Note: ConstraintBundle freezes contents через __post_init__ → callers
    # cannot mutate dicts post-hoc.
    channel_min_pct: Optional[Mapping[str, float]] = None
    channel_max_pct: Optional[Mapping[str, float]] = None

    def __post_init__(self):
        # Validate finite + non-negative для всех scalar pct values
        scalars = {
            'global_min_pct': self.global_min_pct,
            'global_max_pct': self.global_max_pct,
            'brand_min_pct': self.brand_min_pct,
            'brand_max_pct': self.brand_max_pct,
            'perf_min_pct': self.perf_min_pct,
            'perf_max_pct': self.perf_max_pct,
        }
        for name, val in scalars.items():
            if val is None:
                continue
            if not isinstance(val, (int, float)):
                raise ValueError(f"{name}={val!r} must be numeric (int|float|None)")
            if not math.isfinite(val):
                raise ValueError(f"{name}={val} must be finite (no NaN/Inf)")
            if val < 0:
                raise ValueError(f"{name}={val} must be non-negative (got {val})")

        # Validate global_min ≤ global_max
        if self.global_min_pct > self.global_max_pct:
            raise ValueError(
                f"global_min_pct ({self.global_min_pct}) > global_max_pct "
                f"({self.global_max_pct}) — incoherent"
            )

        # Per-channel dict elements: validate finite/non-negative + freeze view
        for dict_name, d in [('channel_min_pct', self.channel_min_pct),
                              ('channel_max_pct', self.channel_max_pct)]:
            if d is None:
                continue
            for ch, val in d.items():
                if not isinstance(val, (int, float)) or not math.isfinite(val) or val < 0:
                    raise ValueError(
                        f"{dict_name}[{ch!r}]={val!r} must be finite non-negative number"
                    )

        # Freeze per-channel dicts (defensive immutability)
        object.__setattr__(self, 'channel_min_pct', _freeze_dict(self.channel_min_pct))
        object.__setattr__(self, 'channel_max_pct', _freeze_dict(self.channel_max_pct))


class FeasibilityError(ValueError):
    """Raised when constraint configuration infeasible.

    Contains actionable hint в .message field.
    """
    pass


def resolve_channel_bounds(
    col: str,
    current_money: float,
    channel_categories: Dict[str, str],
    bundle: ConstraintBundle,
) -> tuple[float, float]:
    """Resolve money-axis bounds для single channel using 3-level precedence.

    Precedence: per-channel > per-group > global.
    Mixed/unknown category channels → fall back к global (H3).

    Args:
        col: channel name
        current_money: current spend в money axis (must be ≥ 0 finite)
        channel_categories: {channel: 'brand'|'performance'|'mixed'}, missing key OK
        bundle: ConstraintBundle с all sliders

    Returns:
        (min_money, max_money): bounds for SLSQP optimization.

    Raises:
        ValueError: если current_money negative or non-finite (audit fix).
    """
    if not isinstance(current_money, (int, float)) or not math.isfinite(current_money):
        raise ValueError(f"current_money={current_money!r} must be finite numeric")
    if current_money < 0:
        raise ValueError(
            f"current_money={current_money} must be non-negative (channel='{col}'). "
            f"Negative spend = corrupted data. Возможно неверный unit_cost."
        )
    # Resolve min_pct
    if bundle.channel_min_pct and col in bundle.channel_min_pct:
        min_pct = bundle.channel_min_pct[col]  # per-channel override
    else:
        category = channel_categories.get(col)
        if category == 'brand' and bundle.brand_min_pct is not None:
            min_pct = bundle.brand_min_pct
        elif category == 'performance' and bundle.perf_min_pct is not None:
            min_pct = bundle.perf_min_pct
        else:
            # mixed/unknown/no-group-set → global
            min_pct = bundle.global_min_pct

    # Resolve max_pct (mirror logic)
    if bundle.channel_max_pct and col in bundle.channel_max_pct:
        max_pct = bundle.channel_max_pct[col]
    else:
        category = channel_categories.get(col)
        if category == 'brand' and bundle.brand_max_pct is not None:
            max_pct = bundle.brand_max_pct
        elif category == 'performance' and bundle.perf_max_pct is not None:
            max_pct = bundle.perf_max_pct
        else:
            max_pct = bundle.global_max_pct

    return (current_money * min_pct, current_money * max_pct)


def validate_feasibility(
    channel_money: Dict[str, float],
    channel_categories: Dict[str, str],
    bundle: ConstraintBundle,
    budget: float,
    tolerance: float = 0.001,
) -> None:
    """Pre-flight constraint feasibility validation. Raises FeasibilityError если infeasible.

    Checks:
    1. group_max ≤ global_max enforced (H4 fix — prevent slider conflict)
    2. Σ(min bounds) ≤ budget ≤ Σ(max bounds) — SLSQP solvable

    Args:
        channel_money: {channel: current_money_spend}
        channel_categories: {channel: 'brand'|'performance'|'mixed'}
        bundle: ConstraintBundle
        budget: target total budget
        tolerance: float comparison tolerance (0.1% default)

    Raises:
        FeasibilityError с actionable message.
    """
    # Check 1: group max ≤ global max
    if bundle.brand_max_pct is not None and bundle.brand_max_pct > bundle.global_max_pct:
        raise FeasibilityError(
            f"Brand max ({bundle.brand_max_pct * 100:.0f}%) превышает global max "
            f"({bundle.global_max_pct * 100:.0f}%). "
            f"Brand max должен быть ≤ global max — иначе constraint hierarchy нарушается."
        )
    if bundle.perf_max_pct is not None and bundle.perf_max_pct > bundle.global_max_pct:
        raise FeasibilityError(
            f"Performance max ({bundle.perf_max_pct * 100:.0f}%) превышает global max "
            f"({bundle.global_max_pct * 100:.0f}%). "
            f"Performance max должен быть ≤ global max — иначе constraint hierarchy нарушается."
        )

    # Check 2: budget feasibility
    bounds = {col: resolve_channel_bounds(col, money, channel_categories, bundle)
              for col, money in channel_money.items()}
    total_min = sum(b[0] for b in bounds.values())
    total_max = sum(b[1] for b in bounds.values())

    if budget < total_min * (1 - tolerance):
        raise FeasibilityError(
            f"Budget ({budget:,.0f}) меньше суммы минимумов ({total_min:,.0f}). "
            f"Уменьшите per-channel min либо увеличьте budget. "
            f"Превышение: {(total_min - budget):,.0f} ₽."
        )
    if budget > total_max * (1 + tolerance):
        raise FeasibilityError(
            f"Budget ({budget:,.0f}) больше суммы максимумов ({total_max:,.0f}). "
            f"Увеличьте per-channel max либо уменьшите budget. "
            f"Превышение: {(budget - total_max):,.0f} ₽."
        )


def lock_group_to_current(
    bundle: ConstraintBundle,
    group: str,
) -> ConstraintBundle:
    """Quick action — lock group bounds к 100% (H5 fix — common contractual brand budget).

    Args:
        bundle: existing ConstraintBundle
        group: 'brand' or 'performance'

    Returns:
        New ConstraintBundle с group_min=group_max=1.0.
    """
    if group == 'brand':
        return ConstraintBundle(
            global_min_pct=bundle.global_min_pct,
            global_max_pct=bundle.global_max_pct,
            brand_min_pct=1.0,
            brand_max_pct=1.0,
            perf_min_pct=bundle.perf_min_pct,
            perf_max_pct=bundle.perf_max_pct,
            channel_min_pct=bundle.channel_min_pct,
            channel_max_pct=bundle.channel_max_pct,
        )
    elif group == 'performance':
        return ConstraintBundle(
            global_min_pct=bundle.global_min_pct,
            global_max_pct=bundle.global_max_pct,
            brand_min_pct=bundle.brand_min_pct,
            brand_max_pct=bundle.brand_max_pct,
            perf_min_pct=1.0,
            perf_max_pct=1.0,
            channel_min_pct=bundle.channel_min_pct,
            channel_max_pct=bundle.channel_max_pct,
        )
    raise ValueError(f"Unknown group '{group}'. Valid: 'brand', 'performance'")
