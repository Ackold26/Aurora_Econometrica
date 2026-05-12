"""
aurora_html.sections - 14 section renderers.

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


def _fmt_x(v: Any, fallback: str = "-") -> str:
    try:
        return f"{float(v):.2f}×"
    except (TypeError, ValueError):
        return fallback


def _fmt_x_bare(v: Any, fallback: str = "-") -> str:
    """Same as _fmt_x but без × — для CI bracket inner numbers."""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return fallback


def _ci_tier_class(mean: Any, ci_low: Any, ci_high: Any) -> str:
    """Phase 1.9: returns CSS class for CI width tier — green/amber/red badge.

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
    """Format value with optional 90% CI bracket: '2.4× [1.8 — 3.1]'.

    Returns plain '_fmt_x' when CI unavailable (Phase 1.9 backward compat).
    Bracket span has CSS class ci-bracket plus tier class for color tinting.
    """
    base = _fmt_x(mean)
    if ci_low is None or ci_high is None:
        return base
    tier = _ci_tier_class(mean, ci_low, ci_high)
    return (
        f'{base} <span class="ci-bracket {tier}">'
        f'[{_fmt_x_bare(ci_low)} — {_fmt_x_bare(ci_high)}]</span>'
    )


def _fmt_pct(v: Any, fallback: str = "-") -> str:
    """N1 (Phase 0.1 fix-session 2026-04-25): conditional precision — never lies via rounding to 0%.

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
# (legacy callers, v1.2 contexts) — fallback к monetary ROI поведению.

_DEFAULT_KPI_LABELS = {
    "metric_label": "ROI",
    "metric_short_label": "ROI",
    "target_unit_label": "₽",
    "target_axis_label": "Продажи, ₽",
    "methodology_label": "",
}


def _kpi_view(ctx: dict) -> dict:
    """Extract KPI metadata + labels с v1.2 backward-compat fallback."""
    kpi = (ctx.get("kpi") or {}) if isinstance(ctx, dict) else {}
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


def _fmt_metric(value: Any, kpi: dict, fallback: str = "-") -> str:
    """Format metric value per (kpi_kind, mode).

    monetary roi: 1.5 → '1.50×'
    count: 120.5 → '120 ₽/ед.'
    effectiveness: 0.25 → '25%' (already as fraction). если value > 1 — already as pct.
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
        # share метрика. Если |value| <= 1 — fraction. Иначе уже %.
        if abs(f) <= 1.0:
            return f"{f * 100:.1f}%"
        return f"{f:.0f}%"
    if kind == "count":
        return f"{f:.0f} ₽/ед."
    return f"{f:.2f}×"


def _fmt_metric_bare(value: Any, kpi: dict, fallback: str = "-") -> str:
    """Inner CI-bracket version (без unit suffix)."""
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
        return f"{f:.0f}"
    return f"{f:.2f}"


def _fmt_metric_with_ci(mean: Any, ci_low: Any, ci_high: Any, kpi: dict) -> str:
    """KPI-aware analog of _fmt_x_with_ci."""
    base = _fmt_metric(mean, kpi)
    if ci_low is None or ci_high is None:
        return base
    tier = _ci_tier_class(mean, ci_low, ci_high)
    return (
        f'{base} <span class="ci-bracket {tier}">'
        f'[{_fmt_metric_bare(ci_low, kpi)} — {_fmt_metric_bare(ci_high, kpi)}]</span>'
    )


def _weighted_summary_phrase(weighted_value: Any, kpi: dict) -> str:
    """Краткая фраза «средний ROI/CPU/доля портфеля» с числом.

    Narrative_adapter всегда отдаёт `weighted_roi = total_contrib / total_spend`.
    Для count KPI — это units/₽ (обратное к CPU), потому преобразуем к CPU = 1/x.

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
            return f"CPU портфеля {cpu:.0f} ₽/ед."
        return "CPU портфеля недоступен"
    return f"ROI портфеля {wv:.2f}×"


def _under_breakeven_phrase(kpi: dict) -> str:
    """Описание условия 'канал убыточен' для текстов рекомендаций."""
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


def _table_metric_header(kpi: dict) -> tuple:
    """Returns (header_label, unit_label) для столбца главной метрики action_table."""
    mode = kpi.get("mode", "roi")
    kind = kpi.get("kpi_kind", "monetary")
    if mode == "effectiveness":
        return ("Доля эффекта", "%")
    if kind == "count":
        return ("CPU", "₽/ед.")
    return ("mROAS", "×")


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
    # 2026-05-04: gold-accent sigil over h1 — Aurora deliverable brand mark.
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
    """Section 2: Executive Summary - SCQAR preview (full blocks in s10)."""
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
        mqs = ctx.get("diagnostics", {}).get("mqs_score") or 0
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
                weighted_roi=wr, mqs=mqs
            )
        else:
            # v1.3.2: KPI-aware situation — заменяем «Weighted ROI X×» на CPU/доля.
            situation = (
                f"{client} размещает {budget:.0f} млн ₽ в квартал через "
                f"{n_ch} активных каналов. {_weighted_summary_phrase(wr, kpi)}, "
                f"MQS модели {mqs:.0f}/100."
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
        question = scqar["question"]["template"]
        # N3 (Phase 0.1): consistent answer logic with f3 + Action 01.
        # math-fix v1.0.14.1 (2026-04-28): + converged_at_current state — SLSQP
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
                "Оптимизатор сошёлся на текущем распределении — лучшее решение "
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
            # cut_source в narrative_adapter. Если empty («-») — пропускаем
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
                    # Без underperf clause — основная часть только
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
                    f"Сохранить приоритет {leader} с контролем saturation."
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

    body = f"""
{_action_title(title)}
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
                f"Медиа-вклад {_fmt_pct(media_pct)}, baseline {_fmt_pct(baseline_pct)} - "
                f"модель преимущественно объясняет продажи через organic baseline"
            )
            f1_sup = (
                f"{leader} - лидер среди медиа "
                f"({_fmt_pct(facts.get('leader_share_contrib_pct'))} media-вклада)"
            )
        else:
            # N1 (Phase 0.1): pre-format pct values to avoid {x:.0f} rounding
            # 0.4% to "0%" — see _fmt_pct conditional precision logic.
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
        if honest and hero_m < 1.0:
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
        all_below_breakeven = bool(channels) and all(
            (float(c.get("mroas") or c.get("roi") or 0) < 1.0) for c in channels
        )
        # N3 (Phase 0.1): if optimizer hit binding constraints, surface that
        # explicitly — otherwise narrative says "сохранить аллокацию" while
        # the real story is "оптимизатор не получил места для манёвра".
        if honest and all_below_breakeven:
            f3 = "Все медиа-каналы под breakeven - рассмотреть сокращение медиа или диагностику данных"
            if kpi["is_legacy"]:
                f3_sup = "При weighted ROI < 1× оптимизация перераспределением не вернёт прибыльность"
            else:
                f3_sup = (
                    f"Когда у всех каналов {_under_breakeven_phrase(kpi)} — "
                    "оптимизация перераспределением не вернёт прибыльность"
                )
        elif binding:
            f3 = "Оптимизатор упёрся в заданные границы - расширьте Мин./Макс. % и перезапустите"
            f3_sup = "Текущие границы зажимают пространство решений - реальное перераспределение скрыто"
        elif realloc >= 0.5 and hero != leader:
            f3 = strings["findings_templates"]["f3_realloc"].format(
                realloc=realloc, leader=leader, hero=hero)
            f3_sup = strings["findings_templates"]["f3_realloc_support"].format(lift=lift)
        else:
            f3 = strings["findings_templates"]["f3_keep"]
            f3_sup = strings["findings_templates"]["f3_keep_support"]
        findings.append((f3, f3_sup))

        scale_n = sum(1 for c in channels if c.get("verdict") == "Scale")
        cut_n = sum(1 for c in channels if c.get("verdict") in ("Cut", "Reduce"))
        f4 = strings["findings_templates"]["f4_verdicts"].format(scale_n=scale_n, cut_n=cut_n)
        f4_sup = strings["findings_templates"]["f4_verdicts_support"].format(n_channels=len(channels))
        findings.append((f4, f4_sup))

        try:
            mqs_val = float(mqs) if mqs is not None else 0
        except (TypeError, ValueError):
            mqs_val = 0
        # L16 (math-fix v1.4 Section C, 2026-04-29): align frontend tier labels
        # с backend (utils/diagnostics.py:62-72) — single 5-tier source of truth.
        # Pre-fix: frontend had 3 tiers (good/fair/poor at 80/60/<60), backend
        # had 5 tiers (excellent/good/acceptable/weak/poor at 85/70/55/40/<40)
        # → MQS=70 showed «Хорошее» (sources block) vs «приемлемо» (findings).
        diag_tier = (ctx.get("diagnostics") or {}).get("mqs_tier_label")
        # Audit fix (2026-04-29): explicit `is not None` check distinguishes
        # «backend not provided» vs «backend provided non-empty string».
        # Pre-fix: `if diag_tier:` falsy для empty string '' → silent fallback
        # к local computation, masking backend issues. Post-fix: trust backend
        # value when present (even if empty), only fallback when truly absent.
        if diag_tier is not None and diag_tier != "":
            tier_label_text = diag_tier
        elif mqs_val >= 85:
            tier_label_text = 'Отличное'
        elif mqs_val >= 70:
            tier_label_text = 'Хорошее'
        elif mqs_val >= 55:
            tier_label_text = 'Приемлемое'
        elif mqs_val >= 40:
            tier_label_text = 'Слабое'
        else:
            tier_label_text = 'Ненадёжное'
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
      <div class="chart-subtitle">Baseline + вклад каналов = итоговые продажи</div>
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
                "Модель преимущественно отражает baseline - "
                "медиа-вклад ограничен"
            )
            big = _fmt_pct(media_pct)
            big_label = "Медиа-вклад в продажи"
            big_support = f"Baseline: {_fmt_pct(baseline_pct)} · {portfolio_phrase}"
            quote = (
                f"{leader} - лидер среди медиа ({_fmt_pct(cpct)} media-вклада), "
                f"но абсолютный media-эффект {_fmt_pct(media_pct)} от продаж. "
                "Низкая инкрементальность - проверить adstock, saturation, качество данных."
            )
        else:
            title = strings["action_titles"]["s05_default"].format(leader=leader)
            big = _fmt_pct(cpct)
            big_label = f"Доля {leader} в инкрементальных продажах"
            big_support = f"При {_fmt_pct(spct)} доли бюджета · {portfolio_phrase}"

            if hero != leader:
                quote = (
                    f"Каждый рубль в {hero} возвращает больше, чем в {leader}. "
                    "Сигнал к reallocate части бюджета."
                )
            else:
                quote = f"{leader} - лидер и по вкладу, и по эффективности. Бюджет стоит сохранить до признаков saturation."
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
        chart_title_text = "CPU по каналам · ₽ за единицу"
        chart_subtitle_text = "Стоимость следующей единицы (incremental cost-per-unit)"
    else:
        chart_title_text = "mROAS по каналам · мультипликатор"
        chart_subtitle_text = "Marginal ROI последнего вложенного рубля"

    # Commentary blocks — math-fix v1.0.14.1 B refactor (2026-04-28).
    # Pre-fix: hardcoded «явный потенциал scale-up» / «потенциал удержания» /
    # «топ-2 канала» based на mROAS rank — independent от derive_verdict в
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

        # Show top-3 наиболее actionable channels — covers Scale/Reduce/Cut signals
        # + leaves room для Hold + Watch когда no decisive action в портфеле.
        # Skip duplicate action keys (e.g. 4 Scale channels — show only first).
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
                f"{ch_name} — {label}.",
                reasoning or f"mROAS {float(ch.get('mroas') or 0):.2f}×, рекомендация по портфелю.",
            ))
            if len(commentary_blocks) >= 3:
                break
        # Fallback когда channels not decorated (legacy callers без narrative_adapter)
        if not commentary_blocks:
            top_m = by_priority[0] if by_priority else {}
            commentary_blocks = [(
                f"{top_m.get('name', '-')} — лидер по mROAS.",
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

    rows_html = []
    for c in visible:
        name = c.get("name") or "-"
        spend_mln = float(c.get("spend") or 0) / 1_000_000.0
        contrib_mln = float(c.get("contribution") or 0) / 1_000_000.0
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
            f'<td class="num" data-sort="{contrib_mln:.2f}">{_fmt_mln(contrib_mln)}</td>'
            f'<td class="num" data-sort="{float(mroas or 0):.3f}">{mroas_html}{fn_html}</td>'
            f'<td class="num" data-sort="{share_pct}">{share_pct}</td>'
            f'<td><span class="verdict-badge verdict-{escape(verdict)}">{escape(verdict)}</span></td>'
            f'</tr>'
        )

    # Totals
    if facts:
        tb = facts.get("total_budget_mln") or 0
        tc = facts.get("total_contrib_mln") or 0
        wr = facts.get("weighted_roi")
        # v1.3.2: aggregate cell — adapt unit per KPI/mode.
        if not wr:
            wr_cell = "-"
        elif kpi["is_legacy"]:
            wr_cell = _fmt_x(wr)
        elif kpi["mode"] == "effectiveness":
            wr_cell = "100%"  # сумма долей = 100% по построению
        elif kpi["kpi_kind"] == "count":
            try:
                cpu = 1.0 / float(wr) if float(wr) > 0 else None
                wr_cell = f"{cpu:.0f} ₽/ед." if cpu else "-"
            except (TypeError, ValueError, ZeroDivisionError):
                wr_cell = "-"
        else:
            wr_cell = _fmt_x(wr)
        totals_html = (
            f'<tr class="totals-row">'
            f'<td>{escape(headers["totals"])}</td>'
            f'<td class="num">{_fmt_mln(tb)}</td>'
            f'<td class="num">{_fmt_mln(tc)}</td>'
            f'<td class="num">{wr_cell}</td>'
            f'<td class="num">100</td>'
            f'<td></td>'
            f'</tr>'
        )
    else:
        totals_html = ""

    # Footnotes
    # v1.3.2: KPI-aware verdict reason — заменяем «mROAS» / «рубля» на CPU / доля.
    if kpi["is_legacy"]:
        verdict_reasons_view = v_reasons
    else:
        metric_short = kpi["metric_short"]
        verdict_reasons_view = {}
        for verdict_name, reason_text in v_reasons.items():
            adapted = reason_text.replace("mROAS", metric_short)
            if kpi["mode"] == "effectiveness":
                adapted = adapted.replace("маржинальный возврат от дополнительного рубля",
                                          "вклад канала в доле эффекта")
            elif kpi["kpi_kind"] == "count":
                adapted = adapted.replace("маржинальный возврат от дополнительного рубля",
                                          "стоимость следующей единицы")
            verdict_reasons_view[verdict_name] = adapted

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
      <th scope="col" data-col="2" class="num" aria-sort="descending">{escape(headers["contrib"])} <span style="font-weight:400;color:var(--text-muted);">{escape(units["contrib"])}</span></th>
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
    """Section 9: Timeline stacked area + dataZoom."""
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    kicker = strings["sections"]["timeline"]["kicker"]

    leader = facts.get("leader_channel") if facts else None
    if leader:
        title = strings["action_titles"]["s08_leader"].format(leader=leader)
    else:
        title = "Динамика продаж по неделям"

    body = f"""
{_action_title(title)}
<div class="chart-container">
  <div class="chart-title-bar">
    <div>
      <div class="chart-title">Продажи по неделям · stacked area</div>
      <div class="chart-subtitle">Декомпозиция: baseline + вклад каналов. Перетаскивайте ползунок для зума.</div>
    </div>
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

        # N3 — Action 01: derived from optimizer state, not heuristics.
        # math-fix v1.0.14.1: + converged_at_current branch (false convergence).
        if not converged:
            action_01_text = (
                "Оптимизация не сошлась — попробуйте ослабить ограничения по каналам "
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
                "Расширьте до 10-20% / 200-300% и перезапустите Оптимизацию — "
                "она найдёт реальное перераспределение."
            )
        elif converged_at_current:
            action_01_text = (
                "Оптимизатор не нашёл лучшего распределения — оставил текущую "
                "аллокацию. Расширьте границы Min/Max или используйте экспертный "
                "режим для разблокировки реального перераспределения."
            )
        elif facts.get("cut_source_channel") and facts.get("scale_destination_channel") and realloc >= 0.5:
            # L15 (math-fix v1.4 Section C): action-driven reallocation subjects
            # вместо leader/hero. cut_source = optimizer's biggest cut, scale_dest
            # = biggest grow recommendation. Avoids «из Performance в Social»
            # когда Performance — small-budget сhannel.
            action_01_text = (
                f"{realloc:.0f} млн ₽ из {facts['cut_source_channel']} в {facts['scale_destination_channel']}. "
                "Adstock компенсирует краткосрочный спад awareness."
            )
        elif hero != leader and realloc >= 0.5:
            # Legacy fallback (cut_source/scale_dest unavailable)
            action_01_text = (
                f"{realloc:.0f} млн ₽ из {leader} в {hero}. "
                "Adstock компенсирует краткосрочный спад awareness."
            )
        else:
            action_01_text = (
                f"Портфель близок к оптимуму при заданных границах. "
                f"Сохранить аллокацию по {leader} с контролем индикаторов saturation."
            )

        # N4 — Actions 02/03: data-driven monitoring guidance (not generic boilerplate).
        # v1.3.2: KPI-aware breakeven phrasing.
        n_saturated = sum(
            1 for c in channels
            if (c.get("mroas") or 0) > 0 and (c.get("mroas") or 0) < 1.0
        )
        breakeven_phrase = "mROAS < 1×" if kpi["is_legacy"] else _under_breakeven_phrase(kpi)
        metric_short = kpi["metric_short"]
        if n_saturated > 0:
            action_02_text = (
                f"{n_saturated} канал(ов) под breakeven ({breakeven_phrase}) — "
                "проверить data quality, adstock decay и сравнить с industry benchmarks "
                "перед следующей итерацией."
            )
        else:
            action_02_text = (
                f"Все каналы выше breakeven — мониторить {metric_short} в следующих периодах "
                "на признаки saturation."
            )

        if underperf:
            # L12 (math-fix v1.4 Section C, 2026-04-29): full list, не top-2 slice.
            # Pre-fix: hardcoded [:2] hid 3-5 underperformers in commentary,
            # creating false impression of «small problem». Post-fix: all
            # action='Cut' channels listed → customer sees full picture.
            action_03_text = (
                f"Перевести бюджет из {', '.join(underperf)} согласно вердиктам, "
                "затем измерить эффект через 90 дней (KPI vs baseline)."
            )
        else:
            action_03_text = (
                "Замерить эффект через 90 дней (KPI vs baseline) — "
                "перезапустить MMM с обновлёнными данными для калибровки модели."
            )

        actions = [
            ("01", "Перебалансировать бюджет.", action_01_text),
            ("02", "Контролировать saturation.", action_02_text),
            ("03", "Замерить эффект через 90 дней.", action_03_text),
        ]
        lift_val = lift if lift is not None else 0
    else:
        title = "Рекомендация появится после оптимизации"
        actions = [
            ("01", "Перебалансировать бюджет.", "Из лидера в hero-канал по mROAS"),
            ("02", "Контролировать saturation.", "По каналам с mROAS < 1×"),
            ("03", "Замерить эффект через 90 дней.", "KPI vs baseline после применения"),
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

    # Optimize comparison chart (current vs optimal spend per channel)
    # rendered only when optimize data is available - JS checks CHART_DATA
    # shape and silently no-ops if empty.
    body = f"""
{_action_title(title)}
<div class="recommendations">
{actions_html}
</div>
<div class="impact-card" data-animate-counter>
  <div class="impact-label">Ожидаемый эффект</div>
  <div class="impact-hairline" aria-hidden="true"></div>
  <div class="impact-value" data-counter-end="{lift_val:.0f}">+{lift_val:.0f} пп</div>
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
    """Trust Level 3 (v1.1.0) — auto-generated methodology section про brand vs performance.

    Reads actual prior values из pickle config (issue K — methodology auto-syncs с code).
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
            return "—"
        decay = 1 / (1 + math.exp(-mu_logit))
        if decay <= 0 or decay >= 1:
            return "—"
        hl = math.log(0.5) / math.log(decay)
        return f"{hl:.1f} периодов"

    brand_mu = priors.get('brand_mu_logit_mean')
    perf_mu = priors.get('performance_mu_logit_mean') or priors.get('perf_mu_logit_mean')
    rows = []
    if n_brand:
        rows.append(f'<li><strong>Brand:</strong> {n_brand} канал(ов), effective half-life ≈ {_half_life(brand_mu)} (long-horizon decay)</li>')
    if n_perf:
        rows.append(f'<li><strong>Performance:</strong> {n_perf} канал(ов), effective half-life ≈ {_half_life(perf_mu)} (short-horizon decay)</li>')
    if n_mixed:
        rows.append(f'<li><strong>Смешанные:</strong> {n_mixed} канал(ов), single-prior fallback</li>')

    warning_html = ""
    rwarn = hier.get('rhat_warning')
    if rwarn:
        warning_html = f'<p style="color:var(--warning,#d97706);font-size:11px;margin-top:8px;">⚠ {escape(rwarn)}</p>'

    return f"""
<div class="brand-perf-block" style="margin-top:24px;padding:14px;background:rgba(127,90,240,0.05);border-left:3px solid rgba(127,90,240,0.5);border-radius:6px;">
  <div class="method-col-label" style="margin-bottom:8px;">Brand vs Performance моделирование (v1.1.0)</div>
  <p style="font-size:12px;line-height:1.5;color:var(--text-secondary,#94a3b8);">
    Модель разделяет каналы на brand (long-horizon decay) и performance (short-horizon decay).
    Brand-каналы получают hierarchical prior с большей variance — отражает unknown brand-build duration.
    Performance-каналы используют тесный prior на короткий decay.
  </p>
  <ul style="font-size:12px;line-height:1.7;margin-top:8px;padding-left:16px;">
{chr(10).join(rows)}
  </ul>
  <p style="font-size:11px;font-style:italic;color:var(--text-muted,#64748b);margin-top:8px;">
    Атрибуция между brand и performance имеет fundamental uncertainty — мы используем priors based on industry norms.
    Если категория канала вызывает сомнения, проверьте классификацию на шаге Validate.
  </p>
  {warning_html}
</div>"""


def render_methodology(ctx: dict) -> str:
    """Section 11: Methodology + limitations."""
    strings = ctx["strings"]
    diag = ctx.get("diagnostics") or {}
    kicker = strings["sections"]["method"]["kicker"]
    meth = strings["methodology"]

    formulas_text = "\n".join(meth["spec_formulas"])
    diag_items = []
    if diag.get("r_squared") is not None:
        diag_items.append(("R²", f"{float(diag['r_squared']):.3f}"))
    if diag.get("mape_pct") is not None:
        diag_items.append(("MAPE", f"{float(diag['mape_pct']):.1f}%"))
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

    body = f"""
{_action_title(strings["action_titles"]["s10_methodology"])}
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
<p style="margin-top:24px;font-size:11px;font-style:italic;color:var(--text-muted);">{escape(meth["prior_note"])}</p>
{brand_perf_html}"""
    return _section("method", kicker, body)


def render_sources(ctx: dict) -> str:
    """Section 12: Sources + MQS card with verify badge."""
    strings = ctx["strings"]
    diag = ctx.get("diagnostics") or {}
    kicker = strings["sections"]["sources"]["kicker"]

    mqs = diag.get("mqs_score")
    mqs_tier = diag.get("mqs_tier_label") or "-"
    try:
        mqs_display = f"{int(round(float(mqs)))}" if mqs is not None else "-"
    except (TypeError, ValueError):
        mqs_display = "-"

    mqs_diag_html = ""
    for lbl, key, fmt in [
        ("R²", "r_squared", lambda v: f"{float(v):.3f}"),
        ("MAPE", "mape_pct", lambda v: f"{float(v):.1f}%"),
        ("R-hat", "r_hat_max", lambda v: f"{float(v):.3f}"),
        ("ESS", "ess_min", lambda v: _fmt_int(v)),
    ]:
        if diag.get(key) is not None:
            mqs_diag_html += f'<div><span class="mqs-diag-label">{lbl}</span><span>{fmt(diag[key])}</span></div>'

    body = f"""
{_action_title("Качество модели и источники данных")}
<div class="sources-grid">
  <div class="mqs-card">
    <div class="mqs-label">Model Quality Score</div>
    <div class="mqs-score">{escape(mqs_display)}<sub>/100</sub></div>
    <div class="mqs-tier">{escape(mqs_tier)}</div>
    {f'<div class="mqs-diag">{mqs_diag_html}</div>' if mqs_diag_html else ''}
    <a class="method-badge" href="#method">{escape(strings["brand"]["methodology_badge"])}</a>
  </div>
  <div>
    <div class="method-col-label">Источники данных</div>
    <ul class="sources-list">
      <li>Продажи: первичные данные клиента</li>
      <li>Медиа-инвестиции: биллинг по каналам</li>
      <li>Нормирование: CPP / CPM per unit</li>
      <li>Сезонность и макро: константы в baseline</li>
      <li>Bayesian MMM · posterior means · 95% CI</li>
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
    ('method',    render_methodology),
    ('sources',   render_sources),
    ('glossary',  render_glossary),
    ('closing',   render_closing),
)
