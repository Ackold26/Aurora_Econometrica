# Aurora Econometrica MMM Optimizer — промт следующей сессии

> Скопируй этот промт в начало следующей сессии (cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`).

## Контекст (что уже сделано)

Сессия 2026-06-02 (автономный backlog sweep) — **запушено в origin/master до `0874524`** (sync 0/0), версия `2.1.0-rc7`:
- **#59 flat-response Goal-Seek** (`9eb52c6`) — backend marker `flat_response_fallback` + проброс `error` (non_monotonic) в `optimize/inverse.py`; UI-баннер «Модель близка к насыщению» + `methodLabel()` в `GoalSeekResultCard.svelte`. 3 теста `tests/test_inverse_flat_response_marker.py`.
- **#61 LI-001 license priority** (`e49e8c1` + `0874524`) — `src/lib/license-display.js` `resolveLicenseTier()` (online-ok→offline-valid→cached→none) + `$derived licenseTier` в `settings/+page.svelte`. 5 vitest `src/tests/license-display.test.js`. Только Svelte.
- **#62 R-hat=1.0** и **SKILL.md TODO** — verify-defect: оказались уже сделаны, кода не потребовали.

Гейты на момент закрытия: svelte-check **0E/172W** (= baseline rc7) · pytest tests/ **310 passed** · vitest **581 passed**.

## Блокеры / критичные находки (чтобы не переоткрывать)
- **#60 НЕ чинить вслепую.** Recon показал: Goal-Seek (260M) = бюджет за период, инсайты (2.46B) = за весь training-период (×n_periods), но множитель ~10× точно НЕ сведён. Это баг доверия к цифрам (INV-50). Нужен живой прогон + решение по семантике.
- **GUI offline-smoke #61 — handoff, не сделан** (логика доказана vitest; полный GUI-тест дорог + конфликтовал с параллельной сессией).
- Ship rc8 НЕ делался (по мандату — только фиксы + локальная верификация).

## Файлы для контекста (порядок чтения)
1. `SESSION_PLAN_2026-06-02_optimizer-backlog.md` (корень репо) — полный трекер сессии + recon-карта.
2. Память: `project_econometrica_optimizer_backlog_2026_06_02.md`, `feedback_extract_pure_function_when_gui_test_infeasible.md`, `feedback_svelte_derived_flag_loses_null_narrowing.md`, `feedback_recon_before_task_frame_may_have_shifted.md`.
3. Код #60: `sidecar/econometrica/optimize/inverse.py` (Goal-Seek), `sidecar/econometrica/optimize/bounds.py` (`compute_safe_corridor`, `current_total`), `src/lib/insights-rules.js` (~1648-1660, `total_budget_money`), `src/lib/components/pipeline/GoalSeekResultCard.svelte`.
4. TestData: Kagocel pickle'ы в `sidecar/econometrica/кагоцел-рф-*` (разные n_periods для multi-client проверки).

## Задачи продолжения (приоритет)
1. **#60 budget unit mismatch** (~1.5–3ч) — investigation-first: прогнать pipeline на Kagocel, зафиксировать фактические числа Goal-Seek vs инсайтов + точный источник множителя (per-period vs ×n_periods). Затем РАЗВИЛКА с Антоном: какую семантику показывать (бюджет за период / за год) + явная подпись единицы в UI. Multi-client (Kagocel + Венарус, разные n_periods) — проверить корректность множителя. НЕ чинить до ground-truth.
2. **GUI offline-smoke #61** — открыть Настройки в offline-режиме (или с отключённым сервером): должно быть «Лицензия активна (офлайн)» (зелёная точка), НЕ «Лицензия не подтверждена».
3. **Ship rc8** (когда фиксы накопятся) — через skill `aurora-release-update`: bump rc7→rc8 (package.json + tauri.conf.json + Cargo.toml) → NSIS build → GH Release (243MB >50MB) → Supabase app_versions (`aurora-econometrica-gui` + legacy `econometrica`) → manifest → Edge Function verify → tag.

## Инварианты/правила
- INV-50: при <100% уверенности в цифре — качественное утверждение без числа (особенно #60).
- Test-first; investigation-first (SA8) перед каждым фиксом; fresh-context аудит перед ship.
- Push к remote — show diff → ждать ок (если не дан явный мандат на push).
- Svelte: JS+JSDoc (не TS); после рефактора условий `npm run check` сразу (см. feedback про narrowing).
- aurora-release-update skill при триггерах «собери/выпусти/опубликуй».

## С чего начать
Прочитать `SESSION_PLAN_2026-06-02_optimizer-backlog.md` + 60-сек recon (`git log --oneline -5`, `git status`, ahead/behind) — фрейм мог сдвинуться (параллельные сессии Антона). Затем уточнить у Антона: начинаем с #60 (живой прогон) или другая задача?
