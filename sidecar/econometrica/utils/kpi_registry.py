"""
Aurora Econometrica — KPI registry (v1.3.0).

Centralizes per-KPI configuration: likelihood, hyperpriors, ceiling, baseline drift,
**kpi_kind semantics** (monetary vs count vs proportional), and value-per-count-unit UI labels.

v1.3.0 (2026-05-12) — additive расширение per ADR-016:
- New field `kpi_kind`: 'monetary' | 'count' | 'proportional'.
- New field `value_per_count_unit_label`: UI-label template для count KPIs.
- New field `out_of_scope_v13`: маркирует KPIs, которые не получают v1.3 KPI-aware enhancements
  (awareness — для Phase B Aurora Brand Tracker).
- 7 new count KPIs: sales_packs, leads, registrations, loyalty_cards, subscriptions,
  app_installs, custom.

Usage:
    from utils.kpi_registry import KPI_REGISTRY, get_kpi_config, is_count_kpi

    config = get_kpi_config('sales_packs')  # raises ValueError if unknown
    likelihood = config.likelihood          # 'normal'
    kpi_kind = config.kpi_kind              # 'count'
    label = config.value_per_count_unit_label  # 'Маржа на упаковку, ₽'

References:
- Math reference: docs/MATH_REFERENCE.md → "KPI Registry"
- ADR-016 (KPI kinds binary verdict semantics).
- ADR-017 (Bundle schema v1.3 additive).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Tuple

# Likelihood choices
KPILikelihood = Literal['normal', 'logit_normal', 'beta']

# v1.3.0: KPI kind semantics.
# monetary  → target в рублях (sales_rub, revenue, profit). Главная метрика канала — ROI.
# count     → target в штуках (sales_packs, leads, registrations, etc.). Главная метрика канала — CPU vs value_per_count_unit.
# proportional → target доля/percentage (awareness). Out of scope в v1.3.0 (Phase B).
KPIKind = Literal['monetary', 'count', 'proportional']


@dataclass(frozen=True)
class KPIConfig:
    """Immutable KPI-specific model configuration.

    Frozen для defensive use (config объекты не mutate'ятся между runs).
    """
    name: str
    likelihood: KPILikelihood

    # v1.3.0 — bridge между data-side classification и UX/verdict semantics.
    # See ADR-016 for binary monetary/count rationale.
    kpi_kind: KPIKind = 'monetary'

    # v1.3.0 — UI-label template для value_per_count_unit field.
    # Empty string для monetary KPIs (поле не показывается).
    # Per-KPI customization: 'Маржа на упаковку, ₽' / 'Ценность лида, ₽' / etc.
    value_per_count_unit_label: str = ''

    # v1.3.0 — KPIs marked out_of_scope_v13 не получают KPI-aware enhancements
    # этого релиза (verdicts, insights, отчёты остаются прежними). Per ADR-016.
    out_of_scope_v13: bool = False

    # Outcome bounds. None = unbounded (sales). 100 = awareness percent.
    ceiling: Optional[float] = None

    # Hierarchical adstock decay priors (logit-normal hyperpriors per group).
    # Sales: Trust 3 frozen values (modeler.py:408-411).
    # Awareness: longer brand build-up calibrated.
    brand_mu_logit_prior: Tuple[float, float] = (0.7, 0.3)      # (mu, sigma)
    perf_mu_logit_prior: Tuple[float, float] = (-1.4, 0.7)
    mixed_mu_logit_prior: Tuple[float, float] = (-1.4, 0.7)

    # Group-level beta sigmas (HalfNormal). Trust 3 lines 367-369.
    brand_beta_sigma: float = 0.7
    perf_beta_sigma: float = 0.3
    mixed_beta_sigma: float = 0.4

    # Hill saturation:
    #   gammas Beta(alpha, beta) — half-saturation point
    #   alphas — steepness
    gammas_alpha: float = 3.0
    gammas_beta: float = 3.0

    # Whether to add Gaussian random walk baseline drift (M2 fix для awareness).
    baseline_drift: bool = False

    # Observation noise prior σ (HalfNormal sigma).
    obs_sigma_prior: float = 0.3

    # Phase 2 S7 (audit pass 2 2026-05-02) — KPI-aware forecast horizon settings.
    # Hard cap multiplier для forecast_periods / train_n. Sales=2.0 (Robyn/Meridian
    # convention); awareness ставит tighter (1.5) т.к. brand build-up длиннее →
    # β stationarity слабее.
    forecast_horizon_max_multiplier: float = 2.0
    # Soft warning threshold (forecast / train ratio above which user sees
    # «extrapolation warning»). Sales=1.5×, awareness=1.2×.
    forecast_horizon_warn_multiplier: float = 1.5


# ─── Registered KPIs ────────────────────────────────────────────────────────

KPI_REGISTRY: Dict[str, KPIConfig] = {
    # ─── MONETARY ────────────────────────────────────────────────────────────
    'sales': KPIConfig(
        name='sales',
        likelihood='normal',
        kpi_kind='monetary',
        ceiling=None,                              # unbounded
        brand_mu_logit_prior=(0.7, 0.3),           # ~12wk half-life
        perf_mu_logit_prior=(-1.4, 0.7),           # ~1.3wk half-life
        mixed_mu_logit_prior=(-1.4, 0.7),
        brand_beta_sigma=0.7,
        perf_beta_sigma=0.3,
        mixed_beta_sigma=0.4,
        gammas_alpha=3.0,
        gammas_beta=3.0,
        baseline_drift=False,
        obs_sigma_prior=0.3,
    ),

    # Aliases для удобства, разные кеsы той же monetary семантики.
    'revenue': KPIConfig(
        name='revenue',
        likelihood='normal',
        kpi_kind='monetary',
        # Same as 'sales' — alias (поле name внутри identifier).
        # Priors одинаковы — semantically revenue=sales для MMM.
    ),

    'profit': KPIConfig(
        name='profit',
        likelihood='normal',
        kpi_kind='monetary',
        # Same Trust 3 priors. Profit отличается от revenue только в данных
        # (вычитают COGS) — модель внутренне идентична.
    ),

    # ─── COUNT ──────────────────────────────────────────────────────────────
    # Все count KPIs используют sales priors (Trust 3) как baseline.
    # Pilot validation на реальных данных уточнит calibration в Phase B.

    'sales_packs': KPIConfig(
        name='sales_packs',
        likelihood='normal',
        kpi_kind='count',
        value_per_count_unit_label='Маржа на упаковку, ₽',
        # Same priors as sales (count vs ₽ — это про шкалу, не про temporal dynamics).
    ),

    'leads': KPIConfig(
        name='leads',
        likelihood='normal',
        kpi_kind='count',
        value_per_count_unit_label='Ценность лида, ₽',
    ),

    'registrations': KPIConfig(
        name='registrations',
        likelihood='normal',
        kpi_kind='count',
        value_per_count_unit_label='Ценность регистрации, ₽',
    ),

    'loyalty_cards': KPIConfig(
        name='loyalty_cards',
        likelihood='normal',
        kpi_kind='count',
        value_per_count_unit_label='Ценность выданной карты, ₽',
    ),

    'subscriptions': KPIConfig(
        name='subscriptions',
        likelihood='normal',
        kpi_kind='count',
        value_per_count_unit_label='MRR на подписку, ₽',
    ),

    'app_installs': KPIConfig(
        name='app_installs',
        likelihood='normal',
        kpi_kind='count',
        value_per_count_unit_label='Ценность установки, ₽',
    ),

    'count_custom': KPIConfig(
        name='count_custom',
        likelihood='normal',
        kpi_kind='count',
        # Юзер задаёт свой label через project state — здесь default.
        value_per_count_unit_label='Ценность единицы, ₽',
    ),

    # ─── PROPORTIONAL (out of scope v1.3) ───────────────────────────────────
    'awareness': KPIConfig(
        name='awareness',
        likelihood='logit_normal',                  # bounded, logit-Normal stable
        kpi_kind='proportional',
        out_of_scope_v13=True,                      # v1.3 enhancements не применяются
        ceiling=100.0,                              # awareness % cap
        # Awareness brand build-up длиннее: ~26wk (vs sales 12wk).
        brand_mu_logit_prior=(1.4, 0.4),
        perf_mu_logit_prior=(-0.7, 0.5),
        mixed_mu_logit_prior=(-0.7, 0.5),
        brand_beta_sigma=0.5,
        perf_beta_sigma=0.2,
        mixed_beta_sigma=0.3,
        gammas_alpha=2.0,
        gammas_beta=5.0,
        baseline_drift=True,
        obs_sigma_prior=0.5,
        forecast_horizon_max_multiplier=1.5,
        forecast_horizon_warn_multiplier=1.2,
    ),
}


def get_kpi_config(kpi_type: str) -> KPIConfig:
    """Lookup KPI config с explicit error если unknown.

    Args:
        kpi_type: KPI name (e.g. 'sales', 'sales_packs', 'leads').

    Returns:
        Frozen KPIConfig instance.

    Raises:
        ValueError: если kpi_type не в KPI_REGISTRY OR not str OR None.
    """
    if not isinstance(kpi_type, str):
        raise ValueError(
            f"kpi_type must be string (got {type(kpi_type).__name__}={kpi_type!r})"
        )
    if kpi_type not in KPI_REGISTRY:
        valid = sorted(KPI_REGISTRY.keys())
        raise ValueError(f"Unknown kpi_type='{kpi_type}'. Valid: {valid}")
    return KPI_REGISTRY[kpi_type]


def list_kpi_types() -> tuple[str, ...]:
    """Return tuple of registered KPI types (UI dropdowns + Pydantic validation)."""
    return tuple(sorted(KPI_REGISTRY.keys()))


def is_count_kpi(kpi_type: str) -> bool:
    """True если KPI имеет count семантику (sales_packs, leads, etc.).

    Используется в decomposer / optimizer / reports для бинарной dispatch
    monetary vs count verdict tables (ADR-016).
    """
    return get_kpi_config(kpi_type).kpi_kind == 'count'


def is_monetary_kpi(kpi_type: str) -> bool:
    """True если KPI имеет monetary семантику (sales_rub, revenue, profit)."""
    return get_kpi_config(kpi_type).kpi_kind == 'monetary'


def is_out_of_scope_v13(kpi_type: str) -> bool:
    """True если KPI помечен как out of scope для v1.3 KPI-aware enhancements.

    Currently: awareness. Применяется decomposer/reports для fallback
    на v1.2 текстовые шаблоны (без KPI-aware rewrite).
    """
    return get_kpi_config(kpi_type).out_of_scope_v13


def get_value_per_count_unit_label(kpi_type: str) -> str:
    """UI-label для value_per_count_unit поля. Empty string для monetary KPIs.

    Примеры:
    - 'sales_packs' → 'Маржа на упаковку, ₽'
    - 'leads' → 'Ценность лида, ₽'
    - 'subscriptions' → 'MRR на подписку, ₽'
    - 'sales' (monetary) → ''
    """
    return get_kpi_config(kpi_type).value_per_count_unit_label


def list_count_kpi_types() -> tuple[str, ...]:
    """Tuple of count KPI types only (UI: «Продажи в штуках / Лиды / ...»)."""
    return tuple(sorted(
        name for name, config in KPI_REGISTRY.items()
        if config.kpi_kind == 'count'
    ))


def list_monetary_kpi_types() -> tuple[str, ...]:
    """Tuple of monetary KPI types only."""
    return tuple(sorted(
        name for name, config in KPI_REGISTRY.items()
        if config.kpi_kind == 'monetary'
    ))


# ─── Validation на module import (fail-fast vs runtime surprise) ─────────────
def _validate_registry() -> None:
    """Module-load-time sanity check для KPI_REGISTRY entries."""
    for name, config in KPI_REGISTRY.items():
        # Likelihood-ceiling consistency.
        if config.likelihood == 'logit_normal' or config.likelihood == 'beta':
            if config.ceiling is None or config.ceiling <= 0.1:
                raise ValueError(
                    f"KPI_REGISTRY['{name}']: bounded likelihood ({config.likelihood}) "
                    f"requires ceiling > 0.1 (got {config.ceiling}). "
                    f"Logit-Normal clipping breaks для small ceiling."
                )
        # Beta sigmas positivity.
        if config.brand_beta_sigma <= 0 or config.perf_beta_sigma <= 0 or config.mixed_beta_sigma <= 0:
            raise ValueError(
                f"KPI_REGISTRY['{name}']: beta sigmas must be positive"
            )
        # Hill gammas positivity.
        if config.gammas_alpha <= 0 or config.gammas_beta <= 0:
            raise ValueError(
                f"KPI_REGISTRY['{name}']: Beta(α, β) для gammas requires α>0, β>0"
            )
        # Obs sigma positivity.
        if config.obs_sigma_prior <= 0:
            raise ValueError(
                f"KPI_REGISTRY['{name}']: obs_sigma_prior must be positive"
            )
        # v1.3.0 ADR-016: kpi_kind ↔ value_per_count_unit_label consistency.
        if config.kpi_kind == 'count' and not config.value_per_count_unit_label:
            raise ValueError(
                f"KPI_REGISTRY['{name}']: count KPI requires non-empty "
                f"value_per_count_unit_label (got '')."
            )
        if config.kpi_kind == 'monetary' and config.value_per_count_unit_label:
            raise ValueError(
                f"KPI_REGISTRY['{name}']: monetary KPI cannot have "
                f"value_per_count_unit_label (got '{config.value_per_count_unit_label}'). "
                f"Monetary KPIs measure target в ₽ directly — value-per-unit поле не применимо."
            )


_validate_registry()
