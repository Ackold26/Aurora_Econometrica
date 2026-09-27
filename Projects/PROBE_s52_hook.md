# PROBE s52 – хук установщика: удаление хвостов движка (варианты A, D, E)

**Дата:** 27.09.2026, 14:12–14:31 (время из `date`). Маячок – `Projects/PULSE_s52_hook.md`.
**Предмет:** `src-tauri/installer_hooks.nsh` (подключён через `tauri.conf.json` → `bundle.windows.nsis.installerHooks`), новый `tools/check_sidecar_payload_clean.py`.
**Что НЕ делалось:** полная сборка поставки, `tauri build`, `cargo`, `node tools/build-cloud.mjs` – не запускались; реальная установленная программа не трогалась, в `%LOCALAPPDATA%\Programs` ничего не ставилось; `git commit/push/stash` – нет. Все данные стенда – в `C:\Users\ackol\AppData\Local\Temp\claude\hookprobe_s52\`.

## Итог

- **A (PREINSTALL)** и **D (PREUNINSTALL)** реализованы одним макросом `AURORA_PURGE_DIR` с защитами (а) пустой/корень, (б) главный exe на месте, (в) каталог существует, (г) частичный провал – строка в журнал и установка идёт дальше.
- **Стенд makensis** (тот же `makensis.exe` из комплекта Tauri, реальный хук через `!include`) – 12 прогонов на байтово окончательном хуке (sha256 `E6AA3DE2…7573`), все совпали с ожиданием; сторожевая мутация защиты (б) поймана (удалено 10 и 11 файлов вместо 0) и откачена (sha256 = эталону, мутационных строк в `git diff` – 0).
- **E:** скрипт на текущем дереве – `OK`, 5 817 файлов (ровно столько же файлов движка насчитал PROBE_s50 §4 по `File /a`), код 0; на поддельном грязном дереве – код 1 и 4 находки.
- **Главное, чего стенд не доказывает:** обновление поверх **реальной** загрязнённой установки (~15 тыс. файлов, настоящий шаблон Tauri, антивирус, время) – остаётся на живую пробу совмещённого выпуска.

---

## 1. Что изменено

### 1.1 Главный exe – откуда имя
`aurora-econometrica-gui.exe`: `Cargo.toml` → `[package] name = "aurora-econometrica-gui"`; сгенерированный шаблон `target\release\nsis\x64\installer.nsi:42` → `!define MAINBINARYNAME "aurora-econometrica-gui"`; в установке – `…\Optimizer MMM\aurora-econometrica-gui.exe` (PROBE_s50_hook_live, часть Б). В `tauri.conf.json` `mainBinaryName` не задан. Имя в хуке записано литералом (как и в соседних вызовах `AURORA_KILL_AND_WAIT`), а расхождение с `MAINBINARYNAME` **ломает компиляцию** (`!error`) – иначе переименование молча выключило бы очистку. Проверено: стенд с `MAINBINARYNAME "optimizer-mmm"` → `makensis exit=1`, `!error: installer_hooks.nsh: main binary renamed (MAINBINARYNAME=optimizer-mmm) - update guard (b) in AURORA_PURGE_DIR`.

Сверка стоит **внутри** макроса: шаблон подключает хук на строке 28, а `MAINBINARYNAME` определяет на строке 42 – на уровне файла `!ifdef` не видел бы его никогда (первая редакция так и была написана, поймано чтением шаблона до стенда).

### 1.2 Дифф хука целиком

```diff
diff --git a/src-tauri/installer_hooks.nsh b/src-tauri/installer_hooks.nsh
index 55164571..6a7961e0 100644
--- a/src-tauri/installer_hooks.nsh
+++ b/src-tauri/installer_hooks.nsh
@@ -224,6 +224,76 @@ ${TAG}_gone:
   Pop $0
 !macroend
 
+; Хвосты движка (s52, 2026-09-27; расследование – Projects/PROBE_s50_leftovers.md).
+; NSIS при обновлении только КЛАДЁТ свои файлы и ничего чужого не трогает, а деинсталлятор
+; снимает каталоги нерекурсивно. Сборки до 13.09.2026 брали ресурс движка широким шаблоном
+; `../sidecar/econometrica/**/*` – у обновившегося покупателя в `_up_\sidecar\econometrica`
+; лежит ~9 100 лишних файлов / ~1 ГБ (целый движок 2.5.0.0 в `dist\`, `tests`, `.hypothesis`,
+; `__pycache__`), и они переживают удаление программы. На поведение 2.5.5 они не влияют
+; (доказано там же), это диск и лишний исполняемый файл в профиле.
+;
+; Лечение – удалить каталог ЦЕЛИКОМ и дать установщику положить нагрузку заново (вариант A),
+; а при удалении программы – снять `_up_\sidecar` целиком (вариант D). Адресное удаление
+; известных хвостов (вариант B) отвергнуто: не ловит будущие неизвестные хвосты.
+;
+; 🔴 Рекурсивное удаление по пути от `$INSTDIR` опасно ровно настолько, насколько неверным
+; может оказаться `$INSTDIR`. Три защиты, каждая – отдельный переход:
+;   (а) `$INSTDIR` не пуст и не корень диска (длина ≤ 3: «C:\», «C:», «\», «»). Пустой
+;       `$INSTDIR` превратил бы путь в `\_up_\...` – от корня ТЕКУЩЕГО диска: `IfFileExists`
+;       по такому пути видит файлы (стенд s52), `RMDir /r` его, правда, сам отвергает – но
+;       полагаться на внутреннюю проверку NSIS вместо своей не стали. Корень диска NSIS
+;       через `/D=` не пускает, но `$INSTDIR` приходит и из реестра, и из кода шаблона;
+;   (б) в `$INSTDIR` лежит главный exe программы – значит, это наша установка, а не
+;       случайная папка с совпавшим подкаталогом. Имя – `aurora-econometrica-gui.exe`
+;       (`[package] name` в Cargo.toml → MAINBINARYNAME шаблона Tauri); сверка ниже
+;       ломает КОМПИЛЯЦИЮ, если имя разойдётся, – иначе защита молча выключила бы очистку;
+;   (в) удаляем, только если каталог существует (первая установка – тихий проход).
+;
+; 🔴 Частичный провал – НЕ провал установки. Если файл занят (процесс движка пережил
+; снятие, антивирус держит .pyd), `RMDir /r` удалит что сможет и поднимет флаг ошибок.
+; Тогда пишем строку в ход установки и идём дальше: установщик перезапишет файлы поверх,
+; как делал до этой правки. Прерывать тут нельзя – окно отказа уже есть в
+; AURORA_KILL_AND_WAIT и сработало бы раньше, если бы процесс был жив.
+;
+; 🔴 `/REBOOTOK` здесь НАМЕРЕННО НЕТ: он отложил бы удаление занятого файла до перезагрузки,
+; и после перезагрузки Windows удалила бы уже НОВЫЙ файл с тем же именем, который установщик
+; только что положил, – движок сломался бы у покупателя через день, без связи с обновлением.
+;
+; ${SUBDIR} – путь от `$INSTDIR`, ${TAG} – приставка меток (уникальны в функции).
+; $0 сохраняется и возвращается: макрос встраивается в чужую функцию шаблона Tauri.
+; Сверка имени стоит ВНУТРИ макроса, а не на уровне файла: шаблон подключает этот файл
+; раньше, чем определяет MAINBINARYNAME, и на уровне файла сверка не видела бы его никогда.
+!macro AURORA_PURGE_DIR SUBDIR TAG
+  !ifdef MAINBINARYNAME
+    !if "${MAINBINARYNAME}" != "aurora-econometrica-gui"
+      ; ASCII: консоль сборки выводит кириллицу makensis кракозябрами (проверено на стенде s52).
+      !error "installer_hooks.nsh: main binary renamed (MAINBINARYNAME=${MAINBINARYNAME}) - update guard (b) in AURORA_PURGE_DIR"
+    !endif
+  !endif
+  Push $0
+  ; (а) пустой или корень диска
+  StrCmp $INSTDIR "" ${TAG}_bad
+  StrLen $0 $INSTDIR
+  IntCmp $0 3 ${TAG}_bad ${TAG}_bad 0
+  ; (б) главный exe на месте
+  IfFileExists "$INSTDIR\aurora-econometrica-gui.exe" 0 ${TAG}_noexe
+  ; (в) есть что удалять
+  IfFileExists "$INSTDIR\${SUBDIR}\*.*" 0 ${TAG}_done
+  DetailPrint "Removing stale engine files: ${SUBDIR}"
+  ClearErrors
+  RMDir /r "$INSTDIR\${SUBDIR}"
+  IfErrors 0 ${TAG}_done
+  DetailPrint "WARNING: ${SUBDIR} removed only partially (files in use). Continuing; files will be overwritten in place."
+  Goto ${TAG}_done
+${TAG}_bad:
+  DetailPrint "SKIP cleanup of ${SUBDIR}: install folder is empty or a drive root."
+  Goto ${TAG}_done
+${TAG}_noexe:
+  DetailPrint "SKIP cleanup of ${SUBDIR}: main program file not found in install folder."
+${TAG}_done:
+  Pop $0
+!macroend
+
 !macro NSIS_HOOK_PREINSTALL
   ; P3.1 install-lock fix: освобождаем .pyd / .dll перед extract.
   ; taskkill /IM matches by image name (idempotent – no-op если процесс уже мёртв).
@@ -244,6 +314,8 @@ ${TAG}_gone:
   DetailPrint "Preparing for update: stopping background processes..."
   !insertmacro AURORA_KILL_AND_WAIT "econometrica-sidecar.exe" pre_sidecar
   !insertmacro AURORA_KILL_AND_WAIT "aurora-econometrica-gui.exe" pre_gui
+  ; Вариант A: хвосты прежних сборок – после снятия процессов, иначе .pyd заняты.
+  !insertmacro AURORA_PURGE_DIR "_up_\sidecar\econometrica" pre_purge
 !macroend
 
 !macro NSIS_HOOK_POSTINSTALL
@@ -264,4 +336,10 @@ ${TAG}_gone:
   DetailPrint "Stopping background processes before uninstall..."
   !insertmacro AURORA_KILL_AND_WAIT "econometrica-sidecar.exe" un_sidecar
   !insertmacro AURORA_KILL_AND_WAIT "aurora-econometrica-gui.exe" un_gui
+  ; Вариант D: снять `_up_\sidecar` целиком, с хвостами и кэшем numba, который движок пишет
+  ; во время работы. Именно ЗДЕСЬ, а не в POSTUNINSTALL: к POSTUNINSTALL шаблон Tauri уже
+  ; удалил главный exe (`Delete "$INSTDIR\${MAINBINARYNAME}.exe"` – первая строка после
+  ; хука), и защита (б) там всегда ложна – очистка молча не сработала бы никогда. Здесь
+  ; же процессы уже сняты макросами выше, а exe ещё на месте.
+  !insertmacro AURORA_PURGE_DIR "_up_\sidecar" un_purge
 !macroend
```

### 1.3 PREUNINSTALL, а не POSTUNINSTALL – обоснование

Порядок в `Section Uninstall` сгенерированного шаблона (`installer.nsi:7295-7305`, `14053`):

```
Section Uninstall
  !insertmacro NSIS_HOOK_PREUNINSTALL          ; ← наш хук: процессы снимаются, exe ещё на месте
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  Delete "$INSTDIR\${MAINBINARYNAME}.exe"      ; ← главный exe удаляется первым
  … Delete/RMDir по списку …
  !insertmacro NSIS_HOOK_POSTUNINSTALL         ; ← exe уже нет
```

1. **В POSTUNINSTALL защита (б) всегда ложна** – главный exe к этому моменту удалён, очистка молча не сработала бы никогда. Ослаблять защиту ради POSTUNINSTALL (например, проверять `uninstall.exe`) – значит менять одну защиту на другую, более слабую: `uninstall.exe` удаляется тем же списком.
2. **Процесс снят до удаления**: в PREUNINSTALL наш вызов стоит после двух `AURORA_KILL_AND_WAIT` (движок, затем интерфейс), которые при неснимаемом процессе делают `Abort` – до очистки дело не доходит.
3. Цена: если деинсталлятор прервётся **после** хука (например, `CheckIfAppIsRunning` найдёт интерфейс – но его только что сняли), каталог движка уже удалён. Программа при этом нерабочая до переустановки; для деинсталлятора это приемлемо – человек её и удалял.
4. При ручной переустановке через `PageLeaveReinstall` прежний деинсталлятор вызывается с `_?=$INSTDIR`, и шаблон после него проверяет `${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"` – то есть exe в PREUNINSTALL на месте и в этом пути. Работать это начнёт только с деинсталлятора, собранного с этой правкой (старые деинсталляторы у покупателей – старого образца).

### 1.4 Почему без `/REBOOTOK`
Шаблон Tauri снимает каталоги с `/REBOOTOK`, у нас его намеренно нет: для занятого файла он запланировал бы удаление на перезагрузку, и после перезагрузки Windows удалила бы уже **новый** файл, который установщик только что положил поверх, – движок сломался бы у покупателя через день без видимой связи с обновлением.

---

## 2. Стенд

`hookprobe_s52\stand.nsi` – `Unicode true`, заглушка `!define MAINBINARYNAME "aurora-econometrica-gui"`, `!include "${HOOK}"` (путь к **реальному** `src-tauri/installer_hooks.nsh`), секция установки повторяет шаблон (`SetOutPath $INSTDIR` → `!insertmacro NSIS_HOOK_PREINSTALL`), секция `Uninstall` – `!insertmacro NSIS_HOOK_PREUNINSTALL`. После хука стенд пишет след `reached_<режим>.txt` – «установка после хука продолжилась». Хук ради стенда не менялся.

- **Журнал хода:** в тихом режиме `DetailPrint` не существует вовсе (журнала-файла нет, makensis собран без `NSIS_CONFIG_LOG` – шапка хука). Поэтому каждый случай прогонялся дважды: `/S` – код выхода и перечни, без `/S` – окно вынесено за экран (`SetWindowPos -32000`), содержимое окна хода выгружено в файл приёмом из документации NSIS («Dump Content of Log Window to File»).
- **Модель установки** (`lib.ps1::New-Layout`): главный exe-пустышка; прочие файлы программы (`_up_\NOTICE.md`, `_up_\content-packs\cabinets.json`, `help-econometrica\index.html`, `sidecar\pptx_pipeline.py`, `uninstall.exe`); два соседа-приманки `_up_\sidecar_keep\keep.txt` (похожее имя) и `_up_\sidecar\other\keep.txt` (внутри `_up_\sidecar`: цел в A, удаляется в D); загрязнённый `_up_\sidecar\econometrica\` – 10 файлов: `econometrica-sidecar.exe`, `_internal\python3.dll`, `_internal\jax\__init__.py`, `_internal\jax\__pycache__\__init__.cpython-312.pyc`, `_internal\arviz\stats\__pycache__\density_utils.nbi`, `dist\econometrica-sidecar\econometrica-sidecar.exe`, `dist\econometrica-sidecar\_internal\numpy\core\_mult.pyd`, `tests\test_x.py`, `.hypothesis\examples\ab\cd`, `utils\safe_io.py`. Рядом с «установкой» – контрольный `outside.txt`.
- **Корень и пустота – через subst:** временные диски `Q:` → `hookprobe_s52\drive_a_root`, `R:` → `hookprobe_s52\drive_a_empty`, модель – в корне диска. При сломанной защите пострадала бы только временная папка (что и показала мутация (а), §4). После прогонов subst сняты (`subst` пуст).
- **Процессы:** стенд вызывает настоящий `AURORA_KILL_AND_WAIT`, который бьёт по имени образа. Перед каждым прогоном `Assert-NoProductProcs` проверял, что `econometrica-sidecar.exe` и `aurora-econometrica-gui.exe` не запущены (их не было ни разу).

### 2.1 Находка при постройке стенда
Первый прогон корня (`/D=Q:\`, запись `runs\a_root_1`) **не считается**: NSIS сам отвергает корень диска в `/D=` (`AllowRootDirInstall` по умолчанию выключен, в шаблоне Tauri не включён) и молча подставляет `InstallDir` – след показал `INSTDIR=[…\default_unused]`, хук работал по пустой папке. Корень и пустоту поэтому моделирую присваиванием `$INSTDIR` внутри секции (`/MODE=rootdir|emptydir`, `/ROOT=`), как если бы значение пришло из реестра или кода шаблона. Заодно: NSIS нормализует `Q:\` → `Q:` (длина 2 – ловится `≤ 3`).

---

## 3. Прогоны на окончательном хуке (sha256 `E6AA3DE29AB8C9543AE022960009F86B4D43D5B58907ED68CCC1CD7EBB587573`)

Сводка – `hookprobe_s52\final_suite_F2.txt`; перечни «до / после / удалено / цело» каждого прогона – `hookprobe_s52\runs\F2_*\result.txt`, журналы хода – в тех же файлах.

| Прогон | Ожидание | Факт | Доказательство |
|---|---|---|---|
| **A-норма** (`F2_A_norm`, `/S`) | хвосты удалены, прочее цело | код 0, след «дошли» есть; удалено 10 (все 10 файлов `_up_\sidecar\econometrica\…`, каталог исчез), цело 8 (включая обе приманки и exe), вне установки без изменений | до 18 → после 8. После: `_up_\content-packs\cabinets.json`, `_up_\NOTICE.md`, `_up_\sidecar\other\keep.txt`, `_up_\sidecar_keep\keep.txt`, `aurora-econometrica-gui.exe`, `help-econometrica\index.html`, `sidecar\pptx_pipeline.py`, `uninstall.exe` |
| A-норма, журнал (`F2_A_norm_log`) | строка об удалении | то же + `Removing stale engine files: _up_\sidecar\econometrica` | `result.txt` |
| **(б) нет exe** (`F2_b_noexe`, `/S`) | ничего не удалено | код 0, дошли; удалено 0, цело 17 из 17 | до 17 = после 17 |
| (б), журнал (`F2_b_noexe_log`) | строка пропуска | `SKIP cleanup of _up_\sidecar\econometrica: main program file not found in install folder.` | `result.txt` |
| **(а) корень** (`F2_a_root`, `$INSTDIR`=`Q:`) | ничего не удалено | код 0, дошли (`INSTDIR=[Q:]`); удалено 0, цело 18 из 18 | до 18 = после 18 |
| (а) корень, журнал | строка пропуска | `SKIP cleanup of _up_\sidecar\econometrica: install folder is empty or a drive root.` | `result.txt` |
| **(а) пустой** (`F2_a_empty`, `$INSTDIR`=«», текущий каталог `R:`) | ничего не удалено | код 0, дошли (`INSTDIR=[]`); удалено 0, цело 18 из 18 | до 18 = после 18 |
| (а) пустой, журнал | строка пропуска | `SKIP … install folder is empty or a drive root.` | `result.txt` |
| **(г) файл занят** (`F2_g_locked`, `/S`) | установка не падает, удалено всё, кроме занятого | контроль до прогона: `python3.dll` не открывается другим процессом («being used by another process»); код 0, дошли; удалено 9, цело 9 – среди целых ровно занятый `_up_\sidecar\econometrica\_internal\python3.dll` | после: 8 прежних + `…\_internal\python3.dll`. «Вне установки: False» – это мой маркер `lock_ready.txt` от держателя блокировки, появился после снимка «до»; других отличий нет |
| (г), журнал (`F2_g_locked_log`) | строка о частичном удалении | `Removing stale engine files: …` → `WARNING: _up_\sidecar\econometrica removed only partially (files in use). Continuing; files will be overwritten in place.` | `result.txt` |
| **D-норма** (`F2_D_norm`, `stand-uninstall.exe /S _?=…`) | `_up_\sidecar` удалён | код 0, след `reached_uninstall` есть; удалено 11 (10 хвостов + `_up_\sidecar\other\keep.txt`), каталога `_up_\sidecar` нет; `_up_\sidecar_keep\keep.txt` цел | до 18 → после 7 |
| D без exe (`F2_D_noexe`) | ничего не удалено | удалено 0, цело 17 из 17 | до 17 = после 17 |

Во всех прогонах установщик вернул 0 и дошёл до кода после хука – ни одна защита не превращается в `Abort`.

---

## 4. Сторожевые мутации

Мутации вносились скриптом `hookprobe_s52\mutate.py` по **номеру действующей строки** с проверкой её текста (не по первому вхождению), откат – побайтным возвратом эталона `hook_pristine.nsh` со сверкой sha256.

| Мутация | Внесена | Поймана | Откачена |
|---|---|---|---|
| **(б)**, окончательный хук: строка 279 `IfFileExists "$INSTDIR\aurora-econometrica-gui.exe" 0 ${TAG}_noexe` → `… 0 0` | `mutated sha: e5e2990c…`; makensis дал 2 предупреждения «label `pre_purge_noexe` / `un_purge_noexe` not used» | `F2MUT_b_noexe`: без exe **удалено 10** (было 0); `F2MUT_D_noexe`: **удалено 11** (было 0); журнал: `Removing stale engine files` вместо `SKIP` | `undo: e6aa3de2… == pristine: True`; мутационных строк в `git diff` – 0; повтор `F2_revert_b_noexe` / `F2_revert_D_noexe` – удалено 0; makensis – 0 предупреждений |
| (б), прежняя редакция хука (до правки текста `!error` и комментария): строка 275 | то же | `MUT_b_noexe`, `FMUT_b_noexe`: удалено 10; `FMUT_D_noexe`: 11 | sha256 = эталону на каждом шаге |
| **(а)**, прежняя редакция: строки 271 и 273 (переходы на `_bad` → `0`) – доказать, что прогоны корня и пустоты не холостые | makensis: «label `pre_purge_bad` not used» | `MUT_a_root`: **удалено 10 в `Q:\_up_\sidecar\econometrica`** – то есть во временной папке `drive_a_root`; `MUT_a_empty`: защита отключена (журнал `Removing …` вместо `SKIP`), **но удалено 0** – `IfFileExists "\…"` видит файлы на `R:`, а `RMDir /r` путь без буквы диска сам отвергает и поднимает флаг ошибок (строка `WARNING … partially`) | sha256 = эталону |

Вывод по (а): для корня защита – единственный рубеж; для пустого `$INSTDIR` рубежей два (наш и внутренняя проверка `RMDir /r` в NSIS). Мутации (а) и первая (б) сделаны на редакции, отличающейся от окончательной только текстом `!error` и комментарием; мутация (б) повторена на байтово окончательном хуке (первая строка таблицы).

---

## 5. Вариант E – `tools/check_sidecar_payload_clean.py`

Пути берёт из `src-tauri/tauri.conf.json` → `bundle.resources` (записи с приставкой `../sidecar/econometrica/`, сейчас `econometrica-sidecar.exe` и `_internal/`), ищет каталоги `__pycache__`, `.hypothesis` и файлы `*.nbi`, `*.nbc`. Коды: 0 – чисто, 1 – мусор (перечень), 2 – проверять нечего (ресурсов движка нет в конфиге, хоть одного нет на диске, или ноль файлов) – проверка, которая ничего не увидела, не может сказать «чисто». Никуда не встроен.

Вывод на текущем дереве (`hookprobe_s52\e_tree_output.txt`):
```
Ресурсы движка из bundle.resources:
  ../sidecar/econometrica/econometrica-sidecar.exe: файлов 1
  ../sidecar/econometrica/_internal/: файлов 5816
OK: просмотрено файлов 5817, __pycache__/.hypothesis/*.nbi/*.nbc нет
exit=0
```
Отрицательные контроли – копия скрипта на поддельном дереве `hookprobe_s52\e_probe\` (реальный `_internal` не трогался, чтобы мусор случайно не уехал в поставку):
- грязное дерево → `FAIL(1): мусор в нагрузке движка – 4 шт.:` `…\_internal\.hypothesis\`, `…\_internal\pkg\__pycache__\`, `…\_internal\pkg\f.nbc`, `…\_internal\pkg\f.nbi`, код 1;
- в конфиге нет ресурсов движка → `FAIL(2)`, код 2;
- ресурс движка есть в конфиге, на диске нет → `FAIL(2): 1 ресурс(а) движка нет на диске`, код 2.

---

## 6. Что стенд НЕ доказывает

1. **Обновление поверх реальной загрязнённой установки** – главное. Стенд – не шаблон Tauri: нет `CheckIfAppIsRunning`, распаковки 5 864 файлов, записи реестра, перезапуска по `/R`. Нужна живая проба совмещённого выпуска: установка поверх копии установки с хвостами PROBE_s50 (9 102 файла), затем сверка «в `_up_\sidecar\econometrica` ровно файлы нагрузки», `/health` движка, и удаление программы – `_up_\sidecar` исчез.
2. **Время** удаления ~15 тыс. файлов (≈1 ГБ) и поведение антивируса на нём – на 10 файлах не измеримо.
3. **Занятость файла настоящим движком.** Моделировалась дескриптором PowerShell без общего доступа. Загрузчик Windows держит exe/dll отображением, а не дескриптором (PROBE_s50_hook_live, часть Б); удаление файла, отображённого загрузчиком, Windows, насколько известно, тоже отклоняет, но это не проверялось – с живым движком `RMDir /r` не прогонялся. На штатном пути до этого не доходит – `AURORA_KILL_AND_WAIT` снимает процесс или прерывает установку.
4. **Старые деинсталляторы** у покупателей собраны без D – хвосты при удалении уйдут только после того, как покупатель хотя бы раз обновится на выпуск с этой правкой (A при этом срабатывает сразу, это код нового установщика).
5. **Машинная установка в Program Files** и чужая учётная запись – не моделировались.

## 7. Риски

- **Прерывание после A** (сбой распаковки, нехватка места) оставит установку без движка – прежде оставалась бы смесь старого и нового. Обе ситуации – нерабочая программа до повторной установки; окно отказа и `Abort` для живого процесса стоят раньше очистки.
- **Частичное удаление (г)** оставляет смесь, как и до правки: занятые файлы перезапишутся поверх (или NSIS сообщит об ошибке записи, как раньше). Строка `WARNING` видна только в окне хода установки; при тихом обновлении её не увидит никто – файла журнала нет.
- **Длина путей:** самый длинный хвост у этой учётной записи – 211 символов (`…\dist\econometrica-sidecar\_internal\statsmodels\tsa\vector_ar\tests\JMulTi_results\macrodata_jmulti_ncs_granger_causality_realcons_realinv.txt`, по `leftovers\extra.json`, база `C:\Users\ackol\AppData\Local\Optimizer MMM` – 42 символа); самое длинное из нагрузки 2.5.5 – 185. Запас до 260 – 49 символов на имя папки профиля сверх `ackol`; при обычном имени (до 20 символов) максимум ≈226 – упора в MAX_PATH нет. Длинное имя профиля (например, с приставкой домена) не проверялось.
- **Журнал хода** в ручной установке получит по строке на каждый удалённый файл и каталог (`Delete file:` / `Remove folder:`) – около 15 тыс. строк дополнительно к распаковке. Косметика, не отказ.
- **Имя exe** зашито литералом; при переименовании сборка упадёт на `!error` (проверено), а не выключит очистку молча.
- Защита (а) не считает корнем UNC-путь вида `\\сервер\ресурс`; там остаётся защита (б).

## Артефакты
`C:\Users\ackol\AppData\Local\Temp\claude\hookprobe_s52\`: `stand.nsi`, `stand_renamed.nsi`, `lib.ps1`, `run_case.ps1`, `final_suite.ps1`, `mutate.py`, `hook_pristine.nsh` / `hook_final.nsh` (эталон, sha256 `E6AA3DE2…`), `hook_final.diff`, `final_suite_F2.txt`, `e_tree_output.txt`, `e_probe\` (поддельное дерево для E), `runs\<прогон>\result.txt` (все прогоны, включая промежуточные `A_norm`…`MUT_a_empty`, `F_*`, `FMUT_*`; `a_root_1` – холостой, см. §2.1), `stale_*` – уведённые в сторону следы прежних прогонов (не удалялись).

Чужие незакоммиченные файлы в дереве (`Projects/SAMPLES_s49.md`, `src/tokens.generated.css`, `src-tauri/src/commands/cabinet.rs`, `src-tauri/src/commands/online_auth.rs`, PULSE-файлы других исполнителей, `.impeccable/hook.cache.json`) не трогались.
