# Трассировка «meta → jobs»: почему задание не создалось (показ 10.09.2026)

## Что читал
- Поставляемый шлюз: `C:\Users\ackol\.cargo\git\checkouts\aurora-platform-core-646048ec9d057d6a\0e14284\aurora_gateway\src\cloud\{client,protocol,sse,progress}.rs`, метка v0.6.6. Двойник `_wt_gw_v066_backport` НЕ читала — расхождений не сверяла (сообщаю явно).
- Продукт: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt\src-tauri\src\commands\gateway_executor.rs`.

## Промежуточно (23:4x)
- Единственный вызов `meta()` в продукте — `warn_on_cabinets_mismatch` (gateway_executor.rs:1200). Ошибка ПРОГЛАТЫВАЕТСЯ (:1202-1207), путь продолжается. `models` не читается вовсе. Значит meta НЕ ворота.
- Первый сетевой вызов после meta — `create_job_full` → `POST /v1/jobs` (client.rs:672-687, `?`).
- `CloudError::Connection` → ровно тот текст (client.rs:151-155). Возникает и при обрыве, и при «сервис ответил {status}» (client.rs:1020) для статусов Decision::Retry.
- Повторы: attempts = 6 (client.rs:338), паузы 2+5+10+20+30 = 67 с (client.rs:35-41).
