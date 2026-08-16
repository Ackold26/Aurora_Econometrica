# Отчёт — правка справки Econometrica (2026-08-16)

Ветка: `feat/econ-p1-winning` (не переключалась, не создавалась новая). Ничего не закоммичено (`git add` не вызывался).

## Пункт 1. Обещание XLSX/PPTX для выгрузки сценариев

**Файл:** `src-tauri/help-econometrica/features.html:181`

**Было:**
> «Сохранённые сценарии выгружаются в CSV / XLSX / PPTX отдельно от основного отчёта.»

**Стало:**
> «Сохранённые сценарии выгружаются в CSV отдельно от основного отчёта.»

**Чем доказано:**
- `grep -rn "econ_export_scenarios_xlsx\|export_scenarios_pptx" src-tauri/src` — ноль совпадений (команды не существуют, дал grep до начала правки — задача сама содержала эту проверку, дополнительно не перепроверяла, т.к. src-tauri/src не менялся и второй исполнитель его тоже не трогает).
- Соседняя строка про ОСНОВНОЙ отчёт (`features.html:177`, «Единая кнопка «Создать отчёт»» — PPTX/XLSX/HTML) не тронута — там формат правдив, это отдельная сущность (основной отчёт vs экспорт сценариев).

## Пункт 2. «6-шаговый процесс» → 7 шагов

**Файл:** `src-tauri/help-econometrica/econometrica.html:126`

**Было:**
> «Интерактивный 6-шаговый процесс с визуализациями. Drag-drop импорт, автоопределение колонок, корреляционная матрица, прогресс обучения, оптимизатор бюджета.»

**Стало:**
> «Интерактивный 7-шаговый процесс с визуализациями. Drag-drop импорт, автоопределение колонок, корреляционная матрица, прогресс обучения, оптимизатор бюджета.»

**Чем доказано:**
- `src/lib/project-state.js:82-90`, `PIPELINE_STEPS` — 7 записей: import, validate, model, decompose, optimize, **planning**, report.
- `src-tauri/help-econometrica/features.html:98` уже верно гласит «Пайплайн моделирования (7 шагов)» и перечисляет все 7 (`features.html:101-107`) — расхождение было именно в `econometrica.html:126`.

**Проверка всего каталога справки на другие упоминания числа шагов:**
```
grep -rn "шаг" src-tauri/help-econometrica/ | grep -iE "шест|6-шаг|семь|7-шаг"
```
Единственное совпадение — сама строка `econometrica.html:126`, уже исправлена. Других мест с «6 шагов»/«шестишаговый» в каталоге справки нет. Отдельно отмечаю: цифры «6» встречаются в справке в других контекстах (например номер раздела `<span class="h2-num">6</span>Чат-режим Эконометрист` в `features.html:195`, версия «v1.0.16»/«v1.1.0» в историч. пометках) — это НЕ про число шагов пайплайна, не трогала.

## Пункт 3. Пересборка PDF справки

Инструмент: `tools/build_help_pdf.py` (без аргументов — берёт дефолтные пути `src-tauri/help-econometrica/`, `tools/help_pdf_manifest.json`).

```
python tools/build_help_pdf.py
```

Результат:
```
[help-pdf] Version:     2.4.10
[help-pdf] Printing main pages... / appendix / front cover / back cover
[help-pdf] Merging into final PDF...
[help-pdf] Page numbers: 2..117 (обложки без номера)
[help-pdf] Manifest:    tools/help_pdf_manifest.json
[help-pdf] Done: src-tauri/help-econometrica/econometrica-help.pdf (2980.1 KB)
```
PDF и манифест `tools/help_pdf_manifest.json` обновлены (sha256 всех html + econ-nav.js пересчитан).

## Гейты справки — прогнаны и зелёные

Источники заданий: `lefthook.yml` (pre-commit hooks) + `.github/workflows/ci.yml`. Из списка, касающегося справки, прогнаны:

| Команда | Результат |
|---|---|
| `python tools/check_help_pdf_consistency.py` | **OK**, exit 0. econ-nav.js<->файлы согласованы, U+2014 не найден, копирайт на месте, версия tauri.conf.json=package.json, **PDF свежий** (манифест совпал после пересборки). 5 WARN (не FAIL) — старые историч. пометки версий «v1.0.16»/«v1.1.0» в `econometrica.html`/`methodology.html`, не относятся к моим правкам, линтер сам их не считает блокирующими (см. докстринг линтера п.4). |
| `python tools/check_help_consistency.py` | **OK**, exit 0. Четверное совпадение команд кабинета econometrist (8=8=8) — не задевалось моими правками, гейт зелёный. |
| `python tools/check_glossary_sync.py` | **OK**, exit 0. Глоссарий синхронен, U+2014 не найден. |

Не прогоняла `prompt-lint` (`tools/lint_prompt_commands.py`) — по glob в lefthook.yml он касается `New_AI_Agency/econometrist/**`, а не `src-tauri/help-econometrica/*.html`; правки этого пункта не задевали. `content-pack-sync` — тоже вне scope (правки не касались `content-packs/*.json`).

## Проверка длинного тире «—»

```
grep -n "—" src-tauri/help-econometrica/features.html src-tauri/help-econometrica/econometrica.html
```
Совпадений нет (exit 1 = не найдено) — в обоих файлах длинного тире нет ни в правках, ни в остальном тексте.

## Итог

- Изменённые файлы: `src-tauri/help-econometrica/features.html`, `src-tauri/help-econometrica/econometrica.html`, `src-tauri/help-econometrica/econometrica-help.pdf` (бинарный артефакт пересборки), `tools/help_pdf_manifest.json`.
- `src/` не трогала.
- Ничего не закоммичено, веток не создавала.

РАБОТА ЗАВЕРШЕНА. 16 авг 2026 г. 12:14
