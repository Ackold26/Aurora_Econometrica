"""
aurora_html.sections - 17 section renderers.

Each function emits an HTML fragment wrapped in `<section id="{id}">...`,
aligned with PPTX S7 slides:

    s01 cover → render_cover       s02 summary → render_executive_summary
    s03 findings → render_at_a_glance   s04 divider → render_section_divider
    s05 key → render_key_message   s06 mroas → render_mroas
    s07 share → render_share       s08 table → render_action_table
    s09 timeline → render_timeline s10 recommend → render_recommendation
    s11 method → render_methodology s12 sources → render_sources
    s13 glossary → render_glossary s14 closing → render_closing

Progressive enhancement: every section must be readable without JS.
JS layer adds sortable columns, drill-downs, counters, etc.
"""
from __future__ import annotations

import math
from typing import Any

from .security import escape


# ─── Helpers ────────────────────────────────────────────────────────────────

def _fmt_int(v: Any, fallback: str = "-") -> str:
    try:
        return f"{int(round(float(v))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return fallback


def _fmt_num(v: Any, fallback: str = "-") -> str:
    try:
        return f"{float(v):.0f}"
    except (TypeError, ValueError):
        return fallback


def _fmt_mln(v: Any, fallback: str = "-") -> str:
    """0 if <10 decimals → 1, else integer millions."""
    try:
        x = float(v)
        return f"{x:.1f}" if abs(x) < 10 else f"{x:.0f}"
    except (TypeError, ValueError):
        return fallback


def _contrib_scale(kpi: dict, raw_values: Any, money_unit: str = "₽ млн") -> tuple:
    """Масштаб и единица столбца «Вклад» (fix 2026-07-13: единица ↔ масштаб).

    Корень бага: вклад канала делился на 1e6 безусловно («₽ млн»), а для count-KPI
    единица подписывалась без «млн» → клиент видел «1.3 лид.» вместо «1.3 млн лид.»
    (занижение в 1e6, нарушение INV-50). Здесь масштаб и единица выбираются вместе.

    monetary/effectiveness → (1e6, money_unit) «₽ млн».
    count → адаптивный масштаб по макс |вклад|, единица результата из паспорта.
    """
    if kpi.get("kpi_kind") != "count":
        return 1_000_000.0, money_unit
    unit = kpi.get("target_unit") or "ед."
    try:
        mx = max((abs(float(v or 0)) for v in raw_values), default=0.0)
    except (TypeError, ValueError):
        mx = 0.0
    if mx >= 1_000_000:
        return 1_000_000.0, f"млн {unit}"
    if mx >= 10_000:
        return 1_000.0, f"тыс. {unit}"
    return 1.0, unit


def _fmt_contrib(value: Any, scale: float, fallback: str = "-") -> str:
    """Значение вклада в масштабе из _contrib_scale (единый форматтер для ₽ и count)."""
    try:
        x = float(value) / scale
    except (TypeError, ValueError, ZeroDivisionError):
        return fallback
    if scale == 1.0:
        return f"{x:,.0f}".replace(",", chr(0xA0))
    return f"{x:.1f}" if abs(x) < 10 else f"{x:.0f}"


def _fmt_x(v: Any, fallback: str = "-") -> str:
    try:
        return f"{float(v):.2f}×"
    except (TypeError, ValueError):
        return fallback


def _fmt_x_bare(v: Any, fallback: str = "-") -> str:
    """Same as _fmt_x but без × - для CI bracket inner numbers."""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return fallback


def _ci_tier_class(mean: Any, ci_low: Any, ci_high: Any) -> str:
    """Phase 1.9: returns CSS class for CI width tier - green/amber/red badge.

    Per ADR Amendment A5:
        relative_width < 0.5  → ci-tier-good   (Уверенная)
        0.5 - 1.0             → ci-tier-warn   (Направленная)
        > 1.0                 → ci-tier-bad    (Высокая неопределённость)

    Returns empty string when CI unavailable (no badge applied).
    """
    try:
        m = float(mean)
        lo = float(ci_low)
        hi = float(ci_high)
    except (TypeError, ValueError):
        return ""
    if abs(m) < 1e-10:
        return "ci-tier-bad"
    rw = (hi - lo) / abs(m)
    if rw < 0.5:
        return "ci-tier-good"
    elif rw < 1.0:
        return "ci-tier-warn"
    else:
        return "ci-tier-bad"


def _fmt_x_with_ci(mean: Any, ci_low: Any, ci_high: Any) -> str:
    """Format value with optional 90% CI bracket: '2.4× [1.8 - 3.1]'.

    Returns plain '_fmt_x' when CI unavailable (Phase 1.9 backward compat).
    Bracket span has CSS class ci-bracket plus tier class for color tinting.
    """
    base = _fmt_x(mean)
    if ci_low is None or ci_high is None:
        return base
    tier = _ci_tier_class(mean, ci_low, ci_high)
    return (
        f'{base} <span class="ci-bracket {tier}">'
        f'[{_fmt_x_bare(ci_low)} - {_fmt_x_bare(ci_high)}]</span>'
    )


def _fmt_pct(v: Any, fallback: str = "-") -> str:
    """N1 (Phase 0.1 fix-session 2026-04-25): conditional precision - never lies via rounding to 0%.

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


# ─── KPI/mode-aware helpers (v1.3.2) ────────────────────────────────────────
#
# ctx['kpi'] populated narrative_adapter (см. ADR-016). Когда блок отсутствует
# (legacy callers, v1.2 contexts) - fallback к monetary ROI поведению.

_DEFAULT_KPI_LABELS = {
    "metric_label": "ROI",
    "metric_short_label": "ROI",
    "target_unit_label": "₽",
    "target_axis_label": "Продажи, ₽",
    "methodology_label": "",
}


def _passport_html(kpi_type: str | None) -> dict | None:
    """Загружает паспорт KPI из реестра. None при kpi_type=None или ошибке."""
    if not kpi_type:
        return None
    try:
        from utils.kpi_display import get_display
        return get_display(kpi_type)
    except Exception:
        return None


def _kpi_view(ctx: dict) -> dict:
    """Extract KPI metadata + labels с v1.2 backward-compat fallback.

    Фаза 1a: читает ctx['kpi']['kpi_type'] и перегенерирует паспортные подписи
    через kpi_display (target_axis, target_unit, metric_label, cpu_per_label).
    Если kpi_type отсутствует — работает как раньше (labels из pre-built dict).
    """
    kpi = (ctx.get("kpi") or {}) if isinstance(ctx, dict) else {}
    kpi_kind = kpi.get("kpi_kind") or "monetary"
    mode = kpi.get("derived_mode") or "roi"
    kpi_type = kpi.get("kpi_type") or None
    labels = {**_DEFAULT_KPI_LABELS, **(kpi.get("labels") or {})}

    # Фаза 1a: если kpi_type известен — перегенерируем паспортные подписи из реестра.
    P = _passport_html(kpi_type)
    if P:
        if P.get("result_axis_label"):
            labels["target_axis_label"] = P["result_axis_label"]
        if P.get("result_unit_short"):
            labels["target_unit_label"] = P["result_unit_short"]
        if mode != "effectiveness" and kpi_kind == "count" and P.get("cpu_per_label"):
            labels["metric_label"] = f'CPU, {P["cpu_per_label"]}'
            labels["metric_short_label"] = "CPU"

    return {
        "kpi_kind": kpi_kind,
        "mode": mode,
        "kpi_type": kpi_type,
        "metric_label": labels["metric_label"],
        "metric_short": labels["metric_short_label"],
        "target_unit": labels["target_unit_label"],
        "target_axis": labels["target_axis_label"],
        "methodology_label": labels["methodology_label"],
        "vpcu": kpi.get("value_per_count_unit"),
        "vpcu_label": kpi.get("value_per_count_unit_label") or "",
        "cpu_per_label": P["cpu_per_label"] if (P and P.get("cpu_per_label")) else "₽/ед.",
        "is_legacy": kpi_kind == "monetary" and mode == "roi",
    }


def _fmt_metric(value: Any, kpi: dict, fallback: str = "-") -> str:
    """Format metric value per (kpi_kind, mode).

    Backend convention (per narrative_adapter._merge_channels): channel-level
    mroas/roi всегда mathematical ratio = KPI_units / ₽. Для monetary это
    ROI multiplier (rubles_kpi / rubles_spend = ×). Для count это units/₽
    (например 0.0125 ед./₽). CPU = 1 / units_per_ruble = ₽/ед.

    Display rules:
    - monetary roi: 1.5 → '1.50×' (no transform)
    - count: 0.0125 → invert → '80 ₽/ед.' (CPU display)
    - effectiveness fraction (0..1): 0.25 → '25.0%' (×100)
    - effectiveness >1: 25 → '25%' (assumed already percentage)

    Per-channel raw values for count come как units/₽ в input. Если caller
    хочет передать ready CPU value (как из weighted_summary intermediate
    calc), pass it raw: invert again сводится к no-op только if 1/v == v
    (v=1). Edge case rare.
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
        # share метрика. Если |value| <= 1 - fraction. Иначе уже %.
        if abs(f) <= 1.0:
            return f"{f * 100:.1f}%"
        return f"{f:.0f}%"
    if kind == "count":
        # B4 audit fix: c.mroas / c.roi от backend = units/₽ (mathematical).
        # Invert to CPU для user-facing display.
        # Фаза 1a: cpu_per_label из kpi (установлен _kpi_view) вместо жёсткого '₽/ед.'.
        if f > 0:
            unit = kpi.get("cpu_per_label") or "₽/ед."
            return f"{1.0 / f:.0f} {unit}"
        return fallback
    return f"{f:.2f}×"


def _fmt_metric_bare(value: Any, kpi: dict, fallback: str = "-") -> str:
    """Inner CI-bracket version (без unit suffix). См. _fmt_metric inversion rules."""
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
            return f"{f * 100:.1f}"
        return f"{f:.0f}"
    if kind == "count":
        # B4 audit fix: invert units/₽ → CPU (bare, без unit suffix, для CI bracket).
        if f > 0:
            return f"{1.0 / f:.0f}"
        return fallback
    return f"{f:.2f}"


def _fmt_metric_with_ci(mean: Any, ci_low: Any, ci_high: Any, kpi: dict) -> str:
    """KPI-aware analog of _fmt_x_with_ci.

    B4 audit fix: для count mode CI inverts (units/₽ → CPU ₽/ед.), что
    flips ordering: lo_mroas → hi_cpu, hi_mroas → lo_cpu. Swap order для
    отображения [lo_cpu - hi_cpu].
    """
    base = _fmt_metric(mean, kpi)
    if ci_low is None or ci_high is None:
        return base
    tier = _ci_tier_class(mean, ci_low, ci_high)
    # Для count mode swap, т.к. invert flips ordering.
    if kpi.get("kpi_kind") == "count" and kpi.get("mode") != "effectiveness":
        # ci_low / ci_high в units/₽ space → invert → CPU space → swap.
        lo_str = _fmt_metric_bare(ci_high, kpi)  # inverted CI_high = smaller CPU
        hi_str = _fmt_metric_bare(ci_low, kpi)   # inverted CI_low = larger CPU
    else:
        lo_str = _fmt_metric_bare(ci_low, kpi)
        hi_str = _fmt_metric_bare(ci_high, kpi)
    return (
        f'{base} <span class="ci-bracket {tier}">'
        f'[{lo_str} - {hi_str}]</span>'
    )


def _weighted_summary_phrase(weighted_value: Any, kpi: dict) -> str:
    """Краткая фраза «средний ROI/CPU/доля портфеля» с числом.

    Narrative_adapter всегда отдаёт `weighted_roi = total_contrib / total_spend`.
    Для count KPI - это units/₽ (обратное к CPU), потому преобразуем к CPU = 1/x.

    monetary roi: 'ROI портфеля 1.50×'
    count: 'CPU портфеля 120 ₽/ед.'
    effectiveness: 'Средняя доля каналов в портфеле'
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
            # Фаза 1a: cpu_per_label из kpi (установлен _kpi_view) вместо жёсткого '₽/ед.'.
            unit = kpi.get("cpu_per_label") or "₽/ед."
            return f"CPU портфеля {cpu:.0f} {unit}"
        return "CPU портфеля недоступен"
    return f"ROI портфеля {wv:.2f}×"


def _under_breakeven_phrase(kpi: dict) -> str:
    """Описание условия 'канал убыточен' для текстов рекомендаций.

    Фаза 1a: cpu_per_label из kpi (установлен _kpi_view) вместо жёсткого '₽/ед.'.
    """
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        return "доля < бенчмарка"
    if kind == "count":
        vpcu = kpi.get("vpcu")
        unit = kpi.get("cpu_per_label") or "₽/ед."
        if vpcu:
            return f"CPU > {float(vpcu):.0f} {unit} (выше ценности)"
        return "CPU > ценности единицы (убыточно)"
    return "mROAS < 1×"


def _table_metric_header(kpi: dict) -> tuple:
    """Returns (header_label, unit_label) для столбца главной метрики action_table.

    Фаза 1a: cpu_per_label из kpi (установлен _kpi_view) вместо жёсткого '₽/ед.'.
    """
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        return ("Доля эффекта", "%")
    if kind == "count":
        unit = kpi.get("cpu_per_label") or "₽/ед."
        return ("CPU", unit)
    return ("mROAS", "×")


def _lift_phrase(lift_pct: float | None, kpi: dict) -> str:
    """KPI-aware формулировка ожидаемого прироста для HTML-отчёта.

    Пласт 2 (2026-07-11): устраняет «Ожидаемый прирост ROAS» для count/effectiveness.
    - monetary roi  → «Ожидаемый прирост ROAS: +N пп»
    - count         → «Ожидаемый прирост результата: +N пп»
    - effectiveness → «Ожидаемый прирост доли эффекта: +N пп»
    - lift=None     → «Ожидаемый эффект – положительный»
    """
    if lift_pct is None:
        return "Ожидаемый эффект – положительный"
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        return f"Ожидаемый прирост доли эффекта: +{lift_pct:.1f} пп"
    if kind == "count":
        return f"Ожидаемый прирост результата: +{lift_pct:.1f} пп"
    return f"Ожидаемый прирост ROAS: +{lift_pct:.1f} пп"


def _hero_vs_leader_quote(hero: str, leader: str, kpi: dict) -> str:
    """KPI-aware pull quote «лидер vs герой» для HTML-отчёта.

    Пласт 2 (2026-07-11): устраняет «Каждый рубль» для count/effectiveness.
    - monetary roi  → «Каждый рубль в {hero} возвращает больше, чем в {leader}.»
    - count         → «Каждая единица результата в {hero} обходится дешевле, чем в {leader}.»
    - effectiveness → «{hero} даёт большую долю эффекта, чем {leader}.»
    """
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        return f"{hero} даёт большую долю эффекта, чем {leader}."
    if kind == "count":
        return f"Каждая единица результата в {hero} обходится дешевле, чем в {leader}."
    return f"Каждый рубль в {hero} возвращает больше, чем в {leader}."


def _reliability_disclaimer_html(ctx: dict) -> str:
    """F-A1-9 (2026-07-06): дисклеймер ненадёжности для клиентского HTML-отчёта.

    Вызывает model_reliability_verdict на данных диагностики из ctx и рендерит
    жёлтый баннер при unreliable/uncertain. При reliable — возвращает пустую строку.
    Паттерн: аналогично PPTX narrative_adapter.honesty_verdict.
    """
    diag = ctx.get("diagnostics") or {}
    # Приоритет: если honesty_verdict уже вычислен в diagnostics (modeler.py), читаем его.
    # Иначе — вычисляем здесь (legacy path: старые pickles без поля).
    verdict_str = diag.get("honesty_verdict")
    if verdict_str is None:
        try:
            from utils.optimizer_honesty import model_reliability_verdict
            _r = model_reliability_verdict(diag)
            verdict_str = _r.get("verdict", "unknown")
        except Exception:
            verdict_str = "unknown"
    if verdict_str not in ("unreliable", "uncertain"):
        return ""
    if verdict_str == "unreliable":
        note = "Модель имеет высокий R-hat или много расходящихся цепей – результаты ниже ориентировочные."
    else:
        note = "Узкий объём данных или слабый prior-coverage – результаты ниже трактуйте осторожно."
    return (
        '<div class="reliability-disclaimer" role="alert" style="'
        "margin:16px 0;padding:14px 18px;background:rgba(201,164,73,0.12);"
        "border:1px solid rgba(201,164,73,0.4);border-radius:8px;"
        "font-size:13px;line-height:1.5;color:#e2e8f0;"
        '">'
        f'<strong style="color:#c9a449;">⚠ Ориентировочная модель.</strong> '
        f'{escape(note)}'
        '</div>'
    )


def _section(section_id: str, kicker: str, body: str, extra_cls: str = "") -> str:
    cls = f"section section-{section_id}" + (f" {extra_cls}" if extra_cls else "")
    k = f'<div class="section-kicker">{escape(kicker)}</div>' if kicker else ""
    return f'<section id="{escape(section_id)}" class="{cls}">\n{k}\n{body}\n</section>'


def _action_title(title: str, lime: bool = True) -> str:
    lime_el = '<div class="sacred-lime" aria-hidden="true"></div>' if lime else ""
    return f'<h2 class="action-title">{escape(title)}</h2>\n{lime_el}'


# ─── Section renderers ──────────────────────────────────────────────────────

def render_cover(ctx: dict) -> str:
    """Section 1: Hero Cover."""
    meta = ctx["meta"]
    strings = ctx["strings"]
    period = meta.get("report_date") or ""
    version = meta.get("version") or ""
    kicker = strings["sections"]["cover"]["kicker"]
    brand_mark = ctx.get("brand_mark_svg") or ""
    # 2026-05-04: gold-accent sigil over h1 - Aurora deliverable brand mark.
    # Wrapped в <div class="cover-brand-mark"> для CSS sizing/positioning.
    brand_mark_html = (
        f'<div class="cover-brand-mark" role="img" aria-label="Aurora AI">{brand_mark}</div>'
        if brand_mark else ""
    )

    body = f"""
<div class="cover">
  {brand_mark_html}
  <h1>Декомпозиция медиабюджета</h1>
  <p class="subtitle">и рекомендации по оптимизации</p>
  <div class="sacred-lime" aria-hidden="true" style="width: 64px; height: 3px; margin-top: 24px;"></div>
  <dl class="cover-meta">
    <div class="cover-meta-cell">
      <dt class="cover-meta-label">Подготовлено для</dt>
      <dd class="cover-meta-value">{escape(meta.get("client") or "-")}</dd>
    </div>
    <div class="cover-meta-cell">
      <dt class="cover-meta-label">Дата</dt>
      <dd class="cover-meta-value">{escape(period)}</dd>
    </div>
    <div class="cover-meta-cell">
      <dt class="cover-meta-label">Классификация</dt>
      <dd class="cover-meta-value">Confidential</dd>
    </div>
  </dl>
</div>"""
    return _section("cover", kicker, body)


def render_executive_summary(ctx: dict) -> str:
    """Section 2: Executive Summary - SCQAR preview (full blocks in s10).

    Design decision (I5 audit followup, v1.3.2): scqar templates в strings_ru.json
    остаются single-mode (monetary roi baseline). KPI-aware adaptations делаются
    через Python-side overrides ниже (situation / recommendation per kpi_kind, mode).

    Alternative considered & rejected: per-mode template blocks в JSON
    (scqar.monetary.situation, scqar.count.situation, etc.). Trade-offs:

    Pros JSON per-mode (rejected):
        - Translators see all variants together.
        - No conditional logic в Python.

    Cons JSON per-mode (chosen reason):
        - Translation tooling (typical lokalise / crowdin) optimized для flat
          keypaths. Nested per-mode requires custom workflow.
        - 12 KPI modes × 5 SCQAR blocks = 60 template entries (vs current 5).
          Maintenance overhead для feature что меняется реже чем 1 раз в год.
        - Override pattern proven через 5 audit fixes (Q1 2026 v1.3.0 + v1.3.2):
          adding new mode = single Python branch, не JSON file edit.
        - JSON nesting усложнил бы schema validation + test fixtures.

    Maintainer responsibility: при добавлении нового kpi mode - добавить branch
    в situation block (line ~234) + recommendation block (line ~484). Avoid
    JSON proliferation.
    """
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    meta = ctx["meta"]
    kicker = strings["sections"]["summary"]["kicker"]
    scqar = strings["scqar"]
    kpi = _kpi_view(ctx)

    client = meta.get("client") or "Клиент"
    title = f'Резюме по результатам моделирования'

    # Build placeholder SCQAR when facts present, else short fallback
    if facts and ctx.get("channels"):
        budget = facts.get("total_budget_mln") or 0
        n_ch = facts.get("n_active_channels") or len(ctx["channels"])
        wr = facts.get("weighted_roi") or 1.0
        # Нет числа - нет подписи: метрика может быть не посчитана для этого
        # прогона (ctx["diagnostics"]["mqs_score"] отсутствует) - честный
        # прочерк вместо фиктивного 0, тот же формат что в карточке источников
        # (render_sources) и по всему отчёту (_fmt_num SSOT-фолбэк "-").
        mqs_fmt = _fmt_num(ctx.get("diagnostics", {}).get("mqs_score"))
        leader = facts.get("leader_channel") or "-"
        hero = facts.get("hero_channel") or leader
        leader_pct = facts.get("leader_share_spend_pct") or 0
        hero_m = 0.0
        for c in ctx.get("channels", []):
            if c.get("name") == hero:
                hero_m = float(c.get("mroas") or 0)
                break
        realloc = facts.get("reallocation_mln") or 0
        underperf = ", ".join(facts.get("underperformer_names") or []) or "-"
        lift = facts.get("expected_lift_pct") or 0
        # L14/L15 (math-fix v1.4 Section C, 2026-04-29): use action-driven facts.
        budget_dom = facts.get("budget_dominator_channel") or leader
        bd_spend_pct = facts.get("budget_dominator_spend_pct") or leader_pct
        bd_contrib_pct = facts.get("budget_dominator_contrib_pct") or 0.0
        cut_source = facts.get("cut_source_channel")
        scale_dest = facts.get("scale_destination_channel")

        if kpi["is_legacy"]:
            situation = scqar["situation"]["template"].format(
                client=client, budget_mln=budget, n_channels=n_ch,
                weighted_roi=wr, mqs=mqs_fmt
            )
        else:
            # v1.3.2: KPI-aware situation - заменяем «Weighted ROI X×» на CPU/доля.
            situation = (
                f"{client} размещает {budget:.0f} млн ₽ в квартал через "
                f"{n_ch} активных каналов. {_weighted_summary_phrase(wr, kpi)}, "
                f"MQS модели {mqs_fmt}/100."
            )
        # L14: complication uses budget_dominator (not leader). Fallback when
        # all channels balanced (no clear dominator OR balanced contribution).
        if budget_dom and bd_spend_pct and abs(bd_spend_pct - bd_contrib_pct) >= 5.0:
            complication = scqar["complication"]["template"].format(
                budget_dominator=budget_dom,
                budget_dom_spend_pct_fmt=_fmt_pct(bd_spend_pct),
                budget_dom_contrib_pct_fmt=_fmt_pct(bd_contrib_pct),
                hero=hero, hero_mroas=hero_m,
            )
        else:
            complication = scqar.get("complication_fallback", {}).get(
                "template", "Портфель сбалансирован."
            )
        # Пласт 2 (2026-07-11): KPI-aware question — для count/effectiveness «ROAS» не применим.
        if kpi["is_legacy"]:
            question = scqar["question"]["template"]
        elif kpi["mode"] == "effectiveness":
            question = "Как перераспределить бюджет, чтобы повысить долю эффекта, не снижая awareness?"
        elif kpi["kpi_kind"] == "count":
            question = "Как перераспределить бюджет, чтобы снизить стоимость единицы (CPU), не снижая awareness?"
        else:
            question = scqar["question"]["template"]
        # N3 (Phase 0.1): consistent answer logic with f3 + Action 01.
        # math-fix v1.0.14.1 (2026-04-28): + converged_at_current state - SLSQP
        # вернул current allocation без binding (false convergence). Honest
        # banner вместо vacuous «Сохранить аллокацию».
        binding = bool(facts.get("binding_constraints"))
        converged = facts.get("optimization_converged", True)
        converged_at_current = bool(facts.get("converged_at_current"))
        if not converged:
            answer = (
                "Оптимизация не сошлась. Перед перераспределением "
                "необходимо ослабить ограничения и перезапустить расчёт."
            )
            recommendation = "Прирост ROAS можно будет оценить после успешной оптимизации."
        elif binding:
            answer = (
                "Оптимизатор упёрся в заданные границы. Расширьте Мин./Макс. % "
                "(рекомендуем 10-300%) и перезапустите Оптимизацию для реального перераспределения."
            )
            recommendation = "Прирост ROAS будет рассчитан после расширения границ."
        elif converged_at_current:
            answer = (
                "Оптимизатор сошёлся на текущем распределении - лучшее решение "
                "при заданных границах не найдено. Это может означать что границы "
                "Min/Max задают слишком узкий коридор либо текущая аллокация уже "
                "близка к локальному оптимуму."
            )
            recommendation = (
                "Расширьте границы (10/300% рекомендуется) или используйте "
                "экспертный режим для канал-специфичных ограничений."
            )
        elif realloc >= 0.5 and (cut_source or scale_dest):
            # L15 (math-fix v1.4 Section C): use cut_source / scale_destination
            # from action_summary instead of leader/hero. Fallback templates
            # для edge cases (only-Cut, only-Scale, all-Hold, all-Uncertain).
            # L23 fix (Венарус 2026-04-29): underperf list уже dedup'нут от
            # cut_source в narrative_adapter. Если empty («-») - пропускаем
            # «сократить или остановить» clause целиком чтобы избежать
            # «Перебалансировать ... в Social; сократить или остановить -.»
            has_extra_underperf = bool(facts.get("underperformer_names"))
            if cut_source and scale_dest:
                if has_extra_underperf:
                    answer = scqar["answer"]["template"].format(
                        realloc=realloc, cut_source=cut_source,
                        scale_destination=scale_dest, underperf=underperf,
                    )
                else:
                    # Без underperf clause - основная часть только
                    answer = (
                        f"Перебалансировать {realloc:.0f} млн ₽ из {cut_source} "
                        f"в {scale_dest}."
                    )
            elif scale_dest:  # no Cut signal but Scale opportunity exists
                answer = scqar.get("answer_no_cut", {}).get("template", scqar["answer"]["template"]).format(
                    realloc=realloc, scale_destination=scale_dest,
                )
            else:  # cut_source present but no Scale destination
                answer = scqar.get("answer_no_scale", {}).get("template", scqar["answer"]["template"]).format(
                    realloc=realloc, cut_source=cut_source,
                )
            # v1.3.2 audit fix (M2): scqar.recommendation template = «Ожидаемый
            # прирост ROAS: +N пп». Для non-monetary modes слово «ROAS» leak.
            # Override formula manually per kpi mode.
            # B1-fix R-09/R-13 (2026-07-03): «+0 пп» — пустое обещание; при
            # незначимом lift (<0.5) — честная формулировка без нулевого числа.
            if lift is None or float(lift) < 0.5:
                recommendation = (
                    "Прирост от перераспределения незначим (<0.5 пп) - "
                    "портфель близок к оптимуму в заданных границах."
                )
            elif kpi["is_legacy"]:
                recommendation = scqar["recommendation"]["template"].format(lift=lift)
            elif kpi["mode"] == "effectiveness":
                recommendation = f"Ожидаемый прирост доли эффекта: +{lift:.0f} пп."
            elif kpi["kpi_kind"] == "count":
                recommendation = f"Ожидаемый прирост продаж: +{lift:.0f} пп."
            else:
                recommendation = scqar["recommendation"]["template"].format(lift=lift)
        else:
            # SA19: portfolio with no clear redistribution direction
            counts = facts.get("action_counts") or {}
            uncertain_n = (counts.get("Uncertain") or 0) + (counts.get("Watch") or 0)
            if uncertain_n >= n_ch * 0.5:  # majority uncertain → honest fallback
                answer = scqar.get("answer_uncertain", {}).get(
                    "template",
                    "Недостаточно данных для уверенной рекомендации перераспределения."
                )
            else:
                answer = scqar.get("answer_all_hold", {}).get(
                    "template",
                    f"Сохранить приоритет {leader} с контролем насыщения."
                )
            recommendation = (
                "Дальнейший прирост возможен через расширение границ оптимизации "
                "или сбор большего объёма данных."
            )
    else:
        situation = f"{client} - демонстрационный preview без переданных данных."
        complication = "Narrative появится после обучения модели и оптимизации."
        question = scqar["question"]["template"]
        answer = "Будет сформирована после декомпозиции и оптимизации бюджета."
        recommendation = "Ожидаемый эффект будет рассчитан по результатам пайплайна."

    blocks = [
        (scqar["situation"]["label"], situation, False),
        (scqar["complication"]["label"], complication, False),
        (scqar["question"]["label"], question, True),
        (scqar["answer"]["label"], answer, False),
        (scqar["recommendation"]["label"], recommendation, False),
    ]
    items = "\n".join(
        f'<div class="scqar-block{" accent" if accent else ""}">'
        f'<div class="scqar-label">{escape(label)}</div>'
        f'<div class="scqar-body">{escape(body)}</div>'
        '</div>'
        for label, body, accent in blocks
    )

    # F-A1-9 (2026-07-06): дисклеймер ненадёжности перед денежными инсайтами.
    disclaimer = _reliability_disclaimer_html(ctx)
    body = f"""
{disclaimer}{_action_title(title)}
<div class="scqar">
{items}
</div>"""
    return _section("summary", kicker, body)


def render_at_a_glance(ctx: dict) -> str:
    """Section 3: At-a-Glance - 5 key findings."""
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    channels = ctx.get("channels") or []
    kicker = strings["sections"]["findings"]["kicker"]
    mqs = ctx.get("diagnostics", {}).get("mqs_score")
    kpi = _kpi_view(ctx)

    findings = []
    if facts and channels:
        leader = facts.get("leader_channel") or "-"
        hero = facts.get("hero_channel") or leader
        honest = bool(facts.get("honest_narrative"))
        media_pct = facts.get("media_contribution_pct")
        baseline_pct = facts.get("baseline_pct")
        wr = facts.get("weighted_roi") or 0

        if honest and media_pct is not None and baseline_pct is not None:
            f1 = (
                f"Медиа-вклад {_fmt_pct(media_pct)}, базовый спрос {_fmt_pct(baseline_pct)} – "  # П8-2 П8-1
                f"модель преимущественно объясняет продажи через organic"  # П8-2
            )
            f1_sup = (
                f"{leader} – лидер среди медиа "  # П8-1
                f"({_fmt_pct(facts.get('leader_share_contrib_pct'))} медиа-вклада)"  # П8-2
            )
        else:
            # N1 (Phase 0.1): pre-format pct values to avoid {x:.0f} rounding
            # 0.4% to "0%" - see _fmt_pct conditional precision logic.
            f1 = strings["findings_templates"]["f1_leader"].format(
                leader=leader,
                contrib_pct_fmt=_fmt_pct(facts.get("leader_share_contrib_pct") or 0),
                spend_pct_fmt=_fmt_pct(facts.get("leader_share_spend_pct") or 0),
            )
            if kpi["is_legacy"]:
                f1_sup = strings["findings_templates"]["f1_leader_support"].format(
                    weighted_roi=wr
                )
            else:
                # v1.3.2: KPI-aware portfolio metric (CPU / доля вместо ROI×).
                f1_sup = f"{_weighted_summary_phrase(wr, kpi)} средневзвешенный по каналам"
        findings.append((f1, f1_sup))

        hero_m = 0
        hero_spend_pct = 0
        total_budget = facts.get("total_budget_mln") or 0
        for c in channels:
            if c.get("name") == hero:
                hero_m = float(c.get("mroas") or 0)
                hero_spend = float(c.get("spend") or 0) / 1_000_000.0
                hero_spend_pct = (hero_spend / total_budget * 100) if total_budget else 0
                break

        hero_m_fmt = _fmt_metric(hero_m, kpi) if not kpi["is_legacy"] else f"{hero_m:.1f}×"
        # INV-50 (2026-06-03 synthetic-truth аудит): sub-breakeven hero НИКОГДА не
        # «самый эффективный» — это противоречит его вердикту «убыточный». Гейт
        # расцеплён от honest_narrative (media<10%): даже при media≥10% (honest=False)
        # канал с ROI<1 не коронуется. Зеркалит decomposer._build_channel_insight.
        # effectiveness-mode исключён: там метрика — доля, breakeven неприменим (как
        # all_below_breakeven ниже).
        if hero_m < 1.0 and kpi["mode"] != "effectiveness":
            f2 = f"{hero} - лучший среди медиа, но всё ещё под breakeven ({kpi['metric_short']} {hero_m_fmt})"
            f2_sup = f"{_under_breakeven_phrase(kpi)} означает что канал тратит больше чем приносит инкрементала"
        elif honest:
            f2 = f"{hero} - единственный канал близкий к окупаемости ({kpi['metric_short']} {hero_m_fmt})"
            f2_sup = strings["findings_templates"]["f2_hero_support"].format(hero_spend_pct_fmt=_fmt_pct(hero_spend_pct))
        else:
            if kpi["is_legacy"]:
                f2 = strings["findings_templates"]["f2_hero"].format(hero=hero, hero_mroas=hero_m)
            else:
                # v1.3.2: replace «mROAS X.X×» в шаблоне на KPI-aware фразу.
                f2 = f"{hero} - самый эффективный канал с {kpi['metric_short']} {hero_m_fmt}"
            f2_sup = strings["findings_templates"]["f2_hero_support"].format(hero_spend_pct_fmt=_fmt_pct(hero_spend_pct))
        findings.append((f2, f2_sup))

        realloc = facts.get("reallocation_mln") or 0
        lift = facts.get("expected_lift_pct") or 0
        binding = bool(facts.get("binding_constraints"))
        # v1.3.2 audit fix (M1): для effectiveness mode «all below breakeven»
        # семантически unapplicable (shares always sum to 100%, threshold
        # arbitrary). Skip branch и treat as standard portfolio.
        all_below_breakeven = (
            bool(channels)
            and kpi["mode"] != "effectiveness"
            and all((float(c.get("mroas") or c.get("roi") or 0) < 1.0) for c in channels)
        )
        # N3 (Phase 0.1): if optimizer hit binding constraints, surface that
        # explicitly - otherwise narrative says "сохранить аллокацию" while
        # the real story is "оптимизатор не получил места для манёвра".
        if honest and all_below_breakeven:
            f3 = "Все медиа-каналы под breakeven - рассмотреть сокращение медиа или диагностику данных"
            if kpi["is_legacy"]:
                f3_sup = "При weighted ROI < 1× оптимизация перераспределением не вернёт прибыльность"
            else:
                f3_sup = (
                    f"Когда у всех каналов {_under_breakeven_phrase(kpi)} - "
                    "оптимизация перераспределением не вернёт прибыльность"
                )
        elif binding:
            f3 = "Оптимизатор упёрся в заданные границы - расширьте Мин./Макс. % и перезапустите"
            f3_sup = "Текущие границы зажимают пространство решений - реальное перераспределение скрыто"
        elif realloc >= 0.5 and hero != leader:
            f3 = strings["findings_templates"]["f3_realloc"].format(
                realloc=realloc, leader=leader, hero=hero)
            # Пласт 2 (2026-07-11): KPI-aware — для count/effectiveness «ROAS» не применим.
            if kpi["is_legacy"]:
                f3_sup = strings["findings_templates"]["f3_realloc_support"].format(lift=lift)
            else:
                f3_sup = _lift_phrase(float(lift), kpi)
        else:
            f3 = strings["findings_templates"]["f3_keep"]
            f3_sup = strings["findings_templates"]["f3_keep_support"]
        findings.append((f3, f3_sup))

        scale_n = sum(1 for c in channels if c.get("verdict") == "Scale")
        cut_n = sum(1 for c in channels if c.get("verdict") in ("Cut", "Reduce"))
        f4 = strings["findings_templates"]["f4_verdicts"].format(scale_n=scale_n, cut_n=cut_n)
        f4_sup = strings["findings_templates"]["f4_verdicts_support"].format(n_channels=len(channels))
        findings.append((f4, f4_sup))

        # Нет числа - нет подписи (2026-07-25): mqs_score может отсутствовать
        # (метрика не была рассчитана для этого прогона) - раньше это тихо
        # превращалось в mqs_val=0 и показывало клиенту правдоподобное
        # «Качество модели: 0/100 - Ненадёжное», как будто это результат
        # расчёта, а не факт отсутствия оценки. Честное отсутствие вместо
        # фиктивного нуля - см. тот же принцип в render_sources (mqs_display).
        mqs_val: float | None = None
        if mqs is not None:
            try:
                mqs_val = float(mqs)
            except (TypeError, ValueError):
                mqs_val = None
            # 2026-07-26: NaN проходит float() без исключения и получал вердикт
            # «MQS nan/100 – Ненадёжное» — приговор модели вместо отметки, что
            # оценки нет. NaN приходит штатно: json.loads принимает литерал NaN,
            # а метрики дают его при нулевых фактах. Нечисло — это отсутствие.
            if mqs_val is not None and not math.isfinite(mqs_val):
                mqs_val = None
        if mqs_val is None:
            f5 = strings["findings_templates"]["f5_mqs_unavailable"]
            f5_sup = strings["findings_templates"]["f5_mqs_support_unavailable"]
        else:
            # L16 (math-fix v1.4 Section C, 2026-04-29): align frontend tier labels
            # с backend (utils/diagnostics.py) - single 5-tier source of truth.
            # Pre-fix: frontend had 3 tiers (good/fair/poor at 80/60/<60), backend
            # had 5 tiers (excellent/good/acceptable/weak/poor at 85/70/55/40/<40)
            # → MQS=70 showed «Хорошее» (sources block) vs «приемлемо» (findings).
            # 2026-07-25: локальная копия порогов 85/70/55/40 убрана - тиры читаются
            # из единого SSOT (utils.diagnostics.mqs_tier_info), а не дублируются
            # здесь; дубль этих чисел уже ловили в бою (см. комментарий выше).
            diag_tier = (ctx.get("diagnostics") or {}).get("mqs_tier_label")
            # Audit fix (2026-04-29): explicit `is not None` check distinguishes
            # «backend not provided» vs «backend provided non-empty string».
            # Pre-fix: `if diag_tier:` falsy для empty string '' → silent fallback
            # к local computation, masking backend issues. Post-fix: trust backend
            # value when present (even if empty), only fallback when truly absent.
            # Audit fix (2026-07-26): непустоты мало — ярлык обязан принадлежать
            # набору канона. Прежде сюда проходило любое значение: подстановка
            # ключа `tier` вместо `tier_label` («excellent») печаталась клиенту
            # по-английски и сбивала подбор пояснения на «Приемлемо» при
            # отличной модели, потому что ниже стоит .get(..., 'acceptable').
            # Чужой подписи слой представления не ждёт: не узнал — считает сам.
            # Audit fix (2026-07-27): принадлежности набору тоже мало — ярлык
            # обязан ещё и СООТВЕТСТВОВАТЬ баллу (валидный ярлык канона, но не
            # для этого mqs_val, раньше проходил как есть). Проверка вынесена в
            # SSOT-функцию, а не дублируется здесь и в render_sources ниже.
            from utils.diagnostics import resolve_mqs_tier_label
            tier_label_text = resolve_mqs_tier_label(mqs_val, diag_tier)
            # Support text per tier
            support_key = {
                'Отличное': 'f5_mqs_support_excellent',
                'Хорошее': 'f5_mqs_support_good',
                'Приемлемое': 'f5_mqs_support_acceptable',
                'Слабое': 'f5_mqs_support_weak',
                'Ненадёжное': 'f5_mqs_support_poor',
            }.get(tier_label_text, 'f5_mqs_support_acceptable')
            f5 = strings["findings_templates"]["f5_mqs"].format(
                mqs=mqs_val, tier_label=tier_label_text
            )
            f5_sup = strings["findings_templates"][support_key]
        findings.append((f5, f5_sup))
    else:
        # Preview mode
        findings = [
            ("Модель будет обучена после загрузки данных", "Findings появятся по результатам декомпозиции"),
            ("Leader канал определится из посчитанного contribution", "По вкладу в инкрементальные продажи"),
            ("Hero канал - по mROAS (наибольшая отдача последнего рубля)", "Может отличаться от leader по вкладу"),
            ("Reallocation-рекомендация - из оптимизатора", "Цель: максимизация KPI при текущем бюджете"),
            ("Качество модели измеряется MQS 0-100", "Комбинация R², MAPE, R-hat, ESS"),
        ]

    items = "\n".join(
        f'<li><div class="finding-headline">{escape(f)}</div><p class="finding-support">{escape(s)}</p></li>'
        for f, s in findings
    )

    # Waterfall chart renders underneath findings list when decompose data
    # is present. JS no-ops silently if CHART_DATA.waterfall is empty -
    # keeps section visible without layout collapse.
    body = f"""
{_action_title(strings["action_titles"]["s02_five"])}
<ol class="findings-list">
{items}
</ol>
<div class="chart-container" style="margin-top:32px;">
  <div class="chart-title-bar">
    <div>
      <div class="chart-title">Декомпозиция продаж · вклад компонент</div>
      <div class="chart-subtitle">Базовый спрос + вклад каналов = итоговые продажи</div>  <!-- П8-2 -->
    </div>
    <button class="btn-inline" data-copy-chart="chart-waterfall">Сохранить PNG</button>
  </div>
  <div class="chart-host" id="chart-waterfall" data-chart="waterfall" style="height:320px;">
    <div class="chart-skeleton" aria-hidden="true"></div>
  </div>
</div>"""
    return _section("findings", kicker, body)


def render_section_divider(ctx: dict) -> str:
    """Section 4: Big number + takeaway."""
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    kicker = strings["sections"]["divider"]["kicker"]

    if facts:
        leader = facts.get("leader_channel") or "-"
        cpct = facts.get("leader_share_contrib_pct") or 0
        spct = facts.get("leader_share_spend_pct") or 0
        takeaway = strings["action_titles"]["s04_takeaway"].format(
            leader=leader,
            contrib_pct_fmt=_fmt_pct(cpct),
            spend_pct_fmt=_fmt_pct(spct))
    else:
        takeaway = "Декомпозиция покажет, какие каналы генерируют какой вклад"

    body = f"""
<h2 class="action-title">Декомпозиция вкладов</h2>
<div class="sacred-lime" aria-hidden="true"></div>
<p style="font-family:var(--font-serif);font-style:italic;font-size:20px;color:var(--text-secondary);line-height:1.4;max-width:60ch;margin-top:16px;">{escape(takeaway)}</p>"""
    return _section("divider", kicker, body)


def render_key_message(ctx: dict) -> str:
    """Section 5: Big number (leader contribution) + pull quote."""
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    kicker = strings["sections"]["key"]["kicker"]
    kpi = _kpi_view(ctx)

    if facts:
        leader = facts.get("leader_channel") or "-"
        hero = facts.get("hero_channel") or leader
        cpct = facts.get("leader_share_contrib_pct") or 0
        spct = facts.get("leader_share_spend_pct") or 0
        wr = facts.get("weighted_roi") or 1.0
        honest = bool(facts.get("honest_narrative"))
        media_pct = facts.get("media_contribution_pct")
        baseline_pct = facts.get("baseline_pct")
        # v1.3.2: KPI-aware portfolio metric (ROI×/CPU/доля).
        portfolio_phrase = (
            f"ROI портфеля {wr:.2f}×" if kpi["is_legacy"]
            else _weighted_summary_phrase(wr, kpi)
        )

        if honest and media_pct is not None and baseline_pct is not None:
            title = (
                "Модель преимущественно отражает базовый спрос – "  # П8-2 П8-1
                "медиа-вклад ограничен"
            )
            big = _fmt_pct(media_pct)
            big_label = "Медиа-вклад в продажи"
            big_support = f"Базовый спрос: {_fmt_pct(baseline_pct)} · {portfolio_phrase}"  # П8-2
            quote = (
                f"{leader} – лидер среди медиа ({_fmt_pct(cpct)} медиа-вклада), "  # П8-2 П8-1
                f"но абсолютный медиа-эффект {_fmt_pct(media_pct)} от продаж. "  # П8-2
                "Низкий вклад медиа – проверить отложенный эффект (adstock), насыщение, качество данных."  # П8-2 П8-1
            )
        else:
            title = strings["action_titles"]["s05_default"].format(leader=leader)
            big = _fmt_pct(cpct)
            big_label = f"Доля {leader} в инкрементальных продажах"
            big_support = f"При {_fmt_pct(spct)} доли бюджета · {portfolio_phrase}"

            if hero != leader:
                # Пласт 2 (2026-07-11): KPI-aware, не хардкодить «рубль» для count/effectiveness.
                quote = (
                    f"{_hero_vs_leader_quote(hero, leader, kpi)} "
                    "Сигнал к перераспределению части бюджета."
                )
            else:
                quote = f"{leader} – лидер и по вкладу, и по эффективности. Бюджет стоит сохранить до признаков насыщения."  # П8-1
    else:
        title = "Главный вывод появится после обучения модели"
        big = "-"
        big_label = "Доля лидера в продажах"
        big_support = "По результатам декомпозиции"
        quote = "Pull quote сформируется автоматически на основе leader + hero каналов"

    body = f"""
{_action_title(title)}
<div class="key-message" data-animate-counter>
  <div>
    <div class="big-number" data-counter-end="{escape(big.replace('%','').replace('-','0'))}">{escape(big)}</div>
    <div class="big-number-label">{escape(big_label)}</div>
    <div class="big-number-support">{escape(big_support)}</div>
  </div>
  <blockquote class="pull-quote">{escape(quote)}</blockquote>
</div>"""
    return _section("key", kicker, body)


def render_mroas(ctx: dict) -> str:
    """Section 6: mROAS horizontal bar chart + commentary."""
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    channels = ctx.get("channels") or []
    kicker = strings["sections"]["mroas"]["kicker"]
    kpi = _kpi_view(ctx)

    hero = facts.get("hero_channel") if facts else None
    title = strings["action_titles"]["s06_hero"].format(hero=hero or "лидер портфеля")
    # v1.3.2: chart title/subtitle adaptive per KPI.
    if kpi["mode"] == "effectiveness":
        chart_title_text = "Доля каналов в эффекте · %"
        chart_subtitle_text = "Bar chart по share of effect (доли в продажах)"
    elif kpi["kpi_kind"] == "count":
        cpu_unit = kpi.get("cpu_per_label") or "₽ за единицу"
        chart_title_text = f"CPU по каналам · {cpu_unit}"
        chart_subtitle_text = "Стоимость следующей единицы (incremental cost-per-unit)"
    else:
        chart_title_text = "mROAS по каналам · мультипликатор"
        chart_subtitle_text = "Marginal ROI последнего вложенного рубля"

    # Commentary blocks - math-fix v1.0.14.1 B refactor (2026-04-28).
    # Pre-fix: hardcoded «явный потенциал scale-up» / «потенциал удержания» /
    # «топ-2 канала» based на mROAS rank - independent от derive_verdict в
    # action table → contradictions (Kagocel live-test 2026-04-27).
    # Post-fix: action-driven commentary. Each block reads ch['action_label']
    # + ch['action_reasoning'] populated by narrative_adapter via single source
    # of truth (engines.channel_action.compute_channel_action). Action в table
    # cell + commentary lead garanteed identical per channel.
    if channels and facts:
        # Sort by action priority (Scale=5 first, Hold=4, ..., Cut=0) тогда
        # самые actionable items appear first в commentary. Stable secondary
        # sort by mROAS so within same action group лидер shows first.
        by_priority = sorted(
            channels,
            key=lambda c: (
                -int(c.get("action_priority") or 0),
                -float(c.get("mroas") or 0),
            ),
        )

        # Show top-3 наиболее actionable channels - covers Scale/Reduce/Cut signals
        # + leaves room для Hold + Watch когда no decisive action в портфеле.
        # Skip duplicate action keys (e.g. 4 Scale channels - show only first).
        seen_actions: set[str] = set()
        commentary_blocks = []
        for ch in by_priority:
            ch_action = ch.get("action") or "Watch"
            if ch_action == "Uncertain":
                continue  # uncertain suppressed from commentary
            if ch_action in seen_actions:
                continue
            seen_actions.add(ch_action)
            ch_name = ch.get("name") or "-"
            label = ch.get("action_label") or ch_action
            reasoning = ch.get("action_reasoning") or ""
            commentary_blocks.append((
                f"{ch_name} - {label}.",
                reasoning or f"mROAS {float(ch.get('mroas') or 0):.2f}×, рекомендация по портфелю.",
            ))
            if len(commentary_blocks) >= 3:
                break
        # Fallback когда channels not decorated (legacy callers без narrative_adapter)
        if not commentary_blocks:
            top_m = by_priority[0] if by_priority else {}
            commentary_blocks = [(
                f"{top_m.get('name', '-')} - лидер по mROAS.",
                f"mROAS {float(top_m.get('mroas') or 0):.2f}× по результатам декомпозиции.",
            )]
    else:
        commentary_blocks = [
            ("Chart появится после декомпозиции", "Горизонтальные bar'ы покажут mROAS по каналам с gold hero bar"),
        ]

    commentary_html = "\n".join(
        f'<div class="commentary-block"><div class="commentary-lead">{escape(lead)}</div>'
        f'<div class="commentary-body">{escape(body)}</div></div>'
        for lead, body in commentary_blocks
    )

    body = f"""
{_action_title(title)}
<div class="chart-host-row">
  <div class="chart-container">
    <div class="chart-title-bar">
      <div>
        <div class="chart-title">{escape(chart_title_text)}</div>
        <div class="chart-subtitle">{escape(chart_subtitle_text)}</div>
      </div>
      <div>
        <button class="btn-inline" data-copy-chart="chart-mroas">Сохранить PNG</button>
      </div>
    </div>
    <div class="chart-host" id="chart-mroas" data-chart="mroas">
      <div class="chart-skeleton" aria-hidden="true"></div>
    </div>
  </div>
  <div class="commentary">
    {commentary_html}
  </div>
</div>"""
    return _section("mroas", kicker, body)


def render_share(ctx: dict) -> str:
    """Section 7: Share of Spend vs Share of Effect - side by side bars."""
    strings = ctx["strings"]
    kicker = strings["sections"]["share"]["kicker"]
    body = f"""
{_action_title("Доля бюджета vs доля эффекта - выявление дисбаланса")}
<div class="chart-container">
  <div class="chart-title-bar">
    <div>
      <div class="chart-title">Доля бюджета vs доля эффекта · %</div>
      <div class="chart-subtitle">Каналы с долей эффекта выше доли бюджета недоинвестированы</div>
    </div>
    <button class="btn-inline" data-copy-chart="chart-share">Сохранить PNG</button>
  </div>
  <div class="chart-host" id="chart-share" data-chart="share">
    <div class="chart-skeleton" aria-hidden="true"></div>
  </div>
</div>"""
    return _section("share", kicker, body)


def render_action_table(ctx: dict) -> str:
    """Section 8: Sortable action table + footnotes."""
    strings = ctx["strings"]
    channels = ctx.get("channels") or []
    facts = ctx.get("facts") or {}
    kicker = strings["sections"]["table"]["kicker"]
    headers = strings["table_headers"]
    units = strings["table_units"]
    v_reasons = strings["verdict_reasons"]
    kpi = _kpi_view(ctx)
    # v1.3.2: KPI-aware main metric column (mROAS / CPU / Доля %).
    metric_col_header, metric_col_unit = _table_metric_header(kpi)

    # contrib column масштаб+единица вычисляются ниже (после visible) через
    # _contrib_scale: единица и масштаб выбираются согласованно (fix 2026-07-13,
    # INV-50). budget всегда «₽ млн» (затраты — деньги для любого KPI).

    # Title branching (mirrors PPTX S7 post-audit logic)
    if channels:
        contribs = sorted((float(c.get("contribution") or 0) for c in channels), reverse=True)
        total_real = sum(contribs)
        total_c = total_real or 1.0
        acc = 0.0
        top_n = 0
        for v in contribs:
            acc += v
            top_n += 1
            if acc / total_c >= 0.85:
                break
        pct = int(round(acc / total_c * 100))
        other_n = len(channels) - top_n
        if total_real <= 0:
            title = strings["action_titles"]["s07_zero"]
        elif len(channels) == 1:
            title = strings["action_titles"]["s07_single"]
        elif top_n == 1:
            title = strings["action_titles"]["s07_dominant"].format(pct_fmt=_fmt_pct(pct))
        elif other_n > 0:
            title = strings["action_titles"]["s07_top_n"].format(top_n=top_n, pct_fmt=_fmt_pct(pct))
        else:
            title = strings["action_titles"]["s07_balanced"]
    else:
        title = "Таблица каналов появится после декомпозиции"

    # MAX_CHANNELS_IN_TABLE = 10, matches narrative_adapter
    visible = channels[:10]
    flagged = [c for c in visible if c.get("verdict") in ("Reduce", "Cut")][:3]
    fn_by_name = {c.get("name"): str(i + 1) for i, c in enumerate(flagged) if c.get("name")}

    total_contrib = sum(float(c.get("contribution") or 0) for c in visible) or 1.0

    # Масштаб+единица столбца «Вклад» — согласованно (fix 2026-07-13, INV-50):
    # для count адаптивный масштаб (млн/тыс/ед) с единицей результата из паспорта,
    # для monetary — «₽ млн» как раньше.
    contrib_scale, contrib_unit = _contrib_scale(
        kpi, [c.get("contribution") for c in visible], units["contrib"]
    )

    rows_html = []
    for c in visible:
        name = c.get("name") or "-"
        spend_mln = float(c.get("spend") or 0) / 1_000_000.0
        mroas = c.get("mroas")
        verdict = c.get("verdict") or "Watch"
        share_pct = int(round(float(c.get("contribution") or 0) / total_contrib * 100))
        fn = fn_by_name.get(name, "")
        fn_html = f'<sup class="fn-marker">{fn}</sup>' if fn else ''

        # Phase 1.9: bracket display when posterior CI available (90% HDI).
        # mroas_ci_* aliased from optimizer's mroi_current_ci_* in narrative_adapter._merge_channels.
        mroas_ci_low = c.get("mroas_ci_low")
        mroas_ci_high = c.get("mroas_ci_high")
        if kpi["is_legacy"]:
            mroas_html = _fmt_x_with_ci(mroas, mroas_ci_low, mroas_ci_high)
        else:
            mroas_html = _fmt_metric_with_ci(mroas, mroas_ci_low, mroas_ci_high, kpi)

        rows_html.append(
            f'<tr data-channel="{escape(name)}">'
            f'<td>{escape(name)}</td>'
            f'<td class="num" data-sort="{spend_mln:.2f}">{_fmt_mln(spend_mln)}</td>'
            f'<td class="num" data-sort="{float(c.get("contribution") or 0):.2f}">{_fmt_contrib(c.get("contribution"), contrib_scale)}</td>'
            f'<td class="num" data-sort="{float(mroas or 0):.3f}">{mroas_html}{fn_html}</td>'
            f'<td class="num" data-sort="{share_pct}">{share_pct}</td>'
            f'<td><span class="verdict-badge verdict-{escape(verdict)}">{escape(verdict)}</span></td>'
            f'</tr>'
        )

    # Totals
    if facts:
        tb = facts.get("total_budget_mln") or 0
        # raw total contrib для согласованного _fmt_contrib (total_contrib_mln = /1e6).
        tc_raw = (facts.get("total_contrib_mln") or 0) * 1_000_000.0
        wr = facts.get("weighted_roi")
        # v1.3.2: aggregate cell - adapt unit per KPI/mode.
        if not wr:
            wr_cell = "-"
        elif kpi["is_legacy"]:
            wr_cell = _fmt_x(wr)
        elif kpi["mode"] == "effectiveness":
            wr_cell = "100%"  # сумма долей = 100% по построению
        elif kpi["kpi_kind"] == "count":
            try:
                cpu = 1.0 / float(wr) if float(wr) > 0 else None
                cpu_unit = kpi.get("cpu_per_label") or "₽/ед."
                wr_cell = f"{cpu:.0f} {cpu_unit}" if cpu else "-"
            except (TypeError, ValueError, ZeroDivisionError):
                wr_cell = "-"
        else:
            wr_cell = _fmt_x(wr)
        totals_html = (
            f'<tr class="totals-row">'
            f'<td>{escape(headers["totals"])}</td>'
            f'<td class="num">{_fmt_mln(tb)}</td>'
            f'<td class="num">{_fmt_contrib(tc_raw, contrib_scale)}</td>'
            f'<td class="num">{wr_cell}</td>'
            f'<td class="num">100</td>'
            f'<td></td>'
            f'</tr>'
        )
    else:
        totals_html = ""

    # Footnotes
    # v1.3.2 audit fix (M1): KPI-aware verdict reason - для effectiveness mode
    # «breakeven» metaphor неестественна для shares. Используем «доля ниже
    # бенчмарка». Для count - переформулируем mROAS-specific terms через
    # vocabulary CPU/единиц.
    if kpi["is_legacy"]:
        verdict_reasons_view = v_reasons
    elif kpi["mode"] == "effectiveness":
        verdict_reasons_view = {
            "Cut": "низкая доля в портфеле; рекомендовано остановить или перевести в другие каналы.",
            "Reduce": "вклад канала в долю эффекта ниже среднего по портфелю.",
        }
    elif kpi["kpi_kind"] == "count":
        metric_short = kpi["metric_short"]
        verdict_reasons_view = {
            "Cut": f"{metric_short} превышает ценность единицы; рекомендовано остановить или перевести в другие каналы.",
            "Reduce": "достигнуто насыщение; стоимость следующей единицы выше среднего по портфелю.",
        }
    else:
        # Defensive: unknown mode → keep base reasons (manual / out-of-scope).
        verdict_reasons_view = v_reasons

    if flagged:
        fn_items = []
        for i, c in enumerate(flagged):
            num = str(i + 1)
            name = c.get("name") or "-"
            reason = verdict_reasons_view.get(c.get("verdict"), "")
            fn_items.append(
                f'<li><span class="fn-num">{num}</span>{escape(name)}: {escape(reason)}</li>'
            )
        fn_html = f"""
<div class="footnotes">
  <div class="footnotes-label">Примечания</div>
  <ol class="footnotes-list">{"".join(fn_items)}</ol>
</div>"""
    elif channels:
        ok_metric = "mROAS" if kpi["is_legacy"] else kpi["metric_short"]
        fn_html = (
            '<div class="footnotes">'
            '<div class="footnotes-label">Примечания</div>'
            f'<ol class="footnotes-list"><li><span class="fn-num">-</span>'
            f'Все каналы портфеля в рабочем диапазоне {ok_metric}; критических рекомендаций нет.'
            '</li></ol></div>'
        )
    else:
        fn_html = ""

    body = f"""
{_action_title(title)}
<div class="table-toolbar">
  <input type="search" class="search-inline" id="table-search" placeholder="Поиск канала..." aria-label="Поиск канала">
  <div>
    <button class="btn-inline" id="btn-copy-csv">Копировать в CSV</button>
  </div>
</div>
<table class="action-table" id="action-table">
  <caption>Портфель каналов · таблица с вердиктами</caption>
  <thead>
    <tr>
      <th scope="col" data-col="0" aria-sort="none">{escape(headers["channel"])}</th>
      <th scope="col" data-col="1" class="num" aria-sort="none">{escape(headers["budget"])} <span style="font-weight:400;color:var(--text-muted);">{escape(units["budget"])}</span></th>
      <th scope="col" data-col="2" class="num" aria-sort="descending">{escape(headers["contrib"])} <span style="font-weight:400;color:var(--text-muted);">{escape(contrib_unit)}</span></th>
      <th scope="col" data-col="3" class="num" aria-sort="none">{escape(metric_col_header)} <span style="font-weight:400;color:var(--text-muted);">{escape(metric_col_unit)}</span></th>
      <th scope="col" data-col="4" class="num" aria-sort="none">{escape(headers["share"])} <span style="font-weight:400;color:var(--text-muted);">{escape(units["share"])}</span></th>
      <th scope="col" data-col="5" aria-sort="none">{escape(headers["verdict"])}</th>
    </tr>
  </thead>
  <tbody>{"".join(rows_html)}{totals_html}</tbody>
</table>
{fn_html}"""
    return _section("table", kicker, body)


def render_timeline(ctx: dict) -> str:
    """Section 9: Timeline (обзор групп / детально) + dataZoom."""
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    # П2: «по <единица>» из гранулярности дат (детект в builder), fallback нейтр.
    period_unit = ctx.get("period_unit") or "по периодам"
    # Аудит №3 предложение 4: kicker динамический («ПРОДАЖИ ПО МЕСЯЦАМ») — точнее
    # нейтрального; TOC читает sections.label, kicker чисто визуальный. strings-
    # ключ остаётся резервом на случай пустого period_unit.
    kicker = (
        f"ПРОДАЖИ {period_unit.upper()}" if period_unit
        else strings["sections"]["timeline"]["kicker"]
    )

    leader = facts.get("leader_channel") if facts else None
    if leader:
        title = strings["action_titles"]["s08_leader"].format(leader=leader)
    else:
        title = f"Динамика продаж {period_unit}"

    # Б-3 (аудит Т3+): подпись отражает двухрежимность (обзор групп ⇄ детально),
    # дефолт — обзор 4 групп в паритете с программой, а не «вклад каналов».
    # (2026-07-25, Фаза 3 покрытия): было HTML-комментарием внутри клиентского
    # тела секции — внутренняя аудит-заметка утекала в экспортируемый файл.
    body = f"""
{_action_title(title)}
<div class="chart-container">
  <div class="chart-title-bar">
    <div>
      <div class="chart-title">Продажи {period_unit}</div>
      <div class="chart-subtitle">Декомпозиция по группам (обзор) или по каналам и факторам (детально). Ползунок - зум периода.</div>
    </div>
    <button class="btn-inline" id="tl-view-toggle" title="Показать каналы и факторы по отдельности. Итоговая сумма продаж одинакова в обоих режимах">Детально</button>
    <button class="btn-inline" data-copy-chart="chart-timeline">Сохранить PNG</button>
  </div>
  <div class="chart-host" id="chart-timeline" data-chart="timeline" style="height:420px;">
    <div class="chart-skeleton" aria-hidden="true"></div>
  </div>
</div>"""
    return _section("timeline", kicker, body)


def render_recommendation(ctx: dict) -> str:
    """Section 10: SCQAR recommendation - 3 data-driven actions + lift.

    N3+N4 (Phase 0.1 fix-session 2026-04-25):
      - Action 01 derives from optimizer.json (reallocation, binding, converged).
        If optimizer hit binding constraints or didn't converge → priority text
        explaining how to unblock instead of vacuous "перебалансировать 0 млн".
      - Actions 02/03 replaced from generic boilerplate (Burst-планирование,
        Targeted retargeting) to data-driven monitoring guidance. Generic
        "best practices" moved to render_best_practices() with disclaimer.
    """
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    channels = ctx.get("channels") or []
    kicker = strings["sections"]["recommend"]["kicker"]
    kpi = _kpi_view(ctx)

    if facts and channels:
        leader = facts.get("leader_channel") or "-"
        hero = facts.get("hero_channel") or leader
        if hero != leader:
            title = strings["action_titles"]["s09_scale_hero"].format(hero=hero, leader=leader)
        else:
            title = strings["action_titles"]["s09_hold_leader"].format(leader=leader)

        realloc = facts.get("reallocation_mln") or 0
        lift = facts.get("expected_lift_pct")
        underperf = [c.get("name") for c in channels if c.get("verdict") == "Cut"]
        binding = bool(facts.get("binding_constraints"))
        converged = facts.get("optimization_converged", True)
        converged_at_current = bool(facts.get("converged_at_current"))

        # N3 - Action 01: derived from optimizer state, not heuristics.
        # math-fix v1.0.14.1: + converged_at_current branch (false convergence).
        if not converged:
            action_01_text = (
                "Оптимизация не сошлась - попробуйте ослабить ограничения по каналам "
                "или сократить число каналов в модели и перезапустите Оптимизацию."
            )
        elif binding:
            min_pct = facts.get("optimize_min_pct")
            max_pct = facts.get("optimize_max_pct")
            bounds_txt = (
                f"(текущие границы Мин. {round(min_pct)}% / Макс. {round(max_pct)}%)"
                if min_pct is not None and max_pct is not None
                else "(текущие границы зажимают результат)"
            )
            action_01_text = (
                f"Все каналы упёрлись в заданные границы {bounds_txt}. "
                "Расширьте до 10-20% / 200-300% и перезапустите Оптимизацию - "
                "она найдёт реальное перераспределение."
            )
        elif converged_at_current:
            action_01_text = (
                "Оптимизатор не нашёл лучшего распределения - оставил текущую "
                "аллокацию. Расширьте границы Min/Max или используйте экспертный "
                "режим для разблокировки реального перераспределения."
            )
        elif facts.get("cut_source_channel") and facts.get("scale_destination_channel") and realloc >= 0.5:
            # L15 (math-fix v1.4 Section C): action-driven reallocation subjects
            # вместо leader/hero. cut_source = optimizer's biggest cut, scale_dest
            # = biggest grow recommendation. Avoids «из Performance в Social»
            # когда Performance - small-budget сhannel.
            action_01_text = (
                f"{realloc:.0f} млн ₽ из {facts['cut_source_channel']} в {facts['scale_destination_channel']}. "
                "Остаточный эффект компенсирует краткосрочный спад охвата."
            )
        elif hero != leader and realloc >= 0.5:
            # Legacy fallback (cut_source/scale_dest unavailable)
            action_01_text = (
                f"{realloc:.0f} млн ₽ из {leader} в {hero}. "
                "Остаточный эффект компенсирует краткосрочный спад охвата."
            )
        else:
            action_01_text = (
                f"Портфель близок к оптимуму при заданных границах. "
                f"Сохранить распределение по {leader} с контролем признаков насыщения."
            )

        # N4 - Actions 02/03: data-driven monitoring guidance (not generic boilerplate).
        # v1.3.2 audit fix (M1): mode-natural phrasing - «breakeven» metaphor
        # подходит для monetary/count, для effectiveness используем «низкая доля».
        n_saturated = sum(
            1 for c in channels
            if (c.get("mroas") or 0) > 0 and (c.get("mroas") or 0) < 1.0
        )
        metric_short = kpi["metric_short"]
        if n_saturated > 0:
            if kpi["is_legacy"]:
                problem_clause = f"{n_saturated} канал(ов) под breakeven (mROAS < 1×)"
            elif kpi["mode"] == "effectiveness":
                problem_clause = f"{n_saturated} канал(ов) с низкой долей в портфеле"
            elif kpi["kpi_kind"] == "count":
                problem_clause = f"{n_saturated} канал(ов) под breakeven ({_under_breakeven_phrase(kpi)})"
            else:
                problem_clause = f"{n_saturated} канал(ов) под breakeven"
            action_02_text = (
                f"{problem_clause} - проверить качество данных, параметры затухания и сравнить "
                "с отраслевыми ориентирами перед следующей итерацией."
            )
        else:
            if kpi["mode"] == "effectiveness":
                action_02_text = (
                    "Все каналы дают сравнимый вклад в долю эффекта - "
                    f"следить за {metric_short.lower()} канала в следующих периодах - не появится ли насыщение."
                )
            else:
                action_02_text = (
                    f"Все каналы выше breakeven - мониторить {metric_short} в следующих периодах "
                    "на признаки насыщения."
                )

        if underperf:
            # L12 (math-fix v1.4 Section C, 2026-04-29): full list, не top-2 slice.
            # Pre-fix: hardcoded [:2] hid 3-5 underperformers in commentary,
            # creating false impression of «small problem». Post-fix: all
            # action='Cut' channels listed → customer sees full picture.
            action_03_text = (
                f"Перевести бюджет из {', '.join(underperf)} согласно вердиктам, "
                "затем сверить эффект после следующего периода данных (KPI против базового спроса)."
            )
        else:
            action_03_text = (
                "Сверить эффект после следующего периода данных (KPI против базового спроса) – "
                "перезапустить MMM с обновлёнными данными для калибровки модели."
            )

        actions = [
            ("01", "Перебалансировать бюджет.", action_01_text),
            ("02", "Контролировать насыщение.", action_02_text),
            ("03", "Сверить прогноз с фактом.", action_03_text),
        ]
        lift_val = lift if lift is not None else 0
    else:
        title = "Рекомендация появится после оптимизации"
        actions = [
            ("01", "Перебалансировать бюджет.", "Из лидера в самый отзывчивый канал по mROAS"),
            ("02", "Контролировать насыщение.", "По каналам с mROAS < 1×"),
            ("03", "Сверить прогноз с фактом.", "KPI против базового спроса после применения"),
        ]
        lift_val = 0

    actions_html = "\n".join(
        f'<div class="recommendation">'
        f'<div class="recommendation-num">{escape(num)}</div>'
        f'<div><div class="recommendation-lead">{escape(lead)}</div>'
        f'<div class="recommendation-body">{escape(desc)}</div></div>'
        f'</div>'
        for num, lead, desc in actions
    )

    # v1.3.2: KPI-aware label для impact-card.
    if kpi["mode"] == "effectiveness":
        impact_period_label = "Прогнозный прирост доли"
    elif kpi["kpi_kind"] == "count":
        impact_period_label = "Прогнозный прирост продаж (упак / ед.)"
    else:
        impact_period_label = "Прогнозный ROAS"

    # B1-fix R-09/R-13 (2026-07-03): «+0 пп» — пустое обещание; незначимый
    # lift (<0.5) подписываем честно, без нулевого числа и без анимации.
    if lift_val >= 0.5:
        _impact_value_html = (
            f'<div class="impact-value" data-counter-end="{lift_val:.0f}">+{lift_val:.0f} пп</div>'
        )
        _impact_card_attr = ' data-animate-counter'
    else:
        _impact_value_html = (
            '<div class="impact-value" style="font-size:22px;">Незначим (&lt;0.5 пп)</div>'
        )
        _impact_card_attr = ''

    # Optimize comparison chart (current vs optimal spend per channel)
    # rendered only when optimize data is available - JS checks CHART_DATA
    # shape and silently no-ops if empty.
    body = f"""
{_action_title(title)}
<div class="recommendations">
{actions_html}
</div>
<div class="impact-card"{_impact_card_attr}>
  <div class="impact-label">Ожидаемый эффект</div>
  <div class="impact-hairline" aria-hidden="true"></div>
  {_impact_value_html}
  <div class="impact-period">{escape(impact_period_label)}</div>
</div>
<div class="chart-container" style="margin-top:28px;">
  <div class="chart-title-bar">
    <div>
      <div class="chart-title">Текущий vs оптимальный бюджет · млн ₽</div>
      <div class="chart-subtitle">Рекомендация оптимизатора по каналам</div>
    </div>
    <button class="btn-inline" data-copy-chart="chart-optimize">Сохранить PNG</button>
  </div>
  <div class="chart-host" id="chart-optimize" data-chart="optimize" style="height:320px;">
    <div class="chart-skeleton" aria-hidden="true"></div>
  </div>
</div>"""
    return _section("recommend", kicker, body)


def _render_brand_perf_split_block(ctx: dict) -> str:
    """Trust Level 3 (v1.1.0) - auto-generated methodology section про brand vs performance.

    Reads actual prior values из pickle config (issue K - methodology auto-syncs с code).
    Returns empty string если модель не использовала hierarchical priors.
    """
    diag = ctx.get("diagnostics") or {}
    hier = diag.get("hierarchical") or {}
    if not hier.get("enabled"):
        return ""
    cats = hier.get("channel_categories") or {}
    priors = hier.get("priors_summary") or {}
    if not cats:
        return ""
    n_brand = sum(1 for v in cats.values() if v == 'brand')
    n_perf = sum(1 for v in cats.values() if v == 'performance')
    n_mixed = sum(1 for v in cats.values() if v == 'mixed')

    import math
    def _half_life(mu_logit: float | None) -> str:
        if mu_logit is None:
            return "-"
        decay = 1 / (1 + math.exp(-mu_logit))
        if decay <= 0 or decay >= 1:
            return "-"
        hl = math.log(0.5) / math.log(decay)
        return f"{hl:.1f} периодов"

    brand_mu = priors.get('brand_mu_logit_mean')
    perf_mu = priors.get('performance_mu_logit_mean') or priors.get('perf_mu_logit_mean')
    rows = []
    if n_brand:
        rows.append(f'<li><strong>Brand:</strong> {n_brand} канал(ов), период полураспада ≈ {_half_life(brand_mu)} (долгосрочный отклик)</li>')
    if n_perf:
        rows.append(f'<li><strong>Performance:</strong> {n_perf} канал(ов), период полураспада ≈ {_half_life(perf_mu)} (краткосрочный отклик)</li>')
    if n_mixed:
        rows.append(f'<li><strong>Смешанные:</strong> {n_mixed} канал(ов), единый априорный параметр</li>')

    warning_html = ""
    rwarn = hier.get('rhat_warning')
    if rwarn:
        warning_html = f'<p style="color:var(--warning,#d97706);font-size:11px;margin-top:8px;">⚠ {escape(rwarn)}</p>'

    return f"""
<div class="brand-perf-block" style="margin-top:24px;padding:14px;background:rgba(127,90,240,0.05);border-left:3px solid rgba(127,90,240,0.5);border-radius:6px;">
  <div class="method-col-label" style="margin-bottom:8px;">Иерархическая модель brand/performance (v1.1.0)</div>
  <p style="font-size:12px;line-height:1.5;color:var(--text-secondary,#94a3b8);">
    Модель разделяет каналы на brand (долгосрочный отклик) и performance (краткосрочный отклик).
    Brand-каналы получают более широкий априорный параметр – отражает неизвестную длительность накопления эффекта.
    Performance-каналы используют тесный априорный параметр на быстрое затухание.
  </p>
  <ul style="font-size:12px;line-height:1.7;margin-top:8px;padding-left:16px;">
{chr(10).join(rows)}
  </ul>
  <p style="font-size:11px;font-style:italic;color:var(--text-muted,#64748b);margin-top:8px;">
    Атрибуция между brand и performance содержит неустранимую неопределённость – используются априорные ожидания на основе отраслевых норм.
    Если категория канала вызывает сомнения, проверьте классификацию на шаге «Валидация».
  </p>
  {warning_html}
</div>"""


_СТАТУС_ЗАВЕРЕНИЯ = {
    # 🔴 Аудит F-02: у режима малых данных паспорта прогона не бывает — там
    # закрытая формула без случайного сэмплера, поэтому текст свой.
    # Оговорка «в той же среде» не педантизм: паспорт не зря пишет версии
    # библиотек, а прежняя формулировка обещала совпадение безусловно.
    'issued': 'Расчёт заверен: параметры прогона записаны, повторный запуск на тех же '
              'данных в той же среде даёт те же числа.',
    'issued_deterministic': 'Расчёт заверен: он выполнен по закрытой формуле, случайного '
                            'подбора в нём нет, поэтому повтор на тех же данных даёт те '
                            'же числа.',
    'not_attested': 'Заверение неполное: модель обучена в ранней версии программы, где '
                    'параметры прогона не записывались. Переобучите модель, чтобы '
                    'получить полное заверение.',
}

_ПРОВЕРКА_БАЗЫ = {
    # 🔴 Аудит F-05: сказано ровно то, что проверено. Вердикт «годно» означает
    # вероятность отрицательной базы ниже 20 % и считается по СРЕДНЕЙ по периодам
    # базе — прежний текст обещал положительность в каждом периоде и отсутствие
    # завышения, чего проверка не устанавливала (по-периодная доля в диагностике
    # есть, но порогами не гейтится).
    'passed': 'Средний базовый уровень уверенно положителен: вероятность того, что он '
              'отрицателен, ниже 20 %.',
    # 🔴 Аудит починки, Ф-02: все три вердикта присваиваются по ОДНОЙ величине —
    # вероятности того, что средний по периодам базовый уровень отрицателен.
    # Из «пройдено» по-периодные утверждения убрали, а в соседних они остались
    # слово в слово, включая ту самую фразу «вклад каналов завышен».
    'watch': 'Средний базовый уровень близок к нулю: вероятность того, что он '
             'отрицателен, от 20 до 80 %. Стоит перепроверить полноту факторов.',
    'failed': 'Средний базовый уровень отрицателен с вероятностью выше 80 %. Такую '
              'модель нужно пересмотреть: часть вклада каналов может быть мнимой.',
    # 🔴 Аудит F-06: метрика не называется продажами — признак считается по любому
    # KPI, и у модели знания марки клиент читал бы про продажи, которых в проекте
    # нет. Имя метрики не подставляется: формулировка обобщена, подписи
    # `utils/kpi_labels` тянуть в блок не понадобилось.
    'not_applicable': 'Проверка неприменима на этих данных: разброс значений целевой '
                      'метрики слишком мал, чтобы отличить положительный базовый '
                      'уровень от отрицательного.',
}

_ИСТОЧНИК_ЗЕРНА = {
    'config': 'задано в проекте',
    'env': 'задано переменной среды',
    'default': 'значение по умолчанию',
    'model': 'взято из модели',
}


def _render_certificate_block(ctx: dict) -> str:
    """Блок «Воспроизводимость и сертификат» (P0.7 шаг 15).

    Рендерится только когда сертификат реально посчитан: расчёты старых версий
    его не несут, и печатать вместо него прочерки значило бы обещать заверение,
    которого нет.

    🔴 Формулировка «проверка неприменима» не смягчается до «пройдена» — это
    долг блока P0.6: проверка отрицательной базы на данных с малым разбросом
    продаж не может провалиться в принципе, и «пройдена» там означало бы не
    «модель здорова», а «мы ничего не проверили».
    """
    cert = ctx.get("certificate")
    if not isinstance(cert, dict) or not cert:
        return ""

    статус = cert.get("status")
    строки: list[tuple[str, str]] = []

    отпечаток = cert.get("hash")
    if отпечаток:
        строки.append(("Отпечаток расчёта", str(отпечаток)))

    паспорт = cert.get("reproducibility") or {}
    if паспорт.get("status") == "recorded":
        зерно = паспорт.get("seed")
        источник = _ИСТОЧНИК_ЗЕРНА.get(str(паспорт.get("seed_source")), "")
        if зерно is not None:
            строки.append((
                "Зерно генератора",
                f"{зерно} ({источник})" if источник else str(зерно),
            ))
        mcmc = паспорт.get("mcmc") or {}
        if mcmc.get("chains") and mcmc.get("draws"):
            # Разогрев дописывается, только если он известен: заглушка вместо
            # величины запрещена (сторож `test_em_dash_placeholder_gate`).
            значение = f"{mcmc['chains']} × {mcmc['draws']}"
            if mcmc.get("tune"):
                значение += f", разогрев {mcmc['tune']}"
            строки.append(("Цепи и шаги", значение))

    проверка = (cert.get("checks") or {}).get("negative_baseline")
    if проверка in _ПРОВЕРКА_БАЗЫ:
        строки.append(("Базовый уровень", _ПРОВЕРКА_БАЗЫ[проверка]))

    ключ_статуса = str(статус)
    if статус == "issued" and паспорт.get("status") == "deterministic":
        ключ_статуса = "issued_deterministic"
    пояснение = _СТАТУС_ЗАВЕРЕНИЯ.get(ключ_статуса)
    if статус == "unavailable":
        пояснение = f"Заверение недоступно: {cert.get('reason') or 'причина не названа'}"
    if not пояснение and not строки:
        return ""

    # 🔴 Аудит починки, Ф-06: список и подвал печатались всегда — и там, где
    # отпечатка не выдали вовсе: клиент читал «Отпечаток покрывает файл модели»
    # ровно на отказе, да ещё рядом с пустым списком.
    # 🔴 Ф-09: подвал теперь говорит прямо, что отпечаток принадлежит конкретному
    # файлу модели — при повторном обучении числа те же, а отпечаток другой
    # (в манифест файла входит время его создания).
    список = ''
    подвал = ''
    if строки:
        пункты = "\n".join(
            f'<li><span class="diag-label">{escape(метка)}</span>'
            f'<span class="diag-value">{escape(значение)}</span></li>'
            for метка, значение in строки
        )
        список = f'<ul class="diag-list">\n{пункты}\n  </ul>'
    if отпечаток:
        подвал = (
            '<p style="margin-top:12px;font-size:11px;font-style:italic;'
            'color:var(--text-muted);">Отпечаток покрывает файл обученной модели и '
            'результаты разбивки. Исходная выгрузка данных в него не входит. Базовый '
            'уровень взят до выноса отдельных факторов, поэтому может отличаться от '
            'полосы «Базовый уровень» на графике разбивки. При повторном обучении на '
            'тех же данных числа сохранятся, а отпечаток станет другим: он '
            'принадлежит конкретному файлу модели.</p>'
        )
    return f"""
<div style="margin-top:32px;">
  <div class="method-col-label">Воспроизводимость и сертификат</div>
  <p style="margin:8px 0 12px;font-size:12px;">{escape(пояснение or '')}</p>
  {список}
  {подвал}
</div>"""


def render_methodology(ctx: dict) -> str:
    """Section 11: Methodology + limitations. v2.1.0 Pilot C: engine-aware."""
    strings = ctx["strings"]
    diag = ctx.get("diagnostics") or {}
    kicker = strings["sections"]["method"]["kicker"]
    meth = strings["methodology"]

    # v2.1.0 (Pilot C): engine detection - 'ols' для small-data fallback.
    is_ols = (diag.get("engine") == "ols") or (ctx.get("model_version") == "1.0-ols")

    # Engine-aware formulas: OLS использует closed-form + bootstrap;
    # Bayesian - posterior priors. JSON fallback к base formulas если ключ отсутствует.
    if is_ols and "spec_formulas_ols" in meth:
        formulas_text = "\n".join(meth["spec_formulas_ols"])
    else:
        formulas_text = "\n".join(meth["spec_formulas"])
    diag_items = []
    if diag.get("r_squared") is not None:
        diag_items.append(("R²", f"{float(diag['r_squared']):.3f}"))
    if diag.get("mape_pct") is not None:
        diag_items.append(("MAPE", f"{float(diag['mape_pct']):.1f}%"))
    # OLS guard: hide MCMC diagnostics; show method/CI labels вместо.
    if is_ols:
        diag_items.append(("Метод", "closed-form OLS"))
        diag_items.append(("Диапазон", "bootstrap n=200"))  # факт ols_bootstrap.py n_boot=200 (был n=1000, враньё R-07)
    else:
        if diag.get("r_hat_max") is not None:
            diag_items.append(("R-hat (max)", f"{float(diag['r_hat_max']):.3f}"))
        if diag.get("ess_min") is not None:
            diag_items.append(("ESS (min)", _fmt_int(diag['ess_min'])))
    diag_html = "\n".join(
        f'<li><span class="diag-label">{escape(lbl)}</span><span class="diag-value">{escape(val)}</span></li>'
        for lbl, val in diag_items
    )

    limits_html = "\n".join(
        f'<details><summary>{escape(lim["lead"])}</summary><p>{escape(lim["body"])}</p></details>'
        for lim in meth["limits"]
    )

    # Trust Level 3 (v1.1.0): auto-generated brand vs performance block.
    brand_perf_html = _render_brand_perf_split_block(ctx)

    # v2.1.0 Pilot C: engine-aware action title + prior note text.
    _ats = strings["action_titles"]
    _action_text = (
        _ats.get("s10_methodology_ols", _ats["s10_methodology"])
        if is_ols
        else _ats["s10_methodology"]
    )
    _prior_note = (
        "Параметры отложенного эффекта (adstock) и насыщения: индустриальные бенчмарки OLS MMM, фиксированные. Bootstrap n=200 для диапазона."  # П8-2
        if is_ols
        else meth["prior_note"]
    )

    body = f"""
{_action_title(_action_text)}
<div class="methodology-grid">
  <div>
    <div class="method-col-label">{escape(meth["spec_header"])}</div>
    <pre class="formula-box">{escape(formulas_text)}</pre>
    <div class="method-col-label" style="margin-top:24px;">{escape(meth["diag_header"])}</div>
    <ul class="diag-list">
{diag_html if diag_html else '<li><span class="diag-label">-</span><span class="diag-value">Данные появятся после обучения</span></li>'}
    </ul>
  </div>
  <div>
    <div class="method-col-label">{escape(meth["limits_header"])}</div>
    <div class="limits-list">
{limits_html}
    </div>
  </div>
</div>
<p style="margin-top:24px;font-size:11px;font-style:italic;color:var(--text-muted);">{escape(_prior_note)}</p>
{_render_certificate_block(ctx)}
{brand_perf_html}"""
    return _section("method", kicker, body)


def render_sources(ctx: dict) -> str:
    """Section 12: Sources + MQS card with verify badge. v2.1.0 Pilot C: engine-aware."""
    strings = ctx["strings"]
    diag = ctx.get("diagnostics") or {}
    kicker = strings["sections"]["sources"]["kicker"]

    # v2.1.0 (Pilot C): engine detection.
    is_ols = (diag.get("engine") == "ols") or (ctx.get("model_version") == "1.0-ols")

    mqs = diag.get("mqs_score")
    # 🔴 Внешний аудит 2026-07-26: та же проверка, что в findings выше, — карточка
    # секции её не имела. Адаптер при отсутствии `tier_label` подставляет значение
    # ключа `tier` («excellent»), и клиенту печаталась латиница, тогда как findings
    # той же страницы говорили «Отличное». Ярлык принимается только из набора
    # канона; иначе уровень выводится из посчитанного балла, а при его отсутствии
    # ярлыка нет вовсе (карточка ниже рисует честное отсутствие).
    # Audit fix (2026-07-27): принадлежности набору тоже мало — ярлык обязан ещё
    # и СООТВЕТСТВОВАТЬ баллу (SSOT-проверка вынесена в resolve_mqs_tier_label,
    # используется здесь и в findings выше — не дублируется). Заодно: раньше
    # проверка членства шла ДО проверки самого балла, поэтому валидный ярлык
    # канона без валидного балла тоже проходил как есть — честного отсутствия
    # не получалось, хотя комментарий выше его обещал. Балл парсится первым.
    from utils.diagnostics import resolve_mqs_tier_label
    _diag_tier = diag.get("mqs_tier_label")
    try:
        _mqs_num = float(mqs) if mqs is not None else None
    except (TypeError, ValueError):
        _mqs_num = None
    if _mqs_num is not None and math.isfinite(_mqs_num):
        mqs_tier = resolve_mqs_tier_label(_mqs_num, _diag_tier)
    else:
        mqs_tier = ""
    try:
        mqs_display = f"{int(round(float(mqs)))}" if mqs is not None else None
    except (TypeError, ValueError):
        mqs_display = None

    # INV-50 F-DELIVERABLE-1 (2026-06-07): честная оговорка о тонких данных /
    # переобучении — та же формулировка, что в вердикте программы и письме
    # (utils.diagnostics.format_thinness_caveat — SSOT). Прежде роняла на
    # report-шве: клиентский HTML показывал «MQS 70 Хорошее» без предупреждения.
    from utils.diagnostics import format_thinness_caveat
    mqs_caveat = format_thinness_caveat(diag.get("ratio"), diag.get("thinness_cap"),
                                        leading_space=False)

    mqs_diag_html = ""
    if is_ols:
        # OLS: показываем только R²/MAPE + frequentist метод (без MCMC).
        _diag_rows = [
            ("R²", "r_squared", lambda v: f"{float(v):.3f}"),
            ("MAPE", "mape_pct", lambda v: f"{float(v):.1f}%"),
        ]
    else:
        _diag_rows = [
            ("R²", "r_squared", lambda v: f"{float(v):.3f}"),
            ("MAPE", "mape_pct", lambda v: f"{float(v):.1f}%"),
            ("R-hat", "r_hat_max", lambda v: f"{float(v):.3f}"),
            ("ESS", "ess_min", lambda v: _fmt_int(v)),
        ]
    for lbl, key, fmt in _diag_rows:
        if diag.get(key) is not None:
            mqs_diag_html += f'<div><span class="mqs-diag-label">{lbl}</span><span>{fmt(diag[key])}</span></div>'

    # Engine-aware methodology badge text + sources footer line.
    _brand = strings["brand"]
    _badge_text = (
        _brand.get("methodology_badge_ols", _brand["methodology_badge"])
        if is_ols
        else _brand["methodology_badge"]
    )
    # B1-fix R-07 (2026-07-03): фактический уровень интервалов — 90% HDI
    # (DEFAULT_HDI_PROB=0.9, OLS bootstrap тем же compute_ci_hdi, n=200);
    # «95%» было враньём семейства F-18.
    _src_line = (
        "OLS MMM · точечные оценки · bootstrap 90% HDI (n=200)"
        if is_ols
        else "Bayesian MMM · posterior means · 90% HDI"
    )

    # Нет числа - нет подписи (2026-07-26): пустая шкала «- /100» с ярлыком
    # уровня ниже - та же ложь, что фиктивный ноль (форма измерения без
    # измерения). Формулировка отсутствия дословно та же, что в PPTX-карточке
    # (aurora_pptx/builder.py) - разнобой по поверхностям это тот же дефект
    # в профиль. При отсутствии оценки шкала и ярлык уровня не рисуются вовсе.
    if mqs_display is not None:
        mqs_score_block = (
            f'<div class="mqs-score">{escape(mqs_display)}<sub>/100</sub></div>\n'
            f'    <div class="mqs-tier">{escape(mqs_tier)}</div>'
        )
    else:
        mqs_score_block = (
            '<div class="mqs-absent">Оценка не выполнялась для этого расчёта</div>'
        )

    body = f"""
{_action_title("Качество модели и источники данных")}
<div class="sources-grid">
  <div class="mqs-card">
    <div class="mqs-label">Model Quality Score</div>
    {mqs_score_block}
    {f'<div class="mqs-caveat">{escape(mqs_caveat)}</div>' if mqs_caveat else ''}
    {f'<div class="mqs-diag">{mqs_diag_html}</div>' if mqs_diag_html else ''}
    <a class="method-badge" href="#method">{escape(_badge_text)}</a>
  </div>
  <div>
    <div class="method-col-label">Источники данных</div>
    <ul class="sources-list">
      <li>Продажи: первичные данные клиента</li>
      <li>Медиа-инвестиции: биллинг по каналам</li>
      <li>Нормирование: CPP / CPM per unit</li>
      <li>Сезонность и макро: константы в базовом уровне продаж</li>
      <li>{escape(_src_line)}</li>
    </ul>
  </div>
</div>"""
    return _section("sources", kicker, body)


def render_glossary(ctx: dict) -> str:
    """Section 13: Glossary 24 terms accordion."""
    strings = ctx["strings"]
    kicker = strings["sections"]["glossary"]["kicker"]
    glossary = strings["glossary"]

    groups_html = []
    for group in glossary["categories"]:
        terms_html = "\n".join(
            f'<div class="glossary-term">'
            f'<div class="glossary-term-name">{escape(t["term"])}</div>'
            f'<div class="glossary-term-def">{escape(t["definition"])}</div>'
            f'</div>'
            for t in group["terms"]
        )
        groups_html.append(
            f'<details class="glossary-group" open>'
            f'<summary>{escape(group["label"])}</summary>'
            f'<div class="glossary-terms">{terms_html}</div>'
            f'</details>'
        )

    body = f"""
{_action_title(strings["action_titles"]["s13_glossary"])}
<div>
{"".join(groups_html)}
</div>"""
    return _section("glossary", kicker, body)


def render_closing(ctx: dict) -> str:
    """Section 14: Inspirational closing + CTA + Report ID."""
    strings = ctx["strings"]
    closing = strings["closing"]
    report_id = ctx.get("report_id") or ""

    body = f"""
<div class="closing">
  <div class="closing-statement">
    {escape(closing["statement"])}
    <span class="closing-emphasis">{escape(closing["emphasis"])}</span>
  </div>
  <p class="closing-cta">{escape(closing["cta"])}</p>
  <p class="closing-narrative">{escape(closing["narrative"])}</p>
  <p style="margin-top:32px;font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">
    Report ID: <code class="report-id" style="font-size:11px;">{escape(report_id)}</code>
  </p>
</div>"""
    return _section("closing", "", body, "section-closing")


# ─── Section registry ───────────────────────────────────────────────────────

def render_trust_loop(ctx: dict) -> str:
    """Секция «Петля доверия» (E1–E4, 2026-07-04): проверка на истории,
    что изменилось с прошлого квартала, калибровка экспериментами,
    сбывшиеся рекомендации. Рендерятся ТОЛЬКО живые под-блоки; при полном
    отсутствии данных секция не выводится вовсе (и пропускается в TOC) —
    wireframe-суррогатов нет по построению (урок B1)."""
    trust = ctx.get("trust") or {}
    diag = ctx.get("diagnostics") or {}
    bt = trust.get("backtest") or {}
    gc = trust.get("generation_compare") or {}
    ps = trust.get("promises_summary") or {}
    calib = diag.get("calibration") or {}
    blocks: list[str] = []

    # ── E1: проверка на истории ──
    if bt.get("status") == "ok" and bt.get("windows"):
        hit = bt.get("windows_hit_total")
        n_int = bt.get("windows_with_interval") or 0
        gran, h = bt.get("granularity"), bt.get("horizon_periods")
        is_q = (gran == "M" and h == 3) or (gran == "W" and h == 13) or (gran == "D" and h == 90)
        word = "кварталов" if is_q else "окон проверки"
        rows = ""
        for w in (bt.get("windows") or [])[:8]:
            lo, hi = w.get("pi_low_total"), w.get("pi_high_total")
            interval = (f"{_fmt_int(lo)} – {_fmt_int(hi)}"
                        if lo is not None and hi is not None else "н/д")
            mark = "✓" if w.get("hit_total") else ("–" if w.get("hit_total") is None else "✕")
            rows += (
                f'<tr><td>{escape(str(w.get("window") or "н/д"))}</td>'
                f'<td class="num">{_fmt_int(w.get("actual_total"))}</td>'
                f'<td class="num">{_fmt_int(w.get("predicted_total"))}</td>'
                f'<td class="num">{interval}</td><td class="center">{mark}</td></tr>'
            )
        naive = bt.get("mape_naive_best")
        naive_line = (
            f' Наивный прогноз: {float(naive):.1f}%.' if naive is not None else ""
        )
        blocks.append(f"""
<div class="trust-block">
  <h3 class="trust-h">Проверка на истории</h3>
  <p class="trust-hero">{escape(str(hit))} из {escape(str(n_int))} {word} – факт внутри 90%-интервала прогноза.</p>
  <p class="trust-sub">Ошибка прогноза (MAPE): {float(bt.get("mape_model") or 0):.1f}%.{naive_line}
  {escape(str(bt.get("verdict_text") or ""))}</p>
  <table class="trust-table"><thead><tr>
    <th>Период</th><th>Факт</th><th>Прогноз</th><th>90%-интервал</th><th>✓</th>
  </tr></thead><tbody>{rows}</tbody></table>
</div>""")

    # ── E3: что изменилось с прошлого квартала ──
    if gc.get("status") == "ok" and gc.get("channels"):
        headline = (gc.get("summary") or {}).get("headline") or ""
        rows = ""
        for c in (gc.get("channels") or [])[:8]:
            def _ci(v):
                if not v or v[0] is None or v[1] is None:
                    return ""
                return f" [{float(v[0]):.1f}–{float(v[1]):.1f}]"
            rows += (
                f'<tr><td>{escape(str(c.get("name")))}</td>'
                f'<td class="num">{float(c.get("roi_old") or 0):.1f}{_ci(c.get("roi_ci_old"))} → '
                f'{float(c.get("roi_new") or 0):.1f}{_ci(c.get("roi_ci_new"))}</td>'
                f'<td>{escape(str(c.get("verdict_ru") or ""))}</td></tr>'
            )
        blocks.append(f"""
<div class="trust-block">
  <h3 class="trust-h">Что изменилось с прошлого квартала</h3>
  <p class="trust-sub">{escape(headline)}</p>
  <table class="trust-table"><thead><tr>
    <th>Канал</th><th>ROI: был → стал</th><th>Вердикт</th>
  </tr></thead><tbody>{rows}</tbody></table>
  <p class="trust-note">Обе версии модели пересчитаны на сегодняшних данных;
  вердикт – по перекрытию интервалов неопределённости.</p>
</div>""")

    # ── E2: калибровка экспериментами ──
    applied = calib.get("applied") or []
    checks = calib.get("checks") or []
    if applied:
        lines = ""
        for a in applied:
            lines += (
                f'<p class="trust-sub">Канал «{escape(str(a.get("channel")))}» '
                f'откалиброван тестом ({escape(str(a.get("test_type")))}) '
                f'от {escape(str(a.get("date_from")))} – вошёл в модель как наблюдение.</p>'
            )
        for c in checks:
            if c.get("within_ci"):
                continue
            ci = c.get("model_contrib_ci90") or [None, None]
            lines += (
                f'<p class="trust-warn">Модель и тест расходятся по '
                f'«{escape(str(c.get("channel")))}»: вклад модели '
                f'{_fmt_int(c.get("model_contrib_mean"))} '
                f'[{_fmt_int(ci[0])} – {_fmt_int(ci[1])}] против теста '
                f'{_fmt_int(c.get("test_lift"))} – разберите период с аналитиком.</p>'
            )
        blocks.append(f"""
<div class="trust-block">
  <h3 class="trust-h">Калибровка экспериментами</h3>
  {lines}
</div>""")

    # ── E4: сбывшиеся рекомендации ──
    if ps.get("examples"):
        ex_lines = ""
        for ex in ps["examples"]:
            cls = "trust-sub" if ex.get("status") == "kept" else "trust-warn"
            ex_lines += (
                f'<p class="{cls}">«{escape(str(ex.get("action_text")))}» – '
                f'{escape(str(ex.get("status_ru")))}.</p>'
            )
        blocks.append(f"""
<div class="trust-block">
  <h3 class="trust-h">Проверка прошлых рекомендаций</h3>
  <p class="trust-hero">Сбылось {int(ps.get("kept") or 0)} · не сбылось {int(ps.get("missed") or 0)}</p>
  {ex_lines}
</div>""")

    if not blocks:
        return ""
    body = _action_title("Петля доверия: модель против факта") + "\n" + "\n".join(blocks)
    return _section("trust", "ДОВЕРИЕ К МОДЕЛИ", body)


def render_forecast_plan(ctx: dict) -> str:
    """E5 (2026-07-10): секция «Прогноз на будущий период».

    Рендерит сравнительную таблицу сценариев бюджетного плана. Возвращает ""
    если forecast отсутствует — INV-50, wireframe-суррогатов нет.
    При ≥2 вариантах добавляет сравнительный bar-chart scenarios_comparison_chart.
    """
    fc = ctx.get("forecast") or {}
    if not fc or fc.get("status") != "ok" or not fc.get("scenarios"):
        return ""

    scenarios = (fc.get("scenarios") or [])[:4]
    accepted = fc.get("accepted_variant")

    rows = ""
    for sc in scenarios:
        is_accepted = sc.get("variant_id") == accepted
        # Интервал СУММЫ за горизонт (totals.predicted_kpi_ci_*) — SSOT с
        # колонкой «Прогноз KPI» и GUI-карточкой. P-2 fix 2026-07-16: прежний
        # код брал CI последнего периода — масштаб не совпадал с суммой.
        ci_low_val = sc.get("total_kpi_ci_low")
        ci_high_val = sc.get("total_kpi_ci_high")
        ci_str = (
            f"{int(ci_low_val):,} – {int(ci_high_val):,}".replace(",", " ")
            if ci_low_val is not None and ci_high_val is not None else "н/д"
        )
        budget = sc.get("total_spend_money")
        kpi = sc.get("total_kpi")
        roas = sc.get("roas_money")
        budget_str = f"{int(budget):,}".replace(",", " ") if budget is not None else "н/д"
        kpi_str = f"{int(kpi):,}".replace(",", " ") if kpi is not None else "н/д"
        roas_str = f"{float(roas):.2f}" if roas is not None else "н/д"
        name_str = escape(str(sc.get("name") or sc.get("variant_id") or "н/д"))
        star = "★ " if is_accepted else ""
        bold_open = "<strong>" if is_accepted else ""
        bold_close = "</strong>" if is_accepted else ""
        rows += (
            f'<tr>'
            f'<td>{bold_open}{star}{name_str}{bold_close}</td>'
            f'<td class="num">{bold_open}{budget_str}{bold_close}</td>'
            f'<td class="num">{bold_open}{kpi_str}{bold_close}</td>'
            f'<td class="num">{bold_open}{ci_str}{bold_close}</td>'
            f'<td class="num">{bold_open}{roas_str}{bold_close}</td>'
            f'</tr>'
        )

    disclaimers = fc.get("disclaimers") or []
    disc_html = ""
    if disclaimers:
        disc_items = "".join(f"<li>{escape(str(d))}</li>" for d in disclaimers[:5])
        disc_html = f'<ul class="trust-list">{disc_items}</ul>'

    # Сравнительный график вариантов (только при ≥2 сценариях)
    chart_html = ""
    if len(scenarios) >= 2:
        try:
            from charts.generators import scenarios_comparison_chart
            kpi_meta = _kpi_view(ctx)
            kpi_label = kpi_meta.get("target_axis") or "Прогноз KPI"
            data_uri = scenarios_comparison_chart(scenarios, kpi_label=kpi_label)
            if data_uri:
                chart_html = (
                    '<div class="chart-container" style="margin-top:20px;">'
                    '<div class="chart-title" style="margin-bottom:8px;">'
                    'Сравнение вариантов – прогноз KPI</div>'
                    f'<img src="data:image/png;base64,{data_uri}" '
                    'alt="Сравнение вариантов" '
                    'style="max-width:100%;height:auto;border-radius:6px;" />'
                    '</div>'
                )
        except Exception:
            pass  # График опционален – ошибка не ломает секцию

    body = (
        _action_title("Прогноз на будущий период")
        + f"""
<div class="trust-block">
  <table class="trust-table">
    <thead><tr>
      <th>Сценарий</th><th>Бюджет, ₽</th>
      <th>Прогноз KPI</th><th>90%-интервал</th><th>ROAS</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {disc_html}
</div>
{chart_html}"""
    )
    return _section("forecast", "ПРОГНОЗ", body)


def render_retro_insights(ctx: dict) -> str:
    """Условный блок «Что улучшить в подходе» (ретро-раздел).

    Формирует список практических рекомендаций по улучшению качества модели
    на основе honesty_verdict, honesty_reasons и диагностических показателей.
    Возвращает пустую строку при сильной модели (honesty_verdict == "reliable")
    или при полном отсутствии данных — INV-50, wireframe-суррогатов нет.
    """
    diag = ctx.get("diagnostics") or {}
    verdict = diag.get("honesty_verdict")
    # При reliable-модели блок не нужен
    if verdict == "reliable":
        return ""
    # При полном отсутствии диагностики — тоже
    if not diag:
        return ""

    reasons = (diag.get("honesty_reasons") or [])[:3]
    thinness_cap = diag.get("thinness_cap")
    ratio = diag.get("ratio")
    preflight = diag.get("preflight") or {}
    r_squared = diag.get("r_squared")
    mape_pct = diag.get("mape_pct")

    items: list[str] = []

    # 1. Причины из honesty_reasons (уже человекочитаемые от движка)
    for reason in reasons:
        if reason:
            items.append(escape(str(reason)))

    # 2. Тонкость данных — рекомендация добавить историю
    if thinness_cap is not None and ratio is not None:
        try:
            r = float(ratio)
            if r < 3.0:
                items.append(
                    f"Мало наблюдений относительно числа параметров (отношение {r:.1f}) – "
                    "добавьте как минимум ещё один период данных для снижения неопределённости."
                )
        except (TypeError, ValueError):
            pass

    # 3. Preflight-провал приоров
    pp_status = preflight.get("prior_predictive_status")
    if pp_status == "fail":
        pp_cov = preflight.get("prior_predictive_coverage")
        cov_sfx = (f" (покрытие {float(pp_cov):.0%})" if isinstance(pp_cov, (int, float)) else "")
        items.append(
            f"Априорные предположения расходятся с данными{cov_sfx} – "
            "проверьте диапазоны отложенного эффекта (adstock) и насыщения на шаге «Валидация»."
        )

    # 4. Низкое R² или высокий MAPE
    if r_squared is not None:
        try:
            if float(r_squared) < 0.6:
                items.append(
                    f"R² = {float(r_squared):.2f} – модель объясняет менее 60% вариации продаж; "
                    "рассмотрите добавление сезонных регрессоров или макропеременных."
                )
        except (TypeError, ValueError):
            pass
    if mape_pct is not None:
        try:
            if float(mape_pct) > 20.0:
                items.append(
                    f"MAPE = {float(mape_pct):.1f}% – ошибка прогноза высокая; "
                    "проверьте выбросы и качество входных данных."
                )
        except (TypeError, ValueError):
            pass

    if not items:
        return ""

    items_html = "".join(f"<li>{item}</li>" for item in items)
    body = (
        _action_title("Что улучшить в подходе", lime=False)
        + '\n<div class="retro-block" style="margin-top:16px;padding:16px 20px;'
        'background:rgba(201,164,73,0.06);border:1px solid rgba(201,164,73,0.25);'
        'border-radius:8px;">\n'
        '  <ul class="retro-list" style="margin:0;padding-left:20px;line-height:1.7;'
        'font-size:13px;color:var(--text-secondary,#94a3b8);">\n'
        + items_html
        + '\n  </ul>\n</div>'
    )
    return _section("retro", "РЕКОМЕНДАЦИИ ПО ДАННЫМ", body)


SECTION_RENDERERS: tuple = (
    ('cover',     render_cover),
    ('findings',  render_at_a_glance),
    ('key',       render_key_message),
    ('recommend', render_recommendation),
    ('summary',   render_executive_summary),
    ('divider',   render_section_divider),
    ('mroas',     render_mroas),
    ('share',     render_share),
    ('table',     render_action_table),
    ('timeline',  render_timeline),
    ('trust',     render_trust_loop),
    ('forecast',  render_forecast_plan),
    ('retro',     render_retro_insights),
    ('method',    render_methodology),
    ('sources',   render_sources),
    ('glossary',  render_glossary),
    ('closing',   render_closing),
)
