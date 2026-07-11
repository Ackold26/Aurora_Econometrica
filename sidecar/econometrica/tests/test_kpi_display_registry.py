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
    get_display,
    plural,
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
