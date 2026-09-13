# Отчёт: разнос задания «передаточный пакет» по пяти программам — 13.09.2026

## Таблица

| Программа | Дерево | Ветка | Последняя запись | Куда положена записка | Врезка в NEXT_SESSION_PROMPT |
|---|---|---|---|---|---|
| Docs Lab | `D:\Docs\Aurora_Ai\Dev\ROSST_AI_DocMaster` (productName «Aurora AI Docs Lab») | `feat/rag-core-adopt`, ahead 30 | 13.09.2026 19:41 | `Projects/ЗАДАЧА_передаточный_пакет_2026-09-13.md` | Да — в `Projects/NEXT_SESSION_PROMPT.md` |
| PR Studio | `D:\Docs\Aurora_Ai\Dev\Aurora_PR_Master` (productName «Aurora AI PR Master») | `fix/updater-is-newer-prerelease`, ahead 1 | 28.08.2026 22:58 | `Projects/ЗАДАЧА_передаточный_пакет_2026-09-13.md` (папку `Projects/` создала) | Нет — файла NEXT_SESSION_PROMPT* в дереве нет |
| Media Radar | `D:\Docs\Aurora_Ai\Dev\Aurora_Parser` (productName «Aurora AI Parser») | `fix/updater-is-newer-prerelease`, ahead 1 | 05.09.2026 15:19 | `Projects/ЗАДАЧА_передаточный_пакет_2026-09-13.md` (папку `Projects/` создала) | Нет — файла NEXT_SESSION_PROMPT* в дереве нет |
| Launch Planner | `D:\Docs\Aurora_Ai\Aurora Launch` (productName «Aurora Launch», репо `aurora-launch`) | `fix/autosave-timer-flake-72` | 30.07.2026 13:48 | `Projects/ЗАДАЧА_передаточный_пакет_2026-09-13.md` | Нет — файла NEXT_SESSION_PROMPT* в дереве нет |
| Data Studio | `D:\Docs\Aurora_Ai\Aurora Data Studio` (productName «Aurora Data Studio») | `release/v1.0.1` | 30.05.2026 00:00 | `Projects/ЗАДАЧА_передаточный_пакет_2026-09-13.md` (папку `Projects/` создала — исходно файл лежал в корне) | Да — в корневом `NEXT_SESSION_PROMPT.md` |

## Определение деревьев — без сомнений

По каждой из пяти программ нашёлся ровно один живой кандидат с `tauri.conf.json` и
подтверждённым `productName`. Единственная точка, где сначала показалось два кандидата на
Media Radar (`Aurora_Parser` и `ROSST_AI_Media`) — снята чтением `productName`:
`ROSST_AI_Media` оказался деревом **Smart Analytica** (`productName: "Aurora AI Smart
Analytica"`), а не Media Radar; она уже получила задание напрямую и не трогалась. Media
Radar — только `Aurora_Parser`.

Случаев, требующих решения человека (два подлинно живых кандидата на одну программу), — нет.

## Что не удалось / оговорки

- **Docs Lab и Media Radar показали коммиты сегодня же** (19:41 и обратил внимание также у
  Smart Analytica 19:45) — похоже, что по этим деревьям в момент разноса шла или недавно
  закончилась живая сессия. Задание всё равно положено по прямому указанию — но если сессия
  на Docs Lab ещё активна, записку может не подхватить «первым делом» (она не в диалоге, а
  на диске); стоит убедиться отдельно, что программа её увидела.
- **Антивирусный пункт про расчётный модуль** — включила только для Media Radar (в дереве
  есть `sidecar/`); для остальных четырёх (Docs Lab, PR Studio, Launch Planner, Data Studio)
  проверила — каталога `sidecar/` нет, пункт исключён по факту, не по умолчанию.
- **Коммитов не делала нигде** — все записки и обе врезки лежат неотслеживаемыми файлами
  (`git status` подтверждает `??` / изменённый без стейджа `NEXT_SESSION_PROMPT.md` у Docs
  Lab и Data Studio).
- Демо-материал для Data Studio в каноне не описан отдельной строкой — в записке дала
  рекомендацию (сырой «грязный» набор данных на входе) с явной пометкой, что решение
  оставлено программе, как и просил канон.

## Итог

5 из 5 программ покрыты запиской, папки на рабочем столе созданы для всех пяти. Сомнение
одно — не столько в выборе дерева (он однозначен), сколько в том, что по Docs Lab и Media
Radar сегодня уже была активность в тех же деревьях: стоит свериться, не идёт ли по ним
сейчас параллельная сессия, которая пакет уже начала или которую записка не застанет
«первым делом».
