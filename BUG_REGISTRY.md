# Bug Registry — Aurora AI

Реестр найденных и исправленных ошибок. Читать перед каждым обновлением.

---

## UX-001: Supabase app_versions — двойной ключ product
**Дата:** 2026-04-08
**Критичность:** HIGH — обновления не доходят до клиентов
**Суть:** Updater в Rust отправляет `CARGO_PKG_NAME` (например `rosst-ai-legal`), а CLI публикует в БД как short name (например `legal`). Edge function `/app-update` ищет по тому что пришло — не находит.
**Правило:** При публикации обновления ВСЕГДА создавать запись с ДВУМЯ ключами:
- Short name: `legal`, `creative`, `media`, `docmaster`, `agency`, `creative-hub`
- CARGO_PKG_NAME: `rosst-ai-legal`, `rosst-ai-creative`, `rosst-ai-media`, `rosst-ai-docmaster`, `ai-agency-gui`, `aurora-creative-hub`

**Маппинг CARGO_PKG_NAME → product:**
| CARGO_PKG_NAME | Short name | GitHub Pages folder |
|---------------|------------|-------------------|
| `ai-agency-gui` | `agency` | `ai-agency-gui` |
| `rosst-ai-legal` | `legal` | `rosst-ai-legal` |
| `rosst-ai-creative` | `creative` | `rosst-ai-creative` |
| `rosst-ai-media` | `media` | `rosst-ai-media` |
| `rosst-ai-docmaster` | `docmaster` | `rosst-ai-docmaster` |
| `aurora-creative-hub` | `creative-hub` | `aurora-creative-hub` |

---

## UX-002: sync-variants — tauri.conf.json не патчится при ручном sync
**Дата:** 2026-04-08
**Критичность:** HIGH — билд падает с "brand-hub path not found"
**Суть:** При ручной синхронизации (robocopy/cp) из Agency в варианты, `tauri.conf.json` копируется as-is. Agency tauri.conf.json содержит `../brand-hub/**/*` в resources — для Legal/Creative/Media этих путей нет → сборка падает.
**Правило:** ВСЕГДА использовать `sync-variants.ps1` для синхронизации. Скрипт патчит:
- `tauri.conf.json`: productName, identifier, resources (убирает brand-hub)
- `Cargo.toml`: name
- `main.rs`: lib name
**НЕ КОПИРОВАТЬ** src-tauri/ вручную между вариантами.

---

## UX-003: Product filter — NavRail показывает чужие кабинеты
**Дата:** 2026-04-08
**Критичность:** MEDIUM — UX confusion, лишние кабинеты
**Суть:** `get_cabinets` возвращает ВСЕ кабинеты по лицензии, не по продукту. Если лицензия Agency дана на Legal — Legal видит все 13 кабинетов.
**Решение:** `filterCabinetsByProduct()` в `command-meta.js` — фильтрация на фронтенде по `productType` из `creative-store.js`.
**Правило:** При добавлении нового продукта — добавить в `PRODUCT_CABINETS` в `command-meta.js`.

---

## UX-004: height: 100vh внутри flex layout
**Дата:** 2026-04-08
**Критичность:** MEDIUM — overflow на высоту NavRail tabs (44px)
**Суть:** Страницы использовали `height: 100vh`, но после добавления NavRail tabs (44px вверху) 100vh включает эти 44px → контент выходит за viewport.
**Правило:** Внутри `.main-content` (flex child) использовать `height: 100%`, НЕ `100vh`.
**Затронутые файлы:** `+page.svelte`, `cabinet/+page.svelte`, `settings/+page.svelte`, `brands/+page.svelte`, `data-chat/+page.svelte`, `brand/[id]/+page.svelte`

---

## UX-005: display:none убивает CSS transitions
**Дата:** 2026-04-08
**Критичность:** LOW — визуальный glitch
**Суть:** `display:none → display:block` по CSS spec не анимируется. Transition opacity не работает.
**Правило:** Для анимируемых панелей использовать `visibility: hidden; opacity: 0; height: 0; pointer-events: none; position: absolute;` вместо `display: none`.

---

## UX-006: Flex children без min-height:0 — скролл не работает
**Дата:** 2026-04-08
**Критичность:** HIGH — пользователь не может прокрутить длинный ответ
**Суть:** По CSS spec flex children имеют `min-height: auto` (= min-content). Если content > container, child НЕ сжимается → `overflow-y: auto` внутри не работает.
**Правило:** Для flex children с внутренним скроллом ВСЕГДА добавлять `min-height: 0`.
```css
.flex-child-with-scroll {
  flex: 1;
  min-height: 0;      /* ← обязательно */
  overflow: hidden;    /* или auto */
}
```

---

## UX-007: lastCabinetId auto-redirect — перебрасывает с Home
**Дата:** 2026-04-08
**Критичность:** MEDIUM — user disorientation
**Суть:** `$effect` подписывался на `$layoutCabinets` + `$lastCabinetId` и вызывал `openCabinet()` при каждом обновлении store. Пользователь не успевал увидеть Home page.
**Правило:** НЕ делать auto-redirect из reactive $effect. Если нужен restore — показать banner/chip, а не redirect.

---

## UX-008: Quick actions хардкод — "Создать контент" в Legal
**Дата:** 2026-04-08
**Критичность:** MEDIUM — чужеродный контент
**Суть:** Quick actions на Home были захардкожены: "Создать контент" (Workflow), "Написать текст" (Копирайтер), "Спросить AI" (Data Chat). Для Legal ни один не релевантен.
**Правило:** Quick actions формировать из реальных кабинетов продукта: `cabinets.slice(0, 3)`.

---

## UX-009: $effect бесконечный цикл — guard variable
**Дата:** 2026-04-08
**Критичность:** HIGH — infinite navigation loop
**Суть:** `$effect` зависящий от store A выполняет действие которое изменяет store B. Если store A обновится снова (например при heartbeat) — effect сработает повторно.
**Правило:** Для one-shot effects использовать guard: `let done = false; $effect(() => { if (done) return; done = true; ... });`

---

## UX-010: Placeholder ссылается на удалённый UI
**Дата:** 2026-04-08
**Критичность:** LOW — user confusion
**Суть:** ChatPanel placeholder "выберите команду справа" — но CommandPanel удалён из FileList. Команды теперь в Selection mode (сверху/по центру).
**Правило:** При удалении UI элемента — grep по всему проекту для ссылок на него в текстах, placeholder'ах, tooltip'ах.

---

## UX-011: Duplicate IPC call — get_cabinet_commands
**Дата:** 2026-04-08
**Критичность:** LOW — wasted resources
**Суть:** ChatPanel и CommandGrid оба вызывали `invoke('get_cabinet_commands')`. Два IPC + vault overhead.
**Решение:** `cabinetCommands` store — CommandGrid пишет, ChatPanel читает через subscribe.
**Правило:** Перед добавлением нового `invoke()` — проверить не вызывается ли уже в другом компоненте. Использовать shared store.

---

## UX-012: APP_VERSION хардкод в layout.svelte
**Дата:** 2026-04-08
**Критичность:** LOW — потенциально неверное сравнение
**Суть:** `const APP_VERSION = '0.4.1'` в layout.svelte — хардкод, не обновляется при bump. Используется для `isNewer(resp.app_min_version, APP_VERSION)`.
**Текущий статус:** Не исправлено. Влияние минимальное — mandatory update trigger работает через Rust `check_update` с `env!("CARGO_PKG_VERSION")`.
**TODO:** Получать версию из Rust при запуске.

---

## Checklist перед публикацией обновления

1. [ ] Version bump: `Cargo.toml` + `tauri.conf.json` + `package.json` (все три!)
2. [ ] `sync-variants.ps1 -Build` (НЕ ручной sync)
3. [ ] `cargo test` — 48 тестов pass
4. [ ] `npm run check` — 0 errors
5. [ ] Supabase app_versions: upsert с CARGO_PKG_NAME ключом (не short name!)
6. [ ] Supabase Storage: upload .exe
7. [ ] GitHub Pages: latest.json обновлён и запушен
8. [ ] GitHub Releases: assets обновлены (для Agency 74MB+)
9. [ ] Curl verify: download URL отдаёт HTTP 200
10. [ ] Edge function verify: `curl -X POST .../app-update -d '{"product":"<CARGO_PKG_NAME>"}' `
