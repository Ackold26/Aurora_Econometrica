# PULSE — инвентаризация маршрута/egress (Aurora Econometrica thinwt)

## Задача (своими словами)
Владелец хочет свести три текущих маршрута работы ИИ-ассистента к двум (Полностью локально / Через шлюз Авроры) и убрать вариант с локально установленным Claude Code клиента. Перед правкой нужна точная карта того, что есть сейчас: только чтение, без сборки и правок. Разделы: А — механизм выбора маршрута (execution_mode.rs), Б — путь ассистента (claude.rs, ветка cloud_advisors), В — полный список исходящих сетевых обращений (egress) с гейтами, Г — различие сборок thin/local.

## План
1. Раздел А: execution_mode.rs — типы режимов, resolve/decide_with_history, хранение состояния, все match/if по режиму (backend+frontend).
2. Раздел Б: claude.rs — run_claude_inner, ветка шлюза, границы cloud_advisors.
3. Раздел В: egress-поиск по reqwest/fetch/requests/доменам + capabilities/tauri.conf.json + гейты (ensure_not_local_only и т.п.) + cloud_advisors.
4. Раздел Г: package.json скрипты tauri:build:thin/local, различия признаков, рантайм-определение редакции.
5. Записать всё в Projects/mode_inventory.md по ходу, отметки времени после каждого раздела.

Старт: 10 сен 2026 г. 23:25 (см. date выше)

## Завершено
Все 4 раздела записаны в Projects/mode_inventory.md. Финал: 10.09.2026 ~00:20 (по часам машины уже 11.09).
