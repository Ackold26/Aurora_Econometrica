# Aurora AI — Monorepo (одна кодовая база, 5 product variants)

Этот репозиторий содержит общую кодовую базу для пяти продуктов Aurora AI (Tauri v2 + SvelteKit 5 + Rust). Каждый вариант отличается только `tauri.conf.json` (productName / identifier), `Cargo.toml` (name) и `main.rs` (lib name) — основной код, кабинеты, дизайн-система общие.

## Варианты сборки

| Продукт | Tauri identifier | Кабинеты / pipeline |
|---|---|---|
| **Aurora AI Agency** | `com.aiagency.desktop` | Все 13 кабинетов (117+ команд) |
| **Aurora AI Legal Center** | `com.rosst.legal` | lawyer-contracts, lawyer-claims, lawyer-advertising |
| **Aurora AI Creative Hub** | `com.aurora.creative-hub` | Все 13 кабинетов + Brand Hub (RAG, Parser, Canvas) |
| **Aurora AI Insights Hub** | `com.rosst.media` | media-analyst, communication-analyst, social-listening, econometrist |
| **Aurora AI Econometrica — MMM Optimizer** | `com.aurora.econometrica` | Полный pipeline эконометрического моделирования маркетинг-микса (Import → Validate → Model → Decompose → Optimize → Report) |

> **Aurora AI Econometrica — MMM Optimizer** — флагманский вариант для эконометрического моделирования. Полная справка по продукту: `src-tauri/help-econometrica/`. Документация для пользователя: `docs/USER_GUIDE_v2_1_0.md`. Глоссарий: `docs/GLOSSARY_v2_1_0.md`.

**Стек:** Tauri v2 + SvelteKit 5 + Rust

---

## Системные требования (для конечного пользователя)

### Минимальные

- **ОС:** Windows 10 (build 1903+) / Windows 11
- **CPU:** 4 ядра, 2.5 ГГц (Intel Core i5-8xxx / AMD Ryzen 5 2xxx и выше)
- **RAM:** 8 ГБ
- **Диск:** 1.5 ГБ свободно
- **WebView2** (обычно уже установлен в Windows 10+, иначе — автоматом через инсталлятор)

### Рекомендуемые (для быстрого MCMC)

- **CPU:** 6+ ядер, 3.5+ ГГц (Intel i7-12xxx / AMD Ryzen 7 5xxx и выше)
- **RAM:** 16 ГБ
- **MS Visual C++ 2022 Build Tools** — **критично для скорости обучения модели**

> Без C-компилятора PyMC использует Metropolis-sampler (в 3-5 раз медленнее NUTS). Установка:
> ```powershell
> winget install Microsoft.VisualStudio.2022.BuildTools
> ```
> Выбрать workload: «Desktop development with C++» → «MSVC v143» + «Windows SDK».

### Опционально (на будущее, для JAX-backend)

- **CUDA Toolkit 12+** (NVIDIA GPU) — ускорение через NumPyro/JAX. Сейчас не используется, но планируется в roadmap.

---

## Требования для разработки

- [Node.js LTS](https://nodejs.org/) — `winget install OpenJS.NodeJS.LTS`
- [Rust (stable-msvc)](https://rustup.rs/) — `winget install Rustlang.Rustup`
- Rust target: `stable-x86_64-pc-windows-msvc`
- [Python 3.10+](https://www.python.org/) — с установленными:
  - `pip install pymc arviz pandas numpy scipy scikit-learn statsmodels openpyxl python-pptx fastapi uvicorn`
- **MS Visual C++ 2022 Build Tools** — обязательно для компиляции PyTensor под NUTS-sampler

## Установка

```powershell
cd path\to\Aurora_Econometrica
npm install
pip install -r sidecar/econometrica/requirements.txt
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
