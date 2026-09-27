# DATEFIX s53 – края срока плана выводились сырыми метками ISO

**Дефект:** «Срок плана: 32 периода (2024-12-30T00:00:00 – 2025-08-04T00:00:00)» в PPTX (слайд 7) и HTML-отчёте.
**Стало:** «Срок плана: 32 периода (дек 2024 – авг 2025)». Формат совпадает с соседней фразой периода данных («янв 2023 – дек 2024»).

## 1. Опись поверхностей

| Поверхность | Где | Что выводит | Решение |
|---|---|---|---|
| HTML-отчёт | `sidecar/econometrica/aurora_html/sections.py:2686` | `period_first – period_last` из `summarize_forecast` | исправлено |
| PPTX | `sidecar/econometrica/aurora_pptx/builder.py:4165` | то же | исправлено |
| Источник | `engines/planning.py:639-640` (`labels[0]/labels[-1]`) | метки из `period_labels` или `future_dates` сценария (planning.py:442) | НЕ тронут: сохранённые данные остаются прежними |
| Интерфейс | `src/**` | `period_first/period_last` не выводит нигде | – |
| Интерфейс, соседнее | `ValidateStepV13.svelte:1273`, `PlanningStep.svelte:764` | тот же срок, но из `mp.period_labels` (`_period_label`: «2025-W01», «2025-01»), не ISO со временем | вне условия «такие же сырые метки», НЕ тронуто, вынесено оркестратору |
| Ось графика | `ContinuationChart.svelte:266-269` | ISO уже нормализуется | – |
| XLSX «Прогноз» | `src-tauri/src/commands/report.rs:2096-2123` | `period_labels` построчно (по периоду в строке), срока плана нет | вне задачи, не тронуто |
| Справка | `git grep "Срок плана"` | вне кода отчётов не найдено | – |

Боевые сценарии `period_labels` не несут (движок scenario.py их не выдаёт), поэтому сводка берёт `future_dates`, а это всегда ISO. Метки вида «2026-01» встречаются только в тестовых наборах.

## 2. Что изменено

- `sidecar/econometrica/engines/narrative_adapter.py:901-927` – рядом с `_RU_MONTHS_SHORT` добавлены:
  - `_ru_month_year(dt)` – «мес год»;
  - `_parse_period_label(label)` – разбор по тому же правилу, что в `_derive_data_coverage`: `str[:10]` → `%Y-%m-%d`;
  - публичная `format_period_span(first, last)`. Если хоть одна метка не разбирается, обе выводятся как есть, форматы не смешиваются. Если оба края в одном месяце, выводится один «мес год».
- `narrative_adapter.py:957` – вложенная `_lbl` в `_derive_data_coverage` теперь зовёт `_ru_month_year`: одно правило для обоих периодов, результат прежний.
- `aurora_pptx/builder.py:4166-4167` и `aurora_html/sections.py:2687-2690` – оба отрисовщика зовут `format_period_span`. HTML экранирует итоговую строку целиком.
- JS не менялся, поэтому vitest и `npm run check` не требовались и не запускались.

## 3. Тесты и мутация

Добавлено 8 тестов в `sidecar/econometrica/tests/test_planning_section_reports.py`, раздел (l):

- функция: ISO → «дек 2024 – авг 2025»; один месяц → «мар 2025»; неразборчивые («2025-W01», «1» + ISO, None) → как есть;
- `summarize_forecast` сохраняет сырые метки (данные не тронуты);
- HTML: нет `T00:00:00`, есть «(дек 2024 – авг 2025)»; недели – «(2025-W01 – 2025-W32)»;
- PPTX: нет `T00:00:00`, есть «Срок плана: 3 периода (дек 2024 – авг 2025)»; недели – как есть.

**МУТАЦИЯ:** в pptx и html вернула старые строки вывода, тесты по срезу `-k span` дали 2 failed (`test_html_plan_span_human_readable`, `test_deck_plan_span_human_readable`). После отката из копий – 7/7 passed.

## 4. Прогоны

| Прогон | Было | Стало | Код |
|---|---|---|---|
| `test_planning_section_reports.py` | 34 | 42 passed | 0 |
| pytest движка (`sidecar/econometrica/tests -n auto -m "not requires_real_data and not slow"`) | 1784/0 | **1792 passed / 0 failed / 2 skipped** | 0 |
| pytest tools (корень, как в CI) | 2348/0 | 2347 passed / **1 failed** / 7 skipped | 1 |
| ↳ повтор упавшего файла `tools/test_fourier_integration.py -n 0` | – | 7 passed | 0 |
| **pytest tools, перезапуск `-n 4`** (свободно 5,82 ГБ, без моих параллельных задач) | 2348/0 | **2348 passed / 0 failed / 7 skipped**, дампов 0x8007000e нет | 0 |
| `lint_prompt_commands.py` | – | OK 19/19 | 0 |
| `check_help_consistency.py` | – | OK | 0 |
| `check_content_pack_sync.py` | – | OK, v7 | 0 |

Упал `test_backtest_with_seasonality_not_error`: окно бэктеста `WINDOW_TRAIN_NOT_OK` с пустым текстом ошибки. В тот момент машине не хватало памяти – в журнале `Windows fatal exception 0x8007000e` (E_OUTOFMEMORY) при старте рабочих xdist, у bash `fork: Resource temporarily unavailable`. Бэктест с моей правкой не связан (правка только в строках вывода). Отдельным прогоном файл зелёный, поэтому считаю тест плавающим под нагрузкой.
По указанию оркестратора весь tools перезапущен с `-n 4`: 2348/0, код 0. **Принимается этот прогон** (`Projects/_pytest_tools_s53_datefix_n4.log`).
Журналы: `Projects/_pytest_s53_datefix.log`, `Projects/_pytest_tools_s53_datefix.log` (игнорируются `.gitignore`).

## 5. Пересборка движка

`python sidecar/econometrica/build_sidecar.py` → `Projects/_build_sidecar_s53.log`, RC=0.
- Build SUCCESS, смоук бандла: validate CSV ok, XLSX ok.
- `[OK] Freshness verified (exe newer than all .py sources)`.
- Версия `econometrica-sidecar.exe`: **2.5.6.0** (метаданные «уже на версии продукта 2.5.6»), время 27.09 20:06.
- SHA256: `819DA563DC1C1F755213B6AE59C0BC40B51D0A51F1460B6637D2B22C6845EEB7`.
- Проба: exe на :8798 → `/health` 200 за 10,2 с, процесс снят, чужих процессов движка не осталось.
- `src/tokens.generated.css` сборка переписала только меткой времени, возвращён через `git checkout`.

## 6. Дерево

```
 sidecar/econometrica/aurora_html/sections.py       |  4 +-
 sidecar/econometrica/aurora_pptx/builder.py        |  3 +-
 sidecar/econometrica/engines/narrative_adapter.py  | 31 +++++++++-
 .../tests/test_planning_section_reports.py         | 69 ++++++++++++++++++++++
 4 files changed, 103 insertions(+), 4 deletions(-)
```
Неотслеживаемые мои: `Projects/PULSE_s53_datefix.md`, `Projects/DATEFIX_s53.md`. Остальные `??` (PROBE/PULSE_*/SAMPLES_s53) принадлежат другим исполнителям s53.
Git при следующем касании заменит LF на CRLF в 4 файлах (предупреждение git). В `diff --stat` видны только правленые строки, пересохранения целых файлов нет.

## Долг 2.5.7 (решение оркестратора: в этом выпуске не трогать)

- **Согласовать вид срока плана на экране с отчётом.** `ValidateStepV13.svelte:1273` и `PlanningStep.svelte:764` показывают «(2025-W01 – 2025-W32)» / «(2025-01 – 2025-08)» из `period_labels` (намеренный формат меток периода, не ISO со временем), а отчёт после правки – «дек 2024 – авг 2025».
- **XLSX «Прогноз»** (`report.rs:2096-2123`): столбец «Период» выводит `period_labels` построчно как есть. Только упоминание.
- Пересборка движка прошла до того, как пришло правило «≥5 ГБ свободно перед сборкой». Сборка завершилась с кодом 0, смоук и проверка свежести пройдены, поэтому повторно не собирала.

## Непроверено

- Живой отчёт из НОВОГО exe (PPTX/HTML через программу) не рендерился. Доказательства: тесты на исходниках и сторож свежести (exe новее всех .py). Что `format_period_span` действительно попала в бандл, отдельно не извлекалось.
- Образцы покупателя не пересобирались.

---

# Доработка по аудиту (`AUDIT_s53_datefix.md`: 0 Critical / 0 High / 1 Medium / 5 Low)

Оркестратор решил сделать в 2.5.6 три пункта: M1 (часть), L5 и L3. Остальное (L1 кварталы/годы, L2 экран, L4 строка «итого», окна бэктеста) не тронуто.

## Что изменено
- **M1** – `aurora_pptx/builder.py:2566-2567`: `period_label` слайда декомпозиции раньше собирался как `f"{dates_list[0]} - {dates_list[-1]}"`, теперь берётся из `format_period_span(...)`. Потребители: подзаголовок графика (`:2589`/`:2591`), строки «Источник» (`:2664`, `:2809`). На фикстуре Kagocel было «2023-01-01 - 2025-07-01» (с дефисом), стало «янв 2023 – июл 2025». Это тот же вид, что у периода данных в той же презентации. В HTML сырых дат в этой фразе нет: HTML-фраза «за период» (`sections.py:654`) берёт готовый `data_window_label`. Окна бэктеста (`sections.py:~2447`, слайд 6) не трогала.
- **L5** – `aurora_html/strings_ru.json:89`: «Weighted ROI» → «Средневзвешенный ROI», как в PPTX. В подписанный пакет содержимого файл не входит (в `content-packs/` его нет), переподпись не нужна. `check_content_pack_sync` и `check_help_consistency` – OK. Термин словаря «Weighted ROI» (`strings_ru.json:288`) не тронут: это вне поручения, отмечаю для решения.
- **L3** – добавлен тест экранирования края срока в HTML.

## Тесты (+3) и мутации
- `test_deck_decomposition_period_human_readable` (M1): в тексте нет «2023-01-01 - 2025-07-01», есть «продажи за период янв 2023 – июл 2025;» и «· янв 2023 – июл 2025».
- `test_situation_legacy_kpi_says_weighted_roi_in_russian` (L5, `tests/test_scqar_period_label_matches_coverage.py`): ветка шаблона для старого KPI, нет «Weighted ROI», есть «Средневзвешенный ROI 1.6×».
- `test_html_plan_span_is_escaped` (L3): метка `<script>alert(1)</script>` не попадает в вывод как есть, выводится `&lt;script&gt;…`.
- **МУТАЦИИ:** A – старая строка `period_label` → тест M1 КРАСНЫЙ; B – «Weighted ROI» обратно в шаблон → тест L5 КРАСНЫЙ; C – `escape` → тождество → тест L3 КРАСНЫЙ. Откат из копий, `cmp` идентично, 48/0.

## Прогоны доработки
| Прогон | Было | Стало | Код |
|---|---|---|---|
| pytest движка `-n 4` (свободно 6,37 ГБ) | 1792/0 | **1795 passed / 0 failed / 2 skipped** | 0 |
| pytest tools `-n 4` | 2348/0 | **2348 passed / 0 failed / 7 skipped** | 0 |
| tools по файлам, читающим `strings_ru.json`/отчёты (kpi_aware, narrative_coherence, pptx_integration, narrative_adapter) | – | 49 passed | 0 |
| `verify_aurora_html_brand.py` | – | 34/34 | 0 |
| три линтера | – | OK | 0 |

В журналах доработки дампов 0x8007000e нет. Журналы: `_pytest_s53_datefix_audit.log`, `_pytest_tools_s53_datefix_audit.log`.

## Пересборка движка (вторая)
- Перед сборкой свободно 5,43 ГБ, моих процессов pytest или движка нет.
- `Projects/_build_sidecar_s53b.log`, RC=0: Build SUCCESS, смоук validate CSV/XLSX ok, `[OK] Freshness verified`.
- Версия **2.5.6.0**, exe от 27.09 20:24, SHA256 **`F82A4A758BDD498BDFE4F9E80188AF39ED4DCA6851B502C7C01B44420127E826`** (заменяет хеш первой сборки `819DA563…`).
- Копии в бандле `_internal/` совпадают с исходниками (`cmp`) для `strings_ru.json`, `builder.py`, `sections.py`, `narrative_adapter.py`. Это важно для `strings_ru.json`: сторож свежести сверяет только `.py`.
- Проба на :8798: `/health` 200 за 13,5 с, процесс снят.
- `src/tokens.generated.css` сборка снова тронула (1 строка), вернула через `git checkout`.

## Дерево после доработки
```
 sidecar/econometrica/aurora_html/sections.py       |  4 +-
 sidecar/econometrica/aurora_html/strings_ru.json   |  2 +-
 sidecar/econometrica/aurora_pptx/builder.py        |  6 +-
 sidecar/econometrica/engines/narrative_adapter.py  | 31 +++++++-
 .../tests/test_planning_section_reports.py         | 91 ++++++++++++++++++++++
 .../test_scqar_period_label_matches_coverage.py    |  9 +++
 6 files changed, 137 insertions(+), 6 deletions(-)
```

## Долг 2.5.7 (дополнено)
- L1: при кварталах и годах «мес год» от метки начала или конца периода искажает края срока.
- L4: строка без даты в хвосте («итого») считается периодом плана.
- Окна бэктеста (слайд 6/HTML) в формате «ГГГГ-ММ-ДД – ГГГГ-ММ-ДД» не трогались по решению оркестратора.
- Термин словаря «Weighted ROI» (`strings_ru.json:288`) остался англоязычным.

## Непроверено (доработка)
- Отчёт из нового exe через программу не рендерился. Проверено тестами на исходниках, `cmp` бандла и `/health`.
- Раскладка слайда декомпозиции глазами не смотрелась: подпись периода в подзаголовке и строке «Источник» стала на 4 символа короче (23 → 19).

---

# Доработка 2 (повторный аудит: L6, L7). Последний круг, дальше выпуск заморожен

## Что изменено
- **L7** – `aurora_html/strings_ru.json:288`: термин глоссария «Weighted ROI» → «Средневзвешенный ROI». `term` нигде не служит ключом или якорем: единственный потребитель – вывод в `render_glossary` (`sections.py:2376`, `escape(t["term"])`). Поиск «Weighted ROI» по `.py/.json/.js/.html/.svelte` (движок, `src/`, `tools/`) других опор не находит. Глоссарий выводит новое имя (тест ниже).
- **L6** – вопрос SCQAR «ВОПРОС» во всех трёх ветках KPI:
  - `strings_ru.json:101` (старый KPI): «…поднять ROAS не снижая awareness?» → «…поднять ROAS, не снижая охвата знания?»;
  - `sections.py:691` (effectiveness): «…повысить долю эффекта, не снижая охвата знания?»;
  - `sections.py:693` (count): «…снизить стоимость единицы (CPU), не снижая охвата знания?».

## Тесты (+4) и мутации
- `test_question_says_awareness_in_russian_in_every_kpi_branch` – параметризован по трём веткам (старый KPI, effectiveness, count): нет «awareness», есть своя фраза с запятой и «не снижая охвата знания?».
- `test_glossary_names_weighted_roi_in_russian` – в `render_glossary` нет «Weighted ROI», есть `<div class="glossary-term-name">Средневзвешенный ROI</div>`.
- В `tests/test_scqar_period_label_matches_coverage.py` добавлен `import pytest` (для параметризации).
- **МУТАЦИИ:** D – шаблон вопроса обратно → ветка старого KPI КРАСНАЯ; E – `sections.py:691` обратно → ветка effectiveness КРАСНАЯ; F – `sections.py:693` обратно → ветка count КРАСНАЯ; G – `term` обратно → тест глоссария КРАСНЫЙ. Откат из копий, `cmp` идентично, 52/0.

## Прогоны доработки 2
| Прогон | Было | Стало | Код |
|---|---|---|---|
| pytest движка `-n 4` (свободно 7,67 ГБ) | 1795/0 | **1799 passed / 0 failed / 2 skipped** | 0 |
| tools: все 10 файлов, читающих `strings_ru`/`aurora_html`/`aurora_pptx` | – | 149 passed / 1 skipped | 0 |
| `verify_aurora_html_brand.py` | – | 34/34 | 0 |
| три линтера | – | OK | 0 |

Журнал: `Projects/_pytest_s53_datefix_audit2.log`, дампов нехватки памяти нет. Полный pytest tools в этом круге не гоняла: изменились только клиентские строки HTML, а все файлы tools, которые их читают, прогнаны.

## Пересборка движка (третья, итоговая)
- Перед сборкой свободно 8,44 ГБ, процессов движка нет.
- `Projects/_build_sidecar_s53c.log`, RC=0: Build SUCCESS, смоук validate CSV/XLSX ok, `[OK] Freshness verified`.
- Версия **2.5.6.0**, exe от 27.09 20:37:03, SHA256 **`CF9DB744A0772027768F843E3C80063DBA0AA2C519A55A308ED179C1D5E1D9B1`**. Заменяет `F82A4A75…` (вторая сборка) и `819DA563…` (первая).
- `cmp` бандла `_internal/` с исходниками: `strings_ru.json`, `builder.py`, `sections.py`, `narrative_adapter.py` совпадают.
- Проба на :8798: `/health` 200 за 10,5 с, процесс снят.
- `src/tokens.generated.css` сборка тронула только строкой `Last build` – вернула через `git checkout`.

## Итоговое дерево
```
 sidecar/econometrica/aurora_html/sections.py       |  8 +-
 sidecar/econometrica/aurora_html/strings_ru.json   |  6 +-
 sidecar/econometrica/aurora_pptx/builder.py        |  6 +-
 sidecar/econometrica/engines/narrative_adapter.py  | 31 +++++++-
 .../tests/test_planning_section_reports.py         | 91 ++++++++++++++++++++++
 .../test_scqar_period_label_matches_coverage.py    | 36 +++++++++
 6 files changed, 168 insertions(+), 10 deletions(-)
```

## Долг 2.5.7 (дополнено)
- Остальная латиница в клиентских строках `strings_ru.json` (по аудиту – кандидаты, вывод клиенту не проверен): `brand/tagline` «Marketing Mix Modeling · Quarterly Report», вердикты `Scale/Hold/Watch/Reduce/Cut`, `source_notes/posterior` «posterior means reported», «Бюджет vs эффект», «Report ID». Не трогала.
- Термин глоссария «Weighted ROI» закрыт (L7), пункт из прежнего списка долга снимается.

## Непроверено
- Отчёт из итогового exe через программу не рендерился, слайды и HTML глазами не смотрела. Правку подтверждают тесты на исходниках, `cmp` бандла и `/health`.
