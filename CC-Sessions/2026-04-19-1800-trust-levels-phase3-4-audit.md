---
tags: [session, compressed, econometrica, trust-levels, phase-3, phase-4, unit-costs, audit]
type: session
updated: 2026-04-19
---
# Quick Reference

**Topic:** Trust Level 1+2 (smell-banner + CPP-нормализация) + Phase 3 (What-if) + Phase 4 (Forecast с медиаинфляцией) + 2 волны аудитов.

**Key files:**
- Backend: `sidecar/econometrica/engines/{decomposer,optimizer,validator}.py`, `server.py`, `utils/diagnostics.py`
- Tauri: `src-tauri/src/commands/{project,econometrica}.rs`
- Frontend: `src/lib/components/pipeline/{DecomposeStep,OptimizeStep,BudgetOptimizer,ResponseCurves,UnitCostsPanel,TrustBanner,ValidateStep}.svelte`, `MQSBadge.svelte`, `project-state.js`, `ConfigPanel.svelte`

**Status:**
- ✅ Trust Level 1 (smell-flags + category + TrustBanner с кликом на Валидацию)
- ✅ Trust Level 2 (CPP-нормализация, override unit_costs через request, дефолты РФ 2026)
- ✅ Phase 3 What-if (слайдер ×0.5-×2.0, сравнительная карточка, save-as-scenario)
- ✅ Phase 4 Forecast (2 режима: volume/budget, backend money-constraint, дефолты инфляции по category)
- ✅ Unit consistency (money display, native Hill, конверсия в слайдерах и ResponseCurves)
- ✅ 2 больших аудита с фиксами
- 🟡 Pending: Phase 5 (сценарии onboarding), Scenario rework с unit_costs, Trust Level 3, OLS fallback
- Commits: **19d4ca7** + **d11678b**

## Learnings

### 1. Money vs Native units — корневая архитектура Trust Level 2
MMM-модель обучена на native TRP/показы (Hill-функции). Но пользователь хочет видеть и сравнивать в рублях. Решение:
- Backend `decomposer.py`: spend = raw_spend × unit_cost (money display, ROI сопоставим)
- Backend `optimizer.py`: Hill работает на native, но возвращает `current_spend_money`, `optimal_spend_money`, `total_budget_money`
- Backend `optimizer.py` (новое): принимает `total_budget_money` → constraint `Σ(x × unit_cost) == budget_money`
- Frontend: слайдеры BudgetOptimizer двигаются в money, onChange → native через uc(ch). Redistribute при locked — в money-шкале (сопоставимые единицы).
- ResponseCurves: ось X в money, drag → native для Hill.

### 2. MQS ≠ R² — две разные метрики, явная маркировка
MQS (Model Quality Score) — агрегированный 0-100 (R² 40% + MAPE 30% + MCMC convergence 30%).
R² — чистый fit, доля объяснённой вариации.
В verdict теперь явно `"Модель объясняет 99% вариации продаж (R²)"` + MQSBadge tooltip с формулой.

### 3. Unit smell guard — alarm только при наличии non-money каналов без CPP
Было: ROI > 50× → `smell_flags`. Но если все каналы в money (правильные CPP настроены), высокий ROI — честный результат модели. Теперь `if positive_rois and any_unit_smell` — banner не спамит.

### 4. $effect pickle reuse — сравнение по reference, не по path
Pickle всегда `models/latest.pkl` — путь не меняется. Auto-retry сравнивал по path → не срабатывал после перетренировки.
Фикс: `let lastModelRef = null; if (md === lastModelRef) return;` — Svelte store.set() создаёт новый object, reference работает.

### 5. Python import cache — restart sidecar для backend-правок
Python кеширует `sys.modules` — изменения в `diagnostics.py`/`optimizer.py`/`decomposer.py` не применятся без перезапуска Python процесса. Команда: `taskkill /F /IM python.exe` + запуск `python -B server.py` из `sidecar/econometrica/`. Rust dev-process может reuse orphan process через `is_already_running()` TCP probe.

### 6. DecomposeStep race при перетренировке
Если user на Decompose во время active `stepState === 'loading'` и прилетает новая training → $effect триггерит второй runDecompose параллельно. Guard: `if (stepState === 'loading') return;`.

### 7. `$effect` hydrate pattern с dirty-flag
UnitCostsPanel: `$effect` затирает draft при каждом rerender → теряется пользовательский ввод. Решение: sig-based re-hydrate (`sig = channels.sort().join('|')`) + hydrate только при смене sig.

### 8. Forecast "Сохранить объём" — KPI lift = 0 это НЕ баг, а математика
При volume mode native_total const → Hill-функция видит те же spend → тот же effect → KPI не меняется. Деньги тратятся на компенсацию инфляции. Корректное поведение.

### 9. totalBudget insight money — backend считает `Σ(optimal × unit_cost)`
В optimizer result добавлено `total_budget_money` — для insight в рублях. Раньше insight показывал raw `Σ optimal` (смешанные единицы TRP+рубли) → бессмысленное число.

## Solutions & fixes

### Критичные (P0)

| Проблема | Решение |
|----------|---------|
| time_series_channels ratio = money/raw | Использовать raw_spend для ratio (пропорция одинакова в любых единицах) |
| unit_costs stale после train | DecomposeRequest/OptimizeRequest принимают override → приоритет над pickle config |
| maxMoney = 13.8B ₽ при TRPs (слайдер разваливается) | Cap: `max(initMoney × 2.5, curMoney × 1.2, 1000)` |
| Уведомление успеха через errorMessage (красный) | Раздельные state: `whatIfSuccess` / `forecastSuccess` + `.inline-success` стиль |
| $effect параллельные runDecompose | Guard `if (stepState === 'loading') return;` |
| Forecast "Сохранить бюджет" некорректная avgNewUC | Backend `OptimizeRequest.total_budget_money` + money-constraint |
| MQS 96 vs R² 99% путаница | Verdict маркирован `(R²)`, MQSBadge title с формулой |
| Блок A KPI per-period vs бюджет total | `displayKPI = dData.total_sales` (total за период) |
| Блок B insight totalBudget в смешанных единицах | Backend вычисляет `total_budget_money` |

### Средние (P1)

| Проблема | Решение |
|----------|---------|
| What-if mult→1.0 result висит | Auto-reset whatIfResult в $effect при возврате mult к 1.0 |
| What-if KPI math со вычитанием baseline | Упростили: `total_sales × (1 + lift%)` |
| UnitCostsPanel rawSumForChannel смотрит в 4 места | Упростить до `col.stats.sum` (validator добавляет всегда) |
| Category Mixed скрыта в таблице | Показать серым chip |
| BudgetOptimizer 16 строк мёртвого .btn-optimize CSS | Удалить |
| DecomposeStep em-dash в JSDoc | Заменить на ASCII `-` (svelte-check invalid char) |
| regex word boundary для "тропический" | Откат — `\b` в JS не работает с кириллицей |

### UX fixes

| Проблема | Решение |
|----------|---------|
| Две кнопки "Оптимизировать" | Удалена дубль в BudgetOptimizer, осталась главная CTA в блоке B |
| Пресет "Свободно" 0-300% | Изменён на 0-500% |
| Aurora AI + ECONOMETRICA на разных уровнях | margin-top: 8px на .brand (baseline alignment) |
| "Модель не найдена" при заходе до train | $effect на modelData reference — auto-retry |
| Forecast: пользователь не видит среднюю инфляцию | Summary "Средняя инфляция: +X%" рядом с кнопкой |
| TrustBanner "на шаге Валидация" без ссылки | Кликабельная кнопка `goToValidate()` → pipelineCurrentStep.set(1) |

## Decisions

### Архитектурные
1. **Money для display, native для Hill** — вместо полной конверсии backend на money-units. Оставили Hill в native (сохраняет точность модели), конверсию делаем только на границах (UI, insights).
2. **Backend total_budget_money параметр** — для поддержки money-constraint. Альтернатива «клиент считает native через avgUC» — приближение с ошибкой.
3. **Override unit_costs через request, НЕ через pickle** — после train пользователь может менять CPP без перетренировки. Priority: request override → pickle config → {}.
4. **Smell-detector guard any_unit_smell** — не алармим если всё в money. USP сохраняется для случаев когда user не настроил CPP, но не раздражает когда всё нормально.
5. **Scenario save для What-if/Forecast через явные кнопки** — а не rework общего ScenarioPlayground. Минимум UI-rework.

### Методологические (согласованы с Антоном)
- **Дефолт TV brand W 25-54 = 250 000 ₽/TRP** (не 8-15k как я сначала думала)
- **Смешанные единицы → ROI артефакт** — явное предупреждение в UI
- **Δ-распределение надёжнее точечных ROI** — в правилах TrustBanner
- **Категории brand_reach/performance/mixed** — для правил интерпретации, не для расчёта
- **Forecast mode volume default** — чаще всего пользователь хочет знать "сколько нужно денег чтобы сохранить объём"

## Pending

### Короткосрок (дни)
- **Live-тест Phase 3+4** с реальными данными (What-if + Forecast)
- **Phase 5 — Сценарии onboarding** (~2ч, план в `project_econometrica_optimizer_ux.md`)
- **Scenario rework** — кнопки «Сохранить optimal/current» в ScenarioPlayground + unit_costs в scenario.py (сейчас ROAS meaningless при смешанных единицах)

### Средне (недели)
- **OLS-fallback для <20 точек** (~6-8ч) — honest "CI недоступны" вместо NaN
- **Отчёт** (Report step) — user видел Оптимизацию, дальше не проходил в тесте

### Долгосрок (месяцы)
- **Trust Level 3: Brand vs Performance MMM split** (~12-20ч)
  - Hierarchical Bayesian с разными priors для brand/performance
  - Или 2-stage: brand model → predicted brand-uplift → input для performance MMM
  - Закрывает корневую проблему: модель на weekly/monthly не видит brand-эффект

## Files modified

### Backend (Python sidecar)
- `sidecar/econometrica/engines/decomposer.py` — smell_flags, category per-channel, unit_costs override, time_series raw_spend ratio, any_unit_smell guard, unit_smell только при unit_cost=1.0
- `sidecar/econometrica/engines/optimizer.py` — unit_costs в config, total_budget_money (money-constraint), current_spend_money/optimal_spend_money/total_budget_money/total_current_money в result, O(n²)→enumerate
- `sidecar/econometrica/engines/validator.py` — stats.sum для preview
- `sidecar/econometrica/server.py` — TrainRequest/TrainStartRequest/DecomposeRequest/OptimizeRequest с unit_costs, OptimizeRequest.total_budget_money
- `sidecar/econometrica/utils/diagnostics.py` — verdict с явной меткой «(R²)»

### Tauri (Rust)
- `src-tauri/src/commands/project.rs` — ProjectInfo.unit_costs HashMap + #[serde(default)]
- `src-tauri/src/commands/econometrica.rs` — econ_decompose/optimize принимают unit_costs + total_budget_money

### Frontend (новые файлы)
- `src/lib/components/pipeline/TrustBanner.svelte` — collapsible banner с кликабельной ссылкой на Валидацию
- `src/lib/components/pipeline/UnitCostsPanel.svelte` — ввод CPP с дефолтами РФ 2026, dirty-flag, auto-invalidate, preview, anomaly warn, reset-to-defaults

### Frontend (изменения)
- `src/lib/project-state.js` — unitCosts store + auto-sync из activeProject
- `src/lib/components/ConfigPanel.svelte` — unit_costs в config для econ_train
- `src/lib/components/MQSBadge.svelte` — title с формулой MQS
- `src/lib/components/pipeline/DecomposeStep.svelte` — TrustBanner, category chip+tooltip, spend tooltip, override unit_costs, $effect auto-retry, race guard
- `src/lib/components/pipeline/OptimizeStep.svelte` — Phase 3 What-if, Phase 4 Forecast, displayKPI, currentTotalBudget в money, success/error split, avgInflation
- `src/lib/components/pipeline/BudgetOptimizer.svelte` — money slider, displayBaseKPI lift, maxMoney cap, handleSlider money→native conversion, CSS cleanup
- `src/lib/components/pipeline/ResponseCurves.svelte` — unit_costs prop, money ось X, drag money→native
- `src/lib/components/pipeline/ValidateStep.svelte` — UnitCostsPanel section

### Routes (brand alignment)
- `src/routes/+page.svelte` — margin-top 8px на .brand
- В 8 Aurora-вариантах: ROSST_AI_Legal, Aurora_PR_Master, ROSST_AI_DocMaster, ROSST_AI_Media, ROSST_AI_Creative, AI_APP_AGENCY, Aurora_Creative_Hub, Aurora_Oracle — аналогично

## Setup & config changes

### Дефолты CPP РФ 2026 (в UnitCostsPanel.svelte)
```js
TV brand W 25-54: 250 000 ₽/TRP (ключевой)
TV brand W 18-44: 180 000 ₽/TRP
TV performance:   120 000 ₽/TRP
GRP:              250 000 ₽/GRP
Radio GRP W25-54:  30 000 ₽
OOH CPT:               80 ₽/1000 контактов
Digital CPM:          200 ₽/1000 показов
OTS:                    5 ₽ (прикидка)
```

### Дефолты инфляции Phase 4 (в OptimizeStep.svelte INFLATION_DEFAULTS)
```js
brand_reach: 12%
performance: 7%
mixed:       8%
```

### Пресеты per-channel ограничений (CHANNEL_PRESETS)
```js
free:      0-500%  (раньше 0-300%)
flex:     50-150%
only_up: 100-200%
only_down: 0-100%
locked:  100-100%
```

### Sidecar restart flow (для backend-изменений)
```bash
# 1. Kill Python sidecar (cache bust)
taskkill //F //IM python.exe

# 2. Перезапуск из исходников (dev mode)
cd sidecar/econometrica
python -B server.py

# 3. Проверка health (curl or Monitor until)
curl http://127.0.0.1:7430/health
```

### Dev environment
- `npm run tauri dev` — long-running, запускает Vite + Rust + sidecar auto
- HMR применяет frontend сразу, Rust — после cargo rebuild
- Логи sidecar: `%APPDATA%/aurora-econometrica-gui/logs/sidecar-YYYY-MM-DD.log`

## Errors & workarounds

### 1. Python import cache
**Симптом:** изменения в `.py` не применяются после save.
**Причина:** `sys.modules` кеширует импортированные модули.
**Фикс:** `taskkill /F /IM python.exe` + перезапуск `python -B server.py`.

### 2. Sidecar reuse orphan process
**Симптом:** после kill python, Rust dev не запускает новый sidecar.
**Причина:** `start_sidecar()` проверяет `is_already_running()` TCP probe — вызывается только в `setup()`, не watchdog.
**Фикс:** вручную `python -B server.py` — Rust подхватит через health probe.

### 3. DecomposeStep state застрял на error "Модель не найдена"
**Симптом:** пользователь зашёл на Decompose ДО train → ошибка → перетренировка → ошибка не уходит.
**Причина:** компонент не unmount'ится при переключении шагов, state остаётся.
**Фикс:** `$effect` на `$modelData` reference-change → auto-retry runDecompose.

### 4. Pickle path всегда latest.pkl — нельзя определить "новая модель"
**Симптом:** старый `lastTrainedKey === trainedKey` для разных тренировок.
**Фикс:** сравнение по object-reference (`md === lastModelRef`), Svelte store.set() даёт новый object.

### 5. `\b` regex в JS не работает с кириллицей
**Симптом:** `/\bTRP\b/i.test('TRPs')` → false (буква рядом с границей).
**Workaround:** использовать substring match без boundary. Edge-case false positives принимаем.

### 6. Svelte 5 `{@const}` ограничения размещения
**Симптом:** `{@const}` между `{/each}` и обычным HTML → ошибка `const_tag_invalid_placement`.
**Фикс:** вынести в `$derived` в script блок.

### 7. `$derived` forward reference в Svelte 5
**Симптом:** `const avgInflation = $derived(channels.reduce(...))` до объявления `channels` → "used before its declaration".
**Фикс:** `const avgInflation = $derived(...)` ПОСЛЕ `const channels = $derived(...)`.

### 8. svelte-check em-dash в JSDoc как invalid char
**Симптом:** `@param {number} [attemptsLeft] — Делаем...` → ERROR invalid character.
**Фикс:** заменить em-dash на ASCII `-`.

### 9. CPU не блокируется для curl-poll
**Симптом:** Bash блокирует длинные `sleep` + curl.
**Фикс:** `Monitor` tool с `until curl; do sleep 2; done; echo "ready"` — получаем single event когда условие выполнится.

### 10. Forecast "Сохранить бюджет" без backend constraint
**Симптом:** формула `totalBudgetNative = currentMoney / avgNewUC` даёт случайное число при смешанных unit_costs.
**Фикс:** backend принимает `total_budget_money`, constraint `Σ(x × unit_cost) == budget_money`.

## Full Session Notes

### Хронология работы

**17:30-18:30** — Trust Level 1 реализация:
- Backend decomposer.py: smell_flags + category + unit_smell с regex hints
- Frontend TrustBanner.svelte с collapsible details
- Подключение в DecomposeStep + OptimizeStep

**18:30-19:30** — Trust Level 2 реализация:
- Backend server.py: unit_costs в все Request models
- Backend decomposer/optimizer: spend × unit_cost
- Tauri project.rs: ProjectInfo.unit_costs HashMap
- Frontend UnitCostsPanel с дефолтами РФ 2026
- ConfigPanel передаёт unit_costs в train config

**19:30-20:30** — Live-тест + первый аудит:
- Антон прошёл pipeline → нашёл баги:
  - Trust banner работает, но UnitCostsPanel invisible при objective=ROI (каналы в unused)
  - KPI в блоке A рассоглосован с budget (per-period vs total)
  - Формат «4684.0 M ₽» vs «408 125 247» (разные формата)
  - ROI 1.68× не согласуется с KPI/Budget
  - insight optimizer содержит native sum (TRP+рубли)
- Фиксы: displayKPI = dData.total_sales, fmtBudget везде, unit_costs override в decompose/optimize, backend total_budget_money в insight
- «Значок 96 + текст 99%» путал пользователя → verdict маркирован «(R²)» + MQSBadge title

**20:30-21:00** — Phase 3 What-if + Phase 4 Forecast:
- What-if слайдер, runWhatIf, сравнительная карточка
- Forecast 2 режима (volume/budget), таблица инфляции, runForecast
- Bounds auto-расширение (0-300%+) чтобы constraint выполним

**21:00-21:30** — Scenarios rework:
- Пользователь «сцерании не подхватывают» — ScenarioPlayground сохраняет только текущие слайдеры
- Добавлены saveWhatIfAsScenario + saveForecastAsScenario в OptimizeStep
- Автоимена `what-if-NNpct-XXXXXX` / `forecast-{mode}-NNpct-XXXXXX`

**21:30-22:00** — Детальный аудит Decompose+Optimize:
- 27 пунктов найдено, 15 исправлено (P0+P1+UX), 12 оставлены (P2 — большие рефакторинги)
- Главные фиксы: maxMoney cap (13B→разумный), success/error split, $effect race guard, Forecast budget mode с money-constraint, смелл guard, Mixed category visibility, BudgetOptimizer CSS cleanup

### Два коммита

**19d4ca7** (первый аудит + Trust 1+2):
```
feat(econometrica): Trust Level 1+2 — smell-banner + CPP-нормализация + live-fixes
16 files changed, 842 insertions(+), 33 deletions(-)
```

**d11678b** (Phase 3+4 + второй аудит):
```
feat(econometrica): Phase 3 What-if + Phase 4 Forecast + аудит-фиксы
9 files changed, 731 insertions(+), 84 deletions(-)
```

### Проверки
- `npm run check`: 0 новых errors в модифицированных файлах (было 24 → 21 existing issues не мои, 3 мои исправлены)
- `cargo check`: clean compile
- Live-тест: пользователь прошёл Import→Validate→Train→Decompose→Optimize blocks A+B без замечаний после фиксов

### Backend Python files modified
```python
# decomposer.py
- smell_flags: [{type: 'roi_max'|'roi_spread'|'unit_smell', severity}]
- Per-channel category (brand_reach/performance/mixed) через regex
- unit_smell только при unit_cost=1.0 (CPP не задан)
- spend = raw_spend × unit_cost
- ratio в time_series по raw_spend

# optimizer.py
- unit_costs override из request
- total_budget_money constraint (money-mode)
- response curves в result (native)
- total_budget_money/total_current_money в result
- insight в money

# server.py
- TrainRequest/DecomposeRequest/OptimizeRequest + unit_costs
- OptimizeRequest.total_budget_money

# validator.py
- col.stats.sum для preview

# diagnostics.py
- verdict: «99% вариации продаж (R²)» (явно маркирован)
```

### Key frontend pattern: money/native conversion layer
```svelte
<!-- BudgetOptimizer: слайдеры в money -->
{@const curMoney = cur * uc(ch)}
{@const maxMoney = Math.max(initMoney * 2.5, curMoney * 1.2, 1000)}

<input
  type="range"
  min={0} max={maxMoney} value={curMoney}
  oninput={(e) => handleSlider(ch, parseFloat(e.target.value))}
/>

<script>
function handleSlider(ch, newMoney) {
  const newNative = newMoney / uc(ch);  // ← конверсия для Hill
  if (locked) {
    // Redistribute в money-шкале (сопоставимые единицы)
    const deltaMoney = newMoney - channelBudgets[ch] * uc(ch);
    // ...
    for (const other of others) {
      updated[other] = newOtherMoney / uc(other);  // ← обратно в native
    }
  } else {
    onBudgetChange(ch, newNative);
  }
}
</script>
```

### Key backend pattern: money-constraint switch
```python
# optimizer.py
total_budget_money_target = config.get('total_budget_money')
uc_arr = [float(unit_costs.get(col, 1.0) or 1.0) for col in media_cols]

if total_budget_money_target is not None:
    # Money mode: Σ(x × uc) == budget_money
    constraints = [{
        'type': 'eq',
        'fun': lambda x: float(np.sum(np.asarray(x) * np.asarray(uc_arr)) - total_budget_money_target),
    }]
else:
    # Native mode: Σ x == budget (legacy)
    constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - total_budget}]
```
