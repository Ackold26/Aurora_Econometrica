# Трассировка «meta → jobs»: почему задание не создалось (показ 10.09.2026)

## Что читал
- Поставляемый шлюз: `C:\Users\ackol\.cargo\git\checkouts\aurora-platform-core-646048ec9d057d6a\0e14284\aurora_gateway\src\cloud\{client,protocol,sse,progress}.rs`, метка v0.6.6. Двойник `_wt_gw_v066_backport` НЕ читала — расхождений не сверяла (сообщаю явно).
- Продукт: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt\src-tauri\src\commands\gateway_executor.rs`.

## Промежуточно (23:4x)
- Единственный вызов `meta()` в продукте — `warn_on_cabinets_mismatch` (gateway_executor.rs:1200). Ошибка ПРОГЛАТЫВАЕТСЯ (:1202-1207), путь продолжается. `models` не читается вовсе. Значит meta НЕ ворота.
- Первый сетевой вызов после meta — `create_job_full` → `POST /v1/jobs` (client.rs:672-687, `?`).
- `CloudError::Connection` → ровно тот текст (client.rs:151-155). Возникает и при обрыве, и при «сервис ответил {status}» (client.rs:1020) для статусов Decision::Retry.
- Повторы: attempts = 6 (client.rs:338), паузы 2+5+10+20+30 = 67 с (client.rs:35-41).

---

## Дополнение 23:45 — проверка журналами на этой машине

Искала журнал показа, чтобы закрыть остаток (какой именно отказ пришёл на `POST /v1/jobs`).

**Записей за 10.09.2026 на этой машине нет ни в одном журнале продуктов линейки.** Проверены:
`%LOCALAPPDATA%\com.aurora.econometrica.thin\logs\Optimizer MMM.log` (последняя запись 03.08),
`%LOCALAPPDATA%\com.aurora.econometrica\logs\Optimizer MMM.log` (последняя 09.09 13:07; режим все дни — «ваш Claude Code (автоопределение)», облачного пути нет),
`%LOCALAPPDATA%\com.aurora.econometrica.local\logs\...` (29.08),
`%LOCALAPPDATA%\com.aurora.analytics-hub\logs\Aurora AI Smart Analytica.log` (09.09 13:07).
Вывод: показ шёл на ДРУГОЙ машине, её журнал и закроет вопрос.

**Зато журнал Smart Analytica даёт прямое опровержение «клиент структурно не умеет ставить задания»:** 09.09 на том же входе облачный путь работал трижды подряд.

```
[2026-09-09][09:02:29] gateway_executor: Облачный запрос [media-analyst]: вход=https://rag.auroraai.pro/cloud, метка=tc-media-analyst-e0080bb4
[2026-09-09][09:02:39] gateway_executor: Ответ получен [media-analyst]: 875 байт, задание 67c12f30-6529-49e8-a876-1977d8c5ac9a
[2026-09-09][09:04:43] gateway_executor: Ответ получен [media-analyst]: 1450 байт, задание b34d47d6-cdfd-4e93-a37f-64c803c03b6e
[2026-09-09][09:09:26] gateway_executor: Облачный запрос [media-analyst] ... метка=tc-media-analyst-1ba87c89
[2026-09-09][09:13:50] gateway_executor: Ответ получен [media-analyst]: 43775 байт, задание f840e246-48ea-48f9-bcf7-7812cb0abeca   (264,5 с работы)
```

Значит и адрес с приставкой `/cloud`, и подпись пути, и `POST /v1/jobs` с телом — рабочие. Отказ 10.09 средовой или серверный (посредник, узел, квота, перегрузка), а не структурный порок клиента. Клиентский слой при этом **солгал о нём** — это и есть предмет разбора В2.

🔴 Отдельная деталь для чинки: **Smart Analytica собрана на другой метке шлюза** — `_wt_analytica_cloud\src-tauri\Cargo.cloud.fragment.toml:45` и `_wt_cpd81_analytica\...:45` дают `tag = "aurora_gateway-v0.6.5"`, тогда как Эконометрика на `v0.6.6`. Оба выпуска старше исправления фазы (`NotSent`/`SendPhase`), поэтому ложный текст присутствует в обоих; правка общего слоя потребует поднять метку у ВСЕЙ линейки, а не у одного продукта.
