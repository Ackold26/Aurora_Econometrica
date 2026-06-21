# Следующая сессия — Aurora Econometrica Optimizer (роутер)

> Скопируй в начало следующей сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`. Ветка `feat/ai-insights-tier2`.

## Контекст — что сделано (сессия 2026-06-21, `23099fe..ddda116`, ВСЁ ЗАПУШЕНО)
Закрыты ОБА трека. Ветка `feat/ai-insights-tier2` теперь feature-complete: Tier 1–3 AI-инсайтов (Аврора) + отчётность + дизайн.

- **✅ ОТЧЁТНОСТЬ — live-проверка на РЕАЛЬНОМ XLSX/MD + фиксы.** opt-in Rust-тест `live_real_xlsx_md_probe` (`report.rs::tests`, no-op без env `AURORA_LIVE_*`) кормит `build_xlsx`/`build_markdown` реальной фикстурой `kagocel-load1` + verbatim SSOT honesty → настоящий файл → openpyxl. Подтверждено вживую: waterfall-лист, плашка надёжности verbatim, версия v1.2, режим/KPI, глоссарий-47, ROI «н/д» для битого TRPs. **Фиксы:** `23099fe` clean_label на 8 сайтах (имена с `\n`) + MD `top_ch` INV-50 (короновал битый канал); `25d8e3c` guard пустой коллекции каналов (range-краш) + регресс-тест + decomposer `_clean_name` (нарратив insight). Метод → [[feedback_optin_env_test_real_fixture_for_generated_artifact]].
- **✅ ДИЗАЙН закрыт.** `444c502` InsightCard severity-tint dark 8% (выбор Антона из faithful playwright-превью) + типизация `getAllTerms`; `32a1e5a` широкий проход компонентов = «выравнивать-не-портировать» ДОКАЗАН (токены не трогаем); `42e525b`+`187e6c5`+`ddda116` таймер сессии (СЧЁТ ВВЕРХ, сквозной на всех страницах, lime) + hero-логотип поднят в центр зазора/184px + placeholder «Спросить Аврору…» + чип «ECONOMETRICA» в Настройках (центрирован, замер offset 0). Методы → [[feedback_faithful_preview_for_subjective_visual_choice]], [[feedback_calibrate_autonomy_by_acceptance_criterion]].
- **НЕ тронута** облачная stable 2.1.0.

## ⚠️ Критичные находки/долги (не переоткрывать)
- **Sidecar rebuild нужен** чтобы фикс `decomposer.py::_clean_name` доехал в dist/прод (dev-сайдкар из исходника — там уже ок). [[feedback_sidecar_rebuild_required]].
- **Лайм sacred** (#CCFF00) — только focus/active/Badge/таймер; не primary/error.
- **Канон дизайна** = Svelte `aurora-platform-core/aurora_design` (НЕ React-зеркало). alias-слой `src/aurora-ui-alias.css` оставлен (курс на `--ui-*`). Мёртвый `src/tokens.generated.css` можно снести при чистке.
- Точное позиционирование — ЗАМЕРЯТЬ `getBoundingClientRect` через мост, не на глаз ([[feedback-verify-precise-positioning-by-measuring]]).

## Файлы для контекста (порядок чтения)
1. `Projects/AI_INSIGHTS_ASSISTANT_PLAN.md` — durable trackfile (SSOT статуса Tier 1–3 + отчётности, лог сессий).
2. `Projects/NEXT_SESSION_PROMPT_design_sync.md` — дизайн-трек (закрыт; карта дельт компонентов + backlog focus-trap внутри).
3. Память: `INDEX_econometrica.md` (📍 Состояние) + feedback'и выше.

## Задачи продолжения (приоритет — уточнить у Антона направление)
1. **РЕШЕНИЕ ПО ВЕТКЕ (направление, спросить Антона):** ветка feature-complete (Tier 2 AI «Аврора» + отчётность + дизайн). Мерджить в master / готовить выпуск ~2.2, или продолжать дорабатывать? До мерджа: финальный self-audit gate + sidecar rebuild + проверка обеих редакций (cloud / `--no-default-features`).
2. **Sidecar rebuild + верификация** decomposer-фикса в dist (+ опц. live XLSX на пересобранном сайдкаре — фикстура и opt-in тест готовы, env `AURORA_LIVE_*`).
3. **Опц. focus-trap модалок** (CloudConsent/Onboarding/CommandPalette) → native `<dialog>` (реальный a11y-выигрыш, ты отложил; отдельная задача).
4. **text-muted канон-bump** `#7A7A90→#9090A8` — сторона Маши небесной (`aurora_design/tokens.json`); проверить, долетело ли, если потянем канон-токены.
5. Прежнее (не в фокусе): EULA + `terms_version`; сосуществование двух редакций (productName/identifier).

## Инварианты/правила
- **INV-50 честность:** ненадёжное число (артефакт единиц / model uncertain) НЕ подавать клиенту фактом; `caveat_text` VERBATIM из SSOT `optimizer_honesty`.
- **Зеркала Python↔Rust:** XLSX/MD (`report.rs`) читают results JSON напрямую, мимо Python-моста — любая правка отображаемого значения/имени зеркалится в обоих (clean_label, roi_unreliable, verdict_display, reliability_label, метки режима).
- **Параллельные массивы** (waterfall labels/values/types): равенство длин до индексации, `.get()` не `[i]`, guard вырожденного диапазона.
- **Канарейка специфична** — grep ВЫХОДА генератора на реальном кагоцеле (битые 12186/15525/78/1247/W01 = 0), не юнит.
- **Дизайн:** канон = Svelte aurora_design; «элементами», не вся система; субъективное — faithful-превью/образец до старта + мост для доводки; объективное — гони автономно, доказывай артефактом.
- Коммиты локальные с мини-аудитом; push с approval Антона + секрет-скан diff; свой pathspec (репо общий — untracked-мусор прошлых сессий).
- **Мост для дизайн-правок:** `npm run tauri:dev` (НЕ `tauri dev`) → withGlobalTauri, мост :9223. `CARGO_TARGET_DIR="D:/cargo-targets/ai-agency"` для кэша.

## С чего начать
Прочитать trackfile `AI_INSIGHTS_ASSISTANT_PLAN.md` + этот промт → уточнить у Антона направление: **мерджить/выпускать ветку (Tier 2 + отчётность + дизайн) или продолжать дорабатывать** (задача 1). Оба трека закрыты — это точка принятия решения по выпуску.
