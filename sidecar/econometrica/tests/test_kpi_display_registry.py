"""Тесты реестра отображения KPI (kpi_display.py + kpi_display_registry.json)."""
from __future__ import annotations

import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import json
import pytest
from utils.kpi_display import (
    all_display_types,
    fmt_share_pct,
    get_display,
    plural,
    share_pct_value,
)
from utils.kpi_registry import assert_display_registry_consistent


def test_all_registry_types_present():
    """assert_display_registry_consistent не падает при корректном реестре."""
    assert_display_registry_consistent()


def test_kind_matches_registry():
    """kpi_kind в JSON совпадает с kind в kpi_registry для каждого типа."""
    from utils.kpi_registry import KPI_REGISTRY
    for kpi_type in KPI_REGISTRY:
        display = get_display(kpi_type)
        assert display["kpi_kind"] == KPI_REGISTRY[kpi_type].kpi_kind, (
            f"kpi_type={kpi_type}: kind в registry={KPI_REGISTRY[kpi_type].kpi_kind}, "
            f"в display JSON={display['kpi_kind']}"
        )


_LEAD_FORMS = ["лид", "лида", "лидов"]


@pytest.mark.parametrize("n,expected_idx", [
    (1, 0), (2, 1), (5, 2), (11, 2), (21, 0), (22, 1), (12, 2), (114, 2),
])
def test_plural_russian(n, expected_idx):
    """Русская плюрализация на формах лидов."""
    assert plural(n, _LEAD_FORMS) == _LEAD_FORMS[expected_idx]


def test_get_display_count_custom_override():
    """get_display('count_custom', custom_forms) подменяет result_forms."""
    custom = ["визит", "визита", "визитов"]
    display = get_display("count_custom", custom)
    assert display["result_forms"] == custom


def test_unknown_type_raises():
    """get_display с неизвестным типом → ValueError."""
    with pytest.raises(ValueError):
        get_display("bogus")


def test_generator_idempotent():
    """Генератор даёт одинаковый вывод при двух вызовах подряд."""
    from pathlib import Path

    # Добавляем tools в path для импорта генератора
    tools_dir = SIDECAR_DIR / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from sync_kpi_display import generate

    json_path = SIDECAR_DIR / "data" / "kpi_display_registry.json"
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    result1 = generate(data)
    result2 = generate(data)
    assert result1 == result2


class TestSharePctValueRounding:
    """Аудит s47, находка 5 (та же точка класса, что fmt_share_pct): доля
    канала округляется до одной десятой, а не до целого — иначе сумма долей
    строк таблицы каналов расходится со 100 (87.5+7.5+5.0 → int-round
    88+8+5=101). share_pct_value — общая точка для sections.py (HTML action
    table) и builder.py (_build_action_table_rows), где "%" уже в шапке
    столбца и ячейке не нужен свой знак.
    """

    def test_three_channels_sum_to_100(self):
        total = 1000.0
        parts = [875.0, 75.0, 50.0]  # 87.5% / 7.5% / 5.0%
        shares = [share_pct_value(p, total) for p in parts]
        assert shares == [87.5, 7.5, 5.0]
        assert sum(shares) == pytest.approx(100.0)

    def test_zero_or_missing_total_is_zero_not_zerodiv(self):
        assert share_pct_value(10, 0) == 0.0
        assert share_pct_value(10, None) == 0.0
        assert share_pct_value(None, 100) == 0.0

    def test_matches_fmt_share_pct_rounding_convention(self):
        # Одна десятая — общий принцип с fmt_share_pct (уже готовый процент).
        value = share_pct_value(87.5, 100.0)
        assert fmt_share_pct(value) == "87.5%"

    def test_sum_may_differ_from_100_by_a_tenth(self):
        # Аудит s50, L-3: одна десятая не обещает ровно 100.0 — три равных
        # канала дают 33.3×3 = 99.9 (докстрока share_pct_value говорит честно).
        shares = [share_pct_value(1, 3) for _ in range(3)]
        assert shares == [33.3, 33.3, 33.3]
        assert round(sum(shares), 1) == 99.9
