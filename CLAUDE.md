# CLAUDE.md — Aurora AI (v0.7.0 + UX Redesign v2.0)

Десктопное приложение для работы с Claude AI через специализированные «кабинеты».
Tauri v2 + SvelteKit 5 + JS (JSDoc, НЕ TypeScript) + Rust.

## UX Architecture (v2.0)

**Workspace-first** — не чат с обвесом, а профессиональный workspace.

- **NavRail** (`NavRail.svelte`): adaptive nav — hidden (1 кабинет) / tabs (2-5) / sidebar (6+)
- **Selection/Execution modes** (`cabinet/+page.svelte`): grid команд ↔ chat response
- **CommandGrid** + **CommandCard**: визуальные карточки с tooltip, smart highlighting, groups
- **Structured responses**: markdown ## → collapsible секции + Mini-TOC
- **command-meta.js**: описания, категории, file-aware metadata (JS-side, не Rust)
- **Layout**: AppShell flex (column для tabs, row для sidebar) в `+layout.svelte`
- **Glass tiers**: `--bg-surface-quiet` (0.92, blur 8px) vs `--bg-surface-focus` (0.72, blur 24px)

## Продукты (один код, разные конфиги)

| Продукт | Identifier | Кабинеты |
|---------|------------|----------|
| Aurora AI Agency | `com.aiagency.desktop` | Все 13 (117+ команд) |
| Aurora AI Legal | `com.rosst.legal` | lawyer-contracts, lawyer-claims, lawyer-advertising |
| Aurora AI Creative | `com.rosst.creative` | creative-director, communication-strategist, focus-groups |
| Aurora AI Insights Hub | `com.rosst.media` | media-analyst, communication-analyst, social-listening, econometrist |
| Aurora AI Creative Hub | `com.aurora.creative-hub` | Все 13 + Brand Hub (RAG, Parser, Canvas) |

Варианты отличаются ТОЛЬКО: `tauri.conf.json` (productName, identifier), `Cargo.toml` (name), `main.rs` (lib name).

---

## КРИТИЧЕСКИЕ ПРАВИЛА (выучены на ошибках)

### 1. vite.config.js — НЕ ЛОМАТЬ resolve.conditions
```js
// ПРАВИЛЬНО (только в test mode):
...(mode === 'test' ? { resolve: { conditions: ['browser', 'svelte', 'node'] } } : {}),

// НЕПРАВИЛЬНО (ломает Svelte 5 module resolution в production):
resolve: { conditions: mode === 'test' ? [...] : [] },  // ← пустой [] убивает subscribe()
```

### 2. ChatPanel onMount — ТОЛЬКО синхронный
```js
// ПРАВИЛЬНО:
onMount(() => {
    const unsubCommand = pendingCommand.subscribe(...);  // ← ДО async
    (async () => { await loadHistory(); ... })();         // ← async в IIFE
    return () => { unsubCommand(); };                     // ← sync cleanup
});

// НЕПРАВИЛЬНО (subscribe не работает):
onMount(async () => { ... });  // ← Svelte 5 не поддерживает async cleanup return
```

### 3. vault-pack --fingerprint — SHA-256, НЕ raw hex
```
Raw hex (~200 символов, из приложения "Raw fingerprint")
  → SHA256 покомпонентно с trailing "|"
  → FINGERPRINT (64 символа) ← ЭТО передавать в vault-pack --fingerprint
    → SHA256
    → HASH (64 символа) ← ЭТО передавать в gen_license.py
```
Путаница raw hex / fingerprint / hash — самая частая ошибка. См. `2_Выдача_лицензий/CLAUDE.md`.

### 4. Vault tar extraction — НЕ set_overwrite(false)
В `session/manager.rs` tar-архивы vault'ов начинаются с записи `"."`. `set_overwrite(false)` молча блокирует всю распаковку. Вместо этого — skip для `"."/"./"`

### 5. Claude CLI path — USERPROFILE в trusted prefixes
Claude CLI может стоять в `~/.local/bin/` — это `USERPROFILE`, не `APPDATA`. Без этого `find_claude_binary()` отклонит бинарник.

### 6. Синхронизация 4 репо — ОБЯЗАТЕЛЬНО clean build
При копировании исходников в Aurora-варианты — удалять `build/`, `.svelte-kit/`, `node_modules/.vite/` перед rebuild. Иначе Vite кеширует старый JS.

### 7. JS с JSDoc — НЕ TypeScript
Фронтенд на JS с `checkJs: true`. Не конвертировать в TS.

---

## DEV-режим

```bash
cd <repo_root>
AIAGENCY_DEV=1 AIAGENCY_DEV_CABINETS="<repo>/New_AI_Agency" npm run tauri dev
```

**DOM-driven визуальный аудит (MCP-мост):** для `driver_session`/`webview_*` запускать
`npm run tauri:dev` (НЕ `npm run tauri dev`) — он подмешивает `tauri.dev.conf.json`
(`withGlobalTauri:true`) через `--config`. Иначе `window.__TAURI__` отсутствует и мост
вернёт `hasTauri:false`. `withGlobalTauri` намеренно вынесен в dev-overlay, НЕ в базовый
`tauri.conf.json` (release-гигиена, INV-52: иначе `window.__TAURI__` течёт в production).
Мост = `tauri-plugin-mcp-bridge` под `#[cfg(debug_assertions)]`, bind 127.0.0.1:9223.

### 8. Online auth — НЕ удалять Ed25519 код
Две системы лицензирования работают параллельно. `online_auth.rs` — приоритетная, `license.rs` — fallback. Не удалять Ed25519 код до полной миграции всех клиентов.

### 9. Sidecar Stdio — использовать Stdio::null()
`Stdio::piped()` без чтения буфера → deadlock при большом выводе RAG/Parser. Всегда `Stdio::null()` для sidecar-процессов.

### 10. Pipeline context — inject в message, не файл
Claude не гарантированно читает файлы в workspace. Контекст пайплайна передавать через `build_message_prefix()` — prefix в message. Смотри `campaign.rs::ContextChain`.

### 11. persist_step_exports — ДО close_session
`close_session()` удаляет workspace включая exports. Всегда вызывать `persist_step_exports()` ПЕРЕД `close_session()`, иначе результаты шага теряются навсегда.

### 12. NavRail layout — flex, НЕ grid
```js
// ПРАВИЛЬНО (tabs сверху, sidebar слева):
const shellDirection = $derived(cabinets.length <= 5 ? 'column' : 'row');
// style="flex-direction: {shellDirection}" на .app-shell

// НЕПРАВИЛЬНО (grid ломает tab mode):
// grid-template-columns: auto 1fr  ← tabs оказываются слева, не сверху
```

### 13. Page heights — 100%, НЕ 100vh
```css
/* ПРАВИЛЬНО (внутри main-content flex child): */
.workspace { height: 100%; }

/* НЕПРАВИЛЬНО (overflow на высоту NavRail tab bar = 44px): */
.workspace { height: 100vh; }
```

### 14. Selection/Execution mode — visibility, НЕ display:none
```css
/* ПРАВИЛЬНО (сохраняет CSS transitions): */
.panel.hidden { opacity: 0; height: 0; visibility: hidden; pointer-events: none; position: absolute; }

/* НЕПРАВИЛЬНО (display:none→block НЕ анимируется по CSS spec): */
.panel.hidden { display: none; }
```

### 15. Command descriptions — JS-side (command-meta.js), НЕ в cabinet.rs
CabinetCommand в Rust = {command, label, group}. Описания добавлять в `src/lib/command-meta.js`.
НЕ менять Rust struct — это ломает 48 тестов и 117 кортежей.

### 16. Cabinet loading — один раз в layout, НЕ в каждой странице
`layoutCabinets` store заполняется в `+layout.svelte`. Все страницы читают из store.
НЕ вызывать `invoke('get_cabinets')` повторно в +page.svelte или других routes.

### 17. Git-теги — обязательно при каждом значимом изменении
После каждого значимого изменения (новая фича, фикс кабинета, обновление промптов) — ставить git-тег:
```bash
git tag v0.7.5-описание-изменения
```
Формат: `v{версия}-{краткое-описание}`. Хранить минимум 5 последних тегов для возможности отката.
При откате: `git checkout <tag>` → пересинхронизировать 5 вариантов → clean build.

### 18. Регламент правки промптов и доставки (аудит 2026-07-13, Батч 5)
Разовые находки аудита промптов кабинета econometrist стали автопроверками — держать зелёными.

**Правка промпта кабинета** (`New_AI_Agency/econometrist/CLAUDE.md`, `.claude/commands/*.md`
или `LEGACY_COMMANDS.md`):
1. `python tools/lint_prompt_commands.py` — 0 FAIL (U+2014 запрещён; «доверительный
   интервал»/«CI» запрещены в клиентском тексте — байесовский интервал называется
   «правдоподобный диапазон», INV-50; единая языковая шапка первой строкой каждой
   команды; паттерны блокировки диалога «ОСТАНОВИСЬ»/«не продолжай»/«жди ввода»/
   «не генерируй» запрещены).
2. Задетые команды прогнать через `cabinet_eval --dry` (детерминированный, без
   egress) ДО пуша — калибровка без просадки.

**Правка content-pack** (`content-packs/*.json`):
1. `python tools/check_help_consistency.py` — четверное совпадение `cabinet.rs`
   (блок `"econometrist" => vec![...]`) = `cabinets.json` = файлы-владельцы в
   `.claude/commands/*.md` = описания в `command-meta-data.json`; U+2014=0 по
   всем `content-packs/*.json`.
2. После любой правки `content-packs/*.json` — **re-sign ОБЯЗАТЕЛЕН**:
   `python tools/sign_content_pack.py --bump` (иначе sha256 в manifest устаревает →
   `verify_manifest` у клиента падает → доставка молча не доезжает). Проверка:
   `python tools/check_content_pack_sync.py` = OK.

**CI** (`.github/workflows/ci.yml`, job `check`) и **pre-commit** (`lefthook.yml`)
уже гоняют все три линтера (`prompt-lint`, `help-consistency`, `content-pack-sync`).
Не обходить `--no-verify` без причины. Каждый новый линтер — проверять
«внести-поймать-откатить» (способен реально падать, не мёртвый обвес).

---

## Структура проекта

```
src/                              # SvelteKit фронтенд
├── app.css                       # Design system: Aether Mesh (glass tiers, a11y)
├── lib/
│   ├── store.js                  # Svelte stores (messages, layoutCabinets, cabinetCommands, navCollapsed, recentCommands, inboxFiles)
│   ├── command-meta.js           # v2.0: Cabinet categories, command descriptions, file-aware metadata
│   ├── response-parser.js        # v2.0: Markdown→structured sections parser (memoized)
│   ├── chat-classifier.js        # v0.7: Regex classifier (9 categories, follow-up protection)
│   ├── audio.js                  # v0.7: Web Audio API (0 bytes, off by default)
│   ├── psy.js                    # PSY system: phases, celebrations, mastery, pending work
│   └── components/
│       ├── NavRail.svelte        # v2.0: Adaptive nav (hidden/tabs/sidebar), loading state
│       ├── CommandGrid.svelte    # v2.0: Visual command grid, groups, QuickAccess, highlighting
│       ├── CommandCard.svelte    # v2.0: Command card with tooltip, haptic press, favorites
│       ├── ResponseSection.svelte # v2.0: Collapsible response section with copy/refine
│       ├── ChatPanel.svelte      # Чат + стриминг + structured responses + Mini-TOC
│       ├── CommandPanel.svelte   # DEPRECATED: replaced by CommandGrid (kept for reference)
│       ├── FileList.svelte       # Входящие/экспорты (CommandPanel removed)
│       └── OnboardingOverlay.svelte
├── routes/
│   ├── +layout.svelte            # AppShell: NavRail + main-content flex layout
│   ├── +page.svelte              # Главная (кабинеты из layoutCabinets store, lastCabinet restore)
│   ├── cabinet/+page.svelte      # Selection/Execution workspace modes
│   ├── brands/+page.svelte       # Список брендов (только Creative Hub)
│   ├── brand/[id]/+page.svelte   # Страница бренда (edit, docs, delete, drag-drop)
│   ├── workflow/[id]/+page.svelte # Редактор workflow + brief + pipeline + export
│   └── settings/+page.svelte     # Настройки + лицензия
src-tauri/src/                    # Rust бэкенд
├── lib.rs                        # Tauri commands (с validate_cabinet_id)
├── commands/
│   ├── brand.rs                  # v0.5.0: 15 brand commands (filesystem-first, validate_brand_id)
│   ├── cabinet.rs                # 117 команд в 13 кабинетах
│   ├── campaign.rs               # Campaign + Workflow templates
│   ├── claude.rs                 # Запуск Claude CLI (trusted path validation)
│   ├── license.rs                # Ed25519 лицензирование (офлайн fallback)
│   ├── online_auth.rs            # v2: онлайн-авторизация + detect_product/is_creative_hub
│   ├── parser.rs                 # v0.5.0: Parser HTTP proxy (5 commands)
│   ├── content_updater.rs        # v2: обновления vault-файлов
│   ├── updater.rs                # Обновление .exe
│   ├── user_config.rs            # Пользовательские настройки (папки результатов)
│   └── vault.rs                  # Vault-файлы (per-app storage)
├── crypto/                       # AES-256-GCM, Ed25519, HKDF, fingerprint
├── session/manager.rs            # Vault распаковка + workspace
└── metrics/audit.rs              # Аудит-логирование
New_AI_Agency/                    # Промпты и скрипты кабинетов
├── <cabinet-id>/
│   ├── CLAUDE.md                 # Системный промпт (с Model Configuration)
│   └── .claude/commands/*.md     # Slash-команды
```

## Сборка

🔴 **Поставка клиенту собирается ТОЛЬКО командой со шлюзом** (распоряжение владельца 17.08.2026,
вся линейка; канон — CPD-115 в `aurora-meta/CROSS_PRODUCT_DEFECT_REGISTRY.md`). Штатная
`npm run tauri build` даёт поставку **БЕЗ шлюза**: модуль `gateway_executor` закрыт признаком
`thin`, а признак намеренно не объявлен в базовом манифесте (ADR-048). Проверено пробой на
выпущенном двоичном файле 2.4.10 — `aurora_gateway` встречается 0 раз, то есть все прежние
поставки уехали без шлюза, и никто этого не заметил (CPD-87).

```bash
# 🔴 ПОСТАВКА КЛИЕНТУ — со шлюзом Авроры:
CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" npm run tauri:build:thin

# Проверочная сборка без шлюза (клиенту НЕ отдавать):
CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" npm run tauri build

# Локальная редакция (M1, 152-ФЗ — только MMM-пайплайн, 0 Claude egress):
CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" npm run tauri:build:local
```
Результат: `<cargo_target>/release/bundle/nsis/*-setup.exe`

🔴 **Приёмка обязана гоняться В ТОЙ ЖЕ конфигурации, в какой собирается поставка** (CPD-112).
Без признака `thin` — 501 проверка, с признаком — 529: разница ровно 28 проверок кода шлюза,
и до 17.08.2026 их не гоняли ни разу (написаны они были, просто не существовали для компилятора
в прогоне приёмки). Перед выпуском:
```bash
node tools/build-cloud.mjs --test
```
🔴 **Именно так, а не `cargo test --features thin`** — этой команды не существует: признак `thin`
объявлен только в `Cargo.cloud.fragment.toml`, а в базовом манифесте его нет намеренно (ADR-048),
и `cargo` отвечает «the package does not contain this feature» (проверено прогоном 17.08, код 101).
Манифест с признаком собирает на время прогона сам облачный скрипт и восстанавливает его после.
Ошибка эта была записана сюда мной и прожила десять минут — оставляю след, потому что команда
выглядит правдоподобно и её напишут снова.

🔴 **Установка и обновление — без прав администратора** (то же распоряжение, канон — CPD-116):
`installMode: currentUser`, повышение прав при обновлении только как запасная ветка для клиента
со старой машинной установкой, и решается оно фактической пробой записи в свой каталог.

**Редакции (feature `cloud_advisors`, default-on):** без фичи (`--no-default-features`)
`claude.rs::run_claude`/`run_claude_pipeline` делают ранний bail ДО спавна Claude CLI
(egress к Anthropic статически недостижим), а `filter_by_product` скрывает кабинет-советник
`econometrist`. Гейт MMM-справки в Ctrl+K — по продукту (`isEconometrica`), не по advisor-кабинету.

**Упаковка двух редакций (D2, решено 2026-07-03):** локальная собирается через
`npm run tauri:build:local` = оверлей `src-tauri/tauri.local.conf.json`
(productName «Optimizer MMM Local», identifier `com.aurora.econometrica.local`)
+ `--no-default-features`. Редакции сосуществуют на одной машине: свои пути
`%APPDATA%\com.aurora.econometrica[.local]` (license.json, кэш, проекты —
изоляция ПДн локальной редакции). Канал обновлений разведён:
`updater::update_product_key()` даёт `aurora-econometrica-gui-local` для
локальной — публиковать ОТДЕЛЬНЫЙ манифест (регламент aurora-release-update),
иначе локальным клиентам приедет облачный exe. Лицензия: тот же формат
(fingerprint-based), кладётся в per-app путь локального identifier — см.
`2_Выдача_лицензий/CLAUDE.md`.

## Тесты

```bash
CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" cargo test     # 48 тестов
npm run check                                                  # svelte-check (0 ошибок)
```

## Система защиты

- Ed25519 подпись лицензии (публичный ключ в `crypto/ed25519.rs`)
- Machine fingerprint: SHA-256(UUID + disk serial + board serial с trailing |)
- Vault: AES-256-GCM, ключ = HKDF(fingerprint, license.salt)
- Per-app хранение: `%APPDATA%\<identifier>\license.json` и `vaults/`
- Dev-bypass: только `#[cfg(debug_assertions)]` + env var

## Частые ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| "Unknown skill: X" | Vault не распаковался (workspace пуст) | Проверить tar extraction в manager.rs |
| Кнопки не реагируют | async onMount / vite.config conditions | См. правила 1-2 выше |
| Vault decryption failed | Неправильный fingerprint | Использовать SHA-256 (64 символа), не raw hex |
| Claude not found | Путь не в trusted prefixes | Добавить USERPROFILE |
| Чёрный экран | WebView2 кэш | Приложение чистит автоматически при retry |
| "os error 5" при открытии кабинета | icacls с голым USERNAME при COMPUTERNAME==USERNAME | Использовать `USERDOMAIN\USERNAME` в manager.rs (фикс 2026-04-05) |
| Pipeline stuck на "running" | App crash во время выполнения | fix_interrupted_campaigns() в startup → "interrupted" |
| Exports потеряны после шага | close_session удалил workspace | Вызывать persist_step_exports() ДО close_session |
| Sidecar deadlock | Stdio::piped() без чтения | Использовать Stdio::null() для RAG/Parser sidecar |
