# Aurora AI Econometrica — Python Sidecar

Python-движок эконометрического моделирования для варианта **Aurora AI Econometrica — MMM Optimizer**. Запускается Rust-частью Tauri-приложения как отдельный процесс, общается по JSON-RPC через stdin/stdout.

## Что внутри

| Модуль | Назначение |
|---|---|
| `server.py` | JSON-RPC сервер, диспатчер методов, авторизация |
| `validator.py` | Валидация данных (роли колонок, мультиколлинеарность, ratio, нулевые периоды) |
| `engines/` | Движки моделирования: байесовский MMM (NumPyro + JAX), OLS fallback, декомпозиция, оптимизатор, sensitivity, lift |
| `verdicts.py` | Бизнес-вердикты по результатам (sufficient / weak / artifact) |
| `persistence/` | Сохранение проектов в SQLite, миграции, autosave + crash recovery |
| `reports/` | Сборка PPTX / XLSX / HTML отчётов |
| `cabinets/` | Поддержка кабинетного режима (для других вариантов сборки) |

## Запуск (dev)

```bash
cd sidecar/econometrica
python -m server
```

Sidecar ожидает токен авторизации в первой строке stdin (или env-переменной `AURORA_SIDECAR_AUTH_TOKEN`). В production токен передаёт Rust при spawn'е процесса.

## Запуск (production)

В production sidecar упакован через PyInstaller в `aurora-sidecar.exe` (Windows) или `aurora-sidecar` (macOS/Linux) и лежит рядом с приложением (`src-tauri/binaries/`).

## Зависимости

- Python 3.11+
- NumPyro + JAX (байесовский вывод)
- pandas / numpy (обработка данных)
- python-pptx / openpyxl (отчёты)

Полный список — в корневом `pyproject.toml`.

## Тесты

```bash
cd <repo_root>
python -m pytest sidecar/econometrica/tests
```

## Методология

Полное описание математической модели — в `docs/MATH_REFERENCE.md` (1012 строк) и встроенной справке (`src-tauri/help-econometrica/methodology.html`).
