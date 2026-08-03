# Следующая сессия — Синхронизация отчётности с программой (Волна 1, продолжение)

> cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`. Ветка `feat/ai-insights-tier2` (запушена до `d733d47`).

## Контекст (НЕ переоткрывать)
Клиентские отчёты MMM-оптимизатора (HTML/PPTX/XLSX/Markdown) генерятся из прогона, но отстали от программы → дефекты честности (INV-50). Полный аудит (4 субагента) + карта — в **`Projects/AI_INSIGHTS_ASSISTANT_PLAN.md`** секция «🔧 АУДИТ ОТЧЁТНОСТИ + ВОЛНА 1» (читать ПЕРВЫМ).

**Уже сделано и запушено (Волна 1):**
- ✅ Шаг 1 — единый честный тон оговорки тонких данных (McElreath: «модель сдержана, опирается на priors», не «артефакт переобучения») во всех отчётах + UI. `diagnostics.format_thinness_caveat` + `report.rs` зеркало.
- ✅ Шаг 2 п.1 — заглушка битых ROI (TRPs 15525×/«Статьи» — артефакт единиц) во всех 4 форматах. Признак `_roi_unreliable(ch)` (Python) + `roi_unreliable(ch)` (Rust). data-level обнуление в мосте (HTML/PPTX) + Rust-helper «н/д» (XLSX/MD).

## Задачи (приоритет)
1. **model_reliability-плашка в отчёты** (пункт 2). Сейчас мост `narrative_adapter.py` НЕ доносит `optimization.json → model_reliability` (verdict `uncertain`/`unreliable`, `caveat_text`, `reasons`, OVB-оговорка про исключённые праздники). Прокинуть через `_map_pipeline_to_builder_data` в `data["diagnostics"]["model_reliability"]`; HTML (`aurora_html/sections.py`) + PPTX (`aurora_pptx/builder.py`) показывают явной плашкой при verdict != reliable. (Тон уже синхронизирован — это добавляет полноту: почему модель неуверена, OVB, дивергенции.)
2. **Синхрон вердиктов таблицы** (пункт 3). `derive_verdict`=`compute_channel_action().key` даёт «Uncertain», а decompose action — «Scale» → один канал два вердикта в одном отчёте. **Развилка (решить с Антоном): honesty доминирует** — при `model_reliability.verdict != reliable` вердикты каналов смягчаются (нельзя «масштабировать» при неуверенной модели). Согласуется с гейтом M2.
3. **Волна 2 (фактические ошибки):** XLSX лист «Декомпозиция» молч. теряется (`report.rs:1075` `.as_array()` на объекте `waterfall {labels,values,types}` → читать как объект); PPTX «Наблюдений 78»(реально 31, формула 6×13)/ESS 1247 фабрикация(поля нет)/период «W01 W13 2026» выдуман(данные месячные)/«13 слайдов»→16; baseline 65% показать явно во всех (нарратив «Social 34% продаж» вводит в заблуждение — это доля медиа-вклада, медиа всего 35%).
4. **Волна 3 (полнота/полировка):** метки режима анализа (ROI/Эффективность/смешанный) и типа KPI (денежный/количественный→ROI/CPU) в отчётах; `sales_share`; глоссарий XLSX 11→47 терминов; версия «v1.0.13» зашита в `report.rs:857`; гигиена клиентского текста (англицизмы saturation/reallocate/breakeven, имена каналов с `\n`/мусором, протёкший project_id в имя клиента PPTX).

## Инварианты/правила
- **INV-50** честность метрик: ненадёжное число (артефакт единиц, model uncertain) НЕ подавать клиенту как факт — качественная оговорка.
- **Единый источник тона:** `optimizer_honesty.py` (UI/Аврора) ↔ `diagnostics.format_thinness_caveat` (отчёты) ↔ `report.rs` (XLSX-зеркало, синхрон вручную, тест сверяет). При правке тона — все три.
- **Rust ⊥ Python путь:** XLSX/MD (`report.rs`) читают results JSON напрямую, мост Python их не покрывает — нужна своя Rust-заглушка (helper `roi_unreliable`).
- **Тесты:** `cd sidecar/econometrica && python -m pytest tests/test_deliverable_thinness_disclosure.py tests/test_diagnostics_verdict.py`. Rust: `CARGO_TARGET_DIR="D:/cargo-targets/econ-check" cargo check --manifest-path src-tauri/Cargo.toml` (не конфликтует с dev). Системный python 3.12 + pytest есть; pptx/openpyxl установлены.
- Коммиты локальные с мини-аудитом, push с approval Антона, своим pathspec (репо общий — есть untracked-мусор CC-Sessions/tmp).

## Параллельное направление — доработки по дизайну приложения (UI/UX)
> Запрос Антона (2026-06-20): помимо отчётности, в следующей сессии — **доработки дизайна интерфейса приложения** (не отчёты — сам UI Optimizer: SvelteKit 5 + дизайн-система Aether Mesh, glass tiers; см. `CLAUDE.md` раздел «UX Architecture v2.0»). **Конкретику Антон задаёт в начале сессии** (какие экраны/элементы дорабатываем) — не выдумывать, уточнить.
> **Инструменты:** автономный визуальный аудит вживую — стандарт AVT (программная инспекция `mcp__tauri__webview_dom_snapshot`/`webview_*` > скриншоты; готовая фикстура-проект вместо прохода pipeline; чек-лист на экран; верифицировать находки), скилл **`visual-audit`** (десктоп Tauri); для нового UI/полировки — `frontend-design` / `ui-ux-pro-max` / `design-system`. Поднять `npm run tauri:dev` + MCP-мост (`driver_session :9223`); проекты-фикстуры — кагоцел (125 шт в `%APPDATA%\aurora-econometrica-gui\projects`).
> **Зацепка этой сессии:** UX-фикс блока «Что если» (был виден на шаге Обучение — перенесён на Оптимизацию) показал, что панель инсайтов/«Аврора» живёт в реальном UI и стоит пройти GUI-аудит панели + всех 6 шагов пайплайна на консистентность/полировку. Ключевые компоненты: `InsightsPanel.svelte`, `cabinet/+page.svelte` (Selection/Execution), `NavRail.svelte`, `routes/pipeline/`.

## Как проверять (мета-урок)
Перегенерировать отчёт на РЕАЛЬНОМ прогоне (метод «артефакт в работе»), не на синтетике: проект `кагоцел-…-2006-26--3` (ratio 2.4, есть unit_smell-канал TRPs — идеальная фикстура). Путь: `C:/Users/ackol/AppData/Roaming/aurora-econometrica-gui/projects/<id>/results/`. HTML/PPTX — через `engines.html_export.build_html` / `aurora_pptx.builder.AuroraPPTXBuilder` на python. XLSX — Rust (live после пересборки).

## С чего начать
Два направления в работе: **(A) отчётность Волна 1** (задачи выше) и **(B) доработки дизайна приложения** (раздел выше). Уточнить у Антона приоритет/порядок. Для (A): прочитать trackfile секцию «Аудит отчётности» → (а) пункт 2 (плашка) или пункт 3 (синхрон вердиктов) первым; (б) решение по развилке вердиктов (honesty доминирует?); открыть проект 2006-26--3 как фикстуру. Для (B): уточнить конкретику дизайна → поднять dev+мост → AVT/visual-audit.
