# Маячок — разведка H-4/H-5 (2026-08-17)

## Задача (своими словами)
Внешний аудит нашёл две находки в Econometrica: (H-4) критерий совпадения воспроизводимости
(`repro_tolerance.py`) считается движком, но нигде не показывается клиенту в отчёте/паспорте;
(H-5) паспорт обещает выгрузку полных параметров модели по явному действию пользователя, а самой
кнопки/команды в интерфейсе нет. Задача — ТОЛЬКО разведка: собрать точную карту (файлы, строки,
цитаты, образцы соседних команд/кнопок), чтобы правку можно было сделать быстро, без правок кода.

## План
1. Найти и разобрать `utils/repro_tolerance.py` — сигнатуры, ветви допуска.
2. Проследить вызовы наружу: server.py, генератор паспорта, генераторы отчётов (html/pptx).
3. Найти все форматы выгрузки клиенту (html/pptx) — куда встраивать блок критерия.
4. Найти текст обещания раскрытия параметров в паспорте — файл/строка/цитата.
5. Проверить наличие готовой функции/эндпоинта полного экспорта параметров (server.py, engines/json_export.py).
6. Описать разрыв по слоям: движок / Rust-команда (src-tauri/src/commands/) / фронт (страница+кнопка).

## Ход работы
- 03:51:35 — старт, создан маячок, план зафиксирован.
- 03:54:31 — разведка завершена, отчёт ниже.

---

## Реализация H-4

### Задача своими словами
По карте разведки выше довести критерий совпадения (`utils/repro_tolerance.py` через готовые витрины
`engines/methodology_cert.py::строки_критерия_совпадения`/`пояснение_критерия_совпадения`) до клиента:
третий подраздел в HTML-сертификате (`aurora_html/sections.py`) и строка в PPTX-диагностике
(`aurora_pptx/builder.py`). Проверить XLSX. Гарантировать единый источник сертификата у HTML и PPTX.
Добавить тесты «красный до / зелёный после», включая тест на совпадение чисел между HTML и PPTX.
`engines/methodology_cert.py` не трогать — только вызывать. Границы: без сборки sidecar, без git.

### План
1. Прочитать точный код вокруг точек вставки (sections.py:1932-1975, builder.py:140-175, 3080-3110).
2. Проверить XLSX-генератор — есть ли блок методологии.
3. Проверить единый источник сертификата (откуда `ctx["certificate"]` в HTML и `self.data["certificate"]` в PPTX).
4. Написать тесты (красные) под текущее поведение.
5. Внести правку HTML.
6. Внести правку PPTX.
7. Прогнать тесты (зелёные), точечно.
8. Собрать реальный HTML и PPTX на живой модели, прочитать текст критерия из готового файла.
9. Отчёт.

### Ход
- 04:37:07 — старт реализации, раздел маячка создан.
- 04:38 — сверила единый источник сертификата: `aurora_html/builder.py:590` (`ctx["certificate"] = self.raw_decompose.get("methodology_certificate")`)
  и `engines/narrative_adapter.py:1336-1338` (`data['certificate'] = (decompose_data or {}).get('methodology_certificate')`) —
  ОБА читают один и тот же ключ `decompose_data['methodology_certificate']`, единственный построитель которого —
  `engines/decomposer.py:1517` (`_build_methodology_certificate`, единственная точка вызова `generate_methodology_certificate`
  в продукте, decomposer.py:591-593). Второго источника нет, разводить не пришлось.
- 04:39 — проверила XLSX: экспорт XLSX идёт полностью на Rust-стороне (`src-tauri/src/commands/report.rs`,
  команда `econ_export_xlsx`, найдена в lib.rs/report.rs), сертификат методологии живёт только в Python
  (`methodology_cert.py`/`decomposer.py`) и в Rust-код не попадает. Грепнула `report.rs` на
  `certificate|методолог|reproducib|repro_toleran` — 0 совпадений. Вывод: в XLSX нет ни листа, ни блока
  методологии вообще (не только критерия совпадения) — довести туда H-4 нечем, ничего не выдумываю,
  оставляю за границей по правилу владельца.
- 04:39:52 — правки внесены: `aurora_html/sections.py::_render_certificate_block()` — третий вызов
  `_подраздел_сертификата('Критерий совпадения', пояснение_критерия_совпадения(cert), строки_критерия_совпадения(cert, подробно=True), [])`
  после блока «Перенос эффекта по каналам» (было до строки 1958, теперь между ним и `оговорки.append(...)`);
  `aurora_pptx/builder.py::строки_сертификата()` — `строки.extend(строки_критерия_совпадения(cert, подробно=False))`
  после `краткие_строки_данных_и_переноса` (было до строки 172).
  Подробность в HTML — `True` (по аналогии с двумя соседними подразделами, это форма ОТЧЁТА, не слайда);
  в PPTX — `False` (форма слайда, список уже ужимается под восемь строк автосжатием шага builder.py:3095-3097).
  `engines/methodology_cert.py` не трогала — только вызывала уже готовые `строки_критерия_совпадения`/`пояснение_критерия_совпадения`.
- 04:41 — написан новый тестовый файл `tests/test_h4_repro_criterion_disclosure.py` (3 теста: критерий в HTML,
  критерий на слайде PPTX, HTML и PPTX согласны друг с другом по ветви и числу на одном сертификате). Тесты
  собирают НАСТОЯЩИЙ HTML (`build_html`) и НАСТОЯЩИЙ PPTX (`AuroraPPTXBuilder(...).build()`, сохранённый и
  распакованный как zip) и читают текст из готового файла, а не из возвращаемого значения функции.
- 04:44 — прогон тестов ДО правки: временно откатила оба изменения (sections.py, builder.py), прогнала
  `pytest tests/test_h4_repro_criterion_disclosure.py -q` → **3 failed** (каждый по правильной причине —
  `'Критерий совпадения' in html` / `'Совпадение расчётов' in текст` / число не найдено рядом с веткой).
  Правки вернула на место, прогнала снова → **3 passed in 10.17s**. Красный до / зелёный после подтверждён.
- 04:46 — регрессия на соседних тестовых файлах: `pytest tests/test_certificate_in_reports.py
  tests/test_deliverable_thinness_disclosure.py -q` → 44 passed; `pytest tests/test_cert_data_and_adstock.py
  tests/test_methodology_cert.py -q` → 50 passed. Ни один существующий тест не сломан.
- 04:52 — проверка переполнения слайда PPTX (требование владельца): собрала РЕАЛЬНЫЙ сертификат с
  МАКСИМАЛЬНЫМ набором строк (паспорт recorded + отпечаток данных recorded (content+file) + протокол adstock
  recorded по двум каналам с разными типами переноса → «по каналам различается»), прогнала через
  `AuroraPPTXBuilder(...).build()` и прочитала РЕАЛЬНЫЕ координаты текстовых блоков слайда «Методология»
  (python-pptx, EMU→дюймы). Итог: 9 строк диагностики (4 базовые метрики + 5 из `строки_сертификата`, включая
  новую строку критерия) — это и есть истинный «худший случай» (было 8 до моей правки). Нижний край последней
  строки «Совпадение расчётов» = **6.850 in**, ровно на границе `ВЕРХ_СНОСКИ=6.85`; подвал-сноска
  («Приоры: слабоинформативные…») начинается на **6.87 in** — зазор 0,02 дюйма (~1,4 pt), наложения нет.
  Автосжатие шага (builder.py:3095-3097) само подобрало шаг под 9 строк, как и было рассчитано владельцем
  для восьми — я не трогала эту логику, только убедилась, что она выдерживает +1 строку.

---

# ОТЧЁТ

## H-4. Критерий совпадения не доходит до клиента

### 1. `utils/repro_tolerance.py` — что считается

Точка входа сверки двух прогонов — `compare_runs(model_a, model_b, ...)` (repro_tolerance.py:514).
Три режима допуска (repro_tolerance.py:135-137, 217-242):
- `MODE_EXACT` ('exact') — повторный запуск той же программой, допуск 0 (недостижим для стороннего, см. `SELF_RERUN_NOTE`, repro_tolerance.py:171-177);
- `MODE_STRICT` ('other_seed_full') — другое зерно, полный расчёт (≥ `FULL_RUN_DRAWS`=8000 итоговых выборок, repro_tolerance.py:197): ROI/beta/decay/alpha/gamma ≤5,0 %, contribution_pct ≤1,5 п.п.;
- `MODE_WIDE` ('reduced_or_other_env') — сокращённый расчёт/другая среда: те же величины ≤10,0 % / ≤3,0 п.п.

Ветвь, применимая к КОНКРЕТНОМУ расчёту, вычисляется САМИМ паспортом — `applicable_mode(passport)` (repro_tolerance.py:359-390), по числу итоговых выборок (`total_draws`, 347-356), а не выбирается читателем — это чинит найденный внешним аудитом баг «сторонний брал строгую ветвь и получал ложное несовпадение» (С-2, описано в шапке файла, строки 84-98).

Готовые клиентские витрины УЖЕ ЕСТЬ в этом же модуле:
- `criterion_for_certificate(passport=None)` (697-745) — структура критерия целиком, с полем `applicable` (применимая ветвь);
- `criterion_lines(criterion=None)` (748-793) — список пар «подпись – значение» на русском, готов к печати;
- `criterion_note()` (796-807) — одна фраза-пояснение.

### 2. Путь наружу — обрыв ПОЗЖЕ, чем ожидалось

Есть промежуточный слой — `engines/methodology_cert.py`, который уже подключает `repro_tolerance` к сертификату:
- `_extract_repro_tolerance(reproducibility)` (methodology_cert.py:1082-1122) — берёт паспорт из `reproducibility`, вызывает `criterion_for_certificate` и кладёт результат в `cert['repro_tolerance']`;
- `строки_критерия_совпадения(cert, *, подробно)` (1125-1168) — клиентская витрина (True → полная форма отчёта, False → одна строка для слайда);
- `пояснение_критерия_совпадения(cert)` (1171-1186) — одна фраза.

`generate_methodology_certificate()` (methodology_cert.py:506-591) уже кладёт `repro_tolerance` в возвращаемый сертификат (строки 546, 565, 590) — то есть **данные едут в `cert` всегда**, когда сертификат вообще строится.

**Единственная точка вызова сертификата в продукте** (согласно комментарию decomposer.py:591-593) — `engines/decomposer.py::_build_methodology_certificate()` (584-630), вызывается из `decompose()` на decomposer.py:1517 и кладётся в `result['methodology_certificate']`. Оттуда он попадает в `decompose_data`, который фронт пересылает на `/export/html` и `/export/pptx` как есть.

**Обрыв №1 (HTML)** — `aurora_html/sections.py::_render_certificate_block(ctx)` (1833-1975). Строит подразделы «Исходные данные» и «Перенос эффекта по каналам» через `_подраздел_сертификата()` (вызовы на 1948-1958), берёт `оговорка_о_выгрузке_параметров()` (1962, это H-5), но **не вызывает** `строки_критерия_совпадения`/`пояснение_критерия_совпадения` вообще — грep по файлу даёт 0 совпадений на `repro_tolerance`/`строки_критерия_совпадения`.

**Обрыв №2 (PPTX)** — `aurora_pptx/builder.py`. Грep по всему файлу на `repro_tolerance`/`строки_критерия_совпадения`/`оговорка_о_выгрузке_параметров` — 0 совпадений. `строки_сертификата(cert)` (144-173) собирает диагностический список слайда «Методология» (отпечаток, зерно, `краткие_строки_данных_и_переноса` — 171-172), но критерий совпадения туда не попадает.

### 3. Форматы у клиента — куда встраивать

- **HTML-отчёт** — генератор `_render_certificate_block(ctx)`, aurora_html/sections.py:1833. Место вставки — сразу после блока «Перенос эффекта по каналам» (после строки 1958), симметричным третьим вызовом:
  ```python
  from engines.methodology_cert import строки_критерия_совпадения, пояснение_критерия_совпадения
  ...
  ) + _подраздел_сертификата(
      'Критерий совпадения',
      пояснение_критерия_совпадения(cert),
      строки_критерия_совпадения(cert, подробно=True),
      [],
  ))
  ```
  (паттерн `_подраздел_сертификата` — sections.py:1802-1830, «пустой подраздел не печатается»).

- **PPTX-презентация** — слайд «Методология», список `diag` собирается в методе строк 3049-3110, наполняется на builder.py:3088 (`diag.extend(строки_сертификата(...))`). Естественнее не трогать вызывающий код на 3088, а расширить саму функцию `строки_сертификата()` (builder.py:144-173) — добавить после строки 172 (`.extend(краткие_строки_данных_и_переноса(cert))`):
  ```python
  from engines.methodology_cert import строки_критерия_совпадения
  строки.extend(строки_критерия_совпадения(cert, подробно=False))
  ```
  Список уже умеет ужиматься под 8 строк (шаг автосжимается, builder.py:3095-3097 `ВЕРХ_СНОСКИ`/`шаг`), поэтому +1 строка безопасна количественно, но **обязательно `подробно=False`** — полная форма даёт 4+ строки и собьёт расчёт шага.

- **XLSX** (`econ_export_xlsx`) — НЕ проверяла: сертификат методологии (checks/adstock_protocol/data_fingerprint) в принципе HTML/PPTX-специфичен по коду, который я видела; есть ли в XLSX параллельный «Методология»-лист вообще — вне зоны этой разведки, стоит проверить отдельно перед реализацией, если XLSX тоже должен получить критерий.

### Риски H-4
- HTML и PPTX **обязаны** читать критерий из ОДНОГО и того же `certificate`-объекта (единственный построитель — decomposer.py:599/622), иначе отчёт и презентация разойдутся числами — против чего сам файл написан («один источник для отчёта и презентации», methodology_cert.py:815-820). Проверить перед правкой, что оба рендера действительно получают один и тот же `decompose_data['methodology_certificate']`, а не два независимых вызова.
- Блок сертификата в HTML печатается только при `статус in ('issued', 'not_attested')` (sections.py:1936) — при `unavailable` критерий совпадения не покажется вовсе, хотя логически он про сверку ДВУХ прогонов, а не про заверение ОДНОГО. Решение, показывать ли критерий отдельно от общего гейта сертификата — за владельцем.
- `criterion_lines`/`строки_критерия_совпадения` уже разбирают все три статуса (`declared`/`deterministic`/`absent`, methodology_cert.py:1137-1145) — переиспользовать как есть, не переписывать логику веток.

---

## H-5. Обещанной выгрузки параметров нет в интерфейсе

### 4. Точный текст обещания

`engines/methodology_cert.py:1068-1077`, функция `оговорка_о_выгрузке_параметров()`:

> «Полный набор параметров модели по каждому каналу – коэффициенты, разбросы, правдоподобные диапазоны, параметры переноса и насыщения, нормировка и приоры – в отчёт не входит и выгружается отдельно, по вашему запросу.»

Используется сейчас ТОЛЬКО в HTML-отчёте — `aurora_html/sections.py:1962`, внутри `_render_certificate_block`, добавляется в список `оговорки` при статусе `issued`/`not_attested` (условие sections.py:1936). В PPTX эта фраза не печатается вовсе (0 совпадений по builder.py).

### 5. Готовая функция движка — есть, не подключена к HTTP

`engines/json_export.py::export_model_params_json(model_data, pretty=True, diagnostics=None) -> str` (json_export.py:1081-1244) — полная выгрузка параметров модели, схема `aurora-econometrica-model-params` v3.0 (см. `payload['schema']`, json_export.py:1124-1161): версия модели, KPI, каналы, паспорт воспроизводимости, протокол adstock — на русском, с честными пропусками (`absent_fields`, правило `honesty_rule` строки 1133-1139: «значения по умолчанию не подставляются»).
File-обёртка — `export_model_params_to_file(model_data, output_path, pretty=True, diagnostics=None) -> Path` (json_export.py:2224-2244).

Вход — тот же словарь `model_data`, что уже летает во все существующие export-эндпоинты как `req.model_data`.

**server.py грепнула целиком — ни одного эндпоинта, вызывающего `json_export`.** Есть `/export/pptx` (server.py:2187) и `/export/html` (server.py:2262), эндпоинта `/export/params` нет вообще. Тесты (`test_json_export_params.py`, `test_json_export_params_live.py`, `test_json_export_spec_completeness.py`) вызывают функцию напрямую, без HTTP — то есть серверный слой никогда не строился и не тестировался.

Источник `diagnostics` для этой функции — по аналогии с сертификатом методологии, единственный существующий читатель диагностики с диска: `engines/decomposer.py::_build_methodology_certificate()`, строка 613:
```python
файл_диагностики = model_path.parent.parent / 'results' / 'model-diagnostics.json'
```
Для нового эндпоинта эквивалент проще (project_dir уже резолвится сервером): `project_path / 'results' / 'model-diagnostics.json'`.

### 6. Разрыв по слоям

**(а) Движок** — готов полностью, нужен только HTTP-эндпоинт. Шаблон — `/export/html` (server.py:2262-2325) и его модель запроса `HtmlExportRequest` (server.py:668-677). Новый эндпоинт:
```python
class ParamsExportRequest(BaseModel):
    project_id: str
    model_data: dict
    project_dir: str | None = None
    pretty: bool = True

@app.post('/export/params')
def export_params(req: ParamsExportRequest):
    try:
        from engines.json_export import export_model_params_to_file
        project_path = _resolve_project_dir(req.project_dir, req.project_id)  # server.py:2143
        exports_dir = project_path / 'exports'
        exports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = exports_dir / f'model_params_{ts}.json'
        diagnostics = {}
        файл_диагностики = project_path / 'results' / 'model-diagnostics.json'
        if файл_диагностики.exists():
            diagnostics = json.loads(файл_диагностики.read_text(encoding='utf-8'))
        export_model_params_to_file(req.model_data, output_path, pretty=req.pretty, diagnostics=diagnostics)
        return JSONResponse(content={'status': 'ok', 'path': str(output_path)})
    except Exception as e:
        logger.exception('Params export FAILED')
        return JSONResponse(status_code=500, content={'status': 'error', 'message': _friendly_error(e), 'type': type(e).__name__})
```
Использовать `_resolve_project_dir` (server.py:2143) — тот же резолвер, что у остальных экспортов, не писать свой.

**(б) Rust-команда** — `src-tauri/src/commands/econometrica.rs`. Образец-сосед — `econ_export_html` (строки 506-527):
```rust
#[tauri::command]
pub async fn econ_export_html(
    project_id: String,
    model_data: Value,
    decompose_data: Value,
    optimize_data: Value,
    project_name: Option<String>,
) -> Result<Value, String> {
    info!("econ_export_html: project={project_id}");
    let project_dir = crate::commands::project::project_dir(&project_id)
        .map(|p| p.to_string_lossy().to_string())
        .ok();
    let body = serde_json::json!({
        "project_id": project_id,
        "project_dir": project_dir,
        "model_data": model_data,
        "decompose_data": decompose_data,
        "optimize_data": optimize_data,
        "project_name": project_name.unwrap_or_else(|| "Marketing Mix Model".to_string()),
    });
    post_json("/export/html", &body, quick_client()).await
}
```
Новая команда `econ_export_params(project_id: String, model_data: Value) -> Result<Value, String>` — та же структура, POST на `/export/params`, без decompose/optimize (параметры берутся только из model_data). Регистрация — добавить в список `generate_handler!` в `src-tauri/src/lib.rs`, рядом со строками econ_export_pptx/econ_export_html (lib.rs:3956-3957). Отдельных записей в capabilities/*.json для этих двух соседних команд я не нашла (грep по всему src-tauri вне lib.rs/econometrica.rs — 0 совпадений) — вероятно, доп. разрешение не требуется, но перед сборкой стоит перепроверить через `aurora-fix` (правило CLAUDE.md продукта — сборка только через этот чеклист).

**(в) Фронт** — `src/lib/components/pipeline/ReportStep.svelte`. Образцы рядом:
- функции-экспортёры `exportHtml`/`exportPptx` (строки 727-782) и `openPptxFile` (799-806, `openPath` из `@tauri-apps/plugin-opener`, импорт на строке 12);
- кнопка-сосед — блок `more-exports` (строки 954-956):
  ```svelte
  <div class="more-exports">
    <button class="btn-folder" onclick={openFolder}>📁 Открыть папку</button>
  </div>
  ```

Новая функция (по образцу `exportHtml`):
```js
async function exportParams() {
  const pid = get(activeProjectId);
  if (!pid || !hasData) return;
  try {
    const result = /** @type {any} */ (await invoke('econ_export_params', {
      projectId: pid,
      modelData: get(modelData),
    }));
    if (result.status === 'ok') {
      paramsPath = result.path ?? null;
    } else {
      handleError(result.message ?? 'Ошибка выгрузки параметров');
    }
  } catch (/** @type {any} */ e) {
    handleError(String(e));
  }
}
```

Место кнопки — два варианта, решение за владельцем:
- **Вариант А** (минимальный диф): вторая кнопка в `more-exports` рядом с «Открыть папку» (строка 955). Плюс — копирует принятый паттерн один-в-один. Минус — весь блок скрыт до первого сгенерированного отчёта (`{#if stepState === 'done'}`, строка 925), а параметры логически не требуют предварительного экспорта отчёта — `model_data` уже есть, как только `hasData` истинно.
- **Вариант Б** (точнее по смыслу обещания «по явному действию»): отдельная кнопка в блоке `export-unified` (971-1011), видна при `hasData` без ожидания генерации отчёта.
Моя рекомендация — вариант Б (действие не должно быть заперто позади другого экспорта), но решение по UX — владельца.

### Риски H-5
- `diagnostics` для нового эндпоинта — обязательно читать из `results/model-diagnostics.json` по `project_dir` (как делает `_build_methodology_certificate`, decomposer.py:613), иначе документ потеряет разделы про MCMC/checks, которые есть в остальных выгрузках, и станет ХУЖЕ методологического сертификата по честности.
- `оговорка_о_выгрузке_параметров()` в HTML привязана к статусу сертификата (`issued`/`not_attested`, sections.py:1936) — если кнопка появится в интерфейсе, а сертификат при этом `unavailable`, фраза-обещание в отчёте не покажется вовсе, и это создаст новое несовпадение (кнопка есть, а текст о ней в отчёте иногда нет). Стоит решить, синхронизировать ли видимость кнопки со статусом сертификата, или это не связанные вещи (я считаю — не связанные: кнопка про модель, а не про заверение, но называю риск явно).
- Файл на JS с JSDoc (не TypeScript) — `/** @type {any} */` паттерн повторить как у соседних функций (правило проекта, CLAUDE.md продукта, №7).

---

## Общий риск, не привязанный к одной находке
`оговорка_о_выгрузке_параметров()` и (после правки) критерий совпадения в PPTX ДОЛЖНЫ читаться из ОДНОГО и того же `certificate`, который строит decomposer.py:599/622 — единственная точка сборки в продукте. Если pptx/html/новый эндпоинт параметров начнут порознь запрашивать/собирать сертификат — реинкарнация именно того класса дефекта, который чинил файл methodology_cert.py («один источник для отчёта и презентации»).
