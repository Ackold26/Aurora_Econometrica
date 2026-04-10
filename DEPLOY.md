# ROSST AI Agency — Техническое руководство по развёртыванию

**Для:** Claude Code (разработчик, читающий этот файл)
**Проект:** Tauri v2 + SvelteKit 5 + Rust
**Версия:** 0.1.0
**Автор:** А. Сипович

---

## Что это

Десктоп-приложение для Windows. Содержит 7 AI-кабинетов (юридические, креативные, медиааналитические). Каждый кабинет — это набор slash-команд, отправляемых через Claude API. Файлы кабинетов находятся в `New_AI_Agency/<cabinet-id>/CLAUDE.md`.

Архив — это **монолитная версия** (все 8 кабинетов). Из неё разделены 3 продукта:
- `ROSST_AI_Legal` — lawyer-contracts, lawyer-claims, lawyer-advertising
- `ROSST_AI_Creative` — creative-director, communication-strategist
- `ROSST_AI_Media` — media-analyst, communication-analyst

---

## Системные требования

- **Windows 10/11** (x64)
- **Node.js** ≥ 18 (проверить: `node -v`)
- **Rust** (установить через rustup.rs)
- **Tauri CLI** (установится автоматически через npm)
- **WebView2** (предустановлен в Windows 11; для Windows 10 — установщик скачивается при первом запуске)
- Переменная окружения `ANTHROPIC_API_KEY` — ключ Claude API

---

## Шаги развёртывания (dev-режим)

### 1. Распаковать архив

```powershell
# PowerShell
Expand-Archive AI_APP_AGENCY_archive_2026-03-22.zip -DestinationPath C:\Users\<user>\Desktop\
```

### 2. Перейти в папку проекта

```powershell
cd C:\Users\<user>\Desktop\AI_APP_AGENCY
```

### 3. Установить зависимости фронтенда

```powershell
npm install
```

Ожидаемые предупреждения о deprecated пакетах — игнорировать.

### 4. Задать переменную окружения с ключом API

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Или создать файл `.env` в корне (он уже в `.gitignore`):
```
ANTHROPIC_API_KEY=sk-ant-...
```

**Важно:** без ключа приложение запустится, но чат не будет работать (Rust вернёт ошибку при вызове Claude API).

### 5. Запустить в dev-режиме

```powershell
npm run tauri dev
```

Первый запуск компилирует Rust — занимает 3–7 минут. Повторные запуски быстрее.

Откроется окно 1080×720 с главной страницей ROSST AI Agency.

---

## Структура проекта

```
AI_APP_AGENCY/
├── .github/workflows/ci.yml    # CI pipeline (test + clippy + release)
├── deploy/
│   └── update-manifest.json    # Манифест обновлений
├── tools/
│   ├── license-generator/      # CLI генерации лицензий
│   ├── vault-packer/           # Упаковка кабинетов в vault
│   └── get-fingerprint/        # Получение fingerprint машины
├── src/                          # SvelteKit фронтенд
│   ├── app.css                   # AETHER MESH дизайн-система (CSS custom properties)
│   ├── app.html                  # HTML shell
│   └── routes/
│       ├── +page.svelte          # Главная (список кабинетов)
│       ├── cabinet/+page.svelte  # Рабочее пространство кабинета
│       └── settings/+page.svelte # Настройки, лицензия
│   lib/
│       ├── store.js              # Svelte 5 stores (activeCabinet, messages)
│       └── components/
│           ├── AetherLogo.svelte   # SVG-логотип с анимацией
│           ├── CabinetCard.svelte  # Карточка кабинета (SVG iconMap)
│           ├── ChatPanel.svelte    # Чат (markdown, copy, timestamps)
│           ├── CommandPanel.svelte # Панель slash-команд
│           ├── DigitalClock.svelte # Часы МСК
│           └── FileList.svelte     # Список файлов / drag-and-drop
│
├── src-tauri/                    # Rust бэкенд
│   ├── Cargo.toml
│   ├── tauri.conf.json           # Конфиг приложения
│   ├── help/                     # HTML-справка по каждому кабинету
│   └── src/
│       ├── lib.rs                # Точка входа, регистрация команд
│       └── commands/
│           ├── cabinet.rs        # get_cabinet_definitions(), get_commands_for_cabinet()
│           ├── claude.rs         # Вызов Claude API (streaming)
│           ├── file_ops.rs       # Работа с файлами, экспорт .md/.docx/.xlsx
│           ├── license.rs        # Лицензионная проверка (get_machine_id, import_license)
│           ├── updater.rs       # Проверка обновлений (check_for_updates)
│           └── retry.rs         # Retry с exponential backoff
│       ├── session/
│       │   ├── manager.rs       # Управление сессиями
│       │   └── history.rs       # Сохранение/загрузка истории чата
│       └── metrics/
│           ├── collector.rs     # Метрики использования
│           └── ratings.rs       # Оценки ответов (thumbs up/down)
│
└── New_AI_Agency/                # Кабинеты (CLAUDE.md с командами)
    ├── lawyer-contracts/
    │   └── CLAUDE.md             # Инструкции + slash-команды для кабинета
    ├── lawyer-claims/
    ├── lawyer-advertising/
    ├── creative-director/
    ├── communication-strategist/
    ├── media-analyst/
    └── communication-analyst/
```

---

## Ключевые технические детали

### Фронтенд

- **SvelteKit 5** с рунами: `$state()`, `$effect()`, `$props()`
- **Нет Tailwind** — только CSS custom properties (все токены в `app.css`)
- **Glassmorphism**: `backdrop-filter: blur()`, rgba-фоны, `--bg-glass`, `--glass-blur`
- **Markdown**: `marked` + `DOMPurify`, рендерится через `{@html}` + `:global()` CSS
- **color-mix() не используется** — заменён на rgba() для совместимости с WebView2 Windows 10

### Rust / Tauri

- **Tauri v2** (не v1!)
- Команды регистрируются в `lib.rs` через `tauri::Builder::default().invoke_handler(...)`
- `cabinet.rs` — единственный файл для разделения приложений. Вся логика кабинетов там.
- `claude.rs` — стриминг ответа через `tauri::Emitter`, событие `claude-stream`
- Лицензия: `license.rs` читает/пишет `~/.rosst/license.json`, проверяет подпись ed25519
- **Кабинеты фильтруются по лицензии** — 4-шаговая валидация: загрузка лицензии → проверка подписи ed25519 → проверка срока действия → фильтрация `cabinet_id` по полю `cabinets` в лицензии. В DEV-режиме (`AIAGENCY_DEV=1`) проверка отключается.

### Переменная окружения API-ключа

Rust читает ключ через `std::env::var("ANTHROPIC_API_KEY")` в `claude.rs`. В dev-режиме Tauri наследует переменные окружения от родительского процесса PowerShell.

---

## Сборка продакшн-установщика (.msi / .exe)

```powershell
npm run tauri build
```

Результат: `src-tauri/target/release/bundle/`
- `nsis/AURORA AI AGENCY - ROSST_0.1.0_x64-setup.exe`
- `msi/AURORA AI AGENCY - ROSST_0.1.0_x64_en-US.msi`

Сборка занимает 5–15 минут (LTO включён в `Cargo.toml`).

---

## Запуск тестов Rust

```powershell
cd src-tauri
cargo test
```

Ожидаемые результаты (монолит — 8 кабинетов):
```
test all_seven_cabinets_defined ... ok
test cabinet_ids_are_valid ... ok
test every_cabinet_has_commands ... ok
test command_counts_per_cabinet ... ok
test unknown_cabinet_returns_no_commands ... ok
test all_commands_start_with_slash ... ok
test cabinet_folder_name_is_identity ... ok
test all_cabinets_have_color ... ok
... (ещё 12 тестов: retry, updater, metrics, session, file_ops и др.)

test result: ok. 20 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

---

## CI/CD

GitHub Actions конфигурация: `.github/workflows/ci.yml`

### На каждый push / PR в master:
- `cargo test` — 20 тестов
- `cargo clippy -- -D warnings` — 0 предупреждений

### На tag `v*`:
- Полная сборка release (.exe + .msi)
- Загрузка артефактов в GitHub Releases (draft)

### Проверка обновлений

Приложение проверяет `https://ackold26.github.io/rosst-updates/ai-agency-gui/latest.json`.
Манифест управляется в репозитории [rosst-updates](https://github.com/Ackold26/rosst-updates).
Шаблон: `deploy/update-manifest.json`.

---

## Частые проблемы

| Проблема | Причина | Решение |
|---|---|---|
| `ANTHROPIC_API_KEY not found` | Ключ не задан | `$env:ANTHROPIC_API_KEY = "sk-ant-..."` |
| `WRY_WEBVIEW2_DOWNLOAD_ERROR` | Нет WebView2 | Установить Microsoft Edge WebView2 Runtime |
| `error: linker 'link.exe' not found` | Нет Visual Studio Build Tools | Установить VS Build Tools 2022 с компонентом C++ |
| Первая сборка зависла на 5+ мин | Cargo компилирует ~200 крейтов | Ждать, это нормально |
| Кириллица в PowerShell — кракозябры | UTF-8 проблема | Запустить `chcp 65001` перед командами |

---

## Разделение на 3 приложения

Если нужно снова разделить монолит на 3 продукта — см. план `reactive-questing-wilkinson.md` в папке памяти Claude или выполни следующее:

1. Скопировать папку 3 раза
2. В каждой копии изменить:
   - `src-tauri/tauri.conf.json` → productName, identifier, title
   - `src-tauri/Cargo.toml` → package name, lib name
   - `src-tauri/src/commands/cabinet.rs` → оставить только нужные кабинеты + обновить тесты
   - `src-tauri/help/` → удалить лишние HTML
   - `New_AI_Agency/` → удалить лишние папки кабинетов
   - `src/routes/+page.svelte` → brand-sub текст
   - `src/routes/settings/+page.svelte` → версия приложения
