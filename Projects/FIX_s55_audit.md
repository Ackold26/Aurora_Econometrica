# FIX s55 – правки находок внешнего аудита 2.5.7 (`AUDIT_s55_257.md`)

Дата: 2026-09-28, 09:52–10:18. Дерево `Aurora_Econometrica_thinwt`, `master`, HEAD `3e5667f3`. Записей git не делала,
программу не собирала. Маячок – `scratchpad/PULSE_s55_fixaudit.md`. Стенды и пробы – `scratchpad/fixaudit/`.

## Итог

| ID | Статус | Где |
|---|---|---|
| H-1 | исправлено | `engines/planning.py:122-130` – третья база сверки «строки плана» |
| H-2 | исправлено | `engines/planning.py:141-147` – совпадение с суммой неотрицательного KPI – итог само по себе |
| M-1 | исправлено | `engines/planning.py:108-120` – итог только при наличии чисел в строке |
| M-2 | исправлено | `engines/planning.py:156-171, 195-198` (+ `validator.py:547-550`) – единый распознаватель колонок |
| M-3 | исправлено | `tools/test_installer_hooks.py` – разбор строки снятия + 2 исполняемые пробы |
| M-4 | исправлено | `src-tauri/installer_hooks.nsh:181-188` – проверка живости через CSV |
| M-5 | исправлено | `aurora_pptx/builder.py:2026-2041` – надпись вместо диаграммы без категорий |
| L-2 | исправлено (тривиально) | `engines/planning.py:91-93` – `Totals`/`Subtotal`/`Sum` |
| L-1, L-3, L-4 | долг, не трогала | см. §7 |

Дифф: `planning.py` +71/−25, `validator.py` +3/−9, `builder.py` +17/−5 (остальное – сдвиг отступа блока диаграммы, `git diff -w`),
`installer_hooks.nsh` +8/−1, `test_installer_hooks.py` +215, `test_total_row_s55.py` +125, новый `test_pptx_nonpositive_mroas.py`.

---

## 1. Детектор итога: H-1, H-2, M-1, M-2 (+L-2) – одна форма правила

**Правило после правки** (`_row_is_total`): итог – строка без даты, где есть хотя бы одно число (кроме колонки даты) И
(слово-признак в любой текстовой ячейке ИЛИ совпадение с суммами). Совпадение с суммами:
- базы сверки – все строки выше, только история (KPI заполнен) и **только план (KPI пуст)** (H-1);
- совпадение со столбцом, где выше меньше двух ненулевых значений, не считается (сумма одного значения равна ему самому –
  без этого база «план» с одной строкой давала бы ложные совпадения);
- **совпадение по KPI** (неотрицательный столбец, ≥2 ненулевых выше) – итог уже по одной ячейке (H-2, довод аудита:
  значение, равное сумме такого столбца, у настоящего периода невозможно); KPI со знаком (прибыль) – только по большинству;
- вне KPI – прежнее «≥2 совпадений и не меньше половины значений».

**M-2:** `find_trailing_total_rows` сам определяет колонки даты и KPI, если переданных нет в таблице (или `None`), – тем же
`detect_column_role_with_confidence`, что проверка данных (`_resolve_role_column`). Проверка данных теперь зовёт детектор с
`None, None` – у проверки и обоих обучений один распознаватель; `modeler.py`/`ols_modeler.py` не менялись (их
`config.get('date_column', 'date')` детектор перераспознаёт, если `'date'` в файле нет).

### Тесты (`sidecar/econometrica/tests/test_total_row_s55.py`, +12 тестов, файл 24 passed)
`test_plan_total_over_plan_rows_only_is_detected` (H-1 A, план 6 периодов без `None`),
`test_plan_total_with_zero_kpi_refused_by_training` (H-1 B, OLS – `TOTAL_ROW_IN_DATA`),
`test_kpi_sum_alone_is_a_total` (H-2, OLS отказ), `test_kpi_sum_with_averaged_other_columns_is_a_total` (H-2),
`test_single_non_kpi_sum_match_is_not_a_total` и `test_kpi_with_negative_values_needs_majority` (контроль ложных),
`test_note_row_with_total_word_but_no_numbers_is_not_a_total[summ|vsego|total_en]` (M-1: нет проблемы, OLS `ok`),
`test_training_detects_date_column_when_config_names_default` (M-2: «Дата» в файле, `date_column='date'` – оба обучения отказ),
`test_english_total_words_detected[Totals|Subtotal|Sum]` (L-2).

### МУТАЦИИ (в рабочем дереве, `scratchpad/fixaudit/mutate.py`: замена → pytest → возврат копии → сверка sha256)
sha256 `planning.py` с правкой – `ba8db6b6cf14aa4c…`, после каждой мутации совпадает.

| МУТАЦИЯ | Красные тесты |
|---|---|
| весь `planning.py` до правки | 16 failed (в т. ч. все новые; прежние тесты проверки данных – потому что `validator.py` теперь полагается на распознавание в детекторе) |
| H-1: убрать базу «план» | 2 – `test_plan_total_over_plan_rows_only_is_detected`, `test_plan_total_with_zero_kpi_refused_by_training` |
| H-2: убрать довод «совпал KPI» | 2 – `test_kpi_sum_alone_is_a_total`, `test_kpi_sum_with_averaged_other_columns_is_a_total` |
| H-2b: KPI без проверки знака | 1 – `test_kpi_with_negative_values_needs_majority` |
| M-1: слово без чисел снова итог | 3 – все `test_note_row_…` |
| M-2: без распознавания колонок | 8 – в т. ч. `test_training_detects_date_column_when_config_names_default` и тесты проверки данных |
| L-2: прежнее слово-признак | 3 – `test_english_total_words_detected[*]` |

### Пробы аудита L4 повторены (копии `probe_l4.py`/`probe_ols.py` в `scratchpad/fixaudit/l4/`, код – из дерева)
```
V1_all_sums / V2_sums_avg_idx / V3b_kpi_and_tv          detector=[(50,'sums')] status=error
V3_kpi_sum_only                                          detector=[(50,'sums')] status=error   (было [] warning)
V3c_5sums_7avgs                                          detector=[(50,'sums')] status=error   (было [] ok)
V5a_comment_summ / V5b_comment_vsego / V5d_comment_total_en  detector=[] total_issue_rows=[]   (было (50,'word') error)
V5c_comment_plain / V6_undated_period / V6b_zero_row     detector=[]
V8_word_Totals / Subtotal / Sum                          detector=[(50,'word')]                (было [])
V8_word_Grand_total / ВСЕГО / Итоги / Всего_за_период / TOTAL  detector=[(50,'word')]
V11_plan_total_plan_only       detector=[(138,'sums')] status=error plan_n=32 plan_last_dates=['2025-07-28','2025-08-04']  (было [] ok plan_n=33 [..,None])
V11b_plan_total_all_plancols   detector=[(138,'sums')] status=error plan_n=32                  (было [] warning plan_n=None)
V11c_plan_total_labeled        detector=[(138,'word')] plan_n=32
V12_plan_clean / V13_base_clean  detector=[] status=ok
V7_total_with_date [], V9_subtotal_middle []            – вне правила (L-3), как было
OLS: V13 ok n_obs=48 · V3 / V3c / V11 / V11b error TOTAL_ROW_IN_DATA (было ok n_obs 49/49/–/105)
     V5a_comment_summ ok n_obs=48 (было error) · V5c ok 48 · V12 ok 104 · V9 ok 49 (L-3)
M-2 (V14, колонка «Дата»): date_column=Дата → error TOTAL_ROW_IN_DATA; date_column=date → error TOTAL_ROW_IN_DATA (было ok)
```
`V5*` имеют `status=warning` при пустом списке проблем – так же, как контроль аудита `V5c` (статус от текстовой ячейки в
колонке даты, не от детектора).

### Ложные срабатывания: 38 реальных файлов дерева (`scratchpad/fixaudit/scan_real.py`)
Все `.xlsx/.csv` дерева с колонкой даты (без `node_modules/target/.git/dist/_internal/.svelte-kit`) – **38 файлов, срабатываний 0**
(прежний детектор – тоже 0). Хвостов без даты в этих файлах нет, поэтому добавлен стресс (`stress_real.py`): к каждому из 30
непустых файлов с датами дописана строка-неитог – «настоящий период без даты» (последняя строка ×1,01), строка нулей,
примечание со словами «суммы/всего/total» без чисел, пустая строка, **ровно одно совпадение с суммой вне KPI**, дубль
последней строки – **0 ложных из 180**; контроль «итог только по KPI» пойман во всех 30.

## 2. M-5 – PPTX при mROAS ≤ 0 у всех каналов

`aurora_pptx/builder.py:2026-2041`: размеры области диаграммы вынесены до условия; при пустом `bar_labels` вместо
`add_chart` – надпись «Ни у одного канала нет положительной отдачи в этой модели – сравнивать на диаграмме нечего.»; блок
диаграммы (сама диаграмма, подписи, оси, зазор) – под `else` без изменений (`git diff -w`: +17/−5). Пометка к порогу
«1.0× = безубыточность» и правая колонка слайда не тронуты.

Тест `tests/test_pptx_nonpositive_mroas.py` (фикстура `kagocel_builder_payload.json`): все каналы `mroas=-0.35` – выгрузка
строится, на слайде «MROAS ПО КАНАЛАМ» надпись и нет диаграммы; обычная фикстура – диаграмма на месте, надписи нет. 2 passed.
**МУТАЦИЯ** (весь `builder.py` до правки): `1 failed` – `ValueError: chart data contains no categories`; откат сверен
(sha `20fd3b547762e5f3…` до и после).

**Реестр дефектов** (аудит предлагал завести) – не заводила, это делает оркестратор.

## 3. M-4 – проверка живости не видела интерфейс

`src-tauri/installer_hooks.nsh:181-188` (UTF-8 с BOM и CRLF сохранены):
```diff
-  nsExec::Exec 'cmd /c tasklist /FI "IMAGENAME eq ${IMAGE}" /NH | "$SYSDIR\find.exe" /I "${IMAGE}"'
+  ; 🔴 M-4 (аудит s55, 2026-09-28): … (7 строк комментария)
+  nsExec::Exec 'cmd /c tasklist /FI "IMAGENAME eq ${IMAGE}" /FO CSV /NH | "$SYSDIR\find.exe" /I """${IMAGE}"""'
```
Фильтра по учётной записи в проверке нет (правило «смотреть широко» сохранено). В строке `find` кавычка внутри строки поиска –
удвоенная, ищется `"<имя>"` – совпадает только поле имени CSV. Русское «Информация: Задачи … отсутствуют.» имени не содержит →
`find` = 1 → «процесса нет», как и раньше.

**Живая проба под пониженным токеном** (`scratchpad/fixaudit/m4/`: `make_lines.py` берёт строки из хука до правки и из дерева
и разворачивает `${IMAGE}`/`$SYSDIR`; `m4_live.ps1` запускает их как nsExec – `CreateProcess` «cmd.exe /c …»). Задача
`schtasks /Create /TN s55_fixaudit_m4 … /RL LIMITED /IT` + `/Run`; подставной процесс – копия `PING.EXE` под именем
`zz-fixaudit-econometrica-gui.exe` (32 знака):
```
10:11:28.993  user=ackol IL=… S-1-16-8192  img=zz-fixaudit-econometrica-gui.exe len=32
10:11:29.277  no proc: OLD check rc=1
10:11:29.524  no proc: NEW check rc=1
10:11:31.633  decoy pid=48520 alive=True
10:11:31.893  with proc: OLD check rc=1 out=[]                ← прежняя проверка не видит живой процесс
10:11:32.168  with proc: NEW check rc=0 out=["zz-fixaudit-econometrica-gui.exe","48520","Console","1","5 272 КБ"]
10:11:32.775  kill rc=0 t=0,60s err=[]
10:11:33.299  after kill: decoy alive=False
10:11:33.599  after kill: NEW check rc=1
```
Уборка: задача удалена (`schtasks /Delete … /F`, повторный запрос – rc 1), подставных процессов нет (`Win32_Process`).

## 4. M-3 – сторож хука видит рабочую семантику

`tools/test_installer_hooks.py` (стандартная библиотека в `python tools/…` сохранена; `pytest` импортируется, если есть):
- **(7) статика** в `check()`: `_KILL_PARSE` (`:59-64`) – в строке снятия обязательны `for /f "tokens=1,2 delims=," %a in (`
  с одним `%`, `tasklist … /FO CSV` внутри `('…')`, `if /i %a=="${IMAGE}"`, `taskkill /PID %~b /T /F`; в проверке живости –
  `/FO CSV` и `/I """${IMAGE}"""` (сообщение называет образы длиннее 25 знаков);
- `test_guard_catches_audit_breakages[5]` – мутации на копии текста в памяти: `percent_doubled`, `no_csv_in_kill`, `tokens_2`,
  `no_image_if` (4 поломки аудита) и `table_check` (возврат M-4) – каждая обязана дать провал `check()`;
- **(8) исполняемые пробы** (`skipif` не Windows – CI Python идёт на ubuntu, там пропуск):
  - `test_macro_lines_execute_on_decoy` – обе строки макроса выполняются как у nsExec на подставном дереве (копия `cmd.exe`
    под уникальным именем из 32 знаков + дочерняя копия `PING.EXE`): без процесса проверка «нет» и снятие не зовёт taskkill
    (stderr пуст – это и есть работа `if /i`), с процессом проверка «жив», после снятия родитель и дочерний сняты;
  - `test_macro_built_by_makensis_kills_decoy` – учебный установщик: `!include` настоящего хука + `!insertmacro
    AURORA_KILL_AND_WAIT "<подставное имя>"`, сборка `makensis /V2` из `%LOCALAPPDATA%\tauri\NSIS\` (нет – `skip`),
    запуск `/S` при живом подставном дереве → установщик дошёл до конца (`reached_end.txt`), дерево снято.
Прогон: `9 passed in 8.37s` (пробы ~4 с каждая), `python tools/test_installer_hooks.py` – `OK`.

**МУТАЦИИ в рабочем `installer_hooks.nsh`** (`-k decoy`, только исполняемые пробы – статика ловит их и так), sha `05b92e29e45185a1…`
до и после каждой:

| МУТАЦИЯ | `…lines_execute_on_decoy` | `…built_by_makensis…` |
|---|---|---|
| M-3a `%a` → `%%a` | 🔴 | 🔴 (63 с: `_stuck`) |
| M-3b без `/FO CSV` в снятии | 🔴 | 🔴 (63 с) |
| M-3c `tokens=2` | 🔴 | 🔴 (63 с) |
| M-3d без `if /i %a==…` | 🔴 (taskkill на строке «задачи отсутствуют», stderr) | 🟢 – снятие по-прежнему работает, поломка безвредна для установки |
| M-4 табличная проверка живости | 🔴 | 🔴 (макрос ушёл в `_gone` сразу, дерево живо) |

Побочный след провальных мутаций: макрос в `_stuck` пишет `%LOCALAPPDATA%\com.aurora.econometrica\.update-blocked` (внутри –
имя подставного `aurora-hooktest-4591c7db-gui.exe`) и показывает окно «Обновление не выполнено», которое проба снимает через
60 с вместе с учебным установщиком. Файл до прогона отсутствовал, после – перенесён в корзину. При зелёном хуке этого пути нет
(проверено: до и после обычного прогона файла нет). Это же сказано в строке документации пробы.

## 5. Прогоны наборов

Все – на рабочем дереве с правками, `-n 4`, `-m "not requires_real_data and not slow"`.
- **Движок, задетые наборы**: 64 файла `sidecar/econometrica/tests/test_*.py`, где упоминаются `validate_data`, `train_ols`,
  `train_model`, `find_trailing`, `engines.planning`, `engines.validator`, `aurora_pptx`/`AuroraPPTXBuilder` (список –
  `scratchpad/fixaudit/engine_tests.txt`): **`999 passed, 2 skipped in 47.05s`**, 0 failed (пропуски прежние: нет реальной модели
  клиента; нет апостериорных выборок у OLS).
- **`tools/` целиком** (`pytest.ini: testpaths = tools`, в т. ч. расширенный сторож хука с обеими исполняемыми пробами):
  **`2357 passed, 7 skipped in 93.40s`**, 0 failed (пропуски прежние, ни один не из `test_installer_hooks.py`).
- После прогонов: `.update-blocked` отсутствует, подставных процессов `aurora-hooktest-*`/`zz-fixaudit-*` нет.
- vitest – не гоняла: JS/Svelte не менялись.

## 6. Что не делала / осталось

- vitest: фронтенд не трогала (правка M-2 – в движке), прогона нет.
- Предпроверка обучения (`/compute/preflight`) и `load_frames` итог по-прежнему не отсеивают (отмечено в `FIX_s55_data.md`) –
  не трогала.
- Устаревший комментарий в `NSIS_HOOK_PREINSTALL` (~`:350`, «taskkill /IM … /T убивает дерево») – не правила (хирургия), как и в
  `FIX_s55_cpd208.md`.
- Живая проба M-4 – на подставном процессе и учебном установщике, не на собранном установщике продукта (сборки не было).

## 7. Долг L (не чинила)

- **L-1** номер строки для CSV с пустыми строками (`planning.py` `file_row = pos + 2`, `read_csv` пропускает пустые) – нужен
  отдельный подсчёт по сырому файлу; не одна строка.
- **L-3** итог с датой и подытоги в середине – вне правила «только хвост», известное ограничение.
- **L-4** mROAS в PPTX: таблица две цифры, текст рядом одна (`builder.py` `hero_mroas:.1f`, фолбэк комментария `:.1f`,
  `sections.py:888`) – четыре места в двух файлах, соседняя зона `fix-257-text`; не тривиально.
- (L-2 закрыт, см. §1.)
