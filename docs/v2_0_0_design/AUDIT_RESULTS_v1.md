# v2.0.0 Plan — Red-Team Audit Results

**Дата:** 2026-05-14
**Author:** Маша маленькая (personal audit, post agent-assisted scan)
**Status:** Action items для pre-Phase-A fixes

Methodology:
1. Explore agent ran 25 findings (6 B / 7 H / 8 M / 4 L)
2. **Я лично верифицировала каждое** против documents + code, adjust severity where wrong
3. Sweep сама поверх для пропущенных items
4. Consolidated с моими severities

---

## §1 Agent finding verification (re-rated)

| Agent ID | Topic | Agent severity | **My verified severity** | Reasoning |
|---|---|---|---|---|
| B1 | Timeline 4.5-5w underestimated, ~6-7w realistic | BLOCKER | **HIGH** | Real. Per `feedback_plan_estimates_conservative` — мои estimates conservative-leaning. Reuse audit нашёл 5/8 фич с ~100% готовности (save = 3-5 days). Honest estimate: ~5.5-6.5 weeks с buffer. Не BLOCKER (план выполним), но требует honest re-estimation. |
| B2 | Wizard state lifecycle undefined | BLOCKER | **BLOCKER ✓** | Verified — `WIZARD_FLOW_v2_FINAL.md` упоминает `wizardState` store но не state diagram, persistence path, sync с `analysisMode`. Разработчик потеряет 2-3 дня на guess. |
| B3 | Migration logic v1.3→v2.0 not detailed | BLOCKER | **HIGH** | Real gap, но migration UX полируется в Phase D, не блокирует Phase A backend. Adjust to HIGH. |
| B4 | Signed factor priors calibration | BLOCKER | **HIGH** | Math review нужен но не блокирует Phase A (placeholder priors можно использовать). Recalibrate на pilot data — Phase E task. |
| B5 | Multi-scenario chart edge cases | BLOCKER | **MEDIUM** | Цветовая палитра + accessibility + endpoint overlap — реальные issues, но Phase C details, не блокирует start. |
| B6 | Forecast planned activities validation | BLOCKER | **HIGH** | Реальный edge case risk. План spec для `forecast_planned_activities.yaml` нужен до Phase A (task profile = Phase A deliverable). |
| H1 | Backtest holdout pseudocode missing | HIGH | **HIGH ✓** | Verified. Algorithm для grain detection + auto-extend logic нужен до Phase A. |
| H2 | PPC R² thresholds — нет cascade guidance | HIGH | **MEDIUM** | UX polish, не блокирует math. Можно адресовать в Phase C при diagnostics panel. |
| H3 | Holiday auto-injection collinearity / regional | HIGH | **HIGH ✓** | Verified. `holiday_newyear_preshop` (15-31 Dec) + `holiday_school_breaks` (winter ~20-31 Dec) реально overlap. Multicollinearity = посadition Bayesian model. Нужен фикс до Phase A или explicit collinearity check. |
| H4 | Manager mode escape для low confidence | HIGH | **MEDIUM** | Edge case rare (most data имеет ясный target). Можно адресовать в Phase B при wizard implementation. |
| H5 | Adstock priors monthly grain | HIGH | **BLOCKER** ⬆ | Upgrade. Это **методологически критично** — если current priors calibrated на weekly data из Robyn examples, monthly model даст wrong adstock estimates. Math review **до** Phase A start. |
| H6 | Variable classifier test coverage | HIGH | **HIGH ✓** | Verified. Acceptance criteria сейчас «pytest passing» — слабо. Нужно min 25 test cases per category. |
| H7 | Decomposer signed_factor_contributions JSON structure | HIGH | **HIGH ✓** | Verified. Без spec — Phase A → Phase C integration break. |
| M1 | Diagnostics Expert mode scope | MEDIUM | **MEDIUM ✓** | Verified. Phase C detail. |
| M2 | UnitCostsPanel tied to legacy logic | MEDIUM | **MEDIUM ✓** | Verified. Adjust visibility refs в Phase B. |
| M3 | Migration toast localization | MEDIUM | **LOW** | UX polish, не критично. Downgrade. |
| M4 | Budget optimization horizon default | MEDIUM | **LOW** | 12 months default разумен. Downgrade. |
| M5 | Best practice rules acceptance loose | MEDIUM | **MEDIUM ✓** | Verified. Spec UX presentation. |
| M6 | analysisObjective alias consumers audit | MEDIUM | **HIGH** ⬆ | Upgrade — критично. Grep audit нужен **до** Phase A. Если пропустим consumer — runtime null read crash. |
| M7 | Continuation chart tooltip structure | MEDIUM | **LOW** | UX detail. Downgrade. |
| M8 | Sensitivity tornado selection algorithm | MEDIUM | **MEDIUM ✓** | Verified. Spec в Phase C. |
| L1 | ADR-015 supersession ownership | LOW | **DONE** | Уже сделано (header updated 2026-05-14). |
| L2 | Phase A effort underestimated | LOW | **HIGH** ⬆ | Upgrade — это пересекается с B1 (timeline). Phase A реально 6-7 days, не 5. |
| L3 | Cross-product escape UX guidance | LOW | **MEDIUM** | Upgrade — реальный edge case. |
| L4 | persistence.py v2.0.0 compatibility | LOW | **HIGH** ⬆ | Upgrade — критично. Если old pickle не load'ится в v2.0.0 правильно — все existing customers сломаются. Test mandatory до Phase A end. |

---

## §2 My additional findings (agent missed)

### N1 — Manager mode 2 modes UX semantic conflict (HIGH)

**Issue:** Spec пишет:
- 💰 «Денежный (ROI)» — все media в ₽
- 📦 «Штучный (Эффективность/CPU)» — все media в физических метриках

Это смешивает **две независимые оси**:
- **Media input axis** (₽ vs физика) — определяет mode (ROI vs Эффективность)
- **KPI kind axis** (monetary vs count) — определяет output metric (ROI vs CPU)

«Штучный» как label для **physical media inputs** двусмысленно. В реальности:
- Manager ROI mode = monetary KPI + ₽ media → ROI
- Manager Эффективность mode = monetary OR count KPI + физика media → shares of contribution

Реальный customer case: бренд с count KPI (sales_packs) хочет ROI / CPU mode — это **monetary inputs + count KPI**. Текущий label «Штучный» это исключает.

**Fix:** разделить axes явно. Manager mode selector — **только про media input units** (ROI / Эффективность). KPI kind (monetary/count) определяется в Шаге 2 wizard. Перeлейbel:
- 💰 **ROI режим** — все каналы в ₽
- 📊 **Эффективность режим** — все каналы в физических метриках

Subtitle: «KPI можно выбрать любой (продажи / лиды / упаковки)».

### N2 — Forecast plan vs trained model compatibility (HIGH)

**Issue:** Если customer trained model в Manager ROI mode (все media ₽), затем в Forecast (Task 4) загружает plan Excel с TRP колонками — что?

Model parameters обучены для ₽-inputs. Forecast с TRP-inputs **математически некорректен** без unit_cost conversion на стороне forecast.

Текущий spec не упоминает «forecast input must match trained model input type».

**Fix:** validator в Step 4 (Task 4) принудительно проверяет:
- planned_data columns ⊆ trained_model channels
- planned_data unit types == trained_model unit types per channel
Если mismatch — explicit error + suggest «обучите модель заново с этой структурой данных».

### N3 — Existing Expert mode capabilities audit missing (HIGH)

**Issue:** Cross-product escape «in Expert mode» предполагает что Expert mode сейчас даёт **полный math access** (per-channel overrides, custom priors, manual mode selection, raw data inputs).

Реальный текущий Expert mode = `$expertMode` toggle который **возможно** просто скрывает Manager UI и показывает advanced fields. Я не проверила полноту.

**Risk:** ADR-019 предполагает Expert как «escape hatch с полным math control» — если реально он ограничен, escape не работает.

**Fix:** audit текущего Expert mode capability — что unlocks `$expertMode`? Если не достаточно — расширить в Phase B как часть wizard refactor.

### N4 — Wizard "back" navigation invalidates earlier results (MEDIUM)

**Issue:** Если customer на Step 5, нажимает «Back» к Step 1 и меняет task с `budget_optimization` на `forecast_planned_activities` — Step 4 (Plan inputs) форма полностью другая. Step 3 (Media confirm) может быть тоже invalid если Forecast accepts только subset каналов.

Spec не определяет: invalidation logic, state cleanup, или show «Back may discard your inputs» warning.

**Fix:** wizard state diagram должен включать back-navigation invalidation rules (Phase B).

### N5 — Sensitivity tornado computational cost (MEDIUM)

**Issue:** Adaptive top-7 sensitivity — каждый параметр varied ±20%, full MCMC re-sampling for new posteriors. Для PyMC trace это **минуты на параметр × 14 (7 × ±) = 30+ минут**.

Real-time computation in diagnostics panel?

**Fix options:**
- Async compute, cache results (preferred)
- Approximate via gradient at posterior mean (fast но less accurate)
- Spec: «sensitivity computes on-demand, shows progress indicator, cached for 1h»

### N6 — MCMC 🔴 convergence — что делать? (LOW)

**Issue:** «🔴 R-hat > 1.10 → рекомендация re-train» но re-train с **какими изменениями**? Same priors + same data → same divergence likely.

**Fix:** add cascade actions:
- 🔴 Convergence fail #1 → suggest «increase MCMC iterations to 3000»
- 🔴 Fail #2 → suggest «tighten priors или add more channels»
- 🔴 Fail #3 → suggest «model may be misspecified, contact support / try simpler config»

### N7 — Methodology Certificate v2.0.0 update (HIGH)

**Issue:** Methodology Certificate (PDF + verify.auroraai.pro) содержит hash of bundle + model spec. Если v2.0.0 добавляет fields (signed_factor_contributions, holiday_dummies, analysisMode):

- Hash computation должен включать новые fields
- verify.auroraai.pro Rust WASM verifier должен parse новый schema
- **Это cross-product change** — verifier живёт в `aurora-platform-core / c7-web-verifier`

Не упомянуто в плане.

**Fix:** add Phase E sub-task «update Methodology Certificate schema + verifier coordination».

### N8 — `forecast_planned_activities.yaml` data layout spec missing (HIGH)

**Issue:** ADR-019 №9 говорит NEW task profile, но **data layout не специфирован**:
- Какие columns expected? Same as `budget_optimization` target_brand_historical но в плановых датах?
- Header detection logic? Какие dates допустимы (future-only, mixed historical+future)?
- Channel structure validation?

Без spec — task profile разработка stuck.

**Fix:** написать `forecast_planned_activities.yaml` spec **до** Phase A start (это deliverable Phase A но spec нужен upfront).

### N9 — Test data corpus для acceptance criteria (MEDIUM)

**Issue:** Acceptance criteria требуют «3 pilot test scenarios pass» (Кагоцел + synthetic + migration). Но:
- Кагоцел data — NDA-restricted, может ли использоваться в automated test suite?
- Synthetic test data builder есть или строится с нуля?
- Migration test — synthetic v1.3.x bundles для voor-вычитываемости

**Fix:** Phase E sub-task «build synthetic test corpus» (~0.5-1 день).

### N10 — In-flight project migration (MEDIUM)

**Issue:** Customer открыл проект в v1.3.x, дошёл до Decompose stage, не закончил. Update приложения на v2.0.0. Открывает project — на каком шаге?

- Re-run wizard от Step 1? Loss in-flight progress.
- Skip wizard, продолжить от Decompose? Wizard state может быть incomplete.

**Fix:** migration logic должен handle in-flight projects (auto-Expert + skip wizard + show banner «проект продолжен в Expert mode из-за migration»).

### N11 — Performance regression test missing (MEDIUM)

**Issue:** Wizard auto-detect + variable classifier на large file (1000+ rows × 50+ columns) — спецификация time budget?

- Variable classifier должен complete < 2 sec?
- Если slow — wizard «commits suicide» при больших file'ах

**Fix:** performance acceptance: «classifier < 2 sec on 1000×50 data», «backtest < 5 min on 4-channel weekly 104-week data». Test on synthetic dataset до Phase E end.

### N12 — Aurora Data Studio coordination (MEDIUM)

**Issue:** Per `aurora-meta/PORTFOLIO.md` — **Data Studio ~85% готова**, не shipped. Wizard auto-detect полагается на Studio data signature output.

Если Data Studio ships позже v2.0.0 — wizard может не получать signature payload.

**Fix:** confirm Studio готов до v2.0.0 Phase B start. Если не — fallback в Optimizer-local auto-detect (existing column_detection.py).

### N13 — Save/Load включает ли все v2.0.0 outputs? (HIGH)

**Issue:** ADR-019 №10 говорит Save/Load reuse 100%. Но `persistence.py` сохраняет trace + channel_params + normalization + config. Не упомянуто:

- Signed factor contributions output cached в pickle?
- Holiday dummies (auto-injected) — they're columns в training data, не parameters; не сохраняются в pickle (только в bundle)?
- MCMC convergence diagnostics — cached?
- Backtest results — cached?
- Sensitivity tornado computation — cached?

Если customer load'ает model — должен видеть **все** diagnostics без re-train. Если pickle не сохраняет diagnostics → re-train на load = slow.

**Fix:** extend `persistence.py` для cache всех diagnostics outputs (Phase A item).

---

## §3 Consolidated final severity ranking

### BLOCKER (must fix before Phase A start)

| # | Topic | Action |
|---|---|---|
| **B2** | Wizard state lifecycle undefined | Add state diagram to WIZARD_FLOW_v2_FINAL.md (~1h) |
| **H5→B** | Adstock priors monthly grain | Math review: verify current modeler.py priors are weekly or monthly calibrated. If weekly — recalibrate (~2-3 hours math + pilot data eyeball) |

### HIGH (must address in Phase A or before)

| # | Topic | Action |
|---|---|---|
| **B1** | Timeline 4.5-5w → ~5.5-6.5w | Re-estimate phases honestly. Add 1 неделя buffer. New total ~6 weeks. |
| **B3** | Migration logic detail | Spec `mode-defaults.js` algorithm + toast message bilingual + 4 migration test scenarios |
| **B4** | Signed factor priors review | Document current placeholder priors + add «math review on pilot data» Phase E task |
| **B6** | Forecast input validation | Write `forecast_planned_activities.yaml` spec + validator rules |
| **H1** | Backtest holdout algorithm | Pseudocode + auto-extend rules |
| **H3** | Holiday collinearity | Add collinearity check в auto-inject pipeline; if `holiday_newyear_preshop` ∩ `holiday_school_breaks` > 50%, merge or drop one |
| **H6** | Variable classifier test coverage | Acceptance criteria upgrade: 25+ test cases per category |
| **H7** | Decomposer JSON structure | Add structure spec with example JSON в WIZARD_FLOW |
| **M6→H** | analysisObjective alias consumer audit | Grep codebase, list all consumers, update strategy |
| **L2→H** | Phase A effort | Confirm extended duration ~6-7 dni |
| **L4→H** | persistence.py v2.0.0 compat | Add «load v1.3 model → verify in v2.0.0» test |
| **N1** | Manager mode UX axes split | Rename buttons «ROI режим» / «Эффективность режим», subtitle «KPI любой» |
| **N2** | Forecast plan vs trained model | Spec validator: planned columns ⊆ trained, unit types must match |
| **N3** | Existing Expert mode audit | Audit current `$expertMode` capability before Phase B |
| **N7** | Methodology Certificate update | Add Phase E sub-task для schema + verifier coord |
| **N8** | forecast_planned_activities.yaml spec | Write **до** Phase A start |
| **N13** | Save/Load cache all diagnostics | Phase A extend persistence.py |

### MEDIUM (address in Phase B-C)

| # | Topic |
|---|---|
| B5 | Multi-scenario chart edge cases (palette, accessibility, label overlap) |
| H2 | PPC R² cascade guidance |
| H4 | Manager mode low-confidence escape |
| M1 | Diagnostics Expert mode scope |
| M2 | UnitCostsPanel legacy refs |
| M5 | Best practice rules UX |
| M8 | Sensitivity tornado selection algo |
| L3→M | Cross-product escape UX |
| N4 | Wizard back navigation invalidation |
| N5 | Sensitivity computation cost |
| N9 | Test data corpus |
| N10 | In-flight project migration |
| N11 | Performance regression |
| N12 | Aurora Data Studio coord |

### LOW (Phase D-E)

| # | Topic |
|---|---|
| M3 | Toast localization |
| M4 | Budget optimization horizon default |
| M7 | Continuation chart tooltip |
| N6 | MCMC 🔴 cascade actions |

---

## §4 Plan readiness verdict

**Status:** 🟡 **Ready with significant pre-flight fixes** (не 🟢, не ⚪).

**Что нужно сделать до Phase A start:**

1. **Address 2 BLOCKERs** (~3-4 часа):
   - B2: Wizard state diagram (~1h)
   - H5→B: Adstock priors monthly review (~2-3h math)

2. **Spec 5 HIGH items с upfront требованием** (~4-6 часов):
   - B6 + N8: `forecast_planned_activities.yaml` spec (~1.5h)
   - B3: Migration logic spec + algorithm (~1h)
   - N1: Manager mode UX axes split (rename + subtitle) (~0.5h)
   - N2: Forecast validator spec (~0.5h)
   - N13: Save/Load cache diagnostics list (~0.5h)
   - M6→H: analysisObjective grep audit (~1h)

3. **Update timeline в ADR-019** (B1 + L2): 4.5-5 → **5.5-6.5 недель с buffer** (~30 мин).

4. **Audit existing Expert mode capabilities** (N3): ~1 час grep + verification.

**Total pre-flight fix work:** ~10-12 часов = ~1.5 рабочих дня.

После этого — **Phase A start with significantly higher confidence**.

---

## §5 Verdict для Антона

**Я не могу честно сказать что план «ready to execute»** даже после твоего approval scope. Audit нашёл серьёзные gaps:

- Realistic timeline ~5.5-6.5 weeks (не 4.5-5)
- 2 BLOCKERs + 17 HIGH items требуют пре-execution fix
- Я лично нашла 13 дополнительных findings что agent пропустил

**Это нормально** для большого refactor — pre-execution audit и существует чтобы найти эти gaps. Цена fix сейчас (~1.5 дня) << цена fix в середине execution (3-5 дней rollback + rework).

**Рекомендация:**

1. Закрыть pre-flight fixes **сегодня-завтра** (~1.5 дня focused work)
2. Затем — start Phase A с corrected plan
3. Two gate reviews: end Phase A (verify foundation) + end Phase B (verify wizard works) — corrective опportunities

Согласен на pre-flight fix cycle до Phase A? Если нет — обсудим какие items сокращать или принять.
