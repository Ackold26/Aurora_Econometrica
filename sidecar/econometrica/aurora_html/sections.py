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


def _fmt_pct(v: Any, fallback: str = "-") -> str:
    try:
        return f"{float(v):.0f}%"
    except (TypeError, ValueError):
        return fallback


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

    body = f"""
<div class="cover">
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
      <dt class="cover-meta-label">Версия</dt>
      <dd class="cover-meta-value">v{escape(version)}</dd>
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

        situation = scqar["situation"]["template"].format(
            client=client, budget_mln=budget, n_channels=n_ch,
            weighted_roi=wr, mqs=mqs
        )
        complication = scqar["complication"]["template"].format(
            leader=leader, leader_spend_pct=leader_pct,
            hero=hero, hero_mroas=hero_m
        )
        question = scqar["question"]["template"]
        answer = scqar["answer"]["template"].format(
            realloc=realloc, leader=leader, hero=hero, underperf=underperf
        )
        recommendation = scqar["recommendation"]["template"].format(lift=lift)
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

    findings = []
    if facts and channels:
        leader = facts.get("leader_channel") or "-"
        hero = facts.get("hero_channel") or leader
        honest = bool(facts.get("honest_narrative"))
        media_pct = facts.get("media_contribution_pct")
        baseline_pct = facts.get("baseline_pct")

        if honest and media_pct is not None and baseline_pct is not None:
            f1 = (
                f"Медиа-вклад {media_pct:.1f}%, baseline {baseline_pct:.1f}% - "
                f"модель преимущественно объясняет продажи через organic baseline"
            )
            f1_sup = (
                f"{leader} - лидер среди медиа "
                f"({facts.get('leader_share_contrib_pct') or 0:.0f}% media-вклада)"
            )
        else:
            f1 = strings["findings_templates"]["f1_leader"].format(
                leader=leader,
                contrib_pct=facts.get("leader_share_contrib_pct") or 0,
                spend_pct=facts.get("leader_share_spend_pct") or 0,
            )
            f1_sup = strings["findings_templates"]["f1_leader_support"].format(
                weighted_roi=facts.get("weighted_roi") or 0
            )
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

        if honest and hero_m < 1.0:
            f2 = f"{hero} - лучший среди медиа, но всё ещё под breakeven (mROAS {hero_m:.1f}×)"
            f2_sup = "ROI < 1× означает что канал тратит больше чем приносит инкрементала"
        elif honest:
            f2 = f"{hero} - единственный канал близкий к окупаемости (mROAS {hero_m:.1f}×)"
            f2_sup = strings["findings_templates"]["f2_hero_support"].format(hero_spend_pct=hero_spend_pct)
        else:
            f2 = strings["findings_templates"]["f2_hero"].format(hero=hero, hero_mroas=hero_m)
            f2_sup = strings["findings_templates"]["f2_hero_support"].format(hero_spend_pct=hero_spend_pct)
        findings.append((f2, f2_sup))

        realloc = facts.get("reallocation_mln") or 0
        lift = facts.get("expected_lift_pct") or 0
        all_below_breakeven = bool(channels) and all(
            (float(c.get("mroas") or c.get("roi") or 0) < 1.0) for c in channels
        )
        if honest and all_below_breakeven:
            f3 = "Все медиа-каналы под breakeven - рассмотреть сокращение медиа или диагностику данных"
            f3_sup = "При weighted ROI < 1× оптимизация перераспределением не вернёт прибыльность"
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
        if mqs_val >= 80:
            f5 = strings["findings_templates"]["f5_mqs_good"].format(mqs=mqs_val)
            f5_sup = strings["findings_templates"]["f5_mqs_good_support"]
        elif mqs_val >= 60:
            f5 = strings["findings_templates"]["f5_mqs_fair"].format(mqs=mqs_val)
            f5_sup = strings["findings_templates"]["f5_mqs_fair_support"]
        else:
            f5 = strings["findings_templates"]["f5_mqs_poor"].format(mqs=mqs_val)
            f5_sup = strings["findings_templates"]["f5_mqs_poor_support"]
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
            leader=leader, contrib_pct=cpct, spend_pct=spct)
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

    if facts:
        leader = facts.get("leader_channel") or "-"
        hero = facts.get("hero_channel") or leader
        cpct = facts.get("leader_share_contrib_pct") or 0
        spct = facts.get("leader_share_spend_pct") or 0
        wr = facts.get("weighted_roi") or 1.0
        honest = bool(facts.get("honest_narrative"))
        media_pct = facts.get("media_contribution_pct")
        baseline_pct = facts.get("baseline_pct")

        if honest and media_pct is not None and baseline_pct is not None:
            title = (
                "Модель преимущественно отражает baseline - "
                "медиа-вклад ограничен"
            )
            big = _fmt_pct(media_pct)
            big_label = "Медиа-вклад в продажи"
            big_support = f"Baseline: {baseline_pct:.1f}% · ROI портфеля {wr:.2f}×"
            quote = (
                f"{leader} - лидер среди медиа ({cpct:.0f}% media-вклада), "
                f"но абсолютный media-эффект {media_pct:.1f}% от продаж. "
                "Низкая инкрементальность - проверить adstock, saturation, качество данных."
            )
        else:
            title = strings["action_titles"]["s05_default"].format(leader=leader)
            big = _fmt_pct(cpct)
            big_label = f"Доля {leader} в инкрементальных продажах"
            big_support = f"При {int(spct)}% доли бюджета · ROI портфеля {wr:.2f}×"

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

    hero = facts.get("hero_channel") if facts else None
    title = strings["action_titles"]["s06_hero"].format(hero=hero or "лидер портфеля")

    # Commentary blocks
    if channels and facts:
        by_m = sorted(channels, key=lambda c: float(c.get("mroas") or 0), reverse=True)
        hero_ch = by_m[0] if by_m else {}
        second = by_m[1] if len(by_m) > 1 else {}
        hero_name = hero_ch.get("name") or "-"
        hero_m = float(hero_ch.get("mroas") or 0)
        second_name = second.get("name") or ""
        second_m = float(second.get("mroas") or 0)
        underperf = [c.get("name") for c in channels if float(c.get("mroas") or 0) < 1.0]

        commentary_blocks = []
        if hero_name:
            commentary_blocks.append((
                f"{hero_name} - лидер по mROAS.",
                f"mROAS {hero_m:.2f}× - каждый дополнительный рубль возвращает больше, чем в других каналах. Явный потенциал scale-up."
            ))
        if second_name and second_m >= 1.0:
            commentary_blocks.append((
                f"{second_name} устойчиво эффективен.",
                f"mROAS {second_m:.2f}× при текущих расходах. Низкая волатильность, потенциал удержания."
            ))
        if underperf:
            names_str = " и ".join(underperf[:2])
            commentary_blocks.append((
                f"{names_str} ниже breakeven.",
                "mROAS <1.0× - бюджет рекомендуется перевести в топ-2 канала портфеля."
            ))
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
        <div class="chart-title">mROAS по каналам · мультипликатор</div>
        <div class="chart-subtitle">Marginal ROI последнего вложенного рубля</div>
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
            title = strings["action_titles"]["s07_dominant"].format(pct=pct)
        elif other_n > 0:
            title = strings["action_titles"]["s07_top_n"].format(top_n=top_n, pct=pct)
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

        rows_html.append(
            f'<tr data-channel="{escape(name)}">'
            f'<td>{escape(name)}</td>'
            f'<td class="num" data-sort="{spend_mln:.2f}">{_fmt_mln(spend_mln)}</td>'
            f'<td class="num" data-sort="{contrib_mln:.2f}">{_fmt_mln(contrib_mln)}</td>'
            f'<td class="num" data-sort="{float(mroas or 0):.3f}">{_fmt_x(mroas)}{fn_html}</td>'
            f'<td class="num" data-sort="{share_pct}">{share_pct}</td>'
            f'<td><span class="verdict-badge verdict-{escape(verdict)}">{escape(verdict)}</span></td>'
            f'</tr>'
        )

    # Totals
    if facts:
        tb = facts.get("total_budget_mln") or 0
        tc = facts.get("total_contrib_mln") or 0
        wr = facts.get("weighted_roi")
        totals_html = (
            f'<tr class="totals-row">'
            f'<td>{escape(headers["totals"])}</td>'
            f'<td class="num">{_fmt_mln(tb)}</td>'
            f'<td class="num">{_fmt_mln(tc)}</td>'
            f'<td class="num">{_fmt_x(wr) if wr else "-"}</td>'
            f'<td class="num">100</td>'
            f'<td></td>'
            f'</tr>'
        )
    else:
        totals_html = ""

    # Footnotes
    if flagged:
        fn_items = []
        for i, c in enumerate(flagged):
            num = str(i + 1)
            name = c.get("name") or "-"
            reason = v_reasons.get(c.get("verdict"), "")
            fn_items.append(
                f'<li><span class="fn-num">{num}</span>{escape(name)}: {escape(reason)}</li>'
            )
        fn_html = f"""
<div class="footnotes">
  <div class="footnotes-label">Примечания</div>
  <ol class="footnotes-list">{"".join(fn_items)}</ol>
</div>"""
    elif channels:
        fn_html = """
<div class="footnotes">
  <div class="footnotes-label">Примечания</div>
  <ol class="footnotes-list"><li><span class="fn-num">-</span>Все каналы портфеля в рабочем диапазоне mROAS; критических рекомендаций нет.</li></ol>
</div>"""
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
      <th scope="col" data-col="3" class="num" aria-sort="none">{escape(headers["mroas"])} <span style="font-weight:400;color:var(--text-muted);">{escape(units["mroas"])}</span></th>
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
    """Section 10: SCQAR recommendation - 3 actions + lift."""
    strings = ctx["strings"]
    facts = ctx.get("facts") or {}
    channels = ctx.get("channels") or []
    kicker = strings["sections"]["recommend"]["kicker"]

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
        lift_txt = f"+{lift:.1f} пп к ROAS" if lift else "положительный эффект на ROAS"

        actions = [
            ("01", "Перебалансировать бюджет.",
             (f"{realloc:.0f} млн ₽ из {leader} в {hero}. Adstock компенсирует краткосрочный спад awareness."
              if hero != leader and realloc >= 1
              else f"Сохранить аллокацию по {leader} с контролем индикаторов saturation.")),
            ("02", "Burst-планирование вместо continuity.",
             f"Короткие flights {leader} с паузами - 15-20% экономии бюджета при сохранении awareness."),
            ("03", "Targeted retargeting через эффективные сегменты.",
             f"Segment приоритета {hero}; {lift_txt}."
             + (f" Перевести бюджет из {', '.join(underperf[:2])}." if underperf else "")),
        ]
        lift_val = lift if lift is not None else 0
    else:
        title = "Рекомендация появится после оптимизации"
        actions = [
            ("01", "Перебалансировать бюджет.", "Из лидера в hero-канал по mROAS"),
            ("02", "Burst-планирование.", "Flights вместо continuous контакта"),
            ("03", "Targeted retargeting.", "Эффективные сегменты + саутовер бюджета"),
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
  <div class="impact-period">Прогнозный ROAS</div>
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
<p style="margin-top:24px;font-size:11px;font-style:italic;color:var(--text-muted);">{escape(meth["prior_note"])}</p>"""
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
