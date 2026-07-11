from __future__ import annotations

import json
from pathlib import Path

# Читаем файл один раз при импорте модуля
_DATA_PATH = Path(__file__).parent.parent / "data" / "kpi_display_registry.json"
_registry: dict = {}

def _load() -> dict:
    """Загружает реестр из JSON-файла (кешируется на модуль)."""
    global _registry
    if not _registry:
        with open(_DATA_PATH, encoding="utf-8") as f:
            _registry = json.load(f)
    return _registry


def plural(n: int, forms: list[str]) -> str:
    """Русская плюрализация. forms = [ед.ч., 2-4, 5+]."""
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return forms[0]
    elif n10 in (2, 3, 4) and n100 not in (12, 13, 14):
        return forms[1]
    else:
        return forms[2]


def get_display(kpi_type: str, custom_forms: list[str] | None = None) -> dict:
    """Возвращает паспорт отображения для указанного типа KPI."""
    data = _load()
    kpi_map = data["kpi"]
    if kpi_type not in kpi_map:
        valid = ", ".join(sorted(kpi_map.keys()))
        raise ValueError(f"Неизвестный kpi_type='{kpi_type}'. Допустимые: {valid}")
    result = dict(kpi_map[kpi_type])
    if kpi_type == "count_custom" and custom_forms is not None:
        if len(custom_forms) != 3:
            raise ValueError("custom_forms должен содержать ровно 3 строки")
        result = dict(result)
        result["result_forms"] = list(custom_forms)
        result["result_unit_short"] = custom_forms[0].split()[0] if custom_forms[0] else "ед."
    return result


def currency_symbol() -> str:
    """Возвращает символ валюты из реестра."""
    return _load()["currency"]["symbol"]


def all_display_types() -> tuple[str, ...]:
    """Возвращает кортеж всех доступных типов KPI."""
    return tuple(_load()["kpi"].keys())
