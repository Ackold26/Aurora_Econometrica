#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aurora Econometrica – генератор глоссария (SSOT).

Закрывает «три расходящихся глоссария»: единый источник → три выхода.

Источники (human-editable):
  • docs/GLOSSARY_v2_1_0.md  – основной контент (37 терминов, user-friendly:
    Что это / Пример / Когда увидите в Aurora / Связанные термины).
  • LEGACY_ONLY (ниже)       – ~10 app-внутренних терминов (режимы, KPI,
    goal-seek и т.п.), которых нет в публичном md, но на которые ссылается
    код (GlossaryTerm termId=..., insights). Сохраняются ради обратной
    совместимости in-app id (см. CRITICAL_IDS / LEGACY_IDS – guard ниже).

Выходы (GENERATED – не редактировать вручную):
  • docs/glossary.json                          – машинный SSOT-артефакт
  • src-tauri/help-econometrica/glossary.html   – страница справки
  • src/lib/glossary.js                         – in-app модуль (API сохранён)

Запуск:  PYTHONUTF8=1 python tools/build_glossary.py
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs" / "GLOSSARY_v2_1_0.md"
OUT_JSON = ROOT / "docs" / "glossary.json"
OUT_HTML = ROOT / "src-tauri" / "help-econometrica" / "glossary.html"
OUT_JS = ROOT / "src" / "lib" / "glossary.js"

# ── id-карта: заголовок md → стабильный id (overlap с legacy → legacy id) ──
ID_MAP = {
    "ROAS (Возврат на рекламные расходы)": "roas",
    "ROI (Возврат на вложения)": "roi",
    "Декомпозиция (Decomposition)": "decomposition",
    "Базовые продажи (Base Sales)": "base_sales",
    "Инкрементальный вклад (Incremental)": "incremental",
    "Доля голоса (Share of Voice, SOV)": "sov",
    "Доля рынка (Share of Market, SOM)": "som",
    "Эластичность (Elasticity)": "elasticity",
    "Априорные знания (Prior)": "prior",
    "Апостериорные знания (Posterior)": "posterior",
    "Правдоподобный диапазон": "posterior_ci",
    "MCMC (Алгоритм байесовского расчёта)": "mcmc",
    "R-hat (Сходимость MCMC)": "r_hat",
    "ESS (Эффективный объём выборки)": "ess",
    "Остаточный эффект (Adstock, Carryover)": "adstock",
    "Пиковая неделя (Peak Week)": "peak_week",
    "Период полураспада (Half-Life)": "half_life",
    "Насыщение (Saturation)": "hill_saturation",
    "Кривая отклика (Response Curve)": "response_curve",
    "Плато (Plateau)": "plateau",
    "Убывающая отдача (Diminishing Returns)": "diminishing_returns",
    "Маржинальный вклад (Marginal Contribution)": "mroi",
    "CPU (Стоимость единицы)": "cpu",
    "Атрибуция каналов (Channel Attribution)": "channel_attribution",
    "Медиамикс (Media Mix)": "media_mix",
    "GRP / TRP (Рейтинговые пункты)": "grp_trp",
    "CPP (Стоимость пункта рейтинга)": "cpp",
    "Охват (Reach)": "reach",
    "Частота (Frequency)": "frequency",
    "R² (Коэффициент детерминации)": "r_squared",
    "MAPE (Процент ошибки)": "mape",
    "Сценарий «что если» (Scenario / What-If)": "scenario_whatif",
    "Чувствительность (Sensitivity)": "sensitivity",
    "Подъём (Lift)": "lift",
    "Безопасный коридор": "safe_corridor",
    "Ретроспективный тест (Hold-Out Backtest)": "backtest",
    "OVB (Смещение из-за пропущенной переменной)": "ovb",
}

# ── legacy-only термины (нет в md, но ссылается код) ─────────────────────
LEGACY_ONLY = {
    "mmm": {
        "term": "MMM (Marketing Mix Modeling)",
        "short": "Метод эконометрики, оценивающий вклад каждого маркетингового канала в продажи.",
        "what": "MMM использует исторические данные (бюджеты или контакты каналов + продажи) и строит математическую модель, которая разлагает продажи на базовый уровень и вклад каждого канала. Главная цель – понять «какой канал приносит результат» и «куда лучше переложить бюджет». Aurora использует байесовский подход (NumPyro + JAX) с нелинейными преобразованиями (adstock, Hill).",
        "example": "За год потратили 100 млн ₽ на рекламу. MMM показывает: ТВ дал 35% продаж, performance digital – 25%, retail media – 18%. Теперь можно перераспределить бюджет в более эффективные каналы.",
        "where": "Это основа всего продукта: пайплайн из 7 шагов от данных до оптимального бюджета.",
        "related": ["adstock", "hill_saturation", "decomposition"],
    },
    "bayesian": {
        "term": "Байесовский вывод (Bayesian inference)",
        "short": "Подход, когда вместо одной оценки параметра модель даёт распределение возможных значений.",
        "what": "Обычный подход даёт точечную оценку («ROI канала = 1.5»). Байесовский даёт распределение: «ROI с вероятностью 90% от 1.3 до 1.7». Это честнее отражает неопределённость, особенно при малой выборке. Aurora использует NumPyro для эффективного сэмплирования (MCMC NUTS).",
        "example": "Модель: ROI ТВ = 2.1 (90% интервал [1.6, 2.7]). Мы уверены в положительном ROI, но точная цифра может быть от 1.6 до 2.7.",
        "where": "Под капотом при обучении модели на достаточных данных (на коротких рядах – устойчивый OLS).",
        "related": ["posterior", "mcmc", "prior"],
    },
    "value_per_count_unit": {
        "term": "Ценность единицы (value per unit)",
        "short": "Сколько ₽ для бизнеса стоит одна единица целевой количественной метрики.",
        "what": "Для количественного KPI (упаковки, лиды, подписки) задаётся ценность одной единицы – маржа на упаковку, ценность лида, MRR на подписку. Это порог для сравнения со стоимостью единицы (CPU): если CPU ниже ценности – канал прибыльный.",
        "example": "Цена упаковки 200 ₽, себестоимость 40% → маржа 120 ₽/упак. Канал с CPU выше 120 ₽/упак убыточен.",
        "where": "Шаг «Валидация» / «Оптимизация» при количественном KPI – поле «Ценность единицы».",
        "related": ["cpu", "kpi_kind"],
    },
    "sales_share": {
        "term": "Доля вклада в продажи (sales contribution share)",
        "short": "Доля канала в общих продажах, %.",
        "what": "Безразмерная метрика, корректно сравнивающая каналы в режиме «Эффективность» (где денег нет в модели). Считается как вклад канала / общие продажи × 100%. Главная метрика, когда денежная окупаемость недоступна.",
        "example": "ТВ дал вклад 35 млн из 100 млн общих → доля 35%. Лидер – ТВ. Сравнение работает независимо от единиц каналов.",
        "where": "Декомпозиция и вердикты каналов в режиме «Эффективность».",
        "related": ["mode_effectiveness", "decomposition"],
    },
    "kpi_kind": {
        "term": "Тип KPI (денежный / количественный)",
        "short": "Целевая метрика бывает денежной (рубли) или количественной (штуки).",
        "what": "Денежный KPI (выручка, прибыль, GMV) – главная метрика канала ROI. Количественный KPI (упаковки, лиды, регистрации, подписки, установки) – главная метрика CPU в сравнении с ценностью единицы. От типа KPI зависят доступные режимы и метрики.",
        "example": "Проект с KPI «упаковки» → количественный → колонка CPU, ценность единицы = маржа.",
        "where": "Шаг «Валидация» → выбор KPI.",
        "related": ["cpu", "roi", "value_per_count_unit"],
    },
    "derived_mode": {
        "term": "Автоопределение режима",
        "short": "Режим анализа выводится из выбранных единиц каналов.",
        "what": "Приложение определяет режим по данным: все каналы в рублях → ROI; все в физических метриках → Эффективность; смешанные единицы → Эксперт/Смешанный. Совпадает с отраслевым стандартом (Robyn, PyMC-Marketing).",
        "example": "ТВ в ₽, OLV в показах, Performance в ₽ → смешанный (Эксперт). Все 7 каналов в ₽ → режим ROI.",
        "where": "Шаг «Валидация» – режим показывается автоматически по ролям и единицам.",
        "related": ["mode_roi", "mode_effectiveness", "kpi_kind"],
    },
    "goal_seek": {
        "term": "Подбор под цель (обратная оптимизация)",
        "short": "Дана цель продаж – найти минимальный бюджет, который её достигает.",
        "what": "Двойственная задача к прямой оптимизации. Aurora ищет минимальный бюджет, при котором прогноз достигает цели (функция отклика монотонна). Правдоподобный диапазон требуемого бюджета – через границы прогноза. Если цель за пределами безопасного коридора – «недостижимо».",
        "example": "Текущие продажи 100 млн ₽. Цель 110 млн ₽ (+10%). Подбор под цель: требуемый бюджет 95 млн ₽, вероятность достижения 78%.",
        "where": "Шаг «Оптимизация» → обратный режим.",
        "related": ["safe_corridor", "scenario_whatif"],
    },
    "mode_roi": {
        "term": "Режим ROI (деньги)",
        "short": "Режим, в котором все каналы измеряются в рублях.",
        "what": "Вход – бюджеты каналов в ₽, модель оценивает окупаемость ₽/₽ и оптимизирует бюджет в деньгах. Зависит от точности бюджетных данных. Выводится автоматически, когда все каналы в рублях.",
        "example": "Все 7 каналов в ₽ → режим ROI → колонки ROI в декомпозиции.",
        "where": "Шаг «Валидация» → выбор режима.",
        "related": ["derived_mode", "mode_effectiveness", "roi"],
    },
    "mode_effectiveness": {
        "term": "Режим Эффективность (физика)",
        "short": "Режим, в котором все каналы измеряются в физических контактах.",
        "what": "Вход – показы / клики / GRP, модель оценивает долю вклада, %. Подходит, когда бюджеты непрозрачны (агентские скидки), но трафик меряется точно. Сравнение каналов – только через долю вклада.",
        "example": "Все каналы в показах/GRP → режим Эффективность → доли вклада вместо ROI.",
        "where": "Шаг «Валидация» → выбор режима.",
        "related": ["derived_mode", "mode_roi", "sales_share"],
    },
    "hierarchical_priors": {
        "term": "Иерархические априорные знания",
        "short": "Бренд- и performance-каналы имеют разные ожидания, потому что работают по-разному.",
        "what": "Aurora задаёт разные априорные ожидания по характеру отклика каналов. Каналы с долгосрочным откликом – нарастающий эффект, держится дольше; каналы с быстрым откликом – эффект почти сразу, затухает быстро. Это улучшает различимость каналов на малых выборках.",
        "example": "Каналы с долгим откликом ожидают 4–12 недель эффекта, каналы с быстрым откликом – 1–3 недели. Если данные показывают обратное – модель сместится.",
        "where": "Под капотом при настройке отраслевой категории проекта.",
        "related": ["prior", "adstock", "bayesian"],
    },
}

# раздел для legacy-only терминов
LEGACY_SECTION = "Режимы, KPI и методология"

CRITICAL_IDS = {"adstock", "hill_saturation", "roi", "goal_seek"}  # inline в .svelte
LEGACY_IDS = {  # все id, существовавшие в прежнем glossary.js (guard от потери)
    "mmm", "adstock", "hill_saturation", "bayesian", "prior", "posterior",
    "mcmc", "r_hat", "roi", "cpu", "value_per_count_unit", "sales_share",
    "kpi_kind", "derived_mode", "safe_corridor", "goal_seek", "mode_roi",
    "mode_effectiveness", "hierarchical_priors", "mroi",
}


def gh_slug(heading: str) -> str:
    """GitHub-anchor slug (для резолва «Связанные термины» из md)."""
    s = heading.lower()
    s = re.sub(r"[^\w\s²Ѐ-ӿ-]", "", s, flags=re.UNICODE)
    s = s.replace(" ", "-")
    return s


def parse_md():
    text = MD.read_text(encoding="utf-8")
    lines = text.split("\n")
    terms = []  # (heading, en, what, example, where, related_slugs, section)
    section = ""
    i = 0
    cur = None

    def flush():
        nonlocal cur
        if cur:
            terms.append(cur)
            cur = None

    while i < len(lines):
        line = lines[i]
        if line.startswith("## ") and not line.startswith("### "):
            flush()
            sec = line[3:].strip()
            if sec not in ("Содержание", "Алфавитный указатель"):
                section = sec
            i += 1
            continue
        if line.startswith("### "):
            flush()
            heading = line[4:].strip()
            cur = {"heading": heading, "section": section, "en": "",
                   "what": "", "example": "", "where": "", "related": []}
            i += 1
            continue
        if cur is not None:
            stripped = line.strip()

            def grab(label):
                # собрать текст после «**label**» до пустой строки
                buf = [stripped.split("**", 2)[-1].lstrip()]
                j = i + 1
                while j < len(lines) and lines[j].strip() and not lines[j].lstrip().startswith("**"):
                    buf.append(lines[j].strip())
                    j += 1
                return " ".join(buf).strip(), j

            if stripped.startswith("**Что это.**"):
                cur["what"], i = grab("Что это."); continue
            if stripped.startswith("**Пример.**"):
                cur["example"], i = grab("Пример."); continue
            if stripped.startswith("**Когда увидите в Aurora.**"):
                cur["where"], i = grab("Когда увидите в Aurora."); continue
            if stripped.startswith("**Связанные термины:**"):
                cur["related"] = re.findall(r"\(#([^)]+)\)", stripped)
                i += 1; continue
            # строка с **Term** (English ...) – извлечь en-часть
            if not cur["en"] and stripped.startswith("**") and "(" in stripped:
                m = re.search(r"\(([^)]+)\)", stripped)
                if m:
                    cur["en"] = m.group(1).strip()
        i += 1
    flush()
    return terms


def first_sentence(text: str, limit: int = 160) -> str:
    t = text.strip()
    m = re.search(r"(.+?[.!?])(\s|$)", t)
    s = m.group(1) if m else t
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] + "…"
    return s


def _norm_dash(s: str) -> str:
    """Клиентская типографика: em-dash (U+2014) → короткое тире (U+2013).
    Defense-in-depth – источник может протечь em-dash, выход обязан быть чистым."""
    return s.replace(chr(0x2014), chr(0x2013)) if s else s


def build():
    md_terms = parse_md()
    # slug → id
    slug2id = {}
    for t in md_terms:
        tid = ID_MAP.get(t["heading"])
        if not tid:
            print(f"[WARN] нет id для заголовка: {t['heading']}", file=sys.stderr)
            tid = gh_slug(t["heading"]).replace("-", "_")
        t["id"] = tid
        slug2id[gh_slug(t["heading"])] = tid

    terms = []  # итоговый список dict (SSOT)
    seen = set()
    for t in md_terms:
        related = [slug2id[a] for a in t["related"] if a in slug2id]
        terms.append({
            "id": t["id"], "term": t["heading"], "en": t["en"],
            "short": first_sentence(t["what"]),
            "what": t["what"], "example": t["example"], "where": t["where"],
            "related": related, "section": t["section"],
        })
        seen.add(t["id"])

    for tid, t in LEGACY_ONLY.items():
        if tid in seen:
            continue
        related = [r for r in t.get("related", []) if r in seen or r in LEGACY_ONLY]
        terms.append({
            "id": tid, "term": t["term"], "en": "",
            "short": t["short"], "what": t["what"], "example": t["example"],
            "where": t.get("where", ""), "related": related,
            "section": LEGACY_SECTION,
        })
        seen.add(tid)

    # повторная фильтрация related (теперь известны все id)
    all_ids = {t["id"] for t in terms}
    for t in terms:
        t["related"] = [r for r in t["related"] if r in all_ids and r != t["id"]]

    # ── guard: критичные и legacy id обязаны присутствовать ──
    missing_crit = CRITICAL_IDS - all_ids
    missing_legacy = LEGACY_IDS - all_ids
    if missing_crit:
        sys.exit(f"[FAIL] потеряны inline-id из .svelte: {missing_crit}")
    if missing_legacy:
        sys.exit(f"[FAIL] потеряны legacy glossary.js id: {missing_legacy}")

    # ── defense-in-depth: нормализация тире по всем текстовым полям ──
    for t in terms:
        for f in ("term", "en", "short", "what", "example", "where"):
            if t.get(f):
                t[f] = _norm_dash(t[f])

    write_json(terms)
    write_html(terms)
    write_js(terms)
    print(f"[OK] глоссарий собран: {len(terms)} терминов "
          f"({len(md_terms)} из md + {len(terms) - len(md_terms)} legacy)")


def write_json(terms):
    OUT_JSON.write_text(json.dumps(
        {"_generated": "tools/build_glossary.py – НЕ редактировать вручную; "
                       "правьте docs/GLOSSARY_v2_1_0.md или LEGACY_ONLY и пересоберите",
         "count": len(terms), "terms": terms},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def linkify_related(rel_ids, by_id):
    parts = []
    for r in rel_ids:
        if r in by_id:
            parts.append(f'<a href="#{r}">{esc(by_id[r]["term"])}</a>')
    return ", ".join(parts)


def write_html(terms):
    by_id = {t["id"]: t for t in terms}
    # порядок разделов: как в md + legacy в конце
    sections = []
    for t in terms:
        if t["section"] not in sections:
            sections.append(t["section"])
    # алфавитный указатель
    idx = sorted(terms, key=lambda t: t["term"].lower())
    index_html = "\n".join(
        f'    <li><a href="#{t["id"]}">{esc(t["term"])}</a></li>' for t in idx)

    body = []
    for sec in sections:
        sec_terms = [t for t in terms if t["section"] == sec]
        if not sec_terms:
            continue
        body.append(f'<h2>{esc(sec)}</h2>')
        for t in sec_terms:
            en = f' <span class="en">{esc(t["en"])}</span>' if t["en"] else ""
            card = [f'<div class="term" id="{t["id"]}">',
                    f'  <h3>{esc(t["term"])}{en}</h3>']
            if t["what"]:
                card.append(f'  <p>{esc(t["what"])}</p>')
            if t["example"]:
                card.append(f'  <div class="ex"><span class="lbl">Пример</span>{esc(t["example"])}</div>')
            if t["where"]:
                card.append(f'  <div class="where"><span class="lbl">Где в Aurora</span>{esc(t["where"])}</div>')
            rel = linkify_related(t["related"], by_id)
            if rel:
                card.append(f'  <div class="rel">Связанные: {rel}</div>')
            card.append('</div>')
            body.append("\n".join(card))
    body_html = "\n".join(body)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Глоссарий – Aurora AI Econometrica</title>
<script src="econ-nav.js" defer></script>
<style>
:root {{
  --bg: #0d1117; --bg2: #161b22; --bg3: #1c2128;
  --text: #e6edf3; --text2: #8b949e; --text3: #6e7681;
  --accent: #58a6ff; --accent2: #3fb950; --border: #30363d;
  --green: #3fb950; --amber: #d29922; --red: #f85149; --teal: #39d0d8;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.65; }}
.container {{ max-width: 900px; margin: 0 auto; padding: 40px 32px 80px; }}
h1 {{ font-size: 30px; font-weight: 700; margin-bottom: 6px; letter-spacing: -0.02em; }}
.sub {{ font-size: 15.5px; color: var(--text2); margin-bottom: 24px; }}
h2 {{ font-size: 19px; font-weight: 700; margin: 44px 0 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); color: var(--teal); scroll-margin-top: 20px; }}
h3 {{ font-size: 16px; font-weight: 600; margin: 0 0 8px; color: var(--text); scroll-margin-top: 20px; }}
h3 .en {{ font-size: 12.5px; font-weight: 500; color: var(--text3); margin-left: 6px; }}
p {{ font-size: 14px; margin-bottom: 8px; color: var(--text2); }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.search-box {{ width: 100%; background: var(--bg2); border: 1px solid var(--border); color: var(--text); font-size: 14px; padding: 11px 16px; border-radius: 9px; outline: none; margin: 8px 0 4px; font-family: inherit; }}
.search-box:focus {{ border-color: rgba(88,166,255,0.4); }}
.idx {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 18px 22px; margin: 16px 0 8px; }}
.idx h4 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text3); margin-bottom: 10px; }}
.idx ul {{ columns: 3; column-gap: 24px; list-style: none; padding: 0; margin: 0; }}
.idx li {{ font-size: 12.5px; margin-bottom: 5px; break-inside: avoid; }}
@media (max-width: 720px) {{ .idx ul {{ columns: 1; }} }}
.term {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; margin: 12px 0; }}
.term .ex, .term .where {{ font-size: 13px; border-radius: 7px; padding: 10px 14px; margin-top: 8px; }}
.term .ex {{ background: rgba(63,185,80,0.06); border: 1px solid rgba(63,185,80,0.22); color: var(--text2); }}
.term .where {{ background: rgba(88,166,255,0.06); border: 1px solid rgba(88,166,255,0.22); color: var(--text2); }}
.term .lbl {{ display: block; font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }}
.term .ex .lbl {{ color: var(--green); }}
.term .where .lbl {{ color: var(--accent); }}
.term .rel {{ font-size: 12.5px; color: var(--text3); margin-top: 10px; }}
.term.hidden {{ display: none; }}
.footer {{ text-align: center; padding: 24px; border-top: 1px solid var(--border); margin-top: 40px; }}
.footer p {{ font-size: 11px; color: var(--text3); margin: 0; }}
</style>
</head>
<body>

<div class="container">

<h1>Глоссарий эконометрических терминов</h1>
<p class="sub">Все термины Aurora AI Econometrica простыми словами: что это, пример из практики и где это встречается в приложении. Начните печатать, чтобы отфильтровать.</p>

<input type="text" class="search-box" id="gsearch" placeholder="Поиск термина…" oninput="filterTerms(this.value)" />

<div class="idx">
  <h4>Алфавитный указатель</h4>
  <ul>
{index_html}
  </ul>
</div>

{body_html}

<p style="margin-top:28px"><a href="interpretation.html">Интерпретация результатов →</a> · <a href="methodology.html">Методология MMM →</a> · <a href="features.html">Каталог функций →</a></p>

</div>

<div class="footer">
  <p>Aurora AI Econometrica · © 2026 ООО «Платформа Аврора» · auroraai.pro · глоссарий генерируется из единого источника</p>
</div>

<script>
function filterTerms(q) {{
  q = (q || '').trim().toLowerCase();
  document.querySelectorAll('.term').forEach(function (el) {{
    var txt = el.textContent.toLowerCase();
    el.classList.toggle('hidden', q.length >= 2 && txt.indexOf(q) === -1);
  }});
}}
</script>
</body>
</html>
"""
    OUT_HTML.write_text(html, encoding="utf-8")


def js_str(s: str) -> str:
    return (s.replace("\\", "\\\\").replace("'", "\\'")
             .replace("\n", "\\n").replace("\r", ""))


def write_js(terms):
    # long = what + (Где в Aurora, если есть) – in-app компоненты рендерят long+example+related
    entries = []
    for t in terms:
        long = t["what"]
        if t["where"]:
            long = f'{long}\n\nГде в Aurora: {t["where"]}'
        rel = ", ".join(f"'{r}'" for r in t["related"])
        entries.append(
            f"  {t['id']}: {{\n"
            f"    id: '{t['id']}',\n"
            f"    term: '{js_str(t['term'])}',\n"
            f"    short: '{js_str(t['short'])}',\n"
            f"    long: '{js_str(long)}',\n"
            f"    example: '{js_str(t['example'])}',\n"
            f"    related: [{rel}],\n"
            f"  }},"
        )
    body = "\n".join(entries)
    js = f"""/**
 * Aurora Econometrica – Glossary (GENERATED).
 *
 * НЕ редактировать вручную. Источник: docs/GLOSSARY_v2_1_0.md +
 * tools/build_glossary.py (LEGACY_ONLY). Пересборка:
 *   PYTHONUTF8=1 python tools/build_glossary.py
 *
 * Единый источник для: glossary.html (справка), этого модуля (in-app),
 * docs/glossary.json (поиск Ctrl+K). Закрывает «три расходящихся глоссария».
 *
 * Structure: term: {{ id, term, short, long, example, related: [] }}
 * Use:
 *   import {{ GLOSSARY, getTerm }} from '$lib/glossary';
 *   const t = getTerm('hill_saturation');
 */

/** @type {{Record<string, {{id: string, term: string, short: string, long: string, example: string, related: string[]}}>}} */
export const GLOSSARY = {{
{body}
}};

/**
 * Get term object by ID. Returns null if not found.
 * @param {{string}} termId
 * @returns {{object | null}}
 */
export function getTerm(termId) {{
  return GLOSSARY[termId] ?? null;
}}

/**
 * Get all terms as array (for search/listing UI).
 * @returns {{Array<object>}}
 */
export function getAllTerms() {{
  return Object.values(GLOSSARY);
}}

/**
 * Search terms by text query (in term name + short description).
 * @param {{string}} query
 * @returns {{Array<object>}}
 */
export function searchTerms(query) {{
  if (!query) return getAllTerms();
  const q = query.toLowerCase();
  const all = /** @type {{Array<{{id: string, term: string, short: string, long: string, example: string, related: string[]}}>}} */ (getAllTerms());
  return all.filter(
    (t) =>
      t.term.toLowerCase().includes(q) ||
      t.short.toLowerCase().includes(q)
  );
}}
"""
    OUT_JS.write_text(js, encoding="utf-8")


if __name__ == "__main__":
    build()
