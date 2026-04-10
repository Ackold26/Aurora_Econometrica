# Архитектура AI Agency / ROSST AI

**Дата:** 2026-03-30
**Версия:** v0.3.2 — per-app storage, WebView2 error handling, Svelte 5 fix

---

## Стек

| Слой | Технология |
|------|-----------|
| Desktop shell | Tauri v2 |
| Frontend | SvelteKit 5 + TypeScript |
| Backend | Rust (через Tauri commands) |
| AI движок | Claude CLI (`@anthropic-ai/claude-code`) |
| Лицензирование | Ed25519 (библиотека `ed25519-dalek`) |
| Шифрование vault | AES-256-GCM + HKDF-SHA256 |
| Fingerprint | WMI (Win32_ComputerSystemProduct, DiskDrive, BaseBoard) |
| Упаковщик vault | `vault-pack.exe` (отдельный Rust-бинарник) |
| Генератор лицензий | `gen_license.py` (Python, Ed25519 через `cryptography`) |

---

## Продукты и кабинеты

```
AI Agency (один установщик, 11 кабинетов)
├── lawyer-contracts       Юрист — Договоры
├── lawyer-claims          Юрист — Претензии
├── lawyer-advertising     Юрист — Реклама
├── doc-master             Доку-мастер
├── creative-director      Креативный директор   → vault: creative-group.vault
├── communication-strategist  Коммуникационный стратег
├── media-analyst          Медиа-аналитик
├── communication-analyst  Коммуникационный аналитик
└── social-listening       Social Listening

ROSST AI Legal (отдельный установщик, 3 кабинета)
├── lawyer-contracts
├── lawyer-claims
└── lawyer-advertising

ROSST AI Creative (отдельный установщик, 3 кабинета)
├── creative-director      → vault: creative-group.vault
├── communication-strategist
└── focus-groups           → vault: focus-groups.vault

ROSST AI Insights Hub (отдельный установщик, 4 кабинета)
├── media-analyst
├── communication-analyst
├── social-listening
└── econometrist
```

> Кодовая база идентична — различие только в `cabinet.rs` (какие кабинеты возвращает `get_cabinet_definitions()`), `tauri.conf.json` (имя приложения, идентификатор) и публичном ключе Ed25519.

---

## Структура проекта (на примере AI_APP_AGENCY)

```
AI_APP_AGENCY/
├── src/                              # SvelteKit фронтенд
│   ├── app.css                       # Глобальные стили (AETHER MESH тёмная тема)
│   ├── lib/components/
│   │   ├── CabinetCard.svelte        # Карточка кабинета на главной
│   │   ├── ChatPanel.svelte          # Чат с Claude (markdown, копирование, стриминг)
│   │   ├── CommandPanel.svelte       # Панель быстрых команд
│   │   └── FileList.svelte           # Входящие файлы и экспорты
│   └── routes/
│       ├── +page.svelte              # Главная (список кабинетов)
│       ├── cabinet/+page.svelte      # Страница кабинета с чатом
│       └── settings/+page.svelte     # Настройки, лицензия, Machine ID
│
├── src-tauri/
│   ├── src/
│   │   ├── lib.rs                    # Точка входа, регистрация Tauri-команд
│   │   ├── commands/
│   │   │   ├── cabinet.rs            # ← ГЛАВНЫЙ: определения кабинетов, get_cabinet_definitions()
│   │   │   ├── claude.rs             # Запуск Claude CLI, стриминг через Tauri events
│   │   │   ├── license.rs            # Загрузка, валидация и кэш лицензии
│   │   │   └── vault.rs              # Дешифрование vault-файлов при открытии кабинета
│   │   ├── crypto/
│   │   │   ├── ed25519.rs            # PUBLIC_KEY_BYTES + verify_license_signature()
│   │   │   ├── fingerprint.rs        # get_machine_fingerprint() → SHA-256(UUID|disk|board)
│   │   │   ├── aes.rs                # aes_256_gcm_decrypt()
│   │   │   └── hkdf.rs               # derive_vault_key(raw_fp, license_id)
│   │   └── session/
│   │       └── manager.rs            # Управление рабочими сессиями Claude (inbox/exports)
│   ├── help/                         # HTML-справки для каждого кабинета
│   │   └── <cabinet-id>.html
│   ├── tauri.conf.json               # productName, identifier, devUrl, port
│   └── Cargo.toml                    # [package] name, [lib] name — менять при переименовании
│
├── New_AI_Agency/                    # Кабинеты (промпты + команды)
│   ├── <cabinet-id>/
│   │   ├── CLAUDE.md                 # Системный промпт кабинета
│   │   └── .claude/commands/
│   │       └── <command>.md          # Slash-команды (/contract, /cycle и т.д.)
│
├── vite.config.js                    # port: 1420/1421/1422 (разные для каждого ROSST-приложения)
└── package.json
```

---

## Система лицензирования

### Схема
```
Железо машины (UUID + disk + board)
    ↓ SHA-256
Raw fingerprint (32 байта hex)
    ↓ SHA-256
Hash fingerprint (32 байта hex) → в license.json → верифицируется Ed25519-подписью
```

### Структура license.json

**Формат единый для всех приложений (Legal, Creative, Media, Agency):**
```json
{
  "cabinets": ["lawyer-contracts", ...],
  "expires_at": "2027-03-24",
  "issued_to": "CompanyName",
  "license_id": "uuid-v4",
  "machine_fingerprint_hash": "64-hex-chars",
  "salt": "random-base64",
  "valid_from": "2026-03-24",
  "signature": "ed25519-base64"
}
```

> **ВАЖНО:** Поле `valid_from` записывается в JSON для информации, но **НЕ входит** в подписываемые данные (canonical JSON).
> Все приложения используют **один** Ed25519 ключ (`rosst_agency_private.key`).
>
> Canonical JSON (подписываемый payload):
> `{"cabinets":[...],"expires_at":"...","issued_to":"...","license_id":"...","machine_fingerprint_hash":"...","salt":"..."}`

> Canonical JSON для верификации — поля в алфавитном порядке, без `signature`.

### Публичный ключ

**Все приложения (Legal, Creative, Media, Agency) используют ОДИН Ed25519 ключ.**

| Публичный ключ (встроен в `ed25519.rs` всех приложений) |
|--------------------------------------------------------|
| `6b75e3b0d151acaf4b7a561219f874caf540ab948f09dfc7633a1bfbbf54db38` |

Приватный ключ — `rosst_agency_private.key`, хранится только в `2_Выдача_лицензий/` и `~/.secrets/`. Не хранить в исходниках.

---

## Vault-система

### Схема шифрования
```
Raw fingerprint клиента
    +
License ID
    ↓ HKDF-SHA256
Vault encryption key
    ↓ AES-256-GCM
<cabinet-id>.vault (зашифрованный архив промптов кабинета)
```

### Особенность creative-director
Vault-pack создаёт файл как `creative-director.vault`, но приложение ищет `creative-group.vault`.
При выдаче клиенту — **обязательное переименование**.

### Хранение на машине клиента (per-app, с v0.3.2)

Каждое приложение хранит лицензию и волты в изолированной директории по `identifier` из `tauri.conf.json`:

```
%APPDATA%\com.aiagency.desktop\          ← Full (11 кабинетов)
├── license.json
└── vaults\
    ├── communication-analyst.vault
    ├── communication-strategist.vault
    ├── creative-group.vault
    ├── focus-groups.vault
    ├── lawyer-advertising.vault
    ├── lawyer-claims.vault
    ├── lawyer-contracts.vault
    ├── media-analyst.vault
    └── social-listening.vault

%APPDATA%\com.rosst.creative\            ← Creative (3 кабинета)
├── license.json
└── vaults\
    ├── creative-group.vault
    ├── communication-strategist.vault
    └── focus-groups.vault

%APPDATA%\com.rosst.legal\               ← Legal (3 кабинета)
├── license.json
└── vaults\...

%APPDATA%\com.rosst.media\               ← Insights Hub (4 кабинета)
├── license.json
└── vaults\...
```

> **Миграция:** при первом запуске v0.3.2 код автоматически проверяет legacy пути (`%APPDATA%\AIAgency\` и `%PROGRAMDATA%\AIAgency\`) и копирует файлы в per-app директорию.

> **Legacy** (до v0.3.1): `%PROGRAMDATA%\AIAgency\vaults\` и `%APPDATA%\AIAgency\license.json` — общие для всех приложений. Новые установки туда ничего не пишут.

---

## Поток данных при запросе в кабинете

```
Пользователь вводит текст
    ↓
ChatPanel.svelte → invoke("run_claude", {cabinet_id, message})
    ↓
claude.rs → создаёт рабочую папку, пишет контекст
    ↓
Запускает: claude --print <message> в папке кабинета
    ↓
Стриминг вывода через Tauri events → ChatPanel
    ↓
Markdown-рендеринг в UI
```

---

## Рабочие папки (на машине пользователя)

```
%USERPROFILE%\Desktop\AIAgency\<cabinet-id>\
├── inbox\      # Входящие файлы (пользователь перетаскивает)
└── exports\    # Файлы созданные Claude
```

В DEV: кабинет читает промпты из `AIAGENCY_DEV_CABINETS/<cabinet-id>/CLAUDE.md`.
В продакшне: промпты из дешифрованного vault-файла.
