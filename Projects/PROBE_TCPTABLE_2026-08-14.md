# Зонд: GetExtendedTcpTable + QueryFullProcessImageNameW (2026-08-14)

## Проверяемое утверждение

> Из обычного пользовательского процесса, без прав администратора и без порождения
> подпроцессов, можно системным вызовом узнать: (а) pid держателя конкретного
> TCP-порта, (б) полный путь образа этого процесса — в том числе когда процесс
> чужой (не наш потомок).

## Вердикт

**Подтверждено, с двумя содержательными оговорками.**

1. **(а) pid держателя порта** — подтверждено безусловно. `GetExtendedTcpTable`
   с классом `TCP_TABLE_OWNER_PID_LISTENER` отдаёт пары порт→pid для ВСЕХ
   слушающих сокетов системы (не только своих), без повышения прав. Сверка
   с `netstat -ano` — 26+ пар совпали 1:1.

2. **(б) путь образа чужого процесса** — подтверждено для подавляющего
   большинства процессов, включая процессы под SYSTEM (lsass.exe, services.exe,
   wininit.exe) и PPL/WinTcb-защищённые (csrss.exe, MsMpEng.exe). Из 44
   слушающих сокетов путь получен для 35-36 (~80%), включая ВСЕ протестированные
   чужие процессы кроме pid=4 ("System" — виртуальный процесс ядра без файла на
   диске).

**Оговорка 1 — направление ошибки у смежной линии перепутано.** Заявление ТЗ:
«у мёртвого процесса дескриптор открывается успешно и падает завершение, у
защищённого падает само открытие» — по факту **наоборот**:
- у **заведомо несуществующего** pid (число вне диапазона реальных pid, или
  pid, который система ещё не успела переиспользовать) падает именно
  **OpenProcess**, код **87** (`ERROR_INVALID_PARAMETER`);
- у **живых системных/виртуальных процессов** (System pid=4, Secure System
  pid=332, Registry pid=376) `OpenProcess` **проходит успешно** (право
  `PROCESS_QUERY_LIMITED_INFORMATION` оказалось достаточным даже для них), а
  падает именно **QueryFullProcessImageNameW**, код **31**
  (`ERROR_GEN_FAILURE`) — потому что у этих процессов физически нет обычного
  пути образа на диске.

Коды ошибок **не одинаковы** (87 ≠ 31) — они как раз и есть тот сигнал, по
которому программно различаются два случая: «pid никогда не существовал /
уже полностью освобождён системой» (87 на OpenProcess) против «pid жив (или
только что умер), но путь недоступен» (31 на Query).

**Оговорка 2 — гонка PID пойман фактом, не гипотезой.** В одном из прогонов
«правдоподобный» тестовый pid (`max_seen_pid + 1000`, округлённый до кратного
4) дал отказ 87 на OpenProcess (pid ещё свободен) — а в другом прогоне (после
того как система успела его кому-то присвоить) тот же расчёт дал OpenProcess
**OK** + отказ **31** на Query. Это живая иллюстрация ровно того сценария,
который в ТЗ называется «мёртвый процесс»: PID успел переиспользоваться или
процесс исчез в промежутке между двумя вызовами — окно гонки существует и
зонд его поймал не специально, а по ходу обычного прогона.

**Ни разу не встретился `ERROR_ACCESS_DENIED` (код 5)** на `OpenProcess` —
ни для одного из протестированных процессов, включая PPL AntimalwareLight
(MsMpEng.exe) и WinTcb-protected (csrss.exe). `PROCESS_QUERY_LIMITED_INFORMATION`
оказался «непривилегированным» правом в буквальном смысле — Windows выдаёт
handle с этим правом практически всем процессам в системе независимо от
владельца и уровня защиты; единственное, что может не получиться дальше —
именно чтение пути образа (`QueryFullProcessImageNameW`), и то не по причине
защиты в наблюдавшихся случаях, а по причине отсутствия «нормального» пути у
виртуальных процессов ядра.

## Фактическая выдача зонда (release, полный прогон)

```
=== Зонд GetExtendedTcpTable + QueryFullProcessImageNameW ===
Текущий процесс НЕ администратор (проверка идёт как обычный пользователь).

Найдено слушающих сокетов: 44

AF     PORT   PID                 ПУТЬ / ОШИБКА
v4     135    2348     OK        C:\Windows\System32\svchost.exe
v4     139    4        ОТКАЗ     QueryFullProcessImageNameW код=31
v4     139    4        ОТКАЗ     QueryFullProcessImageNameW код=31
v4     139    4        ОТКАЗ     QueryFullProcessImageNameW код=31
v4     139    4        ОТКАЗ     QueryFullProcessImageNameW код=31
v4     139    4        ОТКАЗ     QueryFullProcessImageNameW код=31
v4     2179   3892     OK        C:\Windows\System32\vmms.exe
v4     5040   9748     OK        C:\Windows\System32\svchost.exe
v4     5354   25360    OK        C:\Users\ackol\AppData\Roaming\Zoom\bin\Zoom.exe
v4     5432   8168     OK        C:\Program Files\PostgreSQL\17\bin\postgres.exe
v4     7425   63036    OK        C:\Users\ackol\AppData\Local\Programs\Python\Python312\pythonw.exe
v4     8203   7024     OK        C:\Program Files (x86)\Tensor\Saby Center\sabycenter.exe
v4     9210   7024     OK        C:\Program Files (x86)\Tensor\Saby Center\sabycenter.exe
v4     10000  7516     OK        C:\Program Files (x86)\Kaspersky Lab\Kaspersky Password Manager 25.3\kpm.exe
v4     11434  4908     OK        C:\Users\ackol\AppData\Local\Programs\Ollama\ollama.exe
v4     13816  60104    OK        C:\Users\ackol\AppData\Roaming\uv\python\cpython-3.13.12-windows-x86_64-none\python.exe
v4     21947  72268    OK        C:\Users\ackol\AppData\Roaming\uv\python\cpython-3.13.12-windows-x86_64-none\python.exe
v4     30116  90756    OK        C:\Users\ackol\AppData\Roaming\uv\python\cpython-3.13.12-windows-x86_64-none\python.exe
v4     43434  6280     OK        C:\Program Files (x86)\Kerio\VPN Client\kvpncsvc.exe
v4     48593  6824     OK        C:\Users\ackol\AppData\Local\Programs\Ollama\ollama app.exe
v4     49664  1784     OK        C:\Windows\System32\lsass.exe
v4     49665  1972     OK        C:\Windows\System32\wininit.exe
v4     49666  2864     OK        C:\Windows\System32\svchost.exe
v4     49667  4024     OK        C:\Windows\System32\svchost.exe
v4     49668  5392     OK        C:\Windows\System32\spoolsv.exe
v4     49677  1256     OK        C:\Windows\System32\services.exe
v4     49678  6184     OK        C:\Program Files (x86)\Kaspersky Lab\Kaspersky 21.26\avp.exe
v4     58795  83732    OK        C:\Users\ackol\AppData\Roaming\uv\python\cpython-3.13.12-windows-x86_64-none\python.exe
v4     445    4        ОТКАЗ     QueryFullProcessImageNameW код=31
v4     2869   4        ОТКАЗ     QueryFullProcessImageNameW код=31
v4     7680   19956    OK        C:\Windows\System32\svchost.exe
v6     135    2348     OK        C:\Windows\System32\svchost.exe
v6     445    4        ОТКАЗ     QueryFullProcessImageNameW код=31
v6     2179   3892     OK        C:\Windows\System32\vmms.exe
v6     2869   4        ОТКАЗ     QueryFullProcessImageNameW код=31
v6     5432   8168     OK        C:\Program Files\PostgreSQL\17\bin\postgres.exe
v6     7680   19956    OK        C:\Windows\System32\svchost.exe
v6     42050  39456    OK        C:\Program Files\Microsoft OneDrive\26.134.0713.0007\OneDrive.Sync.Service.exe
v6     49664  1784     OK        C:\Windows\System32\lsass.exe
v6     49665  1972     OK        C:\Windows\System32\wininit.exe
v6     49666  2864     OK        C:\Windows\System32\svchost.exe
v6     49667  4024     OK        C:\Windows\System32\svchost.exe
v6     49668  5392     OK        C:\Windows\System32\spoolsv.exe
v6     49677  1256     OK        C:\Windows\System32\services.exe

--- Разбивка: свой pid=95060 против чужих pid ---
Чужих процессов с путём получено: 35, отказано: 9
```

Ключевая проверка «чужой процесс» (шаг 5): все процессы в таблице, кроме
самого зонда, — чужие (зонд не порождал ни одного из них). Путь получен для
процессов под собственным пользователем (Zoom, PostgreSQL, Python, Ollama,
Kaspersky, Saby Center и т.д.) **и** для процессов под SYSTEM (lsass.exe,
wininit.exe, services.exe, svchost.exe, spoolsv.exe) — то есть межпользовательская
граница для чтения ПУТИ не является барьером в наблюдавшихся случаях.
Единственный чужой процесс, у которого путь не получен, — pid=4 ("System"),
и причина не в защите доступа, а в отсутствии обычного файла образа.

## Сверка с netstat -ano

Ручной прогон (`netstat -ano`, шаблон LISTENING) сверен построчно с выдачей
зонда — 26+ пар «порт → pid» из первых 40 строк netstat, ВСЕ совпали 1:1 (135→2348,
445→4, 2179→3892, 2869→4, 5040→9748, 5432→8168, 7680→19956, 49664→1784,
49665→1972, 49666→2864, 49667→4024, 49668→5392, 49677→1256, 139→4 (×5 адресов),
5354→25360, 7425→63036, 8203→7024, 9210→7024, 10000→7516, 11434→4908,
13816→60104, 21947→72268, 30116→90756, 43434→6280, 48593→6824, 49678→6184,
58795→83732). Расхождений не найдено.

## Замеры времени (release, 3 прогона, полный перечень + разрешение всех путей)

| Прогон | Записей | Время |
|---|---|---|
| 1 | 44 | 11.799 мс |
| 2 | 44 | 9.107 мс |
| 3 | 44 | 15.672 мс |

Для сравнения смежная линия заявляла 2-5 мс у системного вызова против 15-18 с
у службы управления Windows (WMI). Фактический диапазон здесь выше заявленных
2-5 мс (вероятно из-за 44 портов вместо меньшего числа и накладных расходов
`OpenProcess`+`QueryFullProcessImageNameW` на каждую запись, включая 5
дублей `139/4` и 4 дубля `445`/`2869`), но остаётся **на три порядка быстрее**
заявленных секунд WMI — порядок величины подтверждён.

## Коды ошибок (шаг 8)

| Случай | pid | Этап отказа | Код |
|---|---|---|---|
| Несуществующий, вне формата | 999999999 | OpenProcess | 87 (ERROR_INVALID_PARAMETER) |
| Secure System (PPL) | 332 | QueryFullProcessImageNameW | 31 (ERROR_GEN_FAILURE) |
| Registry (PPL) | 376 | QueryFullProcessImageNameW | 31 |
| csrss.exe #1 (WinTcb) | 1780 | — | OK, путь получен |
| csrss.exe #2 (WinTcb) | 1980 | — | OK, путь получен |
| MsMpEng.exe (PPL AntimalwareLight) | 6660 | — | OK, путь получен |
| System (ядро) | 4 | QueryFullProcessImageNameW | 31 |
| «Правдоподобный» несуществующий (max_seen+1000) | 91756 | debug-прогон: OpenProcess (код 87); release-прогон: QueryFullProcessImageNameW (код 31, после переиспользования pid системой) | зависит от момента — см. оговорку 2 выше |

Практический вывод: код **87 на OpenProcess** = pid точно не существует и не
существовал недавно. Код **31 на QueryFullProcessImageNameW** = pid
соответствует реальной структуре процесса в ядре (жив, только что умер, либо
виртуальный процесс без файла образа) — сам по себе не доказывает «это наш
искомый процесс», но однозначно доказывает «это НЕ полное отсутствие
процесса».

## Точный перечень фич windows-sys, потребовавшихся для сборки

```toml
windows-sys = { version = "0.59", features = [
    "Win32_Foundation",
    "Win32_NetworkManagement_IpHelper",
    "Win32_Networking_WinSock",
    "Win32_System_Threading",
    "Win32_System_ProcessStatus",
] }
```

Использованы явно: `Win32_Foundation` (HANDLE, ERROR_INSUFFICIENT_BUFFER,
GetLastError, CloseHandle), `Win32_NetworkManagement_IpHelper`
(GetExtendedTcpTable, MIB_TCPTABLE_OWNER_PID, MIB_TCP6TABLE_OWNER_PID,
TCP_TABLE_OWNER_PID_LISTENER), `Win32_Networking_WinSock` (AF_INET, AF_INET6),
`Win32_System_Threading` (OpenProcess, QueryFullProcessImageNameW,
PROCESS_QUERY_LIMITED_INFORMATION). `Win32_System_ProcessStatus` в итоге не
понадобился (QueryFullProcessImageNameW живёт в Threading, не в
ProcessStatus) — можно не добавлять в продукт, если продукт не использует
других функций из этого модуля.
Версия 0.59 — та же, что уже закреплена в `src-tauri/Cargo.toml` продукта
(строка 106), фичи `Win32_Foundation`/`Win32_System_Threading` там уже есть,
`Win32_NetworkManagement_IpHelper` и `Win32_Networking_WinSock` — новые для
продукта, добавлять придётся тому, кто это дело подхватит.

## Ограничения зонда — чего он НЕ доказал

1. **Не проверен явный `ERROR_ACCESS_DENIED` на OpenProcess.** Все
   протестированные процессы (включая PPL/WinTcb) дали либо успех, либо код
   31/87 — ни разу не 5. Возможно, на этой машине не нашлось процесса,
   который реально отказал бы в `PROCESS_QUERY_LIMITED_INFORMATION`.
   Не исключено, что такие процессы существуют (например, часть игровых
   анти-чит драйверов или процессы с явным DACL-запретом), просто их не было
   в перечне слушающих портов этой машины.
2. **Не проверен сценарий нескольких интерактивных пользователей одновременно
   (RDP multi-user)**, хотя в `Cargo.toml` продукта уже упомянут
   `xxhash-rust` для «SID hashing для deterministic per-user port allocation
   (RDP multi-user isolation)» — если у продукта есть сценарий именно
   мульти-сессии, его отдельно не проверяли.
3. **Гонка PID поймана один раз случайно, не воспроизведена систематически.**
   Зонд не запускал контролируемый эксперимент «убить процесс и опросить его
   pid в микросекундном окне» — наблюдение косвенное (два независимых
   прогона в разное время дали разные результаты для одного и того же
   расчётного pid).
4. **Не измерялось поведение под нагрузкой** (сотни/тысячи слушающих
   сокетов) — все замеры на реальной рабочей машине с 44 записями.
5. **Не проверялось поведение в песочнице/контейнере/через RDP-сессию** —
   только обычный интерактивный логон на физической машине.

## Воспроизведение

Исходник: `C:\Users\ackol\AppData\Local\Temp\claude\D--Docs-Aurora-Ai\e7778e7e-2989-47a4-821f-98743e7044b7\scratchpad\probe_tcptable\src\main.rs`
Манифест: `C:\Users\ackol\AppData\Local\Temp\claude\D--Docs-Aurora-Ai\e7778e7e-2989-47a4-821f-98743e7044b7\scratchpad\probe_tcptable\Cargo.toml`

Сборка (Bash, не PowerShell — см. примечание ниже) и запуск:
```bash
export CARGO_TARGET_DIR="D:/cargo-targets/probe-tcptable"
cd "C:/Users/ackol/AppData/Local/Temp/claude/D--Docs-Aurora-Ai/e7778e7e-2989-47a4-821f-98743e7044b7/scratchpad/probe_tcptable"
cargo build --release
"$CARGO_TARGET_DIR/release/probe_tcptable.exe"
```

Бинарь после сборки: `D:\cargo-targets\probe-tcptable\release\probe_tcptable.exe`

**Примечание по среде:** первая попытка сборки через PowerShell-инструмент
упала на сетевой ошибке (`curl failed: [2] Failed initialization
(getaddrinfo() thread failed to start)`) при обращении к crates.io — сеть
недоступна из PowerShell-инструмента в этой среде. Пересборка через Bash-
инструмент прошла без проблем — используйте его для сборки, если будете
воспроизводить.

## Одна ошибка компиляции по пути (для памяти)

`HANDLE` в windows-sys 0.59 — это `*mut c_void`, не `usize`; сравнение
`h == 0` не типизируется, нужно `h.is_null()`.
