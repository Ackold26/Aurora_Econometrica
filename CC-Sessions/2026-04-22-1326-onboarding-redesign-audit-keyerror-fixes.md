---
tags: [session, compressed, econometrica, audit, onboarding-redesign, store-restore, xss-fixes, keyerror-guard]
type: session
updated: 2026-04-22
---
# Quick Reference

**Topic:** Follow-up к утренней сессии (Report overhaul): детальный технический аудит с 8 security/stability findings (все закрыты), пофикшен критичный `KeyError: 'Малые медиа'` в train_model, добавлен IMPORT_TOUR + New/Load project chooser, онбординг перепроектирован с per-step completion на always-on toggle + 3-я кнопка «Отключить» прямо в туре, закрыт race-bug restoreProjectResults при переключении проектов.

**Key files modified (8):**
- `src/lib/onboarding-state.js` — убрана per-step логика, disableOnboarding helper
- `src/lib/components/pipeline/PipelineOnboarding.svelte` — 3-я кнопка btn-disable
- `src/lib/components/pipeline/ReportStep.svelte` — reloadFromDisk, escapeHtml, banner upgrade
- `src/lib/components/pipeline/ImportStep.svelte` — New/Load chooser, IMPORT onboarding hook
- `src/lib/components/pipeline/ValidateStep.svelte` — тур на onMount вместо $effect(!result)
- `src/lib/components/ConfigPanel.svelte` — pre-check enabledChannels vs validation
- `src/lib/components/ProjectSelector.svelte` — resetPipeline(id) передаётся
- `src/lib/project-state.js` — restoreProjectResults из resetPipeline, _lastRestoredPid reset
- `src/lib/pipeline-tours.js` — +IMPORT_TOUR, TOURS.import
- `src/routes/settings/+page.svelte` — убран блок Сбросить прогресс
- `sidecar/econometrica/engines/modeler.py` — guard missing columns
- `sidecar/econometrica/engines/html_export.py` — escape {/} + </ → <\/
- `sidecar/econometrica/server.py` — project_dir в HtmlExportRequest
- `src-tauri/src/commands/econometrica.rs` — project_dir в body /export
- `src-tauri/src/commands/project.rs` — atomic zip, streaming copy, pre-validate, data_file norm

**Commits (5):**
- `2d58f14` — audit fixes (8 findings: XSS ×3, data consistency ×2, robustness ×3)
- `6e96e4b` — compressed session log (утренняя)
- `d646427` — guard missing columns + New/Load chooser
- `2042a8b` — onboarding на Import + Validate onMount
- `45333b2` — always-on onboarding + store restore race fix ← **HEAD**

**Status:**
- ✅ Все правки в master, pushed
- ✅ Paша подтвердил rc2: 37/38 PASS, 0 FAIL, train 190s→20s (9.5× speedup)
- ✅ Onboarding redesign: always-on + disable button in tour
- ✅ Restore fix для переключения проектов
- ⏳ Sidecar rebuild нужен для rc3 (HTML endpoint + missing-cols guard + PPTX slides)
- ⏳ Решение: rc2 stable или rc3 с накопленными изменениями

## Learnings

### XSS / Security hardening
- **`{@html}` с user-controlled interpolation** — vector для XSS. Channel names из xlsx (`topDriver.name`, `underfunded.map(c.name)`) требуют `escapeHtml()` перед подстановкой в `**bold**` для regex-bold replace.
- **`</script>` injection в JSON внутри `<script>` block** — `json.dumps(ensure_ascii=False)` оставляет литеральный `</script>` → браузер закрывает script. Escape `</` → `<\/` (backslash в JSON игнорируется парсером).
- **`.format()` template bomb** — user-controlled string с `{` или `}` ломает Python `.format()` с KeyError. Escape `{` → `&#x7B;`, `}` → `&#x7D;` в `_escape` (HTML entity безопасен в HTML + полностью отключает .format placeholder parsing).
- **FastAPI exception_handler(Exception)** не перехватывает HTTPException в современных версиях (FastAPI делегирует на более специфичный default handler). Но `isinstance(StarletteHTTPException): raise exc` — safeguard на edge cases между версиями.

### Race conditions Svelte stores
- `activeProjectId.subscribe` с `_lastRestoredPid` guard блокирует повторный restore для того же pid.
- `resetPipeline()` без projectId сбрасывает stores в null БЕЗ последующего restore.
- При переключении проекта на **тот же** id (duplicate click, или refresh после HMR) — stores остаются null навсегда.
- **Fix:** в `resetPipeline(projectId)` при projectId≠null — обнулить `_lastRestoredPid` и вызвать `restoreProjectResults(projectId)` напрямую, обходя subscribe guard.

### Python column guard patterns
- Backend должен **валидировать входы ДО** любых вычислений — `KeyError` внутри pandas loop даёт непонятный stack trace пользователю.
- Pattern: `missing = [c for c in requested if c not in df.columns]` → early return с `error_code: MISSING_*_COLUMN` + `message` на языке пользователя + список отсутствующих. Не пытаться «починить» silently — лучше fail fast с подсказкой.

### Svelte 5 `{@const}` placement
- `{@const}` должен быть **immediate child** `{#if}` / `{:else}` / `{#each}` / `{#snippet}` / Component. Не внутри `<div>`.
- `{:else}` → `{@const ...}` → `<div>` — ОК. `{:else}` → `<div>` → `{@const ...}` — ERROR `const_tag_invalid_placement`.

### Sidecar performance stable
- Sampling time: **6-7 сек стабильно** (vectorized и parallel похожи для маленьких моделей).
- Total train time varies 20-26 сек за счёт `sample_posterior_predictive` + `arviz.summary` + `pickle.dump` (13-19 сек post-processing).
- Рандом MCMC даёт колебания ±30% per-run — subjective впечатление «в 2 раза дольше» обычно в этом диапазоне.

### Onboarding UX редизайн
- Per-step completion tracking избыточен для **живого обучающего режима** с коротким контентом (4-5 шагов). Пользователь либо хочет подсказки (включено), либо выключил (отключено). Промежуточный «посмотрел один раз» не даёт ценности.
- Кнопка «Отключить в настройках» ВНУТРИ тура даёт пользователю прямой escape-hatch — не надо искать Settings. Красный hover намекает на destructive-like action без реального вреда.

## Decisions

1. **Онбординг always-on** — показывается каждый раз пока enabled; убраны per-step completion flags. Пользователь контролирует через toggle в Settings или 3-ю кнопку в туре.
2. **Backend column guard + frontend pre-check оба нужны** — frontend fail-fast (сразу сообщение без сети), backend fail-safe (защита от bypasses / старых клиентов).
3. **`{@const}` в `{:else}` ветке** — перенос ПЕРЕД `<div>` вместо внутри. Svelte 5 спецификация.
4. **`escapeHtml` + `.format()` escape объединены** в `_escape` html_export.py. Один helper защищает от двух classes атак сразу.
5. **reload-from-disk ≠ recompute** — разные UX-пути. Reload дёшев (одна команда `project_load_results`), recompute дорог (2 sidecar-вызова + MCMC). Показываем оба в banner'е.
6. **`_lastRestoredPid` не убираем** — guard полезен для initial cold-start (один `restoreProjectResults` на активацию), но **`resetPipeline`** должен его обходить для явных пересчётов.
7. **New/Load chooser над drop-zone**, не замена — drop-zone остаётся для опытных пользователей, но новички сразу видят два варианта.
8. **Audit coverage** — приоритет XSS > data > robustness > typing. Все 8 findings закрыты в одном commit с детальным логом в memory.
9. **Session log разбит на 2** (утренняя 1242 + эта 1326) — обе сохранены в CC-Sessions для resume'а.

## Pending

### Sidecar rebuild для rc3
- HTML endpoint `/export/html` (Python)
- PPTX слайды: «Сравнение сценариев» + «Динамика по периодам»
- `_resolve_project_dir()` helper (чтобы экспорты учитывали Settings override директории)
- Backend `modeler.py` guard MISSING_*_COLUMN
- Триггер: решение rc3 vs rc2 stable

### Решение по релизу
- **Вариант A:** rc2 в stable v1.0.9 (Паша подтвердил 37/38). Минимальный риск. Report overhaul + save/load + onboarding + fixes идут в v1.0.10.
- **Вариант B:** rc3 с накопленными изменениями (Report UX + HTML + save/load + guards). Больше фич сразу клиенту. Нужен full rebuild + test cycle.

### Отложенные идеи
- AI narrative через Claude CLI (вектор A Report roadmap)
- PDF / Markdown экспорт (B)
- Кастомизация брендинга (B)
- Публичная ссылка через Supabase Storage (C)
- Offline-mode HTML (bundled echarts)
- Миграция существующих проектов при смене папки в Settings
- aurora-fix skill: V40+ правила (XSS hardening + archive safety + .format bomb)

### Pre-existing tech debt (не в scope)
- `hill.js`, `insights-rules.js` — pre-existing svelte-check errors
- OptimizeOnboarding.svelte dead code (не импортируется)

## Full Session Notes

### Phase 1: Audit по запросу Антона
Антон попросил «провести детальный технический аудит всей сделанной работы — ВСЕХ ЧАСТЕЙ». Прошла по всем файлам утренней сессии критически, нашла 8 реальных проблем:

**XSS (3):**
1. **ReportStep `{@html}` с interpolation.** Channel names попадали в 4 блока interpretation через `.replace('**', '<b>')` на `{@html}`. Name=`<script>alert(1)</script>` → execution. Fix: `escapeHtml(s)` helper для user fields.
2. **`</script>` в charts_json.** `json.dumps(ensure_ascii=False)` оставляет literal `</script>` внутри `<script>` block → HTML parser preamturely закрывает. Fix: post-process `replace('</', '<\\/')`.
3. **`.format()` template bomb.** Имя канала `Test{name}` → `str.format()` → KeyError. Fix: в `_escape` добавлен replace `{` → `&#x7B;`, `}` → `&#x7D;` (HTML entity безопасен в HTML + ломает placeholder parsing).

**Data consistency (2):**
4. **Python endpoints игнорировали Settings `econometrica_projects_root`.** `/export/pptx` и `/export/html` читали scenarios из hardcoded `%APPDATA%`. XLSX (Rust) уже работал правильно. Fix: Rust передаёт `project_dir` в body, Python использует с fallback на старый путь.
5. **Archive `data_file` cross-machine broken.** Абсолютный path с машины A не работал на B. Fix: export копирует external data в `archive/data/<basename>` + маркер `<project_dir>/data/...` в project.json; import resolve'ит на dest path; absolute несуществующий → null + hint в description.

**Robustness (3):**
6. **Archive export non-atomic.** Panic оставлял битый `.aurora` на диске. Fix: `.tmp` → rename.
7. **Archive export OOM.** `std::fs::read(path)` на 1GB+ pickle грузило в RAM. Fix: `std::io::copy(&mut infile, &mut zip)` streaming.
8. **Archive import без pre-validation.** Мусорные zip засоряли destination папку. Fix: pre-open zip + поиск `project.json` в корне ДО распаковки.

Плюс 2 typing errors (onKey без `@param {KeyboardEvent}`, escapeHtml без `@param {unknown}`).

Все закрыты в **commit `2d58f14`** (212+/28-, 6 файлов).

### Phase 2: Feedback Паши — rc2 CONFIRMED
Пришли 3 файла: `checklist_results.md`, `log-check-2026-04-22.txt`, `sidecar_reference.log`. Ключевые results:
- **37/38 PASS, 0 FAIL** (vs вчерашних 31/34)
- Train time **190s → 20s** (9.5× speedup) — multi-core MCMC реально работает
- Tier-1 NumPyro JAX в бандле (вчера был Tier-2 PyTensor)
- JAX devices 4 × cpu (expected=4) — XLA_FLAGS сработал
- ProactorBasePipe спам = 0 в актуальных сессиях
- sidecar.json: port=7441 (SID-hash), product/version OK, user=Администратор
- Паша: «в этой сборке всё прошло быстрее, ошибок не нашёл»

### Phase 3: Dev session + KeyError 'Малые медиа'
Антон запустил dev. Через HMR + live-работу вылез баг:
- `KeyError: 'Малые медиа'` в `train_model::apply_adstock` при отсутствии канала в dataframe
- Модель не обучалась → decompose ругался «Модель не найдена» → тупик

**Root cause:** пользователь применил рекомендацию «объединить с другим каналом» (мердж псевдо-каналов), но xlsx остался прежним. В project.json media_columns был обновлённый список с несуществующими в df именами.

**Fix (commit `d646427`):**
- **Backend modeler.py:** pre-validation `kpi/media/control` columns vs `df.columns` ДО `apply_adstock`. Return JSON `{status: error, error_code: MISSING_MEDIA_COLUMNS, message: "...", missing_columns: [...]}` вместо сырого pandas KeyError.
- **Frontend ConfigPanel.svelte:** pre-check `enabledChannels` vs `validation.columns.map(c => c.name)`. Автоматически отфильтровывает stale каналы + warning в computeStatus с именами пропущенных (first 3 + «...» для overflow). Если все отсутствуют — явный запрет с сообщением.

### Phase 4: New/Load chooser на Import step
Запрос: на Import должна быть явная альтернатива «Новый проект / Загрузить ранее сохранённый».

**Fix (commit `d646427`, продолжение):** добавлен блок `.import-intro` с 2 карточками над drop-zone:
- **📁 Новый проект** — кнопка «Выбрать файл данных» (alias на существующий `pickFile`) + подсказка про drag-drop
- **📦 Загрузить сохранённый проект** — кнопка «Выбрать .aurora архив» (логика из ProjectSelector: `project_import_archive` → `project_activate` → `resetPipeline(newId)`)

Показывается только при `!filePath && !loading`. CSS: 2-column grid (1fr 1fr) с @media breakpoint 900px → 1col.

### Phase 5: Онбординг на всех шагах + Validate fix
Антон: «онбординг подхватывается только на уровне обучения модели, а должен на валидации + должен быть на всех этапах кроме импорта». Потом уточнил: «если импорт-онбординг готов, можно включить и на импорте».

**Fix (commit `2042a8b`):**
- `IMPORT_TOUR` добавлен (3 шага: intro/choose-mode/drop-zone) в pipeline-tours.js.
- `TOUR_STEP_KEYS += 'import'` (6 шагов).
- **Validate fix:** `$effect(() => { if (!result) return; ... })` блокировал тур пока result=null (ObjectiveSelector overlay ждёт выбора). Переведён на `onMount` с `requestAnimationFrame×2` — тур запускается на mount независимо от data.
- **Import:** wire-up через `onMount` + `shouldShowOnboarding('import')` + PipelineOnboarding рендер в конце template.
- Убран duplicate `import { onMount }` в ValidateStep (случайно добавила дважды).

### Phase 6: Онбординг always-on редизайн
Запрос Антона:
> Туры включены всегда пока не выключены в настройках. В туре должны быть кнопки «Далее», «Пропустить» и «Отключить систему онбординга в настройках».

Потом: «Прогресс не сохранять, часть про сброс прогресса убрать совсем».

**Fix (commit `45333b2`):**
- **onboarding-state.js:**
  - `shouldShowOnboarding(_stepKey)` → return global toggle value (stepKey ignored)
  - `markOnboardingDone(_stepKey)` → no-op (backward compat)
  - `resetAllOnboarding()` → просто cleanup legacy keys
  - `cleanupLegacyStepFlags()` вызывается на load модуля → удаляет старые `aurora-econ-onboarded:*`
  - **Новая функция `disableOnboarding()`** → `onboardingEnabled.set(false)`
- **PipelineOnboarding.svelte:**
  - 3-я кнопка `.btn-disable` рядом с «Пропустить»
  - Text: «Отключить обучение»
  - `onclick={disableGlobally}` → `disableOnboarding()` + `onDone()` закрывает тур
  - Tooltip: «Больше не показывать туры. Включить обратно можно в Настройках → Обучающий режим.»
  - CSS: muted color default, **красный** hover (намёк на destructive), `font-size: 11px`, меньше padding
- **Settings +page.svelte:**
  - Убран блок «Пройти все туры заново» (неактуален)
  - Убраны imports `resetAllOnboarding, TOUR_STEP_KEYS`
  - Убран state `onboardingResetMsg`
  - Описание секции переписано: «...отключаются здесь или прямо из тура кнопкой "Отключить обучение"»

### Phase 7: Store restore bug
Антон заметил: на Report снова «Данные предыдущих шагов недоступны» хотя степпер показывает все ✓, и JSON-файлы на диске есть.

**Root cause diagnostics:**
- Проверила `$APPDATA\aurora-econometrica-gui\projects\кагоцел-рф-ммх-2204-26--3\`:
  - `decomposition.json` (9.8KB), `model-diagnostics.json` (6.8KB), `optimization.json` (21KB) — все есть
  - project.json: id="кагоцел-рф-ммх-2204-26--3", name="Кагоцел РФ ММХ 2204-26 (3)"
- Stores пусты → `restoreProjectResults` не отработал

**Bug:** `activeProjectId.subscribe` с `_lastRestoredPid` guard блокирует повторный restore для того же pid. При переключении проекта в рамках сессии на уже ранее активированный id — skip. `resetPipeline()` сбрасывает stores без повторной загрузки.

**Fix (commit `45333b2`):**
- **project-state.js `resetPipeline(projectId)`:** при `projectId !== null` сбрасывается `_lastRestoredPid = null` и вызывается `restoreProjectResults(projectId)` напрямую, обходя subscribe-guard.
- **Callers обновлены:** все 3 call sites передают id:
  - `ProjectSelector.selectProject(id)` → `resetPipeline(id)`
  - `ProjectSelector.importProjectFromArchive(newId)` → `resetPipeline(newId)`
  - `ImportStep.loadSavedProject(newId)` → `resetPipeline(newId)`
- **ReportStep reload-from-disk button:**
  - Новая функция `reloadFromDisk()` вызывает `project_load_results(pid)` и заполняет stores без пересчёта
  - Banner в `{:else}` ветке обновлён: показывает всегда при отсутствии данных (не только в «stale» сценарии)
  - Кнопки в banner: «↓ Загрузить результаты с диска» (primary) + «↺ Пересчитать» (fallback, показывается только если `mData.diagnostics` есть)
  - Svelte 5 fix: `{@const missing = ...}` перенесён ПЕРЕД `<div class="no-data-banner">` (должен быть immediate child {:else})

### Phase 8: Сводка + commit + memory
Финальный commit **`45333b2`** — 7 файлов, 136+/81-. Push в master. Memory обновлена:
- `project_econometrica_report_roadmap.md` + новая секция «Onboarding redesign + store restore fix» + детали всех багов
- `MEMORY.md` обновлена строка со статусом

## Commits timeline

| Commit | Topic | Lines | Files |
|:------:|-------|:---:|:---:|
| `010a39f` | Report overhaul main wave (утро) | 1904/186 | 21 |
| `2d58f14` | Audit fixes: XSS ×3 + data ×2 + robust ×3 | 212/28 | 6 |
| `6e96e4b` | Session log (утренняя) | 314 | 1 |
| `d646427` | Missing cols guard + New/Load chooser | 259/4 | 3 |
| `2042a8b` | Onboarding Import + Validate onMount | 55/6 | 4 |
| `45333b2` | Always-on onboarding + restore race fix | 136/81 | 7 |

Total: ~3000 добавленных, ~400 удалённых lines, 6 commits, все pushed.

## Testing checklist для rc3 (когда соберём)

- [ ] `/health` всё ещё возвращает numpyro/jax/arviz/pytensor versions
- [ ] `/export/html` работает и файл ~15-30KB
- [ ] PPTX содержит слайд «Динамика по периодам» (stacked area)
- [ ] PPTX содержит слайд «Сравнение сценариев» (если сценарии сохранены)
- [ ] Archive save/load на другой машине — data_file подхватывается корректно
- [ ] Settings → Папка проектов — сменил path → new projects пишутся туда
- [ ] Онбординг на Import → intro + drop-zone подсвечиваются spotlight'ом
- [ ] Онбординг на Validate → запускается даже до выбора objective (intro step)
- [ ] Кнопка «Отключить обучение» в туре → туры больше не появляются
- [ ] `KeyError: Малые медиа` → теперь JSON response `{error_code: MISSING_MEDIA_COLUMNS, missing_columns: [...]}`
- [ ] Переключение проектов → Report видит ранее посчитанные данные без действий

## Reference: env flags & paths

```bash
# Dev bypass
AIAGENCY_DEV=1 CARGO_TARGET_DIR="D:/cargo-targets/econometrica" npm run tauri dev

# Custom projects dir override
AURORA_PROJECTS_ROOT="D:/MyProjects" AIAGENCY_DEV=1 npm run tauri dev

# MCMC tuning
AURORA_MCMC_CORES=N               # JAX host devices
AURORA_MCMC_CHAIN_METHOD=parallel  # или vectorized / sequential
AURORA_NUTS_BACKEND=auto           # auto / numpyro / pymc

# Проверка файлов проекта
ls "$APPDATA/aurora-econometrica-gui/projects/<id>/results/"
# Ожидается: decomposition.json, model-diagnostics.json, optimization.json, scenarios/

# Логи dev
tail "$LOCALAPPDATA/aurora-econometrica-gui/logs/sidecar.log"
tail "$LOCALAPPDATA/aurora-econometrica-gui/logs/Aurora AI Econometrica.log"
```

## Grep cheatsheet для resume

```
# Onboarding ключевые файлы
src/lib/onboarding-state.js
src/lib/pipeline-tours.js
src/lib/components/pipeline/PipelineOnboarding.svelte

# Project lifecycle
src/lib/project-state.js            # resetPipeline, restoreProjectResults, _lastRestoredPid
src-tauri/src/commands/project.rs   # projects_dir, project_export/import_archive

# Report UX
src/lib/components/pipeline/ReportStep.svelte  # reloadFromDisk, escapeHtml, interpretation/FAQ

# Export engines
sidecar/econometrica/engines/html_export.py    # build_html + CDN echarts
sidecar/econometrica/engines/pptx_export.py    # timeline slide + scenarios slide
src-tauri/src/commands/report.rs               # build_xlsx + scenarios/timeline sheets

# Missing cols guard
sidecar/econometrica/engines/modeler.py        # MISSING_MEDIA_COLUMNS
src/lib/components/ConfigPanel.svelte          # enabledChannels filter
```
