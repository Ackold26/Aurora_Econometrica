# Report KPI Audit (v1.3.0)

**Date:** 2026-05-12
**Owner:** Маша маленькая
**Scope:** все money-bound тексты в отчётах HTML / PPTX / XLSX / DOCX.

## Цель

Для каждой секции отчёта в 4 форматах — определить:
1. Какой текст сейчас (v1.2).
2. Какая monetary версия (KPI=рубли).
3. Какая count версия (KPI=штуки + любой counted unit).
4. Какая Goal-Seek версия (когда task=inverse).

## HTML report — `sidecar/econometrica/aurora_html/`

### 14 секций (`sections.py` 1278 LOC)

| Секция | v1.2 текст (sample) | Monetary | Count | Goal-Seek версия |
|---|---|---|---|---|
| **cover** | «Отчёт MMM Optimizer» | Same | Same | «План достижения цели: X count_unit» |
| **summary** | «Marginal ROI последнего рубля Y×» | Same | «CPU предельного контакта Y ₽/count_unit» | «Требуемый бюджет: X ₽ для достижения цели Y» |
| **findings** | «Лидирует TV (ROI 2.3×)» | Same | «Лидирует TV (CPU 65 ₽/упак, vs маржа 80 ₽/упак)» | «При +X% бюджета цель достижима с P=Y%» |
| **divider** | — | — | — | — |
| **key** | «Ключевая метрика: ROI 1.5×» | Same | «Ключевая метрика: CPU 70 ₽/count_unit (vs ценность 120 ₽)» | «Δ требуемого бюджета: +X%» |
| **mroas** | «Marginal ROI: ...» | Same | «Marginal CPU: ...» | Не применимо (или показывается current state) |
| **share** | «Доля бюджета vs Доля эффекта» | Same | Same (% share — universal) | Same + plus «доля бюджета в plan» |
| **table** | Channel table с ROI columns | KPI-aware columns | CPU + count contribution columns | Plan-comparison table (current vs plan) |
| **timeline** | «Динамика по периодам (₽ выручки)» | Same | «Динамика по периодам (count_unit продаж)» | Forecast timeline до цели |
| **recommend** | «Перелить N ₽ из A в B → +M ₽ выручки» | Same | «Перелить N ₽ из A в B → +K count, CPU ↓» | «Реалистичность цели: P=Y%. Альтернативы: ...» |
| **method** | Methodology section | Same + add CPU calc paragraph if count | Add: «CPU = бюджет / прирост count; сравнение с value_per_count_unit» | Add: «Goal-seek: бисекция бюджета до достижения цели» |
| **sources** | Data sources list | Same | Same | Same |
| **glossary** | Glossary in footer | Add CPU, value_per_count_unit entries | Same | Add: goal-seek, safe corridor |
| **closing** | «© Aurora AI Econometrica» | Same | Same | Same |

### `interactive.py` (ECharts charts)

| Chart | v1.2 axis label | Monetary | Count |
|---|---|---|---|
| Бюджет vs Эффект share | «% бюджета», «Вклад, млн ₽» | Same | «% бюджета», «Вклад, K count_unit» |
| Timeline | «Продажи, ₽» | Same | «Продажи, count_unit» |
| Response curves | «Бюджет канала, ₽» / «Выручка, ₽» | Same | «Бюджет канала, ₽» / «Count_unit» |
| Sensitivity | «Δ Бюджет → Δ Выручка» | Same | «Δ Бюджет → Δ Count» + additional «Δ CPU» |

### `strings_ru.json` (i18n keys)

| Key | v1.2 | Расширение |
|---|---|---|
| `scqar.situation` | «За год вложили X млн ₽» | + `scqar.situation_count`: «За год получили X лидов / X упак продаж / X регистраций / etc.» |
| `findings_templates.f1_leader` | «Лидирует {channel} с ROI {roi}×» | + `f1_leader_unit`: «Лидирует {channel} с CPU {cpu} ₽/{unit}» |
| `findings_templates.f2_underperformer` | «Убыточный {channel} с ROI {roi}×» | + `f2_underperformer_unit`: «Убыточный {channel} (CPU {cpu} > ценности {value})» |
| `action_titles.cut_underperformer` | «Сократить убыточный канал» | Same |
| `action_titles.reallocate` | «Перебалансировать бюджет» | Same |
| `methodology.hill_short` | «Hill saturation: ...» | Same (math) |
| `methodology.roi_calc` | «ROI = выручка / затраты» | + `methodology.cpu_calc`: «CPU = затраты / count_unit» |

### `strings_en.json` — parity gate

Все новые ключи в `strings_ru.json` обязательно одновременно появляются в `strings_en.json`. CI test `test_locale_parity.py` проверяет.

## PPTX report — `sidecar/econometrica/aurora_pptx/`

### 13 слайдов (`builder.py` 2716 LOC)

| Слайд | v1.2 | Monetary | Count | Goal-Seek |
|---|---|---|---|---|
| 1 Cover | «MMM Optimizer Report» | Same | Same | «План достижения цели» |
| 2 Executive summary | «Выручка X ₽, ROI Y×» | Same | «Продажи X count, CPU Y ₽/count (vs ценность Z)» | «Требуемый бюджет: X ₽, P(hit)=Y%» |
| 3 Key insights | «Лидер: TV», «Underperformer: OOH» | Same | KPI-aware, CPU-based | Plan-vs-current insights |
| 4 Decomposition waterfall | «Декомпозиция продаж, млн ₽» | Same | «Декомпозиция продаж, K count» | Forward+plan side-by-side |
| 5 Channel ROI table | «ROI каналов» | Same | «CPU каналов» (вместо ROI column) | Plan reallocation table |
| 6 Share vs Effect | bar chart «бюджет vs эффект» | Same | Same | + plan layer |
| 7 Timeline | «Динамика продаж» | Same | Same | + forecast |
| 8 Saturation curves | Hill curves per канал | Same | Same | Same |
| 9 Recommendations | «Перелить N ₽ → +M ₽» | Same | «Перелить N ₽ → +K count» | «Для цели X требуется план: ...» |
| 10 Sensitivity | «Δ Budget → Δ Sales» | Same | + Δ CPU layer | + Δ to goal |
| 11 What-if scenarios | Bar charts | Same | Same | Plan vs alternatives |
| 12 Methodology | Bayesian intro | Same + CPU calc | Same + goal-seek explanation | + goal-seek section |
| 13 Glossary | Terms | + CPU, value_per_count_unit | Same | + goal seek, safe corridor |

### Goal-Seek dedicated template (NEW)

`templates/goal_seek_template.pptx` — 10 слайдов:
1. Cover «План достижения цели X».
2. Executive: цель X, требуемый бюджет Y ₽, P(hit)=Z%.
3. Распределение по каналам (plan).
4. Δ vs current allocation.
5. Sensitivity: P(hit) для различных бюджетов.
6. Risk corridor: safe zone vs extrapolation warning.
7. Альтернативные сценарии (если цель за corridor).
8. Methodology: бисекция + posterior bands.
9. Footnotes / disclaimers.
10. Glossary excerpt.

## XLSX report — `src-tauri/src/commands/report.rs` (Rust rust_xlsxwriter)

| Sheet | v1.2 | Monetary | Count | Goal-Seek |
|---|---|---|---|---|
| Cover | Title + top metric | Same | «Topcount metric» | «Plan achievement summary» |
| Channels | Channel × [ROI, share, contrib] | Same | + CPU column, + value comparison | + plan_budget column |
| Timeline | Period × media decomposition | Same | Same (in count units) | + forecast columns |
| Sensitivity | Slider data | Same | + CPU sensitivity | Plan sensitivity |
| Methodology | Notes | Same | + CPU explanation | + goal-seek explanation |

## DOCX report — sketched in `report.rs` (python-docx future)

| Section | v1.2 | Расширение |
|---|---|---|
| Executive summary | 1 paragraph | KPI-aware sentence templates |
| Findings | Top findings list | KPI-aware bullets |
| Recommendations | Action items | KPI-aware action verbs |

## План работ по форматам (Stage 3)

| Формат | Estimated effort | Notes |
|---|---|---|
| HTML | 2 дня | Jinja conditionals × 14 секций + interactive.py charts |
| PPTX | 2 дня | Conditional slide generation + goal_seek_template |
| XLSX | 1 день | Rust rust_xlsxwriter conditional + new CPU column |
| DOCX | 1 день | Templates rewrite |
| Strings (RU+EN parity) | 0.5 дня | New keys × parity gate |
| Tests | 0.5 дня | 16 snapshot tests (2 kpi × 4 format × 2 task) |

**Total: ~7 дней Stage 3 reports portion.** План v1.3.0 Stage 3 = 10 дней (optimize + reports вместе), reports = 7 / optimize = 3.

## Открытые вопросы

1. **Goal-Seek в PPTX — отдельный template или конструируется из Forward + extra slides?**
   - Decision: dedicated template (cleaner UX, проще maintain).

2. **DOCX — реализовать в Stage 3 или Phase B?**
   - Decision: minimal viable DOCX (executive summary only) в Stage 3.

3. **Generalized chart axis labels** — нужна общая util `format_axis_label(kpi_kind, unit_kind)` → return localized string.
   - Decision: add `sidecar/econometrica/utils/i18n_labels.py` helper в Stage 3.
