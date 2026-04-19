---
tags: [session, compressed, econometrica, live-test, reports, pptx, insights]
type: session
updated: 2026-04-19
---

# Quick Reference

Live-тест Econometrica на датасете Кагоцел РФ MMX (31 точка × 6 каналов, Ratio 2.4:1) вскрыл серию UX/методологических проблем — все исправлены в коммите `4fd0684` (16 файлов, +1101/-151). Ключевые фичи: MQS thinness cap, live-reactive optimize insights через новый store, rich saturation breakdown (🟢🟡🔴⚪), полный рефакторинг Report (5 метрик в ряд, email-ready cover text с dynamic Модель/Результаты/Ограничения блоками, XLSX sheet «Данные», PPTX chart text fix + redesign Exec/Recs/Methodology, unified exports path). Scenario delete UI с ✕ чипами.

**Topic:** econometrica-s8-live-test
**Key files:**
- `sidecar/econometrica/utils/diagnostics.py` — MQS thinness cap + thin-data verdict
- `sidecar/econometrica/engines/pptx_export.py` — chart text styling + redesign + waterfall fix
- `sidecar/econometrica/engines/scenario.py` — delete_scenario fn
- `sidecar/econometrica/server.py` — unified identifier + /compute/scenario/delete endpoint
- `src-tauri/src/commands/report.rs` — XLSX «Данные» sheet (time-series)
- `src-tauri/src/commands/econometrica.rs` — econ_scenario_delete
- `src-tauri/src/lib.rs` — register new command
- `src/lib/project-state.js` — optimizeLiveState store
- `src/lib/insights-rules.js` — thin-data warnings + rich optimize insights + reportInsights + baseline_pct fix
- `src/lib/components/pipeline/ValidateStep.svelte` — section reorder + recs key fix
- `src/lib/components/pipeline/InsightsPanel.svelte` — reportInsights wiring + optimizeLiveState
- `src/lib/components/pipeline/OptimizeStep.svelte` — live state $effect + E letter
- `src/lib/components/pipeline/ReportStep.svelte` — большой рефакторинг
- `src/lib/components/pipeline/BudgetOptimizer.svelte` — overflow fix
- `src/lib/components/pipeline/ScenarioPlayground.svelte` — delete button
- `src/lib/components/MQSBadge.svelte` — MQS title label

**Status:** ✅ Все 5 шагов live-теста завершены. Commit сделан. Memory обновлена (project_econometrica_session8.md, MEMORY.md). Carry-over: sidecar auto-respawn, scenario ROAS при mixed units, Phase 5 onboarding, OLS-fallback, Trust L3.

---

## Learnings

### Методология MMM на тонких данных
- Ratio 2.4:1 (31 точка × 6 каналов ≈ 5 dof) → модель переобучается: R²=0.99, MAPE=6.94%, MQS=95 — формально идеально, но **содержательно ненадёжно**.
- Baseline волатилен между прогонами MCMC (первый прогон 0%, после retrain 30%) — сигнал слабой identifiability.
- ROI отдельных каналов в этих условиях — артефакт: Статьи 496×, Social 125×, Performance 59×. Не для принятия решений.
- mROAS при mixed units несопоставим: TRP mROAS=114-204× vs каналы в рублях с mROAS=0.01-3×. Разброс 8000-1 943 000× — не «реальный потенциал», а unit artifact.
- Факт vs Прогноз visually показывает классический overfit — линии накладываются идеально, но это значит модель помнит точки, а не закономерность.

### Доверие через UX
- **Никогда не показывать «95» без caveat**, если данных мало. Cap на MQS честнее, чем формально высокое число. Пользователь принимает решения на доверии к числу.
- **Многослойная защита**: thin-data warning + MQS cap + unit-smell badges + «не используйте для решений» в инсайтах — три разных сигнала о проблеме. Один упустит пользователь, другой поймает.
- **Context-aware рекомендации** важнее общих советов. При lift=0% рекомендация «сохраните сценарий» звучит глупо — нужно «расширь Мин/Макс %» или «обнови креатив».

### Архитектурные паттерны Svelte 5
- **Store-driven reactivity** для inter-component data flow: InsightsPanel не знает про OptimizeStep, но через `optimizeLiveState` store получает live slider data. Чисто, без coupling.
- **$effect как write-through** из local $state в store — трёхстрочный паттерн, работает безупречно.
- **$derived из множества stores** в функции с `$store` префиксом — автоматически подписывается на все.
- **Dynamic email templates** через $derived из data stores — при retrain email обновляется сам, без refresh кнопки.

### Stable insights принцип
- Инсайты не должны **мигать** при движении слайдеров — это воспринимается как баг. Если саturated=0, не убирать секцию, а показать «🟢 All clear».
- Консолидированный breakdown (🟢🟡🔴⚪ + имена) стабильнее, чем 3-4 отдельные insight'а с условиями.
- Handline меняется по контексту, но количество инсайтов стабильно.

### Python-pptx specifics
- **Default chart text color — чёрный**. На тёмных слайдах невидим. Нужен `_style_chart_text(chart)` helper для осей/легенды/меток.
- **Waterfall data format mismatch** — python-pptx ожидает list of dicts с 'category' key, а decomposer возвращает `{labels, values, types}` dict. Двойная поддержка через isinstance.
- **Layout на textboxes** (не placeholders) — blank_layout + explicit positioning даёт полный контроль над версткой и цветом.
- **Severity badges** через два textboxes (badge left + body right) — работает лучше чем `[VIS]` префиксом в тексте.

### Развёртывание / Reload pipeline
- **Python кеширует импорты** — любое изменение в sidecar/ требует kill python.exe.
- **Tauri не auto-respawn Python** после kill. Приходится запускать вручную `python -B server.py`.
- **Vite HMR работает для .svelte/.js** автоматически.
- **Rust requires cargo rebuild** — Tauri делает это автоматически при изменении в src-tauri, но медленно (30-60 сек).
- **Новые store exports в project-state.js** иногда требуют Ctrl+R в окне приложения (HMR не всегда подхватывает).

---

## Decisions

### MQS Thinness Cap
- **Decision**: добавить data-thinness cap в model_quality_score — Ratio < 2 → 50, < 4 → 70.
- **Why**: без cap на тонких данных модель получает MQS=95, дает ложное доверие. Cap делает оценку методологически честной.
- **Alternative rejected**: менять веса R²/MAPE/convergence — не помогло бы, т.к. те тоже переобучаются.
- **Approach**: min(raw_mqs, thinness_cap). Сохраняем raw_score для аудита.

### optimizeLiveState Store
- **Decision**: новый store для live slider state, write-through через $effect из OptimizeStep.
- **Why**: slider movements не писали в `optimizeData` (только `optimize` клик записывал) → insights не реагировали.
- **Alternative rejected**: пропсы через InsightsPanel — это layout-level компонент, не имеет прямого доступа к OptimizeStep.
- **Alternative rejected**: дублировать buildScaledParams в InsightsPanel — нарушает DRY, impactful при rebalance параметров.
- **Trade-off**: write-through на каждое движение слайдера — дешёво (O(N channels)), но создаёт зависимость двух компонентов от общего store. Оправдано reactive UX.

### Static format cards (done state merged with idle)
- **Decision**: после генерации файла cards с сопроводительным текстом **не скрываются**. done-банер добавляется сверху.
- **Why**: пользователь сохранил PPTX → нужен email-текст → приходилось нажимать «Назад» (не работает) или повторно экспортировать.
- **Alternative rejected**: отдельный tab «Cover text» — лишний UX уровень.
- **Result**: cards видны всегда при наличии data, кнопки меняют label «Презентация (PPTX)» → «PPTX — пересоздать».

### Stable insights per saturation
- **Decision**: консолидировать 3 отдельных инсайта (перенасыщенные/недонасыщенные/стабильные) в **один** с встроенным breakdown по всем 4 категориям (+ unused).
- **Why**: пользователь двигал слайдеры → инсайтов становилось меньше (исчезали при count=0) → кажется багом.
- **Trade-off**: менее гранулярная severity (весь инсайт один severity), но стабильный UX.

### Unified exports path
- **Decision**: Python sidecar использует `aurora-econometrica-gui` (как Rust CARGO_PKG_NAME), не `com.aurora.econometrica`.
- **Why**: XLSX (Rust) и PPTX (Python) оказывались в разных папках → «Открыть папку» показывала только XLSX.
- **Alternative rejected**: Rust вычисляет tauri identifier из config — сложнее, меняет больше файлов.

### Dynamic email templates
- **Decision**: сопроводительный текст в details/summary генерируется из real data через $derived (`modelSummary`, `resultsSummary`, `limitationsSummary`).
- **Why**: статический текст устареет после retrain. Ограничения зависят от текущих данных (Ratio, suspicious каналы).
- **Structure**: Модель (методология + MCMC диагностика + размер данных) / Результаты (метрики + драйвер + lift) / Ограничения (условный список warnings).

### Scenario delete UI
- **Decision**: чипы с ✕ над таблицей, confirm-диалог браузера.
- **Alternative rejected**: delete column в DataTable — изменило бы generic компонент ради одного кейса.
- **Trade-off**: один confirm не custom-styled (native browser), но простой и понятный.

---

## Pending

### Short-term (следующая сессия или две)

1. **Sidecar auto-respawn** — Tauri должен поднимать Python при потере connection, не только в cold-start. Сейчас после kill python.exe user видит «Вычислительный модуль недоступен» и должен либо перезапустить dev, либо стартовать python вручную.
2. **Scenario ROAS при mixed units** — carry-over из S7. scenario.py считает `Σ native` без unit_costs. Для смешанных каналов (TRPs + рубли) ROAS бессмысленный. Нужно пробросить unit_costs в scenario engine.
3. **Ratio calculation unification** — проверить все inline-подсчёты насыщенных каналов. Traffic light в блоке A использует mROAS, некоторые inline-инсайты могли использовать verdict — теперь synced, но при добавлении новых инсайтов проверять.
4. **«Данные» лист в XLSX** не тестировался с пустым time_series — edge case.

### Medium-term

5. **Phase 5 onboarding сценариев** (carry-over из S7, ~2ч) — туториал первого визита на Optimize с явным показом Блоков A→E.
6. **ScenarioPlayground rework** (carry-over из S7) — кнопки «Сохранить optimal» / «Сохранить current» вместо только текущих слайдеров.

### Long-term

7. **OLS-fallback для <20 точек** (~6-8ч) — honest «CI недоступны», но точечные оценки ROI. Для случаев когда Bayesian MMM не сходится из-за малых данных.
8. **Trust Level 3 — Brand vs Performance MMM split** (~12-20ч) — hierarchical Bayesian или 2-stage: отдельная модель для brand-awareness (TRP/GRP) и performance (рубли), потом combine. Фундаментально решает проблему mixed units.
9. **Hill backend: учёт media_means/stds** — pre-existing issue. Модель обучается на normalized X, но optimizer подаёт raw в Hill — даёт аппроксимацию, не точный оптимум.

---

## Errors & Workarounds

### PPTX waterfall AttributeError
- **Error**: `AttributeError: 'str' object has no attribute 'get'` at `pptx_export.py:214`.
- **Cause**: `waterfall` из backend — dict `{labels, values, types}`, код итерировал как list of dicts (получал ключи-строки при iter).
- **Fix**: `isinstance(waterfall, dict)` check с fallback на legacy list-format.
- **File**: `sidecar/econometrica/engines/pptx_export.py:214-224`

### Chart text invisible (чёрный на чёрном)
- **Error**: на тёмных слайдах оси графиков и легенды не читаются.
- **Cause**: python-pptx default font color = black. Slide background = AURORA_DARK.
- **Fix**: `_style_chart_text(chart)` helper красит category_axis/value_axis/legend/data_labels в AURORA_TEXT. Применён ко всем 4 графикам.
- **File**: `sidecar/econometrica/engines/pptx_export.py:93-131`

### base_pct → baseline_pct field mismatch
- **Error**: Инсайт «Base sales = 0%» постоянно, даже когда baseline = 30% в waterfall.
- **Cause**: Backend decomposer.py возвращает `baseline_pct`, frontend insights читал `data.base_pct` → always 0.
- **Fix**: `data.baseline_pct ?? data.base_pct ?? 0` в insights-rules.js + в pptx_export.py.
- **Files**: `src/lib/insights-rules.js:729`, `sidecar/econometrica/engines/pptx_export.py:275`

### BudgetOptimizer overflow «+1 071 473 300%»
- **Error**: при `cur < 1` и `opt = 107M` процент показывал миллиарды.
- **Cause**: `((opt - cur) / Math.max(cur, 1)) × 100` — при cur=0 получаем opt×100.
- **Fix**: условная формула. `cur < 1 && opt >= 1` → badge «новый». `cur < 1 && opt < 1` → «—». Иначе обычный процент.
- **File**: `src/lib/components/pipeline/BudgetOptimizer.svelte:132`

### Port 1420 already in use
- **Error**: `Error: Port 1420 is already in use` при `npm run tauri dev`.
- **Cause**: предыдущий процесс Vite (PID 48728) и Tauri-приложение (PID 45864) не завершились.
- **Fix**: `netstat -ano | grep :1420` → находим PID → `taskkill //F //PID <pid>`.
- **Workaround для регулярных сессий**: всегда закрывать окно приложения через X перед запуском нового `npm run tauri dev`.

### Python sidecar stale code
- **Problem**: изменения в Python-файлах не подхватываются без рестарта (import cache).
- **Fix**: `taskkill //F //IM python.exe` → Tauri НЕ respawn automatically → `cd sidecar/econometrica && python -B server.py` вручную.
- **Indicator в UI**: «Python: Готов» зелёный светится — не доверять ему, смотреть на логи в `%APPDATA%/aurora-econometrica-gui/logs/`.

### UI «Ошибка PPTX» при status=partial
- **Problem**: Backend возвращает `{status: 'partial', path: ...}` когда одна фаза fail, но файл всё-таки сохранён. Frontend ругался и не показывал path.
- **Fix**: принимать `status === 'ok' || status === 'partial'`, логировать failed_phases в console.warn, но считать успехом.
- **File**: `src/lib/components/pipeline/ReportStep.svelte:212-217`

### PPTX + XLSX в разных папках
- **Problem**: XLSX сохранялся в `aurora-econometrica-gui`, PPTX в `com.aurora.econometrica`. «Открыть папку» показывала только XLSX.
- **Cause**: Python hardcoded `identifier = 'com.aurora.econometrica'`, Rust использовал `CARGO_PKG_NAME`.
- **Fix**: unify на Python side — `identifier = 'aurora-econometrica-gui'`.
- **File**: `sidecar/econometrica/server.py:527-531`

---

## Full Session Notes

### Контекст входа
Пришёл после S7 (Trust Level 1+2 + Phase 3+4 + 2 аудита). Все big features собраны. Антон хотел live-тест на реальных данных → «Кагоцел РФ MMX» (31 недель × 6 каналов). Это тонкие данные (Ratio 2.4:1) — специально выбрано для edge case.

### Трейс сессии

**Шаг 1. Старт dev-сервера.** Запустил `npm run tauri dev` в background. Без приключений.

**Шаг 2. Валидация.** Первый скрин — Recommendations panel с кнопкой «Принять». Клик не работал. Debug: `appliedFixes` Set использовал `warn.column + warn.type` в guard но `(warn.column ?? '') + warn.type` в handler → для dataset-level warnings (без column) ключ mismatch. Фикс: унификация. Затем три итерации на reorder блоков (Антон передумывал): финальный порядок **Результат → Рекомендации → Стоимость юнита → Mapper**.

**Шаг 3. Модель / Тренировка.** MQS=95, R²=0.986, MAPE=6.94%, R-hat=1.000, Divergences=0 — формально безупречно. НО Ratio 2.4:1 — переобучение. Методологически катастрофа скрыта за красивыми цифрами. Антон принял решение — добавить **MQS thinness cap**. Написал `model_quality_score(ratio)` с caps. После перетренировки MQS упал с 95 → 70 (capped на «Хорошее»). Добавил caveat в verdict тексте и инсайты с warnings.

**Шаг 4. Декомпозиция.** MQSBadge без «MQS» подписи — число 95 без контекста. Добавил title. Base sales показывалось 0% (устаревший инсайт) — нашёл field mismatch `base_pct` vs `baseline_pct`. Зафиксил frontend + pptx_export.

**Шаг 5. Оптимизация — большой refactor инсайтов.** Антон сказал «катастрофически не хватает инсайтов — тут есть что сказать!». Инсайтов было 3 при богатейшем UI (4 блока + сценарии). Переписал optimizeInsights с нуля — 8+ инсайтов. Потом юзер двинул слайдер бюджета → счётчик «Перенасыщенные X из 6» не обновился. Диагностика: slider writes to `channelBudgets` local state, НЕ в `$optimizeData`. Решение: новый store `optimizeLiveState` с $effect write-through. Заняло ~20 мин, но **теперь вся панель live-reactive на слайдеры**.

Далее Антон двинул 5 каналов в 0 — инсайты «Перенасыщенные: 4 из 6» и «mROAS leaders» **исчезли** (count=0). Выглядит как баг. Фикс: консолидировал 3 saturation-инсайта в один stable с breakdown 🟢🟡🔴⚪ + именами. mROAS leaders тоже стабильны (≥2 active → leaders, 1 → warning, 0 → warning).

Заметил BudgetOptimizer overflow «+1 071 473 300%» при cur≈0. Фикс формулы.

**Шаг 6. Сценарии.** Сохранил 3 сценария (Baseline, what-if-50%, what-if-150%). Антон попросил **delete кнопку** над каждым. Сделал chain: scenario.py `delete_scenario` → server.py `/compute/scenario/delete` endpoint → Rust `econ_scenario_delete` command → lib.rs register → ScenarioPlayground chip + ✕. Плюс заменил ⚙ на **E** в заголовке блока (consistent с A/B/C/D).

**Шаг 7. Report — большой refactor.** 
- Layout: 5 метрик в одну строку через grid repeat(5,1fr).
- Антон: «убери Markdown, оставь DOCX и PPTX». Затем: «описался, нужно XLSX и PPTX». Удалил Markdown кнопки и логику.
- Цветовые карточки форматов с деталями. Антон: «нужен сопроводительный текст для письма». Добавил details/summary с email template.
- Антон: «всегда добавляй описание модели, результата, ограничений». Сделал **dynamic блоки** через $derived (modelSummary / resultsSummary / limitationsSummary) из data stores.
- Антон: «XLSX должен содержать данные для графиков, оба файла — спецификацию модели». PPTX spec slide уже был. Добавил **новый XLSX sheet «Данные»** в Rust (report.rs) — time-series Baseline + каналы + Медиа-вклад + KPI. Вкладка зелёная, с инструкциями внизу.
- reportInsights функция — 5 инсайтов по этапам (Модель/Декомпозиция/Оптимизация/Сценарии/Экспорт), each with рекомендация.
- Антон: «в инсайте осталось упоминание Markdown». Удалил.

**Шаг 8. PPTX экспорт — крашится.** Лог показал `'str' object has no attribute 'get'` — **waterfall format mismatch**. Фикс: поддержка dict + list fallback.

**Шаг 9. PPTX+XLSX в разных папках.** Пользователь: «в папке только один (эксель)». Python использовал `com.aurora.econometrica`, Rust — `aurora-econometrica-gui`. Unify на Python side.

**Шаг 10. PPTX текст не читается.** Антон: «чёрный на чёрном, исправь и сделай красивое форматирование». Нашёл: python-pptx default chart text = black. Добавил `_style_chart_text` helper ко всем 4 графикам. Redesign:
- **Exec Summary**: крупный MQS-бейдж (64pt) + 2×2 сетка метрик.
- **Recommendations**: severity badges (ВЫСОКАЯ=зелёный / СРЕДНЯЯ=янтарный / ВАЖНАЯ=красный) + body. Auto-adds warning при Ratio<4.
- **Методология**: двухколоночная структура — синие accent-заголовки + описания, 6 секций.

**Шаг 11. Sidecar reload проблемы.** Несколько раз убивали python.exe чтобы подхватить изменения. Tauri не respawn. Приходилось вручную `python -B server.py`. Раз был port 1420 collision — убили Vite (PID 48728) и приложение (PID 45864).

**Шаг 12. Commit + memory.** Коммит `4fd0684` — 16 файлов, +1101/-151. Сообщение структурировано по блокам (Methodology/Trust, Optimize UX, Scenarios, Report, PPTX). Написал `project_econometrica_session8.md` с полным трейсом. Обновил MEMORY.md с ссылкой на S8.

### Финальный статус UX-цепочки

**Сигналы доверия, цепочка от валидации до report:**
1. Validate: Ratio 2.2:1 ⚠ в TrafficLight
2. Model: MQS capped 95→70, verdict с thin-data note, 5 инсайтов с warnings
3. Decompose: smell-banner, verdict «ROI подозрительно высок» по каналам
4. Optimize: mROAS breakdown с unit-smell badges, 8 инсайтов с рекомендациями
5. Report: 5 итоговых инсайтов с дисклеймерами + email template с блоком «Ограничения»
6. XLSX: лист «Данные» для independent проверки + «Спецификация» с priors
7. PPTX: Recommendations со словом «ВАЖНАЯ» + Methodology слайд

Это **защита в 7 слоёв** от ложного доверия на тонких данных. Антон после live-теста: «отличная сессия была».
