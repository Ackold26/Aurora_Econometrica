# PULSE — трассировка обрыва meta → jobs (agent: gateway-debt-trace)

## Задача своими словами
На показе 10.09 ассистент Эконометрики после переключения на облако сходил только `GET /cloud/v1/meta` (200, 281 б) и НЕ отправил `POST /cloud/v1/jobs`. Пользователю показали ложное «Работа на сервере продолжается». Нужно по коду (только чтение) найти: что клиент делает с ответом meta и где тихо обрывает путь (В1), откуда берётся ложный текст без идентификатора задания (В2), какая комбинация таймаутов даёт ~60 с ожидания без отправки запроса (В3).

## План
1. Опознать дерево платформы, совпадающее с поставкой (по строке из `client.rs:151`, git log, версии).
2. Прочитать `aurora_gateway/src/cloud/client.rs` целиком + вызывающий код.
3. Клиентская сторона продукта: `src-tauri/src/` (claude.rs / execution_mode / вызовы шлюза) + фронтенд `src/`.
4. Выписать точки тихого обрыва; проверить каждую на опровержение.
5. Отчёт по ходу в `Projects/gateway_debt_trace.md`.

## Журнал
- 2026-09-10 23:18:45 — старт, маячок создан.
- 23:26 — дерево поставки опознано: метка `aurora_gateway-v0.6.6` = коммит `0e14284`; исходник поставки лежит в cargo-кеше `C:\Users\ackol\.cargo\git\checkouts\aurora-platform-core-646048ec9d057d6a\0e14284\aurora_gateway\`. Рабочее дерево-двойник — `_wt_gw_v066_backport` (ветка fix/gateway-utf8-backport-v0.6.6, HEAD 8d4db91, +sse.rs поверх метки). Дальше — чтение client.rs/protocol.rs + gateway_executor.rs продукта (тихая фаза ~10 мин).
- 23:32:29 - otchet Projects/gateway_debt_trace.md zapisan celikom: V1 ustanovleno (meta ne upravlyaet marshrutom; models i contract_version ne chitayutsya vovse), V2 ustanovleno (client.rs:151 cherez gateway_executor.rs:1006; faza otpravki v postavke ne razlichaetsya - vid NotSent poyavilsya POSLE metki), V3 ustanovleno (~67 s = summa pauz 2+5+10+20+30 pri shesti bystryh otkazah POST /v1/jobs, a ne read timeout). Ostatok: pochemu POST bystro otbivalsya - zakryvaetsya zhurnalom produkta (gateway_executor.rs:1004) i zhurnalom vhodnogo posrednika.
- 23:34:55 - dopolnenie: zhurnalov za 10.09 na etoy mashine net (pokaz byl na drugoy); zhurnal Smart Analytica dokazal, chto 09.09 POST /jobs na tot zhe vhod prohodil trizhdy. Smart Analytica sobrana na metke v0.6.5 (Ekonometrika - v0.6.6).
- 23:38:14 - fayl vosstanovlen posle gonki: parallelnyy agent zatyor otchyot v 23:34, ego chernovik sohranyon v Prilozhenii B + kopiya gateway_debt_trace_OTHER_AGENT_backup.md. Polnyy otchyot perezapisan.
- 23:58:22 - polnyy otchyot perenesyon v Projects/gateway_debt_trace_A_full.md (gateway_debt_trace.md bolshe ne trogayu). Dobavleno: 5 mest samootmeny s usloviyami (bez cheloveka srabatyvayut tolko dva) i razbor metki v0.6.7.
