# Econometrica — роутер следующей сессии (vault-заход: доставить промпты econometrist клиентам)

> Скопируй в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_v230`
> (worktree `feat/econ-v2.3.0`, уже merged в master). Обновлён 2026-07-14 (wrap-up после релиза 2.3.1).

## Контекст — что сделано (НЕ переделывать)

**🚀 РЕЛИЗ 2.3.1 ПОЛНОСТЬЮ В ПРОДЕ** (master, тег `v2.3.1`, PR#3 merged, HEAD `34b9aa2`).
В сборку вошли: идеальные демо планирования + drill-fix count-KPI (`d4cbbb7`) + security-fix
апдейтера SEC-03/04 (`1e53e03`, от параллельной сессии).

**Демо переделаны** (задача Антона «очевидная эффективность + надёжная модель»):
- FMCG недельный (104+26): прирост **+11.8%**, R² 0.94, backtest **directional**.
- OTC противопростудные месячный (60+12, `use_holidays=False`): +3.3% итог / **+13.6% медиа**, **reliable**.
- Генератор `tools/generate_demo_samples.py` (перекос насыщения Hill, seed 140/245).
- UI-кнопка «Попробовать планирование на примере» (`ImportStep.svelte`).

**Публикация ВЕРИФИЦИРОВАНА** (curl+service key, MCP Unauthorized): GH Release `v2.3.1` +
.exe `sha256:3c7f905b…` (256.6 MB) · app_versions ×2 (`aurora-econometrica-gui`+`econometrica`)
→ 2.3.1 · Edge app-update → 2.3.1 · **content-pack v5→v7** (download+hash сверены).

## 🔴 ГЛАВНАЯ ЗАДАЧА — vault-заход (доставить промпты econometrist клиентам)

Серверный vault **c1 (апрель) устарел**: кабинет `econometrist` несёт **4 команды**
(configure/diagnose/train/validate) vs текущие **17** (mmm-*, awareness-*, next-quarter-plan…).
Content-pack уже v7 (UI покажет 17 команд), а vault-промпты только для 4 → **рассинхрон
UI(17)/промпты(4)** до выката vault. Нужен новый content_version с актуальным vault.

**Полная схема разобрана** → память `reference_econometrica_ota_vault_content_schema` (ПРОЧИТАТЬ ПЕРВЫМ). Кратко:
- vault = **4 файла plain gzip-tar** (`analysis`/`data-model`/`econometrist`/`reporting`.vault),
  каждый = `tar czf` кабинета `New_AI_Agency/<каб>/` (CLAUDE.md + .claude/commands/*.md). НЕ AES
  (vault-packer AES — только локальная лицензия).
- Лежат в Storage `vaults/econometrica/c<N>/`. `content_versions` (product=**econometrica**)
  несёт `checksums` (4 sha256) + `vault_versions` + content_pack + frontend.
- Клиент качает по номеру: `resolve_vault_version` = `vault_versions[кабинет]` ИЛИ fallback
  `content_version` (c1→1). Серверный `vault_versions={}` → все на fallback c1.

**Шаги (выверенно, необратимо → ВМЕСТЕ с Антоном):**
1. Собрать 4 gzip-tar: `tar --force-local -czf <каб>.vault -C New_AI_Agency/<каб> .` (⚠️ `--force-local`).
2. Залить `vaults/econometrica/c2/*.vault` (bucket `vaults`, private, service key).
3. `content_versions`: **INSERT c2** (product=econometrica, is_current=true, checksums 4 vault,
   content_pack_version=7, content_pack_checksum, frontend_version=1) + **UPDATE c1 is_current=false**.
   ⚠️ Проверить: клиент решает перекачку по `resolve_vault_version` — c1→c2 поднимает fallback 1→2 →
   перекачает РОВНО раз (не на каждом старте). Свериться с `content_updater.rs::resolve_vault_version`.
4. Верифицировать: скачать каждый vault по клиентскому пути + sha сверить; distinct-хеши (на c1
   econometrist.vault==data-model.vault имели ОДИН хеш — проверить, что после пересборки различны).
5. Fresh-install smoke: открыть econometrist → 17 команд с промптами, нет «Unknown skill».

## 📋 ПОЛНЫЙ БЭКЛОГ ПРОДУКТА (перетекает сессия→сессия, НЕ терять)

> **Правило Антона (2026-07-14):** ВСЕ открытые задачи Econometrica живут в durable-бэклоге
> **[[project_econometrica_backlog]]** (память, грузится по имени «Econometrica» в любой сессии).
> Задачи перетекают из сессии в сессию, пока не выполнены — приоритет определяем КАЖДЫЙ раз,
> не фиксирован. Выполнил — пометь ✅ в бэклоге. **Прочитать бэклог в начале сессии** и вместе
> с Антоном выбрать, за что берёмся.

Кратко группы (детали + статусы → в `project_econometrica_backlog.md`):
- 🔴 **Блокеры:** vault c2 (эта задача выше) · P-2 «Прогноз» не в PPTX · KPI-units+Planning merge · sidecar/выкат planning-линии · аудит после `a188986`.
- 💰 **Коммерческая готовность:** пилот прогноз→факт (Горизонт 3, главное) · EULA/DPA · ПДн INV-38 · code-signing · support-контур · онбординг ≤15-30мин · нарратив честности.
- 🧬 **Аврора Tier2 + RAG** (USP онлайн) — порт поверх линии + облачный RAG-слой.
- 🧭 **Петля доверия E1→E4:** backtest-витрина · калибровка экспериментами · жизненный цикл модели · рекомендации-обещания.
- 🔧 **Движок:** G7 SBC · G9 geo (анти-фокус) · medium Planning.
- 🎨 **UX:** онбординг · валидация одним экраном · Фаза 5 OptimizeStep cleanup · Блок C от Антона.
- 📦 **Инфра/отложено:** локальная M1 · is_newer баг · английский/multi-user/macOS (по триггеру).

## Инварианты/правила
- Публикация через `aurora-secrets.env` + curl (Supabase MCP **Unauthorized**). Сеть → `dangerouslyDisableSandbox`.
- **Два product-id:** app_versions=`aurora-econometrica-gui` (raw pkg), content/vault=`econometrica` (mapped).
- Vault OTA = plain gzip-tar (НЕ vault-packer AES). content-pack tar.gz `--force-local`.
- JSON payload с русскими «ёлочками» — через python `json.dumps`, НЕ inline shell (кавычки ломают).
- Shared-репо: зонд HEAD/origin ДО коммита (в этой сессии в ветку прилетел чужой security-fix `1e53e03`).

## 🔴 Руководство по стилю действий (прочитать ПЕРВЫМ)
1. **Vault-публикация — по схеме `reference_econometrica_ota_vault_content_schema`, не по роутеру.**
   Роутер прошлой сессии путал (latest.json «нужен» — НЕ нужен; vault «один файл» — их 4; product-id).
   Живая БД/код > записанный план (в этой сессии зонд БД опроверг роутер по 4 пунктам). Зондировать
   реальное серверное состояние ПЕРЕД каждой записью.
2. **content_versions bump — самое тонкое место.** До INSERT c2 прогони `resolve_vault_version`
   мысленно на клиенте: c1→c2, vault_versions пусто → fallback parse('c2')=2 > local 1 → перекачка.
   Убедиться РОВНО раз, не петля. Если сомнение — сначала выверить механику чтением Rust, потом писать.
3. **JSON с кириллицей — только через `json.dumps` в файл + curl `--data-binary @file`.** Inline
   `-d '{...«…»...}'` в shell ломается на «ёлочках» (в этой сессии первый app_versions PATCH молча упал).
4. **tar на Windows — `--force-local`** (иначе `C:` принимается за remote host, «Cannot connect to C:»).
5. **Каждый необратимый шаг: подготовка → проверка → запись → верификация (download+hash).** В этой
   сессии так прошли .exe/app_versions/content-pack без единой ошибки на проде. Держать тот же ритм.
6. **Публикация необратима → ВМЕСТЕ с Антоном.** Не заливать c2 в одиночку; согласовать bump-механику.
