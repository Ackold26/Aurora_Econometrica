"""
KPI/mode-aware label helpers для AuroraPPTXBuilder (v1.3.2).

Mirrors aurora_html/sections.py:_kpi_view contract. Exported в отдельный
модуль чтобы импортироваться без `aurora_tokens` зависимости (которая
тянется через builder.py и недоступна вне production pipeline).

Builder.py reads `data['kpi']` (populated narrative_adapter, ADR-016) и
условно показывает CPU / Доля вместо ROI/mROAS. legacy ctx без 'kpi' →
backward compat v1.2.
"""
from __future__ import annotations


_DEFAULT_KPI_LABELS = {
    "metric_label": "ROI",
    "metric_short_label": "ROI",
    "target_unit_label": "₽",
    "target_axis_label": "Продажи, ₽",
    "methodology_label": "",
}


def kpi_view(data):
    """Extract KPI metadata + labels с v1.2 backward-compat fallback."""
    if not isinstance(data, dict):
        data = {}
    kpi = data.get("kpi") or {}
    kpi_kind = kpi.get("kpi_kind") or "monetary"
    mode = kpi.get("derived_mode") or "roi"
    labels = {**_DEFAULT_KPI_LABELS, **(kpi.get("labels") or {})}
    return {
        "kpi_kind": kpi_kind,
        "mode": mode,
        "metric_label": labels["metric_label"],
        "metric_short": labels["metric_short_label"],
        "target_unit": labels["target_unit_label"],
        "target_axis": labels["target_axis_label"],
        "methodology_label": labels["methodology_label"],
        "vpcu": kpi.get("value_per_count_unit"),
        "vpcu_label": kpi.get("value_per_count_unit_label") or "",
        "is_legacy": kpi_kind == "monetary" and mode == "roi",
    }


def fmt_metric(value, kpi, fallback="-"):
    """Format metric value per (kpi_kind, mode). No HTML wrappers.

    B4 audit fix: backend convention - per-channel mroas/roi всегда mathematical
    ratio (units_kpi / ₽_spend). Для count это units/₽; CPU = 1/x. Invert
    before display чтобы «120 ₽/ед.» означало true CPU, не raw units/₽.
    """
    if value is None:
        return fallback
    try:
        f = float(value)
    except (TypeError, ValueError):
        return fallback
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        if abs(f) <= 1.0:
            return f"{f * 100:.1f}%"
        return f"{f:.0f}%"
    if kind == "count":
        # Invert units/₽ → CPU ₽/ед. Edge: zero/negative → fallback.
        if f > 0:
            return f"{1.0 / f:.0f} ₽/ед."
        return fallback
    return f"{f:.2f}×"


def fmt_metric_with_ci_text(mean, ci_low, ci_high, kpi):
    """KPI-aware text-only CI bracket: '80 ₽/ед. [60-100]' / '1.5× [1.2-1.8]'.

    B4 audit fix: для count mode CI flips (units/₽ → CPU); swap order для
    canonical [lo_cpu - hi_cpu] display.
    """
    base = fmt_metric(mean, kpi)
    if ci_low is None or ci_high is None:
        return base
    if kpi.get("mode") == "effectiveness":
        if mean is None:
            return base
        try:
            lo = float(ci_low) * (100 if abs(float(ci_low)) <= 1.0 else 1)
            hi = float(ci_high) * (100 if abs(float(ci_high)) <= 1.0 else 1)
        except (TypeError, ValueError):
            return base
        return f"{base} [{lo:.1f}-{hi:.1f}]"
    if kpi.get("kpi_kind") == "count":
        try:
            lo_raw = float(ci_low)
            hi_raw = float(ci_high)
            # Invert and swap: lo_mroas → hi_cpu, hi_mroas → lo_cpu.
            lo_cpu = 1.0 / hi_raw if hi_raw > 0 else float('inf')
            hi_cpu = 1.0 / lo_raw if lo_raw > 0 else float('inf')
            if not (lo_cpu < float('inf') and hi_cpu < float('inf')):
                return base
            return f"{base} [{lo_cpu:.0f}-{hi_cpu:.0f}]"
        except (TypeError, ValueError, ZeroDivisionError):
            return base
    try:
        return f"{base} [{float(ci_low):.2f}-{float(ci_high):.2f}]"
    except (TypeError, ValueError):
        return base


def weighted_summary_phrase(weighted_value, kpi):
    """Aggregate portfolio metric phrase per kpi/mode.

    Narrative_adapter всегда возвращает weighted_roi = contrib / spend. Для
    count KPI это units/₽ (обратное к CPU), потому инвертируем.
    """
    if weighted_value is None:
        return ""
    try:
        wv = float(weighted_value)
    except (TypeError, ValueError):
        return ""
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        return "Средняя доля каналов в портфеле"
    if kind == "count":
        if wv > 0:
            cpu = 1.0 / wv
            return f"CPU портфеля {cpu:.0f} ₽/ед."
        return "CPU портфеля недоступен"
    return f"ROI портфеля {wv:.2f}×"


def under_breakeven_phrase(kpi):
    """Условие «канал убыточен» для текстов рекомендаций."""
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        return "доля < бенчмарка"
    if kind == "count":
        vpcu = kpi.get("vpcu")
        if vpcu:
            return f"CPU > {float(vpcu):.0f} ₽/ед. (выше ценности)"
        return "CPU > ценности единицы (убыточно)"
    return "mROAS < 1×"


def table_metric_header(kpi):
    """Returns (header, unit) для столбца метрики action_table."""
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        return ("Доля эффекта", "%")
    if kind == "count":
        return ("CPU", "₽/ед.")
    return ("mROAS", "×")
