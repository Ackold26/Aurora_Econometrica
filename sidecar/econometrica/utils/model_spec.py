"""
Single source of truth for the Bayesian MMM model specification.

Used by exporters (MD via Rust, XLSX via Rust, PPTX via Python) to render the
"Спецификация модели" section so the client sees the exact mathematical form
of the model and the priors used in inference.

Keep priors here in sync with `engines/modeler.py` (search for `# Priors`).
"""
from typing import Any


def bayesian_mmm_spec() -> dict[str, Any]:
    """Spec block for the canonical Bayesian MMM (PyMC + NumPyro NUTS)."""
    return {
        'family': 'bayesian_mmm',
        'engine': 'PyMC + NumPyro (JAX) NUTS',
        'title': 'Спецификация модели',
        'subtitle': 'Байесовская Media Mix Model с Adstock и Hill saturation',

        # Plain-text formula (Unicode math, renders cleanly in MD/XLSX/PPTX)
        'formula': (
            'Sales_t = β₀ + Σᵢ βᵢ · Hill(Adstock(Media_i,t), αᵢ, γᵢ) '
            '+ Σⱼ γⱼ · Control_j,t + ε_t'
        ),

        # LaTeX form (for MD via mathjax/katex viewers)
        'formula_latex': (
            r'Sales_t = \beta_0 + \sum_i \beta_i \cdot Hill(Adstock(Media_{i,t}), \alpha_i, \gamma_i) '
            r'+ \sum_j \gamma_j \cdot Control_{j,t} + \varepsilon_t'
        ),

        'transformations': [
            {
                'name': 'Hill (saturation)',
                'formula': 'Hill(x, α, γ) = x^α / (x^α + γ^α)',
                'note': 'Моделирует убывающую отдачу: первые рубли работают сильнее последних.',
            },
            {
                'name': 'Adstock (geometric)',
                'formula': "x'_t = x_t + λ · x'_{t-1}",
                'note': 'Накопительный эффект: реклама прошлого периода продолжает работать.',
            },
            {
                'name': 'Adstock (Weibull)',
                'formula': "x'_t = Σ θ₁^((k-1)^θ₂) · x_{t-k}",
                'note': 'Гибкая форма затухания: пик может быть отложен (TV).',
            },
        ],

        # Priors mirror engines/modeler.py - keep in sync.
        'priors': [
            {
                'symbol': 'β₀',
                'name': 'intercept (базовые продажи)',
                'distribution': 'Normal(0, 0.5)',
                'note': 'нормализованная шкала, центр 0',
            },
            {
                'symbol': 'βᵢ',
                'name': 'media coefficients',
                'distribution': 'HalfNormal(0.3)',
                'note': 'положительные эффекты медиа; tight prior для устойчивости NUTS',
            },
            {
                'symbol': 'αᵢ',
                'name': 'Hill steepness',
                'distribution': 'Gamma(5, 3)',
                'note': 'mean ≈ 1.67, var ≈ 0.56 - типичная форма saturation',
            },
            {
                'symbol': 'γᵢ',
                'name': 'Hill half-saturation',
                'distribution': 'Beta(3, 3)',
                'note': 'концентрируется около 0.5 - половина насыщения посередине шкалы',
            },
            {
                'symbol': 'γⱼ',
                'name': 'control coefficients',
                'distribution': 'Normal(0, 0.3)',
                'note': 'эффекты сезонности/праздников/тренда',
            },
            {
                'symbol': 'σ',
                'name': 'noise (residual std)',
                'distribution': 'HalfNormal(0.3)',
                'note': 'на нормализованной шкале (std(y) = 1)',
            },
        ],

        'inference': {
            'method': 'NUTS (No-U-Turn Sampler) через NumPyro/JAX',
            'default_chains': 2,
            'default_draws': 500,
            'default_tune': 500,
            'note': (
                'Tight priors устраняют funnel-геометрию и сводят divergences к нулю '
                'на малых выборках (~30 наблюдений).'
            ),
        },

        'normalization': (
            'Media и control нормализованы (X / max(X)) перед инференсом, '
            'y нормализован к std=1 - для стабильной NUTS-геометрии.'
        ),
    }


# Convenience constant for callers that just want the spec dict.
MMM_SPEC: dict[str, Any] = bayesian_mmm_spec()
