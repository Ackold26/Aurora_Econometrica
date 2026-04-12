---
tags: [session, compressed]
type: session
updated: 2026-04-13
---

# Quick Reference
Phase 3 (Model Training & Diagnostics) полностью реализована для Aurora Econometrica. Async MCMC pipeline: ConfigPanel → TrainingProgress (polling) → MQSBadge + ConvergenceDashboard (ECharts). Все 9 шагов завершены, аудитные решения A1-D2 применены.

**Topic:** econometrica-phase3-model-training
**Key files:** echarts-setup.js, EChartBase.svelte, TrainingProgress.svelte, ConvergenceDashboard.svelte, ModelTrainingStep.svelte, AdstockPreview.svelte, server.py, modeler.py, econometrica.rs
**Status:** ✅ DONE — коммит `f70d69b`, тег `v1.0.0-phase3-done`. Next: Фаза 4 Decomposition.

---

## Decisions

### A. Критические решения (аудит переопределяет план)

**A1: Фазовый прогресс вместо PyMC per-draw callback**
- PyMC 5.x callback API нестабилен между версиями, на Windows с Metropolis может не вызываться
- Решение: `report('loading', pct=10)` → `report('compiling', pct=20)` → `report('sampling', pct=25)` → `report('diagnostics', pct=90)` → `report('saving', pct=95)` → `report('complete', pct=100)`
- Во время sampling (3-15 мин) pct=25, но elapsed timer тикает → пользователь видит что процесс жив
- Bonus: try/except для PyMC callback — graceful degradation без краша
- `report()` обёрнута в try/except — ошибка в callback никогда не роняет training

**A2: Sequential setTimeout polling вместо setInterval**
- setInterval → очередь запросов при медленном sidecar (ответ >2с)
- Решение: `setTimeout(poll, 2000)` вызывается только ПОСЛЕ завершения текущего poll
- Pattern: `async function poll() { ... setTimeout(poll, 2000); }` — рекурсивный вызов в конце

**A3: prop `useAsyncTraining` в ConfigPanel (backward compat)**
- ConfigPanel используется в chat-first cabinet (cabinet/+page.svelte) — риск сломать
- Решение: `let { useAsyncTraining = false, onTrainingStarted } = $props();`
- При `useAsyncTraining=false` (default) — старый sync `econ_train` flow, untouched
- При `useAsyncTraining=true` — `econ_train_start` → `onTrainingStarted(task_id)` → parent handles progress
- ~15 строк изменений в 410-строчном компоненте

### B. Over-engineering убран

**B1: Вертикальный stack вместо двухколоночного layout**
- ConfigPanel (55%) | Results (45%) создаёт узкий ConfigPanel с channels grid
- Решение: ConfigPanel full width → TrainingProgress → MQSBadge + ConvergenceDashboard

**B2: Channel params table → Phase 4**
- beta/alpha/gamma per channel нужны в Budget Optimizer, не здесь

**B3: GaugeChart исключён из echarts-setup.js**
- MQSBadge — CSS component, не ECharts. GaugeChart добавить в Phase 4 если нужен

### C. Добавлено (пропущено в исходном плане)

**C1: Фильтрация per_param_rhat**
- 70+ параметров → R-hat bar chart нечитаем
- Решение: `key_params = {'intercept', 'sigma'} | {f'media_betas[{i}]' for i in range(len(media_cols))}`

**C2: Dates в actual_vs_predicted**
- X-axis с датами информативнее чем observation index
- `df[date_col].dt.strftime('%Y-%m-%d').tolist()` → `actual_vs_predicted.dates`

**C3: Task cleanup в /train/result/{task_id}**
- `_training_tasks` dict рос бесконечно
- `del _training_tasks[task_id]` после потребления результата

**C4: Visibility при навигации со Step 2**
- StepWrapper использует visibility switching (Rule 14) → компонент остаётся mounted
- Polling продолжается корректно — TrainingProgress не размонтируется

**C5: Error recovery + pulse animation**
- Error banner с "Повторить" и "Изменить настройки" кнопками
- `retryTraining()` → stepState = 'idle', `editConfig()` → resetDownstream(1)
- Pulse animation на progress bar во время sampling фазы: `animation: pulse-opacity 1.8s ease-in-out infinite`

### D. Оптимизации

**D1: Lazy-load ECharts**
- ECharts ~120KB загружается только когда ConvergenceDashboard монтируется
- Dynamic import в `onMount()` IIFE: `const { echarts } = await import('$lib/echarts-setup.js')`

**D2: Минимальный EChartBase (40 строк вместо 80)**
- Только: async init, setOption, ResizeObserver, dispose
- `$effect(() => { if (chart && option) chart.setOption(option, true); })`

---

## Files Modified

### Созданные файлы (6)

| Файл | Размер | Назначение |
|------|--------|-----------|
| `src/lib/echarts-setup.js` | ~20 строк | Tree-shaken ECharts, без GaugeChart (B3) |
| `src/lib/components/charts/EChartBase.svelte` | ~40 строк | D1 lazy import, D2 минимальный wrapper |
| `src/lib/components/AdstockPreview.svelte` | ~80 строк | Pure SVG, geometric/weibull decay кривые |
| `src/lib/components/pipeline/TrainingProgress.svelte` | ~130 строк | A2 sequential polling, C5 pulse animation |
| `src/lib/components/pipeline/ConvergenceDashboard.svelte` | ~200 строк | R-hat bars + Actual vs Predicted (ECharts) |
| `src/lib/components/pipeline/ModelTrainingStep.svelte` | ~180 строк | B1 vertical stack, C5 error recovery |

### Изменённые файлы (6)

| Файл | Изменения |
|------|-----------|
| `package.json` | `"echarts": "^5.6.0"` в dependencies |
| `sidecar/econometrica/server.py` | +threading/uuid/time imports, `_training_tasks` dict + lock, 3 async endpoints (start/progress/result), `TrainStartRequest` model |
| `sidecar/econometrica/engines/modeler.py` | `progress_callback` param, `report()` helper, фазовый прогресс (A1), try/except PyMC callback, per_param_rhat фильтрация (C1), dates в actual_vs_predicted (C2) |
| `src-tauri/src/commands/econometrica.rs` | `econ_train_start`, `econ_train_progress`, `econ_train_result` команды |
| `src-tauri/src/lib.rs` | Регистрация 3 новых команд в `generate_handler![]` |
| `src/lib/components/ConfigPanel.svelte` | Prop `useAsyncTraining`/`onTrainingStarted`/`lastConfig`, async flow ветка, AdstockPreview интеграция, `lastConfig = $bindable(null)` |
| `src/routes/pipeline/+page.svelte` | Step 2 placeholder → `<ModelTrainingStep />` |

---

## Solutions & Fixes

### JSDoc ошибки svelte-check (5 ошибок → 0)

**Проблема 1:** `Parameter 'p' implicitly has an 'any' type` в ECharts formatter callbacks
```js
// ❌ Было:
formatter: (p) => p.value.toFixed(4)
formatter: (params) => { const p = params[0]; ... }

// ✅ Стало:
formatter: (/** @type {any} */ p) => p.value.toFixed(4)
formatter: (/** @type {any[]} */ params) => { const p = params[0]; ... }
```

**Проблема 2:** `Expression of type 'string' can't be used to index type` для PHASE_LABELS
```js
// ❌ Было:
const PHASE_LABELS = { loading: '...', compiling: '...', ... };

// ✅ Стало:
/** Phase labels in Russian @type {Record<string, string>} */
const PHASE_LABELS = { loading: '...', compiling: '...', ... };
```

**Проблема 3:** `Parameters '_' and 'i' implicitly have 'any' type` в array.map
```js
// ❌ Было:
avp.actual.map((_, i) => `#${i + 1}`)

// ✅ Стало:
avp.actual.map((/** @type {any} */ _, /** @type {number} */ i) => `#${i + 1}`)
```

### ECharts tooltip formatter — ошибка в логике
- `trigger: 'axis'` возвращает `params: any[]` (массив), а не один объект
- Tooltip formatter в rhatOption получает массив — `params[0]` для первого элемента
- Исправлено: `formatter: (/** @type {any[]} */ params) => { const p = params[0]; ... }`

### ConvergenceDashboard — rhat chart height
- Фиксированная высота 300px → мало для 10+ параметров
- Динамическая: `Math.max(180, rhatCount * 28 + 60)px` — масштабируется с числом параметров

### EChartBase — cleanup return в onMount
- Rule 2: `onMount` возвращает синхронную функцию очистки
- IIFE для async, sync return для cleanup: `return () => chart?.dispose();`

---

## Learnings

### Python async threading pattern в FastAPI
```python
_training_tasks: dict[str, dict] = {}
_training_lock = threading.Lock()

@app.post('/compute/train/start')
def train_start(req: TrainStartRequest):
    task_id = str(uuid.uuid4())
    with _training_lock:
        _training_tasks[task_id] = {'status': 'running', 'pct': 0, 'started_at': time.time(), ...}
    threading.Thread(target=run, daemon=True).start()
    return {'task_id': task_id}
```
- `daemon=True` → thread умирает вместе с процессом
- Lock только вокруг dict mutations, не вокруг самого training
- `elapsed_sec` вычисляется в реальном времени: `time.time() - started_at`

### Sequential polling vs setInterval
```js
// ✅ Sequential — следующий poll после завершения предыдущего
async function poll() {
  if (!active) return;
  try {
    const p = await invoke('econ_train_progress');
    // ... update state ...
    if (p.status === 'done') { /* fetch result */ return; }
    if (p.status === 'error') { /* handle */ return; }
  } catch { /* retry on error */ }
  setTimeout(poll, 2000);  // ← ПОСЛЕ await
}
```

### ConfigPanel backward compat pattern
```js
// Один компонент, два flow:
if (useAsyncTraining) {
    const start = await invoke('econ_train_start', { config });
    onTrainingStarted?.(start.task_id);
    return;  // TrainingProgress берёт управление
}
// Original sync flow — untouched ниже
const result = await invoke('econ_train', { config });
```

### ConvergenceDashboard — ECharts R-hat color coding
```js
const colors = values.map(v =>
  v < 1.01 ? '#22c55e' :   // green — good
  v < 1.05 ? '#f59e0b' :   // yellow — warning
  '#ef4444'                  // red — not converged
);
```
- markLine at x=1.05 с label "Порог сходимости"
- rhatHeight динамическая: `Math.max(180, rhatCount * 28 + 60)px`

### AdstockPreview — Weibull PDF формула
```js
// k=2, lambda=3
const x = t === 0 ? 0.01 : t;  // избегаем деления на 0
pts.push((k / lam) * Math.pow(x / lam, k - 1) * Math.exp(-Math.pow(x / lam, k)));
```
- Normalize to [0,1]: `const mx = Math.max(...pts); pts.map(v => v / mx)`

---

## Pending

### Фаза 4: Decomposition
- `DecomposeStep.svelte` — waterfall chart (ECharts), channel contributions
- `/compute/decompose` уже реализован в server.py + econometrica.rs
- `econ_decompose` Rust команда существует
- Нужно: компонент + wiring в +page.svelte

### Фаза 5: Budget Optimizer
- Интерактивные слайдеры, Hill function client-side
- Channel params table (была в B2 — откладывалась сюда)
- draggable ECharts graphic

### Фазы 6-7: Report + Sidecar bundle
- Executive summary, PPTX export
- PyInstaller bundle для Python sidecar

### Технический долг
- `_temp_license.json` в корне репо — не закоммичен, не в .gitignore
- econometrica.html — нужно обновить под Phase 3 (сейчас описывает только Import+Validate)
- Dev-тест с реальными данными: `C:\Users\ackol\Desktop\Эконометрика\`

---

## Full Session Notes

### Порядок реализации
Блок 1 (параллельно): Шаги 1+2+5
- echarts-setup.js + EChartBase.svelte + AdstockPreview.svelte
- server.py async endpoints + modeler.py modifications

Блок 2 (параллельно): Шаги 3+4
- econometrica.rs 3 команды + lib.rs регистрация
- TrainingProgress.svelte

Блок 3: Шаг 6
- ConvergenceDashboard.svelte

Блок 4 (параллельно): Шаги 7+8
- ModelTrainingStep.svelte
- ConfigPanel.svelte modifications

Блок 5: Шаг 9
- +page.svelte wiring
- npm install echarts
- svelte-check + cargo test
- коммит + тег

### Верификация
```
npm run check: 251 FILES, 0 ERRORS, 16 WARNINGS (pre-existing)
cargo test:    57 passed, 0 failed
git commit:    f70d69b — 14 files changed, 1084 insertions(+), 49 deletions(-)
git tag:       v1.0.0-phase3-done
```

### Состояние тегов
```
v1.0.0-phase0-done  (816a0e0) — Prerequisites
v1.0.0-phase1-done  (0d1da31) — Pipeline Architecture
v1.0.0-phase2-done  (2b61dc0) — Data Intelligence
v1.0.0-phase3-done  (f70d69b) — Model Training & Diagnostics ← ТЕКУЩИЙ
```

### Ключевые архитектурные решения (зафиксированные)
- **HTTP async task pattern:** POST /start → GET /progress polling → GET /result/{id}
- **Sequential setTimeout** вместо setInterval для polling
- **Phase-level progress** (не per-draw) — надёжно на Windows без компилятора
- **Visibility switching** (Rule 14) — TrainingProgress продолжает работать при навигации
- **useAsyncTraining prop** — один ConfigPanel для двух flow без дублирования логики
- **Lazy ECharts** — D1 dynamic import только когда ConvergenceDashboard монтируется
- **Task cleanup on consumption** — C3 `del _training_tasks[task_id]` в /result endpoint
