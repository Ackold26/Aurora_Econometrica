# RC2 Remediation Plan — Aurora MMM Optimizer v2.1.0

> **Создан:** 2026-05-16 после пилотного прогона.
> **База:** `docs/PILOT_FINDINGS_CONSOLIDATED.md` (21 находка).
> **Цель текущей сессии:** закрыть **P0 + критичные P1**, остальное в backlog для v2.1.0-rc3 / v2.2.0.

---

## Что делаем сейчас (этой сессией)

| # | Задача | Приоритет | Часов | Исполнитель | Параллелится |
|---|---|---|---|---|---|
| 4a | Фикс holiday decomposer 500 | P0 | 1.5 | Маша (критично) | — |
| 4b | Single source of truth `validationMetrics` | P0 | 2 | Маша | — |
| 4c | Severity градация по ratio | P0 | 1 | Маша | — |
| 4d | «Далее» в Manager mode на «Метрики каналов» | P1 | 0.5 | Sonnet agent | да |
| 4e | Mode-aware тексты PerChannelInputSelector | P1 | 1 | Sonnet agent | да |
| 4f | Иерархия рекомендаций (конверсия first) | P1 | 2.5 | Маша | — |
| 4g | Финальный экран «Подтверждение» | P1 | 3 | Sonnet agent | да |
| 4h | Расширенный Expert mode (готовый код) | P2 | 1.5 | Sonnet agent | да |
| 4i | Кнопка «Применить рекомендации» | P2 | 1.5 | Sonnet agent | да |
| 5 | Аудит реализованного (red-team agent) | meta | 1 | Sonnet agent | finalize |
| 6 | Доработки по аудиту | meta | 1-2 | Маша | — |
| **Итого** |  |  | **~16-17 ч работы** |  |  |

---

## Что в backlog (отдельный sprint после rc2)

| Задача | Приоритет | Откладываем потому |
|---|---|---|
| U-05 Mode-aware инсайты на «Целевая метрика» | P1 | Большая структурная переделка `validateInsights` |
| U-06 Одна целевая метрика привязанная к KPI | P1 | Требует backend logic в `column_detection.py` |
| M-03 Англицизмы в subtitle (sign-ups → регистрации) | P2 | Косметика, в отдельном PR |
| M-04 «Только 99% R²» текст | P2 | Косметика |
| M-05 «Per-channel выбор единиц» англицизм | P2 | Косметика |
| M-06 Holdout валидация на графике | P2 | Backend changes (compute holdout split) |
| M-07 Технические параметры в Технической диагностике | P2 | Структурная переделка summary |
| P-01..P-04 polish | P3 | Косметика |

---

## Стратегия параллельной работы

### Маша (Opus 4.7 max) — критичные блоки сама:
- **4a holiday decomposer** — backend feature engineering, требует точности
- **4b validationMetrics store** — архитектурная переделка, влияет на 3+ компонента
- **4c severity градация** — простая логика, но user-facing критично
- **4f иерархия рекомендаций** — backend + frontend, эконометрически правильная логика

### Sonnet sub-agents — параллельно с чётким brief:
- **agent-A (4d)** — Manager «Далее» на «Метрики каналов»
- **agent-B (4e)** — Mode-aware тексты PerChannelInputSelector
- **agent-C (4g)** — Финальный экран «Подтверждение» (большая задача, но изолированная)
- **agent-D (4h)** — Подключить Expert панели (готовый код, простая работа)
- **agent-E (4i)** — Кнопка «Применить рекомендации»

### Аудит (5) — после всех правок:
- Sonnet red-team agent на новый код
- Прогон vitest + pytest + svelte-check
- Cross-check изменений с PILOT_FINDINGS

### Доработка (6) — Маша:
- Закрыть критичные находки аудита
- Финальный отчёт Антону

---

## Файлы которые точно тронем

### Backend (Python sidecar)
- `sidecar/econometrica/engines/decomposer.py` — фикс holiday injection (4a)
- `sidecar/econometrica/utils/holiday_calendar_ru.py` — может потребоваться helper для inject (4a)

### Frontend (Svelte)
- `src/lib/project-state.js` — derived store `validationMetrics` (4b)
- `src/lib/insights-rules.js` — severity градация для ratio-based warnings (4c)
- `src/lib/components/pipeline/RatioInfoCard.svelte` — мapping severity → текст/цвет (4c)
- `src/routes/pipeline/+layout.svelte` — sticky header читает из `validationMetrics` (4b)
- `src/lib/components/pipeline/ValidateStepV13.svelte` — Manager «Далее» + Expert pre-fill state (4d)
- `src/lib/components/pipeline/PerChannelInputSelector.svelte` — mode-aware тексты (4e)
- `src/lib/components/pipeline/AppliedModeSummary.svelte` — иерархия рекомендаций (4f, может быть)
- `src/lib/components/pipeline/ModeDerivedExplanation.svelte` — финальный summary (4g) — или новый ValidationSummary.svelte
- `src/lib/components/pipeline/ColumnMapperConfirm.svelte` — кнопка «Применить рекомендации» (4i)

### Документация
- `docs/RC2_REMEDIATION_PLAN.md` — этот файл
- `docs/PILOT_FINDINGS_CONSOLIDATED.md` — связан
- `docs/MASTER_PLAN_v2_1_0.md` — обновить со ссылкой на RC2 plan

---

## Acceptance criteria для каждой задачи

### 4a — holiday decomposer
- ✅ Декомпозиция запускается без 500 ошибки на модели обученной с РФ holidays
- ✅ Holiday columns корректно появляются в decomposition output (как «base sales» или «контрольные»)
- ✅ Unit test: model trained with holidays → decomposer.run() succeeds

### 4b — validationMetrics single source
- ✅ Sticky header / RatioInfoCard / Insights показывают **одинаковое** значение ratio в любом состоянии
- ✅ Манипуляции с frontend exclusions триггерят обновление всех 3 источников синхронно
- ✅ Unit test: store updates → all subscribers receive same value

### 4c — severity градация
- ✅ При ratio 2.8:1 показывается «warning высокий» (НЕ error)
- ✅ Текст не содержит слова «невозможно»
- ✅ Unit test: 5 ratio buckets → корректная severity + текст

### 4d — Manager «Далее»
- ✅ Кнопка «Далее ▶» появляется под AppliedModeSummary
- ✅ Активна когда все каналы корректно настроены (все ₽ или с конверсией)
- ✅ При клике переходит на под-шаг 4 «Подтверждение» с правильным state (5 каналов)

### 4e — Mode-aware тексты
- ✅ 3 версии текста (ROI / Эффективность / Mixed) корректно отображаются
- ✅ Текст в ROI режиме НЕ предлагает «контакты как альтернатива»
- ✅ Текст в Эффективность НЕ предлагает «деньги как альтернатива»

### 4f — Иерархия рекомендаций
- ✅ TRPs ТВ канал БЕЗ парного бюджета НЕ предлагается к исключению (предлагается конверсия)
- ✅ Инсайт «исключите N каналов» сначала предлагает альтернативы (объединение/конверсия)
- ✅ Основные media (ТВ, OLV, Banners) защищены от auto-exclusion без явных data quality проблем

### 4g — Финальный summary
- ✅ 5+ секций (контекст / каналы / controls / exclusions / quality / прогноз)
- ✅ Таблица каналов с ролями + единицами + итогами
- ✅ Quality metrics (ratio, период, VIF) согласованы с другими экранами

### 4h — Expert mode расширение
- ✅ CorrelationHeatmap + ExpertValidatePanel показываются под `{#if $expertMode}`
- ✅ Никаких новых тестов сломанных (re-use готовых компонентов)

### 4i — «Применить рекомендации»
- ✅ Кнопка появляется в `ColumnMapperConfirm.svelte`
- ✅ Batch применение через `setColumnRolesBulk`
- ✅ Анимация stagger flash на затронутых строках

---

## Timeline

| Время | Активность |
|---|---|
| T+0 | План создан (этот документ) |
| T+0:15 | Маша стартует 4a (holiday decomposer) |
| T+0:15 | 5 sub-agents запущены параллельно (4d/4e/4g/4h/4i) |
| T+1:30 | Маша заканчивает 4a, стартует 4b (validationMetrics) |
| T+3:00 | Маша заканчивает 4b, стартует 4c (severity) |
| T+3:30 | 5 sub-agents завершают, Маша забирает результаты + аудит |
| T+4:00 | Маша заканчивает 4c, стартует 4f (иерархия рекомендаций) |
| T+6:30 | Маша заканчивает 4f, запускает red-team аудит |
| T+7:30 | Маша получает результаты аудита, дорабатывает |
| T+8:30 | Все P0/P1 закрыты. Финальный отчёт Антону. |

---

## После завершения сессии

1. Commit + push всех правок (один логический commit на каждую задачу, или один большой rc2-batch)
2. Обновить `docs/MASTER_PLAN_v2_1_0.md` со статусом «RC2 правки сделаны»
3. Запросить у Антона **повторный пилот** на Кагоцел для верификации фиксов
4. Если пилот проходит — tag `v2.1.0-rc2`
5. Backlog задач (U-05, U-06, M-03..M-07, P-01..P-04) — отдельный sprint
