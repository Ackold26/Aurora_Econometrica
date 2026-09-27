# PULSE s51 — образцы демо-отчёта после правок доли канала

## Задача (пересказ своими словами)
Образцы покупателя (HTML-отчёт + презентация PPTX) в `Projects/_demo_samples_s49/` сняты СТАРЫМ движком. С тех пор в движке правили: (1) 🔴 УТОЧНЕНО team-lead 13:0x — доля канала = ФОРМАТ вывода `contribution_pct`, теперь с одной десятой («87.5%») вместо целого («88%»), число то же самое (НЕ десятикратная разница — если найду ×10, это дефект, не ожидаемая правка); (2) подпись заголовка слайда S7 — «X% медиа-вклада» вместо «X% продаж»; (3) подпись под крупным числом слайда 4 — по измеренной высоте. Нужно: пересобрать движок, снять образцы заново в НОВУЮ папку `Projects/_demo_samples_s51/` (модель переобучить с нуля), проверить 7 пунктов дословными цитатами, положить итог в `checks.json`. В проверке (7) ожидать пары вида «s49: 88% → s51: 87.5%».

## План
1. Убедиться, что процессов движка нет — done, чисто.
2. Сборка: `python build_sidecar.py` из `sidecar/econometrica`, журнал в `Projects/_build_sidecar_s51.log`, ждать до конца (10–20 мин).
3. Проверить свежесть exe и наличие «медиа-вклада» в `strings_ru.json` собранного dist.
4. Скопировать рабочие скрипты прошлой сессии из scratchpad прошлой сессии в `Projects/_demo_samples_s51/_scripts/`, поправить пути, прогнать пайплайн (validate→confirm-media-plan→train→decompose→optimize→scenario→planning/save→backtest→export html→export pptx).
5. Семь проверок с цитатами → `Projects/_demo_samples_s51/checks.json`.
6. Снять процесс движка, tasklist пусто.

🔴 ЗАПРЕТЫ: не трогать `handoff_package/`, `_demo_samples_s49/`, `src-tauri/` (там работает другой исполнитель), исходники движка кроме сборки. Никакого git add/commit/stash/checkout/reset. В дереве уже есть чужие незакоммиченные правки (report.rs, tokens.generated.css и др.) — не мои, не трогаю.

## Отметки
- 12:54:07 — старт, маячок создан, процессов движка нет, приступаю к сборке.
- 12:57:14 — сборка идёт (PyInstaller собирает зависимости, лог растёт). Параллельно скопировала и адаптировала скрипты прогона в `Projects/_demo_samples_s51/_scripts/run_full_s51.py` (пути: DATA_FILE → handoff_package/demo, PROJECT_DIR → `_demo_samples_s51/_project`, OUT_DIR → `_demo_samples_s51`, project_id `demo_fmcg_s51`). Не запускаю движок, пока сборка не закончится.

- 13:06:38 — сборка ЗАВЕРШЕНА, «КОД:0», «[OK] Freshness verified». exe свежий (13:05), `strings_ru.json` содержит «медиа-вклада» в `s07_dominant`. `git diff --stat` по сгенерённым файлам — только `src/tokens.generated.css` (метка времени, 1 строка), остальные три (`aurora_tokens.py`, `aurora_html.css`, `aurora_html_tokens.js`) без диффа.
- 13:08:41 — движок поднят на 8799 (pid 48860), `/health` отвечает ok, версия пакетов подтверждена. Запущен полный конвейер `run_full_s51.py` в фоне (validate→confirm→train→decompose→optimize→scenario→planning/save→backtest→export html→export pptx), журнал `Projects/_demo_samples_s51/run_full_s51.log`.
- 13:09:39 — жду первых строк лога (train на подходе, обучение может занять время).

- 13:10 — train прошёл успешно (44.9с, модель сохранена в `_project/models/latest.pkl`), но шаг decompose упал единичным сетевым таймаутом клиента (WinError 10060) к самому же localhost:8799 — движок не падал, `/health` сразу после ответил ok. Не переобучаю заново (дорого и не нужно): написала `run_continue_s51.py`, продолжает с decompose, используя уже сохранённые `s51_model_data.json`/`s51_validate.json` из scratchpad. Запущен в фоне, журнал `Projects/_demo_samples_s51/run_continue_s51.log`.

- 13:13 — конвейер ЗАВЕРШЁН: «ALL DONE s51 continue», «КОД:0». Файлы записаны: `ПРИМЕР HTML-отчёта.html` (1 154 727 б), `ПРИМЕР_презентации.pptx` (513 726 б, 16 слайдов). Версия exe подтверждена: 2.5.5.0.
- 13:15–13:25 — семь проверок (`Projects/_demo_samples_s51/_scripts/checks_s51.py`), итог в `checks.json` (ключ `0_SUMMARY`). Все PASS, кроме находки в (6): overflow/overlap на слайде 13 pptx — ДОСЕЙЧАШНИЙ дефект, идентичен в старом s49 (не мой, не регрессия правок s51), доложила, не чинила.
- Процесс движка снят (`taskkill /F /PID 48860`), `tasklist | grep econometrica` — пусто.

## ИТОГ
Образцы сняты в `Projects/_demo_samples_s51/`, все семь проверок прошли (шесть PASS, одна нашла досейчашний дефект overflow/overlap слайда 13, идентичный в s49 — не регрессия). Движок собран (2.5.5.0), процесс остановлен. Полная таблица проверок — в ответе team-lead.
