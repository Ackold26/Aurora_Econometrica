# Design: Reorder Substeps Валидации — KPI before Roles

**Status:** 🟡 Draft (awaiting Антон approval)
**Author:** Маша маленькая, 2026-05-14
**Target:** Aurora MMM Optimizer v2.1.0
**Estimated effort:** 3-5 hours
**Feedback source:** Антон, pilot UI testing 2026-05-14

---

## Problem

Текущий порядок sub-steps в Validate шаге:
1. **Роли колонок** — auto-classify все 30+ колонок
2. **Целевая метрика** (KPI selector)
3. Ценность единицы (только для count KPI)
4. **Метрики каналов**
5. Подтверждение

Антон отметил (verbatim 2026-05-14):
> «этап Целевая метрика должен быть до этапа Роли колонок — исходя из этого
> будут удалены/скорректированы данные уже под задачу»

**Issues с текущим порядком:**

1. **Cognitive overload:** Юзер видит ВСЕ 30+ колонок в Roles step,
   classifications для irrelevant cols. Например, для Кагоцел dataset
   classifier classifies «Продажи в уп. бренд» и «Продажи в уп. конкуренты»
   и «SOM в уп.» как kpi/control — но если user выбрал KPI = «Продажи в
   руб. бренд», все «в уп.» колонки irrelevant.

2. **Bad UX flow:** Manager mode wizard логика подразумевает что user
   сначала формирует **intent** (что измеряем), потом filter колонок под
   intent. Сейчас наоборот — classify первым, intent вторым.

3. **Wasted user effort:** В Roles step user может override classifications
   для cols которые потом всё равно irrelevant. Wasted clicks.

---

## Proposed flow

1. **Целевая метрика** (NEW first) — KPI selector +  ValuePerCountUnit
2. **Роли колонок** (filtered) — show только relevant cols под выбранный KPI
3. **Метрики каналов**
4. **Подтверждение**

### Filter logic для Roles step

После KPI choice:

| Если KPI = | Filter правило для Roles step |
|---|---|
| Sales-based (Выручка / Доход / Прибыль / Продажи_руб) | Скрыть `Продажи_в_уп.*` + `SOM в уп.`. Reclassify `Продажи_в_руб._конкуренты` + `SOM в руб` → derived/competitor (signed) |
| Count-based (Продажи_в_шт. / Лиды / Регистрации / etc.) | Скрыть `Продажи_в_руб.*` + `SOM в руб`. Reclassify count_конкуренты → signed_competitor |
| Awareness / Custom KPI | Hide pure sales cols (если irrelevant к KPI semantic) |

### State machine impact

`wizard-state.js` (XState-like FSM) currently has linear sub-step
progression: 0 → 1 → 2 → 3 → 4. Reorder требует:
- Swap labels in `navStages` (line 478-488 of ValidateStepV13.svelte)
- Renumber subStep enum: KPI=0, Roles=1 (after KPI confirmed), Metrics=2, Summary=3
- Update `goBack()` logic (line 305-314)
- Update `INVALIDATION_MAP` если есть в wizard-state.js
- Refresh `persistRolesConfirmed` localStorage key (potential migration)

### KPI-driven column filter

New derived в ValidateStepV13:
```js
const relevantColumns = $derived.by(() => {
  const cols = $validateData?.result?.columns;
  if (!Array.isArray(cols)) return [];
  const kpi = currentKPI;  // e.g. 'sales_rub_brand'
  const kind = kpiKindForType(kpi);  // 'monetary' | 'count'

  return cols.filter((c) => {
    // Always show: date, media, control (non-derived), the KPI itself
    if (c.role === 'date' || c.role === 'media') return true;
    if (c.name === kpiColumnName(kpi)) return true;

    // Hide irrelevant unit-mismatch cols
    if (kind === 'monetary') {
      // Hide count-only sales cols
      if (/(в уп\.|в шт\.|в pack)/i.test(c.name)) return false;
    } else {
      // count KPI — hide ₽-only sales cols if user selected count
      if (/(в руб|revenue|выручка|profit)/i.test(c.name)) return false;
    }

    return true;  // default — show
  });
});
```

### Backward compatibility

- Existing `.aurora` projects (saved с старым flow) — нужно migrate
  `roles_confirmed: true` flag после первого open в v2.1.0. Если roles
  уже confirmed — KPI step показывается с pre-selected current KPI,
  юзер просто clicks «Далее» без потери ничего.
- `analysisObjective` / `analysisMode` stores не меняются.

---

## Implementation tasks

| # | Task | File | Effort |
|---|------|------|--------|
| 1 | Swap KPI/Roles sub-step order | `ValidateStepV13.svelte` | 30min |
| 2 | New `relevantColumns` derive + filter | `ValidateStepV13.svelte` | 1h |
| 3 | Update `ColumnMapperConfirm` to accept filtered cols | `ColumnMapperConfirm.svelte` | 30min |
| 4 | State machine update | `wizard-state.js` | 45min |
| 5 | `navStages` re-order + labels | `ValidateStepV13.svelte` | 15min |
| 6 | localStorage key migration for `roles_confirmed` | `ValidateStepV13.svelte` | 30min |
| 7 | Vitest updates | `src/tests/*.test.js` | 1h |
| 8 | Integration tests (manual pilot) | — | 30min |
| 9 | Documentation update | `WIZARD_FLOW_v2_FINAL.md` | 30min |
| 10 | INV update (aurora-meta) | `ENGINEERING_INVARIANTS.md` | 15min |

**Total estimated:** 4 hours conservative, 3 hours optimistic.

---

## Risks

1. **Breaking change в state machine** — если customer save `.aurora`
   на одной версии и reopen на v2.1.0, sub-step indices различаются.
   Migration logic нужен.
2. **Tests cascade** — 30+ vitest tests касаются Validate flow. Many
   могут require update.
3. **Manager mode users** который уже привык к существующему flow —
   могут запутаться. Mitigate через onboarding tooltip «Что нового».

---

## Recommendation

Implement в **v2.1.0 minor release** (не v2.0.1 hotfix) потому что:
- Architectural change (state machine + filter logic)
- Не критичный bug — это UX improvement
- v2.0.0 customers могут жить с текущим flow до v2.1.0
- Time для proper testing на multiple datasets (FMCG / pharma / SaaS)

**Дата target:** v2.1.0 spring sprint, после ship v2.0.0 + v2.0.1.

---

## Approval гетsh

- [ ] Антон approve design direction
- [ ] Маша небесная review state machine implications (cross-product)
- [ ] Создать issue в GitHub для tracking (после approval)
- [ ] Spec section в WIZARD_FLOW_v2_FINAL.md (после implementation)
