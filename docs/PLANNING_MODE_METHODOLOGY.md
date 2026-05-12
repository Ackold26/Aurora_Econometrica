# Aurora Econometrica - Planning Mode (Методология)

**Версия:** 1.2.0
**Дата:** 2026-05-02
**Аудитория:** аналитики и пленнеры, использующие Aurora MMM для планирования будущих медиабюджетов.

---

## 1. Зачем нужен режим планирования

Aurora MMM обучается на исторических данных (например, 3 года недельных продаж). Стандартный оптимизатор отвечает на вопрос: «как нужно было бы перераспределить **исторический** бюджет?» - это аналитический режим (Analyst).

Но настоящий запрос пленнера другой: «какое распределение будет оптимальным для **2026 года** (52 недели) с **другим бюджетом**?» - это режим планирования (Planner).

Без specialized planning mode пленнеры были вынуждены вручную делить optimal allocation на ratio (training_horizon ÷ forecast_horizon), что давало системные ошибки до 11% на коротких горизонтах.

**Planning Mode** в v1.2.0 решает эту проблему математически корректно.

## 2. Что меняется в математике

В Aurora три инженера выполняют forward simulation:
- **scenario.py** (предсказание сценариев) - суммирует Hill saturation **по периодам**
- **decomposer.py** (декомпозиция продаж) - суммирует Hill saturation **по периодам**
- **optimizer.py** (оптимизация бюджета) - до v1.2.0 использовал Hill-of-mean approximation

В planning mode optimizer переключается на **per-period Hill summation** - то же поведение, что у scenario и decomposer. Это восстанавливает 3-way alignment в режиме планирования.

### Формула optimizer planning mode

Для каждого канала c с per-period spend `x_avg = forecast_budget_c / forecast_n / unit_cost_c`:
```
adstock_t = adstock_kernel(x_avg, t, decay_c)        # для t = 0..forecast_n-1
x_norm_t  = adstock_t / adstock_mean_posterior_c
sat_t     = α_c × γ_c^α / (γ_c^α + x_norm_t^α)        # Hill saturation
total    += β_c × Σ_t sat_t                            # сумма по форecast_n периодам
```

Hill применяется **поканально**, к **каждому периоду**. Это математически точно для нелинейной saturation: `Σ Hill(x_t)` ≠ `Hill(mean(x)) × n` (неравенство Йенсена).

## 3. Когда вы видите Planning Mode

В шаге «Оптимизация» появляется переключатель:
- **Аналитик** (по умолчанию) - обучающий период, текущее поведение Aurora.
- **Планнер** - будущий период, новый режим v1.2.0.

При переключении на «Планнер» появляются:
- **Период планирования** - пресеты (Год/Полугодие/Квартал) на основе обучающей гранулярности или своё значение в периодах.
- **Бюджет периода (₽)** - авто-предложение пропорционально training, можно перезаписать.
- Если в данных обнаружена сезонность - предупреждение.

## 4. Гарантии корректности

### 4.1 Жёсткий потолок горизонта

| KPI | Hard cap | Warn |
|-----|---------|------|
| Sales | 2.0× обучающего горизонта | 1.5× |
| Awareness | 1.5× | 1.2× |

Превышение → backend rejects с error code `FORECAST_HORIZON_TOO_LONG`. Допущение стационарности коэффициентов нарушено - переучите модель на расширенных данных.

### 4.2 Дрифт калибровки saturation

Aurora отслеживает **per-channel** дрифт:
- **forecast_avg / training_avg ≥ 3.0×** → critical: «Hill saturation вне калибровочной зоны»
- **forecast_avg / training_avg ≤ 0.3×** → warn: «β плохо калиброван для нижней зоны»
- **adstock_avg ratio ≥ 3.0** → critical: «adstock накопление за пределами наблюдённых данных»

Drift detection emits warnings, но **не блокирует** оптимизацию. Customer informed honestly, **не выдаём fake точность**.

### 4.3 Зоны экстраполяции (S3 - verdict_tier)

Per-channel x_norm forecast сравнивается с обучающими квантилями `{p50, p75, p90, p95, p99}`:
- `x ≤ p95` → in-zone (зелёная зона)
- `p95 < x ≤ p99` → boundary (warn)
- `p99 < x ≤ 3×p99` → extrapolation (critical, force tier «Направленная»)
- `x > 3×p99` → extreme extrapolation (force tier «Высокая неопределённость»)

Используется существующая 3-tier таксономия Aurora - единая модель для verdict'ов модели и forecast'ов.

### 4.4 Сезонность (L3)

При обнаружении сезонности в обучающей y_actual (autocorr ≥ 0.2 на стандартных периодах 13/26/52 для weekly data) - picker выдаёт предупреждение «требуется указать дату начала», т.к. forecast одного и того же периода с разных стартовых месяцев расходится до 17.35% (FMCG-realistic Q4 spike vs Q3 trough).

В v1.2.0 - warning-only. Auto-correction (per-period adjustment per seasonal multiplier) - Phase 2.5+.

## 5. Backward compatibility

- **v1.1.0 customer pickles работают без re-train.** Планнер режим запрашивает три новых поля (training_granularity, train_x_norm_quantiles, seasonality_detected) - для legacy v1.3 pickles они lazy-инферируются на первом invocation планнер режима.
- **Аналитик режим (default)** - байт-в-байт идентично pre-v1.2.0 поведению. 162 baseline tests подтверждают.
- **Никаких breaking schema changes** - все новые поля additive optional.

## 6. Как читать результаты Planning Mode

После клика «Оптимизировать» в planner режиме:
- **Пропорции каналов** валидны для прогнозного периода.
- **Абсолютные суммы (₽)** валидны при сопоставимом per-period бюджете (drift detection это отслеживает).
- **Lift %** - в forecast scale, **не training scale**.
- **mROAS** per-channel - в planning-period-marginal scale.
- **Response curves** - x-axis в forecast spend scale.

Если все каналы попали в critical drift zone - Aurora переходит в **«No-absolute mode»**: показывает только пропорции, suppresses absolute KPI numbers с честным сообщением «бюджет настолько отличается от обучающих данных, что absolute прогноз ненадёжен».

## 7. Известные ограничения

- **v1.2.0** ship'ит uniform-per-period budget allocation. Variable per-period (Q1/Q2/Q3/Q4 разными бюджетами) - Phase 2.5.
- **Adstock warmup** (cold-start первые ~1/(1-decay) периодов) автоматически моделируется через Option C kernel (M1 auto-resolved).
- **Conformal Prediction в planning mode для OLS pickles** - wired в backend (`/compute/forecast-scaling`), UI surface - Phase 2.5.
- **Hierarchical Bayesian × extreme forecasts** - generic warning ship'ed; quantitative threshold deferred к Part 2 audit (после 1+ customer pickle real-data validation).

## 8. Reference & math audit

Полный математический аудит и synthetic test results:
- `docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md` - §1-§10
- `docs/audit_v2_0_synthetic_results.json` - 25-case Option A vs B vs ground truth + 5-case cap sensitivity + 4-case seasonality bias
- `tools/audit_v2_0_synthetic.py` - стандartne harness для воспроизведения

Industry benchmark:
- Robyn (Meta): `robyn_allocator(date_range=...)` - date-range based
- Meridian (Google): `forecast_horizon_periods` numeric
- LightweightMMM (Google): `optimize_media(n_time_periods=...)`
- **Aurora differentiation:** calendar-aware preset picker + KPI-aware horizon caps + saturation drift detection + seasonality-aware warnings + 3-way math alignment in planning mode + Conformal-in-planning для OLS users (S2).

## 9. Если возникли вопросы

Логи Aurora содержат telemetry:
- `planning_mode` boolean в optimize result
- `train_n_periods` + `forecast_n_periods` echo
- `top_warning` + `secondary_warnings` от drift detection

Для диагностики запросите оптимизацию через `/compute/forecast-scaling` (preview без full SLSQP - ~12ms) - увидите все warnings без ожидания.

---

**Aurora Analytics Suite - Aurora Econometrica v1.2.0**
Подготовлено в рамках Phase 2 (Planning Mode) ship cycle.
