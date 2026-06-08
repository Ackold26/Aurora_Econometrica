# Инвентаризация потребителей ratio / MQS — ПЕРЕД единым селектором

**Дата:** 2026-06-07 · **Ветка:** master @ `73688f6` · **Статус:** карта (артефакт #1), до кода селектора
**Зачем:** honesty-баг нечестного ratio всплыл ТРИЖДЫ (MQS-score → insight-панель → письмо клиенту), несмотря на 2 точечных фикса. Автор структурно слеп к слою, который сам забыл. Поэтому ПЕРВЫЙ deliverable задачи — не селектор, а **доказанная полнотой карта всех N мест**, проверенная независимыми агентами. Селектор ценен ТОЛЬКО полнотой: если 90 % потребителей ходят через него, а N+1-й нет — он даёт ложное «готово» и N+1-й продолжает врать под прикрытием «единого источника».

---

## 0. Различение метрик (корень всех швов)

Похоже выглядят — РАЗНЫЕ по смыслу. Баг всегда в шве, где post-train дисплей читает оптимистичную pre-train метрику.

| # | Метрика | Поле данных | Значение (Кагоцел) | Где честна |
|---|---------|-------------|--------------------|------------|
| **A** | **post-train MQS** (cap по эффект. параметрам) | `diagnostics.mqs.score` + `.tier_label` + `.thinness_cap` | 70 «Хорошее» | везде после обучения |
| **B** | **post-train effective ratio** (obs / effective_params, posterior contraction) | `diagnostics.metrics.ratio` (= `diagnostics.mqs.ratio`) | **2.4** | везде после обучения; драйвит cap+вердикт |
| **C** | pre-train **media-ratio** (obs / назначенные колонки) | `validationHeaderMetrics.ratio` · `validationMetrics.ratio` · `detected.ratio` · `ratioCardData.ratio` | 4.4 | ТОЛЬКО на шаге Валидация (до обучения) |
| **D** | pre-train **MQS-прогноз** (эвристика готовности данных) | `computeValidationMetrics().mqs` (project-state.js) | — | ТОЛЬКО на Валидации |
| | (прозрачность) номинальный ratio | `diagnostics.metrics.ratio_nominal` | 4.4* | служебно, не для вердикта |

**Шов = post-train потребитель (A/B), по ошибке читающий C.** Именно так возникали 3 слоя. C/D — легитимны на своём экране и в карту селектора НЕ вливаются (иначе потеряют отдельный смысл) — но граница должна быть явной.

**Backend SSOT-производитель:** `sidecar/econometrica/utils/diagnostics.py::generate_diagnostics_summary` — единственный, кто считает A и B. `model_quality_score` (cap 50/70 по B) и `metrics.ratio` (=B) идут оттуда. Никаких альтернативных вычислителей ratio/MQS в рантайме нет.

---

## 1. Потребители POST-TRAIN MQS (A) — обязаны читать `diagnostics.mqs.score`

### Фронт (in-app экраны)
| Файл | Строки | Источник | Статус |
|------|--------|----------|--------|
| `MQSBadge.svelte` | 31, 49, 64 | `diagnostics.mqs` | ✓ честно |
| `ModelTrainingStep.svelte` | 47, 234–241, 293–295 | `diagnostics.mqs` | ✓ |
| `ExpertModelPanel.svelte` | 17–20, 118–127, 166–171 | `diagnostics.mqs` | ✓ |
| `ReportStep.svelte` | 175–178, 270, 358–360, 450–463, 819–825 | `diagnostics.mqs` | ✓ |
| `insights-rules.js::modelInsights` | 1120 | `d.mqs.score` | ✓ |
| `insights-rules.js::reportInsights` | 2064 | `mod.diagnostics.mqs.score` | ✓ |
| `comparison/ModelComparisonView.svelte` | 82, 116–118, 296–299 | `diagnostics(snap).mqs.score` | ✓ |

### Backend (КЛИЕНТСКИЙ deliverable — проверен ПЕРВЫМ)
| Файл | Строки | Источник | Статус |
|------|--------|----------|--------|
| `narrative_adapter.py::normalize_diagnostics` | 737–757 | `diag_src["mqs"]["score"]` / `tier_label` → `mqs_score`/`mqs_tier_label` | ✓ честный мост |
| `aurora_pptx/builder.py` | 255–256, 812–824, 1133, 1278–1283, 2338, 2393, 2769–2782 | `self.mqs_score` (← `diag["mqs_score"]`) | ✓ |
| `aurora_html/sections.py` | 405, 427–434, 574, 686–721, 1532–1577 | `diagnostics.mqs_score`/`mqs_tier_label` | ✓ |
| `aurora_html/strings_ru.json` | 32, 54–59 | шаблоны `{mqs}` | ✓ заполняются из A |

### Bulk / persistence
| Файл | Строки | Источник | Статус |
|------|--------|----------|--------|
| `tools/recompute_mqs.py` | 83–94 | `generate_diagnostics_summary(effective_params=eff)` | ✓ тот же SSOT (+F-PY1 sanitize) |
| `engines/modeler.py` | producer | `generate_diagnostics_summary(...)` | ✓ источник A/B |

**Вывод по A:** клиентский deliverable (PPTX/HTML) показывает MQS из честного backend-SSOT через единственный мост `_map_pipeline_to_builder_data`/`normalize_diagnostics`. Альтернативного вычисления MQS в отчётах НЕТ. Ratio в PPTX/HTML **не печатается вовсе** → нечестному *числу* ratio там негде всплыть. **НО см. находку F-DELIVERABLE-1 ниже** — отсутствие ratio-печати оборачивается обратной проблемой: честная оговорка о переобучении тоже не доходит.

---

## 1b. НАХОДКА F-DELIVERABLE-1 (verified) — асимметрия раскрытия в клиентском файле

**Severity: MEDIUM (disclosure-fidelity, INV-50-adjacent). НЕ дубль 3 слоёв нечестного ratio.**

Вскрыта независимым backend-агентом, **подтверждена на источнике** (narrative_adapter.py:706–772 + греп builder.py/sections.py — все `verdict` там КАНАЛЬНЫЕ, не модельный).

**Суть:** `generate_diagnostics_summary` производит честный `verdict` со строкой `⚠ Данных мало (Ratio 2.4:1 < 4:1) — высокий R² может быть артефактом переобучения` (diagnostics.py:186–190). Этот `verdict` (+ `metrics.ratio`, `mqs.thinness_cap`, `effective_parameters`) **роняется** мостом `_map_pipeline_to_builder_data`: отчётная схема `diagnostics` извлекает только `{mqs_score, mqs_tier_label, r_squared, mape_pct, r_hat_max, ess_min}`. Канальные вердикты доходят, модельный — нет.

**Эффект:** программа (MQSBadge/InsightsPanel) и сопроводительное **письмо** (ReportStep, фикс F-JS1) предупреждают о переобучении; формальный **PPTX/HTML/XLSX**, который клиент сохраняет, показывает «MQS 70 · Хорошее» + мягкое «можно опираться с учётом диагностики» — **без явной оговорки о тонких данных**. MQS честно капнут (70, не 86) — ложного числа нет — но защитная оговорка асимметрична: program ⊃ deliverable.

**НЕ путать со слоями 1–3:** там deliverable показывал ложный ratio 4.4; здесь число честное, отсутствует *раскрытие*. Это другой корень (drop на report-шве), фиксится отдельно от селектора.

**Фикс (отдельная задача, по решению Антона):** в `_map_pipeline_to_builder_data` добавить в отчётную `diagnostics` → `thinness_cap`, `ratio` (effective), `ratio_nominal`, и/или `verdict`; затем провести строку через PPTX (slide MQS/sources) + HTML (sources-card / methodology) + XLSX executive summary. Probe-доказуемо на pickle Кагоцела без GUI.

**ДОКАЗАНО НА БОЕВЫХ ВЫГРУЖЕННЫХ ФАЙЛАХ (probe, 2026-06-07, проект `…-0706-26`):**
| Артефакт | MQS показан | Оговорка переобучения (переобуч/данных мало/Ratio/артефакт) |
|---|---|---|
| `results/model-diagnostics.json` (источник на диске) | 70 «Хорошее», `thinness_cap=70`, `metrics.ratio=2.4` | ✅ ЕСТЬ в `verdict`: «⚠ Данных мало (Ratio 2.4:1 < 4:1) — высокий R² может быть артефактом переобучения» |
| `exports/*.html` | 24× | **0** |
| `exports/*.pptx` | 5× | **0** |
| `exports/*.xlsx` | 6× | **0** (4 матча = saturation/methodology, не оговорка) |

Вывод: честная оговорка существует у истока, но НЕ доходит ни до одного из трёх клиентских форматов. Асимметрия program ⊃ deliverable — не гипотеза, а факт на реальных файлах.

---

## 2. Потребители POST-TRAIN effective RATIO (B) — обязаны читать `diagnostics.metrics.ratio`

| Файл | Строки | Источник | Статус | Слой honesty-бага |
|------|--------|----------|--------|-------------------|
| `insights-rules.js::modelInsights` | 1111, 1126 (`isThin`) | `m.ratio` ?? ssotRatio(fallback) | ✓ фикс `6fd4540` | **слой 2** |
| `insights-rules.js::reportInsights` | 2058, 2087 (`isThin`) | `mod.diagnostics.metrics.ratio` ?? ssotRatio | ✓ фикс `6fd4540` | **слой 2** |
| `ReportStep.svelte` (письмо клиенту, `modelSummary` стр. 262) | 225–226 | `metrics.ratio` ?? `validationHeaderMetrics.ratio` | ✓ фикс `73688f6` F-JS1 | **слой 3 (deliverable!)** |
| `diagnostics.py` вердикт `thin_note` | 186–190 | считается по эффект. `ratio` (стр. 178) | ✓ честен у истока | — (backend) |
| MQS-score cap | `model_quality_score` 122–129 | эффект. `ratio` | ✓ фикс 2026-06-07 | **слой 1** |

**Все 3 фронт-потребителя B имеют fallback на C (`validationHeaderMetrics.ratio`/`ssotRatio`)** — допустим ТОЛЬКО когда backend не дал `metrics.ratio` (legacy-pickle). Это правильный приоритет, но именно этот fallback — место будущего рецидива, если кто-то добавит 4-го потребителя и забудет приоритет. ⇒ селектор.

---

## 3. ЛЕГИТИМНЫЕ pre-train потребители (C/D) — НЕ шов, в селектор НЕ вливать

| Файл | Строки | Метрика | Комментарий |
|------|--------|---------|-------------|
| `StepWrapper.svelte` | 39, 49–51 | C+D (`validationMetrics.ratio`/`.mqs`) | заголовок шага Валидация |
| `ValidateStepV13.svelte` | 638–720, 1100–1108 | C (`ratioCardData.ratio`, gating ≥2:1) | gate-логика до обучения |
| `RatioInfoCard.svelte` | prop `ratio` | C | dumb-компонент, монтируется ТОЛЬКО из ValidateStepV13 |
| `TrafficLight.svelte` | 154–157 | C (`detected.ratio`) | чип детекции |
| `ModeDerivedExplanation.svelte` | 113–115 | C (`validationMetrics.ratio`) | объяснение режима |
| `project-state.js::computeValidationMetrics` | 425–484 | D producer (`mqs` прогноз) | эвристика готовности |
| `InsightsPanel.svelte` | 300, 316 | C→fallback | читает `validationHeaderMetrics.ratio` и передаёт как `ssotRatio` (fallback) в model/reportInsights ✓ |

---

## 4. Вестигиальное / watch (не баг, кандидат на чистку при селекторе)

- `MQSBadge.svelte` принимает prop `ssotRatio` (передаётся из `ModelTrainingStep.svelte:295`), но **для отображения не используется** (стр. 49 `displayMqs = mqs`). Мёртвый prop — убрать вместе с селектором, чтобы исключить будущую путаницу «а что если подключат».

---

## 5. Дизайн селектора (после верификации карты)

Создать `src/lib/metric-views.js`:
- `mqsView(diagnostics)` → `{ score, tierLabel, thinnessCap }` из `diagnostics.mqs` (единственный пост-train источник A).
- `ratioView(diagnostics)` → `{ ratio, isThin, nominal, source }` из `diagnostics.metrics.ratio` (B), `isThin = ratio<4`, `source='effective'|'fallback'`; fallback на переданный pre-train ratio помечается `source='fallback'` явно.
- Все пост-train потребители §1–§2 переводятся на селектор. Pre-train §3 НЕ трогаются.
- Гейт-тест: для каждого пост-train потребителя — что он зовёт `*View`, а не сырое поле (греп-гард в vitest, ловит будущие сырые `metrics.ratio`/`mqs.score` в пост-train компонентах).

**Грань:** греп «всех мест» ловит существующие N, не будущий N+1. Поэтому селектор + анти-рецидив греп-гард, а не просто перевод.

---

## 6. Метод проверки (probe-first, дёшево)

Найдено грепом точных accessor'ов + чтением SSOT, БЕЗ GUI/ретрейна. Δ ROI и любые «дорогие» проверки доказуемы probe'ом на реальном pickle Кагоцела (`…-0706-26`, MQS 70) — стоячий актив, тянуться сразу.

**СЛЕДУЮЩИЙ ШАГ:** 2 независимых агента (фронт-дисплеи / backend-deliverable) проверяют ЭТУ карту на полноту вслепую → реконсиляция → только потом код селектора.
