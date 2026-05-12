# Aurora MMM Optimizer v1.3.2 - Pilot test plan

**Дата:** 2026-05-12
**Branch:** `feat/v1.3.2-reports-kpi-aware`
**Scope:** verify KPI/mode-aware adaptations end-to-end через UI

---

## Цель пилотного теста

После v1.3.2 sprint (9 commits + audit pass) у нас:
- 1013 backend tests pass
- 97 frontend Vitest tests pass
- 13 PPTX integration tests pass (через shim)
- 0 svelte-check errors

Но **runtime через UI** не verified - нужны pilot runs для подтверждения что end-to-end flow работает корректно. Особенно critical: count KPI и effectiveness mode никогда не запускались в реальном workflow.

---

## Запуск приложения

```powershell
cd "D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica"
git checkout feat/v1.3.2-reports-kpi-aware
$env:AIAGENCY_DEV = '1'
npm run tauri dev
```

После запуска DevTools открываются автоматически (если debug). Логи следить в console + сидикар terminal.

---

## Сценарий 1 - Кагоцел (monetary roi, baseline regression)

**Цель:** убедиться что v1.3.2 НЕ ломает v1.2 backward compat. ROI labels и SCQAR templates должны быть как в v1.2.

### Шаги

1. Open existing project: `Кагоцел РФ ММХ 1105-26.aurora` (v1.2 bundle).
2. После загрузки → переход к Validate шагу.
3. **NEW v1.3.2:** видна substep nav "Роли колонок → Целевая метрика → Метрики каналов → Подтверждение" (4 dots, monetary skip Ценность).
4. ColumnMapperConfirm показывает detected roles. Confirm без правок.
5. KPISelector default = `sales` (monetary). Select → next.
6. PerChannelInputSelector - proceed с default monetary attribution для каждого канала.
7. ModeDerivedExplanation → continue.
8. Train model → Decompose → Optimize → Report.

### Проверки

- [ ] **Decompose table:** колонка показывает `mROAS` header, values format `1.50×`.
- [ ] **InsightsPanel:** `ROI портфеля X.XX×`, `Лучший ROI: ChannelName = X.XX×`.
- [ ] **WaterfallChart:** chart renders без crash.
- [ ] **ChannelComparisonChart (renamed):** card title «Расходы vs Эффект», bars показывают % shares.
- [ ] **Optimize:** lift показан как `+N%`, RecommendationCard «Переложите N млн ₽ из X в Y».
- [ ] **Report HTML:** `ROI портфеля 1.5×`, action_table column header `mROAS`, не CPU.
- [ ] **Report PPTX:** аналогично, s06 chart title `MROAS ПО КАНАЛАМ / МУЛЬТИПЛИКАТОР`.
- [ ] **Goal-seek:** target ввод в ₽, result formatted `1 050 000 000 ₽`.
- [ ] **ColumnMapperConfirm persisted:** возврат к Validate шагу через goBack - ColumnMapperConfirm НЕ показывается повторно (localStorage hit).

### Acceptance

Все checkbox'ы выполнены. Никаких visible regressions от v1.2. Никаких слов "CPU" или "Доля эффекта" в UI.

---

## Сценарий 2 - Synthetic count KPI (`sales_packs`)

**Цель:** проверить B4 fix (units/₽ → CPU inversion) end-to-end, CPU labels всюду.

### Подготовка

1. Создать synthetic project через File → New:
   - Brand: «TestPharma»
   - Product: «TestDrug»
   - Excel file: создать с колонками:
     - `date` (weekly, 2 года = 104 строки)
     - `sales_packs` (random 100-1000 per week)
     - `tv_grp` (random 0-50)
     - `digital_spend_rub` (random 0-2000000)
     - `social_spend_rub` (random 0-1000000)
   - **Margin per upak:** 80 ₽

### Шаги

1. Open new project → ImportStep loads file.
2. Validate шаг → **NEW v1.3.2:**
   - Substep 1: ColumnMapperConfirm - verify auto-detected roles. `sales_packs` = kpi, остальные = media, `date` = date.
   - Substep 2: KPISelector - choose `sales_packs` (count group).
   - Substep 3: ValuePerCountUnitInput - verify auto-detected price ~80₽ (from sales/sales_packs ratio) OR enter manually `80`.
   - Substep 4: PerChannelInputSelector - для каждого канала: `tv_grp` = physical (units), `digital_spend_rub` / `social_spend_rub` = monetary.
   - Substep 5: ModeDerivedExplanation - verifies mode = `roi` (count KPI + monetary spend = CPU-mode).
3. Train → Decompose → Optimize → Report.

### Проверки

- [ ] **DecomposeStep displayMetric:** «CPU, ₽/ед.» column header.
- [ ] **Channel values:** integer CPU values (10-500 range), НЕ маленькие fractions (0.001-0.05).
- [ ] **InsightsPanel:** «CPU портфеля 80 ₽/ед.», «Лучший CPU: ChannelName = 50 ₽/ед.».
- [ ] **OptimizeStep miROAS table:** показывает CPU values (не units/₽).
- [ ] **RecommendationCard:** «Переложите N ₽ из X в Y. Прогнозный прирост: +M%».
- [ ] **Report HTML s06 chart:** subtitle «Стоимость следующей единицы», bar values are CPU integers.
- [ ] **Report HTML s07 table:** column header «CPU ₽/ед.», cells показывают integer CPU.
- [ ] **Report HTML s08 SCQAR:** situation phrase «CPU портфеля 80 ₽/ед.», recommendation «Ожидаемый прирост продаж: +N пп».
- [ ] **Report PPTX:** parallel checks (s05 key_message, s06 action_chart, s07 action_table, s09 SCQAR).
- [ ] **Goal-seek:** target = `100000 упак` (или похоже), result = required ₽ budget.
- [ ] **WaterfallChart:** still works correctly (KPI-agnostic chart).

### Acceptance

Никаких visible «0 ₽/ед.» (B4 pre-fix signature). CPU values integer и semantically correct (smaller = better). SCQAR не упоминает «ROAS» в narrative.

---

## Сценарий 3 - Synthetic effectiveness mode

**Цель:** проверить mode=`effectiveness` flow (share-based, 100% по построению).

### Подготовка

Same synthetic project как Сценарий 2 OR создать new с:
- KPI = `sales` (monetary, или count - не важно для mode test)
- Все каналы в `physical` (не monetary) → derived mode = `effectiveness`

### Шаги

1. Open new project → Validate.
2. ColumnMapperConfirm + KPISelector + PerChannelInputSelector:
   - **Key:** в PerChannelInputSelector выбрать `physical` для всех каналов.
3. ModeDerivedExplanation должен показать «Effectiveness mode (share)».
4. Train → Decompose → Optimize → Report.

### Проверки

- [ ] **DecomposeStep:** columnheader «Доля %», values как percentages (10%, 30% etc.).
- [ ] **InsightsPanel:** «Средняя доля каналов в портфеле», «Лучший по доле эффекта: X = 30%».
- [ ] **RecommendationCard impact label:** «Прогнозный прирост доли».
- [ ] **Report HTML s06 chart:** title «Доля каналов в эффекте · %», bars показывают % values.
- [ ] **Report HTML s07 totals row:** `100%` aggregate (sum of shares).
- [ ] **Report HTML s08 SCQAR:** «Средняя доля каналов в портфеле», impact card «Прогнозный прирост доли».
- [ ] **NO «ROI» / «mROAS» / «CPU» mentions в UI/report для effectiveness mode.**
- [ ] **Action_02_text:** «N канал(ов) с низкой долей в портфеле» (не «под breakeven»).
- [ ] **PPTX chart subtitle:** «Доли каналов в продажах, Q1 2026».
- [ ] **PPTX number_format:** values show as percentages (e.g. «25.0%»), не «0.25%» - B1 fix verification.

### Acceptance

Effectiveness mode рендерит share-based labels везде. M1 «breakeven» metaphor отсутствует. B1 native % format работает корректно.

---

## Quick smoke checks (parallel runs)

После трёх сценариев - быстрая verify:

| Check | Expected | Status |
|---|---|---|
| Cargo build | OK, no errors | ⏳ |
| `npm run check` | 0 errors / 157 warnings | ✅ (verified in tests) |
| `npm test` | 97 pass / 0 fail | ✅ |
| `python -m pytest tools/` | 1014 pass / 5 skipped | ✅ |
| `python -m pytest tools/test_aurora_pptx_integration.py` | 13 pass / 0 fail | ✅ |
| NSIS build | installer produced | ⏳ |
| Updater workflow | upload + verify download | ⏳ |

---

## Bug reporting template

Если pilot обнаруживает regression - фиксировать в issue:

```
**Сценарий:** [1/2/3]
**Шаг:** [substep N описание]
**Ожидалось:** [правильное behavior]
**Получено:** [actual]
**Severity:** [BLOCKER / HIGH / MEDIUM / LOW]
**Screenshot:** [если визуальный]
**Repro project:** [path к .aurora file]
```

---

## После pilot

При passes ✅:
1. Merge `feat/v1.3.2-reports-kpi-aware` → `hotfix/v1.3.1` или прямо в release branch.
2. Tag v1.3.2.
3. NSIS build.
4. Ship to `aurora-releases`.

При fail ❌:
1. Categorize finding (BLOCKER / HIGH / MEDIUM / LOW).
2. Создать issue в repo.
3. Fix branch off `feat/v1.3.2-reports-kpi-aware` если в scope; deferred к v1.3.3 если out-of-scope.

---

**Maintained by:** Маша маленькая (primary), revised после каждого pilot run.
