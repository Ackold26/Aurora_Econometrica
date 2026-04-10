# AI Agency Desktop

Десктопное приложение для работы с AI-кабинетами. Каждый кабинет — изолированная среда с системным промптом, входящими файлами, историей диалога и экспортами.

**Стек:** Tauri v2 + SvelteKit 5 + Rust

---

## Требования

- [Node.js LTS](https://nodejs.org/) — установить в `D:\Program Files\nodejs`
- [Rust (stable-msvc)](https://rustup.rs/) — `winget install Rustlang.Rustup`
- Rust target: `stable-x86_64-pc-windows-msvc`

## Установка

```powershell
cd path\to\AI_APP_AGENCY
npm install
```

---

## Запуск в dev-режиме

Dev-режим работает без лицензии и vault — кабинеты читаются напрямую из `New_AI_Agency/`.

```powershell
$env:AIAGENCY_DEV = "1"
$env:AIAGENCY_DEV_CABINETS = ".\New_AI_Agency"
npm run tauri dev
```

Логи пишутся в: `%APPDATA%\ai-agency-gui\logs\ai-agency.log`

---

## CI/CD

Проект использует GitHub Actions для автоматизации:
- **На каждый push/PR:** `cargo test` + `cargo clippy -- -D warnings`
- **На tag `v*`:** автосборка .exe/.msi + загрузка в GitHub Releases

Конфигурация: `.github/workflows/ci.yml`

---

## Проверка обновлений

Приложение проверяет наличие обновлений через манифест:
`https://ackold26.github.io/rosst-updates/ai-agency-gui/latest.json`

Манифест хранится в репозитории [rosst-updates](https://github.com/Ackold26/rosst-updates).

---

## Структура кабинетов

```
New_AI_Agency/
  {cabinet_id}/
    CLAUDE.md          ← системный промпт кабинета
    .claude/           ← опционально: skills, settings
```

Рабочие данные (создаются при открытии кабинета):
```
%USERPROFILE%\Desktop\AIAgency\
  {cabinet_id}/
    inbox/             ← входящие файлы
    exports/           ← результаты работы
```

### Кабинеты

| ID | Название | Назначение |
|----|----------|------------|
| `communication-analyst` | Коммуникационный аналитик | Анализ медиаполя, мониторинг упоминаний |
| `media-analyst` | Медиа-аналитик | Комментарии к pptx (Tier-1 стандарт) |
| `communication-strategist` | Коммуникационный стратег | Стратегия, позиционирование, бриф |
| `creative-director` | Креативный директор | Концепции, Big Idea, Cannes-калибровка |
| `lawyer-contracts` | Юрист — Договоры | Анализ договоров, протоколы разногласий |
| `lawyer-claims` | Юрист — Претензии и NDA | Претензии, ответы, NDA |
| `lawyer-advertising` | Юрист — Реклама | Проверка по 38-ФЗ, ОРД, ЦБ РФ |

---

## Продакшн сборка

### Подготовка (один раз)

```powershell
# 1. Получить fingerprint машины
tools\get-fingerprint

# 2. Сгенерировать ключевую пару
tools\license-generator keygen

# 3. Выпустить лицензию
tools\license-generator generate

# 4. Упаковать кабинеты в vault
tools\vault-packer pack-all

# 5. Разложить файлы
# vault-файлы → C:\ProgramData\AIAgency\vaults\
# лицензия   → C:\ProgramData\AIAgency\license.json
```

### Сборка инсталлятора

```powershell
npm run tauri build
# Результат: src-tauri/target/release/bundle/nsis/ (.exe) и bundle/msi/ (.msi)
```

---

## Ключевые файлы

| Файл | Назначение |
|------|------------|
| `src-tauri/src/lib.rs` | Все Tauri-команды |
| `src-tauri/src/commands/cabinet.rs` | Список кабинетов и команд |
| `src-tauri/src/session/manager.rs` | Сессии, dev_open_session |
| `src/lib/components/FileList.svelte` | UI файлов, открытие экспортов |
| `New_AI_Agency/*/CLAUDE.md` | Системные промпты кабинетов |
| `src-tauri/help/*.html` | HTML-справки для каждого кабинета |
| `src-tauri/src/commands/updater.rs` | Проверка обновлений |
| `src-tauri/src/commands/retry.rs` | Retry с exponential backoff |
| `src-tauri/src/session/history.rs` | Сохранение/загрузка истории чата |
| `src-tauri/src/metrics/collector.rs` | Метрики использования |
| `.github/workflows/ci.yml` | CI/CD pipeline |
| `deploy/update-manifest.json` | Шаблон манифеста обновлений |
