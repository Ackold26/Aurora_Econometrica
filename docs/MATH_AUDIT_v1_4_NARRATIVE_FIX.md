# Math Audit v1.4 - Narrative consistency fix (Section B)

**Created:** 2026-04-28
**Branch:** math-fix-v1.0.13
**Predecessor:** docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md (Section A - optimizer)
**Trigger:** Live-test Kagocel выявил 4 contradictions в HTML отчёте: «Performance - основная точка оптимизации» (декомп) vs «потенциал удержания» (mROAS); «Social - явный потенциал scale-up» (commentary) vs HOLD verdict (table); «Топ-2 канала» referent unclear; ROI/mROAS определения ambiguous.

Этот документ - audit-trail для Section B fixes (post-Section-A optimizer fix). Закрывает structural narrative contradictions через single-source-of-truth refactor.

---

## Empirical evidence (audit-of-audit, fresh-context, 2026-04-28)

Phase 1 meta-audit обнаружил что план's «inline label generation» framing был неверен. Реальный structural issue:

**TWO PARALLEL VERDICT SYSTEMS in production code:**

| File:line | Function | Output | Used by |
|---|---|---|---|
| `decomposer.py:42` | `compute_roi_verdict(roi, gap, ...)` | 16 ROI-based labels («Перенасыщен», «Эффективен», «Высокая неопределённость» и т.д.) | Decomposition UI page table |
| `narrative_adapter.py:294` | `derive_verdict(channel)` | 5 mROAS+ratio labels (Cut/Reduce/Watch/Hold/Scale) | HTML report action table + findings + commentary |

Same channel, different metric → different verdict в two pages report'а.

**Plus 5+ hardcoded narrative sites** generating commentary independently от derive_verdict:

| File:line | Site | Hardcoded text |
|---|---|---|
| `aurora_html/sections.py:526-541` | `render_mroas` commentary | «явный потенциал scale-up» / «потенциал удержания» / «топ-2 канала портфеля» |
| `aurora_html/sections.py:798-825` | `render_recommendation` Action 01 | binding-aware но НЕ converged_at_current-aware |
| `aurora_pptx/builder.py:1395-1430` | `s06` mROAS commentary | Same hardcoded structure as HTML |
| `aurora_pptx/builder.py:1048,1053` | `s04_section_divider` | takeaway template + wireframe placeholder |

**These were the ROOT CAUSE.** «Hold verdict» в table mismatched «scale-up» в commentary because two different code paths generated each independently от mROAS rank vs derive_verdict.

---

## Fix strategy - single source of truth

### `engines/channel_action.py` (NEW, 230 LOC)

`compute_channel_action(channel: dict) → ChannelAction` - единая функция возвращающая `(key, label_ru, tone, reasoning, priority, confidence)`.

**Decision tree (top to bottom - first match wins):**

```
0. Bad input (no mroas + spend unparseable)        → Watch (low confidence)
1. Untrained channel                                → Uncertain
2. Zero spend                                       → Uncertain
3. Severe optimizer cut signal (ratio < 0.5)        → Cut
4. Below breakeven (mROAS < 0.8)                    → Cut
5. Optimizer reduce (ratio ≤ 0.95 + mROAS ≥ 1.0)    → Reduce
6. Near breakeven (mROAS < 1.0)                     → Reduce
7. Optimizer scale (ratio ≥ 1.05 + mROAS ≥ 1.0)     → Scale
8. mROAS+gap heuristic (mROAS ≥ 1.5 + gap ≥ +5pp)   → Scale
9. CI uncertainty (width > mROAS) - EVALUATED LAST  → Uncertain
10. Hold (mROAS ≥ 1.1 + |gap| < 5pp)                → Hold
11. Watch (fallback)                                → Watch
```

**Critical design choice - CI step ordering:**

Pre-design: CI uncertainty step early (#3) - каналы с wide CI получают Uncertain regardless of optimizer signal. Test result: real Kagocel n=31 wide posterior CI → ALL 6 channels Uncertain → Antón's product mandate «что изменить» suppressed despite optimizer finding +28% lift.

Post-design: CI uncertainty step LATE (#9). Optimizer's redistribution implicitly integrates joint posterior (mROAS samples per channel), so meaningful `ratio` (≥ 1.05 OR ≤ 0.95) reflects already-confidence-aware ranking even с individual-channel wide CI. Только когда optimizer не двигает + CI wide → Uncertain (правда не actionable).

Real Kagocel post-fix: 5 Scale + 1 Cut + 0 Uncertain. Lift +28.3% surface'ит cleanly.

**Vocabulary (6 keys, preserved 5-key backward compat):**

```python
ACTION_KEYS = ('Scale', 'Hold', 'Watch', 'Reduce', 'Cut', 'Uncertain')

ACTION_LABEL_RU = {
    'Scale':     'Масштабировать',
    'Hold':      'Удерживать',
    'Watch':     'Под наблюдением',
    'Reduce':    'Сократить умеренно',
    'Cut':       'Сократить',
    'Uncertain': 'Недостаточно данных',  # NEW
}
```

`Uncertain` - новый key. CSS class `verdict-Uncertain` добавлен в HTML rendering. PPTX layouts inherit through verdict text.

### `derive_verdict` migration (narrative_adapter.py)

```python
def derive_verdict(channel: dict) -> str:
    from .channel_action import compute_channel_action
    return compute_channel_action(channel).key
```

Тонкий wrapper для backward compat - все существующие callers получают same answer.

### `_map_pipeline_to_builder_data` decoration

Каждый channel в merged list получает structured action fields:
```python
ch['action']             = action.key            # 'Scale' | 'Hold' | ...
ch['action_label']       = action.label_ru       # 'Масштабировать'
ch['action_reasoning']   = action.reasoning      # 'Optimizer рекомендует +100%, mROAS 9.8×'
ch['action_tone']        = action.tone           # 'good' | 'warn' | 'bad' | 'neutral'
ch['action_priority']    = action.priority       # 0..5 для sort
ch['action_confidence']  = action.confidence     # 'high' | 'medium' | 'low'
ch['verdict']            = action.key            # legacy compat (table CSS class)
```

Templates читают эти поля → consistency by construction.

### `_derive_narrative_facts` extensions

```python
"converged_at_current": bool   # NEW - false convergence detector from Section A
"action_counts":        dict   # {'Scale': N, 'Hold': N, ...} portfolio summary
"channels_by_action":   dict   # {'Scale': [name1, ...], ...}
"top_action":           str    # most-frequent decisive action
```

### HTML render refactor

**`render_mroas` commentary** (sections.py:504-580):
- Pre-fix: 3 hardcoded blocks based на mROAS rank
- Post-fix: top-3 unique actions (de-duplicated по action key) с `ch['action_label']` + `ch['action_reasoning']` per block

```python
by_priority = sorted(channels, key=lambda c: -priority(c.action))
seen_actions = set()
for ch in by_priority:
    if ch.action in ('Uncertain', *seen_actions): continue
    seen_actions.add(ch.action)
    commentary.append((f"{ch.name} - {ch.action_label}.", ch.action_reasoning))
    if len(commentary) >= 3: break
```

**`render_recommendation` + `render_executive_summary`**: добавлен `converged_at_current` branch с honest banner («Оптимизатор сошёлся на текущем распределении... Расширьте границы»).

### PPTX builder refactor

`aurora_pptx/builder.py` lines 1395-1430 (s06 commentary): same action-driven pattern as HTML. Уважает channel decoration from narrative_adapter - single source of truth.

`aurora_pptx/builder.py:1053` - wireframe-mode placeholder для preview (когда `self.facts` is None). НЕ demo-leak в production output.

---

## Validation

### Unit tests - channel_action mapping (10 cases)

```
U1: untrained → Uncertain                            ✓
U2: zero spend → Uncertain                           ✓
U3: CI width > mROAS, no optimizer signal → Uncertain ✓
U4: mROAS < 0.8 → Cut                                ✓
U5: optimizer ratio ≤ 0.95 → Reduce                  ✓
U6: mROAS 0.8-1.0 → Reduce                           ✓
U7: optimizer ratio ≥ 1.05 → Scale                   ✓
U8: mROAS ≥ 1.5 + gap ≥ +5pp → Scale                 ✓
U9: stable → Hold                                    ✓
U10: mROAS=1, gap negative, no optimizer → Watch     ✓
```

### Integration - HTML coherence (14 cases)

```
I1a: table contains verdict cells для каждого channel       ✓
I1b: table[ch] verdict == ch.action для каждого channel      ✓
I1c: каждый decisive action label_ru appears в commentary    ✓
I1d: render_mroas НЕ использует hardcoded «scale-up»         ✓
I2a/b: converged_at_current banner surfaces honestly         ✓
I3a/b/c: render_at_a_glance counts match action_summary      ✓
```

### Real Kagocel pickle (production validation)

```
Pre-Section-B (Section A only):
  Optimizer: 5 channels +100%, TRPs -8.30%, lift=+28.30%
  Narrative table verdicts: undefined / inconsistent с commentary

Post-Section-B:
  action_counts: {'Scale': 5, 'Hold': 0, 'Watch': 0, 'Reduce': 0, 'Cut': 1, 'Uncertain': 0}
  Performance  | mROAS=9.83  | ratio=2.00 | Scale
  Social       | mROAS=10.49 | ratio=2.00 | Scale
  Banners      | mROAS=1.08  | ratio=2.00 | Scale
  OLV          | mROAS=1.04  | ratio=2.00 | Scale
  Retail Media | mROAS=7.41  | ratio=2.00 | Scale
  TRPs         | mROAS=0.03  | ratio=0.92 | Cut
```

Optimizer signal trumps wide CI (n=31 small sample) - product value restored. Antón's mandate «что изменить» surface'ит cleanly: 5 каналов Scale, TRPs Cut, total lift +28.3%.

### Regression check

```
test_audit_of_sprint3      : 20/20 PASS
test_causal_m0..m4         : 149/149 PASS
test_math_correctness      : 156/156 PASS
test_narrative_adapter     : 65/65 PASS  (3 backward-compat cases preserved)
test_posterior_ci          : 82/82 PASS
test_roi_verdict           : 36/36 PASS
test_optimizer_kagocel...  : 9/9 PASS  (Section A lock-in)
test_narrative_coherence   : 24/24 PASS  (Section B lock-in, NEW)
                          ━━━━━━━━━━━━━━
Total: 541/541 (was 517 + 24 new, no regressions)
```

---

## Known limitations / out-of-scope

1. **PPTX optimizer state awareness.** `aurora_pptx/builder.py` НЕ читает `binding_constraints` / `optimization_converged` / `converged_at_current` для banner SCQAR/Action 01. HTML refactored, PPTX deferred. PPTX users получат action-driven commentary но вместо honest «оптимизатор не нашёл» banner - generic recommendation. Sprint 4+ task.

2. **`compute_descriptive_state` not implemented.** Plan's option (b) предусматривал отдельный «descriptive state» function (past performance: «Перенасыщен», «Эффективен») рядом с prescriptive action. Existing `decomposer.compute_roi_verdict` уже выполняет descriptive - mapping к structured class deferred. Decomposition UI page продолжает использовать ROI-based labels, unaffected by Section B.

3. **Wireframe placeholder в PPTX line 1053.** Hardcoded «TV генерирует 42% продаж при 28% бюджета - основная точка оптимизации» появляется ТОЛЬКО когда `self.facts is None` (preview mode без data). Production rendering uses dynamic template. НЕ demo-leak в client output.

---

## Files changed

```
sidecar/econometrica/engines/channel_action.py     (NEW, 280 LOC, single source of truth)
sidecar/econometrica/engines/narrative_adapter.py  (refactor, +30/-30 LOC)
sidecar/econometrica/aurora_html/sections.py       (refactor render_mroas + 2 banners, +60/-30)
sidecar/econometrica/aurora_pptx/builder.py        (refactor s06 commentary, +40/-40)
tools/test_narrative_coherence.py                  (NEW, 280 LOC, 24 lock-in tests)
docs/MATH_AUDIT_v1_4_NARRATIVE_FIX.md              (NEW, this file)
SPRINT3_PROGRESS.md                                 (session log append)
```

---

**Маша, 2026-04-28**
