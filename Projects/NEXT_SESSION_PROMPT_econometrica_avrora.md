# Следующая сессия — Аврора (Tier 2 ИИ-ассистент в Econometrica Optimizer)

> Скопируй этот промт в начало новой сессии. **cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`**.

## Контекст (что уже сделано — НЕ переоткрывать)
Построена **Аврора** — встроенный ИИ-ассистент (Tier 2) поверх детерминированных инсайтов (Tier 1). Ветка **`feat/ai-insights-tier2`** — **13 коммитов от master `7fbfd96`, ЛОКАЛЬНО, НЕ запушена** (push ждёт слова Антона).

Сделано и **live-verified на реальной модели** через MCP-мост:
- **Фаза 0** — INV-50 страж `src/lib/insights-grounding.js` (сверяет числа в ответе LLM с фактами модели).
- **Фаза 1** — «Спросить Аврору»: объяснение результата простым языком. JS-ядро `src/lib/tier2-context.js` (`TIER2_SYSTEM_RULES` + grounding-контекст), Rust-команда `econ_ask_insight` (`src-tauri/src/lib.rs`) через единый egress-чок-поинт `run_claude` (cabinet econometrist), UI в `InsightsPanel.svelte`.
- **Фаза 2** — runtime-тумблер «только локально» (egress отключается в одной сборке): `user_config.local_only` + `ensure_not_local_only` в обоих чок-поинтах claude.rs + тумблер в Настройках.
- **Фаза 3** — советчик «Что если»: NL→config→`econ_scenario`→интерпретация. `src/lib/scenario-advisor.js`.
- **Методология первоисточников** (Binet&Field/Sharp/McElreath/Kahneman/Knaflic из `D:\Docs\Knowledge_Library`) → правила 6–10 промпта.
- **Стиль/границы** (live-feedback Антона): деловой тон, только тематика, безопасность, чистота артефактов кабинета (+ `sanitizeAvroraText`).

## Файлы для контекста (порядок чтения)
1. **`Projects/AI_INSIGHTS_ASSISTANT_PLAN.md`** — durable trackfile (полный план + лог 13 шагов сессии + точка возобновления).
2. **`Projects/AVRORA_METHODOLOGY_FINDINGS.md`** — отчёт библиотеки + **roadmap улучшений** (приоритеты).
3. Память: `INDEX_econometrica.md` (🆕 2026-06-20), `feedback_live_e2e_via_mcp_bridge_fire_poll`, `feedback_inline_claude_via_cabinet_inherits_artifacts`, `feedback_em_dash_jsdoc_breaks_svelte_check`, `project_knowledge_library`.
4. Код: `tier2-context.js`, `scenario-advisor.js`, `insights-grounding.js`, `InsightsPanel.svelte`, `src-tauri/src/lib.rs` (econ_ask_insight ~318).

## Задачи продолжения (приоритет)
1. **Push** ветки `feat/ai-insights-tier2` (с diff + approval Антона — правило D10).
2. **Методология roadmap** (из `AVRORA_METHODOLOGY_FINDINGS.md`, если Антон дополнил Knowledge_Library MMM-книгами — сначала **проиндексировать**: `ingest.py --subdir "<тема>"` → `index --mode add --cat "<тема>"` → перезапуск демона; ~1.5ч/10К чанков CPU, не параллелить):
   - Новый **INV causal-caveats** (McElreath) в `aurora-meta/ENGINEERING_INVARIANTS.md` (решение Антона).
   - **Caveat коллинеарности** в советчике (данные корреляций уже есть в валидации).
   - **Тон honesty-gate** при низком ratio: «модель намеренно сдержана» вместо «сломана» (priors компенсируют).
   - **Takeaway-заголовки** инсайтов + **диапазоны** вместо ложной точности.
3. **Справка в контекст Авроры** — подать glossary.js + руководства, чтобы отвечала строго по содержанию справки (сейчас знает программу частично из системного промпта кабинета).
4. **kind=optimize** в советчике (сейчас только scenario; optimize отсылает на шаг «Оптимизация»).
5. Опц. дозапись MMM-книг (Robyn/Meta whitepaper, Jin et al. 2017) в `Knowledge_Library` тему «Эконометрика и статистика» (агенты отметили пробел — нет прямой MMM-методологии).

## Инварианты/правила
- **INV-50** (честность метрик): Аврора не выдумывает числа — все из фактов модели; страж `findUngroundedNumbers` проверяет; при неуверенности — качественно без числа.
- **Единый egress-чок-поинт**: весь облачный ИИ только через `run_claude` (consent + feature + local_only гейты). НЕ открывать второй API-канал (152-ФЗ/INV-38).
- **Imenа каналов** для econ_scenario — `c.name` (с `\n`), не display_name (согласование с pkl).
- `npm run check` = 0 ошибок (не только vitest — ловит TS-специфику, напр. em dash в JSDoc).
- Коммиты локальные с мини-аудитом; push только с approval; цель — не трогать stable 2.1.0.

## ⚡ Как работать эффективно (мета-урок этой сессии — главное)
**Живой прогон AI-фичи = двигатель итераций, а не финальная приёмка. И не перестраховывайся — проверяй дёшево.**
1. **Live-цикл с первого шага:** держи `npm run tauri:dev` + MCP-мост (`driver_session :9223`) поднятыми С НАЧАЛА, гоняй реальные `econ_ask_insight`/`econ_scenario` на каждой вехе. Поведенческие дефекты LLM (выдуманное число, артефакты кабинета, тон) СТРУКТУРНО невидимы юнит-тестам — ловятся только живьём. Долгие вызовы — fire async + poll dev-лога (см. `feedback_live_e2e_via_mcp_bridge_fire_poll`).
2. **Антон на работающем продукте — быстрейший UX-верификатор:** дай рабочий MVP рано, итерируй точечными правками вживую, не полируй в воображении.
3. **Анти-перестраховка:** контекст-бюджет щедрее инстинкта; юр-оговорки только с основанием; вместо осторожного допущения — дешёвый зонд реальности.

## С чего начать
Прочитать trackfile (1) + roadmap (2) → уточнить у Антона: (а) дал ли push, (б) дополнил ли Knowledge_Library MMM-книгами (если да — индексировать), (в) какой пункт roadmap берём первым. Поднять dev+мост сразу, если будем трогать Аврору.
