"""Validator: derived metrics (SOM / SOV / market_share) — BUG #3 fix v2.0.1.

Endogeneity risk: эти метрики computed из KPI (brand_sales / total_market).
Использование как predictor → predictor зависит от outcome. По умолчанию
исключаем из модели (role='unused'). Юзер может explicitly включить
через Roles UI override.

Discovered through pilot UI testing на Кагоцел РФ+ dataset 2026-05-14:
classification put «SOM в руб», «SOM в уп.» в role='control' — это создавало
endogeneous predictor risk в model training.
"""
import sys
from pathlib import Path

# Add sidecar to path для import engines.validator.
SIDECAR_DIR = Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica'
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest
from engines.validator import detect_column_role, detect_column_role_with_confidence


class TestDerivedMetricsExcluded:
    """SOM / SOV / market_share / доля_рынка должны классифицироваться как 'unused'."""

    @pytest.mark.parametrize("col_name", [
        "SOM в руб",
        "SOM в уп.",
        "som в %",
        "SOM (бренд)",
        "som_brand",
        "SOV",
        "SOV (W 25-54)",
        "sov_total",
        "share_of_market",
        "share of market",
        "market_share",
        "market share",
        "share_of_voice",
        "share of voice",
        "доля_рынка",
        "доля рынка",
        "доля_голоса",
        "доля голоса",
    ])
    def test_derived_metric_returns_unused(self, col_name):
        """Каждое из этих имён должно дать role='unused' (excluded by default)."""
        role, conf = detect_column_role_with_confidence(col_name)
        assert role == 'unused', f"Expected 'unused' for {col_name!r}, got {role!r}"
        assert conf >= 0.80, f"Confidence too low for {col_name!r}: {conf}"


class TestDerivedFixDoesNotMaskRegression:
    """Регрессия не должна mark `mosgorsovet`/`sovetnik`/`somatic` как unused.

    Pre-existing: CONTROL_PATTERNS использует substring matching ('sov', 'som')
    без separator-awareness, поэтому 'mosgorsovet' попадает в 'control'. Это
    accepted technical debt в validator.py (TODO: миграция к utils/column_detection
    с separator-aware regex). Тест ensures что мой DERIVED_KEYS fix НЕ
    превращает их в 'unused' (т.е. не делает регрессию хуже).
    """

    @pytest.mark.parametrize("col_name", [
        # SVOK = «share of voice конкурентов» — обрабатывается explicit pattern.
        "svok",
        "svok_2024",
        # Pre-existing false positives — остаются 'control', НЕ становятся 'unused'.
        "mosgorsovet",
        "sovetnik",
        "somatic",
    ])
    def test_my_fix_does_not_mark_as_unused(self, col_name):
        """Critical: эти примеры НЕ должны быть 'unused' (BUG #3 fix не applied)."""
        role = detect_column_role(col_name)
        assert role != 'unused', f"Regression: {col_name!r} unexpectedly classified as 'unused'"


class TestCompetitorOverrideStillWorks:
    """Конкурент-keys должны ВСЕГДА → control, даже если содержат SOM/SOV."""

    @pytest.mark.parametrize("col_name", [
        "TRPs конкуренты (W 25-54)",
        "Продажи в уп. конкуренты",
        "competitor_trp",
        "конкурент_показы",
    ])
    def test_competitor_priority_preserved(self, col_name):
        role = detect_column_role(col_name)
        assert role == 'control', f"Competitor override broken for {col_name!r}"


class TestCategoryVolumeIsControl:
    """Фаза Б: продажи ВСЕЙ категории/рынка (объём) → control (экзогенный спрос),
    даже когда имя содержит «продажи». Доля рынка (derived) остаётся unused."""

    @pytest.mark.parametrize("col_name", [
        "Продажи категории",
        "Продажи в руб. категория",
        "Объём рынка",
        "Объем рынка, уп.",
        "Рынок всего",
        "category sales",
        "total market volume",
    ])
    def test_category_volume_is_control(self, col_name):
        role, conf = detect_column_role_with_confidence(col_name)
        assert role == 'control', f"Category volume должно быть control, got {role!r} для {col_name!r}"
        assert conf >= 0.80

    @pytest.mark.parametrize("col_name", [
        "доля рынка",       # derived → unused (не перехвачено category)
        "market_share",     # derived → unused
    ])
    def test_market_share_still_unused(self, col_name):
        """Category-override НЕ должен захватить долю рынка (она endogenous)."""
        assert detect_column_role(col_name) == 'unused'


class TestKpiTargetsStillKpi:
    """Sales / продажи / выручка не должны быть affected fix-ом."""

    @pytest.mark.parametrize("col_name", [
        "Продажи в руб. бренд",
        "sales_packs",
        "revenue",
        "Продажи в уп. бренд",
    ])
    def test_kpi_unaffected(self, col_name):
        role = detect_column_role(col_name)
        assert role == 'kpi', f"KPI detection broken for {col_name!r}"
