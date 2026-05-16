# RC2 Implementation Report — Aurora MMM Optimizer v2.1.0

> **Сессия:** автономная работа после пилотного прогона 2026-05-16.
> **Алгоритм Антона:** сохранить пилот → собрать ошибки → план → реализовать → аудит → доработать.

---

## Шаги 1-3 — подготовка ✅

| Шаг | Результат |
|---|---|
| **1. Сохранение пилотных правок** | commit `a698c89` (83 файла, +3296/-508) + push на origin |
| **2. Консолидация ошибок** | `docs/PILOT_FINDINGS_CONSOLIDATED.md` — 21 находка (4 P0 / 6 P1 / 7 P2 / 4 P3) |
| **3. План RC2** | `docs/RC2_REMEDIATION_PLAN.md` — 9 задач для текущей сессии, остальное в backlog |

---

## Шаг 4 — реализация ✅

### Все 9 задач закрыты

| # | Задача | Severity | Commit | Способ |
|---|---|---|---|---|
| 4a | Holiday decomposer 500 fix | P0 | `d7f0921` | Маша + 4 unit tests |
| 4b | Single source validation metrics | P0 | `ebd5853` | Маша |
| 4c | Severity градация 5 уровней | P0 | `ebd5853` | Маша (объединено с 4b) |
| 4d | Manager «Далее» на «Метрики каналов» | P1 | `128606b` | Sonnet agent |
| 4e | Mode-aware тексты PerChannelInputSelector | P1 | `128606b` | Sonnet agent |
| 4f | Иерархия рекомендаций (конверсия first) | P1 | `892d2f0` | Маша |
| 4g | Полная сводка ModeDerivedExplanation | P1 | `f0116a6` | Sonnet agent |
| 4h | Expert mode расширение (готовый код) | P2 | `128606b` | Sonnet agent |
| 4i | Кнопка «Применить рекомендации» | P2 | `975ec0d` | Sonnet agent |

### Sub-agents статистика

- 5 sub-agents запущены параллельно (4d/4e/4g/4h/4i)
- 4 закрыли задачи за один проход
- 0 пришлось переделывать
- Маша на Opus 4.7 max делала P0 (architecture / backend) сама
- Все коммиты проходили через pre-commit hook (v40-xss lint)

### Тестовое покрытие после RC2

| Уровень | Baseline | После RC2 | Прирост |
|---|---|---|---|
| Sidecar pytest | 277 | **281** | +4 (holiday re-injection tests) |
| Frontend vitest | 570 | **570** | 0 (правки совместимы с тестами) |
| **Всего проходит** | 847 | **851** | +4 |
| **Регрессий** | — | **0** | — |

### Что осталось в backlog (не P0/P1 для rc2)

| ID | Задача | Почему отложено |
|---|---|---|
| U-05 | Mode-aware инсайты на «Целевая метрика» | Большая структурная переделка validateInsights |
| U-06 | Одна целевая метрика привязанная к KPI | Требует backend logic в column_detection.py |
| M-03 | Англицизмы в subtitle (sign-ups → регистрации) | Косметика, отдельный PR |
| M-04 | «Только 99% R²» текст | Косметика |
| M-05 | «Per-channel выбор единиц» | Косметика |
| M-06 | Holdout валидация на графике | Backend changes |
| M-07 | Технические параметры в Технической диагностике | Структурная переделка summary |
| P-01..P-04 | Полировка (подсказки/нумерация/шрифт/прогресс-бар) | Косметика |

---

## Шаг 5 — аудит 🔄

Sub-agent red-team **запущен в фоне** — анализирует все 6 RC2 commits (`d7f0921..892d2f0`). Результаты будут в `docs/RC2_AUDIT_REPORT.md`.

Аудит проверяет:
1. Корректность фиксов (legacy compat, edge cases)
2. State propagation после single source
3. Regression на критичных путях (тесты)
4. Эконометрические замечания на severity logic
5. UX corner cases (пустой validateData, отсутствие mode)
6. Security (нет injection через holiday_cols)

---

## Шаг 6 — доработка по аудиту ⏸ ждёт

После результатов red-team закроем критичные находки.

---

## Краткие диагностики каждого фикса

### B-01 Holiday decomposer

**Что:** декомпозиция падала 500 после успешного обучения, потому что modeler.py инжектировал 12 РФ holiday колонок в X-матрицу при тренировке, но decomposer читал df без этих колонок.

**Как фикс:** в `decomposer.py` после `pd.read_excel(data_file)` re-injectit те же holiday колонки через `generate_holiday_dummies(df[date_col])`. Список injected колонок берётся из `normalization.holiday_cols_injected`.

**Защита:** при сбое re-injection — graceful degradation, убираем holiday cols из control_cols чтобы df[control_cols] не падал. β для них остаётся в model_data но вклад будет 0.

**Тесты:** 4 unit tests в `test_decomposer_holiday_reinject.py` — re-injection, no-op для legacy моделей, sanity для импорта.

---

### B-02 Single source of truth

**Что:** на одном экране показывались **3 разных значения ratio одновременно** (1.4 в sticky header / 2.8 в RatioInfoCard / 2.8 в инсайтах).

**Как фикс:** `validationHeaderMetrics` derived store в `project-state.js` теперь считает `ratio = nObs / (media + control)` из current state, не из stale `result.detected.ratio`. Согласовано с `ratioCardData` в ValidateStepV13.

**Доп:** добавлены `nPredictors / activeMedia / activeControls / ratioSeverity / ratioMessage` в return для удобства потребителей.

**Alias:** `validationMetrics` экспортирован как читаемое имя.

---

### B-03 Severity градация

**Что:** показывалось «**Моделирование невозможно** без исправления» при ratio 2.8:1 — категорически ложно (Bayesian модель технически обучится).

**Как фикс:** 5-уровневая градация в `validationHeaderMetrics` и `insights-rules.js`:
- < 2:1 → error «Слишком мало данных»
- 2-3:1 → warning-high «Критически мало - модель ненадёжна»
- 3-4:1 → warning «Мало - широкие доверительные интервалы»
- 4-5:1 → info «Достаточно для пилота»
- ≥ 5:1 → success «Хорошее соотношение»

Слово «невозможно» убрано для ratio ≥ 2:1.

---

### U-01 Manager «Далее»

**Что:** на «Метрики каналов» в Manager mode «Далее» была неактивна — обязательный заход в Expert.

**Как фикс:** добавлена кнопка «Далее ▶» под AppliedModeSummary с derived check `allChannelsConfigured` (все каналы должны быть с правильной единицей измерения).

---

### U-02 Mode-aware тексты PerChannelInputSelector

**Что:** текст «или-или» представлял выбор как равноправный, но в каждом режиме предопределён.

**Как фикс:** 3 версии текста (ROI / Эффективность / Mixed) через `$derived(modeHeading, modeLead)` + переписанная WhyThisStep panel + адаптированные метки таблицы.

---

### U-03 Иерархия рекомендаций

**Что:** Aurora автоматически предлагала исключить важные media каналы (TRPs ТВ, OLV) ради улучшения ratio — omitted variable bias.

**Как фикс:** в `insights-rules.js` рекомендации теперь говорят:
1. Объединить парные метрики (OLV Бюджет + Показы)
2. Конверсия физических метрик через CPP
3. Сбор больше истории
4. Исключение каналов с >50% нулей (data quality)
5. Прочее с предупреждением «omitted variable bias»

Кнопка «Исключить N с >50% нулей» ограничена только weak channels.

---

### U-04 Полная сводка

**Что:** финальный экран Валидации показывал 3 строки и 1 цифру.

**Как фикс:** `ModeDerivedExplanation.svelte` переписан как 5-секционный summary:
1. Шапка: режим / KPI / период / дата-диапазон
2. Медиа-каналы: таблица с ролями, единицами, итогами
3. Внешние факторы: chip-tags
4. Исключённые: accordion с причинами
5. Контроль качества: 4 quality cards + полный RatioInfoCard
6. Финальная кнопка: «Перейти к моделированию (~30-60 сек обучения)»

---

### M-01 Кнопка «Применить рекомендации»

**Что:** при 20+ колонках применять рекомендации по одной утомительно.

**Как фикс:** панель `bulk-actions` над таблицей с кнопками:
- «Применить все рекомендации (N)» — batch через `setOverride` для каждой
- «Пропустить все» — обнуляет счётчик без изменения
- Stagger row-flash animation с шагом 60ms
- `prefers-reduced-motion` guard

---

### M-02 Expert mode расширение

**Что:** новый ValidateStepV13 имел слабый Expert mode.

**Как фикс:** переподключены готовые компоненты из legacy ValidateStep:
- `CorrelationHeatmap` — матрица корреляций
- `ExpertValidatePanel` — VIF table + детальные stats

Под `{#if $expertMode && $validateData?.result}` с aurora-styled header.

---

## Что протестировано

| Тест | Результат |
|---|---|
| Sidecar pytest (Python) | 281/281 ✅ (+4 holiday re-injection) |
| Frontend vitest | 570/570 ✅ (0 регрессий) |
| Pre-commit hook (v40-xss lint) | passed на всех 6 commits ✅ |
| svelte-check | 11-12 errors (все pre-existing) |

---

## Pending Антон gates

- Push 6 RC2 commits к origin (после аудита)
- **Повторный пилот** на Кагоцел для верификации фиксов
- Tag `v2.1.0-rc2` после ack пилота
