# Aurora AI Econometrica MMM Optimizer — План рефактора v1.3.0

**Дата начала плана:** 2026-05-12
**База:** v1.2.0 (tag `d383636` на `math-fix-v1.0.13`)
**Тип релиза:** minor (v1.2.0 → v1.3.0), hotfix в текущей кодовой базе. НЕ Phase B migration на Platform Core.
**Owner:** Маша маленькая, ревью Антон.

---

## Цели релиза

1. **Закрыть методологическую дыру** mode-aware UX на шагах Модель / Декомпозиция / Оптимизация / Отчёт.
2. **Добавить дуальный режим оптимизации** Goal-Seek (оптимизация от цели продаж → требуемый бюджет).
3. **Закрепить научно валидные коридоры** бюджета и цели.
4. **Расширить формы отчётов** для goal-seek сценария.

---

## Матрица 4 базовых режимов (anchor для всех P0.X разделов)

Две независимые оси параметризации:
- **mode** ∈ { ROI (все каналы → ₽-бюджеты), Эффективность (все каналы → физ. контакты) } — **derived state** (см. P0.9). Mode выводится автоматически по тому, какую input metric юзер выбрал per канал на шаге Импорт. Не explicit toggle.
- **kpi_kind** ∈ { **monetary** (target = sales_rub / revenue / profit), **count** (target = sales_packs / leads / registrations / loyalty_cards / subscriptions / installs / любая другая считаемая метрика) }

= **4 базовых режима**: A, B, C, D. Когда per-channel input metrics неоднородны → derived_mode = «Вручную» (гибрид, mixed) — UI поведение совпадает с Эффективностью + opt-in CPM/CPC для cost-comparison.

**Generic value-per-unit:** для всех `count` KPI нужно поле `value_per_count_unit` — сколько ₽ для бизнеса стоит одна единица KPI. UI-label адаптируется per KPI type:

| count KPI | label поля | auto-suggest |
|---|---|---|
| sales_packs | «Маржа на упаковку, ₽» | margin = sales_rub × (1 − COGS_ratio) / sales_packs |
| leads | «Ценность лида, ₽» | CPL benchmark или LTV × CR_lead→sale |
| registrations | «Ценность регистрации, ₽» | LTV × CR_reg→active |
| loyalty_cards | «Ценность выданной карты, ₽» | avg_basket × frequency × retention_months |
| subscriptions | «MRR на подписку, ₽» | avg_subscription_price |
| custom | юзер задаёт label сам | manual |

| Ось | **A. ROI × Monetary** | **B. ROI × Count** | **C. Эффективность × Monetary** | **D. Эффективность × Count** |
|---|---|---|---|---|
| Семантика | Деньги → деньги | Деньги → штуки KPI | Контакты → деньги | Контакты → штуки KPI |
| **Главная метрика канала** | ROI = ₽ выручки / ₽ затрат | **CPU** = ₽ затрат / count_unit (+ count/₽ справочно) | Sales share % (вклад в выручку) | KPI share % (вклад в общий count) |
| Cross-channel сравнимая | Да (безразмерен) | Да (₽/count_unit для всех каналов) | Только через share % | Только через share % |
| mEffect native units | — | — | ₽/контакт справочно | count_unit/контакт справочно |
| Эталон сравнения | ROI vs 1.0 (окупаемость) | CPU vs **value_per_count_unit** | sales share vs медиана | KPI share vs медиана |
| Вердикты «убыточный» | ROI пороги (0.5 / 0.8 / 1.0) | CPU vs value_per_count_unit (×2 / ×1 / ≈) | НЕТ окупаемости — только share (P25 / median / P75) | НЕТ окупаемости — только share |
| Светофор насыщения | По mROAS (₽/₽) | По mEffect (count/₽) | По mEffect (₽/контакт) | По mEffect (count/контакт) |
| Левая панель Декомпозиции | Расходы (₽) vs Эффект (₽) | Расходы (₽) vs Эффект (count) | Контакты vs Вклад (₽) per-channel | Контакты vs Вклад (count) per-channel |
| Unit-smell warning | Активен | Активен | **Отключён** | **Отключён** |
| Required input на Валидации | Бюджеты, sales_rub | Бюджеты, target count колонка, **value_per_count_unit (auto-suggest или manual)** | Контакты, sales_rub | Контакты, target count колонка, value_per_count_unit |
| Инсайты-плашки | «Лучший ROI: X», «Убыточный: Y», «эффективнее своей доли бюджета» | «Самый дешёвый: CPU Y ₽/count», «Дороже ценности: Z» | «Самый большой вклад: X — Y% продаж», «Слабый вклад» — БЕЗ упоминания бюджета | Аналогично C, в count_unit |
| Optimize forward | Слайдер бюджета (₽) → max выручка (₽) | Слайдер бюджета (₽) → max count | Слайдеры контактов (native, per канал) → max выручка | Слайдеры контактов → max count |
| Optimize goal-seek | Цель (₽) → требуемый бюджет (₽) | Цель (count) → требуемый бюджет (₽) | Цель (₽) → требуемые контакты per канал | Цель (count) → требуемые контакты per канал |
| Cover отчёта | «Выручка X ₽. ROI Y×» | «KPI X count_unit. CPU Y ₽/count (vs ценность Z)» | «Продажи X ₽. Топ-канал Z (Y%)» | «KPI X count_unit. Топ-канал Z (Y%)» |
| Топ-3 драйверы | по ROI | по CPU (низший = лучший) | по доле в продажах | по доле в KPI |
| Рекомендации | «Перелить N ₽ из A в B → +M ₽» | «Перелить N ₽ из A в B → +K count, CPU ↓» | «Увеличить контакты A на P% → +M ₽» | «Увеличить контакты A на P% → +K count» |
| Sensitivity слайдеры | 1: бюджет → выручка | 2: бюджет → count + бюджет → CPU | per-channel: контакты → выручка | per-channel: контакты → count |
| Cross-channel cost opt-in | N/A | N/A | **Да**: кнопка «Добавить CPM/CPC/CPP» → Вручную | **Да**: то же |

### Применение матрицы

- **P0.6 verdicts**: рендеринг текстов вердиктов = lookup `verdict_table[mode][kpi_kind][threshold]`.
- **P0.7 отчёты**: 4 conditional ветки в template = (mode, kpi_kind) pair. Не 4 копии файлов.
- **P0.8 Эффективность**: режимы C+D полностью без ROI/CPU колонок, share-based UI.
- **P0.2 inverse solver**: 4 разных signature функции (input/output dimensions). Общий solver core с диспатчем по (mode, kpi_kind).
- **Mode Вручную**: per-channel выбор (`channel.mode`), kpi_kind = один на проект. UI смешанный.

---

## P0 — Goal-Seek Mode (новая фича)

### P0.1 — Математический коридор бюджета и цели

**Проблема:** сейчас слайдер бюджета можно сдвинуть на +500%. Hill saturation параметры экстраполируются далеко за наблюдаемые значения. Posterior predictive CI расширяется кратно, рекомендации теряют валидность.

**Решение MVP (per-channel safe bounds):**
```
X_i^lo = max(P5(X_i_observed), 0.5 · µ_i)
X_i^hi = min(P95(X_i_observed), 1.5 · µ_i)
```

**Решение Expert Mode (posterior-based):**
- Sample M=1000 бюджетных распределений из истории + bootstrap.
- Compute predicted_sales через posterior MCMC.
- Bounds = [P5(predicted_sales), P95(predicted_sales)].

**Литература для ADR (нужен lit review до финализа):**
- Robyn (Meta) — default `0.5×–1.5×` от average channel spend.
- PyMC-Marketing — posterior predictive bounds для extrapolation.
- Hanssens, Parsons, Schultz (2003) "Market Response Models" — RMSE экстраполяции растёт 2–3× за observed range.
- Jin et al. (2017) "Bayesian Methods for Media Mix Modeling with Carryover and Shape Effects" — Hill curve identifiability.

**ADR:** `docs/adrs/ADR-014_safe_corridor_bounds.md` — формула + обоснование + ссылки.

**Файлы:**
- `sidecar/econometrica/optimize/bounds.py` — NEW. `compute_safe_corridor(model, mode='mvp'|'posterior')` → `{X_lo, X_hi, S_lo, S_hi}`.
- `sidecar/econometrica/server.py` — добавить endpoint `POST /optimize/corridor`.
- `src-tauri/src/commands/optimize.rs` — wrapper `get_safe_corridor`.

### P0.2 — Inverse оптимизация (Goal-Seek solver)

**Forward (текущий):** `argmax_X { Σ β_i · f(X_i) }` при `Σ X_i ≤ B`.

**Inverse (новый):** `argmin_X { Σ X_i }` при `Σ β_i · f(X_i) ≥ S_target`.

**Solver:** SLSQP (scipy) + multi-start (M=10 random init points для невыпуклой Hill). Уже используется в forward — переиспользуем с переключёнными objective/constraint.

**Posterior uncertainty:** inverse шире чем forward — посчитать через posterior samples (для каждого MCMC draw решить inverse, собрать distribution).

**Outputs:**
```python
{
  "achievable": bool,
  "distribution": {channel: budget},  # точечная оценка (P50)
  "total_budget": {p10, p50, p90},     # distribution
  "delta_vs_current": float,           # %
  "fallback_max_sales": float,         # если недостижимо — потолок при X_i = X_i^hi
  "channel_confidence": {channel: {p10, p50, p90}}
}
```

**Файлы:**
- `sidecar/econometrica/optimize/inverse.py` — NEW. `optimize_inverse(model, target_sales, constraints?)`.
- `sidecar/econometrica/optimize/forward.py` — REFACTOR, выделить общий solver core.
- `sidecar/econometrica/server.py` — endpoint `POST /optimize/inverse`.
- `src-tauri/src/commands/optimize.rs` — `run_inverse_optimization`.

### P0.3 — Авто-вычисление цены за упаковку

**Логика:**
```
price_per_pack = sales_rub / sales_packs  (per-period)
mean_price = trimmed_mean(prices, trim=0.1)
cv = std(prices) / mean_price
if cv > 0.20: warn "цена нестабильна (CV={cv:.1%}), возможно промо/SKU-mix"
```

**UI:**
- Карточка «Обнаружена цена: X ₽/упаковка (на основе Y периодов)». 
- Поле для override + чекбокс «использовать вычисленную автоматически».
- Если `sales_packs` колонка отсутствует — режим «упаковки» в goal-seek прячется.

**Файлы:**
- `src-tauri/src/commands/validate.rs` — добавить `detect_price_per_pack(project)`.
- `src/lib/components/PriceConfirmation.svelte` — NEW component.
- `src/routes/cabinet/+page.svelte` — встроить в шаг Валидация.

### P0.4 — UI шага Оптимизация (toggle + слайдеры)

**Toggle вверху:** `( ) Оптимизировать от бюджета  (•) Оптимизировать от цели`

**Режим "от цели":**
1. Слайдер цели с зонами:
   - 🟢 Зелёная зона `[S_lo, S_hi]` — модель валидна.
   - 🟡 Жёлтая зона `±10% от границ` — extrapolation warning.
   - 🔴 Красная — кнопка blocked.
2. Выбор валюты цели: ₽ / упаковки (упаковки прячутся если price отсутствует).
3. Опциональный слайдер max budget cap.
4. Кнопка «Найти решение» → solver → результат.
5. Карточка результата:
   - Главная цифра: «Требуемый бюджет: X ₽ ± CI».
   - Распределение по каналам (bar chart).
   - Δ vs current (%).
   - Probability of hitting target (на posterior samples).
   - Fallback message если недостижимо.

**Режим "от бюджета" (текущий):**
- Сохраняется.
- **Добавить визуализацию коридора** на слайдере total budget (вертикальные линии S_lo / S_hi).
- Warning при выходе за коридор.

**Файлы:**
- `src/routes/cabinet/+page.svelte` — рефактор шага Оптимизация.
- `src/lib/components/OptimizeGoalSeek.svelte` — NEW.
- `src/lib/components/OptimizeBudget.svelte` — выделить текущий UI как компонент.
- `src/lib/components/CorridorSlider.svelte` — NEW reusable.

### P0.5 — Новые формы отчётов для Goal-Seek

**Template:** `sidecar/econometrica/report/templates/goal_seek_plan.report.yaml` — NEW.

**Секции отчёта Goal-Seek (отличаются от стандартного):**
1. **Executive Summary**: «Для достижения цели X ₽ выручки требуется бюджет Y ₽ (Δ Z%)».
2. **Целевой план**: распределение по каналам, прогноз продаж, confidence intervals.
3. **Сценарии чувствительности**: «что если цель −10% / +10%».
4. **Достижимость**: probability of hitting target, ширина CI.
5. **Ограничения и предположения**: коридоры, период обучения, метрики качества модели.
6. **Альтернативные сценарии**: если бюджет ограничен — fallback цель.

**Форматы:**
- HTML (drill-down, what-if слайдер на цель).
- PPTX (новый template ~10 слайдов).
- XLSX (cover + детали по каналам + sensitivity).
- DOCX (executive summary).

**Файлы:**
- `sidecar/econometrica/aurora_html/templates/goal_seek.html` — NEW.
- `sidecar/econometrica/aurora_pptx/templates/goal_seek_template.pptx` — NEW.
- `sidecar/econometrica/aurora_xlsx/builders/goal_seek_builder.py` — NEW.
- `sidecar/econometrica/aurora_docx/templates/goal_seek_executive.docx` — NEW.
- `src-tauri/src/commands/report.rs` — wire новый template.

### P0.6 — Полный аудит KPI-семантики всех user-facing текстов

**Расширено 2026-05-12:** не только вердикты декомпозиции, а **все** комментарии и метрики в UI + отчётах должны быть KPI-aware. В unit-based KPI давать **альтернативные метрики** (например, обратная метрика CPU = ₽ / упаковку — интуитивнее, чем «отдача», сравнима с маржой продукта).

**Проблема (выявлено 2026-05-12 на скрине шага Декомпозиция):** функция `compute_roi_verdict` в `sidecar/econometrica/engines/decomposer.py:110` генерирует тексты «Глубоко убыточный», «Убыточный», «На грани окупаемости», «(широкий ROI-интервал)» — все money-bound термины (loss / окупаемость = денежная семантика). Они корректны когда KPI = `sales_rub` (продажи в рублях), но **некорректны** когда KPI = `sales_packs` (продажи в упаковках) или `awareness` (доля знающих).

Текущее состояние:
- `kpi_registry.py:77-99` имеет `sales` (money) + `awareness` (proportion). **Нет `sales_units`.**
- `ROI_THRESHOLDS.md:30` упоминает `unit_smell` — детектит inflated ROI на physical metrics, но решает через warning, не через смену семантики вердикта.
- Все 4-step decision flow в `decomposer.py:_apply_ci_suffix` + `compute_roi_verdict` хардкодит money-bound тексты.

**Решение — бинарное разделение KPI:**

Два типа комментариев и метрик: **«рубли»** (`kpi_kind=monetary`) и **«штуки»** (`kpi_kind=unit`). Awareness и прочие proportional KPI — вне scope v1.3.0 (отдельный workstream Brand Tracker).

1. **Расширить KPI registry** новым KPI `sales_units`:
   - Likelihood = normal (как sales).
   - Ceiling = None (количество упаковок ограничено только demand, не математикой).
   - `kpi_kind = 'unit'`.

2. **Добавить поле `kpi_kind`** в `KPIConfig`:
   - `'monetary'` — деньги. KPI: `sales` (sales_rub).
   - `'unit'` — штуки. KPI: `sales_units` (sales_packs).

3. **Главная метрика per kpi_kind:**

   | kpi_kind | Прямая метрика | Обратная метрика | Когда показывать обе |
   |---|---|---|---|
   | monetary | **ROI** = ₽ выручки / ₽ затрат | CPRub = ₽ затрат / ₽ выручки (редко нужна) | Только ROI в основной таблице |
   | unit | **Отдача** = упаковок / ₽ затрат | **CPU** = ₽ затрат / упаковку | Обе колонки. CPU интуитивнее, сравнима с маржой продукта |

   **Главная цифра для unit KPI = CPU**, потому что юзер мгновенно сравнивает с маржой («моя маржа 80 ₽/упак, канал даёт 120 ₽/упак — убыточно»).

4. **Verdict tables (бинарно):**

   | Условие | KPI=рубли | KPI=штуки |
   |---|---|---|
   | ROI < 0.5 / CPU > 2×margin | Глубоко убыточный | Глубоко убыточный (затраты на упаковку выше маржи в 2 раза) |
   | ROI < 0.8 / CPU > margin | Убыточный | Убыточный (CPU выше маржи) |
   | ROI < 1.0 / CPU ≈ margin | На грани окупаемости | На грани окупаемости (CPU близко к марже) |
   | ROI > 50 + unit_smell | ROI завышен (не рубли?) | CPU подозрительно низкий (проверьте единицы канала) |
   | ROI > 100 | ROI нереалистичен (артефакт) | CPU нереалистичен (артефакт) |
   | wide CI | (широкий ROI-интервал) | (широкий интервал CPU) |

   **Семантика «убыточный» сохраняется для KPI=штуки**, но измеряется через CPU vs маржу (а не ROI vs 1.0). Антон прав: для unit KPI это всё ещё про окупаемость, просто метрика другая. Главное — **юзер видит CPU и сравнивает с маржой**, а не ROI=«1 рубль → X штук», что бессмысленно.

5. **Маржа продукта — новое required поле** для KPI=штуки:
   - Поле «маржа на упаковку» (₽/упак) запрашивается на шаге Валидация одновременно с подтверждением цены.
   - Auto-suggest: если в данных есть `cogs_per_pack` или `gross_margin_%` — вычисляем.
   - Иначе — ручной ввод (default 30% маржи от цены).
   - Без маржи verdict для unit KPI не может различить «убыточный» / «окупаемый» — fallback на нейтральные тексты («высокая стоимость продажи», «низкая стоимость продажи»).

6. **UI label** в `DecomposeStep.svelte` — заголовки колонок:
   - KPI=рубли: «ROI» (одна колонка), вердикт.
   - KPI=штуки: «CPU, ₽/упак» (основная) + «Отдача, упак/₽» (вспомогательная), вердикт.

7. **Аудит всех user-facing текстов** (extended):
   - Вердикты декомпозиции — выше.
   - **Инсайты** (правая панель, скрин 2026-05-12 шаг Оптимизация: «Готово к оптимизации: 7 каналов, бюджет 5.8 млрд ₽, средний ROI 0.12×») — для KPI=штуки заменить на «средний CPU = X ₽/упак».
   - **Метрические тайлы** (СРЕДНИЙ ROI, СВЕТОФОР НАСЫЩЕНИЯ) — KPI-aware заголовки и единицы.
   - **Tooltips** в `command-meta.js` + inline-help.
   - **Tour-подсказки** (если используются) — две версии текстов.
   - **Отчёты HTML/PPTX/XLSX/DOCX** — section commentary KPI-aware (см. P0.5 + P1.3).
   - **Рекомендации оптимизации** — «перелейте бюджет в канал X для роста выручки» → «перелейте бюджет в канал X для роста продаж упаковок» / «снижения CPU».
   - **Error messages** — если упоминают «рубли» / «выручку», параметризовать.

8. **Edge case Вручную mode** — когда часть каналов в ₽, часть в контактах:
   - kpi_kind проекта (monetary/unit) — один на проект (зависит от что в `y_target`).
   - Per-channel input metric (₽ или контакты) — независимо. Vector mode UI.
   - Если канал на контактах, а KPI = sales_rub — это unit_smell, существующий warning сохраняется.

**Файлы:**
- `sidecar/econometrica/utils/kpi_registry.py` — добавить `sales_units` + поле `kpi_kind` в `KPIConfig`.
- `sidecar/econometrica/engines/decomposer.py` — рефакторинг `compute_roi_verdict` с lookup verdict_table[kpi_kind][threshold]; добавить расчёт CPU и сравнение с margin.
- `sidecar/econometrica/engines/optimizer.py` — KPI-aware рекомендации.
- `sidecar/econometrica/server.py` — endpoint для маржи (`POST /project/margin`).
- `docs/ROI_THRESHOLDS.md` — переименовать в `KPI_THRESHOLDS.md`, добавить обе таблицы (rub/units).
- `src/lib/components/pipeline/DecomposeStep.svelte` — label колонки + tone-aware tooltip + CPU колонка для unit KPI.
- `src/lib/components/pipeline/ExpertDecomposePanel.svelte` — то же.
- `src/lib/components/pipeline/InsightsPanel.svelte` — KPI-aware тексты инсайтов.
- `src/lib/components/PriceConfirmation.svelte` (NEW в P0.3) — расширить: запрашивать margin рядом с ценой.
- `src/lib/command-meta.js` — KPI-aware tooltips.
- `tools/test_roi_verdict.py` — параметризовать по kpi_kind, добавить тесты CPU.
- Полный grep `выручк|убыт|ROI|окуп|рубл|₽` по `src/` + `sidecar/aurora_html|aurora_pptx|aurora_xlsx|aurora_docx` — список user-facing мест в audit report.

**Зависимость:** P0.3 (авто-вычисление цены) расширяется: одновременно с ценой запрашивается **маржа на упаковку**. Без маржи verdict для unit KPI деградирует в нейтральные тексты.

**Аудит deliverable:** `KPI_TEXT_AUDIT.md` — таблица всех найденных текстов × где встречается × текущая формулировка × предлагаемая monetary версия × предлагаемая unit версия. Cmит контрибуцию ~50-100 строк.

**Оценка:** 4 рабочих дня (1 день grep-аудит → audit doc → 1.5 дня код verdict_table + CPU + margin field → 1 день UI правки label+tooltip+insights → 0.5 дня тесты).

**Связь с Goal-Seek:** в goal-seek режиме цель в упаковках = KPI sales_units. Вердикты декомпозиции должны соответствовать.

### P0.7 — KPI-aware секции отчётов (HTML / PPTX / XLSX / DOCX)

**Проблема:** все 4 формата отчётов сейчас построены вокруг ROI (cover слайд «средний ROI», ключевые таблицы в ₽ выручки, recommendations типа «канал X даёт 1.5× окупаемость»). Для KPI=штуки эти секции некорректны или малопонятны:
- «1.5× окупаемость в упаковках» — что это значит для CMO?
- График «вклад каналов в выручку, ₽» бессмысленен.
- Recommendation «увеличьте TV ради ROI» не работает — нужно «увеличьте TV ради продаж упаковок (CPU = X ₽/упак vs маржа Y ₽/упак)».

**Решение:** все 4 формата (HTML / PPTX / XLSX / DOCX) делают conditional rendering секций по `kpi_kind`. Единый template + ветка `{% if kpi_kind == 'monetary' %} ... {% else %} ... {% endif %}` (Jinja-style для Python генераторов, аналогично для PPTX через python-pptx).

**Секции и их KPI-aware варианты:**

| Секция | KPI=рубли | KPI=штуки |
|---|---|---|
| Cover / Executive Summary | «Выручка от рекламы: X ₽. Средний ROI: Y×» | «Продажи от рекламы: X упак. Средний CPU: Y ₽/упак (маржа Z ₽/упак)» |
| Вклад каналов | bar chart «вклад в выручку, ₽» | bar chart «вклад в продажи, упак» + таблица «CPU по каналам, ₽/упак» |
| Светофор насыщения | пороги по ROI | пороги по CPU vs маржа |
| Динамика по периодам | stacked area в ₽ выручки | stacked area в упаковках |
| Топ-3 драйверы | «ТВ даёт 25% выручки» | «ТВ даёт 25% продаж упаковок» |
| Рекомендации | «перелейте Y ₽ из канала А в канал B → +Z ₽ выручки» | «перелейте Y ₽ из канала А в канал B → +Z упаковок (CPU снизится с A до B ₽/упак)» |
| Sensitivity / What-if | слайдер «бюджет → выручка ₽» | слайдер «бюджет → продажи упак» + второй слайдер «бюджет → CPU ₽/упак» |
| Goal-Seek результат (P0.5) | «для роста выручки на X% нужен бюджет Y ₽» | «для роста продаж на X% упак нужен бюджет Y ₽ (CPU Z ₽/упак)» |
| Footer / методология | стандартный | стандартный + 1 параграф «расчёт CPU = бюджет / прирост продаж, сравнение с маржой Y ₽/упак» |

**Файлы (по форматам):**

- **HTML** (`sidecar/econometrica/aurora_html/`):
  - `templates/base.html` — Jinja conditionals по `kpi_kind`.
  - `builders/sections/decomposition.py` — KPI-aware bar charts.
  - `builders/sections/optimization.py` — KPI-aware рекомендации.
  - `builders/sections/sensitivity.py` — KPI-aware слайдеры (для unit — два).
  - `strings_ru.json` / `strings_en.json` — добавить `*_unit` ключи рядом с money.

- **PPTX** (`sidecar/econometrica/aurora_pptx/`):
  - `builder.py` — параметр `kpi_kind` в конструктор. Conditional `add_slide_xxx_monetary` / `add_slide_xxx_unit`.
  - `strings_ru.json` / `strings_en.json` — `*_unit` ключи (тот же подход что HTML).
  - `templates/cover.pptx` + `cover_unit.pptx` — два cover slide template если визуально радикально разные (иначе один с placeholder).

- **XLSX** (`sidecar/econometrica/aurora_xlsx/`):
  - `cover_builder.py` — KPI-aware top metric.
  - `channel_sheet_builder.py` — добавить колонку CPU для unit KPI.
  - `sensitivity_builder.py` — секция CPU vs margin.

- **DOCX** (`sidecar/econometrica/aurora_docx/`):
  - `executive_summary.py` — KPI-aware первый абзац.
  - `recommendations.py` — KPI-aware bullet списки.

**Тесты:**
- `tools/test_report_kpi_aware.py` — NEW. Параметризованные генерации по 2 kpi_kind × 4 формата = 8 базовых случаев + smoke на наличие правильных ключей в strings.
- `tools/test_report_visual_regression.py` — расширить existing snapshot test с двумя baseline'ами per format.

**Зависимости:**
- P0.6 (kpi_kind в registry + verdict tables + margin field).
- P0.5 (Goal-Seek templates) — конструируются параллельно: goal-seek для KPI=рубли и для KPI=штуки.
- P1.3 (mode-aware report templates) — третья ось параметризации.

**Decision matrix секций (3D):**

```
section(mode, task, kpi_kind) → rendered content
mode ∈ {ROI, Эффективность, Вручную}
task ∈ {forward, goal-seek}
kpi_kind ∈ {monetary, unit}
```

12 вариантов на секцию **через conditional logic**, не 12 копий файлов. Single source of truth — template + condition stack.

**Audit deliverable:** `REPORT_KPI_AUDIT.md` — таблица «секция × формат × текущая формулировка × monetary версия × unit версия». Парная с `KPI_TEXT_AUDIT.md` из P0.6, но фокус на отчёты.

**Оценка:** 5 рабочих дней (1 день аудит-таблица всех секций × форматов → 2 дня HTML+PPTX переделка → 1 день XLSX+DOCX → 1 день тесты + visual regression).

### P0.8 — Режим Эффективность: устранение money-bound артефактов

**Проблема (выявлено 2026-05-12 на скрине Декомпозиция режим Эффективность):**

В режиме Эффективность модель внутри работает корректно (физические метрики, нормированный Hill, sales contribution в ₽). Но **пост-обработка** считает ROI = sales_contribution / cost с дефолтным unit_cost=1, что выдаёт numeric artifacts (4172.72×, 59.47×, 0.10×). UI рендерит эти числа как ROI и генерирует невалидные вердикты + невалидные инсайты:

- Таблица: колонка ROI с абсурдными значениями + вердикт «ROI завышен (не рубли?)» / «Глубоко убыточный» на каждом канале.
- Левая панель «Расходы vs Эффект» — оси теряют смысл (расходов в ₽ нет).
- Инсайты: «эффективнее своей доли бюджета», «Лучший ROI: X — 4172×», «Убыточный канал: Y» — все ссылаются на ₽-семантику, которой нет.

Также — **unit_smell warning** ложно срабатывает на каждом канале, потому что в этом режиме его триггер (unit_cost=1 + ROI > 50) — нормальное состояние, а не аномалия.

### Решение

#### 1. Полное отключение ROI-семантики в Эффективность

- **Убрать колонку ROI** в таблице декомпозиции.
- **Заменить главной метрикой:** Sales contribution share (% вклада в общие продажи). Это **единственная безразмерная метрика, сравнимая между каналами с разными физ. единицами**.
- **Добавить колонку mEffect в native units** (per канал, не cross-channel):
  - Banners → «Y ₽ / 1000 показов».
  - OLV → «Y ₽ / 1000 показов».
  - Performance → «Y ₽ / клик».
  - TRPs → «Y ₽ / GRP».
  - Tooltip: «единицы разнотипны — прямое сравнение между каналами некорректно».

#### 2. Светофор насыщения — оставить

Hill saturation работает в любых единицах. Светофор «по mROAS каналов» переименовать в «**по mEffect каналов**» (mROAS — money-bound термин).

#### 3. Левая панель «Расходы vs Эффект» → «Контакты vs Вклад»

- Per-channel scatter: X = native units (показы/клики/GRP), Y = вклад в продажи (₽ или упак).
- НЕ cross-channel overlay (нельзя ставить разные масштабы на одну ось).
- Альтернатива: тumbnails per channel, не один общий график.

#### 4. Вердикты per канал

Заменить ROI-based на share-based:

| Условие (sales share) | Вердикт |
|---|---|
| share > P75(channels) | Топ-драйвер вклада |
| share > median | Значимый вклад |
| share < P25 | Слабый вклад |
| share < threshold (0.5%) | Пренебрежимо малый вклад |
| wide CI | (широкий интервал вклада) |

Плюс **не зависящий от ROI** вердикт по насыщению (тот же что и в monetary): «Перенасыщен», «Сбалансирован», «Недонасыщен» через Hill curve position.

#### 5. Инсайты panel — KPI/mode-aware (extended audit)

Текущие 8 инсайтов из скрина 2026-05-12, исправления для режима Эффективность:

| Текущее | Исправление |
|---|---|
| «Декомпозиция готова: 94% продаж — базовые, 6% — вклад рекламы» | Остаётся валидным |
| «Главный драйвер: Performance Клики (20% от медиа-вклада)» | Остаётся валидным |
| «Base sales = 94%. Медиа-эффект относительно слабый» | Остаётся валидным |
| «Топ-3 драйверы медиа-вклада (56%)» | Остаётся валидным |
| «4 канала работают эффективнее своей доли **бюджета**» | **УБРАТЬ полностью** в режиме Эффективность (бюджета нет) |
| «1 канал перенасыщен» | Остаётся валидным (Hill curve) |
| «Лучший ROI: TRPs бренд — 4172.72×» | **«Самый большой вклад: TRPs бренд (W 25-54) — X% продаж»** |
| «Убыточный канал: Banners Показы — ROI 0.10×» | **«Слабый вклад: Banners Показы — X% продаж при Y% объёма контактов»** + tooltip «контакты разнотипны» |

#### 6. Cross-channel сравнение — opt-in переход в Вручную

Когда юзер хочет «понять кто канал лучший» в Эффективности, default ответ — sales share. Но юзеру может быть нужна стоимость контакта.

UI: на шаге Декомпозиция в режиме Эффективность кнопка **«Добавить ценники контактов для cost-effectiveness анализа»** → переключает проект в режим Вручную, открывает диалог ввода CPM / CPC / CPP per канал. После ввода — virtual ROI считается, ROI колонка возвращается, но **с явной плашкой «оценено через юзер-введённые ценники, не из бюджетных данных»**.

#### 7. Отключить unit_smell warning в Эффективности

В `decomposer.py` `compute_roi_verdict` ROI > 50 + unit_smell триггер — должен быть **скип в режиме Эффективность** (unit-mismatch — состояние по определению, не аномалия). Только в режимах ROI и Вручную (где часть каналов на бюджете) warning сохраняется.

### Файлы

- `sidecar/econometrica/engines/decomposer.py` — параметр `mode` (roi/effectiveness/manual) в `compute_roi_verdict`, switch на share-based для effectiveness.
- `sidecar/econometrica/engines/insights.py` (если есть) или эквивалент — KPI/mode-aware текстов инсайтов.
- `src/lib/components/pipeline/DecomposeStep.svelte` — conditional рендеринг таблицы и левой панели.
- `src/lib/components/pipeline/InsightsPanel.svelte` — mode-aware insights.
- `src/lib/components/pipeline/UnitCostsDialog.svelte` — NEW. Диалог ввода CPM/CPC/CPP с переходом в Вручную.
- `tools/test_decomposer_effectiveness_mode.py` — NEW. Snapshot test что в Эффективности нет ROI колонки, нет «убыточный» вердиктов, нет ложных unit_smell warnings.

### Зависимости

- P0.6 (kpi_kind в registry + verdict tables): mode и kpi_kind — две независимые оси. В Эффективности есть оба варианта: KPI=рубли (нативно) или KPI=штуки. Вердикт-таблицы становятся 2×2 (mode × kpi_kind для основных текстов).
- P0.7 (отчёты): секции в режиме Эффективность также без ROI, с sales share как главной метрикой.

### Оценка

3 рабочих дня (1 день рефактор decomposer + insights backend → 1 день UI: таблица, инсайты, левая панель → 0.5 дня unit-costs dialog + переход в Вручную → 0.5 дня тесты + visual regression).

### P0.9 — Mode as derived state (rebuild Validate + Import UX)

**Решение Антона 2026-05-12 (Вариант C из Open Question #6):** mode становится **derived property** от per-channel input metrics, а не первичным выбором юзера. Совпадает с industry standard (Robyn, PyMC-Marketing, Lightweight MMM, Jin et al. 2017).

**ADR:** `docs/adrs/ADR-015_mode_as_derived_state.md` — NEW. Обоснование + decision matrix + migration path.

### Новый UX Валидации

**Текущее (v1.2.0):** карточки «ROI / Эффективность / Вручную» — первый вопрос на шаге Валидация.

**Новое (v1.3.0):**
- Шаг Валидация переименовывается в логически правильное «**Настройка модели**» (или сохранить «Валидация» — это технический термин для шага, но контент меняется).
- Первый вопрос: **«Что измеряем как итог?»** — выбор KPI (target):
  - 💰 **Выручка / прибыль** (KPI=monetary) → sales_rub.
  - 📦 **Продажи в штуках** (count) → sales_packs.
  - 🎯 **Лиды / заявки** (count) → leads.
  - 📝 **Регистрации / активации** (count) → registrations.
  - 💳 **Выданные карты / подписки** (count) → loyalty_cards / subscriptions.
  - ✍️ **Другое (custom)** — юзер задаёт label.
- Если KPI=count → подзапрос **value_per_count_unit** (см. P0.6 матрица label).
- НЕТ карточек ROI/Эффективность/Вручную как первого вопроса.

### Новый UX Импорта (или подэтап Валидации)

Per-channel input metric selector:

**Логика:**
1. Юзер загрузил Excel (или auto-mapping из P0.6/P0.3).
2. Для каждого обнаруженного канала система определяет **доступные единицы** (по названиям колонок и их значениям):
   - Колонка `tv_spend` / `tv_budget` / `тв_бюджет` → доступен `monetary` (₽).
   - Колонка `tv_grp` / `тв_grp` → доступен `physical` (GRP).
   - Колонка `olv_impressions` / `olv_показы` → `physical` (impressions).
   - И т.д.
3. UI таблица каналов:

| Канал | Доступные метрики | **Использовать** (selector) | Источник |
|---|---|---|---|
| TV | ₽ (1.2M), GRP (250) | ⦿ ₽ ○ GRP | твой выбор |
| OLV | ₽ (300K), показы (2.5M) | ○ ₽ ⦿ показы | твой выбор |
| Banners | показы (1.8M) | ⦿ показы | единственная доступна |
| Performance | ₽ (450K), клики (12K) | ⦿ ₽ ○ клики | твой выбор |
| TRPs бренд | GRP (180) | ⦿ GRP | единственная |
| Social | показы (920K) | ⦿ показы | единственная |
| Retail Media | ₽ (180K) | ⦿ ₽ | единственная |

4. Smart hints:
   - «У TV есть и ₽ и GRP — выберите более надёжную колонку (точные деньги или точные охваты?)».
   - «У OLV нет колонки с бюджетом — будем использовать показы».
   - «Все каналы имеют только ₽ → модель сразу в ROI-режиме».

5. **Mode derived** по результату:
   - `derived_mode = ROI` если все каналы выбрали `monetary` input.
   - `derived_mode = Эффективность` если все каналы выбрали `physical` input.
   - `derived_mode = Вручную` (mixed) если у части каналов `monetary`, у части `physical`.

6. **Plain-text объяснение** под таблицей:
   - «По вашему выбору модель будет работать в режиме **ROI** — все каналы оцениваются через денежные расходы».
   - «Режим **Эффективность** — все каналы оцениваются через физические контакты; для cost-comparison добавьте ценники контактов на отдельном шаге».
   - «**Смешанный режим** — TV/Performance в деньгах, OLV/Banners/PR в показах. Cross-channel сравнение через долю в продажах; для cost-comparison добавьте ценники контактов».

### Expert Mode override

Опционально: тогл «Я знаю, что делаю — переключить режим явно». При активации возвращается старый toggle ROI/Эффективность/Вручную. Скрыт по умолчанию в `Settings → Expert features`. Сценарий: senior эконометристы, привыкшие к v1.2.

### Backward compat .aurora v1.2 bundles

Старые проекты с явным `mode` field в bundle:
- При импорте `mode = 'roi'` → все каналы прогружаются как `monetary` input (derived_mode будет = ROI).
- При `mode = 'effectiveness'` → все каналы как `physical`.
- При `mode = 'manual'` → читаем per-channel input metric из bundle (старая Вручную сохраняла per-channel).
- Migration tool в `tools/migrate_v12_to_v13.py` — NEW.

### Onboarding и docs

- **Onboarding step 1** (`OnboardingOverlay.svelte`) — переписать описание: убрать «3 режима», добавить «гибкая модель учитывает любые типы данных».
- **Help docs** (`help-econometrica/`) — обновить страницы про режимы.
- **Pipeline.html** — обновить описание шагов.
- **Method ref** (`docs/MATH_REFERENCE.md`) — пометить mode как derived.

### Mode-aware UI на следующих шагах

Не меняется относительно матрицы 4 режимов из этого плана:
- Шаг Модель — параметры priors в native units per channel.
- Шаг Декомпозиция — UI по derived_mode (P0.6 и P0.8).
- Шаг Оптимизация — UI по derived_mode (P0.2 inverse + P0 mode-aware optimize).
- Отчёты — секции по derived_mode (P0.7).

Все эти разделы продолжают работать с матрицей 4 базовых режимов как lookup-table; меняется только **откуда берётся mode** (derived, не explicit).

### Файлы

- `src/lib/components/pipeline/ValidateStep.svelte` — REWRITE. Первый вопрос KPI, потом per-channel selector.
- `src/lib/components/pipeline/KPISelector.svelte` — NEW. 6 типов KPI + custom.
- `src/lib/components/pipeline/PerChannelInputSelector.svelte` — NEW. Таблица каналов с radio selector.
- `src/lib/components/pipeline/ModeDerivedExplanation.svelte` — NEW. Plain-text под таблицей.
- `src/lib/components/pipeline/ExpertModeToggle.svelte` — NEW. Override.
- `src/lib/components/OnboardingOverlay.svelte` — UPDATE step 1.
- `sidecar/econometrica/utils/mode_inference.py` — NEW. Logic `derive_mode(per_channel_inputs)`.
- `sidecar/econometrica/utils/column_detection.py` — NEW. Auto-detect доступные метрики из Excel.
- `sidecar/econometrica/utils/kpi_registry.py` — расширить (см. P0.6).
- `tools/migrate_v12_to_v13.py` — NEW. .aurora v1.2 → v1.3 schema.
- `docs/adrs/ADR-015_mode_as_derived_state.md` — NEW.
- `help-econometrica/methodology.html` — UPDATE.

### Тесты

- `tools/test_mode_inference.py` — NEW. Параметризованные тесты derive_mode для 4 базовых + edge cases (1 канал, 100 каналов, все одной единицы).
- `tools/test_column_detection.py` — NEW. Auto-detect разных названий колонок (русский / английский / mixed-case).
- `tools/test_v12_migration.py` — NEW. 3 baseline .aurora v1.2 проекта → v1.3 → проверка идентичности результатов.
- Regression: pilot test corpus (Кагоцел / Венарус) — derived mode совпадает с прежним явным выбором.

### Оценка

5 рабочих дней (1 день ADR-015 + auto-detect colums + mode_inference logic → 2 дня UI Валидация rebuild + KPI selector + per-channel selector → 1 день migration tool + backward compat → 1 день тесты + regression на baseline проектах).

---

## P0 — Mode-Aware Optimize (ROI / Эффективность / Вручную)

Параллельный поток к Goal-Seek. См. предыдущее обсуждение — три режима на шаге Валидация задают, как именно считается оптимизация:

| Режим | Forward | Goal-Seek |
|---|---|---|
| **ROI** | Distribute budget ₽ to max sales | Find min budget ₽ to hit sales target |
| **Эффективность** | Distribute contacts to max sales | Find min contacts to hit sales target. Conversion to ₽ через CPM/CPC |
| **Вручную** | Per-channel: ₽ или contacts | Per-channel: ₽ или contacts. Solver работает в смешанной валюте |

**Файлы:**
- `sidecar/econometrica/optimize/forward.py` — добавить `mode` параметр.
- `sidecar/econometrica/optimize/inverse.py` — добавить `mode` параметр.
- `src/lib/components/OptimizeBudget.svelte` — conditional UI per mode.
- `src/lib/components/OptimizeGoalSeek.svelte` — conditional UI per mode.

---

## P1 — Сопутствующие изменения

### P1.1 — Декомпозиция: правильные единицы per mode

- Графики в режиме Эффективность показывают вклад в **продажах** (после умножения на β), но raw inputs в **контактах**.
- Никогда не показывать β напрямую (методологическая ошибка — несравнимы между каналами).
- Sales contribution share (%) — основная метрика сравнения каналов.

**Файлы:**
- `src/lib/components/DecomposeChart.svelte`
- `sidecar/econometrica/decompose.py`

### P1.2 — Модель: priors в native единицах

- Когда канал измеряется в показах — priors на Hill K параметр в показах.
- Когда в рублях — priors в рублях.
- UI parameter inspector показывает правильные единицы.

**Файлы:**
- `src/lib/components/ModelInspector.svelte`
- `sidecar/econometrica/model/priors.py`

### P1.3 — Report templates per mode + Goal-Seek toggle

3 mode × 2 task (forward/goal-seek) = 6 базовых template вариантов.
Реализация через единый template + conditional sections (не 6 копий).

---

## P2 — Отложено (явное сужение скоупа)

- Импорт wizard mode-aware с динамическими required colums — оставить базовую валидацию.
- Валидация runtime checks per mode — общий чек-лист.
- Mediascope / DSM adapters — отдельный workstream (Phase B).
- Cross-app sync с Data Studio — Phase B.

---

## Зависимости и риски

### Зависимости
- Нужен **lit review** для ADR-014 safe corridor bounds (Robyn / PyMC-Marketing / academic refs). До этого MVP формула остаётся гипотезой.
- Нужно подтверждение Антона по **полю price_per_pack source** — если в Кагоцел/Венарус данных есть и sales_rub и sales_packs, AUTO работает; иначе UI должен gracefully degrade.

### Риски
- **Inverse solver convergence** — multi-start 10 точек, fallback на forward + linear adjustment если не сходится.
- **Posterior-based corridor дорого вычислительно** — MVP P5/P95 быстро, Expert Mode будущий.
- **Юзер не понимает разницу режимов оптимизации** — обязательная inline help-плашка + tour на первом запуске.
- **Backward compat .aurora bundle** — v1.2.0 проекты должны открываться в v1.3.0. Default mode = ROI + forward (текущее поведение). Goal-seek — opt-in.

### Тесты
- Unit: `test_safe_corridor_bounds.py`, `test_inverse_optimize.py`, `test_price_per_pack_detection.py`.
- Integration: Кагоцел РФ test corpus → forward / goal-seek параллельно, проверка близости результатов на пересечении.
- Regression: 552 существующих теста проходят без изменений.

---

## Оценка работы

| Поток | Дни |
|---|---|
| P0.1 Safe corridor + ADR | 2 |
| P0.2 Inverse solver | 3 |
| P0.3 Price auto-detect | 1 |
| P0.4 UI Optimize toggle + слайдеры | 3 |
| P0.5 Goal-Seek report templates (4 формата) | 3 |
| P0.6 Аудит KPI-семантики (decomposer + UI + tooltips + margin) | 4 |
| P0.7 KPI-aware секции отчётов (4 формата × 2 kpi_kind) | 5 |
| P0.8 Режим Эффективность: устранение money-bound артефактов | 3 |
| P0.9 Mode as derived state (Validate + Import UX rebuild) | 5 |
| Mode-Aware Optimize (3 режима × 2 task) | 2 |
| P1.1 Decompose units | 1 |
| P1.2 Model priors units | 1 |
| P1.3 Report templates per mode | 2 |
| Tests + regression | 2 |
| **Total** | **~37 рабочих дней** |

Vs первая оценка 6-10 дней — расширилось из-за добавления mode-aware всех остальных шагов и 4 форматов goal-seek отчётов.

---

## Порядок исполнения

1. **Wave 1 (math foundation, 5 дней):** ADR-014 lit review → safe corridor → inverse solver → unit tests.
2. **Wave 2 (UI optimize, 4 дня):** toggle + слайдеры + CorridorSlider + price auto-detect.
3. **Wave 3 (mode-aware всего pipeline, 3 дня):** decompose + model priors + report toggles.
4. **Wave 4 (goal-seek reports, 4 дня):** HTML + PPTX + XLSX + DOCX templates.
5. **Wave 5 (regression + bundle compat + release notes, 2 дня):** v1.3.0 tag + ship.
6. **Wave 6 (pilot validate на Кагоцел Венарус, 2 дня):** live test → fixes → ship.

---

## Открытые вопросы перед стартом

1. **ADR-014 формула финал** — после lit review подтвердить `[max(P5, 0.5µ), min(P95, 1.5µ)]` или другой вариант.
2. **Posterior-based в MVP или Expert Mode** — стартовать с MVP, Expert как Phase B?
3. **Goal-seek в режиме Вручную** — есть смыслы (per-channel constraints), но UI сложный. P0 или Phase B?
4. **Backward compat .aurora bundle v1.2** — точно ли default ROI + forward сохраняет текущее поведение для существующих демо-клиентов?
5. **Pilot validate** — Кагоцел + Венарус могут потестировать goal-seek? Нужно ли менять контракты пилотов?
6. **[ЗАКРЫТО 2026-05-12] Mode = explicit toggle или derived state?**
   - **Решение:** Вариант C принят Антоном. Mode выводится автоматически из per-channel input metrics. UI Валидации редизайнится.
   - **Зафиксировано как:** ADR-015 «Mode as derived state» (создать).
   - **Новый раздел плана:** P0.9 — «Mode as derived state: rebuild Validate + Import UX».
