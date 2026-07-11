# Следующая сессия — KPI-units (единицы целевой метрики)

Скопируй этот промт в начало следующей сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`.

## Контекст (что сделано)
Сквозная проблема «Оптимайзер вне ROI-режима показывает ₽/ROI на результате» РЕШЕНА системно.
Ветка `feat/econ-kpi-units` (от `36857cd`, база P-1). **НЕ смержена, НЕ запушена.** Теги:
`v-kpi-units-phase{0,1,3,verdicts,4,live-probe,audit-fixes}`.
- Фазы 0–4: KPI-паспорт (единый JSON-источник единиц → генерируемый фронт-модуль; contract-тест +
  lefthook `--check` против дрейфа) · подписи · вердикты (virtual ROI + честная деградация) · тексты
  PPTX/HTML/инсайтов · гейты · обучающий контент.
- Live-probe реальным движком (INV-33) вскрыл утечку «ROI» в insight → починено.
- **Внешний diff-аудит (2 старших Opus, чистый контекст):** 2 High + 3 Medium найдены и починены,
  fix-коммит `2ffa970`. High были ЧИСЛОВЫЕ (CPU занижен в vpcu раз; «₽» на count-вкладе) — юнит-тесты
  их не ловили (проверяли подстроку, не величину). Добавлен регресс-тест на величину CPU.
- **Кодификация:** `aurora-meta/DECISIONS/ADR-038-kpi-passport-metric-units.md` + `INV-95` + пункт §6 —
  в рабочем дереве aurora-meta, **ЖДУТ sync** (в default-ветку канона сама не коммичу).

## Файлы для контекста (порядок чтения)
1. `~/.claude/projects/D--Docs-Aurora-Ai/memory/INDEX_econometrica.md` (шапка KPI-units сверху).
2. `Projects/handoff_kpi_units.md` — цель/инварианты/компромиссы/зоны неуверенности/файлы.
3. `TEST_FINDINGS_kpi_units_live_2026-07-11.md` — живой прогon + находка+фикс.
4. `MODE_METRIC_UNITS_AUDIT_2026-07-11.md` + `MODE_METRIC_UNITS_SOLUTION_2026-07-11.md` — анализ+дизайн.
5. Память: `feedback_econometrica_pytest_cwd_bootstrap`, `feedback_test_asserts_what_agent_claims`.
6. Код: `sidecar/econometrica/{utils/kpi_display.py,utils/kpi_labels.py,engines/channel_action.py,
   engines/decomposer.py}` + `src/lib/{kpi-aware-formatting.js,format-numbers.js,insights-rules.js}`.

## Задачи продолжения (приоритет)
1. **Решение Антона: мерж ветки** `feat/econ-kpi-units` (+ порядок с P-1 `feat/econ-planning-mode` —
   обе от близких точек; проверить конфликты `decomposer.py`/`narrative_adapter.py`, которые трогали обе).
2. **Sync канона** aurora-meta (ADR-038 + INV-95) — по команде «синхронизируйся».
3. **Визуальный слой в окне** (осталось от INV-33): оси ECharts, карточки вердикта/action/insight
   SvelteKit, рендер PPTX/HTML вживую на 3 режимах. Фикстуры готовы в `tmp/kpi_fixtures/` (monetary/
   count_leads_vpcu/count_leads_novpcu/effectiveness). **Перед поднятием окна — уточнить состояние машины**
   (порт :5173 был занят; не задеть открытую работу P-1).
4. **Реальный count-проект** для калибровки порогов virtual ROI (зона §4.4 handoff): мост
   `eff=mroas×vpcu` с порогами 0.8/1.0/1.5 проверен на денежных фикстурах, не на живых count-данных.
5. **TODO из аудита (Medium, отложены):** (a) `format-numbers.js` proportional/awareness → money-fallback
   даёт «35 ₽» вместо «35 %» (awareness out-of-scope v13, но паспорт есть); (b) `kpi-aware-formatting.js`
   count-ветка — guard `P.kpi_kind==='count'` (защита от рассинхрона стора, штатно недостижимо);
   (c) зеркало JS↔Python: effectiveness+count без kpiType даёт «ед.» (JS) vs «упак / ед.» (Python) —
   привести к одному канону; (d) `lefthook.yml` drift-страж читает диск, не staged → при частичном
   `git add` рассинхрон просочится (обычно `git add -A`, потому Medium).

## Инварианты/правила
- Единица результата/метрики — ТОЛЬКО через KPI-паспорт по `kpi_type`; «₽ у затрат/бюджета» корректно
  всегда, не трогать. Backward-compat: без kpi_type → прежнее monetary.
- `kpi-display.generated.js` не редактировать руками (генератор `sync_kpi_display.py`).
- Клиентский текст: короткое тире «–», русский без англицизмов.

## С чего начать
Прочитать handoff_kpi_units.md + INDEX_econometrica шапку → уточнить у Антона: мерж сейчас или после P-1;
поднимать ли окно для визуального слоя (состояние машины). Затем по приоритету.

## 🔴 Руководство по стилю действий (ПРОЧИТАТЬ ПЕРВЫМ, выведено из этой сессии)
1. **pytest ТОЛЬКО из `sidecar/econometrica/`** (`cd sidecar/econometrica && python -m pytest tests/…`).
   Запуск из `sidecar/` → `ModuleNotFoundError: aurora_pptx` — это cwd, НЕ дефект. В этой сессии стоило
   времени + ложного подозрения субагента. `_tkinter.TclError` (matplotlib) — тоже окружение, не регресс.
2. **Проверять ВЕЛИЧИНУ числа, не подстроку.** Оба High-бага аудита были числовые (CPU 0.6 вместо 50;
   «₽» на count-вкладе), а тесты/гейты проверяли лишь наличие «₽/лид» — пропустили. При ревью
   агентских фиксов гонять probe с конкретным входом и сверять число, не «тест зелёный».
3. **Live-probe реальным движком гонять РАНО** — он вскрыл утечку, которую все юнит-тесты Фаз 0-4
   пропустили. Фикстуры через override `kpi_type` на готовом pickle (не переобучать MCMC).
4. **Внешний diff-аудит чистым контекстом окупается** — 2 High нашёл только он. При завершении крупного
   блока не пропускать (даже если свои тесты зелёные).
5. **Перед поднятием GUI-окна — спросить состояние машины** (AVT-протокол): :5173/окно/параллельная
   работа P-1. Не поднимать вслепую.
6. **Клиентский текст — проверять em-dash в СВОИХ добавках лично** (субагент заявил «ноль», был em-dash).
   Старые «—» в чужом коде не трогать (хирургия), чинить только свои вставки.
