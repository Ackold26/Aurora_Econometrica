# PULSE — H-5: выгрузка параметров модели

## Задача (своими словами)
Паспорт модели (сертификат методологии) обещает клиенту отдельную выгрузку полного набора параметров по запросу, но самого действия в продукте нет — движок (`json_export.py`) готов и протестирован, но не подключён к HTTP-обработчику, Rust-команде и кнопке во фронте. Нужно связать все три слоя: FastAPI-обработчик `POST /export/params` → Rust-команда `econ_export_params` → кнопка «Выгрузить параметры модели» в `ReportStep.svelte` (блок `export-unified`).

## План по слоям
1. Движок (`sidecar/econometrica/server.py`): обработчик `POST /export/params` по образцу `/export/pptx` и `/export/html`, модель обучается через `load_model_with_compat`, диагностика — тем же путём что и `decomposer.py:613`.
2. Rust (`src-tauri/src/commands/econometrica.rs` + регистрация в `lib.rs`): команда `econ_export_params` по образцу `econ_export_html`.
3. Фронт (`ReportStep.svelte`): функция `exportParams()` по образцу `exportHtml`/`exportPptx`, кнопка в блоке `export-unified`, клиентский текст без англицизмов и эмодзи.
4. Проверки: краснеть до / зеленеть после — (1) непустые параметры на живой модели, (2) `_loader_injected_defaults` помечены как подставленные, (3) внятный отказ на несуществующем проекте. `npm run check` = 0 ошибок.

## Отметки времени
- Старт: 2026-08-17 04:39:44
- Слой 1 (движок) готов, красный→зелёный на TestClient: 2026-08-17 04:50
- Слой 2 (Rust) готов, `cargo check` чисто: 2026-08-17 04:53
- Слой 3 (фронт) готов, `npm run check` 0 ошибок: 2026-08-17 04:58
- Живой прогон целиком (uvicorn на 127.0.0.1:7998, реальный POST): 2026-08-17 05:00-05:02
- Финиш, точечный прогон 22/22 зелёных: 2026-08-17 05:04:30

## ИТОГОВЫЙ ОТЧЁТ

### (а) Движок — sidecar/econometrica/server.py

Добавлен `POST /export/params` (класс `ParamsExportRequest` + функция `export_params`,
вставлены перед секцией `# v1.3.0 endpoints`, после `export_html`, ~строка 2328-2408).

**Устройство:** запрос принимает `project_id`, необязательный `project_dir`, `pretty`.
🔴 Сознательно НЕ принимает `model_data` от фронта — в отличие от `/export/pptx` и
`/export/html`. Причина явно прописана в докстринге `ParamsExportRequest`: только
`load_model_with_compat(project_dir/models/latest.pkl)` заводит след подстановок
`_loader_injected_defaults` (Critical C-1 внешнего аудита 2026-08-16). Модель,
округлившая путь через JSON фронта, эту защиту обходит по построению — приняли бы
`model_data` "для порядка", как в брифе, и открыли бы дорогу тому самому регрессу,
от которого специально предостерегал бриф. Это единственное отступление от буквального
списка полей в задаче — оставил только то, что реально используется, чтобы у следующего
разработчика не было соблазна "по аналогии" передать `model_data` и тем самым тихо
вернуть дефект.

Диагностика читается `project_path / 'results' / 'model-diagnostics.json'` — тем же
путём, что и в `engines/decomposer.py:613` (там `model_path.parent.parent / 'results' /
'model-diagnostics.json'`, что при `model_path = project_path/models/latest.pkl`
даёт тот же `project_path/results/...`). Отсутствующая модель → 404 `MODEL_NOT_FOUND`
с человеческим текстом (тот же паттерн, что у `/optimize/corridor` и
`/compute/forecast-context`).

**Доказано:**
- Тест `tests/test_export_params_endpoint.py` (новый файл, 3 теста):
  1. `test_export_params_returns_real_file_with_nonnull_coefficients_and_marks_loader_defaults` —
     живая модель на диске → файл существует, `channels["ТВ"].beta == 0.42` с `origin.beta ==
     'recorded'`, а `kpi.type`/`channels["ТВ"].unit_kind` (оба — умолчания загрузчика,
     в файле модели их не было) выходят `null` с `origin == 'loader_default'` и названы в
     `absent_fields`.
  2. `test_export_params_records_written_field_as_written_not_defaulted` — контрольный
     прогон: то же поле, но реально ЗАПИСАННОЕ в модели, остаётся `'recorded'` (защита не
     стирает правду, где она есть).
  3. `test_export_params_on_missing_project_is_explicit_not_silent` — 404 +
     `error_code=MODEL_NOT_FOUND` + непустое сообщение.
- **Красный до / зелёный после:** временно переименовал путь на
  `/export/params__TEMP_DISABLED_FOR_RED_PROOF`, прогнал — все 3 теста упали на
  `404 Not Found` / `assert 404 == 200` (реальный красный, не «тест был всегда зелёным»).
  Вернул путь обратно — все 3 снова зелёные.
- **Живой прогон целиком (не только TestClient):** поднял `python server.py 7998` по-настоящему
  (uvicorn, полный старт PyMC/JAX — см. лог), собрал fixture-проект с моделью на диске через
  `save_model_safe`, дёрнул curl'ом:
  ```
  POST /export/params {"project_id":"h5-live","project_dir":".../h5_live_project"}
  → {"status":"ok","path":"...\\exports\\model_params_20260817_050002.json","size_kb":54.1}
  ```
  Перечитал файл С ДИСКА (`json.load`), фрагмент:
  ```json
  "channels": {"ТВ": {"beta": 0.42, "origin": {"beta": "recorded", ...}, "unit_kind": null,
                        "origin": {..., "unit_kind": "loader_default"}}},
  "kpi": {"type": null, "type_origin": "loader_default", ...},
  "absent_fields": [{"field": "kpi.type", "reason": "...загрузчик продукта подставил «sales»..."}]
  ```
  32 честно названных отсутствующих поля. Отдельно дёрнул на несуществующем проекте:
  `404 {"status":"error","error_code":"MODEL_NOT_FOUND","message":"Модель не найдена - обучите MMM перед выгрузкой параметров."}`.
  Sidecar остановлен штатно через `/shutdown`.
- Точечный финальный прогон: `pytest tests/test_export_params_endpoint.py
  tests/test_json_export_loader_defaults.py tests/test_export_decompose_gate.py
  tests/test_corridor_endpoint_sales_opt_in.py -q` → **22 passed**. Полный прогон
  НЕ запускал (по инструкции — ложные красные под параллельной нагрузкой).

### (б) Rust — src-tauri/src/commands/econometrica.rs + lib.rs

Добавлена команда `econ_export_params(project_id, pretty: Option<bool>)` (после
`econ_export_html`, перед секцией Sprint 3 Pharma Causal) — по образцу `econ_export_html`:
резолвит `project_dir` через `crate::commands::project::project_dir`, шлёт POST на
`/export/params` через `quick_client()`. **Модель телом не передаёт** — сознательно, тем же
резоном, что и в Python-слое (комментарий над функцией это объясняет явно).

Регистрация: `commands::econometrica::econ_export_params,` добавлена в `generate_handler!`
в `lib.rs` сразу после `econ_export_html` (было 3956-3957, теперь между ними одна новая
строка).

**Разрешения (проверено лично):** `src-tauri/capabilities/default.json` содержит только
плагинные ACL (`core:*`, `opener:*`, `dialog:*`, `notification:*`, `mcp-bridge:default`) —
grep по `econ_export|econ_chart|econ_data_preview` в этом файле не даёт ни одного совпадения.
Кастомные `#[tauri::command]`-функции, зарегистрированные через `generate_handler!`, у
econometrica НЕ участвуют в capabilities ACL продукта (это система для плагинов и
явно ограниченных app-команд) — ни у одной из ~30 соседних `econ_*`-команд отдельной записи
нет. Новая команда следует тому же правилу без исключений.

**Доказано:** `cargo check` (без `--message-format` фильтра лишнего) —
`Finished \`dev\` profile [unoptimized + debuginfo] target(s) in 49.33s`, ошибок 0.
(Строка про `{{cookiecutter.app_id}}` — не относящийся к делу кэш-пакет
`aurora-platform-core` из отдельного git-checkout, не часть этой сборки.)

### (в) Фронт — src/lib/components/pipeline/ReportStep.svelte

- Состояние: `paramsPath`, `paramsGenerating`, `paramsError` — **отдельно** от `stepState`
  (которым делятся xlsx/pptx/html). Причина: `stepState` в состоянии
  `'generating-report'/'generating-xlsx'` прячет ВСЮ карточку экспорта (см. шаблон,
  ветка `{:else if stepState === 'generating-report' || ...}`) — если бы кнопка параметров
  делила это состояние, клик по ней на секунду убирал бы весь выбор форматов с экрана.
  Отдельное состояние = кнопка не мешает остальному экспорту и не прячется сама.
- `exportParams()` — по образцу `exportHtml`/`exportPptx`, но зовёт `econ_export_params`
  только с `projectId` (без `modelData`/`decomposeData`/`optimizeData` — see выше про
  причину).
- Кнопка вставлена **внутрь `.export-unified`**, сразу после `.btn-export-unified`, ДО
  закрытия блока — то есть видна всегда при наличии данных, не только после первого
  экспорта отчёта (проверил: `.export-unified` рендерится при
  `stepState === 'idle' || 'error' || 'done'`, что истинно с самого начала — `stepState`
  стартует как `'idle'`). Текст кнопки: «Выгрузить параметры модели» / «Выгружаю…» /
  «Выгрузить заново» — без англицизмов, без эмодзи (только lucide-иконки `Check`/
  `TriangleAlert`, уже импортированные в файле, новых импортов не добавлял). Подсказка
  (`title`): «Полный список параметров модели в отдельном файле – для независимой
  проверки или переноса в другой инструмент» — без слов «JSON»/«экспорт».
- CSS: `.params-export`, `.btn-export-params` (outline-стиль, по образцу `.btn-folder`/
  `.btn-more` — вторичное действие, не перетягивает внимание с основной кнопки отчёта),
  `.btn-spinner-muted`, `.params-export-error`, `.params-export-path`.

**Доказано:** `npm run check` → `COMPLETED 4159 FILES 0 ERRORS 177 WARNINGS`. Прицельно
проверил warnings по `ReportStep.svelte` — все 13 предупреждений (`.export-buttons`,
`.btn-export`, `.btn-icon`, `.export-hint`, `.btn-more`, `.spinner-sm` и т.п.) относятся к
коду, который был ДО моих правок; ни одного нового unused-selector warning на моих классах
(`.params-export*`, `.btn-export-params`, `.btn-spinner-muted`) нет — значит они
действительно используются шаблоном.

### Что НЕ сделано и почему
- Живой клик по кнопке во фронте (реальный Tauri webview) не прогонял — сборка
  установщика/sidecar вне границ задачи («не запускай build_sidecar.py», «не собирай
  установщик»). Доказательство слоя (в) ограничено статической проверкой (`npm run check`)
  + сквозным прочтением кода по образцу соседей + `cargo check` для Rust-моста. Слои
  движка и Rust-контракта (тело запроса/ответа) доказаны живым HTTP-прогоном напрямую.
- Не добавлял отображение `paramsPath` в общий `.success-section` (тот блок виден только
  при `stepState === 'done'`, то есть только после первого экспорта одного из трёх
  форматов) — это создало бы ту же проблему «видно не сразу», от которой явно
  предостерегал бриф. Вместо этого путь к файлу выводится прямо под новой кнопкой,
  независимо от `stepState`.

### Где легко ошибиться следующему
- **Не подключать `model_data` к `/export/params` "для симметрии" с pptx/html** — это
  прямой путь назад к Critical C-1. Если понадобится передавать несохранённые изменения
  модели, решение — сначала сохранить их на диск, а не пробрасывать словарь в обход
  загрузчика.
- `_resolve_project_dir` в server.py резолвит `project_dir` с fallback на
  `%APPDATA%\aurora-econometrica-gui\projects\<id>` — идентификатор захардкожен под
  облачную редакцию; для локальной редакции (`com.aurora.econometrica.local`) Rust уже
  передаёт настоящий `project_dir` явно, так что fallback на практике не используется,
  но если кто-то станет звать `/export/params` без `project_dir` на локальной редакции —
  получит путь в чужом APPDATA-каталоге.
- Кнопка «Выгрузить параметры модели» не ограничивает частоту кликов ничем, кроме
  `paramsGenerating` — при быстром повторном клике до ответа сервера второй клик
  заблокирован (`disabled`), это ок, но если пользователь дважды подряд успеет (при
  очень быстром сервере) - будут два файла с разными таймстемпами, что нормально и
  ожидаемо (как и у html/pptx/xlsx).
