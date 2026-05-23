# Aurora MMM Optimizer v2.0.0 — Wizard Flow & Architecture (FINAL)

**Дата:** 2026-05-14
**Author:** Маша маленькая
**Status:** FINAL — basis для ADR-019 + execution plan
**Supersedes:** `WIZARD_FLOW_DRAFT_v1.md`, `V1_4_0_EXPLICIT_MODE_PLAN.md` (deprecated)
**Sister docs:** `INTERVIEW_NOTES.md`, `GAP_ANALYSIS_v1.md`, `V2_1_0_PLUS_ROADMAP.md`
**Related ADRs:** будет ADR-019 (supersedes ADR-015), сохраняет ADR-014, ADR-016

---

## TL;DR

ScenarioWizard 3-7 шагов (3-4 active в типовом случае, до 7 в ambiguous data). **Auto-detect делает 60-80%** работы через расширенный variable classifier. Wizard спрашивает task intent + disambiguation. Pipeline после training включает: MCMC convergence traffic light, backtest holdout, PPC validation, sensitivity tornado, forecast continuation chart с overlay scenarios. Multi-scenario comparison — отдельная страница после Optimize.

**Scope v2.0.0:** ~4 недели благодаря reuse существующих наработок (Save/Load, Waterfall, SCQAR executive, 10 KPI types, signed factors backend partially).

---

## §0 Paradigm & Principles

### 0.1 Core paradigm

«Программа сама подводит проект к нужному шаблону. Категория вторична — первична задача.»

- **NOT TemplateGallery** (каталог карточек выбираемых).
- **YES ScenarioWizard** (диагностический мастер, derives конфигурацию из данных + минимального диалога).

### 0.2 4-factor decomposition

| Фактор | Источник | Влияет на |
|---|---|---|
| F1 Activity status | Auto-detect (history длина, gaps) | Optimizer / Launch / Brand / Trade — cross-product redirect |
| F2 Output type | Auto-detect (target column type) | KPI kind + type |
| F3 Media input type | Auto-detect (channel column types) | Mode (ROI / Effectiveness / Expert mixed) |
| F4 Task intent | **Wizard вопрос** | Task profile (5 options) |

Категория (FMCG / OTC фарма / ритейл / e-commerce и т.д.) — **enhancement layer** поверх (terminology / insights flavor), не primary axis.

### 0.3 Cross-product escape strategy

Если wizard детектирует что задача за пределами Optimizer scope:

- **History <24 мес / >50% gap** → «Это случай для Launch Planner (proxy-MMM)» + escape в Expert mode
- **Awareness/ЗПЛ goal** → «Это случай для Brand Tracker» + escape в Expert
- **Promo/pricing focus** → «Это случай для Trade & Pricing» + escape в Expert

**Не redirect** (другой продукт может быть не установлен). **Escape в Expert mode** — даёт пользователю math machinery без guidance.

### 0.4 Manager vs Expert modes (INV-25)

| Aspect | Manager (default 80%+) | Expert (opt-in via `$expertMode`) |
|---|---|---|
| Entry point | ScenarioWizard | Direct project setup |
| Wizard | 3-7 шагов до train | Skippable (start с пустого) |
| KPISelector | 2 главных категории (Денежный / Штучный), specific = default | Все 10 specific types visible |
| Mode selection | One выбор (ROI / Эффективность) | + 3-я опция «Смешанный (Expert)» |
| PerChannelInputSelector | HIDDEN, replaced by AppliedModeSummary | VISIBLE per-channel control |
| UnitCostsPanel | HIDDEN | VISIBLE при mixed + monetary KPI + physical channels |
| Diagnostics panel | Traffic-light summary (MCMC convergence / backtest / PPC) | Full plots, trace, sensitivity tornado, prior sensitivity |
| Multi-scenario page | Visible если ≥2 scenarios | Visible always (можно добавить scenarios) |

### 0.5 Соответствие invariants

- **INV-04** Don't supersede ADR без re-confirm — ADR-019 (после написания) явно supersedes ADR-015 с обоснованием
- **INV-15** Adapter wiring path completeness — wizard state flows через `wizardState` store без breaks
- **INV-17** Single source of truth для UI metrics — `analysisMode` store как SSOT для mode
- **INV-25** Dual-mode UX — реализуется AnalysisModeSelector + diagnostics panel
- **INV-30** MMM single-unit preference — реализуется Manager 2 modes + Expert mixed

---

## §0.6 Wizard State Lifecycle (added pre-flight audit B2)

### State machine

```
                  ┌─────────────────────────────────────┐
                  │           IDLE (no project)         │
                  └────────────┬────────────────────────┘
                               │ user creates new project
                               ▼
                  ┌─────────────────────────────────────┐
                  │      WIZARD_PENDING                 │
                  │  (project created, no data yet)     │
                  └────────────┬────────────────────────┘
                               │ user imports data through Studio
                               ▼
                  ┌─────────────────────────────────────┐
                  │      AUTO_DETECTING                 │
                  │  (Studio runs variable classifier)  │
                  └────────────┬────────────────────────┘
                               │ classifier complete
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
        ┌───────────┐  ┌─────────────┐  ┌──────────┐
        │ ESCAPE    │  │ WIZARD_     │  │ AUTO_    │
        │ (history  │  │ ACTIVE      │  │ FILLED   │
        │  <24mo or │  │ (data OK,   │  │ (all 4   │
        │  no media)│  │  show steps)│  │  factors │
        └─────┬─────┘  └──────┬──────┘  │  clear,  │
              │               │         │  skip to │
              ▼               │         │  Step 6) │
        ┌───────────┐         │         └────┬─────┘
        │ EXPERT_   │         │              │
        │ MODE      │         │              │
        │ (escape)  │         │              │
        └───────────┘         │              │
                              ▼              ▼
                       ┌─────────────────────────┐
                       │   step navigation       │◀──┐
                       │   (1→2→3→4→5→6)         │   │
                       │   may skip silent steps │   │
                       └────────┬────────────────┘   │
                                │ user back-nav      │
                                └────────────────────┘
                                │ user runs Step 6
                                ▼
                       ┌────────────────────────┐
                       │  RUNNING (Train→...)   │
                       │   wizard state frozen  │
                       └────────┬───────────────┘
                                │ training complete
                                ▼
                       ┌────────────────────────┐
                       │   COMPLETED            │
                       │   results visible      │
                       │   wizard read-only     │
                       └────────────────────────┘
```

### Lifecycle events

| Event | Behavior |
|---|---|
| **New project create** | `wizardState = WIZARD_PENDING`. Show wizard placeholder. |
| **Data import (Studio bundle)** | `wizardState = AUTO_DETECTING`. Run classifier. |
| **Auto-detect complete + quality gates pass** | Transition to `AUTO_FILLED` (if F1+F2+F3 resolved with confidence ≥0.95 each, only F4 missing) или `WIZARD_ACTIVE` (some disambiguation needed). |
| **Quality gate fail** | Transition to `ESCAPE` state. Show explanation + offer Expert mode. |
| **User clicks Expert escape** | Migrate to `expertMode=true`, preserve detected factors as pre-filled values, no wizard. |
| **Step submit** | Save wizard state to `wizardState` store. Advance step. |
| **Back navigation to earlier step** | **Invalidation rule** — see below. |
| **User clicks Run в Step 6** | Freeze wizard state → Train pipeline starts. Wizard becomes read-only. |
| **Training complete** | `wizardState = COMPLETED`. Wizard visible как audit trail. |
| **Load existing project** | If `wizardState` exists в bundle — restore. If absent (v1.3.x project) → run migration logic (см. §M). |
| **Edit existing project (change inputs)** | If project COMPLETED — re-open wizard в `WIZARD_ACTIVE` from Step 1 с pre-filled values (user must confirm каждый шаг since data changed). |
| **Abandon project mid-wizard** | wizardState persisted в localStorage (per session). Reopen → resume from last step. |

### State persistence

| Where | What | When written |
|---|---|---|
| `wizardState` store (in-memory Svelte) | active session state | every step submit |
| `localStorage` (project-scoped key) | partial state for resume on abandon | every step submit |
| `bundle.json` field `wizard_state` | frozen state at training time | on Step 6 Run |
| `bundle.json` field `analysisMode` | derived mode | on Step 6 Run |
| `bundle.json` field `wizard_history` | optional audit log of changes | on Step 6 Run + on Edit |

### Back-navigation invalidation rules

If user navigates back и changes а **higher-priority factor**, lower-priority steps invalidate (must re-confirm):

- **Step 1 change (task intent)** → invalidate Steps 4, 5, 6 (plan inputs differ per task; context may differ)
- **Step 2 change (target metric)** → invalidate Steps 3, 4, 5, 6 (KPI affects mode default; plan inputs reflect KPI)
- **Step 3 change (media inputs)** → invalidate Steps 4 (planned bounds reflect channel set), 6
- **Step 4 change (plan)** → invalidate Step 6 (summary recomputed)
- **Step 5 change (context)** → invalidate Step 6
- **Step 6 — no back-effect** (last step, only Run или Edit)

UX: при back-navigation if any invalidation triggered, show inline warning «Изменение этого шага потребует пересмотреть Step X, Y, Z. Продолжить?» с [Yes, change] [Cancel].

### Manager ↔ Expert sync

| User action | Result |
|---|---|
| Manager Step 6 → click «Изменить настройки (Expert)» | `$expertMode = true`. Wizard state preserved as pre-filled Expert form values. Wizard hidden. Expert UI shows wizard's derived configuration editable. |
| Expert mode → user clicks «Вернуть в Manager wizard» (button в Expert UI) | If Expert form values still match valid Manager configuration (single-unit mode, no custom unit_costs, etc.) → `$expertMode = false`, wizard reopens at Step 6 с preserved state. Если Expert модify сделал invalid for Manager (mixed mode + custom unit_costs) → blocked: «Конфигурация требует Expert mode. Нельзя вернуться в Manager без сброса.» с [Continue Expert] [Reset & Start Manager wizard] |
| User toggles `$expertMode` в Settings (anywhere) | If active wizard exists и user в middle of wizard — confirm dialog «Переключение в Expert mode остановит wizard. Continue?» |

### Edge case: data re-import

User uploaded data, started wizard, then re-imports new data (corrected file):
- `wizardState` clears
- Run AUTO_DETECTING again
- Re-show user wizard from Step 1 (или AUTO_FILLED if everything resolves)
- Pre-filled values cleared (new data may have different structure)

---

## §1 Pre-step: Import + Auto-detect

Перед первым шагом wizard'а — обязательная стадия импорта данных через Aurora Data Studio с одновременным auto-detect.

### 1.1 Data import

Принимаем:
- Excel (`.xlsx`)
- CSV
- Data Studio bundles (через source adapters: DSM, Mediascope, AdEx, TV Index, Excel/CSV)

### 1.2 Variable classifier (extended)

Расширяем существующий `column_detection.py` до полной типизации. **Distinct categories:**

**Target metrics (расширенный список, 13 types):**

| Type | Aliases (RU/EN) | Magnitude signature | KPI kind |
|---|---|---|---|
| sales_rub | продажи_рубли, выручка, sales_rub, revenue | currency-magnitude, summable | monetary |
| sales_packs | продажи_упаковки, упак, units, packs, шт | small-int (100s-1000s) | count |
| revenue | доход, gross_revenue | currency | monetary |
| profit | прибыль, profit, margin, маржа | currency | monetary |
| leads | лиды, заявки, leads, applications | int 10-10000 | count |
| registrations | регистрации, sign-ups, signups, активации | int | count |
| subscriptions | подписки, subs, MRR-units | int small-medium | count |
| applications | заявления, applications (финуслуги) | int | count |
| bookings | бронирования, bookings, заказы (travel) | int | count |
| transactions | транзакции, transactions (e-commerce) | int large | count |
| traffic | трафик, traffic, visits (retail) | int large | count |
| loyalty_cards | карты лояльности, loyalty_cards | int | count |
| app_installs | установки, installs, app_installs | int | count |
| custom | fallback for unrecognized numeric | — | count |

**Media formats (15 channel types):**

TV / Digital (display) / OLV (online video) / Performance (search/context) / Social / OOH / Print / Radio / Cinema / Аптечный OOH / Retail Media (in-store) / Influencer / Email-CRM / Programmatic / Affiliates

Detection rules:
- Name prefix/suffix (`tv_*`, `digital_*`, `ooh_*`, `*_grp`, `*_trp`)
- Magnitude signature (TRP 0-100, GRP 0-500, impressions 1k-1M, clicks 100-100k, OTS millions)
- Cross-correlation patterns

**Media metrics:** TRP / GRP / impressions / clicks / views / OTS / contacts / reach / frequency / VTR / CTR

**Budget:** spend_rub (currency, per-channel или aggregate)

**Signed control factors** (NEW — расширение existing `CONTROL_PATTERNS` в `validator.py`):

| Type | Patterns | Sign expectation |
|---|---|---|
| **competitor** | `competitor_*`, `*_конкурент*`, `share_of_voice_competitors`, `comp_trp`, `comp_spend` | **Negative** (their activity reduces our sales) |
| **price** | `price_*`, `цена_*`, `avg_price`, `price_index` | **Signed unconstrained** (positive when premium, negative when promo-driven) |
| **weather** | `weather_*`, `temp_*`, `precipitation`, `погода` | **Signed unconstrained** (category-dependent) |
| **macro** | `cpi`, `gdp`, `inflation`, `fx_*`, `usd_rub` | **Signed unconstrained** |

**Positive control factors** (existing, no change):

| Type | Patterns |
|---|---|
| distribution | distribution, дистрибуция, weighted_dist, numeric_dist |
| trade_activity | trade_activity_score, trade_*, промо-активность |
| promo (positive sign in this category) | promo_indicator (boolean) |
| product_launches | new_sku_count, launch_*, npd_* |

**External factors (auto-derived):**

| Type | Source |
|---|---|
| seasonality | Derived from target_brand_historical через STL decomposition |
| holiday_* | **Auto-injected from РФ holiday calendar** (см. §1.3) |

### 1.3 РФ Holiday auto-injection (silent)

После Variable classifier — automatic injection 10-12 hardcoded РФ holiday dummies. **Не спрашивается у user**, происходит silent в Studio bundle stage.

**File:** `sidecar/econometrica/utils/holiday_calendar_ru.py` (NEW)

**Holidays (Variant B):**

| Dummy column | Period | Category | Pre/post |
|---|---|---|---|
| `holiday_newyear_preshop` | 15-31 декабря | gift | pre-period (закупки подарков) |
| `holiday_newyear_postsale` | 25 декабря - 8 января | commercial | post-period (новогодние распродажи + январские) |
| `holiday_valentine` | 1-14 февраля | gift | pre-period |
| `holiday_defender_day` | 15-23 февраля | gift | pre-period (23 февраля shopping) |
| `holiday_march8` | 1-8 марта | gift | pre-period |
| `holiday_may_holidays` | 28 апреля - 9 мая | general | full window |
| `holiday_russia_day` | 11-12 июня | general | full window |
| `holiday_back_to_school` | 15 августа - 1 сентября | category_specific | pre-period |
| `holiday_unity_day` | 3-4 ноября | general | full window |
| `holiday_black_friday` | last Friday of November + weekend | commercial | event window |
| `holiday_cyber_monday` | первый понедельник после Чёрной пятницы | commercial | event window |
| `holiday_school_breaks` | 4 окна / год (осенние / новогодние / весенние / летние каникулы) | family | windows |

**Logic:** model подхватывает их как control factors (already в `CONTROL_PATTERNS` через `holiday`). Coefficient per holiday dummy estimated в Bayesian model с zero-centered Gaussian prior (unconstrained sign).

### 1.4 Quality gates check

Per `budget_optimization.yaml` task profile:

| Gate | Check | Action |
|---|---|---|
| `history_minimum` | ≥24 months OR ≥52 weeks | BLOCK if fail → escape to Expert / Launch Planner suggestion |
| `active_advertising` | ≥50% obs with non-zero spend | BLOCK if fail → escape to Launch |
| `spend_variation` | CoV ≥0.3 per channel | WARN (Hill saturation не идентифицируется) |
| `channel_collinearity` | Pairwise correlation ≤0.95 | WARN (collinear channels — interpretation difficult) |
| `channel_coverage_optimization` | All channels в optimization set присутствуют в history | BLOCK if fail → reroute to Launch с benchmark |

### 1.5 Output to wizard state

```js
{
  data_signature: {
    history_months: 36,
    history_grain: 'weekly',
    cutoff_row: 156,
    active_advertising_pct: 0.78,
    target_candidates: [
      { column: 'sales_packs', confidence: 0.95, kpi_kind: 'count', kpi_type: 'sales_packs' },
      { column: 'sales_rub', confidence: 0.92, kpi_kind: 'monetary', kpi_type: 'sales_rub' },
    ],
    channels: [
      { name: 'TV', input_type: 'physical', metric: 'TRP', confidence: 0.9 },
      { name: 'Digital', input_type: 'monetary', metric: 'rub', confidence: 0.95 },
      { name: 'OOH', input_type: 'physical', metric: 'OTS', confidence: 0.85 },
      { name: 'Performance', input_type: 'physical', metric: 'clicks', confidence: 0.9 },
    ],
    positive_controls: {
      trade_activity_score: 'detected',
      distribution: 'detected',
    },
    signed_controls: {
      competitor_trp: 'detected',
      price_average: 'derivable',
    },
    holidays_injected: 11, // count
    quality_gates: {
      history_minimum: 'pass',
      active_advertising: 'pass',
      spend_variation: 'pass',
      channel_collinearity: 'warn (TV-Digital 0.81)',
      channel_coverage: 'pass',
    },
  },
  resolved_factors: {
    F1_activity: 'established',
    F2_output: 'count_packs',  // если ambiguous → null + Step 2 asks
    F3_media_input: 'mixed',    // ambiguous → Step 3 asks
    F4_task: null,              // wizard asks Step 1
  },
  best_practice_warnings: [
    { channel: 'Performance', detected: 'clicks', recommendation: 'OK', severity: 'info' },
    { channel: 'OLV', detected: 'clicks', recommendation: 'use views', severity: 'warn' },
  ],
}
```

---

## §2 Wizard Steps (detailed)

### 2.1 Шаг 1 — Task intent (F4)

**Вопрос:** «Что вы хотите получить от анализа?»

**5 опций (one-of):**

| # | Опция | Maps to | Описание (без жаргона) |
|---|---|---|---|
| 1 | **Распределить плановый бюджет по каналам** | `budget_optimization` | «У меня бюджет на следующий период, хочу понять как распределить между каналами» |
| 2 | **Достичь цели — сколько потратить?** | `inverse_optimization` | «У меня цель продаж, хочу узнать минимальный бюджет для её достижения» |
| 3 | **Найти оптимальный размер бюджета** | `what_if` | «Хочу понять, где saturation — имеет ли смысл наращивать бюджет» |
| 4 | **Прогноз по моему плану активностей** | `forecast_planned_activities` (NEW) | «Я уже спланировал кампанию, хочу узнать что прогнозирует модель» |
| 5 | **Просто декомпозировать прошлый период** | `decompose-only` | «Понять вклад каждого канала в прошлом периоде, без оптимизации» |

**UX:** карточки с Lucide-иконкой + business-question формулировкой.

**Cross-product check (immediate):**
- Если выбрано 4 (forecast) и F1=Launch-like (history <24 мес) → «Прогноз требует обученной модели, у вас данных мало. Aurora Launch Planner — для нового продукта с прокси-категорией.»
- Если выбрано 5 (decompose-only) и нет рекламной истории → «Декомпозицию запустить можно, но интервалы будут широкие.»

### 2.2 Шаг 2 — Target metric confirm

**Условный:** показывается если auto-detect не однозначен (≥2 candidates) ИЛИ count KPI (нужна value_per_count_unit).

**UI (single candidate, monetary):** silent auto-confirm, не показывается.

**UI (multiple candidates):**
```
Какой целевой показатель будем оптимизировать?
● Продажи в упаковках (sales_packs) — рекомендовано
○ Выручка в рублях (sales_rub)
○ Другое (выбрать вручную из колонок)
```

**UI (count KPI sub-step):**
```
Ценность одной упаковки (маржа), ₽:
[_______ ₽]   

(auto-suggest на основе категории: для OTC фарма обычно 30-150 ₽/упак)
```

В Manager mode — generic label «Ценность единицы». В Expert mode — per-KPI specific («Маржа на упаковку», «Ценность лида = LTV × CR», «MRR на подписку»).

### 2.3 Шаг 3 — Media inputs confirm

**Условный:** silent if все каналы в одной единице И no best-practice warnings.

**UI (mixed / ambiguous):**

```
Канал          Auto-detected           Confidence   [Confirm/Change]
────────────────────────────────────────────────────────────────
TV             TRP (физика)                  90%   ▾
Digital        Бюджет в ₽                    95%   ▾
OOH            OTS (физика)                  85%   ▾
Performance    Клики (физика)                90%   ▾

⚠ Performance: рекомендуем клики (у вас клики ✓)
⚠ OLV: рекомендуем просмотры (у вас клики — менее точно для OLV)
ℹ TV TRP должны быть приведёнными (gross или net consistent)

────────────────────────────────────────────────────────────────
Текущая конфигурация: смешанная (1 канал в ₽ + 3 физика)
Программа предлагает: режим ROI с CPU

Manager Mode рекомендация: выбрать один режим единиц
○ Все каналы в ₽ (требует прохода через unit conversion для TRP/OTS)
● Все каналы в физических метриках (Эффективность)
○ Оставить смешанным (включить Expert mode для unit_costs ставок)
```

**Best-practice warnings library (см. §1.2):**
- Performance → clicks (warn if impressions)
- OLV → views (warn if clicks)
- Display → impressions (warn if clicks)
- TV TRP → приведённые
- OOH → OTS (warn if impressions)
- Mixed + monetary KPI → recommend single режим

Warnings = soft, не block.

### 2.4 Шаг 4 — Plan inputs (task-specific)

#### Task 1: `budget_optimization`
```
Плановый бюджет на следующий период:
[_______ ₽]  (default: средний бюджет последней активной кампании = 50М ₽)

Период оптимизации:
[12 ▾] [месяцев ▾]   ← unit auto-set from data grain (monthly default РФ-стандарт)
                       weekly если data signature weekly

Дополнительные ограничения по каналам? [Skip] [Указать]
  └─ Если Указать: таблица min%/max% per канал
```

#### Task 2: `inverse_optimization`
```
Целевое значение:
○ Абсолютное: [_______] упаковок
● Прирост: [+__%]   (default: +10%)

Период:
[12 ▾] [месяцев ▾]   ← monthly default
```

#### Task 3: `what_if`
```
Диапазон бюджетов для сравнения:
○ Базовый ±20%
● Базовый ±50%
○ Custom: от [____] до [____] ₽

Период:
[12 ▾] [месяцев ▾]   ← monthly default
```

#### Task 4: `forecast_planned_activities` (NEW)
```
Загрузите файл с плановыми активностями:
[📁 Выбрать Excel] [Excel template] [Manual entry]

Auto-validation:
✓ Каналы соответствуют trained model (TV / Digital / OOH / Performance)
✓ Период покрывает 12 недель (cuts off model history до 2026-09-01)
⚠ Канал «Print» в плане отсутствует в trained model — будет проигнорирован

Опционально — изменения non-media:
○ Без изменений (default)
○ Указать planned distribution / promo / price изменения
```

#### Task 5: `decompose-only`

Skip Шаг 4 — нет плановых inputs. Декомпозиция строится только на исторических данных.

### 2.5 Шаг 5 — Context (опциональный)

**Условный:** показывается только если есть **новые / неподтверждённые** non-media factors. Auto-detect items не требуют confirm если confidence ≥0.9 (silent injection).

**UI (если ambiguous):**
```
Программа обнаружила дополнительные факторы:
✓ Trade activity score (баллы 0-5) — auto-detected, used
✓ Дистрибуция — auto-detected, used
✓ 11 РФ-праздников — auto-injected (Новый Год / 8 марта / 9 мая / ...)
⚠ Активность конкурентов (competitor_trp) — обнаружено, использовать? [✓ Да] [✗ Нет]
⚠ Цена (price_average) — derive from sales_rub/sales_packs? [✓ Да] [✗ Нет]

Планируется ли изменение non-media в плановом периоде?
○ Нет (default)
○ Да — указать distribution / trade / price плановые значения
```

### 2.6 Шаг 6 — Summary + Diagnostics + Run

**ВАЖНО:** этот шаг показывается **после Train** (model уже обучена). Backtest + MCMC + PPC автоматически рассчитываются в training pipeline. На Summary показывается их results.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Программа поняла вашу задачу:                                     │
│                                                                     │
│  📊 Сценарий                                                       │
│     Оптимизация медиа-бюджета для established бренда                │
│     Категория: OTC фарма (auto-detect — для подсказок)              │
│                                                                     │
│  🎯 Цель                                                           │
│     Распределить плановый бюджет 50 млн ₽ на 12 недель              │
│     между 4 каналами: TV, Digital, OOH, Performance                 │
│                                                                     │
│  📐 Эконометрический режим                                         │
│     Эффективность (все каналы в физических метриках)                │
│     • TV = TRP (приведённые), Digital = bytes (но юзер выбрал phys.)│
│     • OOH = OTS, Performance = clicks                               │
│     • KPI = продажи в упаковках, ценность = 80 ₽/упак               │
│                                                                     │
│  🔢 Тип расчёта                                                    │
│     Forward budget optimization (Robyn-style)                       │
│                                                                     │
│  ─────────────────────── ДИАГНОСТИКА МОДЕЛИ ──────────────────────  │
│                                                                     │
│  🟢 Сходимость (MCMC): R-hat 1.02, ESS 1240 — OK                   │
│  🟢 Backtest (4 недели holdout): MAPE 8.2%, RMSE 1.4К упак — OK    │
│  🟢 Posterior predictive: R² 0.91 на observed, без bias residuals  │
│  🟡 Sensitivity TV-adstock ±20% → ROI меняется на ±15% (нормально) │
│                                                                     │
│  ─────────────────────── ВНЕШНИЕ ФАКТОРЫ ────────────────────────  │
│                                                                     │
│  ✓ Активность конкурентов учтена: -11% вклад в продажи              │
│  ✓ РФ-праздники (11 событий) учтены: суммарный вклад +5%            │
│  ✓ Дистрибуция учтена: +12% вклад                                   │
│  ✓ Цена учтена: -3% вклад                                           │
│                                                                     │
│  ⚠ Soft-recommendations (можно проигнорировать)                    │
│     • Performance — клики OK                                        │
│     • TV-Digital correlation 0.81 (warn, не block)                  │
│                                                                     │
│  [Запустить анализ →]  [Изменить настройки (Expert)]                │
│  [💾 Сохранить модель]  [📥 Скачать model.json]                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Actions:**
- **Запустить анализ** → переход к Decompose → Optimize → Report
- **Изменить настройки** → Expert mode с pre-filled values, юзер может править
- **Сохранить модель** → reuse `engines/persistence.py` (already done)
- **Скачать model.json** → JSON export (0.5-1 день new code, см. §6)

---

## §3 Pipeline: post-wizard flow

После Run wizard сложен. Pipeline продолжается:

### 3.1 Train → Decompose → Optimize (или Forecast) → Report

| Стадия | Что меняется в v2.0.0 |
|---|---|
| **Train** | + автоматический backtest holdout (last 4-8 weeks) + MCMC convergence check + PPC (actual vs predicted scatter, residual time series). Outputs в diagnostics panel |
| **Decompose** | + signed factor support — negative bars в WaterfallChart (extending existing component). Insights текст: «Активность конкурентов забрала 11%, ваша Performance дала +31%, чистый эффект рекламы +20% сверх базы» |
| **Optimize** | unchanged для tasks 1-3, + новый `forecast_planned_activities` task profile (5-й) |
| **Multi-scenario page (NEW)** | отдельная страница (см. §4) если ≥2 сценариев в проекте. Сравнение Plan A vs Plan B vs Aurora-optimized |
| **Report** | + sensitivity tornado chart как раздел отчёта. + signed factor narrative. Executive summary SCQAR — reuse existing |

### 3.2 Diagnostics panel

Новый раздел в pipeline (между Train и Decompose). Manager видит **traffic-light summary**. Expert разворачивает **full plots**.

**Manager view:**
```
┌──────────────────────────────────────────┐
│  ДИАГНОСТИКА МОДЕЛИ                      │
│                                          │
│  Сходимость:    🟢 R-hat 1.02, ESS 1240  │
│  Backtest:      🟢 MAPE 8.2%             │
│  Validation:    🟢 R² 0.91               │
│  Sensitivity:   🟡 ±15% к adstock TV     │
│                                          │
│  [Подробнее ▾]                           │
└──────────────────────────────────────────┘
```

**Expert view (expanded):**
- Trace plots (MCMC chains)
- ESS per parameter (table)
- Posterior pairs plot (key params)
- Actual vs predicted scatter (PPC)
- Residual time series + autocorrelation
- Sensitivity tornado bar chart
- Per-parameter prior sensitivity table

### 3.3 Continuation chart (main forecast viz)

После Optimize / Forecast — main visualization (как на скрине от Антона):

- X: full timeline (history + forecast horizon)
- Y: KPI (sales_packs / sales_rub / leads / etc.)
- Lines:
  - **Actual** (solid orange) — historical observed
  - **Model fit** (solid dark) — in-sample model prediction
  - **Forecast scenario(s)** (red solid / dotted) — future projections
- **Endpoint labels** на каждом scenario tail
- **CI ribbons 90%** на forecast lines (Bayesian уверенность)
- **Vertical divider** на cutoff (где actual заканчивается)
- **Clickable legend** (toggle scenarios)
- **Hover tooltip** per-period values + per-channel breakdown

---

## §4 Multi-scenario comparison page (Variant B)

**Новая страница** в pipeline между Optimize и Report. Visible если в проекте ≥2 scenarios.

### 4.1 Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  СРАВНЕНИЕ СЦЕНАРИЕВ                                                 │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ [Continuation chart with multi-scenario overlay]              │ │
│  │  History → Model fit → 4 scenarios with endpoint labels       │ │
│  │  CI ribbons, clickable legend, hover tooltip                  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Сценарий          | Budget  | Predicted KPI  | CI 90%   | Δ%  │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ Базовый           | 50.0M ₽ | 245K упак      | 230-262K | —    │ │
│  │ План А (мой)      | 50.0M ₽ | 264K упак      | 248-281K | +7.8 │ │
│  │ План B (мой)      | 70.0M ₽ | 312K упак      | 293-330K | +27.3│ │
│  │ Aurora-optimized  | 50.0M ₽ | 281K упак      | 265-298K | +14.7│ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Per-channel breakdown:  [Развернуть ▾]                              │
│                                                                      │
│  Анализ:                                                             │
│  • План B даёт +27.3% KPI при +40% budget — высокая marginal стоимость роста │
│  • Aurora-optimized превосходит План А на +6.4% при том же бюджете   │
│    основная экономия — shift TV → Digital                            │
│                                                                      │
│  Действия:                                                           │
│  [Export comparison ▾]  [Принять сценарий как plan ▾]                │
│  [Дублировать и изменить ▾]  [Удалить сценарий ▾]                    │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.2 Components

- **MultiScenarioChart** — extension continuation chart с поддержкой N overlaid scenarios
- **MultiScenarioTable** — comparison table со sortable columns
- **DiffAnalyzer** — auto-generates narrative diffs («Plan A vs Baseline: +7.8%»)
- **ScenarioExport** — CSV / Excel / PPTX slide с comparison

### 4.3 Effort

~3 дня (component scaffolding 1d + table+diff logic 0.5d + chart integration 0.5d + export 0.5d + tests 0.5d).

---

## §5 Variable classifier — implementation spec

### 5.1 Files

| File | Change |
|---|---|
| `sidecar/econometrica/utils/column_detection.py` | EXTEND with new target types (subscriptions, bookings, transactions, applications, traffic, loyalty_cards, app_installs) + signed control patterns |
| `sidecar/econometrica/utils/holiday_calendar_ru.py` | NEW — 12 РФ holiday dummy generator |
| `sidecar/econometrica/utils/best_practice_rules.py` | NEW — soft-recommendation library |
| `sidecar/econometrica/engines/validator.py` | EXTEND `CONTROL_PATTERNS` to include signed controls (competitor / price / weather / macro) с sign expectations |
| `sidecar/econometrica/engines/decomposer.py` | EXTEND — separate `signed_factor_contributions` output field |
| `sidecar/econometrica/engines/modeler.py` | EXTEND — pre-train auto-inject holidays + signed factor prior namespace |

### 5.2 Signed factor priors

В Bayesian model:

| Type | Prior |
|---|---|
| Media channels | LogNormal (positivity-constrained) — existing |
| Positive controls | HalfNormal — existing |
| Signed controls (competitor) | Normal с negative-leaning mean (μ=-0.5σ, σ=1.0) |
| Signed controls (price/weather/macro) | Normal zero-centered (μ=0, σ=1.0) |
| Base intercept | Normal — existing |

### 5.3 Effort

~2-3 дня (extension column_detection, validator, modeler + holidays library + tests).

---

## §6 Diagnostics features (детали)

### 6.1 Backtest (simple holdout)

**Auto-runs в training pipeline:**
- Default: last 4 weeks (если weekly) или last 8 weeks для долгой истории
- Train on `history[:-holdout]`, predict on `history[-holdout:]`
- Compute MAPE, RMSE, R²
- Single summary panel в diagnostics

**Effort:** 1.5-2 дня.

### 6.2 MCMC convergence (traffic light)

**Auto-computed в training (PyMC уже даёт):**
- R-hat per parameter → max R-hat
- ESS (effective sample size) per parameter → min ESS

**Traffic light rules:**
- 🟢 Green: max R-hat < 1.05 AND min ESS > 400
- 🟡 Yellow: max R-hat 1.05-1.10 OR min ESS 200-400
- 🔴 Red: max R-hat > 1.10 OR min ESS < 200 — рекомендация re-train

**Expert mode:** full trace plots, ESS per parameter table.

**Effort:** 0.5 дня (mainly UI surfacing — backend already has).

### 6.3 Posterior predictive checks (PPC)

**Auto-runs:**
- Sample from posterior predictive distribution
- Compute actual vs predicted scatter (R²)
- Plot residuals over time
- Check residual autocorrelation (Durbin-Watson)

**Manager view:** R² summary + simple residual plot.
**Expert view:** full PPC density plot, residual ACF.

**Effort:** 1.5-2 дня.

### 6.4 Sensitivity tornado

**Computation:**
- Take 5-7 ключевых параметров (adstock_decay TV, Hill alpha TV, channel betas top-3, etc.)
- Vary each by ±20% holding others fixed
- Compute new ROI estimate
- Plot as horizontal bar chart (tornado layout, sorted by impact magnitude)

**Display:** chart on diagnostics page + section in report.

**Effort:** 1-2 дня (compute logic + chart component).

---

## §7 Save/Load + Export

### 7.1 Save/Load (reuse existing)

**Backend ready** (`engines/persistence.py`):
- `save_model(project_id, trace, params, normalization, config)` → pickle к `projects/<project_id>/models/<version>.pkl`
- `load_model_with_compat(project_id)` → unmarshall с backward-compat v1.0→v1.3+

**UI changes (new):**
- Кнопка «💾 Сохранить» на Summary page
- Кнопка «📁 Загрузить модель» в New Project flow
- При load — skip Train stage, go directly to Decompose

**Effort:** 0.5 дня (UI buttons + integration).

### 7.2 JSON export (new layer)

**File:** `sidecar/econometrica/engines/json_export.py` (NEW)

```python
def export_model_params_json(model_data: dict) -> str:
    params = {
        'version': model_data['model_version'],
        'kpi_type': model_data['kpi_type'],
        'channels': {
            ch: {
                'beta_mean': cp['beta_mean'],
                'beta_std': cp['beta_std'],
                'adstock_decay': cp['adstock_decay'],
                'hill_alpha': cp['hill_alpha'],
                'hill_gamma': cp['hill_gamma'],
                'roi_estimate': cp['roi'],
                'roi_ci_90': cp['ci_90'],
            }
            for ch, cp in model_data['channel_params'].items()
        },
        'signed_factors': {...},
        'holidays': {...},
        'normalization': model_data['normalization'],
        'priors_used': bayesian_mmm_spec()['priors'],
        'mcmc_diagnostics': {
            'r_hat_max': ...,
            'ess_min': ...,
        },
    }
    return json.dumps(params, indent=2)
```

**UI:** «📥 Скачать model.json» на Summary page.

**Effort:** 0.5-1 день.

---

## §8 Executive summary (reuse SCQAR — existing)

`aurora_html/sections.py::render_executive_summary()` уже генерирует SCQAR. Для v2.0.0 — **extension с учётом signed factors**:

- Situation: «Бюджет 50М ₽ на OTC, прирост +14.7% к baseline»
- Complication: «Активность конкурентов снизила продажи на 11% за период»
- Question: «Где оптимальная точка распределения?»
- Answer: «Aurora-optimized: TV 22% / Digital 48% / OOH 8% / Performance 22%»
- Recommendation: «Перенаправить 8М ₽ из TV в Digital»

**Effort:** 0.5 дня (extension narrative templates).

---

## §9 ScenarioWizard component spec

### 9.1 Files

| File | Type | Change |
|---|---|---|
| `src/lib/components/pipeline/ScenarioWizard.svelte` | NEW | Main wizard orchestrator |
| `src/lib/components/pipeline/wizard/StepTaskIntent.svelte` | NEW | Step 1 |
| `src/lib/components/pipeline/wizard/StepTargetConfirm.svelte` | NEW | Step 2 |
| `src/lib/components/pipeline/wizard/StepMediaConfirm.svelte` | NEW | Step 3 |
| `src/lib/components/pipeline/wizard/StepPlanInputs.svelte` | NEW | Step 4 (5 variants) |
| `src/lib/components/pipeline/wizard/StepContextConfirm.svelte` | NEW | Step 5 (optional) |
| `src/lib/components/pipeline/wizard/StepSummary.svelte` | NEW | Step 6 (summary + run) |
| `src/lib/wizard-state.js` | NEW | State management + autodetect orchestration |
| `src/lib/components/pipeline/MultiScenarioPage.svelte` | NEW | Multi-scenario comparison page |
| `src/lib/components/pipeline/MultiScenarioChart.svelte` | NEW | Extension continuation chart |
| `src/lib/components/pipeline/DiagnosticsPanel.svelte` | NEW | Traffic light + Expert expand |
| `src/lib/components/pipeline/SensitivityTornado.svelte` | NEW | Tornado bar chart |
| `src/lib/components/pipeline/PPCScatter.svelte` | NEW | Actual vs predicted plot |
| `src/lib/components/pipeline/ContinuationChart.svelte` | NEW | Main forecast viz |

### 9.2 Existing extensions

| File | Change |
|---|---|
| `src/lib/project-state.js` | + `analysisMode` store, + `wizardState` store |
| `src/lib/components/pipeline/WaterfallChart.svelte` | Extension для negative bars (signed factors) |
| `src/lib/components/pipeline/ValidateStepV13.svelte` | Refactor — wizard как entry, AnalysisModeSelector сверху, AppliedModeSummary вместо PerChannelInputSelector в Manager mode |
| `src/lib/components/IntroTutorial.svelte` | Slide 8 переписать под new mode logic |
| `src/lib/help-econometrica/*.html` | 1-2 pages обновить |

---

## §10 ADR-019 outline

Документ который пишется после approval этого spec'а:

```
ADR-019: Aurora MMM Optimizer v2.0.0 Architecture

Status: Accepted
Supersedes: ADR-015 (Mode as Derived State)
Date: 2026-05-XX

Context:
- v1.3.x derived-mode UX создаёт mixed-mode trap (см. retrospective 2026-05-13)
- Двух-панельная архитектура UnitCostsPanel + PerChannelInputSelector — UX-путаница
- Industry libraries (Robyn / LightweightMMM / PyMC-Marketing) — analyst-driven, не self-service
- Aurora ICP — agency analyst (90%), бренд-менеджер (10%)

Decision:
1. Mode as Explicit Choice (Manager: 2 кнопки ROI / Эффективность + Expert opt-in для mixed)
2. ScenarioWizard как entry point (3-7 шагов, auto-detect 60-80%)
3. Variable classifier extended (target metrics, signed factors, holidays)
4. Signed factor support в math + UI
5. РФ Holiday auto-injection (12 hardcoded events)
6. Diagnostics panel (MCMC / Backtest / PPC / Sensitivity)
7. Multi-scenario comparison page
8. Forecast continuation chart как main viz
9. Forecast по плану — 5-й task profile

Alternatives Considered (steel-man):
A. Keep ADR-015 derived mode — отвергнуто (root cause не решается)
B. 2 modes only без wizard — отвергнуто (Антон vision = wizard-driven)
C. Wizard без signed factors — отвергнуто (naive vs industry)
D. Templates catalog (не wizard) — отвергнуто (категория < задача)

Consequences:
Positive: ...
Negative: ADR-015 superseded требует UX migration для existing customers
Neutral: ...

Implementation: см. WIZARD_FLOW_v2_FINAL.md
```

---

## §11 Phase plan v2.0.0 (preview)

| Phase | Duration | Deliverable |
|---|---|---|
| **Phase A — Backend foundation** | ~1 неделя | Variable classifier extension, holiday calendar, signed factor support, store changes (analysisMode), forecast task profile, JSON export |
| **Phase B — Wizard + ValidateStep refactor** | ~1.5 недели | ScenarioWizard 6 steps + ValidateStepV13 refactor + AnalysisModeSelector + AppliedModeSummary + WizardState management |
| **Phase C — Diagnostics & visualizations** | ~1 неделя | DiagnosticsPanel + ContinuationChart + MultiScenarioChart + SensitivityTornado + PPCScatter + WaterfallChart extension |
| **Phase D — Multi-scenario page + integration** | ~0.5 недели | MultiScenarioPage + DiffAnalyzer + ScenarioExport |
| **Phase E — ADR-019 + audit + ship** | ~1 неделя | ADR-019 written, red-team audit, full test suite, 3 pilot test scenarios, NSIS build, tag v2.0.0 |

**Total: ~4.5-5 недель**.

---

## §12 Acceptance criteria

### Phase A done when:
- [ ] `column_detection.py` распознаёт 13 target types + 15 media formats + signed controls
- [ ] `holiday_calendar_ru.py` injects 12 dummies automatic
- [ ] `validator.py` `CONTROL_PATTERNS` extended с signed (competitor/price/weather/macro)
- [ ] `modeler.py` использует signed-factor priors (Gaussian zero-centered / negative-leaning)
- [ ] `decomposer.py` returns separate `signed_factor_contributions`
- [ ] `forecast_planned_activities.yaml` task profile создан + sidecar handler работает
- [ ] `json_export.py` НОВЫЙ файл + endpoint работает
- [ ] `analysisMode` store создан, `analysisObjective` alias preserved
- [ ] pytest passing на extended classifier + holiday tests

### Phase B done when:
- [ ] ScenarioWizard визуально работает с 6 шагами
- [ ] Шаги skip правильно (silent при unambiguous)
- [ ] Auto-detect resolves F1/F2/F3, F4 спрашивается
- [ ] AnalysisModeSelector рендерит 2 кнопки в Manager + 3-ю в Expert
- [ ] AppliedModeSummary заменяет PerChannelInputSelector в Manager mode
- [ ] WizardState persistence через project lifecycle
- [ ] vitest passing на wizard component + state

### Phase C done when:
- [ ] DiagnosticsPanel рендерит traffic-light в Manager + full в Expert
- [ ] ContinuationChart с overlay scenarios + CI ribbons + endpoint labels
- [ ] WaterfallChart с negative bars (signed factor contributions)
- [ ] SensitivityTornado chart работает
- [ ] PPCScatter (actual vs predicted) + residual time series
- [ ] vitest passing на всех components

### Phase D done when:
- [ ] MultiScenarioPage визуально работает
- [ ] Сравнение N сценариев в таблице + chart + diff text
- [ ] Export to CSV/Excel/PPTX работает
- [ ] vitest passing

### Phase E done when:
- [ ] ADR-019 написан и committed в `docs/adrs/`
- [ ] ADR-015 status updated на «Superseded by ADR-019»
- [ ] Red-team audit pass с 0 BLOCKER findings
- [ ] Full pytest + vitest + svelte-check zero errors
- [ ] 3 pilot test scenarios pass (pilot pharma dataset established / synthetic effectiveness / synthetic forecast от плана)
- [ ] NSIS build successful
- [ ] Tag v2.0.0 + push aurora-releases

---

## §13 Финальные decisions (Антон 2026-05-14)

**Q-fin-1. Default granularity = месяц (РФ-стандарт MMM)**

В РФ MMM работает преимущественно с monthly grain, не weekly как в US/EU practice. **Backtest holdout = 4 месяца**.

**Cascade implication для всего product UX:**
- Default time unit = **месяц** во всех wizard плановых вводах (длина периода, forecast horizon, backtest holdout)
- Weekly grain — option в Expert mode для customers с подходящими данными
- Auto-detect data signature определяет grain (monthly/weekly) по data timestamps
- В UI всё отображается в соответствующих единицах ("4 месяца" / "16 недель" в зависимости от data)

**Backtest scheme:**
- Default: last 4 months holdout (если monthly grain)
- Auto-adapt для weekly grain: last 16 weeks holdout
- Auto-extend если history ≥48 months: 6-8 months holdout

**Q-fin-2. PPC R² thresholds — стандартные**

- 🟢 R² > 0.85 — OK
- 🟡 R² 0.70-0.85 — usable но room for improvement
- 🔴 R² < 0.70 — модель не fitted, искать проблему в данных

**Q-fin-3. Sensitivity tornado — adaptive top-7**

Система sama выбирает 7 самых influential параметров для конкретного проекта. Top-N selection logic: vary каждый параметр ±20%, ранжировать по |ΔROI|, взять top 7.

**Q-fin-4. Multi-scenario chart — лимит 5**

5 scenarios на chart (предел читаемости при разных цветах + dashed/dotted). Если больше — toggle через legend для visible 5, остальные в таблице.

**Q-fin-5. РФ holidays opt-out — нет в v2.0.0**

Hardcoded 12 holidays auto-inject без customer customization. Customization откладывается в **v2.2.0 Quality of Life sprint** (item #11 «Custom calibration via priors UI»).

---

**Все decisions закрыты.** Следующие шаги:
1. ADR-019 «Aurora MMM Optimizer v2.0.0 Architecture» (supersedes ADR-015)
2. Red-team audit плана через Explore agent
3. Apply audit findings → finalize plan
4. Ship v1.3.2 (твой pilot test 2-3) — immediate customer benefit, не блокирует v2.0.0
5. Phase A start — backend foundation (~1 неделя)
