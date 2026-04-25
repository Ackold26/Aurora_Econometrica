---
tags: [session, compressed]
type: session
updated: 2026-04-25
---

# Quick Reference

Tier-1 quality pass для PPTX/HTML/XLSX отчётов после live-test MMX 2021-2025 (TV-heavy FMCG, baseline 96.5% / media 3.5%). Внедрён **honest_narrative mode** который переключает leader story / pull quote / SCQAR / action titles на честную диагностику когда media < 10% от total — вместо misleading «Performance 58% продаж». Реальный AREA_STACKED chart в PPTX s08 заменил рисованные `_rect` placeholder. HTML SECTION_RENDERERS reordered под PPTX flow. Smart дивергенции — context-aware совет с tune/draws/target_accept.

**Topic:** report quality pass v1.0.13 session 2
**Key files:** `narrative_adapter.py`, `aurora_pptx/builder.py`, `aurora_pptx/charts.py`, `aurora_html/sections.py`, `aurora_html/builder.py`, `aurora_html/strings_ru.json`, `aurora_html/templates/layout.css`, `src-tauri/src/commands/report.rs`, `ConvergenceDashboard.svelte`, `modeler.py`, `docs/MATH_AUDIT_v1_3.md`
**Status:** SHIPPED commit `33269fe` (13 файлов, +745/-177). Антон делает live-test финальный round. Pending: Phase 0.5 ship.

## Learnings

### 1. honest_narrative mode — системный паттерн для baseline-dominated данных

**Проблема которую решает:** на TV-heavy FMCG (русский рынок) часто media-вклад в продажи микроскопический (3-7%), а baseline (organic, seasonality, brand равновесие) — 93-97%. Стандартные template strings типа «Performance обеспечивает 58% инкрементальных продаж» — **технически некорректны**: 58% это share среди media (39% от 21.5M, не от total 613M). Клиент прочитает «media драйвит продажи», когда реальность — «media работает плохо, нужна диагностика».

**Реализация:**
```python
# narrative_adapter.py::_derive_narrative_facts (новые ключи)
total_sales = float(decompose_data.get("total_sales") or 0)
baseline_val = float(decompose_data.get("baseline") or 0)
media_contrib_total = float(decompose_data.get("media_contribution") or total_contrib)
media_contrib_pct = (media_contrib_total / total_sales * 100) if total_sales > 0 else None
baseline_pct = (baseline_val / total_sales * 100) if total_sales > 0 else None
honest_narrative = media_contrib_pct is not None and media_contrib_pct < 10.0
```

**Где консьюмится:**
- `aurora_html/sections.py::render_at_a_glance` (5 findings: f1/f2/f3 переключаются)
- `aurora_html/sections.py::render_key_message` (pull quote 3.5% вместо 58%, title disclosing baseline)
- `aurora_pptx/builder.py::_build_at_a_glance_findings` (PPTX 5 findings)
- `aurora_pptx/builder.py::s05_key_message` (PPTX big number = media_pct)
- `aurora_pptx/builder.py::derive_action_headline` (все 4 slide_hint: timeline/mroas/portfolio/scqar)

**Threshold 10%:** эмпирический, основан на FMCG benchmarks (Robyn / Aurora 2024-2026 проекты). При media_pct < 10% optimization не вернёт прибыльность — disclosure лучше fake-confidence.

### 2. time_series propagation в PPTX builder

**Проблема:** PPTX s08 «Декомпозиция вкладов · Динамика» рисовал stacked area через `_rect()` примитивы (хардкод 13 фиктивных weeks + sinusoidal `math.sin()` modulation для красоты). Реальные данные не использовались. Existing `make_timeline_area()` в `charts.py` была — но не вызывалась.

**Решение:**
```python
# narrative_adapter.py::_map_pipeline_to_builder_data
ts = decompose_data.get("time_series")
if isinstance(ts, dict) and ts.get("dates") and ts.get("baseline"):
    data["time_series"] = {
        "dates": list(ts["dates"]),
        "baseline": [float(v) for v in ts["baseline"]],
        "channels": {str(name): [float(v) for v in vals]
                     for name, vals in (ts.get("channels") or {}).items()},
    }

# aurora_pptx/builder.py::__init__
self.time_series = self.data.get("time_series") or None

# aurora_pptx/builder.py::s08_action_timeline (новый блок)
if ts and ts.get("dates") and ts.get("baseline"):
    from .charts import make_timeline_area
    make_timeline_area(slide, x, y, w, h, dates=..., baseline=..., channel_series=...)
    return  # skip legacy preview rect
# else fallback на legacy Kagocel pilot bands
```

**Pattern:** `narrative_adapter` проброс raw decompose data → builder читает через `self.X`. Эту схему нужно использовать для всех будущих pipeline data в builders.

### 3. Cross-format channel name mismatch

**Проблема (HTML timeline):** в legend и chart показывался только Baseline. Причина: `self.channels` пришли через `_merge_channels` + `_normalize_channel_name` (имена нормализованы: «Performance Бюджет ДО НДС» → «Performance»). Но `time_series.channels` keys остались raw. JS `data.channels[name]` для name="Performance" возвращал undefined.

**Fix:**
```python
# aurora_html/builder.py
from econometrica.engines.narrative_adapter import _normalize_channel_name
raw_channels = ts.get("channels") or {}
ts_channels = {}
for raw_name, series in raw_channels.items():
    norm = _normalize_channel_name(raw_name) or raw_name
    ts_channels[norm] = series
```

**Why it bit:** PPTX и XLSX используют raw decompose data напрямую (не передают через `_merge_channels`), поэтому keys совпадают. HTML же использует `self.channels` (merged+normalized) для channel_order — отсюда mismatch. Если в будущем добавятся другие cross-format mappings — следить за consistency name normalization.

### 4. CSS findings-list grid auto-placement bug

**Проблема:** на скрине Антон видел support текст столбиком по одному слову («ROI / 0.4× / средневзвешенный / по / каналам»).

**Анализ:** `<li>` имеет `display: grid; grid-template-columns: 50px 1fr;`. В li три grid items: `::before` (counter), `.finding-headline`, `.finding-support`. Auto-placement раскидывал:
- ::before → row 1, col 1 (50px) ✓
- .finding-headline → row 1, col 2 (1fr) ✓
- .finding-support → **row 2, col 1 (50px wide)** ← support в узкой колонке → каждое слово на отдельной строке

**Fix:**
```css
.findings-list > li::before { grid-column: 1; grid-row: 1 / span 2; }
.finding-headline { grid-column: 2; }
.finding-support  { grid-column: 2; }
```

### 5. Sidecar Python module cache

**Проблема которая повторялась всю сессию:** после изменений в `.py` файлах (narrative_adapter, builder, sections) пересоздание PPTX/HTML давало старый narrative. Sidecar держит модули в памяти после import — `.py` hot-reload отсутствует.

**Solution для dev workflow:**
- Закрыть/открыть Aurora AI Econometrica окно (cold start sidecar)
- ИЛИ kill `python.exe` в Task Manager (Tauri watchdog респавнит за ~15s)

**Note:** Vite + Svelte hot-reload работает для frontend (CSS/JS). Rust dev — auto-rebuild через tauri dev. Только Python sidecar требует ручной restart.

## Decisions

### Removed «Q3-Q4 2026» / «к следующему периоду» (везде)
**Why:** Антон — «конкретный период не задача эконометрики, это вопрос дальнейшего планирования». Эконометрика выдаёт **аналитическую** рекомендацию (как улучшить аллокацию), а **когда** применять — решает медиа-планнер.

**Где удалено:**
- PPTX cover subtitle: «и рекомендации по оптимизации **на Q3-Q4 2026**» → «и рекомендации по оптимизации»
- PPTX SCQAR question (2 места): «перераспределить бюджет **на Q3-Q4 2026**» → без периода
- PPTX impact label: «ROAS **к Q3-Q4 2026**» → «Прогнозный ROAS»
- HTML recommendation template: «+X пп **к следующему периоду**.» → «+X пп.»
- HTML impact-period: «ROAS к следующему периоду» → «Прогнозный ROAS»

### «Не для распространения» → «Конфиденциально»
**Why:** Антон выбрал короткое + стандартное. Применено в 3 формах (PPTX builder.py, HTML strings_ru.json, XLSX report.rs).

### Cover kicker «MARKETING MIX MODEL REPORT» (без «QUARTERLY»)
**Why:** отчёт может быть не quarterly (annual / period-flexible). Применено в PPTX + HTML.

### HTML section reorder — recommend после key
**Why:** Антон — «раздел Рекомендация (10) поставь после главного вывода (3)». Логика: после ключевого вывода клиент сразу видит actionable рекомендацию, а потом погружается в детали (декомпозиция / mROAS / portfolio).

**Финальный order HTML (14 секций):**
1. Cover → 2. Findings → 3. KeyMessage → 4. **Recommend** → 5. Summary (SCQAR) → 6. Декомпозиция → 7. mROAS → 8. Share → 9. Table → 10. Timeline → 11. Method → 12. Sources → 13. Glossary → 14. Closing

### PPTX slide reorder — Executive Summary block consolidated
**Why:** ранее был разорван: slides 4 (Декомпозиция divider), 5 (Key message), 6-8 (Action chart/table/timeline), 9 (SCQAR — обратно к Executive). Антон — «исправь чтобы Executive шёл подряд».

**Финальный order PPTX:**
1. Cover → 2. TOC → 3. AtAGlance → **4. KeyMessage → 5. SCQAR** → 6. Декомпозиция divider → 7-9. ROI/Portfolio/Timeline → 10-16. Methodology/Data/Appendix

### Стиль заголовков — стараться в одну строку
**Why:** Антон — «писать в одну строку, если места достаточно. Когда нет — может быть 2 или даже 3».

**Решение:**
- Убран `max-width: 48ch` для `.action-title` (длинные titles больше не упираются в 48 символов)
- НЕ добавлен `nowrap+ellipsis` (хрупко, может обрезать важный текст)
- Укорочены templated strings: «{leader} обеспечивает X% инкрементальных продаж при Y% доли бюджета» (78 chars) → «{leader} - X% продаж при Y% бюджета» (39 chars)

### Декомпозиция divider — упрощение
**Why:** Антон — «многократное упоминание РАЗДЕЛ 05/08, огромная 05 — стилистически не повторяется в других разделах».

**Изменения:**
- Убрана декоративная «05» (180px font)
- Убран inline «Раздел 05 / 08» (дублировал kicker)
- Kicker «РАЗДЕЛ 05 / 08» → «АНАЛИЗ ВКЛАДОВ КАНАЛОВ»

### MQS card layout (PPTX slide 13)
**Why:** Антон — «70/100 поднять выше (по центру), отодвинуть 70 от / на расстояние равное / до 100».

**Решение:**
- «70» frame: x 0.95→0.45, y 0.50→0.30 (move up), `align=PP_ALIGN.RIGHT` (right-aligned внутри 2.0" frame, end at x=2.45)
- «/ 100» frame: x 2.70→2.55, y 1.35→1.10 (move up), w 1.2→1.5, left-aligned
- Gap «70 → /» ≈ 0.10", gap «/ → 100» ≈ 0.06" — близко к симметричным

## Pending

### Финальная приёмка отчётности (LIVE-TEST)
Антон делает раунды live-test, шлёт скрины с мелкими находками (тексты, тайпо, layout). Фиксь точечно. После приёмки — переходим в ship.

### Phase 0.5 — GH Release v1.0.13 (BLOCKED)
- `npm run tauri build` (sidecar exe rebuild check автоматически)
- git tag v1.0.13 + push
- gh release create v1.0.13 + upload installer
- Supabase update (app_versions) + latest.json в aurora-releases
- PASHE_IT.MD update для клиента

### XLSX полный hybrid push (~4-6h, post-ship)
Сейчас базовый pass: Inter font, Lora cover title 28pt, gold accent stripe, header gold underline (medium), Cover tab GOLD, Confidentiality «Конфиденциально». Что осталось:
- Tab colors всех 9 sheets → consistent navy DEEP_80 (сейчас разноцветные `0x3B82F6/8B5CF6/22C55E/F59E0B/14B8A6/0EA5E9/EC4899`)
- Conditional formatting heat-map для ROI колонок (зелёный/жёлтый/красный)
- Zebra striping (DEEP_20 каждая 2-я строка) на data sheets
- Number format `#,##0 "₽"` для money columns
- Print setup hybrid header/footer

### Phase 1.1 — Joint adstock+Hill MCMC estimation (~12-15h)
Сейчас adstock fixed-prior (geometric/weibull выбирается snr-grid pre-MCMC), Hill параметры — MCMC. Joint MCMC ускорит сходимость + улучшит posterior coverage. Детали в `Aurora_Econometrica_Math_Plan.md` (на Desktop).

### Phase 1.9 — Full posterior CI propagation (~8-10h)
В `compute_roi_verdict` сейчас CI placeholder для honest uncertainty disclosure. Полный пробро posterior 95% CI до decomposer/optimizer/verdict для UI display и reproducibility.

### Phase 2.9 — Pareto multi-objective optimizer (~12-15h)
Заменить SLSQP single-objective на Pareto front. Решит trivial allocation на TV-heavy data (concentration → optimizer не может улучшить → 0% delta). Pareto добавит ROI-floor + diversification objective + hidden constraint propagation.

### 5 documented findings post-fix v1.2 (~6-10h, individual fixes)
- **A2:** ROI thresholds recalibration на real data (нужно собрать 5+ моделей FMCG → откалибровать deep_loss/loss/breakeven thresholds vs текущих 0.5/0.8/1.0)
- **B2:** adstock schema documentation (текущий — geometric/weibull mix snr-selected, нет clean spec)
- **B4:** scenario controls (UI overrides для adstock decay в what-if, сейчас фиксированы из training)
- **C1:** modeler efficiency на тонких данных (n<30 точек — добавить OLS fallback с честным «CI недоступны», сейчас MCMC даёт wide CI)
- **C2:** padding UX (scenario.py single-period plan distribution, frontend hint)

## Files Modified (commit 33269fe)

```
docs/MATH_AUDIT_v1_3.md                                       (new file)
sidecar/econometrica/aurora_html/builder.py                   M
sidecar/econometrica/aurora_html/sections.py                  M
sidecar/econometrica/aurora_html/strings_ru.json              M
sidecar/econometrica/aurora_html/templates/layout.css         M
sidecar/econometrica/aurora_pptx/builder.py                   M
sidecar/econometrica/aurora_pptx/charts.py                    M
sidecar/econometrica/engines/modeler.py                       M
sidecar/econometrica/engines/narrative_adapter.py             M
sidecar/econometrica/engines/optimizer.py                     M (math audit carry-over)
sidecar/econometrica/engines/scenario.py                      M (math audit carry-over)
src-tauri/src/commands/report.rs                              M
src/lib/components/pipeline/ConvergenceDashboard.svelte       M
```

13 files changed, +745/-177.

## Setup & Config Changes

Не было config изменений в этой сессии — все правки в код.

Раньше в сессии (math audit phase) изменены:
- `vite.config.js` — порт 1420 → 5173 (HNS reservation issue)
- `src-tauri/tauri.conf.json` — host 127.0.0.1 explicit

## Errors & Workarounds

### 1. Sidecar Python module cache (повторяющаяся проблема)
**Symptom:** изменения в `.py` файлах не применялись после пересоздания PPTX/HTML.
**Root cause:** sidecar держит import'ы в памяти; `.py` hot-reload отсутствует.
**Workaround:** kill `python.exe` (или закрыть/открыть Aurora окно).

### 2. Port 5173 zombie от предыдущего vite
**Symptom:** `Error: Port 5173 is already in use`. Предыдущая попытка `npm run tauri dev > log 2>&1 &` улетела detached.
**Diagnose:** `netstat -ano | grep :5173` → нашёл PID 30388.
**Fix:** `Stop-Process -Id PID -Force` (PowerShell). Параллельно убить `python.exe` PID для sidecar.

### 3. Bash `taskkill /F /PID N` → MSYS2 path mangling
**Symptom:** `bash: ошибка: неправильный параметр '/F:/'` — MSYS2 интерпретирует `/F` как Unix path.
**Fix:** использовать PowerShell tool вместо Bash для kill: `Stop-Process -Id N -Force`.

### 4. PowerShell `$_` переменная mangled через Bash → `extglob.ProcessName`
**Symptom:** при PowerShell командах через Bash tool с `$_.ProcessName` — Bash превращает `$_.X` → `extglob.X`.
**Fix:** использовать PowerShell tool напрямую.

### 5. tauri dev — exit code 0 но процесс не остаётся
**Symptom:** `npm run tauri dev > log 2>&1 &` exit 0 — но `tasklist` не показывает процессы.
**Root cause:** npm run обёртка exit'ает после spawn child, который ловится в shell и detach не работает корректно через Bash `&`.
**Fix:** использовать `run_in_background: true` параметр Bash tool (правильный detach через Tauri runtime).

### 6. Background tauri dev завершился неожиданно (live-test interruption)
**Pattern:** task notifications с status `completed` exit code 0 от долгоживущих tauri dev — это **Антон закрыл окно**, не реальная ошибка. Всегда проверять `tail -50 log` чтобы убедиться, что нет panic/error в выводе.

## Full Session Notes

### Sequence of fixes (chronological)

1. **Bug найден:** PPTX/HTML экспорт падал с «No module named 'econometrica'» в dev mode. `aurora_pptx/builder.py:40` и `aurora_html/builder.py:28` делали `from econometrica.engines.narrative_adapter import...` — работает только в bundled exe (PyInstaller настраивает `econometrica` как root package), но не в dev (cwd=`sidecar/econometrica`, `econometrica` не пакет).

   **Fix:** try-cascade pattern:
   ```python
   try:
       from econometrica.engines.narrative_adapter import compute_report_id
   except ImportError:
       from engines.narrative_adapter import compute_report_id
   ```

2. **Reorder PPTX slides:** Executive Summary block был разорван (slides 5 KeyMessage и 9 SCQAR между 4 Декомпозиция divider и 6-8 actions).

   **New order:**
   - `build()` функция: cover → toc → at_a_glance → **key_message → scqar** → divider → action_chart/table/timeline → methodology → ...
   - Updated `slide_to_section` map в `__init__`
   - Updated `toc_page_refs = [3, 6, 10, 12, 14]` (was [3, 4, ...])
   - Updated `slide_num=N` в `_header()` для каждого method (s05_key_message 5→4, s09_scqar 9→5, s04_section_divider 4→6, s06 6→7, s07 7→8, s08 8→9)
   - Updated `_footer(slide, N)` — 5×

3. **Real time_series chart в PPTX s08:** заменил `weeks=13; for w_idx: self._rect(...)` на native `make_timeline_area()` с реальным `self.time_series`. Subtitle с реальным периодом из `dates[0]-dates[-1]`. Trim top-5 channels by contribution для legend readability.

4. **honest_narrative mode:** добавил флаг + 3 ключа (media_contribution_pct, baseline_pct, total_sales) в `_derive_narrative_facts`. Передал `decompose_data` в caller. Применил в:
   - HTML render_at_a_glance (5 findings f1/f2/f3 переключаются)
   - HTML render_key_message (pull quote 3.5%)
   - PPTX `_build_at_a_glance_findings` (5 findings)
   - PPTX `s05_key_message` (pull quote 3.5%)
   - `derive_action_headline` для всех 4 slide_hint

5. **Smart дивергенции:** добавил `diagnostics.metrics.mcmc {chains, draws, tune, target_accept}` в modeler.py. ConvergenceDashboard.svelte читает и даёт context-aware совет вместо хардкод «Tune 4000-6000».

6. **HTML CSS fixes:**
   - findings-list grid: explicit `grid-column: 1; grid-row: 1 / span 2` для ::before; `grid-column: 2` для headline+support (auto-placement баг с support в узкой колонке)
   - cover layout: убран `min-height: 60vh`, flex column + gap (компактнее)
   - action-title: убран `max-width: 48ch` (длинные не переносятся)
   - closing-statement: `white-space: nowrap` (одна строка)

7. **HTML SECTION_RENDERERS final order:**
   ```python
   ('cover', render_cover),
   ('findings', render_at_a_glance),    # was after summary
   ('key', render_key_message),
   ('recommend', render_recommendation), # moved from position 10
   ('summary', render_executive_summary), # moved after key
   ('divider', render_section_divider),
   ('mroas', render_mroas),
   ('share', render_share),
   ('table', render_action_table),
   ('timeline', render_timeline),
   ('method', render_methodology),
   ('sources', render_sources),
   ('glossary', render_glossary),
   ('closing', render_closing),
   ```

8. **Декомпозиция divider упрощение:**
   - Убрано: декоративная «05» (180px font), inline «Раздел 05 / 08»
   - Kicker «РАЗДЕЛ 05 / 08» → «АНАЛИЗ ВКЛАДОВ КАНАЛОВ»
   - Body: только action-title + sacred-lime + italic takeaway

9. **Brand consistency:**
   - Cover kicker «MARKETING MIX MODEL REPORT» (без QUARTERLY) — PPTX + HTML
   - Footer «© 2026 Aurora AI. Конфиденциально» — PPTX + HTML + XLSX
   - Удалены «Q3-Q4 2026» и «к следующему периоду» — PPTX + HTML (5 мест)
   - f1_leader template укорочен (78 → 39 chars) — HTML strings_ru.json

10. **PPTX timeline chart formatting (charts.py):**
    - Compact dates `2021-10-01` → `10.21` (5 chars vs 10)
    - Y-axis Excel format `0,, "М"` (25M → «25 М»)
    - Axis tick font 10 → 8pt
    - Legend font 10 → 9pt
    - Channel name truncation: split по `\n` (для «Performance Бюджет\nДО НДС» → «Performance Бюджет»), max 22 chars

11. **PPTX MQS card (s11) layout:**
    - «70» x 0.95→0.45, y 0.50→0.30, `align=PP_ALIGN.RIGHT`
    - «/ 100» x 2.70→2.55, y 1.35→1.10, w 1.2→1.5

12. **HTML timeline channel mismatch fix:** `ts_channels` keys нормализуются через `_normalize_channel_name` (matches `self.channels` post-merge names).

13. **XLSX базовый hybrid pass:**
    - Font Arial → Inter
    - Cover title Lora 28pt + gold accent stripe row (4pt)
    - Cover tab GOLD (DEEP_80 для остальных post-ship)
    - Header bottom-border thin grey → medium GOLD
    - Confidentiality «Конфиденциально»

### Live-test progression

- **Datasets tested:** Kagocel (TV-heavy), Venarus (TV-heavy), MMX 2021-2025 (TV-heavy + 4 каналов)
- **Math reactive PASS** на всех (verified ранее в Phase 0.1)
- **Honest narrative PASS** на MMX (media_contribution_pct = 21.5M / 613.6M * 100 = 3.50% → honest mode triggered)
- **Optimizer trivial allocation на MMX** — physical SLSQP limitation (TV-concentration), не bug. Phase 2.9 Pareto multi-objective post-ship решит.

### Commit info

```
HEAD: 33269fe
Branch: math-fix-v1.0.13
Author: Антон + Маша (Claude Opus 4.7 1M)
Files: 13
Stats: +745/-177
Pre-commit hook: V40 lint OK (0.79s)
Tag: not yet (waiting for ship)
```

### Active scheduled work after ship

```
Aurora_Econometrica_Math_Plan.md (на Desktop) — master plan
docs/MATH_AUDIT_v1_3.md — cross-engine propagation findings
project_econometrica_v1013_report_quality.md — этот session memory
project_econometrica_math_audit.md — Phases 1-7 history
project_econometrica_phase0_roi_recalibration.md — verdict logic
```
