# Aurora AI Econometrica v1.0.16 (math-fix v1.4 Section C)

**Дата:** 2026-04-29
**Branch:** `math-fix-v1.0.13`
**Статус:** Pending NSIS build + ship

## Краткое резюме

Закрыто **20+ findings** из live-test 2026-04-28 (Kagocel). Закрыты L1-L21 (минус некоторые отложенные) — three-way alignment между декомпозицией, оптимизацией и финальным отчётом + UX consistency на странице оптимизации.

Регрессия: **552+/552+ backend tests PASS** + **31/31 vitest** + **0 new svelte-check errors** на каждом commit.

## Что нового

### 🎯 Three-way alignment (критическое)

Декомпозиция, Оптимизация и финальный отчёт теперь используют **единый источник правды** для:
- `mroi_current` (marginal ROAS at current allocation) — единый helper `_compute_mroas_money` в backend
- `action` labels (Scale / Hold / Watch / Reduce / Cut / Uncertain) — единый `compute_channel_action()` helper

**Effect:** customer не видит противоречий — TRPs во всех trех экранах показывает same value (0.03×) вместо 110× в одном и 0.03× в другом.

Math identity verified на real Kagocel pickle: `decompose_mroi ≈ optimize_mroi` max Δ = **0.0000**.

### 🚀 Optimize page UX (cluster L4-L8)

- **Auto-apply optimal**: после расчёта оптимизации слайдеры автоматически переходят на оптимальные позиции (animation 800ms). KPI прогноз обновляется live через JS Hill prediction.
- **Response Curves markers**: на каждой кривой — текущая (○ серый круг) и оптимальная (★ цвет канала pin) точки.
- **Edge-case banners**: 3 mutually exclusive баннера honestly disclose почему optimizer не нашёл lift:
  - 🚨 baseline_zero — медиа-вклад равен нулю
  - ⚠️ binding_constraints — все каналы упёрлись в Min/Max
  - ℹ️ converged_at_current — текущая аллокация близка к оптимуму
- **Per-channel override warning** — банер при changes к global Min/Max если есть индивидуальные overrides.
- **Money-axis mROAS** — все каналы (TRPs/clicks + рубли) сравниваются в единой денежной шкале. Mixed-units bug закрыт.

### 📝 Honest narrative (cluster L11-L15, L2)

**SCQAR Answer/Action 01:**
- `cut_source_channel` (real overspender from action='Cut') и `scale_destination_channel` (action='Scale') — вместо устаревших leader (top contribution) / hero (top mROAS).
- На Kagocel: «Перебалансировать N млн ₽ из TRPs в Performance» (правильно), pre-fix: «из Performance в Social» (оба micro-channels).

**SCQAR Complication:**
- `budget_dominator` — отдельное поле от contribution leader. Template: «{TRPs} занимает 92.3% бюджета, но даёт 10.5% эффекта». Honest contradiction framing.
- Fallback templates для balanced portfolios (when no clear dominator).

**Channel name normalization (L11):**
- `display_name` field в decomposer + optimizer ch_dict (вызывает `_normalize_channel_name`).
- «Performance Бюджет до НДС до АК» → «Performance» в interpretation block.

**Verdict CI uncertainty (L2):**
- Wide-CI каналы получают суффикс «(низкая уверенность)» вместо подавления informative verdict к 'Высокая неопределённость'. Customer видит описательную метку И уровень уверенности.
- Tone демоновирован: 'good' + wide CI → 'warn'.

**Grammar fixes (L13):**
- Russian period plural: «1 период / 2-4 периода / 5+ периодов» с правильными edge cases для 21/31.
- MAPE «менее 10%» вместо «меньше десятой части» (clearer для customer).

**Underperformer lists (L12):**
- В Action 03 commentary полный список всех Cut channels (раньше hardcoded `[:2]`). На Kagocel: 5 каналов вместо 2.

### 🔧 Validate state sync (L1)

- Единый источник правды = `validateData.result.columns[i].role`.
- Все 3 mutator paths (drag-drop, Insights button, matrix click) используют общий helper `setColumnRole()` из `src/lib/column-roles.js`.
- Persistence: project.json gains `excluded_columns` field — explicit list user's «не использовать» решений.
- Cross-session restore: ValidateStep после re-validation вызывает `restoreExcludedColumns()` чтобы preserve user choice над validator's auto-detected roles.
- 17 vitest lock-in tests verifying 3-mutator-path consistency.

### ⚙️ Settings cleanup (L18-L20)

- Удалён «Статистика использования» блок (irrelevant в Econometrica build).
- Удалён file-based «Лицензия» блок (legacy [LI-001] error pattern).
- Renamed «Подключение к серверу» → «Лицензия» (online auth = primary licensing path).
- Удалён «Версия контента: c1» (unclear notation).
- Backend code preserved: Ed25519 + license.rs остаются для legacy fallback в online_auth.rs flow.

### 📊 MQS labels alignment (L16)

- Frontend `f5_mqs` template теперь принимает `{tier_label}` параметр от backend.
- Aligned 5-tier system: ≥85 Отличное / ≥70 Хорошее / ≥55 Приемлемое / ≥40 Слабое / <40 Ненадёжное.
- Pre-fix: MQS=70 показывал «Хорошее» в sources block vs «приемлемо» в findings block — теперь consistent.

### 🛡️ Forward-compat (L9)

- Checkbox «Фиксировать бюджет» disabled с tooltip «Запланировано в v1.1».
- Backend `OptimizeRequest` gains `budget_mode: str = 'fixed'` field.
- `/compute/optimize` rejects `budget_mode != 'fixed'` с error_code='BUDGET_MODE_NOT_IMPLEMENTED' (forward-compat для direct API callers).
- Free-budget mode полная реализация → v1.1.

### 📝 Audit hardening (post-Day 1)

- Legacy action vocabulary migration map в frontend (Russian primitive 'увеличить'/'сократить'/'сохранить' → ACTION_KEYS Scale/Cut/Hold). Backward compat для projects saved on v1.0.15.
- Delta display fix: используется `initialSpend` (real current) вместо live `channelBudgets`. После auto-apply animation delta остаётся видимым (был = 0%).
- Reasoning tooltip для Uncertain channels (action_reasoning от backend).
- Explicit `Number.isFinite()` checks для NaN propagation guards.
- ResponseCurves pin symbolOffset removed (default anchor on coord).

## Что осталось (отложено в v1.1)

- **L17** Data-readiness tier indicator (auto-only, no manual override) — 6-10h
- **L9 full** — Free-budget mode полная реализация — 16-24h
- **Svelte e2e test infrastructure** — 4-6h initial setup, lock-in tests для UI flows
- **L21** `lift_pct: None` в optimization.json — investigate when touching result_data shape (low priority — есть `expected_lift_pct` fallback)

## Тесты

- **Backend Python:** 552+ assertions PASS (37 roi_verdict + 24 narrative_coherence + 65 narrative_adapter + 156 math_correctness + 82 posterior_ci + 20 audit_of_sprint3 + 149 causal + 20 optimizer_kagocel + новые L4 lock-ins)
- **Vitest:** 31/31 PASS (14 cabinet-card + 17 column-roles L1 lock-ins)
- **svelte-check:** 33 errors (все pre-existing в hill.js / insights-rules.js, no new)
- **Real Kagocel verification:** mroi_current alignment max Δ=0.0000, action labels match expected (TRPs=Cut, Performance=Scale)
- **cargo check:** clean compile

## Ship details (placeholder для финала)

- NSIS installer SHA256: `<TBD после build>`
- Installer size: `<TBD>`
- Branch: `math-fix-v1.0.13` (HEAD `<TBD>` после release commit)
- GitHub Release: `https://github.com/Ackold26/aurora-releases/releases/tag/v1.0.16`
- Auto-update channel: `latest.json` обновлён к v1.0.16
- Customer IT-doc: `PASHE_IT.MD` обновлён с new SHA256
