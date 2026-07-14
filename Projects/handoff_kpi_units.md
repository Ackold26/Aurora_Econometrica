# Handoff — KPI-units (единицы целевой метрики через KPI-паспорт)

Блок: ветка `feat/econ-kpi-units` (8 коммитов, от базы `36857cd`). Aurora Econometrica MMM Optimizer.

## 1. Цель блока
Оптимайзер работает не только на выручку/ROI (деньги), но и на счётные метрики (лиды, упаковки,
установки, регистрации, карты, подписки) и режим «эффективность» (каналы в физконтактах). До блока
подписи/вердикты/тексты были захардкожены денежными → вне ROI-режима показывали неверные ₽/ROI. Блок
вводит единый KPI-паспорт: любой слой (подписи, вердикты, инсайты, PPTX/HTML, форматтеры) берёт единицы
и формулировки из паспорта по `kpi_type`, а не хардкодит «₽/ROI/упак» на результате.

## 2. Ключевые инварианты
- Единица результата/метрики отдачи — ТОЛЬКО через паспорт по `kpi_type`; хардкод «₽/ROI/упак» на
  результате запрещён. «₽ у затрат/бюджета/реаллокации» корректно ВСЕГДА (даже для count) — не трогается.
- `kpi_kind` согласован между `utils/kpi_registry.py` (истина модели) и `data/kpi_display_registry.json`
  (display) — стережёт `assert_display_registry_consistent` + contract-тест.
- `src/lib/kpi/kpi-display.generated.js` — только результат генератора `tools/sync_kpi_display.py`;
  ручная правка ловится `--check` (lefthook pre-commit).
- Вердикты count: с ценностью единицы (vpcu) — `eff_mroas = mroas × vpcu` (₽/₽), пороги 0.8/1.0/1.5
  валидны; без vpcu ИЛИ effectiveness — `money_roi_unavailable` → без breakeven-вердиктов (не «Cut»),
  только сигнал оптимизатора + подсказка. Эталон флага — `decomposer.compute_roi_verdict`.
- Backward-compat: без `kpi_type`/kpi-контекста все функции дают прежнее monetary-поведение (дефолты).

## 3. Осознанные компромиссы
- Фронт получает паспорт как СГЕНЕРИРОВАННЫЙ модуль (не runtime-чтение общего JSON) → причина: Tauri-фронт
  и PyInstaller-sidecar — раздельные бандлы, один физический файл в рантайме недостижим без склейки; цена —
  шаг генерации, защищён `--check` + contract-тест.
- Обучающий контент (glossary/tooltip/help): ДОБАВлены примеры count/effectiveness рядом с денежными, НЕ
  полная параметризация под режим → решение заказчика, дешевле, диссонанс убран.
- Старые em-dash «—» в существующих примерах glossary НЕ тронуты (правило хирургических правок) —
  предсуществующий долг; чинился только em-dash в СВОИХ добавках.
- Визуальный слой в окне (оси ECharts, карточки SvelteKit, рендер PPTX/HTML) НЕ прогнан вживую — по
  решению заказчика проверяется попутно; live-probe закрыл data-path на реальном движке.
- Фикстуры live-probe (`tmp/kpi_fixtures/`) — копии денежного pickle с override `kpi_type` на count;
  числа-величины нереалистичны для count (проверялось ПРЕДСТАВЛЕНИЕ единиц, не математика).

## 4. Зоны неуверенности
1. `channel_action` деградация (money_roi_unavailable): оставлены сигналы оптимизатора (ratio≤0.95→Reduce,
   ≥1.05→Scale). Не проверено на реальном count-датасете, что optimizer-ratio для count без денежной
   ценности не даёт вводящий в заблуждение Scale/Reduce (ratio сам мог считаться на денежной оси).
2. `_build_channel_insight` effectiveness ранжирует по `contribution_pct`/`share_of_effect`. Если в
   каком-то пути decompose channel-dict не содержит этих полей → `_share`=0 для всех → top/worst
   схлопываются в первый канал. В реальном decompose поле заполняется (~decomposer:1054), но edge-пути
   (пустые/untrained каналы) не проверены.
3. `narrative_adapter` contrib scale (~:711–712): числовой масштаб `/1e6` оставлен units-neutral, единица
   управляется на стороне потребителя (builder/sections). Не исключено, что какой-то потребитель
   `contrib`-значения всё ещё подписывает «млн ₽» для count — полного обхода всех потребителей не было.
4. Мост «virtual ROI» `eff_mroas = mroas × vpcu`: на реальных count-данных (mroas≈0.01–0.05) пороги
   0.8/1.0/1.5 применяются к eff. Проверено на денежных фикстурах (eff синтетичен) — на живом count-проекте
   калибровка порогов не подтверждена.
5. `format_metric` для count-CPU: `1/mroas` при экстремальных mroas (очень большой→«0 ₽/лид»,
   отрицательный→fallback). На нереалистичной фикстуре видели «0 ₽/лид»; поведение на реальных краевых
   значениях не прогнано вживую.

## 5. Затронутые файлы
- `sidecar/econometrica/data/kpi_display_registry.json` — SSOT единиц целевой метрики (11 KPI).
- `sidecar/econometrica/utils/kpi_display.py` — Python-загрузчик паспорта + русская плюрализация.
- `sidecar/econometrica/tools/sync_kpi_display.py` — генератор фронт-модуля + `--check` drift-страж.
- `src/lib/kpi/kpi-display.js` + `kpi-display.generated.js` — фронт-обёртка + сгенерированные данные.
- `sidecar/econometrica/utils/kpi_registry.py` — `assert_display_registry_consistent`.
- `sidecar/econometrica/utils/kpi_labels.py` — подписи Python из паспорта (kpi_type-aware).
- `sidecar/econometrica/aurora_pptx/kpi_helpers.py` — подписи/фразы PPTX (lift_phrase, hero_vs_leader_quote).
- `sidecar/econometrica/aurora_html/sections.py` — подписи/фразы HTML (зеркало PPTX).
- `sidecar/econometrica/engines/decomposer.py` — `kpi_type` в output-meta + `_build_channel_insight` count-aware.
- `sidecar/econometrica/engines/narrative_adapter.py` — прокидка kpi_type/kwargs в вердикты+labels.
- `sidecar/econometrica/engines/channel_action.py` — вердикты каналов (virtual ROI + деградация).
- `src/lib/kpi-aware-formatting.js` — JS-подписи/метрики из паспорта.
- `src/lib/format-numbers.js` — `formatSpend` (затраты) + `formatKpiValue` (результат по паспорту).
- `src/lib/components/pipeline/InsightsPanel.svelte` — прокидка `kpiType` в kpiView.
- `src/lib/insights-rules.js` — фразы-суждения count-aware.
- `lefthook.yml` — шаг `kpi-display-drift`.
- `src/lib/glossary.js`, `src/lib/data/tooltip-texts.js`, `src/lib/help-econometrica/analysis-mode.html` — обучающий контент.
- Тесты (pytest): `test_kpi_display_registry`, `test_kpi_labels_passport`, `test_channel_action_kpi_aware`,
  `test_report_text_kpi_aware`, `test_kpi_units_lint`, `test_decomposer_insight_kpi_aware`.
- Тесты (vitest): `kpi-display`, `format-numbers-kpi`, `insights-kpi-count-aware`, `kpi-units-lint`,
  `kpi-contract-parity`, доп. кейсы в `kpi-aware-formatting`.
