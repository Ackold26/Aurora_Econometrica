---
tags: [session, compressed, econometrica, optimize, ux, trust, methodology]
type: session
updated: 2026-04-19
---
# Quick Reference

Большая UX-сессия по шагу Оптимизация Aurora Econometrica + критичный фикс денормализации KPI + согласованы методологические принципы Trust Levels (smell-banner + CPP-нормализация). Phase 1+1B+2 Optimizer закрыты. Антон поднял фундаментальный методологический вопрос про TRPs/охватные каналы (ROI 48,322× — артефакт смешанных единиц), согласован план уровней 1+2 как ближайший приоритет.

**Topic:** Optimize UX overhaul + Trust methodology
**Status:** ✅ Phase 1+1B+2 в коммите `5998b8b`. ⏭ Trust Level 1+2 (БЛИЖАЙШИЕ) → Phase 3-5 → Brand/Perf split (долгосрочно).

**Key files:**
- `src/lib/components/pipeline/OptimizeStep.svelte` — 4 блока, экспертная панель, fallback на decompose, custom-лимиты
- `src/lib/components/pipeline/BudgetOptimizer.svelte` — Δ бюджета бейдж, normalization prop
- `src/lib/components/pipeline/ModelTrainingStep.svelte` — success-banner, auto-scroll, resetDownstream(2)
- `src/lib/components/ConfigPanel.svelte` — modelTrained prop, кнопка меняется, советует свернуть advanced
- `src/lib/components/pipeline/DecomposeStep.svelte` — 4-шажный backoff retry, type-safe, ensureProjectId
- `src/lib/components/pipeline/InsightsPanel.svelte` — context для optimizeInsights
- `src/lib/insights-rules.js` — переписана `optimizeInsights(opt, ctx)`, pre/post state
- `src/lib/hill.js` — `predictKPI`/`marginalROI` принимают normalization
- `src/lib/project-state.js` — `modelData.normalization`
- `sidecar/econometrica/server.py` — `min_per_channel`/`max_per_channel`, лог decompose endpoint
- `sidecar/econometrica/engines/optimizer.py` — per-channel constraints
- `sidecar/econometrica/engines/modeler.py` — возвращает `normalization: {y_mean, y_std}` в результате train
- `src-tauri/src/commands/econometrica.rs` — пробрасывает доп. параметры

## Learnings

### Методологические (главные открытия сессии)

**1. MMM на месячных/недельных данных НЕ ВИДИТ brand-эффект.** TV/TRPs/OOH работают long-term (build-up месяцами, decay weibull λ=0.7-0.9). Текущая модель использует Adstock geometric (decay 1-2 недели) → улавливает только performance-bump. Brand-вклад «вымывается» в intercept или приписывается коррелирующим каналам.

**2. Multicollinearity на малых данных непреодолима.** На 31-43 наблюдениях модель физически не может надёжно различить каналы, движущиеся синхронно с продажами. Получает «удобное» решение (часто валит на «дешёвые» каналы), не «правильное». Это фундаментальный предел MMM, не баг конкретной реализации.

**3. Смешанные единицы ломают ROI.** TRPs/GRPs/показы не в рублях → ROI = вклад_₽ ÷ TRP-пункты = математический артефакт без физического смысла. На Кагоцеле: 22,100 TRPs → ROI 48,322× при реальной стоимости медиа в сотни миллионов ₽.

**4. Дефолт CPP TV brand W 25-54 = 250 000₽/TRP** (Антон поправил, моя оценка 8000-15000 была неверна на порядок). Это критическая константа для будущей CPP-нормализации.

**5. Главный принцип честной интерпретации:** «модель должна знать свои пределы и сама о них предупреждать». Это инженерная честность, отличающая зрелый продукт от чёрного ящика. Robyn/LightweightMMM этого не делают — наш USP.

### Технические

**6. ECharts не парсит CSS color-mix().** `itemStyle: { color: 'color-mix(...)' }` молча падает на дефолтную палитру. Бары были серые, легенда — цветная. Решение: hex-цвета + явная `legend.data` с itemStyle.color.

**7. Svelte onclick передаёт MouseEvent как первый аргумент.** `<button onclick={runDecompose}>` → `runDecompose(MouseEvent)`. Если функция ожидает number `attemptsLeft`, проверка `attemptsLeft > 1` возвращает false (NaN). Решение: оборачивать в `() => runDecompose()` либо type-safe default `if (typeof attemptsLeft !== 'number') attemptsLeft = 4`.

**8. `mainEl = $state()` в Svelte 5.** Просто `let mainEl` без `$state()` даёт warning «non_reactive_update» — `bind:this` работает, но связанные effect'ы могут не срабатывать корректно.

**9. Stale HMR cache в Tauri webview.** Иногда после правок нужно Ctrl+Shift+R / «Empty cache and hard reload» в DevTools. HMR Vite пересобирает, но скомпилированный bundle в браузере остаётся старым.

**10. Денормализация predictKPI критична.** Backend модель работает в normalized шкале (`y_norm = (y - mean) / std`). Frontend predictKPI без денормализации возвращает ≈0.5-2 → toLocaleString({maximumFractionDigits: 0}) округляет до 0. Та же история с marginalROI (mROAS «0.00×»).

**11. UX доверия = «модель сама знает свои пределы».** Согласованный подход — не маскировать проблемы, а явно предупреждать в banner'е с конкретными правилами интерпретации.

## Decisions

### Согласованы с Антоном

**1. Trust Levels 1+2 — БЛИЖАЙШИЙ приоритет** (перед Phase 3-5):
- 🔴 **Уровень 1** (~2ч): smart-детектор подозрительных результатов в decomposer.py + жёлтый информационный banner на Decompose/Optimize с честной интерпретацией. Триггеры: ROI > 50×, спред ROI(top)/ROI(bottom) > 50×, имя канала содержит TRP/GRP/OTS/показ/охват/рейтинг.
- 🟡 **Уровень 2** (~4ч): на шаге Валидация — input CPP/CPM для non-money каналов, backend умножает spend на cost_per_unit. Дефолты по медиа-данным РФ 2026 (см. ниже).

**2. Trust Level 3 — долгосрочная** (после Phase 5 + Trust 1+2 + production):
- Brand vs Performance MMM split (hierarchical Bayesian / 2-stage). Откладывается до v2 после feedback от реальных клиентов.

**3. Дефолты CPP по медиа-данным РФ 2026** (для UI Уровня 2):
- **TV brand W 25-54: 250 000₽ за TRP** (КЛЮЧЕВОЙ дефолт, согласован)
- TV brand W 18-44: ≈ 180 000₽ за TRP
- TV performance: ≈ 120 000₽ за TRP
- OOH: ≈ 80₽ за тыс. контактов
- Digital impressions (CPM): ≈ 200₽ за 1000 показов
- Radio: ≈ 30 000₽ за GRP (W 25-54)

**4. UX-структура Optimize — 4 явных блока** + сценарии отдельной секцией:
- A. Текущий бюджет (статус, view-only)
- B. Оптимизация распределения (основной usecase)
- C. What-if (другой бюджет, Phase 3 placeholder)
- D. Прогноз на будущий период с медиаинфляцией (Phase 4 placeholder)
- ⚙ Сценарии (постоянно видимы, Phase 5 расширит)

**5. Экспертный режим = per-channel ограничения** (не глобальное упрощение). 5 пресетов для baying-сценариев: Свободно/Гибкий/Только↑/Только↓/Зафиксирован. Архитектура `min_per_channel`/`max_per_channel` в `econ_optimize` — переиспользуется для Phase 3/4.

**6. UX после тренировки модели** — комбо A+B+C+collapse:
- Success banner вверху с MQS/R² + кнопка «↓ Смотреть детали» (slide-in)
- Auto-scroll к anchor через 0.6с
- Кнопка меняется: «Запустить модель» (синяя) → «✓ Обучено · Перетренировать» (зелёная outline)
- ConfigPanel сворачивает «Расширенные настройки» (НЕ трогаем глобальный expertMode)

**7. miROAS статус «⚪ Не используется»** для каналов с 0 расходом (вместо нелогичного «🔴 Перенасыщен 0.00×»).

**8. ROI > 50× в decomposer.py получает вердикт «ROI завышен (не рубли?)»** + verdict_tone='warn' для frontend подсветки.

## Pending

### 🔴 Ближайшие (приоритет — следующая сессия)

1. **Trust Level 1: smell-banner + smart-детект** (~2ч)
   - Backend (decomposer.py): добавить `smell_flags: [{type, channel, severity}]`
   - Frontend (Decompose + Optimize): жёлтый banner с честной интерпретацией
   - Бонус: категория канала (Performance / Brand-Reach / Mixed) в экспертной таблице

2. **Trust Level 2: CPP-нормализация** (~4ч)
   - Шаг Валидация: input CPP/CPM для non-money каналов с пресетами
   - Backend: `unit_costs: {channel: cost_per_unit}` в config
   - optimizer/decomposer умножают spend на cost_per_unit для нормализации в рубли

### 🟡 Средние (после Trust 1+2)

3. **Phase 3: What-if блок** (~3ч)
   - Слайдер общего бюджета (±50% от текущего) или прямой ввод
   - Кнопка «Пересчитать для нового бюджета»
   - Сравнительная таблица текущий vs новый

4. **Phase 4: Прогноз на будущий период с медиаинфляцией** (~3-4ч)
   - Период (квартал/год)
   - Таблица per-channel inflation% с дефолтными пресетами по типу медиа
   - Режимы: «Сохранить объём» vs «Сохранить бюджет»
   - Backend: `inflation_per_channel` и `mode` параметры в econ_optimize

5. **Phase 5: Сценарии onboarding** (~2ч)
   - ScenarioPlayground постоянно видим
   - Onboarding объяснение «что это»
   - Готовые кейсы: «-30% TV», «+50% Performance», «Перебросить из OLV в Banners»

### 🟢 Долгосрочные

6. **Trust Level 3: Brand vs Performance split** (~12-20ч)
   - Hierarchical Bayesian с разными priors для brand-каналов и performance-каналов
   - Или 2-stage MMM (brand model → performance MMM с brand_uplift как control)
   - После Trust 1+2 + Phase 3-5 + production feedback

7. **OLS-fallback для <20 точек** (~6-8ч) — из старой задачи, отдельный документ

8. **ROI и CI 95% в channel_params** — backend не возвращает их, прочерки в таблице параметров каналов

### Нюансы

- ECharts warning «There is a chart instance already initialized on the dom» — некритично, чарты пересоздаются без dispose() при смене props
- Старые pickle (до 2026-04-19) не имеют normalization → predictKPI вернёт normalized value. Нужна перетренировка.

## Full Session Notes

### Хронология сессии

**Начало:** Антон попросил продолжить Aurora Econometrica после прорыва live-теста. Контекст из предыдущих сессий: PPTX блокер, R²/MAPE wiring, спецификация модели — всё закрыто в session 5 (bebbe7a).

**Phase 1: Структура Optimize в 4 блока + tooltips** (закрыто)

Реструктурировала `OptimizeStep.svelte`:
- Блок A — статус-карточка (Общий бюджет, Прогноз KPI, Средний ROI, Светофор насыщения)
- Блок B — основная оптимизация (контролы, slider'ы, Response Curves, miROAS)
- Блок C — What-if placeholder с бейджем «скоро»
- Блок D — Прогноз+медиаинфляция placeholder
- Сценарии — отдельная секция с ▼ Развернуть

Tooltips на 9 опциях формата «что это + почему важно»: Общий бюджет, Мин %, Макс %, Фиксировать бюджет, Прогноз KPI, miROAS, Response Curves, Средний ROI, Светофор насыщения.

Двойной overflow убран (та же проблема что в DecomposeStep — `.pipeline-main` владеет скролом).

**Phase 1B: Экспертная панель per-channel ограничений** (по запросу Антона)

Антон попросил per-channel настройки границ Min/Max — для baying-сценариев (TV-сделка, OOH контракты, фиксированные обязательства).

Реализация:
- Backend (optimizer.py + server.py): `econ_optimize` принимает `min_per_channel/max_per_channel` (dict)
- Логика: если для канала задан явный лимит — используется он, иначе глобальный fallback
- Rust (econometrica.rs): пробрасывает доп. параметры
- Frontend: таблица «Ограничения по каналам» (только в expert-mode)
- 5 пресетов:
  - 🆓 Свободно (0-300%)
  - ⚖ Гибкий (50-150%) — дефолт
  - ⬆ Только ↑ (100-200%) — фикс. контракт с минимумом
  - ⬇ Только ↓ (0-100%) — бюджет ограничен сверху
  - 🔒 Зафиксирован (100-100%) — годовая сделка
- Жёлтый ● маркер на каналах с custom-лимитами + кнопка ↺ Сбросить

Архитектура переиспользуется для Phase 3/4 (там же per-channel inflation %).

**Phase 2: Реактивные инсайты Optimize** (закрыто)

Переписала `optimizeInsights(opt, context)` в `insights-rules.js`:

Pre-state (до запуска оптимизации):
- Headline по decompose: «Готов к оптимизации: N каналов, бюджет X₽, средний ROI Y×»
- Прогноз потенциала по структуре каналов:
  - saturated > efficient → warning + 5 путей улучшения
  - благоприятная структура → «Ожидаемый прирост 5-N%»
- Объяснение всех параметров оптимизации

Post-state (после optimize):
- Headline lift (значительный/умеренный/почти оптимально) с tip про пилот
- **Особый случай +0% / негатив** — explanation overlay с 5 путями выхода (Снизить Мин, Повысить Макс, What-if, Эксперт-лимиты, проверить TRPs)
- Главные сдвиги: топ-4 каналов с ↑/↓ и +/-Pct + суммы в ₽
- Влияние custom-лимитов
- Total budget изменение (если фиксация выключена)
- Action items

InsightsPanel передаёт `{dec, mod}` в context.

**Критичный фикс KPI денормализация**

Антон обнаружил: Прогноз KPI = 0 в блоке Распределение. Корневая: `predictKPI` возвращает в normalized шкале (~0.5-2), `toLocaleString({maximumFractionDigits: 0})` округляет до 0.

Решение:
- modeler.py: `train_model` возвращает `normalization: {y_mean, y_std}` в результате
- modelData store расширен полем `normalization`, синхронизирован с resetDownstream
- `predictKPI(budgets, scaledParams, normalization?)`: если normalization передана → `total × y_std + y_mean`
- `marginalROI(x, alpha, gamma, beta, normalization?)`: × y_std → mROAS в реальных рублях
- OptimizeStep + BudgetOptimizer пробрасывают yNorm

⚠️ Старые pickle модели не имеют normalization → predictKPI вернёт normalized value (≈0-2). Нужна перетренировка.

После перетренировки на Кагоцеле: Прогноз KPI = 409 875 876 ₽ ✅, «-2.0% к текущему» работает.

**UX-полировка miROAS**

Антон обнаружил «постоянно показывает 0» и «перенасыщение при нуле — что-то не так?»:
1. Денормализация через y_std (см. выше)
2. **Live miROAS** — использует `channelBudgets[ch]` (текущие слайдеры), не `currentSpend` (initial)
3. **Статус «⚪ Не используется»** для каналов с 0 расходом (раньше «🔴 Перенасыщен 0.00×» — нелогично)
4. Светофор в блоке A: 4-я категория «⚪ N»

**Δ бюджета в карточке «Общий бюджет»**

По запросу Антона: «не показывает динамику к текущему бюджету. то есть можно сократить бюджет в 2 раза, но почти не упасть по KPI»

В BudgetOptimizer добавлен бейдж «🔴 -86% (-227M ₽)» рядом со значением. Зелёный/красный по знаку. Tooltip про initial total.

Демонстрирует saturation: «бюджет 37.4M 🔴 -86% / Прогноз KPI -2.0%» = «сократил в 7 раз, KPI упал на 2%».

**ModelTrainingStep — UX после тренировки** (по запросу Антона)

Антон: «когда модель уже посчитана, кнопка ЗАПУСТИТЬ МОДЕЛЬ должна меняться - результаты появляются ниже - их не видно. как лучше сделать?»

Согласовано комбо A+B+C+collapse:
1. **Success banner** вверху с MQS/R² + кнопка «↓ Смотреть детали» (slide-in анимация)
2. **Auto-scroll** к anchor `#model-results-anchor` через 0.6с
3. **Кнопка меняется**: «Запустить модель» (синяя filled) → «✓ Обучено · Перетренировать» (зелёная outline)
4. **ConfigPanel.modelTrained** prop: автоматически сворачиваются «Расширенные настройки» (НЕ трогаем глобальный expertMode)
5. **resetDownstream(2)** при handleTrainingStarted — устаревшее ✕ от прошлой попытки исчезает

**DecomposeStep race-fixes** («Модель не найдена» — старая проблема)

Антон: «работает только через клик Повторить». Корневая: `<button onclick={runDecompose}>` передавал MouseEvent → `attemptsLeft = MouseEvent` → `attemptsLeft > 1 = false` (NaN comparison) → авто-retry не срабатывал.

Фиксы:
- Кнопка обёрнута в `() => runDecompose()` — без event arg
- Type-safe `runDecompose(attemptsLeft)`: `if (typeof attemptsLeft !== 'number') attemptsLeft = 4`
- 4 попытки с backoff 1.5/2/3с (раньше было 1)
- ensureProjectId через backend fallback (`project_get_active`)
- Расширенный regex: «модель не найдена / pickle / latest.pkl / not found»
- onMount сбрасывает старый errorMessage
- Server.py /compute/decompose: добавлен лог `project_dir` + `pickle_exists` для диагностики

**OptimizeStep fallback на decomposeData**

Антон: «блок A пустой (Бюджет 0₽)» при первом заходе на Optimize до запуска оптимизации.

Фикс: `channels`, `currentSpend`, `currentTotalBudget`, `channelBudgets` имеют fallback на `decomposeData?.channels` если `optimizeData` ещё нет → блок A показывает реальные числа сразу + блок B интерактивен.

**ROIComparison color-mix баг** (исправлен в session 5, но обнаружен заново здесь)

`itemStyle: { color: 'color-mix(in srgb, var(--success) 70%, transparent)' }` — ECharts не понимает CSS-функции (только hex/rgb/hsl). Падал на дефолтную палитру → легенда цветная, бары серые. Заменено на hex + разделение «Эффект %» на 2 серии (зелёная efficient + красная saturated) через stack='effect'.

**Согласованы методологические принципы Trust Levels** (главная содержательная часть сессии)

Антон поднял критический вопрос на скрине Декомпозиции по Кагоцелу:
- TRPs бренд (W 25-54): 22,100 пунктов → ROI 48,322× (бред)
- Статьи: расход 3.8M, вклад 1.96B → ROI 506× (подозрительно)
- Social: 15.5M → 1.9B = ROI 123×
- Performance: 23.8M → 1.43B = ROI 60×
- OLV: 107M → 868M = ROI 8.10× (реалистично)
- Banners: 113M → 631M = ROI 5.55× (реалистично)

Вопросы Антона:
1. TRP не рубли, не могут давать ROI
2. Статьи 3.8M ≠ 22100 TRP по реальной стоимости — нелогично, ставит модель под вопрос
3. Social/Performance тоже не сравнимы с TRP, но вклад высокий
4. Возможно TRP даёт и базу?
5. Как правильно интерпретировать?
6. Как помочь пользователю не потерять веру в эконометрику?

Дала развёрнутый методологический ответ:
1. ROI 48,322× = математический артефакт деления вклада_₽ на TRP-пункты
2. На 31 наблюдении модель не различает каналы — multicollinearity непреодолима
3. Brand-эффект НЕ виден текущей моделью (Adstock geometric decay 1-2 недели). TV/TRPs реально работают на сдвиг базы (Adstock weibull λ=0.7-0.9)
4. ROI каналов сравнивать только внутри одной группы единиц
5. Главный принцип: модель должна знать свои пределы и сама о них предупреждать

Согласован 3-уровневый план. Антон подтвердил: «Давай сделаем уровень 1 и 2». Поправил мой дефолт CPP — TV brand W 25-54 = **250 000₽/TRP** (моя оценка 8000-15000 была неверна).

**Коммит и память**

В конце сессии:
- Git commit `5998b8b` — 13 файлов, +1196/-198 (только тематически relevant файлы, не трогая чужое в репо)
- Создано 3 новых memory:
  - `project_econometrica_session6.md` — детальная сводка
  - `project_econometrica_trust_methodology.md` — Trust Levels 1+2 план + дефолты CPP
  - `project_econometrica_brand_perf_split.md` — Trust Level 3 (долгосрочно)
- Обновлён `project_econometrica_optimizer_ux.md` — Phase 1+1B+2 закрыты
- Обновлён `MEMORY.md` — все ссылки и приоритеты 🔴🟡🟢

### Errors & workarounds

**stale HMR cache (Tauri webview)** — несколько раз Антон видел старый bundle (например `stepEl is not defined` хотя в коде stepEl убран). Решение: Ctrl+Shift+R в DevTools → «Empty cache and hard reload». Не блокер, но запомнить — при «странных» ошибках первое что проверить.

**ECharts color-mix** — невалидный для парсера ECharts. Только hex/rgb/hsl. Решение: явные hex.

**Svelte onclick → MouseEvent** — `onclick={fn}` передаёт event как первый аргумент. Если функция имеет int default, можно сломать логику. Решение: `() => fn()` либо type-safe default.

**Svelte 5 `$state()`** — bind:this нужен `let x = $state()`, иначе non-reactive warning.

**Race с pickle файлом** — после тренировки sidecar пишет latest.pkl async, decompose может стартовать до записи. Решение: 4 retry с backoff.

**MouseEvent в onclick передавался как attemptsLeft в runDecompose** — баг моего собственного фикса retry. Решение: `() => runDecompose()`.

**TRPs/non-money каналы дают артефактный ROI** — фундаментальная проблема, частично решается Trust Level 1 (banner), полностью — Trust Level 2 (CPP-нормализация).

**Модель приписывает TRPs «инкрементальный» вклад** — фундаментальный предел MMM на коротких рядах. Полное решение — Trust Level 3 (Brand vs Performance split, hierarchical Bayesian).
