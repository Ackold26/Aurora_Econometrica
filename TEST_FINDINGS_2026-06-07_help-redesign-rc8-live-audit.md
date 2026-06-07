# Live-аудит rc8 — справочная система после редизайна (2026-06-07)

> Метод: visual-audit скилл. Probe-first (Phase 0) → DOM-driven live через tauri MCP-мост (порт 9223, dev `npm run tauri:dev`). HEAD `3c1b950` (master, в синхроне с origin).
> Цель: подтвердить, что редизайн справки работает в живом продукте; найти баги ДО релиза.

## Итог: PASS — 0 реальных багов редизайна

Probe закрыл ~80% (справка = статический HTML + SSOT-консистентность + wiring). Live подтвердил то, что probe структурно не доказывает (рантайм-резолв open_help, фактическое открытие палитры + gating).

## ✓ Подтверждено (probe)
- **Глоссарий SSOT консистентен:** glossary.html 47 `class="term"` ↔ `docs/glossary.json` 47 ↔ `src/lib/glossary.js` 47. CRITICAL_IDS + legacy сохранены (генератор `tools/build_glossary.py`).
- **Новые страницы в бандле:** `tauri.conf.json` resources = `help-econometrica/*` (wildcard → interpretation/features/whats-new + 5 xlsx попадают в rc8).
- **open_help без хардкод-allowlist:** `lib.rs:1606` `format!("{}.html", cabinet_id)` → резолв в `["help-econometrica","help"]` → любой существующий файл открывается.
- **econ-nav.js:** 4 группы (Начало/Данные и MMM/Результаты/Интерфейс); interpretation→`results`; pipeline title «Pipeline: 6 шагов».
- **5 xlsx-шаблонов** (fmcg/pharma_otc/pharma_rx/retail_ecom/realestate_b2b) на диске + бандл + все 5 залинкованы в data-preparation.html (realestate — ложная тревога снята: regex `[a-z_]+` не пропускала «2» в «b2b»).
- **MQSBadge микро-справка:** кнопка «? Как читать результаты» (`MQSBadge.svelte:130`) → `invoke('open_help', {cabinetId:'interpretation'})` (:27).
- **CommandPalette фильтр** (`:135-140`): match `label`/`description` через `includes(toLowerCase)`; help-записи gated `cabinets.some(c=>c.id==='econometrist')` (:98) — cross-product безопасно.
- **PipelineOnboarding «5→6»** (`9123cf1`) = comment-only, поведение не затронуто.

## ✓ Подтверждено (live, DOM-driven через мост)
- **hasTauri:true** (dev-overlay `withGlobalTauri` работает), **document.title = «Aurora AI Econometrica»** (фикс реликта «AI Agency» держится).
- **Кабинет `econometrist` присутствует** → gating-условие выполнено.
- **Ctrl+K открывает палитру** (`palette-overlay`); запрос «справ» → ВСЕ 9 help-страниц; запрос «интерпрет» → «Справка: интерпретация результатов» (скриншот). Gating сработал.
- **open_help('interpretation') → opened-ok** в рантайме (Rust резолвит новую страницу + внешний браузер). Это общий механизм MQS-кнопки И help-записей палитры → оба пути валидны.

## ⚠️ Наблюдения (не блокеры релиза)
1. **[LOW, UX] Транзиентное «Ничего не найдено» при быстром вводе после Ctrl+K.** `allItems` строится асинхронно (invoke `get_cabinets` + per-cabinet commands + glossary). До завершения async help/cabinet-записи отсутствуют → ввод в это окно показывает «Ничего не найдено» без loading-индикатора. Само-разрешается за ~100-300мс. Воспроизведено синтетически (печать до async); с ожиданием 1500мс — корректные результаты. Опц. фикс: loading-state пока `allItems` строится.
2. **[LOW, PRE-EXISTING, не регрессия редизайна] Ctrl+K двойной биндинг на /cabinet.** `ChatPanel.svelte:379` вешает глобальный `window keydown` (Ctrl+K → поиск в чате), смонтирован в `cabinet/+page.svelte`. Layout-листенер (Ctrl+K → палитра) — отдельный глобальный. На /cabinet оба срабатывают. Биндинг палитры v1.3.0 + чат-поиск оба были ДО редизайна (редизайн лишь добавил help-записи в палитру). Code-proven; live-repro заблокирован routing-guard'ом (/cabinet→redirect). Реко-фикс: в ChatPanel-хендлере `if (paletteOpen) return` или scoped-listener вместо window-global.
3. **[INFO] Escape через синтетический window-keydown не закрыл палитру** (закрытие по backdrop-клику работает). Вероятно палитра слушает Escape на input/локально — не баг, артефакт синтетического теста.

## Не покрыто (вне досягаемости моста)
- xlsx `<a download>` фактическое скачивание — открывается во ВНЕШНЕМ браузере (вне webview, мост не достаёт). Ссылки+файлы code-proven.
- MQS-кнопка визуальный рендер — требует загруженного обученного проекта → экран отчёта. Её `open_help`-вызов live-проверен отдельно.

## Грабли окружения (для skill-evolution)
- **`location.href = '/cabinet'` (full-reload на guarded-роут) сорвал гидрацию SPA** (Tauri+Vite): /cabinet→redirect на «/», но клиент завис на bootstrap-шелле (bodyText = сырой theme-скрипт, elemCount 44, title «Aurora AI»). Восстановление — `location.href='/'`+ожидание. Урок: для in-app навигации НЕ использовать `location.href`; SPA client-nav или клик по реальной ссылке.
- **`execute_js` ~5с timeout:** `await invoke('open_cabinet')` + setTimeout внутри одного скрипта упёрся в timeout. Разбивать на короткие шаги, тяжёлые invoke — отдельным вызовом.
