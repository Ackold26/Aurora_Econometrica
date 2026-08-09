# Pulse — разведка ai-insights-tier2

## Задача (своими словами)
Ветка `origin/feat/ai-insights-tier2` помечена тегом `v-tier2-absorbed-2026-08-02` как «поглощённая» в основную ветку `feat/econ-canon-p0`. Но `git cherry` показывает 44 записи с `+` — то есть git по истории коммитов НЕ считает их патч-эквивалентными текущему дереву. Метка может врать. Моя задача — не доверять метке и истории, а руками, по коду, проверить: для каждой из ~10 заметных функций tier2-ветки — реально ли её содержимое присутствует в современном дереве (feat/econ-canon-p0, рабочая копия). Результат — таблица ЕСТЬ/НЕТ/ПЕРЕДЕЛАНО с адресами-доказательствами по каждой из 10 функций, и список того, что потеряется, если ветку не сливать.

## План
1. Получить список 44 коммитов (git log) + просмотреть git cherry вывод для ориентира.
2. Для каждой из 10 функций: найти сигнатуру/строку/файл в современном дереве (Grep по src/, src-tauri/src/, sidecar/); если нет — найти где в tier2 она определена (git show/log по коммитам).
3. Заполнить таблицу с вердиктами и адресами.
4. Записать раздел «что потеряется» — только по вердиктам НЕТ.
5. Сохранить оба файла (pulse + findings), дать краткую сводку.

## Старт: 2026-08-04, 01:29

## Отметка после ~5 обращений (01:32)
Получен список 44 коммитов. Проверила функцию 1 (Аврора/econ_ask_insight) — ЕСТЬ, полностью:
- Rust-мост: src-tauri/src/lib.rs:469 (econ_ask_insight), регистрация в invoke_handler :3670
- Grounding-контекст/промпт: src/lib/tier2-context.js, insights-grounding.js, scenario-advisor.js (+ тесты)
- Тумблер «только локально»: src/lib/components/pipeline/InsightsPanel.svelte, src/lib/store.js, src/routes/+layout.svelte, src/routes/settings/+page.svelte
- UI «Что если»: InsightsPanel.svelte, RecommendationCard.svelte
Дальше проверяю функции 2-10.

## Отметка ~15 обращений (01:45)
- Функция 2 (заглушка ROI): в d0ea3aa был точечный decorator `roi_unreliable` в narrative_adapter — в текущем дереве ЕГО НЕТ (roi_unreliable = 0 совпадений), но decomposer.py/verdicts.py/optimizer.py/narrative_adapter.py содержат гораздо более широкую систему unit_smell/ROI_ARTIFACT детекции с верните-labels ("ROI завышен (не рубли?)" и т.д.) — функционально решает ту же проблему другой архитектурой → ПЕРЕДЕЛАНО.
- Функция 3 (глоссарий XLSX 11→47 SSOT): commit 796c1df добавлял параметр `glossary: Option<Value>` в econ_export_xlsx/build_xlsx + getAllTerms() из ReportStep.svelte. В текущем report.rs (строки 1855-1899) — жёстко закодированный массив из 11 терминов, БЕЗ параметра glossary, БЕЗ getAllTerms в ReportStep.svelte → НЕТ.
- Функция 4 (плашка надёжности 4 отчёта): HTML sections.py:430-441 (model_reliability_verdict) и PPTX builder.py:309,3312,3318 (self.honesty_verdict) — ЕСТЬ, хоть и другим путём (HTML вызывает verdict напрямую, не через narrative_adapter.diagnostics). В report.rs (XLSX+MD) — reliability_label/honesty_verdict = 0 совпадений → НЕТ для двух форматов. Итог по функции — ПЕРЕДЕЛАНО/ЧАСТИЧНО (2 из 4 форматов).
- Функция 5 (метки режима анализа и типа KPI): commit b694283 — analysis_mode_label/kpi_kind_label во ВСЕХ 4 отчётах. В текущем дереве — 0 совпадений `analysis_mode_label|kpi_kind_label|Режим анализа` ни в narrative_adapter.py, ни в sections.py, ни в builder.py, ни в report.rs → НЕТ полностью, во всех форматах.
Дальше — функции 6-10.

## Финал (~38 обращений, 02:10)
Проверила все 10 функций. Попытка записать `findings_tier2.md` заблокирована харнессом
(системное правило: субагентам запрещено писать report/findings/summary .md — только
текстовый ответ команде). Полная таблица вердиктов и раздел «что потеряется» переданы
текстом в финальном сообщении team-lead вместо файла.

Итог: ЕСТЬ=1 (#1 Аврора), ПЕРЕДЕЛАНО=5 (#2,4,6,7,10 — частично у #4 и #6), НЕТ=4 (#3,5,8,9).
