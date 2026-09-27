# PULSE s44 — гигиена сборки: Б-53 (следы тестов) + Б-46 (dist/ дубль)

## Задача своими словами
Широкий шаблон ресурсов в `tauri.conf.json` (`../sidecar/econometrica/**/*`) забирает в поставку
всё подряд из каталога sidecar: и собственный дубль `dist/` вывода PyInstaller (Б-46, 926 МБ), и
следы прогонов тестов — `.hypothesis`, `.pytest_cache`, `__pycache__` (Б-53, +7,5 МБ в 2.5.2).
Оба — один корень: включение по маске «всё из каталога» вместо явного списка. Нужно сузить/явно
исключить, поставить сторожа на класс (падает на любом новом мусоре в собранном пакете) и доказать
сторожа мутацией. Установщик НЕ собирать — только конфигурация, spec PyInstaller, скрипты, тесты.

## План
1. Найти реальный артефакт: где физически лежат `dist/`, `.hypothesis`, `__pycache__` относительно
   `sidecar/econometrica/`, что из этого попадает в `_internal/` собранного PyInstaller-пакета.
2. Прочитать `src-tauri/tauri.conf.json` (resources), `sidecar/build_sidecar.py`, `.spec`-файл.
3. Починить: явный список ресурсов или надёжные exclude в конфигурации/spec/скриптах сборки.
4. Написать сторожа (тест/скрипт), доказать мутацией: создать файл-пустышку класса «след теста» →
   красный с указанием файла → убрать → зелёный.
5. Дёшево проверить: конфиг, тесты движка, build_sidecar.py в режиме проверки (без полной сборки).
6. Отчитаться числами.

## Ход работы
- 00:07 (13.09) — старт. Прочитаны git 21d28ebe (Б-53) и backlog-запись Б-46. Пишу этот файл.
- 00:20 — факт измерен: `sidecar/econometrica/dist/` = 939 МБ (Б-46, дубль вывода PyInstaller,
  никогда не удалялся после синка `build_sidecar.py:392-404`). В синкнутом `_internal/` (то, что
  реально уезжает установщику) — 170 каталогов `__pycache__` стороннего кода (arviz/jax/pymc/
  pytensor/linearmodels/numpyro/xarray), доставшихся вместе с `--collect-all`/`--add-data` из
  site-packages сборочной машины. Не трогаю (чужой артефакт, снимется следующей сборкой).
- 00:35 — корень найден: `build_sidecar.py` вызывает PyInstaller через `--add-data ROOT/engines:engines`
  (и так же `charts`, `utils`, `aurora_pptx`, `aurora_html`) — копирует каталог ЦЕЛИКОМ, включая
  любой `__pycache__`, если он там лежал на момент сборки. `tauri.conf.json:39` тем временем берёт
  ВЕСЬ `sidecar/econometrica/**/*` одним шаблоном — это и есть общий корень с Б-46 (`dist/` туда же
  попадает). Рантайм (`src-tauri/src/econ_sidecar.rs::resolve_bundled_exe`) резолвит РОВНО
  `sidecar/econometrica/econometrica-sidecar.exe` (+ соседний `_internal/` через PyInstaller
  onedir-конвенцию, `sys._MEIPASS`, `server.py:154`); dev-режим (`spawn_python_dev`) читает исходники
  напрямую из репо, минуя ресурсы Tauri вообще. Значит клиентской поставке НИЧЕГО, кроме exe и
  `_internal/`, не нужно.
- 00:45 — правка 1: `src-tauri/tauri.conf.json` — заменён `"../sidecar/econometrica/**/*"` на
  явную пару `"../sidecar/econometrica/econometrica-sidecar.exe"` + `"../sidecar/econometrica/_internal/"`.
  Убито мутацией (см. ниже) и восстановлено.
- 00:55 — правка 2: `sidecar/econometrica/build_sidecar.py` — добавлены `TEST_RESIDUE_DIR_NAMES`
  (`__pycache__`, `.hypothesis`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`) и функция
  `purge_test_residue()` — снимает эти каталоги из СОБРАННОГО пакета (`dist/econometrica-sidecar/`)
  ДО синка в `sidecar/econometrica/`, вторая линия обороны на случай следа внутри `_internal/`.
  Вызов вставлен в `main()` сразу после успешной сборки, до проверки `exe_path`.
- 01:05 — сторож: новый файл `sidecar/econometrica/tests/test_bundle_resource_hygiene.py` (5 тестов):
  1) `test_tauri_resources_do_not_use_wide_sidecar_glob` — статический разбор `tauri.conf.json`,
     падает на широком шаблоне; 2-3) `purge_test_residue` мутация (кладём `.hypothesis`/
     `.pytest_cache`/`__pycache__` вперемешку с настоящим кодом → RED → чистка → GREEN, настоящий
     код цел); 4) отрицательный контроль (чистое дерево — no-op); 5) вложенный след внутри чужого
     каталога — не роняет обход.
  `python -m py_compile build_sidecar.py` — ОК. `pytest .../test_bundle_resource_hygiene.py` — 4/4
  зелёных (5-й тест написан позже, тоже зелёный при финальном прогоне).
- 01:10 — мутация на РЕАЛЬНОМ конфиге: временно вернула `"../sidecar/econometrica/**/*"` в
  `tauri.conf.json` (через .bak-копию) → тест `test_tauri_resources_do_not_use_wide_sidecar_glob`
  упал (RED, текст ассерта называет находку) → восстановила правку → тест зелёный (GREEN).
- 01:15 — прогон движка: `python -m pytest sidecar/econometrica/tests -n auto -m "not requires_real_data and not slow"`
  (та же команда, что в CI `.github/workflows/ci.yml:108`) — 1474 passed, 10 failed, 2 skipped.
  Все 10 падений — в `test_forecast_report.py`, `KeyError: 'strings'` внутри `aurora_html/sections.py`.
  `git status` подтверждает: `aurora_html/sections.py`, `builder.py`, `strings_ru.json` сейчас
  меняют ДРУГИЕ агенты сессии (мне эта зона запрещена) — падения не мои, до и после моих двух правок
  дерево `aurora_html/**` в работе параллельно. Мои файлы (`build_sidecar.py`, `tauri.conf.json`,
  новый тест) — единственные, что я меняла (`git diff --stat`: +43/-1 в двух файлах).
- 01:20 — отчёт владельцу, сессия закрывается.

## ИТОГ (отчёт владельцу)

**Что уезжало.** `tauri.conf.json` ресурс `"../sidecar/econometrica/**/*"` рекурсивно забирал ВЕСЬ
каталог `sidecar/econometrica/`: 1) `dist/econometrica-sidecar/` — дубль вывода PyInstaller,
**939 МБ** на диске сейчас (Б-46, никогда не чистился после копирования в синк); 2) следы прогонов
тестов — `__pycache__` рядом с исходниками (`engines/`, `charts/`, `utils/`, `aurora_pptx/`,
`aurora_html/`, `tests/`, `optimize/`, `tools/`) и `.hypothesis`/`.pytest_cache`, если они лежали
там на момент сборки (Б-53; коммит 21d28ebe зафиксировал факт: +7,5 МБ в 2.5.2 от 1368 файлов
`.hypothesis` + тысяч `__pycache__`). Отдельно, ВНУТРИ уже собранного `_internal/`, сейчас лежат
**170 каталогов `__pycache__`** сторонних пакетов (arviz/jax/pymc/pytensor/linearmodels/numpyro/
xarray) — их туда приносит PyInstaller `--collect-all`/`--add-data` из site-packages сборочной
машины; это та же болезнь глубже по стеку.

**Механизм.** Два уровня: (а) Tauri резолвит ресурсы по шаблону файловой системы — широкий `**/*`
не различает «нужное» и «мусор рядом»; (б) `build_sidecar.py` вызывает PyInstaller с
`--add-data ROOT/<dir>:<dir>` для пяти каталогов — это копирует каталог-источник ЦЕЛИКОМ, как есть,
включая любой `__pycache__`, если он там оказался к моменту сборки (пример: пробный прогон pytest
импортирует `engines/channel_action.py` → рядом ложится `__pycache__` → следующая сборка утаскивает
его в `_internal/engines/__pycache__`).

**Что изменено.**
1. `src-tauri/tauri.conf.json:37-43` — ресурс sidecar сужен с одного широкого шаблона до явной пары:
   `"../sidecar/econometrica/econometrica-sidecar.exe"` + `"../sidecar/econometrica/_internal/"`.
   Доказано измерением, что рантайму больше ничего не нужно: `src-tauri/src/econ_sidecar.rs:466-471`
   (`resolve_bundled_exe`) резолвит ровно `sidecar/econometrica/econometrica-sidecar.exe`; PyInstaller
   onedir кладёт зависимости в соседний `_internal/`, который сама программа находит через
   `sys._MEIPASS` (`server.py:154`). Dev-режим (`spawn_python_dev`, `econ_sidecar.rs:502-538`) вообще
   не использует Tauri-ресурсы — запускает `python server.py` из исходников репозитория напрямую.
   Это одной правкой закрывает класс: `dist/` (Б-46), `tests/`, `engines/__pycache__` и любой другой
   мусор верхнего уровня — они физически перестают попадать в состав ресурсов, что бы ни лежало
   в каталоге на момент сборки.
2. `sidecar/econometrica/build_sidecar.py` — добавлены `TEST_RESIDUE_DIR_NAMES = {'__pycache__',
   '.hypothesis', '.pytest_cache', '.mypy_cache', '.ruff_cache'}` и `purge_test_residue(dist_output)`:
   рекурсивно снимает эти каталоги из `dist/econometrica-sidecar/` СРАЗУ после успешной сборки
   PyInstaller и ДО копирования в `sidecar/econometrica/` (строка вызова — в `main()`, между очисткой
   `build_tmp` и проверкой `exe_path`). Это вторая линия обороны: закрывает случай, когда след
   оказался ВНУТРИ `_internal/` (третьи пакеты, `--collect-all`), где явный список ресурсов Tauri
   его уже не отличит от нужного файла.

**Чем доказано, что больше не попадает.**
- Статический тест `test_tauri_resources_do_not_use_wide_sidecar_glob` разбирает реальный
  `tauri.conf.json` и падает на любом шаблоне с `**` или на голом `sidecar/econometrica` — прогнан
  и зелёный на текущем файле.
- Мутация на РЕАЛЬНОМ файле: вернула широкий шаблон → тест красный с указанием находки
  (`['../sidecar/econometrica/**/*']`) → восстановила правку → тест зелёный. Числа: 1 файл изменён
  туда-обратно, 1 assert сработал в обе стороны.
- `purge_test_residue`: три теста на `tmp_path` (не трогают реальное дерево) — мутация 5 подставных
  каталогов-следов вперемешку с настоящим `.py`-модулем и exe → RED (следы на диске) → GREEN после
  вызова (все 5 сняты, модуль и exe целы, `len(removed) == 5`); отрицательный контроль (чистое
  дерево → `removed == []`, ничего не тронуто); вложенный след (`_internal/a/b/c/__pycache__` рядом
  с `module.py`, который не должен пострадать) — снят один, `module.py` цел.
- Полный прогон: `python -m py_compile build_sidecar.py` — синтаксис ОК; импорт модуля не запускает
  PyInstaller (`if __name__ == '__main__':` на месте, проверено).

**Что осталось непроверенным без полной сборки.**
- Реальный прогон `build_sidecar.py` (PyInstaller, ~10+ минут, MCMC-зависимости) НЕ запускался —
  прямой запрет сессии. Значит `purge_test_residue()` проверена мутацией на синтетическом дереве,
  но не на настоящем выводе PyInstaller живьём — теоретическая брешь: если PyInstaller когда-нибудь
  положит след с ИНЫМ именем каталога (не из пяти в `TEST_RESIDUE_DIR_NAMES`), функция его не поймает.
  Список закрывает известный класс, не все мыслимые имена кэшей.
- `npm run tauri build`/`tauri:build:thin` не запускался — сузился ли реально итоговый `.exe`
  установщика и совпадает ли контрольная сумма при повторной сборке (приёмка, которую сама запись
  Б-53 требует: «собрать дважды подряд с прогоном тестов между сборками — сумма обязана совпасть») —
  проверит следующая сборка владельца.
- Текущий `sidecar/econometrica/_internal/` и `dist/` на диске СЕЙЧАС всё ещё грязные (170 каталогов
  `__pycache__` в `_internal/`, 939 МБ в `dist/`) — НЕ чистила: это чужой артефакт прошлых сборок, не
  мой временный мусор (регламент правки). Новый `tauri.conf.json` уже не заберёт `dist/`, но
  `_internal/` со старыми `__pycache__` внутри уедет как есть, ПОКА не пересоберётся `build_sidecar.py`
  с новым `purge_test_residue()` — то есть до следующей реальной сборки эффект Б-53 для `_internal/`
  ещё не реализован физически, только в коде. Отметила — решение чистить руками сейчас или ждать
  пересборки за владельцем.
- Прогон полного набора тестов движка (`sidecar/econometrica/tests`, команда CI) дал 10 падений — все
  в `test_forecast_report.py` / `aurora_html/sections.py` (`KeyError: 'strings'`), это зона ДРУГИХ
  агентов сессии (`git status` подтверждает файлы `aurora_html/*.py`, `strings_ru.json` изменены не
  мной) — не связано с моей правкой, не чинила (не моя зона).
