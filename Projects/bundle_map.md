# Карта экспорта — куда уходит расчёт клиенту (Aurora Econometrica canon)

Все пути от `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_canon\sidecar\econometrica\`. Каталоги `dist/`, `target/`, `_internal/`, `node_modules/`, `.venv/` исключены из поиска.

---

## 1. Точка расчёта декомпозиции

**Эндпоинт:** `server.py:1331` — `@app.post('/compute/decompose')` → `decompose_sales(req: DecomposeRequest)`.

```python
# server.py:1334-1348
from engines.decomposer import decompose as _decompose
...
result = _decompose(
    req.project_dir,
    unit_costs_override=req.unit_costs,
    unit_cost_inflation_pct=req.unit_cost_inflation_pct,
    kpi_unit_cost_override=req.kpi_unit_cost,
)
...
return JSONResponse(content=sanitize_nonfinite(result))
```

Реальная функция — `engines/decomposer.py:569` `def decompose(project_dir, unit_costs_override=None, unit_cost_inflation_pct=None, kpi_unit_cost_override=None, model_path=None, save_results=True) -> dict[str, Any]`.

**Полная структура возвращаемого словаря верхнего уровня** (`decomposer.py:1359-1441`, поле `result = {...}`):

| Ключ | Что |
|---|---|
| `status` | `'ok'` |
| `model_version` | версия pickle (`'1.0-ols'`/`'1.2'`/`'1.3'`/…) |
| `model_warning` | предупреждение по устаревшей модели или `None` |
| `smell_flags` | список диагностических «запахов» |
| `kpi_kind`, `derived_mode`, `value_per_count_unit`, `value_per_count_unit_label`, `kpi_type` | KPI-метаданные (ADR-016) |
| `total_sales`, `baseline`, `baseline_pct`, `media_contribution` | агрегаты |
| `kpi_unit_cost` | цена единицы KPI (может быть `None`) |
| `money_roi_unavailable` | bool — отключены ли денежные пороги окупаемости |
| `total_sales_money`, `baseline_money`, `media_contribution_money` | денежные эквиваленты (или `None`) |
| `channels` | список per-channel записей (ROI, contribution, CI) |
| `insight` | текстовый инсайт |
| `waterfall` | `{labels, values, types}` |
| `time_series` | `{dates, baseline, channels}` |
| `hierarchical` | `{enabled, channel_categories, categorization_warnings, priors_summary}` |
| `signed_factor_contributions` | v2.0.0 (ADR-019 §4) — конкуренты/цена/погода/макро/праздники/сезонность/positive_control, схема `{factor: {value, pct, type, beta_mean, per_period[]}}` |
| `decomposition_series` | канонический таймлайн-набор (единый источник для UI и всех отчётов) |

Если `save_results=True` (дефолт) — результат (после `sanitize_nonfinite`) пишется на диск в `results/decomposition.json` (`decomposer.py:1446-1451`), помимо возврата наружу через API.

**Вывод:** decompose — единственная точка, где формируется полный snapshot расчёта; наружу отдаётся JSON без какого-либо криптографического идентификатора/сертификата — их там нет вовсе.

---

## 2. Экспорт отчёта

### 2.1 Кто зовёт

- **PPTX:** `server.py:2187` `@app.post('/export/pptx')` → `export_pptx(req: PptxExportRequest)` → `engines/pptx_export.py:53` `build_pptx(...)` → делегирует в `aurora_pptx/__init__.py:35` `build_pptx(data=None, lang='ru')` → `AuroraPPTXBuilder(data=data, lang=lang).build()` (класс живёт в `aurora_pptx/builder.py`, 4074 строк).
- **HTML:** `server.py:2262` `@app.post('/export/html')` → `export_html(req: HtmlExportRequest)` → `engines/html_export.py:71` `build_html(...)` → делегирует в `aurora_html/__init__.py` → `AuroraHTMLBuilder` (`aurora_html/builder.py`).
- **JSON:** `engines/json_export.py:31` `export_model_params_json(model_data, pretty=True)` и `:156` `export_model_params_to_file(...)` — **НЕ вызываются ни из одного эндпоинта `server.py`, ни из фронта.** Grep по всему `sidecar/econometrica/**/*.py` — единственные упоминания `json_export` — в самом файле и в докстринге `methodology_cert.py`. Live `/export/json` эндпоинта нет.
- Кто зовёт Rust/фронт — эти два POST-эндпоинта (`/export/pptx`, `/export/html`) вызываются из Rust-команд Tauri (не проверяла напрямую `src-tauri`, за пределами поручения — но по паттерну сайдкара это HTTP-прокси с фронта через Rust).

### 2.2 Вход/выход

- **PPTX** (`server.py:2242-2247`): `build_pptx(req.model_data, req.decompose_data, req.optimize_data, output_path, scenarios=..., project_id=..., backtest=..., generation_compare=..., promises=..., forecast=...)`. `output_path` = `<project_dir>/exports/mmm_report_<ts>.pptx` (`server.py:2202`).
- **HTML** (`server.py:2307-2313`): `build_html(req.model_data, decompose_for_build, req.optimize_data, output_path, scenarios=..., project_name=..., project_id=..., backtest=..., generation_compare=..., promises=..., forecast=...)`. `output_path` = `<project_dir>/exports/mmm_report_<ts>.html`.
- Оба гейтятся `_assert_decompose_present()` (`server.py:2161-2184`, INV-50 NEW-2) — пустой `decompose_data` без `allow_wireframe=True` → HTTP 400.

### 2.3 Report ID в HTML

Общий источник для HTML и PPTX — `engines/narrative_adapter.py:358` `compute_report_id(client, project_id, channels, diagnostics) -> str` (формат `aurora-mmm-{12hex}`, SHA-256-префикс от client+project+channels+diagnostics; **версия продукта сознательно не входит в хеш** — ID идентифицирует контент отчёта, не сборку).

- **HTML:** `aurora_html/builder.py:134-136` — `self.report_id = compute_report_id(self.client, self.project_id, self.channels, self.diagnostics)`.
  - Рендерится в футере шаблона: `aurora_html/templates/shell.html:79-93` (`<footer class="app-footer">`), подстановка в `builder.py:655` `report_id=security.escape(self.report_id)` → `shell.html:82-83`:
    ```html
    <div class="footer-section footer-report-id">
      <div class="footer-label">${report_id_label}</div>
      <code class="report-id">${report_id}</code>
    </div>
    ```
  - Также в meta-описании документа: `builder.py:628` `doc_description = f"... Report ID: {self.report_id}"`.
- **PPTX:** `aurora_pptx/builder.py:377` — `self.report_id = self.data.get("report_id") or compute_report_id(...)`. Отображается на слайде-обложке в 4-колоночной метаданных-сетке (`builder.py:1164-1188`, колонка `("REPORT ID", self.report_id)` на строке 1170), и повторяется в подписях-источниках почти на каждом content-слайде (`builder.py:1636, 1882, 2270, 2272, 2407, 2555` — формат `f"Источник: ... · {self.report_id}"`).

**⚠️ Важно (deprecated-ловушка):** в `aurora_pptx/` есть параллельный набор файлов `layouts.py`, `master.py`, `tokens.py`, `typography.py`, `charts.py`, `i18n.py`, `strings_ru.json/en.json` — они **deprecated**, живой код инлайнен в `builder.py` (см. докстринг `aurora_pptx/__init__.py:24-27`, "Deprecated submodules... Early-session skeleton; functionality inlined into builder.py during Session 3 port"). В `layouts.py` есть заглушки `render_methodology`, `render_sources`, `render_colophon` — все три **`raise NotImplementedError(...)`** ("M3 Session 3") — это мёртвый нереализованный код, НЕ путать с живыми `s10_methodology()` (`builder.py:2909`) и `s13_colophon()` (`builder.py:3954`), которые реально рендерят слайды.

---

## 3. Место под блок «Воспроизводимость и сертификат»

### В HTML

- Есть готовая секция методологии: `aurora_html/sections.py:1682` `def render_methodology(ctx) -> str`, зарегистрирована в `SECTION_RENDERERS` (`sections.py:2251`, тег `'method'`). Естественное место для блока сертификата — внутри неё, рядом/под `<div class="methodology-grid">` (`sections.py:1740`), где уже рендерятся диагностика/приоры.
- Report ID уже в футере документа (`shell.html:79-93`, см. п.2.3) — рядом с ним (`footer-section footer-report-id`, `shell.html:81-84`) логично добавить ещё один `footer-section` с хешем сертификата/статусом верификации, либо отдельный блок внутри методологии со ссылкой на `verify.auroraai.pro` (упомянут в докстринге `methodology_cert.py:6`).
- Контекст сборки (`ctx` в `builder.py:567-587`) уже содержит секцию `"trust": {"backtest": ..., "generation_compare": ..., "promises_summary": ...}` — по аналогии сертификат можно прокинуть новым ключом `"certificate": {...}` в тот же `ctx`.

### В PPTX

- Живой слайд методологии — `s10_methodology()` (`builder.py:2909-3094`, физическая страница 11). Внутри него блок «ДИАГНОСТИКА» (`builder.py:2984-3024`) — таблица label/value (R², MAPE, R-hat, ESS для байеса / R², MAPE, метод, диапазон для OLS). Естественно добавить туда строку (например «Зерно сэмплера» / «Хеш сертификата») тем же паттерном `for label, val in diag: ...`.
- Финальный слайд `s13_colophon()` (`builder.py:3954-4037`, физическая последняя страница) сейчас — чистый брендовый CTA-слайд без метрик («No duplication of metrics from other slides», см. докстринг строки 3955-3957) — тоже вариант, но потребует нарушить его текущий принцип «без метрик».
- Cover-слайд уже содержит 4-колоночную сетку метаданных (`builder.py:1164-1188`: «ПОДГОТОВЛЕНО ДЛЯ» / «ДАТА» / «REPORT ID» / «КЛАССИФИКАЦИЯ») — жёстко на 4 колонки (`col_w = (self.w - 2*self.safe - 0.2) / 4`), добавление 5-й колонки потребует правки геометрии.

**Рекомендуемое место (моя оценка, не решение):** секция методологии в обоих форматах — там уже живёт содержательный disclosure, и она одна на весь отчёт (в отличие от футера/breadcrumb, которые повторяются на каждой странице избыточно).

---

## 4. Паспорт воспроизводимости (seed / seed_source / diagnostics / mcmc_info)

**Модуль:** `utils/seeding.py` (253 строки, весь модуль посвящён этому).

- `resolve_seed(config) -> (seed, seed_source)` (`seeding.py:60-88`) — источник: `config['seed']` → `env AURORA_MCMC_SEED` → `DEFAULT_SEED=42`; `seed_source ∈ {'config', 'env', 'default'}`.
- `environment_snapshot(*, seed, seed_source, chains, draws, tune, has_compiler, chain_method=None, jax_devices=None) -> dict` (`seeding.py:114-164`) — возвращает словарь:
  ```python
  {
    'seed': seed, 'seed_source': seed_source, 'sampler_tier': None,
    'chain_method_requested': ..., 'chain_method_delivered': False,
    'jax_devices': ..., 'has_compiler': ...,
    'mcmc': {'chains':..., 'draws':..., 'tune':...},
    'versions': {...},  # python/numpy/pymc/pytensor/numpyro/jax
    'platform': {'system':..., 'release':..., 'machine':..., 'python':...},
  }
  ```
- `mark_sampler_tier(snapshot, tier)` (`seeding.py:221-229`) дописывает фактический ярус (`numpyro-nuts` / `pytensor-nuts` / `pytensor-nuts-no-callback`) после сэмплинга.
- `seed_from_model(model_data) -> (seed, seed_source)` (`seeding.py:167-191`) — читает `model_data['reproducibility']['seed']`, иначе фолбэк на `resolve_seed(model_data['config'])`; источник `'model'`. Используется для воспроизведения того же зерна при перепроверке на истории (backtest).

**Кто пишет в pickle** (`engines/modeler.py`):
- `modeler.py:785-793` — вызов `resolve_seed(config)` + `environment_snapshot(...)` при тренировке.
- Снапшот кладётся **в двух местах** сохранённой модели:
  - `model_data['diagnostics']['reproducibility']` (`modeler.py:1380`);
  - `model_data['reproducibility']` — верхний уровень (`modeler.py:1608`, а также `1900`, `1925` — по одному на ветку byte-identical-repro).
- `mark_sampler_tier(reproducibility, TIER_NUMPYRO/...)` вызывается по факту успешного сэмплинга (`modeler.py:1078, 1124, 1137`).

**Как достать после загрузки модели:** `model_data = load_model_with_compat(path)` (из `engines/persistence.py`) → `model_data['reproducibility']` (полный снапшот) или `model_data['diagnostics']['reproducibility']` (тот же словарь, дублируется для совместимости с UI, читающим diagnostics). Других пользователей нашла: `utils/reliability_a4.py`, `engines/optimizer.py` (оба ссылаются на `reproducibility`).

---

## 5. Формат сохранённой модели (`engines/persistence_safe.py`)

Формат — `aurora-model` (ZIP-архив), константы `FORMAT_NAME = 'aurora-model'`, `FORMAT_VERSION = '1'` (`persistence_safe.py:62-63`).

**`manifest`** формируется в `save_model_safe(model_data, path, *, extra_manifest=None)` (`persistence_safe.py:308`):

```python
# persistence_safe.py:334-340, затем 365-367
manifest = {
    'format': FORMAT_NAME,               # 'aurora-model'
    'format_version': FORMAT_VERSION,    # '1'
    'created_at': datetime.now(timezone.utc).isoformat(),
    'array_count': len(arrays),
    'model_version': model_data.get('model_version', 'unknown'),
    # + любые ключи extra_manifest (кроме format/format_version — защищены)
}
...
manifest['sha256_data'] = hashlib.sha256(data_bytes).hexdigest()
if arrays_bytes:
    manifest['sha256_arrays'] = hashlib.sha256(arrays_bytes).hexdigest()
```

Итого поля manifest: `format`, `format_version`, `created_at`, `array_count`, `model_version`, `sha256_data`, `sha256_arrays` (опционально, если есть numpy-массивы) + всё, что передано через `extra_manifest`.

**Доступ снаружи без полной загрузки модели:** `read_manifest(path) -> dict[str, Any]` (`persistence_safe.py:621-641`) — читает только `manifest.json` из ZIP без десериализации данных/массивов. Использует `zipfile.ZipFile`, бросает `FileNotFoundError` / `CorruptArchiveError` / `SafeModelFormatError` на плохом файле. Докстринг явно говорит «удобно для UI-диагностики (показать model_version, created_at) без полной десериализации».

`sha256_data` защищает `_split_arrays()`-очищенный JSON-payload модели (без бинарных массивов), `sha256_arrays` — отдельный npz-архив с numpy-массивами (посteriors и т.п.); при загрузке (`load_model_safe`, строки 495-522) оба хеша сверяются (SH-AM-05 защита от подмены).

---

## 6. `save_v20_diagnostics` — живые вызывающие + `model_version` при обучении

**🔴 Ключевая находка: `save_v20_diagnostics` (`engines/persistence.py:863`) НЕ имеет ни одного живого вызывающего в продуктовом коде.**

Полный grep `save_v20_diagnostics` по `sidecar/econometrica/**/*.py`:
- `persistence.py:38, 747, 839, 863(def), 923, 938, 994, 1012` — определение и внутренние комментарии/докстринги самого модуля.
- `modeler.py:1833` и `ols_modeler.py:494` — только **комментарии** («SH-AM-11: project_lock защищает от race условий с `save_v20_diagnostics`») — упоминание в тексте, не вызов функции.
- `tests/test_persistence_safe.py:736-737` — единственный реальный вызов, и это тест.

Никакой эндпоинт `server.py` и никакой `engine/*.py` не вызывает `save_v20_diagnostics()` в живом потоке. Функция при вызове бампает `model_data['model_version'] = '2.0.0'` (`persistence.py:927`) и пишет allowlist-поля (`mcmc_diagnostics`, `backtest_results`, `ppc_results`, `holiday_dummies_injected`, `analysis_mode`, `sensitivity_tornado_cache`, `signed_factor_priors_used`) — но раз функция не вызывается, **свежеобученная модель никогда не получает `model_version = '2.0.0'` через этот путь.**

**Чему равен `model_version` при живом обучении** (`engines/modeler.py:1673`):
```python
'model_version': '1.3' if use_hierarchical else '1.2',
```
Т.е. сразу после `train()` модель помечена `'1.2'` или `'1.3'` — не `'2.0.0'`. Единственное другое место присвоения `model_version` в `modeler.py` — не найдено (grep дал ровно одно совпадение на весь файл).

**Следствие для сертификата методологии:** `methodology_cert.py::build_cert_payload()` определяет v2.0.0-ветку через `is_v20_compatible(model_data)` (`persistence.py:762`), которая по факту почти никогда не сработает на свежей модели, потому что `model_version` остаётся `'1.2'/'1.3'` — путь, который должен был бы бампнуть до `'2.0.0'` (`save_v20_diagnostics`), не вызывается. Нужно либо (а) найти/восстановить живой вызов `save_v20_diagnostics` после backtest/PPC-шагов, либо (б) переопределить условие v2.0-совместимости в `methodology_cert.py`, либо (в) присваивать `'2.0.0'` прямо в `modeler.py` при тренировке, если v2.0.0-поля (`signed_factor_contributions`, `holiday_dummies_injected` и т.п.) уже заполняются на этапе `train()` (нужна отдельная проверка — не входила в это поручение).

---

## Чего НЕ нашла

- Live `/export/json` эндпоинт — `json_export.py` полностью не подключён ни к одному роуту `server.py` (только к тестам? — grep по `tests/` на `json_export`/`export_model_params` не делала отдельно, стоит проверить отдельно если понадобится).
- Прямые вызовы `engines/methodology_cert.py` (`build_cert_payload`, `compute_cert_hash`, `generate_methodology_certificate`) — ни в `server.py`, ни в `engines/*.py`, ни в `tests/*.py`. Модуль полностью написан (361 строка, версии v1.3/v2.0.0, JCS RFC 8785 канонизация), но нигде не подключён — «осиротевший» движок, готовый к интеграции.
- Кто именно из Rust/фронта дёргает `/export/pptx` и `/export/html` — не проверяла `src-tauri/` (за пределами поручения по каталогам сайдкара).
- Слайд-конфигурация `build()` (`builder.py:4041-4070`) — не выписала полный порядок всех 13 слайдов, только относящиеся к вопросу (методология, colophon, cover).
