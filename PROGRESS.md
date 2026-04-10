# Aurora AI Agency — Progress Tracker

## Фаза 1 — Quick Wins

| # | Задача | Статус | Детали |
|---|--------|--------|--------|
| 1.1 | Кнопка Raw Fingerprint | DONE | `get_raw_fingerprint_hex()` + команда + кнопка с лаймовым акцентом |
| 1.2 | PDF-экспорт через Pandoc | DONE | `convert_to_pdf()` — pandoc + wkhtmltopdf, silent skip |
| 1.3 | Скелет онбординга | DONE | `OnboardingOverlay.svelte` 4 шага + `hasCompletedOnboarding` store |

## Фаза 2 — Core Improvements

| # | Задача | Статус | Детали |
|---|--------|--------|--------|
| 2.1 | История чата | DONE | `history.rs` + 3 команды + авто-загрузка/сохранение + кнопка очистки |
| 2.2 | Метрики использования | DONE | `metrics/collector.rs` + секция в Settings с 4 карточками + сбор в open_cabinet/send_message/export |
| 2.3 | Оценка ответов | DONE | `metrics/ratings.rs` + thumbs up/down виджет в ChatPanel |

## Фаза 3 — Расширение платформы

| # | Задача | Статус | Детали |
|---|--------|--------|--------|
| 3.1 | macOS-fingerprinting | DONE | `#[cfg(target_os = "macos")]` блок: ioreg + diskutil + system_profiler |
| 3.2 | XLSX-экспорт | DONE | `rust_xlsxwriter` + `convert_to_xlsx()` — парсинг MD-таблиц, авто-конвертация |
| 3.3 | Межкабинетный обмен | DONE | `copy_export_to_inbox` + `list_recent_exports` + UI на главной |

## Phase 4 — Production Hardening

| # | Задача | Статус | Детали |
|---|--------|--------|--------|
| 4.1 | Structured logging | DONE | `tauri-plugin-log` + `log` crate, файл `%APPDATA%/ai-agency-gui/logs/ai-agency.log` |
| 4.2 | Error retry logic | DONE | `commands/retry.rs` — retry с exponential backoff для Claude API |
| 4.3 | Update checker | DONE | `commands/updater.rs` — проверка новых версий через JSON manifest |
| 4.4 | DEPLOY.md | DONE | Полное техническое руководство по развёртыванию |

## Phase 5 — CI/CD & Production Deploy

| # | Задача | Статус | Детали |
|---|--------|--------|--------|
| 5.1 | Fix warnings + cleanup | DONE | 8 clippy warnings исправлены → 0 warnings, `[profile.release]` в workspace |
| 5.2 | Update manifest | DONE | `deploy/update-manifest.json` + GitHub Pages `rosst-updates` repo |
| 5.3 | GitHub Actions CI | DONE | `.github/workflows/ci.yml` — test + clippy на push, release build на tag |
| 5.4 | Release builds (.msi/.exe) | DONE | MSI target добавлен в tauri.conf.json, NSIS + MSI |
| 5.5 | License generator CLI | DONE | `tools/license-generator/` — keygen, generate, show-pubkey |

## Изменённые файлы

### Rust (src-tauri/src/)
- `lib.rs` — 10 новых команд, модуль metrics, точки сбора метрик
- `commands/claude.rs` — convert_to_pdf(), convert_to_xlsx(), record_export()
- `crypto/fingerprint.rs` — get_raw_fingerprint_hex(), macOS collect_hw_ids()
- `metrics/mod.rs` — новый модуль
- `metrics/collector.rs` — новый: сбор и хранение usage metrics
- `metrics/ratings.rs` — новый: хранение оценок thumbs up/down
- `session/mod.rs` — подключение history
- `session/history.rs` — новый: save/load/clear chat history

### Svelte (src/)
- `lib/store.js` — hasCompletedOnboarding store
- `lib/components/OnboardingOverlay.svelte` — новый: 4-шаговый онбординг
- `lib/components/ChatPanel.svelte` — история чата, оценки, кнопка очистки
- `routes/+page.svelte` — онбординг + секция межкабинетных экспортов
- `routes/settings/+page.svelte` — Raw Fingerprint кнопка + метрики

### Config
- `src-tauri/Cargo.toml` — rust_xlsxwriter dependency

### Phase 4 — Rust
- `commands/updater.rs` — новый: проверка обновлений через HTTP
- `commands/retry.rs` — новый: retry с exponential backoff
- `lib.rs` — интеграция логирования tauri-plugin-log

### Phase 5 — Config & CI
- `.github/workflows/ci.yml` — новый: CI pipeline (test + clippy + release)
- `deploy/update-manifest.json` — новый: манифест обновлений
- `Cargo.toml` (workspace) — `[profile.release]` перемещён сюда
- `src-tauri/tauri.conf.json` — добавлен MSI target
