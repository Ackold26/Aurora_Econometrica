# Migration Guide: Aurora MMM Optimizer v1.3.x → v2.0.0

**Аудитория:** customers с существующими v1.3.x projects (`.aurora` bundles, in-progress pipelines).

**TL;DR:** обновитесь на v2.0.0, откройте проект как обычно — миграция автоматическая. Mixed-mode projects получают auto-Expert + toast notification.

---

## 🎯 Что меняется для customer

### Mode выбор стал явным (one-click)

**Было (v1.3.x):**
1. KPISelector (выбор target metric)
2. ColumnMapperConfirm (auto-detect ролей)
3. PerChannelInputSelector (per-channel: ₽ или физ. метрика)
4. ModeDerivedExplanation (mode выводится автоматически)

**Стало (v2.0.0 Manager mode):**
1. AnalysisModeSelector (**ROI или Эффективность одним кликом**)
2. KPISelector
3. ColumnMapperConfirm
4. AppliedModeSummary (read-only сводка: «Все каналы в ₽»)

**Expert mode** (opt-in через Settings → Expert toggle):
- + третья опция «Смешанный» в AnalysisModeSelector
- + per-channel control (как в v1.3.x)
- + UnitCostsPanel для ставок конверсии TRP → ₽

### Новые возможности

- **Diagnostics panel** — traffic-light статус модели (MCMC / Backtest / PPC / Sensitivity)
- **Multi-scenario comparison** — сравнить N планов на одной странице
- **Forecast task profile** (5-й) — загрузить план активностей → прогноз
- **Signed factors** — модель учитывает negative factors (конкуренты / цена / погода)
- **РФ-праздники** — 12 событий auto-injected (Новый Год / 8 марта / Чёрная Пятница / ...)

---

## 🔄 Что происходит при открытии v1.3.x project

Aurora automatically detects mode из bundle's `perChannelInput` field:

| Случай | `perChannelInput` содержит | Что вы увидите |
|---|---|---|
| **Pure monetary** | Все каналы = `'monetary'` | Открывается в **Manager ROI mode**. Silent migration. |
| **Pure physical** | Все каналы = `'physical'` | Открывается в **Manager Эффективность mode**. Silent migration. |
| **Mixed** | Часть `'monetary'`, часть `'physical'` | **Auto-Expert mode + toast notification**: «Ваш проект использует смешанный режим единиц. Управление per-channel доступно в Expert UI.» |
| **Empty/unknown** | Пусто или null values | **Auto-Expert mode + toast**: fallback safe default |

Customer data **не теряется**. Все existing fields preserved.

### Toast notification (mixed case)

```
┌──────────────────────────────────────────────────┐
│  ✓ Включён Expert mode                            │
│                                                    │
│  Ваш проект использует смешанный режим единиц    │
│  медиа-каналов (часть в ₽, часть в физических    │
│  метриках). Управление per-channel доступно      │
│  в Expert UI. Переключить режим — Settings.      │
│                                                    │
│  [Подробнее →]              [Понятно]            │
└──────────────────────────────────────────────────┘
```

Тост dismissible (10 sec auto-hide). После dismiss больше не показывается для этого project.

---

## 📊 Какие customer scenarios затронуты

### ✅ Не затронуты (продолжают работать как раньше)

- **Чистые ROI проекты** (FMCG, OTC фарма, e-commerce с budgets в ₽). Открываются в Manager ROI mode silent.
- **Чистые Эффективность проекты** (TV-heavy с TRP, бартер media). Открываются в Manager Эффективность mode silent.
- **In-progress pipelines** на любом stage (Validate / Train / Decompose / Optimize / Report). Текущий state сохраняется, можно продолжить.

### ⚠️ Auto-Expert (требуется внимание customer)

- **Смешанные projects** (бренды с TV в TRP + Performance в ₽). Получают toast + Expert mode UI. Все existing data + settings preserved.

### 🆕 Новые возможности (opt-in)

- **Multi-scenario comparison** — после Optimize появляется кнопка «Сравнить сценарии» (если ≥2 scenarios в project).
- **Forecast task** — в task selector новая опция «Прогноз по моему плану активностей».
- **Diagnostics panel** — автоматически появляется после Train. Manager видит traffic-light, Expert раскрывает details.

---

## 🧪 Math compatibility

**Bundle schema additive** (per ADR-017 + ADR-018). v1.3.x bundles загружаются без потерь:
- Existing `channel_params` (β, adstock, Hill) — preserved
- Existing `normalization` — preserved
- Existing `trace` (PyMC posterior samples) — preserved
- **NEW v2.0.0 fields** добавляются при следующем training:
  - `signed_factor_priors_used`
  - `holiday_dummies_injected`
  - `mcmc_diagnostics`
  - `backtest_results`
  - `ppc_results`
  - `sensitivity_tornado_cache`
  - `analysis_mode`

**Если открыть v1.3.x project без re-train:** все existing analytics доступны (Decompose / Optimize / Report). Diagnostics panel показывает «Модель обучена в v1.3.x — диагностика недоступна. Рекомендуем re-train для full v2.0.0 features.» Customer free to re-train (~5-10 min depending на data size) или продолжать с v1.3.x model.

---

## 🚨 Edge cases

### 1. Project с unit_costs (TRP → ₽ ставками)

`UnitCostsPanel` остаётся доступным в Expert mode (`expertMode=true` + `analysisMode='mixed'` + есть physical channels + monetary KPI). В Manager mode скрыт.

Customer с existing unit_costs:
- Если был Manual mode в v1.3.x → auto-Expert в v2.0.0 → UnitCostsPanel остаётся доступен
- Если был ROI / Effectiveness mode (без unit_costs) → Manager mode v2.0.0 → UnitCostsPanel hidden (не нужен)

### 2. Project с custom holiday columns в data

Если customer уже добавил own holiday columns (например, `holiday_brand_birthday`) в Excel — они **preserved**. Aurora auto-injects 12 РФ-events DOPOLNITELNO (не overwriting customer columns). Модель учитывает обе set's как control factors.

### 3. Project с competitor activity colonнами

v1.3.x — competitor columns могли быть classified как `media` или ignored. v2.0.0 — auto-detect classifies как `signed_competitor` с negative-leaning prior. После re-train customer видит negative contribution в WaterfallChart («−11% от конкурентов»).

### 4. Project с >24 месяцев истории

Same as v1.3.x — minimum 24 months (monthly grain) или 52 weeks (weekly) для valid model. v2.0.0 default monthly per РФ-стандарт.

---

## 🛠️ Manual override (для опытных эконометристов)

Если customer **не хочет auto-migration** для конкретного project:

1. Открыть project в v2.0.0
2. Settings → Expert mode toggle ON
3. AnalysisModeSelector → выбрать «Смешанный (Expert)»
4. PerChannelInputSelector становится доступен
5. Manually override per-channel input types

Эта конфигурация preserved в project state (`analysisMode='mixed' + expertMode=true`).

---

## 📞 Support

Возникли проблемы при migration? 

- **Telegram:** @aurora_econometrica_support
- **Email:** support@auroraai.pro
- **Documentation:** https://help.auroraai.pro/v2.0.0/migration

Готовы помочь с:
- Auto-Expert toast не появился но ожидался
- Existing analytics показывают другие результаты после migration
- Custom holiday/competitor columns не определились правильно
- Multi-scenario comparison page показывает empty state

---

## 📚 Дополнительные ресурсы

- **CHANGELOG_v2.0.0.md** — полный changelog с list of features
- **ADR-019** — архитектурное обоснование mode-change
- **PRE_FLIGHT_FIXES.md §B3** — technical migration algorithm
- **GAP_ANALYSIS_v1.md** — comparative analysis vs Robyn / PyMC-Marketing / Nielsen
