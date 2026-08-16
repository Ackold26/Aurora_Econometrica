# Проверка линии 2 «выигрывать» — по факту кода (2026-08-16)

**Дерево:** `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt`, ветка `master`, HEAD `6fa2498`, версия 2.4.10.
**Режим:** только чтение. Мёртвый код проверялся grep по всему дереву с исключением `dist/`, `target/`, `_internal/`, `node_modules/`, `__pycache__`, `.svelte-kit/`.

---

## 1. Профит-фронтир «сколько вообще тратить» — **НЕ НАЧАТО**

### Что из основания есть
- `optimize/inverse.py:612` `optimize_inverse(...)` — обратная задача «цель продаж → минимальный бюджет» бисекцией, живая: `server.py:2609` → `econometrica.rs:815 econ_optimize_inverse` → `lib.rs:3941` → `OptimizeGoalSeek.svelte:185`. Есть даже квантильный режим «бюджет под вероятность» (`confidence`, server.py:2604).
- `optimize/split_ci.py:23` `optimal_split_ci(...)` — 90% HDI на ДОЛИ сплита по posterior-draws (Jin et al. 2017). Живой: `server.py:2387` → `econometrica.rs:681` → `OptimizeStep.svelte:364`.
- Прибыль присутствует, но как ВХОД, а не как расчёт: KPI-тип `profit` (`utils/kpi_registry.py:132`) — пользователь сам подаёт колонку прибыли; для счётных KPI ценность единицы = маржа (`value_per_count_unit_label='Маржа на упаковку, ₽'`, kpi_registry.py:148). База окупаемости честно называется: `src/lib/kpi-aware-formatting.js:289` `roiBase()` возвращает `'оборот'|'прибыль'|'не определена'`.

### Чего не хватает
Всего заявленного: кривой «бюджет → прибыль», максимума по условию предельная отдача = `1/маржа`, интервала на ПОЛОЖЕНИЕ максимума, честной границы наблюдаемого диапазона.
- `split_ci` даёт интервал на доли при ЗАДАННОМ бюджете, не на оптимальный размер бюджета.
- Прибыль нигде не считается из выручки и маржи — `grep profit_curve|frontier|фронтир` по `sidecar/`, `src/`, `src-tauri/` даёт ноль совпадений.
- Граница наблюдаемого диапазона в агрегате не считается: `optimize/bounds.py:103` объявляет `'aggregate_sales': {lo, hi, current}  # optional, требует forward pass`, строка 106: «Note: aggregate_sales - placeholder. Полный compute требует forward pass», а в возвращаемом словаре (bounds.py:176) есть только `aggregate_budget` — поля нет.

### Прямое признание в коде, что работа не начата
`src/lib/components/pipeline/OptimizeGoalSeek.svelte:106-114`:
> «🔴 Движок его пока не считает: `optimize/bounds.py::compute_safe_corridor` возвращает `per_channel` и `aggregate_budget`, а `aggregate_sales` живёт ТОЛЬКО в докстринге с пометкой «placeholder, требует forward pass» … Настоящий расчёт — в P1, вместе с профит-фронтиром: обоим нужен один и тот же прямой проход через модель, считать порознь значит делать работу дважды.»

То же в тесте-стороже `src/lib/__tests__/goalseek-corridor-honesty.guard.test.js:13`: «Настоящий расчёт вынесен в P1 (общий прямой проход с профит-фронтиром)». Продукт при этом честен с пользователем: `OptimizeGoalSeek.svelte:130` показывает «Зелёная зона – ориентир от текущего уровня продаж, а не диапазон, наблюдавшийся в данных: его модель пока не рассчитывает».

### Мёртвый код
Нет. `optimize_inverse` и `optimal_split_ci` оба имеют живых вызывающих по всей цепочке до интерфейса.

---

## 2. Досье решения — **ЧАСТИЧНО** (четыре части живут порознь, единого объекта нет)

`grep -i "досье|dossier|decision_record"` по `sidecar/`, `src/`, `src-tauri/`, `docs/` — **ноль совпадений**. Единого объекта нет.

### Что из основания есть
| Часть | Состояние | Цепочка вызовов |
|---|---|---|
| Обещания | живые | `engines/promises.py:82 create_promise` / `:144 list_promises` / `:149 check_promises` → `server.py:2541,2552,2575` → `econometrica.rs:771,780,808` → `lib.rs:3938` → `OptimizeStep.svelte:1216` (фиксация) + `PromisesCard.svelte:68` (сверка) |
| Проверка на истории | живая | `engines/backtest.py:58 run_backtest`, `:453 run_rolling_backtest`, `:427 load_saved_backtest`; карточка `BacktestCard.svelte` |
| Сравнение поколений | живое | `engines/model_compare.py:91 compare_generations`, `:333 drift_check`, `:516 load_saved_generation_compare`; экран `ModelComparisonView.svelte` |
| Сертификат | живой | `engines/methodology_cert.py:506 generate_methodology_certificate` ← `engines/decomposer.py:1515` («Сертификат методологии (P0.7 шаг 14) — считается по уже собранной…»); хеш SHA-256 по JCS-канону (`compute_cert_hash`, methodology_cert.py:69), внешний проверяющий — `verify.auroraai.pro` (Rust WASM, methodology_cert.py:6) |

### Связаны ли части между собой
Почти нет. Единственные точки схождения — **отчёт**, а не подписанный объект:
- `engines/narrative_adapter.py:874` принимает `promises`, `:1313` кладёт `data['promises_summary']`; `engines/pptx_export.py:65,105` и `html_export.py:83,133` пробрасывают `promises` и `generation_compare` в сборщик отчёта.
- В **подписанный** payload сертификата не входит ничего из трёх остальных. Реальный payload v1.3 — `methodology_cert.py:337-342`:
```python
    return {
        'bundle_manifest_hash': bundle_hash,
        'model_spec': model_spec_raw,
        'decomposition_summary': decomp_summary,
        'channel_roi': channel_roi,
    }
```
плюс `certificate_version` (`:501`). Проверка на истории попадает в хеш ТОЛЬКО через `_extract_v20_fields` (`:444 'backtest_results': backtest_cert`), а эта ветка по признанию самого кода мертва и сломана — `methodology_cert.py:483-496`:
> «🔴 ВЕТКА НЕДОСТИЖИМА И СЛОМАНА ПО КОНТРАКТУ … `model_version` при обучении равен '1.2'/'1.3' (`modeler.py:1673`), до '2.0.0' его поднимает только `save_v20_diagnostics`, у которой нет ни одного живого вызывающего … ключ режима кладётся как `analysisMode`, а парсер проверяющей стороны объявлен как `analysis_mode` … хеш не сойдётся НИКОГДА.»

Обещаний и сравнения поколений нет в хеше ни в одной ветке.

### Чего не хватает до готовой возможности
- Самого объекта «одно решение = один файл»: что решили, на каком расчёте, при каких допущениях, диапазон, кто проверяет, чем подтвердилось.
- Включения обещаний, проверки на истории и сравнения поколений в подписываемый payload (сейчас подписаны только разбивка, окупаемость каналов, спецификация модели и хеш поставки).
- Автодописывания исхода на новых данных: `check_promises` дёргается только вручную кнопкой в `PromisesCard.svelte:68`; авто-вызова при загрузке новых данных в дереве нет.
- Офлайн-проверки на стороне клиента: верификатор — внешний веб-сервис `verify.auroraai.pro`; локального инструмента сверки хеша в `tools/` нет.

### Мёртвый код
**Есть, признан в коде:** `_extract_v20_fields` (`methodology_cert.py:345`) и вся v2.0-ветка `build_cert_payload` (`:482-498`) недостижимы, потому что `save_v20_diagnostics` не имеет вызывающих. Оставлено намеренно, решение за владельцем.

---

## 3. Реестр допущений и «что сломает этот вывод» — **НЕ НАЧАТО** (правая колонка есть отдельно)

### Что есть
- Торнадо чувствительности живой и считается при обучении: `engines/sensitivity.py:60 compute_sensitivity_tornado` ← `engines/modeler.py:1709-1710`:
```python
            from engines.sensitivity import compute_sensitivity_tornado
            diagnostics['sensitivity_tornado'] = compute_sensitivity_tornado(model_data)
```
с оговоркой в комментарии `modeler.py:1701`: «Движок (sensitivity.py, 673 строки) и график (SensitivityTornado.svelte)…». График — `src/lib/components/pipeline/SensitivityTornado.svelte`. То есть «насколько чувствителен результат» (правая колонка) есть.
- Разрозненные оговорки о допущениях: `engines/optimizer.py:444` и `engines/scenario.py:385` («Допущение стационарности коэффициентов…»), `utils/optimizer_honesty.py:293`, `aurora_pptx/builder.py:3420` («оценки чувствительны к допущениям модели»).
- Полноценная таблица допущений есть только в каузальном модуле и только для него: `engines/causal/common.py:60-73` `HonestDisclosure` с полем `assumptions: list[str]`, заполняется в `causal/did.py:173`, `causal/scm.py:341`, `causal/causal_forest.py:190`, показывается в `src/lib/components/causal/CausalResultCard.svelte:81-84`.

### Чего не хватает
Таблицы «допущение → почему приняли → что будет, если неверно → чувствительность» для основного MMM-пути нет ни в отчёте, ни в интерфейсе. Правая колонка (торнадо) и левые три (допущения) нигде не сведены в один объект; `HonestDisclosure` каузального модуля к MMM-выводу не подключён.

### Мёртвый код
Нет: и торнадо, и `HonestDisclosure` имеют живых вызывающих.

---

## 4. Знание бренда и ESOV в интерфейс — **ЧАСТИЧНО** (движок готов, интерфейса ноль)

### Сколько слоёв реализовано в движке — четыре из четырёх
1. Медиа → знание с длинным затуханием: `engines/awareness.py:146-151` — adstock Weibull (shape 2, scale 4) поверх трат перед регрессией, `:156-164` AR(1) `awareness[t] = decay·awareness[t-1] + impact·spend[t]`.
2. Честный прогнозный интервал: `awareness.py:188-197`, `ci_method = 'ar1_forecast_variance_90'` — формула дисперсии AR(1) вместо прежней константы (мат-аудит F-26).
3. **ESOV есть:** `awareness.py:41 _esov_module` (Binet & Field), константы `:29-30` `ESOV_SLOPE_POINT = 0.05`, `ESOV_SLOPE_RANGE = (0.05, 0.07)`; `:76-80` `esov_series = sov_a - som_a`, ожидаемый рост SOM = наклон × средний ESOV; включается только при живых колонках SOV/SOM (`:42-45` «модуль не выдумывает»). Результат кладётся в выдачу: `:218 'esov': esov`.
4. Знание → продажи S-кривой: `awareness.py:238 awareness_to_sales`, логистика `:13 s_curve`.

### Доставка: три слоя из четырёх
- Движок ✅ → HTTP `server.py:1919 /compute/awareness/forecast`, `:1929 /compute/awareness/sales` ✅ → Rust `econometrica.rs:378 econ_awareness_forecast`, `:384 econ_awareness_sales`, зарегистрированы в `lib.rs:3950-3951` ✅ → **интерфейс: ноль.** `grep "econ_awareness_forecast|econ_awareness_sales" src/` — ни одного совпадения.

### Можно ли выбрать KPI «знание бренда» — нет
- Зарегистрирован с брендовыми приорами: `utils/kpi_registry.py:196-215` — `'awareness': KPIConfig(name='awareness', likelihood='logit_normal', kpi_kind='proportional', out_of_scope_v13=True, ceiling=100.0, brand_mu_logit_prior=(1.4, 0.4), …)`, комментарий `:195`: «PROPORTIONAL (out of scope v1.3)».
- В интерфейсе выбрать нельзя: `KPISelector.svelte:23` перечисляет ровно 10 типов без awareness, `iconMap` (`:47-58`) тоже без него, `monetaryOptions`/`countOptions` (`:69-80`) — тоже.
- Бэкенд его и не предложит: `engines/validator.py:981-993` собирает `available_kpi_types` только из `_MONETARY_KPI_TYPES = ['sales', 'revenue', 'profit']` и `_COUNT_KPI_TYPES`; awareness не входит ни в один набор, а фронт по этому списку гасит карточки (`KPISelector.svelte:41-44`).
- Более того, `server.py:391` прямо отвергает связанные типы: «'aided_awareness'/'top_of_mind'/'unaided_awareness' → reject через…».

### Мёртвый код
**Есть.** `econ_awareness_forecast` и `econ_awareness_sales` (`econometrica.rs:378,384`) зарегистрированы в `lib.rs`, но не вызываются ни из одного файла `src/` — Rust-команды без потребителя. Соответственно и `forecast_awareness` / `awareness_to_sales` / `_esov_module` достижимы только через прямой HTTP к движку или чат-кабинет `econometrist` (`cabinet.rs:276-277`: `/awareness-forecast`, `/awareness-to-sales`), но не через пайплайн приложения. Также `charts/generators.py:106 awareness_chart` рисуется только по файлу `results/awareness-forecast.json` (`server.py:1965-1968`), который создаёт лишь `forecast_awareness`.

---

## 5. Советник, видящий всю диагностику — **НЕ НАЧАТО** (утверждение задачи подтверждено точно)

### Что собирает контекст советника сейчас
Единственный сборщик — `src/lib/tier2-context.js:190 buildTier2Context(input)`. Его единственный живой вызывающий — `src/lib/components/pipeline/InsightsPanel.svelte:410`, и он передаёт ровно это (`InsightsPanel.svelte:410-427`):
```js
    const ctx = buildTier2Context({
      step: $pipelineCurrentStep,
      question: askQuestion,
      tier1Insights: insights,
      val: $validateData,
      mod: $modelData,
      dec: $decomposeData,
      opt: $optimizeData,
      methodology,
      kpiType: $kpiType, kpiKind: $kpiKind, valuePerCountUnit: $valuePerCountUnit,
```
То есть в советник попадают: валидация, модель (`summarizeModel`, tier2-context.js:107 — r_hat, дивергенции, ratio, R², MAPE, MQS), декомпозиция (`summarizeDecompose`, :60), оптимизация (`summarizeOptimize`, :84), база окупаемости (`:243 facts.roi_base`), справка о программе (`buildHelpContext`, :251) и выдержки из RAG-библиотеки первоисточников (`:255`).

### Чего нет — ровно перечисленное в задаче
`grep` по `tier2-context.js` и `InsightsPanel.svelte`: `backtest`, `promises`, `generation_compare`/`model_compare`, `split_ci` — **ни одного упоминания**. Советник не знает о проверке на истории, обещаниях, сравнении поколений и интервалах оптимального сплита, хотя все четыре артефакта посчитаны и лежат в проекте.

Вердикт надёжности берётся из одного места — `tier2-context.js:130-138`:
```js
function extractHonesty(opt) {
  const mr = opt?.model_reliability;
```
это `optimization.json → model_reliability`, то есть строго артефакт оптимизации (докстринг `:125`: «Источник — optimization.json `model_reliability`»). Подтверждает формулировку задачи «вердикт надёжности берёт только из оптимизации».

### Чего не хватает
Расширить вход `buildTier2Context` артефактами `backtest.json`, `promises.json`, `generation_compare`, `split_ci` + добавить их сводки в `facts` и в `grounding.jsonFacts` (иначе рантайм-страж `findUngroundedNumbers` пометит их числа как выдуманные — `InsightsPanel.svelte:453`).

### Мёртвый код
Нет.

---

## 6. Локальный советник для редакции 152-ФЗ — **НЕ НАЧАТО** (советника нет, замены нет; детерминированный разбор есть, но не связан)

### Что видит пользователь локальной редакции
- Блок «Спросить ИИ» скрыт целиком гейтом `InsightsPanel.svelte:359-364`:
```js
  const canAsk = $derived(
    $cloudConsent.advisorsEnabled &&
      $cloudConsent.granted &&
      !$cloudConsent.localOnly &&
      $isEconometrica,
  );
```
`advisorsEnabled` приходит из Rust-константы `claude.rs:132 pub const CLOUD_ADVISORS_ENABLED: bool = cfg!(feature = "cloud_advisors");`, а локальная редакция собирается `--no-default-features` → `false`. Никакой локальной замены на месте скрытого блока в коде нет.
- Остаётся Tier-1: детерминированные правила `src/lib/insights-rules.js` (2490 строк, не 2375 — файл вырос), вызываются в `InsightsPanel.svelte:35-38` (`importInsights`, `validateInsights`, `modelInsights`, `modelPreTrainingInsights`, `decomposeInsights`, `optimizeInsights`, `reportInsights`) и в `ValidateStepV13.svelte:51`. Форма инсайта: `severity` (error/warning/info/success — 141 вхождение), `text` (158), `tip` (113), `action` (19, применимое действие с откатом — `InsightsPanel.svelte:60 appliedActions`).
- В отчёте (он собирается локально, без обращений наружу) — раздел «Петля доверия» `aurora_html/sections.py:2190 render_trust_loop` и связный текст от `engines/narrative_adapter.py`.

### Связаны ли правила и адаптер повествования — нет
Два независимых источника текста в разных слоях и на разных языках:
- `insights-rules.js` — фронт, показывается только в панели выводов; вызывающие: `InsightsPanel.svelte`, `ValidateStepV13.svelte`. В сборку отчёта не попадает никогда (`grep insights-rules` по `sidecar/` — ноль).
- `engines/narrative_adapter.py` — движок, отображает данные пайплайна в структуру для PPTX/HTML: `_merge_channels` (:160), `derive_verdict` (:378 → Cut/Reduce/Watch/Hold/Scale), `derive_action_headline` (:448), `_derive_narrative_facts` (:604), `_map_pipeline_to_builder_data` (:865). Докстринг `:5-8`: «both PPTX and HTML exports consume the same business-logic … Zero logic duplication between output formats» — единство между ФОРМАТАМИ отчёта, не с правилами фронта.

### Чего не хватает
- Связной цепочки «вывод → почему → что сделать → чего опасаться»: сейчас есть «вывод» (`text`) и «совет» (`tip`), причина и риск отдельными полями не выделены (`grep "why:|risk:"` по insights-rules.js — ноль).
- Единого источника формулировок между панелью и отчётом — сейчас правила и адаптер могут расходиться по построению.
- Хоть какого-то видимого блока на месте скрытого советника в локальной редакции.

### Мёртвый код
Нет. Но отмечу рядом: `sidecar/econometrica/aurora_pptx/layouts.py` целиком состоит из заглушек `raise NotImplementedError("… - M3 Session 3")` (строки 121, 127, 133, 139, 145, 151, 157) и не импортируется ниоткуда, кроме упоминания в докстринге `aurora_pptx/__init__.py:25`. К линии 2 прямо не относится, но это мёртвый модуль.

---

## 7. Слоистая подача отчёта по адресату — **НЕ НАЧАТО**

### Что есть
- Один состав отчёта на всех. PPTX — 13 слайдов фиксированной последовательности (`aurora_pptx/builder.py`: SLIDE 01 COVER … 02 AT A GLANCE … 09 EXECUTIVE SUMMARY (SCQAR) … 10 METHODOLOGY + LIMITATIONS … 11 SOURCES + MQS … 13 COLOPHON). HTML — 17 разделов реестра `aurora_html/sections.py:2495 SECTION_RENDERERS` (cover, findings, key, recommend, summary, divider, mroas, share, table, timeline, trust, forecast, retro, method, sources, glossary, closing). XLSX — 10+ листов (`report.rs`: «Обзор», «Executive Summary», «Спецификация», «Декомпозиция», «ROI каналов», «Spend vs Effect», «Динамика», «Оптимизация», «Прогноз», «Сценарии»).
- Разделы под разные глубины де-факто существуют: «одна страница руководству» ≈ `render_executive_summary` / SLIDE 09 SCQAR, «сверка финансам» ≈ листы XLSX, «детали каналам» ≈ `render_action_table` / SLIDE 07.

### Чего не хватает
Выбора адресата или уровня детализации нет нигде. `grep -i "audience|адресат|report_level|detail_level|one_pager"` по `sidecar/`, `src/`, `src-tauri/` — ни одного совпадения. Пользователь выбирает только ФОРМАТ, и каждый формат собирается полностью: `ReportStep.svelte:152-161`:
```js
  /** v1.0.16: unified «Создать отчёт» - selector chooses one format per click,
   *  prevents simultaneous generation of all formats (token/CPU economy).
   *  @type {'pptx' | 'xlsx' | 'html'} */
  let selectedFormat = $state('pptx');
```
Условность есть только по НАЛИЧИЮ данных (раздел не рендерится, если данных нет — `sections.py:2311 if not blocks: return ""`), а не по адресату.

### Мёртвый код
Не по этому пункту (см. `layouts.py` в п.6).

---

## 8. Обещания из сноски в раздел — **ЧАСТИЧНО** (в PPTX — сноска, в HTML — уже свой раздел)

### Где именно печатаются в колоде
`aurora_pptx/builder.py:3466-3487`, внутри метода `s11_sources` (`# SLIDE 11 - SOURCES + MQS`, объявлен на `:3158`), в правой колонке, ДО списка источников:
```python
        # E4 (2026-07-03): сбывшиеся рекомендации — петля доверия в отчёте.
        if self.promises_summary:
            _ps = self.promises_summary
            self._text(
                slide, right_x, _hy, right_w, 0.25,
                (f"Проверка прошлых рекомендаций: сбылось {_ps.get('kept', 0)}, "
                 f"не сбылось {_ps.get('missed', 0)}."),
                font=self.sans, size=10, bold=True, color=self.deep_100,
            )
```
и примеры ниже — `size=9.5` (`:3481`). Для сравнения, типовые кегли колоды: 32 (крупный заголовок, `:1265`), 28 (`:1291`), 24 (`:1210`), 22 (`_big_number`, `:805`), 18 (`_pull_quote`, `:821`). Собственного слайда или раздела у обещаний в PPTX нет — в списке `# SLIDE 01…13` его не существует. Источник данных — `builder.py:330-331`, причём только для живого расчёта:
```python
        self.promises_summary = (
            self.data.get("promises_summary") if self.is_live else None
```

### А вот в HTML-отчёте раздел уже есть
`aurora_html/sections.py:2190 render_trust_loop` — секция «ДОВЕРИЕ К МОДЕЛИ» с заголовком-действием «Петля доверия: модель против факта» (`:2312`), внутри четыре блока: проверка на истории (E1), что изменилось с прошлого квартала (E3), калибровка экспериментами (E2) и обещания (E4, `:2292-2307`) — свой `<h3 class="trust-h">Проверка прошлых рекомендаций</h3>` и крупная строка `trust-hero` «Сбылось N · не сбылось M». Зарегистрирована в реестре разделов (`:2506 ('trust', render_trust_loop)`).

### Чего не хватает
Поднять обещания в PPTX до собственного слайда/раздела наравне с HTML — сейчас паритета форматов нет, хотя оба берут одни и те же данные `promises_summary` из `narrative_adapter.py:1313`.

### Мёртвый код
Нет: `promises_summary` формируется в `narrative_adapter.py:1309-1313` и потребляется обоими сборщиками.

---

## 9. Панель здоровья продукта — **НЕ НАЧАТО**

### Что есть из сырья
- Время: `src-tauri/src/commands/project.rs:19-20` `pub created_at: String, pub updated_at: String` в `ProjectInfo` (сохраняется в `project.json`), перечисление — `project.rs:244 project_list()`, сортировка по `updated_at` (`:256`).
- Дошёл ли проект до отчёта: по наличию файлов в каталоге выгрузок (`report.rs` пишет в `exports_dir(&project_id)`, имя вида `Aurora_Econometrica_<slug>_Model_<дата>_v<NN>.xlsx`).
- Отказ модели: флаг `model_reliability.refused` (SSOT — `sidecar/econometrica/utils/diagnostics.py::RELIABILITY_STATEMENT_REFUSED`, зеркало на фронте `src/lib/mqs-tiers.js:138`, предикат `:148 verdictRefuses`), лежит в `optimization.json` каждого проекта.
- Сбывшиеся обещания: `results/promises.json` со статусами `kept`/`missed`/`pending`/`inconclusive` (`PromisesCard.svelte:26-31`), сводка — `check_promises` (`engines/promises.py:149`).

То есть три из четырёх (доля дошедших до отчёта, доля отказов, доля сбывшихся обещаний) действительно собираются по файлам проектов без новых счётчиков; четвёртая — «время от файла до первого решения» — по `created_at`/`updated_at` даёт лишь грубую оценку, момента «первого решения» отдельно нет.

### Чего не хватает
Самой панели и любого агрегатора. `grep -i "health_dashboard|панель здоровья|time_to_first|доля отказов|refusal_rate|телеметри|product_health"` по всем `*.py`, `*.svelte`, `*.rs` дерева — **ноль совпадений**. Ни экрана, ни команды, ни скрипта в `tools/`.

### Мёртвый код
Нет — кода этой возможности не существует вовсе.

---

# Сводная таблица

| # | Возможность | Вердикт | Что готово | Чего не хватает |
|---|---|---|---|---|
| 1 | Профит-фронтир «сколько тратить» | **НЕ НАЧАТО** | `optimize_inverse` (цель→бюджет) и `optimal_split_ci` (HDI на доли) живые до интерфейса; KPI «прибыль» и маржа на единицу как ВХОД | кривой «бюджет→прибыль», максимума при mROI=1/маржа, интервала на положение максимума, `aggregate_sales` (placeholder в bounds.py) |
| 2 | Досье решения | **ЧАСТИЧНО** | все 4 части живые порознь: обещания, проверка на истории, сравнение поколений, сертификат с JCS-хешем | единого объекта нет (`grep досье` = 0); в подписанный payload входят только разбивка, ROI каналов, спецификация и хеш поставки; авто-дописывания исхода и офлайн-проверки нет |
| 3 | Реестр допущений | **НЕ НАЧАТО** | правая колонка есть: торнадо `compute_sensitivity_tornado` считается при обучении + `SensitivityTornado.svelte`; `HonestDisclosure` с `assumptions` — но только в каузальном модуле | таблицы «допущение → почему → что если неверно → чувствительность» для MMM-пути нет ни в отчёте, ни в интерфейсе |
| 4 | Знание бренда и ESOV в интерфейс | **ЧАСТИЧНО** | движок 4/4 слоя: adstock Weibull + AR(1), честный интервал AR(1), ESOV Binet & Field (`_esov_module`), S-кривая знание→продажи; доставка движок→HTTP→Rust | интерфейса ноль: `econ_awareness_*` не вызываются из `src/`; KPI «знание» не выбирается (нет в KPISelector и в `available_kpi_types`) |
| 5 | Советник со всей диагностикой | **НЕ НАЧАТО** | контекст собирает `buildTier2Context`: валидация, модель, декомпозиция, оптимизация, база окупаемости, справка, RAG-канон | backtest / promises / model_compare / split_ci в контексте отсутствуют; надёжность — только `opt.model_reliability` |
| 6 | Локальный советник для 152-ФЗ | **НЕ НАЧАТО** | Tier-1 правила (2490 строк) в панели выводов + «Петля доверия» и повествование в локально собираемом отчёте | блок советника просто скрыт `canAsk`, замены нет; правила (JS, панель) и адаптер (Python, отчёт) — независимые источники; полей «почему»/«чего опасаться» нет |
| 7 | Слоистая подача по адресату | **НЕ НАЧАТО** | 13 слайдов / 17 разделов HTML / 10+ листов XLSX, включая Executive Summary и таблицу каналов | выбора адресата/уровня нет (`grep audience|адресат|report_level` = 0); выбирается только формат |
| 8 | Обещания из сноски в раздел | **ЧАСТИЧНО** | в HTML уже свой раздел «Петля доверия» (`render_trust_loop`, h3 + hero) | в PPTX — правая колонка слайда 11 «SOURCES + MQS», кегль 10 (заголовок) и 9.5 (примеры) при типовых 18–32; своего слайда нет |
| 9 | Панель здоровья продукта | **НЕ НАЧАТО** | сырьё лежит: `created_at`/`updated_at` в `project.json`, файлы в exports, `model_reliability.refused`, `promises.json` со статусами | ни панели, ни агрегатора, ни скрипта — ноль совпадений по всем ключевым словам |

## Мёртвый код, найденный по ходу
1. **v2.0-ветка сертификата методологии** — `methodology_cert.py:345 _extract_v20_fields` и ветка `:482-498`: недостижима (`save_v20_diagnostics` без вызывающих) и сломана по контракту (`analysisMode` против `analysis_mode` у проверяющей стороны). Признано в самом коде, оставлено намеренно.
2. **Rust-команды знания бренда** — `econometrica.rs:378 econ_awareness_forecast`, `:384 econ_awareness_sales`: зарегистрированы в `lib.rs:3950-3951`, ноль вызовов из `src/`.
3. **Модуль `aurora_pptx/layouts.py`** — все семь функций рендера бросают `NotImplementedError("… - M3 Session 3")`, модуль не импортируется нигде.

**Общий итог: работа по линии 2 не начиналась.** Пять пунктов из девяти — НЕ НАЧАТО, четыре — ЧАСТИЧНО, и в каждом «частично» готово ровно то основание, которое план и называл основанием (движок написан, интерфейса нет; части живут, связи нет). Ни одного пункта СДЕЛАНО. За две недели после 2026-08-02 линия 2 не двигалась; более того, в коде от 2026-08-03 стоит явная запись, что профит-фронтир отложен в P1.

**ПРОВЕРКА ЗАВЕРШЕНА — 16 августа 2026, 02:22.**

