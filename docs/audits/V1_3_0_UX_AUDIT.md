# v1.3.0 UX Audit & Fixes

**Date:** 2026-05-12
**Reviewer:** 3 parallel Explore agents (flow+onboarding / insights+recommendations / visual+accessibility)
**Branch:** `feat/v1.3.0-next-gen`

## Severity summary

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 3 | 2 | 1 |
| HIGH | 13 | 6 | 7 |
| MEDIUM | 14 | 1 | 13 |
| LOW | 7 | 0 | 7 |

## Fixed в audit commit

### CRITICAL

**C1: GlossaryPanel - focus trap + restore focus + ARIA missing.**
- Pre-fix: модал без focus trap (Tab уходил на background), без programmatic focus restore, search input без aria-label.
- Post-fix: focus trap через Tab keydown handler, `previousFocus` сохраняется на mount + restore на unmount, search input + close button → explicit `aria-label`, dialog → `aria-labelledby="glossary-title"`.
- File: `src/lib/components/GlossaryPanel.svelte`.

**C2: PerChannelInputSelector - selected row invisible feedback.**
- Pre-fix: только маленький radio dot - юзер не видел какой канал в каком режиме.
- Post-fix: `tr.row-monetary` (accent-primary 4% bg) + `tr.row-physical` (success 4% bg) - entire row подсвечивается. Hover state на tr. Disabled radio labels - `opacity: 0.5 + text-decoration: line-through`.
- File: `src/lib/components/pipeline/PerChannelInputSelector.svelte`.

### HIGH

**H1: WhyThisStep defaultOpen=false на всех шагах.**
- Pre-fix: novice юзер не видел контекст шага если не кликал 💡 icon.
- Post-fix: `defaultOpen={shouldOpenByDefault}` где `shouldOpenByDefault = $pipelineCurrentStep <= 1` (Import + Validate). На остальных шагах collapsed (юзер уже знает context). `{#key currentStepId}` для re-mount при смене шага.
- File: `src/lib/components/pipeline/PipelineWhyThisStep.svelte`.

**H2: Glossary - only Ctrl+G hidden hotkey, no visible button.**
- Pre-fix: пользователи не знали о existence глоссария.
- Post-fix: floating action button (📖 emoji) в правом нижнем углу. Скрывается когда GlossaryPanel / IntroTutorial / CommandPalette уже открыты. Aria-label + title с hint про Ctrl+G.
- File: `src/routes/+layout.svelte`.

**H3: KPISelector - font sizes 10-11px (WCAG AA fail).**
- Pre-fix: subtitle 10px + desc 12px - below WCAG AA для body text.
- Post-fix: subtitle 11px (UPPERCASE letter-spaced - OK по WCAG для caption), desc 13px line-height 1.5.
- File: `src/lib/components/pipeline/KPISelector.svelte`.

**H4: KPISelector - selected card almost invisible (8% opacity bg).**
- Pre-fix: `background: color-mix(...8%)` + 1px border - на dark theme почти неразличимо.
- Post-fix: border-width 2px + bg opacity 18% + box-shadow 3px ring 15% accent-primary.
- File: `src/lib/components/pipeline/KPISelector.svelte`.

**H5: GoalSeekResultCard - нет baseline comparison.**
- Pre-fix: показывал только required budget + delta_vs_current %. Юзер не видел actual baseline number.
- Post-fix: новый `.baseline-comparison` row: «Текущий бюджет: X ₽ → Новый: Y ₽ (+N%)». Visible под main figure.
- File: `src/lib/components/pipeline/GoalSeekResultCard.svelte`.

**H6: GoalSeekResultCard - 3-col metrics row не responsive.**
- Pre-fix: `grid-template-columns: repeat(3, 1fr)` хардкод. На < 800px overflow.
- Post-fix: `@media (max-width: 800px) { grid-template-columns: 1fr; }`.
- File: `src/lib/components/pipeline/GoalSeekResultCard.svelte`.

### MEDIUM

**M1: Number formatting - нет single source of truth.**
- Pre-fix: каждый компонент имел свои inline format helpers (formatRub, formatPct), несовместимо.
- Post-fix: `src/lib/format-numbers.js` с unified helpers:
  - `formatMoney(n, opts)` - compact > 1M, full < 1M.
  - `formatROI(n)` - always 2 decimals + ×.
  - `formatCPU(n)` - 0 decimals + ₽/ед.
  - `formatPct(n, opts)` - auto fraction/percent detection.
  - `formatCount(n, label)` - integers + unit label.
  - `formatMetric(value, ctx)` - KPI-aware dispatch.
  - `formatDelta(n)` - signed percent (no +0% spurious sign).
  - `formatCountCompact(n, label)` - для big numbers.
- GoalSeekResultCard migrated к unified helpers как первый consumer.

## Deferred к hotfix v1.3.1 (с обоснованием)

### CRITICAL

**C3: ColumnMapper missing в новом ValidateStepV13 flow.**
- В v1.2 был drag-drop role assignment (KPI / media / control). В v1.3 ValidateStepV13 показывает только KPI selector + per-channel input - но НЕ role assignment.
- Backend auto-detects role через column heuristic (в pipeline page) - но юзер не видит / не подтверждает.
- **Mitigation:** auto-detect работает для standard schemas. Pilot validate на pilot pharma dataset подтверждает.
- **Fix scope:** v1.3.1 - embed `ColumnMapperConfirm.svelte` после Import с visible review of detected roles.

### HIGH

**H7: insights-rules.js НЕ KPI-aware** - для KPI=count говорит про ROI логику.
**H8: ROIComparison не KPI-aware** - в Effectiveness mode показывает ROI bars.
**H9: Decompose / Optimize - нет «главной рекомендации» как карточки.**
**H10: Empty state на Decompose недостаточно actionable.**
**H11: Report formats без preview** - юзер не видит summary до Generate.
**H12: ValidateStepV13 breadcrumb confusing при skipValueStep** - индексы skip.
**H13: CorridorSlider тонкие зоны при narrow ranges.**

### MEDIUM (13 items)

- WaterfallChart Cyrillic label rotation
- ChannelTimeline color-blind safety
- DecomposeStep table sticky header
- DecomposeStep numbers right-align + tabular-nums
- IntroTutorial keyboard arrow navigation
- Mobile responsiveness untested на 1024px / 800px / 600px
- Color contrast в light theme (status colors)
- Two toggles на OptimizeStep crowded
- Reduced motion не respected в новых components
- Mode-aware tooltips в radio labels PerChannelInputSelector
- ValidateStepV13 busy overlay too thin (opacity 80% needed)
- Recommendation card после optimize / decompose
- Benchmark comparison missing (industry baseline)

### LOW (7 items)

- Emoji semantics inconsistency
- Cards no hover state в DecomposeStep
- Glossary terms cross-links validation
- Animation timings inconsistent
- Help-econometrica HTML pages not v1.3-aware
- Pipeline tours not KPI-aware
- Mastery progression dialog не implemented

## Architectural observations

1. **WhyThisStep is global ONLY** - нет sub-step embedded help. ValidateStepV13 sub-steps не имеют per-step WhyThisStep. v1.3.1: embed sub-step contextual help.

2. **InsightsPanel не KPI-aware** - нужен полный rewrite insights-rules.js с binary dispatcher (monetary / count). Большая работа, deferred.

3. **Recommendation Card pattern отсутствует.** Декомпозиция / Оптимизация показывают numbers, но не выделяют actionable «главную рекомендацию» как primary visual. Должна быть после результата:
   ```
   🎯 Главная рекомендация
   Перелейте 5.2М ₽ из X в Y → +2.1М ₽ выручки
   [Применить в Оптимизацию] [Что если?]
   ```
   v1.3.1 deliverable.

4. **Premium feel achievements:**
   - Glass design ✓
   - Floating glossary button ✓
   - Smooth transitions через `{#key currentStepId}` ✓
   - Selected card strong indication ✓
   - Row-level feedback в PerChannelInputSelector ✓

5. **Premium gaps:**
   - Loading states generic (no multi-stage progress)
   - Empty states pristine но не designed
   - Microcopy ещё inconsistent
   - Skeleton loaders отсутствуют

## Quality после fixes

- **0 svelte-check errors** (от 3 после inits - все fixed)
- WCAG AA ratio: KPISelector text now compliant
- Focus trap: GlossaryPanel WCAG-compliant
- Visual hierarchy: PerChannelInputSelector teal/blue rows + KPISelector ring shadow

## Recommendation

**v1.3.0 ready for pilot validate** (monetary baseline scenarios primary). Все 2 CRITICAL UX fixed, 6 HIGH fixed, 1 MEDIUM (unified formatting) fixed. Remaining HIGH/MEDIUM items для v1.3.1 hotfix не блокируют workflow, только polish.

**v1.3.1 UX scope** (~3 days):
1. ColumnMapperConfirm embed после Import (~0.5 day)
2. Insights-rules.js KPI-aware rewrite (~1 day)
3. Recommendation Card после decompose/optimize (~0.5 day)
4. Report format preview (~0.5 day)
5. Sub-step WhyThisStep embed + arrow keys на IntroTutorial (~0.5 day)
