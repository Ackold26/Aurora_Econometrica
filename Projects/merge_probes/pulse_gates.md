# Пульс: базовая линия гейтов перед слияниями

## Задача своими словами
Снимаю базовую линию проверок в рабочем дереве Aurora_Econometrica_canon (ветка feat/econ-canon-p0, HEAD ed73f21) перед серией слияний веток. Ничего не чиню, ничего не коммичу, ветки не переключаю — только запускаю прогоны и записываю точные числа: Rust-тесты, фронт-тесты, проверку типов, список активных git-крючков, версии продукта. Результат — файл baseline_gates.md с таблицей, чтобы после каждого слияния можно было прогнать то же самое и сверить.

## План
1. Rust-тесты: `cargo test` в src-tauri (учесть возможный кастомный target-каталог из .cargo/config.toml).
2. Фронт-тесты: найти скрипт в package.json (vitest, неинтерактивный режим `run`).
3. Проверка типов: `npm run check` (svelte-check).
4. Крючки: осмотреть .git/hooks и/или .husky, прочитать содержимое активных.
5. Версии: version из src-tauri/tauri.conf.json и package.json.
6. Свести всё в Projects/merge_probes/baseline_gates.md.

## Старт
2026-08-04, начинаю.

## Ход работы
- Это worktree репозитория D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica (git-dir подтверждён через `git rev-parse --git-common-dir`).
- Cargo-workspace в корне (Cargo.toml с members: src-tauri, tools/license-generator, tools/vault-packer, tools/get-fingerprint). Локальный `target/` уже существует в корне (создан 2026-08-02) — использую его по умолчанию, CARGO_TARGET_DIR не переопределяю (не найдено ни .cargo/config.toml, ни установленной переменной окружения в сессии — только documented-конвенция в CLAUDE.md на общий "D:/cargo-targets/ai-agency", который делят другие параллельные агенты этой же сессии; решила НЕ шарить его во избежание конкуренции за лок с другими воркерами).
- Git-крючки: реальный .git/hooks у общего репозитория (worktrees/Aurora_Econometrica_canon) — установлены lefthook'ом `pre-commit` и `prepare-commit-msg`. В lefthook.yml сконфигурирован только `pre-commit` (9 команд), `prepare-commit-msg` — пустой lefthook-диспетчер без команд в конфиге.
- Версии сверены: package.json = 2.4.4, src-tauri/tauri.conf.json = 2.4.4 — совпадают.
- npm-скрипты: тесты `npm test` = `vitest run`, проверка типов `npm run check` = `svelte-kit sync && svelte-check --tsconfig ./jsconfig.json`.

начинаю cargo test, ожидаю до 15 минут без отметок.

Параллельно запущены (не делят target-каталог с cargo, конфликта нет):
- `npm test` (vitest run) — ожидаю до 10 минут без отметок.
- `npm run check` (svelte-check) — ожидаю до 10 минут без отметок.

Все три прогона идут одновременно в фоне, жду завершения.
