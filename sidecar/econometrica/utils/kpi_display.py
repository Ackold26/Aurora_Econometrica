from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Читаем файл один раз при импорте модуля
_DATA_PATH = Path(__file__).parent.parent / "data" / "kpi_display_registry.json"
_registry: dict = {}

def _load() -> dict:
    """Загружает реестр из JSON-файла (кешируется на модуль)."""
    global _registry
    if not _registry:
        try:
            with open(_DATA_PATH, encoding="utf-8") as f:
                _registry = json.load(f)
        except FileNotFoundError:
            # Б-54 (13.09.2026): в собранном PyInstaller-пакете каталог data/
            # раньше не попадал в --add-data (см. build_sidecar.py), и дефект
            # молчал месяцами - оба вызывающих (aurora_html/sections.py::
            # _passport_html, aurora_pptx/kpi_helpers.py::_passport) ловят широкий
            # except Exception и тихо возвращают None, отчёт откатывается на
            # подписи ROI по умолчанию для ЛЮБОГО KPI без единого следа. Оставляем
            # запись в журнале sidecar ДО того, как исключение уйдёт вызывающему -
            # widen except выше не трогаем (он и должен собрать отчёт без паспорта,
            # не уронить его), но теперь пропажа реестра видна без живого прогона.
            logger.error(
                'Реестр отображения KPI не найден: %s - отчёт откатится на '
                'денежные подписи ROI по умолчанию для любого показателя',
                _DATA_PATH,
            )
            raise
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


def active_channels_phrase(n: int) -> str:
    """«N активный канал / N активных канала / N активных каналов» — единая
    точка склонения для мест, где рядом с числом каналов стоит согласованное
    прилагательное «активный» (SCQAR-ситуация, сводка «Из N активных каналов»).

    s49 (18.09.2026): и aurora_html (шаблон в strings_ru.json печатал голое
    «активных каналов» независимо от N), и aurora_pptx (своя локальная пара
    _ch_word/_ch_adj в builder.py) декленировали это же число раздельно,
    каждый по-своему - тот же класс дефекта, что чинили в этой же сессии для
    подписи периода. Прилагательное берёт им.п.ед.ч. только при «канал»; при
    «канала»/«каналов» - род.п.мн.ч. «активных» (одна форма для 2-4 и 5+).
    """
    noun = plural(n, ["канал", "канала", "каналов"])
    adj = "активный" if noun == "канал" else "активных"
    return f"{n} {adj} {noun}"


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


def fmt_pct(v: Any, fallback: str = "-") -> str:
    """N1 (Phase 0.1 fix-session 2026-04-25): conditional precision - never lies via rounding to 0%.

    Общий счётчик на веб-отчёт и колоду (аудит s46, находка 5: колода округляла
    `{:.0f}%` и печатала «+0%» там, где веб-отчёт на тех же числах писал «+0.4%» -
    прямое повторение уже записанной ошибки, урок не был унаследован колодой).

    Pre-fix: `{:.0f}%` rounded 0.4% to 0%, producing absurd narrative claims like
    "канал даёт 26% продаж при 0% бюджета" (Performance had 0.4% spend share).

    Behavior:
      0          → "0%"
      |v| < 0.1  → "<0.1%" (with sign)
      |v| < 1    → "0.4%"  (one decimal)
      else       → "26%"   (rounded int)
    """
    if v is None:
        return fallback
    try:
        f = float(v)
    except (TypeError, ValueError):
        return fallback
    if f == 0:
        return "0%"
    av = abs(f)
    if av < 0.1:
        return "<0.1%" if f > 0 else ">-0.1%"
    if av < 1.0:
        return f"{f:.1f}%"
    return f"{round(f)}%"


def fmt_share_pct(v: Any, fallback: str = "-") -> str:
    """Доля канала в разбивке бюджета (аудит s47, находка 5): фиксированная
    одна десятая, БЕЗ условной точности `fmt_pct`.

    `fmt_pct` округляет значения ≥1% до целого — правильно для дельт/MAPE/ширины
    диапазона, где сумма по строке ничего не значит. Доли каналов — другая
    задача: несколько строк читаются как одна таблица, и их сумма обязана
    сходиться к 100 на глаз, иначе клиент, сложивший колонку «Доля», решает,
    что счёт разъехался. `{:.0f}%` даёт 87.5+7.5+5.0 → 88+8+5 = 101%.
    Один знак после запятой (87.5%+7.5%+5.0%=100.0%) убирает расхождение,
    ничего не округляя дважды. Расчёт `share_pct` (planning.py) не меняется —
    меняется только показ.

    0 и None не получают отдельной ветки: доля канала неотрицательна по
    построению (planning.py:541 делит на положительную сумму), и "0.0%" для
    исчезающе малого канала — не ложь, в отличие от 0% в `fmt_pct`.
    """
    if v is None:
        return fallback
    try:
        f = float(v)
    except (TypeError, ValueError):
        return fallback
    return f"{f:.1f}%"
