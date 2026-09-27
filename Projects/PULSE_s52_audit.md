ЕСЛИ МЕНЯ ОБОРВЁТ: git diff + строки МУТАЦИЯ

# Пульс внешнего аудита s52

Задача: внешний аудит `git diff 85e94bd9..HEAD -- . ':!Projects'` (1586e4e6, 8d3b8216, 3219b0a6) перед выпуском 2.5.6. Главное – хук установщика NSIS (удаление хвостов движка): порядок в шаблоне Tauri, границы RMDir /r, защиты, кодировка, currentUser. Отчёт – `Projects/AUDIT_s52_external.md`, правок в коде нет.

План: 1) прочитать дифф; 2) шаблон Tauri – место PREINSTALL/PREUNINSTALL; 3) стенд makensis – junction, пограничные INSTDIR, кодировка, !error; 4) command-meta.js таблица + тесты; 5) frontier.py границы; 6) Rust Once/тесты; 7) отчёт.

- 2026-09-27 14:39:13 – старт
- 2026-09-27 14:53:13 – дифф прочитан; шаблон Tauri (cargo-targets/econometrica, 14.09): PREINSTALL после SetOutPath, до CheckIfAppIsRunning и распаковки; PREUNINSTALL до Delete exe. Кодировка хука – BOM+CRLF.
- 2026-09-27 14:53:13 – стенд audit_s52: !error при MAINBINARYNAME после include – срабатывает; RMDir /r ИДЁТ ПО JUNCTION (жертва опустошена, контроль цел); ручное GUI-обновление 2.5.5→2.5.6 – очистка пропущена (хвосты целы); rd /s /q junction не проходит.
- 2026-09-27 14:53:13 – Rust: Once съедается до регистрации журнала (зонд onceprobe: 0 строк против 1 в контроле). vitest command-meta 7/7, pytest frontier 10/10; cargo test в фоне.
- 2026-09-27 14:58:00 – cargo test: default 1/1, --no-default-features 2/2 зелёные; L-1 тест не гоняется гейтами. Мутаций в коде дерева не вносилось (git diff по предмету чист).
- 2026-09-27 14:58:00 – отчёт Projects/AUDIT_s52_external.md записан: вердикт «годен к сборке», Medium ×3 (M-1 GUI-обновление без очистки, M-2 RMDir /r по junction, M-3 Once до журнала), Low ×4.
ГОТОВО
