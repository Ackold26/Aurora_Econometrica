# Отчёт s52 – долг Low L-1/L-5 (Rust)

Исполнитель `lowrust` (Sonnet); файл записан оркестратором с его текста – харнесс не даёт субагенту писать файлы
с именем report. Принято оркестратором, записано `3219b0a6`.

Дерево: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt` (master). База: `6981fa04`.

## Текст находок (откуда взят)
`git show 33b79872:Projects/NEXT_SESSION_PROMPT.md` (промт s51, строки 100–103), продублировано в промте s52
строки 31–32: «L-1 тест локальной редакции не различает econometrica/unknown; L-5 журнал засоряется на
"unknown"». Дословного текста в `PULSE_s50_auditor.md` нет – формулировки L-1/L-5 это сводка триажа s50.

## Код
- L-1 – `cabinet.rs::filter_by_product()`: в локальной редакции ветки `"econometrica"` (стр. 123,
  `cfg not cloud_advisors`) и `"unknown"` (стр. 134) обе дают `Some(&[])`; единственный тест локальной
  редакции рядом с функцией проверял только `"econometrica"`.
- L-5 – `online_auth.rs::detect_product()`: при `product == "unknown"` писала `log::error!` на каждый вызов
  (список кабинетов, диагностика, feedback, heartbeat).

## Правка
Только тесты (`cabinet.rs`) + обёртка журнала в `std::sync::Once` (`online_auth.rs`, приватная
`warn_unknown_product_once(once, pkg, emit)`). `map_pkg_to_product` / `filter_by_product` не менялись.
Тесты: `local_edition_unknown_product_gets_zero_cabinets` (только локальная редакция),
`unknown_product_warning_fires_at_most_once_per_once_lifetime` (счётчик вместо `log::error!`: у этого дерева
`CARGO_PKG_NAME` никогда не `unknown`).

## Права ДО/ПОСЛЕ (логика фильтра не менялась; всего кабинетов 13)
| Продукт | Облачная (`cloud_advisors`) ДО / ПОСЛЕ | Локальная (`--no-default-features`) ДО / ПОСЛЕ |
|---|---|---|
| econometrica | 1 (econometrist) / 1 | 0 / 0 |
| unknown | 0 / 0 | 0 / 0 |
| media | 13 (ветка `None`, не трогалась) / 13 | 13 / 13 |
| agency | 13 / 13 | 13 / 13 |

## Мутации
- L-1: `cabinet.rs:134` → `"unknown" => Some(&["econometrist"])` → тест FAILED «unknown получил 1 кабинет(ов)»;
  откат → ok.
- L-5: `online_auth.rs:79` → `emit(pkg)` без `once.call_once` → FAILED left=5 right=1; откат → ok.

## Приёмка
- Локальная редакция (дважды): 563 lib + 12 + 5 + 22 + 7 = **609 passed / 0 failed**
  (`Temp/claude/lowrust_s52_localedition2.log`, EXIT: 0).
- `build-cloud --test`: **638 passed / 0 failed** (`lowrust_s52_buildcloud2.log`, EXIT: 0) = эталон 637 + тест
  L-5; тест L-1 в облачную конфигурацию не компилируется (`cfg not cloud_advisors`) и проверен в локальной.
- 🔴 Ключ подтверждения хвоста сменился: `AURORA_CRATE_TAIL_ACK="aurora_gateway@40d392f=метка не ставится
  намеренно, решение автора записи 7a14c99"`. Хвост тот же (одна запись `7a14c99`), сдвинулась точка отсчёта
  `origin/main`; при следующем отказе ворот брать SHA из текста отказа.

## Не сделано / вне рамок
L-4 (Media, решение владельца), L-6 (закрыт в s51 `cf750054`), ветка `"media" => None` – не трогались.
