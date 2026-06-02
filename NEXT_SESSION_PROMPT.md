# Aurora Econometrica MMM Optimizer — промт следующей сессии

> Скопируй этот промт в начало следующей сессии (cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`).

## 🎯 ЦЕЛЬ СЕССИИ: полная реализация плана коррекции (исправить ВСЕ найденные при тестировании ошибки)

План: **`~/.claude/plans/enumerated-drifting-cerf.md` (v2, после аудита)** — 4 волны, ~22-30ч.
Идти по волнам последовательно, каждая = коммит + git-тег + гейты. Push/ship rc8 — отдельной командой.

## Контекст (что уже сделано до этой сессии)

База: `d479ace` (origin/master, sync 0/0), версия `2.1.0-rc7`.
- **Backlog закрыт+запушен:** #59 flat-response Goal-Seek (`9eb52c6`), #61 LI-001 license (`e49e8c1`+`0874524`),
  #62 + SKILL.md TODO (verify-defect — уже были сделаны). #60 — будет решён в Волне 3A (CPP).
- **Live-тестирование** dev на Кагоцел: полный pipeline end-to-end, ~15 находок → `TEST_FINDINGS_2026-06-02.md`.
- **План коррекции v2** прошёл собственный технический аудит (был ~70% точен, 2 пробела закрыты:
  backward-compat + GS-1 proportional). Решения Антона: единицы → L3 CPP-нормализация; онбординг → единый
  поток; объём → все волны.

## Файлы для контекста (порядок чтения)
1. **`~/.claude/plans/enumerated-drifting-cerf.md`** — ПЛАН v2 (главный документ, по нему работать).
2. `TEST_FINDINGS_2026-06-02.md` (корень репо) — детали находок + repro.
3. Память: `project_econometrica_live_gui_test_2026_06_02.md`, `project_econometrica_optimizer_backlog_2026_06_02.md`,
   `feedback_engine_contract_change_needs_persisted_backward_compat.md` (КРИТИЧНО для В3),
   `feedback_verify_agent_recon_before_finalizing_plan.md`, `feedback_svelte_derived_flag_loses_null_narrowing.md`,
   `project_econometrica_optimizer_rescale.md` (mixed-units контекст), `feedback_multi_client_live_test.md`.

## Задачи продолжения (по волнам, приоритет = порядок плана)
1. **Волна 0 — backward-compat (ПЕРВОЙ, фундамент):** `persistence.py` defaults для `unit_costs`/
   `kpi_unit_cost_snapshot` + version-gate + 3 регрессионных теста. Прогнать ~22 теста под угрозой
   (`test_modeler_unit_costs`, `test_adr020_chain_invariants`) — зелёные ДО В3. (~2-3ч)
2. **Волна 1 — тексты-достоверность + англицизм-свип:** MQS-1/MQS-2/SEV-1/GRAM-1/NUM-1/LANG-1 (точные
   локации в плане) + свип 15+ англицизмов (Forward/What-if/Response Curves/mROAS/baseline/adstock) через
   `GlossaryTerm`. Опц.: adjusted R². (~4-5ч)
3. **Волна 2 — UX:** ONBOARD-1 (СНАЧАЛА инвентаризация 6+ механизмов, потом упростить — оставить 1 на
   first-run), NAV-2 (убрать дублирующую футерную «Далее», номера кликабельны), GS-2/INPUT-1/KPI-1.
   Все правки `ValidateStepV13.svelte` — одним проходом. (~6-8ч)
4. **Волна 3 — глубокая достоверность:** 3A CPP-нормализация L3 (UI ввода CPP на Валидации ③ + пропагация
   unit_cost в decomposer/narrative + рендер единиц + budget per-period/total подпись), 3B STATE-1
   (`modelStaleStatus` сравнивать с обученным подмножеством), 3C **GS-1 proportional-mode** (фиксировать
   пропорции + скейлить бюджет → Goal-Seek рабочий). (~10-14ч)

## Pre-flight перед стартом
- 60-сек recon: `git log --oneline -5`, `git status`, ahead/behind (параллельные сессии Антона возможны).
- **Перед В3:** проверить структуру MMX-файла (число точек/единицы) — план верификации предполагает
  «MMX монотонный», это НЕ проверено.
- Live-тест: dev `npm run tauri dev` (vite 5173, sidecar 7529); тестовые файлы
  `C:\Users\ackol\Desktop\Аврора - материалы для обучения и тестирования\Эконометрика - тестовые файлы\XLSX\`.

## Инварианты/правила
- INV-50 (доверие к цифрам) · test-first где применимо · JS+JSDoc (не TS).
- `npm run check` СРАЗУ после правок Svelte-условий (feedback_svelte_derived_flag_loses_null_narrowing).
- **Backward-compat для `.aurora`** при В3 (schema-migration класс) — defaults первыми.
- Гейты-baseline: svelte 0E/172W · pytest 310 · vitest 581. Каждая волна = коммит+тег.
- Push/ship rc8 — по явной команде. Параллельные сессии — коммитить своим pathspec'ом.

## С чего начать
Прочитать план v2 (`~/.claude/plans/enumerated-drifting-cerf.md`) целиком → recon git → **начать с Волны 0**
(backward-compat, безопасно/аддитивно). Уточнить у Антона только развилки 3A CPP (UI ввода CPP: блокировать
vs «как есть»+warn) когда дойдём — остальное по плану автономно.
