# Aurora AI Econometrica v1.0.16

**math-fix v1.4 Section C — Three-way alignment + Optimize page UX**

## 🎯 Critical fixes

### Three-way alignment between Decompose, Optimize, Report

Channels now show **identical mROAS values and recommendations** across all three pipeline stages. Pre-fix: TRPs showed 110× mROAS in Optimize idle vs 0.03× post-optimize — same channel, different code paths.

Single source of truth: `_compute_mroas_money` (chain rule with adstock_factor + unit_cost normalization) used by decomposer.py + optimizer.py. Both engines decorate channels with structured `action` field (Scale / Hold / Watch / Reduce / Cut / Uncertain) via shared `compute_channel_action()` helper.

### Money-axis mROAS

All channels (TRPs/clicks + ₽) compared in unified money axis. Mixed-units bug closed:
```
TRPs:        mroi=0.0285  action=Cut    (was 110× pre-fix — JS fallback in native units)
Performance: mroi=9.7453  action=Scale
```

## 🚀 Optimize page UX

- **Auto-apply optimal allocation** — sliders animate to optimal positions after run (800ms smoothstep). KPI prognosis updates live.
- **Response Curves markers** — current (○ grey) + optimal (★ channel color pin) per channel curve.
- **Edge-case banners** — surfaces backend flags:
  - 🚨 baseline_zero — медиа-вклад = 0
  - ⚠️ binding_constraints — все каналы упёрлись в Min/Max
  - ℹ️ converged_at_current — текущая аллокация близка к оптимуму
- **Per-channel override warning** — explicit reset button when individual Min/Max settings exist.
- **Disabled "Фиксировать бюджет"** checkbox с tooltip — free-budget mode planned for v1.1.

## 📝 Honest narrative

- **budget_dominator** separate from contribution leader — SCQAR Complication: «{TRPs} занимает 92.3% бюджета, но даёт 10.5% эффекта» (honest contradiction).
- **cut_source / scale_destination** from optimizer action signal — SCQAR Answer: «Перебалансировать N млн ₽ из TRPs в Performance» (correct subjects), pre-fix used leader/hero (wrong для asymmetric portfolios).
- **Channel name normalization** — display_name field strips «Бюджет до НДС» pollution from interpretation text.
- **Wide-CI suffix** — verdict «Перенасыщен (низкая уверенность)» вместо подавления к 'Высокая неопределённость'.
- **Russian grammar** — proper period plural («31 период», not «31 периодов»).

## 🔧 Validate state sync

- Single source of truth = `validateData.result.columns[i].role` via shared `column-roles.js` helper.
- All 3 mutator paths (drag-drop, Insights button, matrix click) converge on `setColumnRole()` API.
- `excluded_columns` persisted к project.json — cross-session restore preserves user choice over validator's auto-detection.
- 17 Vitest lock-in tests verifying 3-mutator-path consistency.

## ⚙️ Settings + MQS

- Settings page cleanup (removed legacy stats + license file blocks).
- MQS labels aligned 5-tier (Отличное / Хорошее / Приемлемое / Слабое / Ненадёжное) between frontend findings и backend sources.

## 📊 Tests

- 552+/552+ Python backend tests PASS (zero regression)
- 31/31 Vitest frontend tests PASS (14 pre-existing + 17 new L1 lock-ins)
- 8 new L4 lock-in tests verify three-way alignment (decompose mroi ≈ optimize mroi, max Δ = 0.0000)
- 0 new svelte-check errors

## 🛠️ Installation

- Download `Aurora AI Econometrica_1.0.16_x64-setup.exe`
- SHA256: `<TBD после NSIS build>`
- Auto-updater: existing v1.0.15 customers get notification through `rosst-updates` channel.

## 📚 Documentation

- Methodology — Action Labels Glossary section (full ACTION_KEYS vocabulary)
- Econometrica Step 5 (Оптимизация) — auto-apply, money-axis mROAS, multi-start optimizer
- Index — full v1.0.16 changelog block

---

**Branch:** `math-fix-v1.0.13`
**Customer ship:** Кагоцел RDP, Materia Medica pilot
**Next:** v1.1 (free-budget mode, e2e infra, data-readiness tier indicator)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
