# Aurora AI Econometrica v1.0.16 (math-fix v1.4 Section C)

**Дата:** 2026-04-29
**Branch:** `math-fix-v1.0.13`
**Статус:** Pending NSIS build + ship

## Краткое резюме

Закрыто **20+ findings** из live-test 2026-04-28 (Kagocel). Закрыты L1-L21 (минус некоторые отложенные) - three-way alignment между декомпозицией, оптимизацией и финальным отчётом + UX consistency на странице оптимизации.

Регрессия: **552+/552+ backend tests PASS** + **31/31 vitest** + **0 new svelte-check errors** на каждом commit.

## Что нового

### 🎯 Three-way alignment (критическое)

Декомпозиция, Оптимизация и финальный отчёт теперь используют **единый источник правды** для:
- `mroi_current` (marginal ROAS at current allocation) - единый helper `_compute_mroas_money` в backend
- `action` labels (Scale / Hold / Watch / Reduce / Cut / Uncertain) - единый `compute_channel_action()` helper

**Effect:** customer не видит противоречий - TRPs во всех trех экранах показывает same value (0.03×) вместо 110× в одном и 0.03× в другом.

Math identity verified на real Kagocel pickle: `decompose_mroi ≈ optimize_mroi` max Δ = **0.0000**.

### 🚀 Optimize page UX (cluster L4-L8)

- **Auto-apply optimal**: после расчёта оптимизации слайдеры автоматически переходят на оптимальные позиции (animation 800ms). KPI прогноз обновляется live через JS Hill prediction.
- **Response Curves markers**: на каждой кривой - текущая (○ серый круг) и оптимальная (★ цвет канала pin) точки.
- **Edge-case banners**: 3 mutually exclusive баннера honestly disclose почему optimizer не нашёл lift:
  - 🚨 baseline_zero - медиа-вклад равен нулю
  - ⚠️ binding_constraints - все каналы упёрлись в Min/Max
  - ℹ️ converged_at_current - текущая аллокация близка к оптимуму
- **Per-channel override warning** - банер при changes к global Min/Max если есть индивидуальные overrides.
- **Money-axis mROAS** - все каналы (TRPs/clicks + рубли) сравниваются в единой денежной шкале. Mixed-units bug закрыт.

### 📝 Honest narrative (cluster L11-L15, L2)

**SCQAR Answer/Action 01:**
- `cut_source_channel` (real overspender from action='Cut') и `scale_destination_channel` (action='Scale') - вместо устаревших leader (top contribution) / hero (top mROAS).
- На Kagocel: «Перебалансировать N млн ₽ из TRPs в Performance» (правильно), pre-fix: «из Performance в Social» (оба micro-channels).

**SCQAR Complication:**
- `budget_dominator` - отдельное поле от contribution leader. Template: «{TRPs} занимает 92.3% бюджета, но даёт 10.5% эффекта». Honest contradiction framing.
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
- Persistence: project.json gains `excluded_columns` field - explicit list user's «не использовать» решений.
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
- Pre-fix: MQS=70 показывал «Хорошее» в sources block vs «приемлемо» в findings block - теперь consistent.

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

- **L17** Data-readiness tier indicator (auto-only, no manual override) - 6-10h
- **L9 full** - Free-budget mode полная реализация - 16-24h
- **Svelte e2e test infrastructure** - 4-6h initial setup, lock-in tests для UI flows
- **L21** `lift_pct: None` в optimization.json - investigate when touching result_data shape (low priority - есть `expected_lift_pct` fallback)
- **L24** Finding #2 семантически инвертирован - «единственный близкий к окупаемости» → «единственный ниже окупаемости»
- **L25** MQS thinness penalty при baseline-dominated моделях (R²/MAPE тривиально достижимы) - нужен warning в Tier
- **L26** ROI 3-5× с low gap → «Сбалансирован» edge case (Статьи pilot pharma dataset 2)

## Live-test session - UX дополнения (2026-04-29)

Реализованы во время live-testing с customer'ом в dev mode:

**Import шаг - model engine selector:**
- Auto-выбор движка на основе n_rows: <30 → OLS (small-data fallback), ≥30 → Bayesian
- Customer-facing описания: Bayesian как «золотой стандарт MMM-эконометрики», OLS с honest disclosure
- Backend Pydantic TrainRequest.mode принимает оба значения

**Optimize шаг - UX refactor:**
- Min/Max sliders bounds расширены: Min 0..100% (was 10..100), Max 100..500% (was 100..300)
- Скрыт «Фиксировать бюджет» checkbox (free-budget mode → v1.1)
- Block D «Прогноз на будущий период» интегрирован в Block C как inline expert disclosure (был standalone)
- Block E «Сценарии» переименован в D
- Forecast volume mode math fix: skip optimizer (KPI unchanged при сохранении объёма медиа, растёт лишь сумма)
- Compare row visible always: показывает Текущий/Новый бюджет с inflation overlay опционально
- Save scenario с zero-baseline support: customer может сохранить current allocation × ucNew как сценарий
- Per-channel constraints в collapsible expert disclosure (red border, ЭКСПЕРТ badge)
- Bidirectional sync с глобальным «Эксперт» toggle

**Report шаг - единая кнопка:**
- 3 separate buttons (PPTX/XLSX/HTML) → 1 unified «✨ Создать отчёт» с radio-селектором
- Один файл per click - explicit choice, экономия CPU/времени
- Зелёная ✓ checkmark «уже создано в текущей сессии» → меняет CTA на «⟲ Пересоздать»
- HTML добавлен в insight «Форматы экспорта»

**Narrative consistency (pilot pharma dataset 2 live-test):**
- **L22:** scale_destination = top mROAS (был top contribution) - narrative consistent с COMPLICATION «По mROAS Social опережает»
- **L23:** dedup cut_source из underperformer_names - устранён дубликат «из TRPs ... остановить TRPs»

**Audit-fix (Day 2-5 hardening):**
- PPTX s10 leftover (L15 missed location)
- L14 negative spend guard
- L16 empty-string MQS distinction
- InsightsPanel merge name auto-suffix (collision detection)

## Тесты

- **Backend Python:** 552+ assertions PASS (37 roi_verdict + 24 narrative_coherence + 65 narrative_adapter + 156 math_correctness + 82 posterior_ci + 20 audit_of_sprint3 + 149 causal + 20 optimizer_kagocel + новые L4 lock-ins)
- **Vitest:** 31/31 PASS (14 cabinet-card + 17 column-roles L1 lock-ins)
- **svelte-check:** 33 errors (все pre-existing в hill.js / insights-rules.js, no new)
- **Real Kagocel verification:** mroi_current alignment max Δ=0.0000, action labels match expected (TRPs=Cut, Performance=Scale)
- **cargo check:** clean compile

## Ship details (FINAL - 2026-04-27)

- **NSIS installer SHA256:** `2cf603f95a34294f2ca5df272d2be933b7c741e1152260609b00fd267060cf94`
- **Installer size:** 189.3 MB (198,521,281 bytes)
- **Branch:** `math-fix-v1.0.13` (HEAD `90de35d`, tag `v1.0.16` pushed)
- **GitHub Release:** https://github.com/Ackold26/aurora-releases/releases/tag/v1.0.16 ✓
- **Supabase app_versions:** UPDATED ✓
- **rosst-updates `latest.json`:** commit `533d218` ✓
- **Edge Function verified:** `/functions/v1/app-update` returns v1.0.16 + correct download URL ✓
- **Customer IT-doc:** `PASHE_IT.MD` updated с new SHA256 + v1.0.16 changelog summary ✓

## Auto-update path (для клиентов v1.0.10+)

1. App startup → Edge Function `app-update` request
2. Edge Function reads Supabase `app_versions` → returns 1.0.16 + GH download URL
3. App compares с локальной версией → show update banner
4. Customer clicks «Обновить» → downloads from GitHub Releases
5. Per-machine NSIS install (admin required)
