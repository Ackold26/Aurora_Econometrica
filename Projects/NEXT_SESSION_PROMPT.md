# Следующая сессия — Aurora Econometrica Optimizer (роутер)

> Скопируй в начало следующей сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`. Ветка `feat/ai-insights-tier2`.

## Контекст — что сделано (сессия 2026-06-20, 8 коммитов `d3fff90..da330d1`, ВСЁ ЗАПУШЕНО)
- **✅ СИНХРОНИЗАЦИЯ ОТЧЁТНОСТИ закрыта (Волны 1-3, честность INV-50)** — клиентские отчёты HTML/PPTX/XLSX/MD больше не расходятся с программой ни по числам, ни по тону, ни по терминам:
  - В1: плашка надёжности модели (`aaeaca8`) + синхрон вердиктов honesty-потолок 2a (`e125521`).
  - В2: waterfall-лист восстановлен + фейк-наблюдения 78→31 + ESS 1247→н/д + период выдуман→реальный (`9ecd00c`).
  - В3: версия модели + англицизмы + имя клиента (`1235656`); метки режима/KPI (`b694283`); глоссарий XLSX 11→47 из SSOT glossary.js (`796c1df`).
- **✅ Глубокий аудит сессии** (3 read-only субагента: математика/логика, Rust-техника, зеркала+INV-50) — зеркала Python↔Rust 0 расхождений; 4 реальных фикса (`7a39879`: waterfall panic-риск на параллельных массивах, chart-range guard, MD denom, частота delta=0). Большинство находок субагентов — FP/вне скоупа.
- **✅ Дизайн-трек заземлён** (`da330d1`): alias-слой канон-namespace создан (под вопросом), новый промт.
- **НЕ тронута** облачная stable 2.1.0.

## Файлы для контекста (порядок чтения)
1. `Projects/AI_INSIGHTS_ASSISTANT_PLAN.md` — trackfile (SSOT статуса отчётности, durable лог сессии).
2. `Projects/NEXT_SESSION_PROMPT_design_sync.md` — **дизайн-трек** (основной незакрытый; полное заземление + задачи + обмен с Машей design-sync).
3. `Projects/NEXT_SESSION_PROMPT_reports_wave1.md` — отчётность (исторический; статус-истина в trackfile).
4. Память: `INDEX_econometrica.md` (📍 Состояние) + feedback'и `feedback_blank_displayed_value_all_paths_and_derivatives` (карта путей+канарейки), `feedback_parallel_arrays_length_equality_before_index` (аудит-урок), `feedback_batch_decision_forks_before_code`.

## Задачи продолжения (приоритет)
1. **ДИЗАЙН-трек (основной)** — см. `NEXT_SESSION_PROMPT_design_sync.md`. Уточнить у Антона приоритет, затем: (а) решить alias-слой оставить (курс Маши на сходимость `--ui-*`) vs откатить (0 потребителей); (б) InsightCard dark severity-tint (нейтральный 3%→цветной 8%, выровнять под DS и свою light-тему) — единственная реальная дельта, live-рендер обязателен; (в) широкий проход компонентов Эконометрики vs канон Button/Card/Modal/Badge — доказать «выравнивать, не портировать». Обмен с Машей design-sync через Антона.
2. **Отчётность — остаток (низкий):** **live XLSX/MD-выход** (waterfall-лист, плашки надёжности/режима, глоссарий-47, метка версии) проверить ВЖИВУЮ после пересборки Rust/dev — доказано cargo+probe, но не на реальном XLSX. + хвост Волны 3 (sales_share-метрика, если всплывёт).
3. **text-muted канон-bump** `#7A7A90→#9090A8` — сторона Маши небесной (`aurora_design/tokens.json`, a11y). Проверить, долетело, если потянем канон-токены.
4. Прежнее (не в фокусе): EULA + `terms_version`; сосуществование двух редакций (productName/identifier).

## Инварианты/правила (соблюдать)
- **INV-50 честность:** ненадёжное число (артефакт единиц / model uncertain) НЕ подавать клиенту фактом — качественная оговорка; `caveat_text` VERBATIM из SSOT.
- **Зеркала Python↔Rust:** XLSX/MD (`report.rs`) читают results JSON напрямую, мимо Python-моста — любая правка отображаемого значения зеркалится в обоих; лейблы/логика синхронны (soften_verdict_display↔verdict_display, reliability_label, roi_unreliable, метки режима).
- **Параллельные массивы** (waterfall labels/values/types): равенство ВСЕХ длин до индексации, `.get()` не `[i]`, guard вырожденного диапазона.
- **Канарейка специфична** (голое `W01`/`Recommendation` дают FP на base64/CSS); grep ВЫХОДА генератора на реальном кагоцеле `2006-26--3`, не юнит.
- **Дизайн:** канон = Svelte `aurora-platform-core/aurora_design` (НЕ React-зеркало); «элементами», не вся система; tracer внутри Эконометрики до РЕНДЕРА (drift=0 недостаточно); лайм sacred (focus/active/Badge-lime); логотип Horizon (не wb-flat).
- Коммиты локальные с мини-аудитом; push с approval Антона + секрет-скан diff; свой pathspec (репо общий — есть untracked-мусор прошлых сессий).

## С чего начать
Прочитать trackfile `AI_INSIGHTS_ASSISTANT_PLAN.md` + `NEXT_SESSION_PROMPT_design_sync.md` → уточнить у Антона: дизайн-трек (alias-решение + InsightCard tint) или сначала live-проверка отчётности на пересобранном Rust/dev. dev-окно `aurora-econometrica-gui.exe` + мост `:9223` можно поднять для live (`npm run tauri:dev`).
