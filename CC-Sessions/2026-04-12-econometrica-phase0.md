---
tags: [session, compressed]
type: session
updated: 2026-04-12
---

# Quick Reference
Сессия реализации **Фазы 0** Next-Gen плана Aurora AI Econometrica. Трансформация chat-first MVP в Visual Analytics Workstation (6-шаговый pipeline). Фаза 0 закрыта полностью: sidecar lifecycle, PyInstaller build script, исправление критического бага A1 (event loop блокировка), help-страница.
Topic: econometrica-phase0
Key files: `src-tauri/src/econ_sidecar.rs`, `src-tauri/src/lib.rs`, `sidecar/econometrica/server.py`, `sidecar/econometrica/build_sidecar.py`, `src-tauri/help/econometrica.html`
Status: Фаза 0 ✅ ЗАВЕРШЕНА (коммит `816a0e0`, тег `v1.0.0-phase0-done`). Следующая — Фаза 1: Pipeline Architecture.

---

## Learnings

### Кодовая база Econometrica v1.0.0
- Tauri v2 + SvelteKit 5 + JS + Rust + Python sidecar FastAPI :7430
- `src-tauri/src/lib.rs` — монолитный (~2400+ строк), содержит команды Tauri + lifecycle логику
- `src-tauri/src/commands/econometrica.rs` — HTTP proxy к Python sidecar (9 команд, 134 строки)
- `sidecar/econometrica/server.py` — FastAPI с endpoints: health, validate, train, decompose, optimize, scenario, compare, awareness, chart
- Python engines: `validator.py`, `modeler.py`, `decomposer.py`, `optimizer.py`, `scenario.py`, `awareness.py`
- Старый `start_econometrica_sidecar()` в lib.rs не хранил Child process, не проверял orphan, не мог gracefully shutdown

### Parser sidecar как эталон
- `Aurora_Parser/src-tauri/src/sidecar.rs` — отличный шаблон: OnceLock<Mutex<Option<Child>>>, orphan check через TCP, exponential backoff, taskkill /T /F на Windows
- В Parser: `.setup()` hook получает `app_handle` → передаёт в `sidecar::start_sidecar(&app_handle)`, production path ищет bundled .exe через `app_handle.path().resolve()`

### A1 bug — критический
- Все compute endpoints в server.py были `async def`, но вызывали **синхронные** функции (MCMC 15 мин)
- FastAPI async endpoints работают в одном event loop → ВСЕ endpoints блокировались во время обучения, включая `/health`
- Следствие: Rust health check возвращал "unavailable", sidecar считался мёртвым, прогресс-бар не обновлялся
- Решение: `def` вместо `async def` — FastAPI автоматически выносит в thread pool

### B2 — --onedir vs --onefile
- PyMC + PyTensor + scipy + numpy = 300-500 MB bundle
- `--onefile` распаковывает в %TEMP% при **каждом** запуске → 10-30 сек задержки на HDD
- `--onedir` = директория без распаковки → старт < 2 сек

---

## Decisions

| Решение | Обоснование |
|---------|-------------|
| `econ_sidecar.rs` — отдельный модуль, не встраивать в lib.rs | Изоляция lifecycle логики, легко тестировать |
| `.setup()` hook для запуска sidecar (не в `run()`) | Только в setup есть `app_handle` → нужен для bundled exe path в production |
| `--onedir` для PyInstaller | Быстрый старт vs --onefile (10-30 сек распаковка) |
| `def` вместо `async def` для compute endpoints | FastAPI thread pool, event loop свободен |
| `econ_sidecar_wait_ready` Tauri command | Фронтенд может ждать ready state перед показом pipeline |
| Один route `/pipeline/+page.svelte` (не dynamic [step]) | Не уничтожать ECharts instances, сохранять form state между шагами (A3 fix) |
| localStorage только для metadata (step statuses) | Предотвратить overflow — results JSON 2-8 MB (A4 fix) |

---

## Files Modified

### Новые файлы:
| Файл | Описание |
|------|----------|
| `src-tauri/src/econ_sidecar.rs` | Sidecar lifecycle: start/wait/stop. Orphan check (TCP), exponential backoff, OnceLock<Mutex<Child>>, CREATE_NO_WINDOW, taskkill /T /F |
| `sidecar/econometrica/build_sidecar.py` | PyInstaller spec: --onedir, hidden-import для pymc/pytensor/fastapi/uvicorn, --exclude torch/dostoevsky |
| `src-tauri/help/econometrica.html` | Справка: 6 шагов pipeline, требования к данным, FAQ, технические детали |

### Изменённые файлы:
| Файл | Изменение |
|------|-----------|
| `src-tauri/src/lib.rs` | + `mod econ_sidecar;` в начале; заменён `start_econometrica_sidecar()` на `econ_sidecar_wait_ready` command; добавлен `.setup()` hook с `econ_sidecar::start_sidecar(&app_handle)` (только if is_econometrica()); добавлен `econ_sidecar::stop_sidecar()` в `on_window_event`; убран старый вызов из `run()` |
| `sidecar/econometrica/server.py` | A1 fix: `async def` → `def` для validate_data, train_model, decompose_sales, optimize_budget, predict_scenario, compare_scenarios, awareness_forecast, awareness_to_sales, generate_chart |

---

## Solutions & Fixes

### A1: FastAPI event loop blocking fix
```python
# БЫЛО (блокирует весь event loop на 15 минут):
@app.post('/compute/train')
async def train_model(req: TrainRequest):
    result = _train(config, project_dir)  # sync 15min call

# СТАЛО (FastAPI выносит в thread pool):
@app.post('/compute/train')
def train_model(req: TrainRequest):
    result = _train(config, project_dir)
```
Применено ко всем 9 compute endpoints.

### Sidecar lifecycle — ключевые паттерны
```rust
// Orphan check (TCP, не reqwest::blocking)
fn is_already_running() -> bool {
    TcpStream::connect_timeout(&addr, Duration::from_secs(1)).is_ok()
}

// Хранение Child process для graceful shutdown
static SIDECAR_PROCESS: OnceLock<Mutex<Option<Child>>> = OnceLock::new();

// Windows: убиваем всё дерево процессов (включая uvicorn workers)
Command::new("taskkill").args(["/PID", &pid.to_string(), "/T", "/F"])
    .creation_flags(0x08000000).output();
```

### .setup() hook для app_handle
```rust
// В build_app():
.setup(|app| {
    if commands::online_auth::is_econometrica() {
        let app_handle = app.handle().clone();
        econ_sidecar::start_sidecar(&app_handle);
    }
    Ok(())
})
```

---

## Setup & Config Changes

- `src-tauri/src/lib.rs` теперь имеет `mod econ_sidecar;` — нужно убедиться что файл компилируется (`cargo check` → OK, только 3 pre-existing warnings)
- Команда `econ_sidecar_wait_ready` зарегистрирована в invoke_handler — доступна из фронтенда как `invoke('econ_sidecar_wait_ready')`
- Git тег: `v1.0.0-phase0-done` на коммит `816a0e0`

---

## Pending Tasks

### Фаза 1: Pipeline Architecture (следующая сессия)
**Промпт готов** — в конце текущей сессии.

Файлы для создания:
- `src/routes/pipeline/+layout.svelte` — pipeline shell
- `src/routes/pipeline/+page.svelte` — **единый** route, все 6 шагов через visibility:hidden
- `src/lib/components/pipeline/PipelineStepper.svelte` — stepper
- `src/lib/components/pipeline/InsightsPanel.svelte` — правая панель AI insights

Файлы для изменения:
- `src/lib/project-state.js` — расширить до 6 шагов pipeline
- `src/routes/+layout.svelte` — добавить Pipeline в NavRail
- `src/routes/+page.svelte` — "Start Pipeline" CTA

Аудитные фиксы для применения в Фазе 1:
- **A3**: один route с visibility switching
- **A4**: localStorage только для metadata (~200 bytes), pipelineData — memory writable store
- **A5**: каскадный reset downstream при setStepComplete()
- **C1**: is_econometrica() guard в pipeline route
- **C4**: InsightsPanel `clamp(240px, 22%, 360px)` + collapse < 1100px
- **C5**: sidecarHealthy store → статус в footer

### sync-variants fingerprint fix (0.3)
- Запустить `sync-variants.ps1` — распространить fingerprint fix на Legal, Creative, Media, DocMaster, Creative Hub
- Отдельная сессия

### nav.js + user-guide.html + about.html (0.5 incomplete)
- Обновить навигационные файлы после Фазы 1 когда появится Pipeline route

---

## Full Session Notes

### Контекст сессии
- Антон запустил реализацию Next-Gen плана для Econometrica
- Plan file: `C:\Users\ackol\Desktop\Aurora Econometrica — Next-Gen Plan.md`
- Модель: Claude Sonnet 4.6 (переключена с Opus в начале сессии)
- Загружена память: communication-style, thinking-framework, все project memories

### Изученные файлы
- `Aurora_Parser/src-tauri/src/sidecar.rs` — эталон реализации lifecycle
- `Aurora_Parser/src-tauri/src/lib.rs` — setup() паттерн
- `Aurora_Econometrica/src-tauri/src/lib.rs` — полный (2400+ строк)
- `Aurora_Econometrica/src-tauri/src/commands/econometrica.rs` — 134 строки
- `Aurora_Econometrica/sidecar/econometrica/server.py` — FastAPI server
- `Aurora_Econometrica/src-tauri/help/econometrist.html` — шаблон для help

### Процесс реализации
1. Прочитан полный Next-Gen план (~1000 строк: Фазы 0-7 + Аудит A-D)
2. Проверено текущее состояние кодовой базы
3. Изучен Parser как эталон sidecar lifecycle
4. Создан `econ_sidecar.rs` по образцу Parser sidecar.rs (порт 7430, путь econometrica/)
5. Исправлен `lib.rs`: mod, setup, on_window_event, invoke_handler, убран старый `start_econometrica_sidecar()`
6. `server.py`: A1 fix — 9 async def → def
7. `build_sidecar.py`: --onedir spec с полным списком hidden-imports
8. `econometrica.html`: полная справка по pipeline
9. `cargo check` → ✅ (3 pre-existing warnings)
10. Коммит `816a0e0`, тег `v1.0.0-phase0-done`
11. Обновлён файл плана (таблица статусов, аудитные фиксы)
12. Обновлена память `project_econometrica.md`

### Структура таблицы статусов в плане
В начале файла плана добавлена таблица:
- Фаза 0: ✅ ЗАВЕРШЕНА | `816a0e0` | 2026-04-12
- Фазы 1-7: ⏳
- Список аудитных фиксов с отметками ✅ / ⏳

### Промпт для Фазы 1
```
Маша, прочитай основную память проекта.

Мы реализуем Next-Gen план для Aurora AI Econometrica.
План: C:\Users\ackol\Desktop\Aurora Econometrica — Next-Gen Plan.md
Кодовая база: D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica\

Фаза 0 завершена (коммит 816a0e0, тег v1.0.0-phase0-done).
Переходим к Фазе 1: Pipeline Architecture.

Прочитай план (раздел "Фаза 1") и файлы, которые нужно изменить:
- src/lib/project-state.js
- src/routes/+layout.svelte
- src/routes/+page.svelte

Затем реализуй Фазу 1 с учётом аудитных исправлений из плана:
- A3: один route /pipeline/+page.svelte с visibility switching (не dynamic [step])
- A4: localStorage только для metadata, данные в memory stores
- A5: каскадный reset downstream шагов
- C1: guard — Pipeline только для is_econometrica()
- C4: InsightsPanel clamp(240px,22%,360px) + collapse < 1100px
- C5: статус sidecar в footer

По завершении — коммит + тег v1.0.0-phase1-done + отметь в файле плана.
```
