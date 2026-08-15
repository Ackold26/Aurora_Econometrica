# check_py_consumers.py — счётчик потребителей общих Python-пакетов

Пара инструменту `aurora-meta/tools/check_crate_consumers.py` (тот же день,
тот же вопрос про общий слой aurora-platform-core, только для Python вместо
Cargo). Файл: `D:\Docs\Aurora_Ai\aurora-meta\tools\check_py_consumers.py`.

## Что делает и как запустить

```
python D:\Docs\Aurora_Ai\aurora-meta\tools\check_py_consumers.py
```

Читает только: общий репозиторий `aurora-platform-core` (список Python-пакетов
+ давность их правки по git) и девять деревьев продуктов в `Dev\` (потребители).
Ничего не пишет, не коммитит, не переключает ветки. Возврат 0 — нарушений нет;
1 — есть хотя бы одно нарушение (пакет с нулём потребителей дольше 30 дней).

## Живой прогон — полный вывод (24 с)

```
Пакет                  Потребителей   Манифест          Статус
--------------------------------------------------------------
aurora_common          0              есть              КРАСНЫЙ (1)
aurora_design          0              есть              КРАСНЫЙ (1)
aurora_engines         0              есть              КРАСНЫЙ (1)
aurora_inference       0              есть              КРАСНЫЙ (1)
aurora_observability   0              есть              КРАСНЫЙ (1)
aurora_rag             3              НЕТ (по каталогу) зелёный
aurora_report_lint     2              есть              зелёный
aurora_reporting       0              есть              зелёный
aurora_schema_registry 0              есть              КРАСНЫЙ (1)
aurora_studio          0              есть              КРАСНЫЙ (1)
aurora_verifier        0              есть              КРАСНЫЙ (1)
aurora_workflow        0              есть              КРАСНЫЙ (1)

Потребители по пакетам:

[aurora-common]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_common
    потребителей нет

[aurora-design]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_design
    потребителей нет

[aurora-engines]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_engines
    потребителей нет

[aurora-inference]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_inference
    потребителей нет

[aurora-observability]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_observability
    потребителей нет

[aurora_rag (манифеста нет, имя взято из каталога)]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_rag
    Aurora_Creative_Hub:
        [импорт] brand-hub\rag-server\embedder.py:7 — from aurora_rag.adapters.brandhub import Embedder  # noqa: F401
        [импорт] brand-hub\rag-server\vector_store.py:10 — from aurora_rag.adapters.brandhub import VectorStore  # noqa: F401
    Aurora_Econometrica_thinwt:
        [импорт] brand-hub\rag-server\embedder.py:7 — from aurora_rag.adapters.brandhub import Embedder  # noqa: F401
        [импорт] brand-hub\rag-server\vector_store.py:10 — from aurora_rag.adapters.brandhub import VectorStore  # noqa: F401
    ROSST_AI_DocMaster:
        [импорт] brand-hub\rag-server\embedder.py:7 — from aurora_rag.adapters.brandhub import Embedder  # noqa: F401
        [импорт] brand-hub\rag-server\vector_store.py:10 — from aurora_rag.adapters.brandhub import VectorStore  # noqa: F401

[aurora-report-lint]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_report_lint
    Aurora_Oracle:
        [импорт] tools\report\tests\lang_lint_gate.py:324 — from aurora_report_lint.core import LintFinding, LintResult, discover_pptx, lint_pptx
        [импорт] tools\report\tests\lang_lint_gate.py:325 — from aurora_report_lint.report import exit_code, format_report
        [импорт] tools\report\tests\lang_lint_gate.py:326 — from aurora_report_lint.rules import LintConfig
    ROSST_AI_Media:
        [импорт] tools\media-analyst\tests\lint_report_language.py:73 — from aurora_report_lint.core import lint_pptx as _shared_lint_pptx
        [импорт] tools\media-analyst\tests\lint_report_language.py:74 — from aurora_report_lint.report import format_result as _shared_format_result
        [импорт] tools\media-analyst\tests\lint_report_language.py:75 — from aurora_report_lint.rules import LintConfig as _SharedLintConfig

[aurora-reporting]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_reporting
    потребителей нет (каталог правили 21 дн. назад — ещё не просрочен)

[aurora-schema-registry]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_schema_registry
    потребителей нет

[aurora-studio]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_studio
    потребителей нет

[aurora-verifier]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_verifier
    потребителей нет

[aurora-workflow]  D:\Docs\Aurora_Ai\aurora-platform-core\aurora_workflow
    потребителей нет

НАРУШЕНИЯ (9):
  [aurora_common] ноль потребителей, последняя правка каталога 2026-06-07 — 68 дн. назад (порог 30)
  [aurora_design] ноль потребителей, последняя правка каталога 2026-06-15 — 61 дн. назад (порог 30)
  [aurora_engines] ноль потребителей, последняя правка каталога 2026-06-07 — 68 дн. назад (порог 30)
  [aurora_inference] ноль потребителей, последняя правка каталога 2026-06-07 — 68 дн. назад (порог 30)
  [aurora_observability] ноль потребителей, последняя правка каталога 2026-06-07 — 68 дн. назад (порог 30)
  [aurora_schema_registry] ноль потребителей, последняя правка каталога 2026-06-07 — 68 дн. назад (порог 30)
  [aurora_studio] ноль потребителей, последняя правка каталога 2026-06-07 — 68 дн. назад (порог 30)
  [aurora_verifier] ноль потребителей, последняя правка каталога 2026-06-07 — 68 дн. назад (порог 30)
  [aurora_workflow] ноль потребителей, последняя правка каталога 2026-06-14 — 62 дн. назад (порог 30)

Охват: пакетов найдено — 12 (без манифеста — 1), исключено — 0, с нарушениями — 9, нарушений всего — 9.
```

Код возврата: `1`.

## Расхождение с ручной проверкой тимлида

Ручная проверка решила «потребителей нет ни у одного». Машинный счёт это
подтверждает для **9 из 12** пакетов, но **не для двух** — и это расхождение
ценнее совпадения, поэтому фиксирую отдельно:

- **`aurora_rag` — 3 потребителя** (Aurora_Econometrica_thinwt, Aurora_Creative_Hub,
  ROSST_AI_DocMaster), не 0.
- **`aurora_report_lint` — 2 потребителя** (Aurora_Oracle, ROSST_AI_Media), не 0.

Оба случая не оставляют следа ни в одном `requirements.txt` — ни разу, ни в
одном из 9 деревьев ни один манифест не упоминает `aurora_*`. Оба обнаружены
исключительно фактическим импортом (см. ниже, «Что за штука `aurora_rag`»
и раздел про `aurora_report_lint`). Если бы инструмент проверял только
манифесты, как просилось изначально в самом узком прочтении задачи, он
доложил бы ложные «0 потребителей» ровно там, где живая зависимость есть, —
это и есть причина, по которой в задаче отдельно подчёркнуто, что импорт
«часто единственная его форма».

Дополнительно: пакетов с манифестом оказалось **11, а не 8** — кроме
перечисленных в задаче (`aurora_common`, `aurora_reporting`, `aurora_inference`,
`aurora_design`, `aurora_engines`, `aurora_observability`, `aurora_report_lint`)
в `[tool.uv.workspace].members` корневого `pyproject.toml` есть ещё
`aurora_schema_registry`, `aurora_studio`, `aurora_workflow`. Все три вошли
в обход дискаверинга и в таблицу (все три — 0 потребителей, все три просрочены).

## Что за штука `aurora_rag`

На текущей рабочей ветке `aurora-platform-core` (`feat/reg-pay-cabinets-jwt`)
каталог `aurora_rag/` физически почти пуст: ни `pyproject.toml`, ни исходников
`.py` — только `__pycache__/*.pyc` и `.pytest_cache/` (осадок прошлого запуска
pytest на другой ветке). `git status`/`git ls-tree HEAD` по нему пусты — каталог
untracked на этой ветке. Настоящее содержимое (`pyproject.toml`, `src/aurora_rag`,
`tests/`) есть на ветках `feat/rag-core-extraction` и `feat/regulatory-rag-node-b`
(`git log --all` это подтверждает: 12 коммитов с 21.06 по 03.08.2026, последний —
`7771028 fix: audit findings — снос категории при пустой выборке…`, 03.08.2026).
Это тот же паттерн, что описан в докстринге `check_crate_consumers.py` про
`aurora_gateway` — общий репозиторий держит 11 рабочих копий, и «правды» на
текущей ветке достаточно, чтобы решить «пакета нет», хотя по всем веткам он
активно развивается.

Способ распространения — **не pip**, а «canonical + sync» (ADR-027, вариант G,
тот же паттерн, что у `port_discovery` для 10 продуктов):
`aurora_rag/scripts/sync_to_products.py` физически **копирует** канон
(`aurora_rag/src/aurora_rag`) в `{продукт}/brand-hub/rag-server/aurora_rag/`
и кладёт рядом маркер `_GENERATED_aurora_rag.txt` («не редактируй здесь, правь
канон и перекатывай sync-скрипт»). Копия физически присутствует в 3 деревьях
из 9 (Econometrica_thinwt, Creative_Hub, DocMaster) — но сама по себе копия ещё
не значит «потребление»: в `Aurora_Econometrica_thinwt` рядом с ней лежат старые
`embedder.py`/`vector_store.py`/`brand_manager.py` — при проверке выяснилось,
что после перехода на общий склад именно `embedder.py` и `vector_store.py`
переписаны в GENERATED-shim-файлы, которые реально импортируют
`aurora_rag.adapters.brandhub` (`from aurora_rag.adapters.brandhub import
Embedder/VectorStore`) — это и есть настоящий потребитель. У остальных шести
продуктовых деревьев либо нет `brand-hub` вовсе (`Aurora_Oracle`,
`Aurora_PR_Master`, `Aurora_Parser`), либо `brand-hub/rag-server` есть, но
`aurora_rag/` рядом не синкан (`ROSST_AI_Legal`, `AI_APP_AGENCY`) — там своя
старая независимая реализация RAG, общий склад ей не подключён.

Инструмент детектирует это ровно тем же общим механизмом, что и любой другой
импорт-потребитель (обход `.py`-файлов + regex на `import`/`from`), без
специального кода под этот конкретный пакет — обнаружение сработало «само»,
потому что shim-файлы физически содержат буквальный `from aurora_rag...`.
Единственное специальное решение — **исключение self-copy**: при поиске
потребителей `aurora_rag` инструмент не заходит внутрь каталогов с именем,
точно совпадающим с `aurora_rag` (сама скопированная копия канона содержит
собственные внутренние импорты `aurora_rag.*` — это не «продукт потребляет
пакет», это пакет ссылается сам на себя). Без этого исключения счётчик
потребителей был бы завышен «самоимпортом» копии — то есть именно тот риск,
из-за которого сосед один раз посчитал Creative Hub дважды.

## Что за штука `aurora_report_lint`

В отличие от `aurora_rag`, у `aurora_report_lint` полноценный `pyproject.toml`
и он честно значится в `[tool.uv.workspace].members`. Способ распространения —
третий, отличный и от pip-зависимости, и от copy-with-shim: **динамический
sys.path-импорт по относительному пути**. Тестовый языковой гейт продукта сам
ищет общий склад (`aurora-platform-core/aurora_report_lint/src`) рядом на диске
или через переменную окружения `AURORA_PLATFORM_CORE`, и если находит —
подключает и импортирует (`from aurora_report_lint.core import lint_pptx`),
если не находит — печатает `[SKIP]` и не падает. Это by design, прямо
задокументировано в `description` пакета: «dependency-light… so any product's
own bundled or system Python can invoke it standalone via CLI, without
installing the full platform-core workspace» — то есть намеренно устроено так,
чтобы работать и без общего репозитория на диске (dev-time-only гейт, не
шипуется клиенту). Потребители найдены в `Aurora_Oracle` (`tools/report/tests/
lang_lint_gate.py`) и `ROSST_AI_Media` (`tools/media-analyst/tests/
lint_report_language.py`) — оба вызывают одну и ту же функцию `lint_pptx` из
общего склада.

## Где искал потребителей и что исключил из обхода

Манифесты (`requirements*.txt` где угодно в дереве продукта, `pyproject.toml`,
`setup.py`, `setup.cfg` продукта) + фактические импорты во всех `.py`-файлах
(`import module`, `from module import …`, включая форму с точкой
`from module.sub import …`) — оба пути обходят одно и то же дерево с одним и
тем же списком исключений (`SKIP_DIR_NAMES` в коде):

```
target, node_modules, .git, __pycache__, .pytest_cache, .svelte-kit,
dist, build, site-packages, .venv, venv, env, _internal,
.mypy_cache, .ruff_cache, .hypothesis, .claude
```

Почему именно эти: `_internal`/`dist` — PyInstaller-сборка (в `sidecar/
econometrica/` это 1.9 ГБ, замерено `du`); `site-packages` — покрывает и
`sidecar/*/python/Lib/site-packages`, и `src-tauri/python/Lib/site-packages`,
и `target/{debug,release}/python/Lib/site-packages` одним именем, без
привязки к конкретному относительному пути; `.venv`/`venv`/`env` — рабочие
окружения инструментов; `target`/`node_modules`/`.git`/`build` — сборочные
артефакты, как и у соседа; `.claude` — рабочие копии параллельных агентов
(`.claude/worktrees/agent-…` — нашёл ровно такую внутри `ROSST_AI_Media` при
разведке, полное дублирование дерева продукта; без исключения — задвоенный
счёт потребителя).

Замер без исключений: `find` по всем 9 деревьям без прунинга — **1m23s**
(тимлид предупреждала о ровно этой проблеме). С прунингом — поиск манифестов
0.6 с, поиск импортов 1.3 с. Полный прогон инструмента (12 пакетов × 9
деревьев × два вида поиска, плюс 12 вызовов `git log`) — **21–24 с**, в разы
внутри двухминутного бюджета.

## Доказательство мутацией

Фикстура — `C:\Users\ackol\AppData\Local\Temp\claude\D--Docs-Aurora-Ai\
e7778e7e-2989-47a4-821f-98743e7044b7\scratchpad\fixture_py\`, реальные деревья
не тронуты. Структура:

- `core_repo/` — отдельный git-репозиторий с двумя пакетами:
  `orphan_pkg` (коммит `2026-05-01`, 106 дней до текущей даты) и `used_pkg`
  (коммит `2026-08-14`).
- `products/consumer_product/` — `requirements.txt` без единого упоминания
  `used_pkg`/`orphan_pkg` (фиктивная запись `requests>=2.31.0`, чтобы файл не
  был пустым) и `app/main.py` с `from used_pkg import helper` — потребление
  ТОЛЬКО импортом, ни в одном манифесте.

Прогон (`run_all(core_repo, {"consumer_product": …})`, реальные `CORE_REPO`/
`PRODUCTS` не подставлялись):

```
Пакет      Потребителей   Манифест Статус
-----------------------------------------
orphan_pkg 0              есть     КРАСНЫЙ (1)
used_pkg   1              есть     зелёный

Потребители по пакетам:

[orphan-pkg]  …\fixture_py\core_repo\orphan_pkg
    потребителей нет

[used-pkg]  …\fixture_py\core_repo\used_pkg
    consumer_product:
        [импорт] app\main.py:4 — from used_pkg import helper  # noqa: F401

НАРУШЕНИЯ (1):
  [orphan_pkg] ноль потребителей, последняя правка каталога 2026-05-01 — 106 дн. назад (порог 30)

Охват: пакетов найдено — 2 (без манифеста — 0), исключено — 0, с нарушениями — 1, нарушений всего — 1.

КОД ВОЗВРАТА (если бы main()): 1
```

Оба случая подтвердились: пакет-сирота со старой датой покраснел с внятным
сообщением о давности; пакет, потребляемый только импортом (без единой строки
в манифесте), позеленел и назвал точного потребителя с файлом, номером строки
и буквальной уликой.

## Список исключений (`EXCLUDED_PACKAGES`)

Пуст. У Cargo-инструмента в исключениях два крейта, каждый заведомо, по
конструкции, не может иметь потребителя через проверяемый механизм (WASM-крейт
для JS-потребления, cookiecutter-плейсхолдер). Среди 12 найденных Python-пакетов
такого не нашлось: даже `aurora_verifier` (Python-версия — «reference»,
продакшн — Rust WASM, по описанию) в принципе может быть потреблён и через
импорт, и через `[project.scripts]` CLI — структура кода (словарь с объяснением
на каждую строку, как у соседа) готова принять исключение, если оно появится,
без изменения логики.

Отдельно решено НЕ включать в счёт как «пакет» сам корневой `pyproject.toml`
репозитория (`name = "aurora-platform-core"`) — discovery ищет манифесты через
`repo.glob("*/pyproject.toml")`, то есть на один уровень ниже корня, поэтому
сам workspace-root физически не подхватывается: это explicit-дизайн, не
недосмотр.

## Чего инструмент не ловит

- **CLI-вызов через subprocess.** Четыре пакета (`aurora_report_lint`,
  `aurora_schema_registry`, `aurora_verifier`, `aurora_workflow`) объявляют
  `[project.scripts]` — если продукт вызывает их как отдельную команду
  (`subprocess.run(["aurora-workflow", …])`), а не через `import`, инструмент
  этого не увидит: он ищет только `import`/`from … import`, не текст команды
  в `.bat`/PowerShell-скриптах или в `subprocess.run(...)`.
- **`sys.path.insert`/`importlib` без последующего `from module import`
  на отдельной строке.** Regex ловит форму `import X` / `from X import Y`
  (в т.ч. с точкой), но не поймает динамическую строку вида
  `importlib.import_module("aurora_" + name)` — такого в разведке не
  встретилось, но конструктивно возможно.
- **Потребление внутри самого общего репозитория** (например, если бы
  `aurora_engines` импортировал `aurora_inference`) — инструмент смотрит
  только в 9 деревьев продуктов, не в сам `aurora-platform-core`; кросс-
  зависимости внутри общего слоя вне периметра задачи и вне периметра этого
  отчёта.
- **`setup.py`/`setup.cfg`/`pyproject.toml`-путь не проверен вживую.** Ни в
  одном из 9 продуктовых деревьев такого файла не нашлось (только
  `requirements*.txt`) — код для этих трёх форм написан и синтаксически
  прогнан (не падает на реальном дереве, где таких файлов нет), но
  собственного мутационного случая под них в фикстуре нет; фикстура покрывает
  вариант «манифест без искомого имени» (`consumer_product/requirements.txt`)
  и вариант «искомое имя только в импорте», но не вариант «искомое имя реально
  найдено в `pyproject.toml`/`setup.py` продукта».
- **Копия без импорта не считается потреблением, и это может быть избыточно
  строго.** Если бы `sync_to_products.py` синканул `aurora_rag` в продукт, но
  ни один файл продукта не импортировал бы его ни строкой — инструмент
  корректно доложил бы «0 потребителей» для такого продукта, хотя физическая
  копия и заняла место на диске. Это осознанное решение (копия — не
  потребление, потребление — использование), но стоит держать в уме при
  чтении будущих отчётов: «синкан» ≠ «потребляется».
- **Дрейф версий / давность копии относительно канона** — в отличие от
  Cargo-версии с её правилами 2/3 (дрейф тегов, отставание потребителя),
  здесь этого нет вовсе: у Python-пакетов тегов нет, а copy-with-shim
  синкается вручную запуском `sync_to_products.py` без версионирования —
  сравнить «копия устарела относительно канона» негде, разве что через
  побайтовое сравнение файлов, что за рамки задачи.

## Границы (соблюдены)

Только чтение чужих деревьев, ни одной правки ни в продуктах, ни в общем
репозитории. Ветки нигде не переключались. В `aurora-meta` добавлен в индекс
поимённо только `tools/check_py_consumers.py` (`git add`, без коммита и без
пуша) — остальные незакоммиченные изменения в рабочей копии `aurora-meta`
(`INBOX_TO_MN_GIT_FALLBACK.md`, `NODE_A_MIGRATION_CHECKLIST.md`,
`tools/aurora-admin.html`, `LETTER_oracle_cpd77_answer_and_consent_revision_
2026-08-15.md`, `patches/econ_canon_uncommitted_2026-08-09.patch`) — чужие,
не мои, не тронуты. Единственный побочный артефакт моих действий —
`tools/__pycache__/`, созданный интерпретатором при импорте модуля для
мутационного теста — удалён в корзину сразу после обнаружения.
