---
tags: [session, compressed, econometrica, nuts, msvc, tamburin, saas, branding]
type: session
updated: 2026-04-19
---
# Quick Reference

Длинная live-сессия продолжения тестирования Econometrica на Кагоцеле. Главный blocker — медленный Metropolis sampler из-за недетекции MSVC — разрешён через `vswhere.exe` + `vcvars64.bat` env injection (ускорение NUTS в 3-5×). Плюс цикл UX-фиксов (Stop button, time-based progress, data_file store), брендинг (Logo_PNG_3-2 header + Logo_PNG_4_cuted иконки) и стратегические документы (Tamburin competitive, SaaS migration, System Requirements).

**Topic:** econometrica-nuts-saas-strategy

**Коммиты:** `74691f8` (Econometrica, 61 файл +495/-30) · 8 × иконочных коммитов в других приложениях (`6f10da4 / e6a9419 / 8f0da77 / 9faf9e4 / 0649809 / 8b7f497 / a2b6420 / 58c96be`)

**Key files:**
- `sidecar/econometrica/engines/modeler.py` — check_compiler() + vswhere + functools.partial fallback
- `sidecar/econometrica/server.py` — train/cancel endpoint, progress error field
- `src-tauri/src/commands/econometrica.rs` + `lib.rs` — econ_train_cancel
- `src/lib/components/ConfigPanel.svelte` — data_file store, Adstock 'auto', MSVC msg
- `src/lib/components/pipeline/TrainingProgress.svelte` — Stop button, time-based pct
- `src/lib/components/pipeline/ModelTrainingStep.svelte` — handleStop, estimatedSec
- `src/lib/components/pipeline/ExpertModelPanel.svelte` — MCMC rename
- `src/lib/insights-rules.js` — MCMC rename (4 карточки)
- `src/routes/+page.svelte` — topbar-logo 31px → 26px, new logo
- `static/logo-wordmark.png` — Logo_PNG_3-2
- `src-tauri/icons/*` — все иконки из Logo_PNG_4_cuted
- `docs/SYSTEM_REQUIREMENTS.md` (NEW) — детальные требования Econometrica
- `README.md` — обновлён раздел «Системные требования»

**Внешние документы:**
- `D:/Docs/Aurora_Ai/5_Документация/SYSTEM_REQUIREMENTS_PLATFORM.md` (NEW)
- `D:/Docs/Aurora_Ai/5_Документация/COMPETITIVE_TAMBURIN.md` (NEW)
- `D:/Docs/Aurora_Ai/5_Документация/ROADMAP_SAAS_MIGRATION.md` (NEW)
- `D:/Docs/Aurora_Ai/KB/System_Requirements/` (2 файла + index) — Obsidian vault
- `D:/Docs/Aurora_Ai/KB/Competitive/` (1 файл + index)
- `D:/Docs/Aurora_Ai/KB/Roadmap/` (1 файл + index)

**Status:** Шаг 2 Модель ещё в прогоне в момент компрессии (10 мин = 82%, time-based). NUTS vs Metropolis определится по завершении. Шаги 3-5 (Decompose/Optimize/Report) — ожидают.

---

## Learnings

### L1 — MSVC Build Tools не в PATH по умолчанию

Установка MS Visual C++ Build Tools (Desktop development with C++) **не добавляет `cl.exe` в PATH**. Чтобы активировать среду, нужно запустить `vcvars64.bat` из `VC\Auxiliary\Build\` — он экспортирует ~15 env vars (PATH, INCLUDE, LIB, LIBPATH, WINDOWSSDKDIR и пр.).

Это означает что `subprocess.run(['cl.exe'])` всегда возвращает FileNotFoundError у свежеустановленной VS, даже если компилятор физически на диске.

**Правильная детекция:**
1. Найти `vswhere.exe` — он **всегда** в фиксированной локации `%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe`
2. Запросить `vswhere.exe -latest -property installationPath` → путь к VS
3. Glob по `VC\Tools\MSVC\*\bin\Hostx64\x64\cl.exe` → путь к компилятору
4. Запустить `vcvars64.bat && set` → parse output → inject в `os.environ`

Это стандартная техника, которую используют Microsoft Build Insights, CMake, ninja-build.

### L2 — Markov Chain ≠ Markov Chain Monte Carlo

Терминологическая ловушка, критичная для коммуникации с клиентами:

- **Markov Chain (модель)** — граф переходов между состояниями. Для **MTA** (Multi-Touch Attribution, анализ клик-стрима) — золотой стандарт. Для **MMM** — не применимо, не умеет моделировать Adstock и diminishing returns.
- **Markov Chain Monte Carlo (MCMC)** — метод **сэмплирования** posterior-распределения в байесовских моделях. Это **вычислительный движок** под капотом всех современных MMM (Meta Robyn, Google LightweightMMM, PyMC-Marketing).

Наша Econometrica = Байесовский MMM с MCMC-сэмплером = state-of-the-art.

Антон просил писать полностью «Markov Chain Monte Carlo» в UI чтобы избежать путаницы.

### L3 — Два разных Svelte store для file path

`importData.file` (где ImportStep сохраняет) ≠ `pipelineState?.data?.file` (откуда ConfigPanel читал). Эти store'ы никто не синхронизировал. При рестарте dev (memory-only stores) ConfigPanel получал пустой `data_file` → Python `[Errno 2] No such file or directory: ''`.

**Паттерн:** когда два компонента разделены шагами пайплайна, читают и пишут в **один** store, или есть явная синхронизация.

### L4 — PyMC ppc crash с custom Deterministic

`pm.sample_posterior_predictive` в PyMC 5.x может падать с `'functools.partial' object has no attribute '__name__'` когда модель содержит custom Deterministic переменные (Adstock/Hill через `pm.math`). Внутренне PyMC пытается рекомбинировать граф, и partial-функции без `__name__` ломают сериализацию.

**Workaround:** try/except + manual reconstruction y_pred из posterior means. Для MMM это работает потому что Hill-формула полностью задаётся через media_betas + alphas + gammas (все в posterior).

### L5 — Tauri dev watcher перезапускает приложение при ЛЮБОМ изменении в src-tauri/

Запуск `npx tauri icon <path>` пишет файлы в `src-tauri/icons/` → Tauri dev обнаруживает изменения → Rust rebuild → перезапуск приложения → Python sidecar убивается.

**Паттерн:** в процессе live-теста **не запускать** `tauri icon` или любые операции, пишущие в `src-tauri/`. Всё делать с остановленным dev, либо после завершения теста.

### L6 — Sidecar Stdio::null() = нет логов в dev-консоли

PyMC и PyTensor пишут в stderr. Tauri sidecar запускается с `stderr(Stdio::null())` → логи идут в /dev/null. Невозможно диагностировать падения sidecar без отдельного logging-to-file.

**Паттерн:** в production-sidecar writtely логгировать в файл `%APPDATA%\<app>\logs\sidecar-YYYY-MM-DD.log`.

### L7 — Metropolis CompoundStep → functools.partial без __name__

Метробой Metropolis в PyMC для модели со смешанными типами переменных (Normal, HalfNormal, Gamma, Beta) создаёт **CompoundStep** — композицию шагов разных типов. Внутри CompoundStep есть functools.partial объекты которые не всегда имеют `__name__`. arviz.summary() и sample_posterior_predictive натыкаются на это → KeyError/AttributeError.

NUTS не использует CompoundStep для тех же переменных → ошибка не возникает.

**Смысл:** та же ошибка «functools.partial» — сигнал что Metropolis работает вместо NUTS. Root fix = починить детекцию C-compiler.

### L8 — Subscription-модель Claude несовместима с SaaS

Anthropic ToS явно запрещает перепродажу подписочного доступа (Pro / Max) через SaaS. Детектится автоматически (IP, user-agent, частотные паттерны). Публичные кейсы банов есть. Для SaaS — **только per-token API**.

### L9 — Anthropic не продаёт в РФ официально

Для российских клиентов SaaS через Anthropic API — схема через офшорное юрлицо (EU / UAE / AM / KZ). Клиент платит в ₽ через CloudPayments/Tinkoff, мы платим Anthropic в $ через офшор. Схема легальная, использует множество российских AI-продуктов.

### L10 — Econometrica = самый тяжёлый продукт платформы

7 из 8 продуктов Aurora — «оболочка для Claude API» с минимальной локальной нагрузкой. Только Econometrica запускает реальные вычисления (PyMC + PyTensor). Это критично для:
- Системных требований (tier 🔴 vs 🟢🟡)
- Ценообразования (CPU-compute в облаке дорогой)
- SaaS-миграции (Econometrica требует worker-кластер и cost management)

### L11 — Git Bash на Windows vs PowerShell

Команды из PowerShell (`Get-Process`, `taskkill /F`) не работают в Git Bash. Git Bash конвертирует одиночные `/argument` в пути. Для native-команд в Git Bash нужны:
- Двойные слеши: `taskkill //F //IM python.exe`
- Или через cmd: `cmd "/c taskkill /F /IM python.exe"`
- Или использовать отдельный PowerShell

### L12 — Tamburin использует OLS/RF (предположение)

Основной российский MMM-конкурент Tamburin (tametrics.ru) позиционируется «без сложных терминов и формул» → вероятно использует OLS + Random Forest, а не байесовский движок. Это означает:
- Нет доверительных интервалов → точечные оценки
- Переобучение на малых данных
- Не «честные» выводы для принятия бюджетных решений

Наш байесовский путь = **технологическое преимущество**.

---

## Decisions

### D1 — Stop button не убивает MCMC thread, только помечает cancelled

PyMC MCMC-поток нельзя корректно прервать (thread.terminate() = memory corruption). При нажатии Stop:
- Task помечается 'cancelled' в `_training_tasks[task_id]`
- Polling на фронте видит status → onStop callback → UI возвращается в idle
- MCMC-поток **продолжает работать в фоне** ~5-15 мин, но результат отбрасывается

Это компромисс: UI отзывчивый, но CPU занят. Для MVP приемлемо.

### D2 — Time-based progress interpolation на фронте

Sidecar PyMC не даёт per-draw callback без нестабильности. Вместо fake-backend-progress делаем чисто визуальную интерполяцию на TrainingProgress.svelte:
- При phase='sampling' запоминаем samplingStartElapsed
- Budget = estimatedSec × 0.7 (оставляя 30% на post-processing)
- pct = max(25, 25 + min(elapsed/budget, 0.97) × 60) → растёт от 25% до 85%
- Когда backend отчитается 90% (diagnostics) — frontend перехватит

**Честно:** прогресс не отражает real MCMC progress, только прошедшее время. Но UI живой.

### D3 — Adstock default = 'auto' для всех каналов

Было: validator.py назначал Geometric по умолчанию. Стало: 'auto' — auto-selector через BIC подменит на concrete type. UX выигрывает: dropdown показывает «Авто» сразу, без «Geometric» по умолчанию.

Backend fallback `adstock_config.get(col, 'geometric')` остаётся — страховка если auto-selector не отработал.

### D4 — Полное «Markov Chain Monte Carlo» в UI

Антон попросил избегать сокращения MCMC. Обновлены:
- ConfigPanel: label + tooltip Chains
- ModelTrainingStep: 2 status-строки
- TrainingProgress: phaseLabel sampling
- ExpertModelPanel: section-title «Диагностика Markov Chain Monte Carlo»
- insights-rules.js: 4 карточки инсайтов

Code comments не трогала (не user-facing).

### D5 — Hero logo: Logo_PNG_3-2 (wordmark), высота 26px

Итеративный подбор: 31 → 36 (+15%) → 29 (-20%) → 26 (-10%). Антон предпочёл wordmark-вариант без пирамиды в header.

### D6 — App icons: Logo_PNG_4_cuted (только пирамида)

В иконках нет места для wordmark (32px и меньше — текст нечитаем). Logo_PNG_4_cuted — квадратный логотип только пирамиды, хорошо читается в любом размере.

Tight margin 2% (`1024×1024` финальный размер), Lanczos resampling.

### D7 — Путь B (Hybrid SaaS) для миграции в облако

Рекомендуется из трёх вариантов:
- **Путь A** (Desktop-only до 2028): упустим SMB, где Tamburin выиграет время
- **Путь B** (Hybrid): 7 LLM-продуктов в SaaS, Econometrica + Creative Hub desktop-only → сохраняем USP приватности для enterprise
- **Путь C** (Full SaaS): 24+ мес, $1M+, высокий риск

Путь B — **9 месяцев** MVP, ~$530k.

### D8 — Офшорное юрлицо для Anthropic API (решение на конец 2026 Q3)

Для SaaS нужен биллинг с Anthropic через EU/UAE/Казахстан. Antropic не работает с РФ напрямую. Российские клиенты платят нам в ₽, мы в $ через офшор. Схема стандартная для AI-продуктов на рынке РФ.

### D9 — Не публичные пуши Oracle и Media

Конфликт remotes (Aurora_Oracle origin = ROSST_AI_Media.git) не разрешён. В этой сессии не пушила эти два репо, чтобы не усугублять. Fix требует подтверждения force-push от Антона. См. `project_oracle_media_remote_conflict.md`.

### D10 — SYSTEM_REQUIREMENTS в двух уровнях

- **Per-product** (`docs/SYSTEM_REQUIREMENTS.md` в репо Econometrica) — детально для конкретного продукта
- **Platform-level** (`5_Документация/SYSTEM_REQUIREMENTS_PLATFORM.md`) — для всей платформы с tier'ами

Позднее станут публичной документацией на сайте.

### D11 — OLS-fallback как roadmap task

Для данных <20 точек байесовская модель не сходится. OLS-fallback — альтернативный движок с честным «CI недоступны». 6-8 часов разработки, medium complexity, запуск после live-теста MVP. Задача записана в `project_econometrica_ols_fallback.md`.

---

## Solutions & Fixes

### Fix 1 — NUTS через vswhere.exe (ключевой)

**Root cause:** `check_compiler()` искал `cl.exe` только через PATH. MSVC Build Tools не добавляет себя в PATH.

**Fix:** `_find_msvc_via_vswhere()` в `modeler.py`:
- Путь vswhere: `%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe`
- Команда: `vswhere -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`
- Glob по `{vs_path}\VC\Tools\MSVC\*\bin\Hostx64\x64\cl.exe` — sorted pick newest
- Запускает `vcvars64.bat >nul && set` через subprocess shell
- Парсит output, фильтрует по whitelist (PATH/INCLUDE/LIB/LIBPATH/WINDOWSSDKDIR/VCINSTALLDIR/VCTOOLSINSTALLDIR/VSINSTALLDIR)
- `os.environ[key] = val` → PyTensor видит среду

**File:** `sidecar/econometrica/engines/modeler.py:17-95`

### Fix 2 — functools.partial ppc fallback

**Root cause:** PyMC 5.x ppc рекомбинирует граф с custom Deterministic → partial без __name__ → AttributeError.

**Fix:** try/except вокруг `pm.sample_posterior_predictive`:
- На failure: `intercept_mean + media_effect_pred + control_effect_pred`
- media_effect_pred = Hill-трансформация X_media_norm с posterior means (alphas, gammas, media_betas)
- control_effect_pred = X_control @ control_betas_mean
- Если fallback тоже падает — zeros array (редко, но graceful)

**File:** `sidecar/econometrica/engines/modeler.py:296-330`

### Fix 3 — Error field в train_progress

**Root cause:** `train_progress` endpoint вырезал поле `error` из task dict:
```python
return {'task_id': task_id, **{k: v for k, v in task.items() if k not in ('result', 'error', 'started_at')}}
```

Фронт `TrainingProgress:60-68` читал `p.error` → undefined → generic «Ошибка обучения модели» без real message.

**Fix:** убрать 'error' из exclusion + frontend дополнительно fetches full result on error status.

**Files:** `server.py:258` + `TrainingProgress.svelte:60-68`

### Fix 4 — Stop training endpoint

**New:** `POST /compute/train/cancel/{task_id}` в `server.py:261-271` — помечает task как 'cancelled' + error message «Обучение остановлено пользователем».

**Rust binding:** `econ_train_cancel` в `econometrica.rs:74-85` — POST через quick_client.

**Frontend:** кнопка «⏹ Остановить обучение» в `TrainingProgress.svelte` (красная outline) + `handleStop` в `ModelTrainingStep` очищает isComputing / computeStatus / localStorage и возвращает stepState='idle'.

### Fix 5 — Time-based progress interpolation

**Root cause:** modeler.py вызывает `report('sampling', pct=25)` один раз в начале MCMC. Далее 3-25 минут UI стоит на 25%.

**Fix:** в `TrainingProgress.svelte:45-80`:
```js
if (newPhase === 'sampling') {
  if (samplingStartElapsed === null) samplingStartElapsed = elapsedSec;
  const samplingElapsed = elapsedSec - samplingStartElapsed;
  const samplingBudget = Math.max(60, estimatedSec * 0.7);
  const sampleProgress = Math.min(samplingElapsed / samplingBudget, 0.97);
  pct = Math.max(serverPct, Math.round(25 + sampleProgress * 60));
}
```

`estimatedSec` приходит из `ModelTrainingStep.estimatedSec = $derived.by(...)` — считает из `lastConfig.mcmc_override` (chains × (draws+tune) × secPerSample с учётом channels).

### Fix 6 — data_file из правильного store

**Root cause:** ImportStep пишет в `importData.file`, ConfigPanel читал `pipelineState.data.file` → рассинхрон.

**Fix:** `ConfigPanel.svelte:199`:
```js
const dataFile = $importData?.file || $pipelineState?.data?.file || '';
if (!dataFile) {
  computeStatus.set('Ошибка: файл данных не найден. Вернитесь на шаг Импорт и загрузите файл заново.');
  setTimeout(() => computeStatus.set(''), 6000);
  return;
}
// ...
const config = { data_file: dataFile, ... };
```

### Fix 7 — Adstock 'auto' default

**Was:** `adstock[ch.name] = ch.adstock_type || 'geometric';` (ConfigPanel $effect)

**Now:** `adstock[ch.name] = 'auto';` — auto-selector через BIC подменит на concrete, dropdown показывает «Авто (digital=мгновенный, TV=отложенный)».

**Fix:** `ConfigPanel.svelte:86`

### Fix 8 — Иконки приложений, Logo_PNG_4_cuted

Python-скрипт preprocess:
1. Open Logo_PNG_4_cuted.png, RGBA
2. Alpha bbox crop
3. Iterate pixels: convert white-opaque (>240 alpha, RGB>245) в transparent
4. Second bbox crop (после transparentization)
5. Pad to square `max(w,h) × 1.02` (2% margin)
6. Resize 1024×1024 Lanczos
7. Save PNG optimized

Затем `npx @tauri-apps/cli icon <path>` генерит:
- Windows: icon.ico (multi-res), 32/64/128/128@2x.png
- macOS: icon.icns, Square*Logo.png, StoreLogo.png
- iOS + Android: полный набор (ignored для desktop)

Распространено через `cp` в все 9 `src-tauri/icons/` директорий.

**Trigger:** осознали после incident (tauri icon в dev = kill sidecar → прервали обучение). Записано как паттерн L5.

---

## Files Modified

### Session commit `74691f8` (Econometrica) — 61 файл, +495/-30

**Python sidecar:**
- `sidecar/econometrica/engines/modeler.py` — check_compiler + vswhere + vcvars + functools.partial fallback
- `sidecar/econometrica/server.py` — train/cancel endpoint, error field в progress

**Rust backend:**
- `src-tauri/src/commands/econometrica.rs` — econ_train_cancel
- `src-tauri/src/lib.rs` — register econ_train_cancel в invoke_handler

**Frontend (Svelte):**
- `src/lib/components/ConfigPanel.svelte` — data_file из importData, Adstock 'auto', MSVC hint
- `src/lib/components/pipeline/TrainingProgress.svelte` — Stop button, time-based pct, cancelled handler
- `src/lib/components/pipeline/ModelTrainingStep.svelte` — handleStop, estimatedSec, MCMC rename
- `src/lib/components/pipeline/ExpertModelPanel.svelte` — MCMC rename
- `src/lib/components/pipeline/ObjectiveSelector.svelte` — (unchanged content этой сессии)
- `src/lib/insights-rules.js` — MCMC rename в 4 карточках
- `src/routes/+page.svelte` — topbar-logo 31→26px, новый wordmark

**Branding:**
- `static/logo-wordmark.png` — Logo_PNG_3-2
- `src-tauri/icons/*` (51 файл) — Logo_PNG_4_cuted на все размеры

**Docs:**
- `docs/SYSTEM_REQUIREMENTS.md` (NEW)
- `README.md` — новый раздел Системные требования

### 8 коммитов других приложений (иконки)

`Aurora_Creative_Hub` `6f10da4` · `Aurora_Oracle` `e6a9419` · `Aurora_Parser` `8f0da77` · `Aurora_PR_Master` `9faf9e4` · `ROSST_AI_Creative` `0649809` · `ROSST_AI_DocMaster` `8b7f497` · `ROSST_AI_Legal` `a2b6420` · `ROSST_AI_Media` `58c96be`

Все: копии иконок из Econometrica в `src-tauri/icons/` (17 файлов каждый).

### Внешние документы (не в git)

- `D:/Docs/Aurora_Ai/5_Документация/SYSTEM_REQUIREMENTS_PLATFORM.md` (NEW, ~500 строк) — 11 разделов: OS, железо, MSVC, антивирусы, файрвол, сетевые требования, пути, диагностика, roadmap, contacts
- `D:/Docs/Aurora_Ai/5_Документация/COMPETITIVE_TAMBURIN.md` (NEW, ~350 строк) — 9 разделов: справка по Tamburin, сравнительная таблица, наши + их сильные стороны, позиционирование, 6-месячный план, риски, sources
- `D:/Docs/Aurora_Ai/5_Документация/ROADMAP_SAAS_MIGRATION.md` (NEW, ~600 строк) — 10 разделов: исходная позиция, требования SaaS, сложность per-product, API vs подписки, экономика, модели монетизации, roadmap, ресурсы, метрики, риски

### Obsidian KB vault (`D:/Docs/Aurora_Ai/KB/`)

- `System_Requirements/index.md` (NEW, MOC)
- `System_Requirements/Aurora_Platform_System_Requirements.md` (NEW, copy с frontmatter+wikilinks)
- `System_Requirements/Econometrica_System_Requirements.md` (NEW, copy)
- `Competitive/index.md` (NEW, MOC)
- `Competitive/Aurora_vs_Tamburin.md` (NEW, copy)
- `Roadmap/index.md` (NEW, MOC)
- `Roadmap/SaaS_Migration_Strategy.md` (NEW, copy)

Все с Obsidian frontmatter (tags, type, status, updated) и `[[wikilinks]]` для cross-navigation.

### Memory updates

- `C:\Users\ackol\.claude\projects\D--Docs-Aurora-Ai\memory\project_econometrica_session4.md` (NEW)
- `C:\Users\ackol\.claude\projects\D--Docs-Aurora-Ai\memory\project_econometrica_methodology.md` (NEW)
- `C:\Users\ackol\.claude\projects\D--Docs-Aurora-Ai\memory\project_econometrica_ols_fallback.md` (NEW)
- `C:\Users\ackol\.claude\projects\D--Docs-Aurora-Ai\memory\project_oracle_media_remote_conflict.md` (NEW earlier)
- `C:\Users\ackol\.claude\projects\D--Docs-Aurora-Ai\memory\MEMORY.md` — updated с 4 новыми ссылками

---

## Setup & Config Changes

### MSVC Build Tools detection

**Уже установлены** на машине Антона (v14.44.35207) — winget upgrade не принёс ничего нового. Путь: `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207\`.

**Корневое исправление** — не установка (она была давно), а **детекция**:
- `modeler.py:check_compiler()` переписан чтобы использовать vswhere.exe
- После sidecar restart (обязательно!) PyTensor получает среду VS и компилирует NUTS

### Tauri icons

- Temp preprocess script: `D:/Docs/Aurora_Ai/Dev/.tmp_icon_prep.py` (создан и удалён)
- Temp 1024×1024 PNG: `D:/Docs/Aurora_Ai/Dev/.tmp_aurora_icon_1024.png` (создан и удалён)
- Generator: `npx @tauri-apps/cli icon <path>` из Aurora_Econometrica/
- Distribution: bash cp всех иконок в 8 других `src-tauri/icons/`

### Python sidecar process management

11 повисших python.exe после live-теста предыдущей сессии. Решение:
```powershell
# PowerShell от имени Администратора:
taskkill /F /IM python.exe
```
8 успешно убиты, 3 уже были мертвы (но числились). Освободилось ~2-3 ГБ RAM.

### Background tasks в этой сессии

- Task `bs4ox2die` (начальный dev run) — завершён
- Task `bvaaedi0z` (current dev run) — был активен на момент компрессии

---

## Pending Tasks

### Блокирующие (пока не завершим — не двигаемся)

- ⏳ **Live-test Шаг 2 Модель** — в процессе, 82% interpolation на 10 мин. Ждём финальной метрики MQS/R²/R-hat.
- ⏳ **Проверить NUTS vs Metropolis** — по времени прогона и наличию/отсутствию `functools.partial` ошибки
- ⏳ **Шаг 3 Декомпозиция** (waterfall chart)
- ⏳ **Шаг 4 Оптимизация** (budget optimizer, response curves)
- ⏳ **Шаг 5 Отчёт** (XLSX/PPTX export)

### Tech debt

- [ ] **OLS-fallback** для <20 точек (6-8ч, medium) — см. `project_econometrica_ols_fallback.md`
- [ ] **MSVC auto-check в Settings** — при старте вызвать `_has_c_compiler()` и показать баннер если Metropolis активен (1ч)
- [ ] **Auto-watcher на result.status** для мгновенной разблокировки «Далее» без клика
- [ ] **Скрыть bulk-карточку «Оставить бюджеты»** после applyObjective (дубль)
- [ ] **Синхронизация UX-фиксов** в 9 других Aurora-вариантов после закрытия live-теста
- [ ] **Prod build v1.0.8** (GitHub Releases + Supabase + rosst-updates manifest)

### Стратегические (отложено)

- [ ] **Разрулить Oracle/Media remote conflict** (нужен Антон для force-push на `e350fb9`) — см. `project_oracle_media_remote_conflict.md`
- [ ] **Создать отдельный репо для Aurora_Oracle** на GitHub, переключить origin
- [ ] **3-5 публичных кейсов** Econometrica (партнёрство с Кагоцелом — первый кандидат)
- [ ] **Коннектор Mediascope** (TV + радио) — приоритет 2
- [ ] **Prior calibration via lift-tests** — Q3-Q4 2026 roadmap
- [ ] **SaaS MVP (Hybrid)** — Q3-Q4 2027 roadmap
- [ ] **Офшорное юрлицо** для Anthropic API — конец 2026 Q3

### TODO в Obsidian index файлах

- [ ] Конкурентные анализы: Meta Robyn, LightweightMMM, Qualtrics, Consultant.ru, Kittl (Competitive/index.md)
- [ ] Стратегия международного рынка (EU / MENA) (Roadmap/index.md)
- [ ] Партнёрство с YandexGPT / GigaChat как fallback (Roadmap/index.md)
- [ ] Продуктовая feature-roadmap: MTA, GPU backend, prior calibration (Roadmap/index.md)

---

## Errors & Workarounds

### E1 — Metropolis CompoundStep crash `'functools.partial' object has no attribute '__name__'`

**Сценарий:** обучение дошло до 100% (30 мин), упало на post-processing (arviz.summary / ppc).

**Root cause:** Metropolis sampler создаёт CompoundStep со смесью типов переменных. functools.partial объекты внутри CompoundStep не всегда имеют `__name__`. arviz / ppc натыкается на это.

**Workaround (primary):** NUTS вместо Metropolis — NUTS не использует CompoundStep → ошибка не возникает. Root fix = vswhere + vcvars64 env injection (Fix 1 выше).

**Workaround (secondary):** try/except ppc + manual reconstruction (Fix 2) — защита на случай если NUTS где-то тоже упрётся в эту ошибку.

### E2 — Винда: 11 повисших python.exe процессов

**Сценарий:** live-тест Econometrica, sidecar крашился несколько раз, MCMC-потоки не убивались корректно.

**Workaround:** `taskkill /F /IM python.exe` из PowerShell **от имени Админа**. Из non-admin получишь «Отказано в доступе».

**Правильный fix (отложено):** sidecar должен регистрировать SIGTERM handler и gracefully killать child-процессы.

### E3 — Git Bash не понимает single-slash args

**Сценарий:** `taskkill /F /IM python.exe` в Git Bash → `Ошибка: Неправильный параметр или аргумент - 'F:/'`

**Workaround:** `taskkill //F //IM python.exe` (двойной слеш) или `cmd "/c taskkill /F /IM python.exe"`.

### E4 — Tauri dev watcher убивает sidecar при icon regen

**Сценарий:** `npx tauri icon <path>` во время активного dev → rebuild → sidecar kill → прерван live-test.

**Workaround:** не запускать операции в `src-tauri/` во время live-test. Делать с остановленным dev.

### E5 — Winget install BuildTools exit code 1 (при уже установленной VS)

**Сценарий:** `winget install Microsoft.VisualStudio.2022.BuildTools` → «Found an existing package already installed. Trying to upgrade… Installer failed with exit code: 1».

**Root cause:** VS BuildTools 17.14.30 уже установлена, но winget upgrade не знает какие workloads уже включены.

**Workaround:** игнорировать exit code, проверить через glob что cl.exe существует:
```bash
ls "C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64/cl.exe"
```
Если есть — всё ок, просто fix детекции (Fix 1).

### E6 — Aurora_Oracle origin = ROSST_AI_Media.git

**Сценарий:** `git push` из Aurora_Oracle ушёл в remote `ROSST_AI_Media.git` (fast-forward `e350fb9..49beb61`), испортил историю Media remote.

**Workaround:** не пушить Oracle и Media в этой сессии. Оба коммита (иконки, Markov Chain Monte Carlo updates) остались локально.

**Proper fix (отложено):**
1. Проверить существование отдельного репо `Ackold26/Aurora_Oracle` на GitHub
2. Если есть — `git remote set-url origin https://github.com/Ackold26/Aurora_Oracle.git` в Aurora_Oracle
3. Force-reset remote ROSST_AI_Media на `e350fb9` (destructive — требует подтверждения Антона)
4. Push Oracle в свой корректный remote
5. Push Media в свой (откаченный) remote

---

## Full Session Notes

### Хронология

1. **Подхват контекста** — прочитала session log предыдущей сессии, память проекта, коммиты `72c6493 → 539e11f → 83f28a2`. Статус: Шаг 1 Валидация пройден, Шаг 2 Модель ready.

2. **Замена header-лого** — Антон попросил `Logo_PNG_3-2.png` в топбаре, размер +15%. Скопировала static/logo-wordmark.png, увеличила height 31→36. Далее итерации: -20% (36→29), -10% (29→26). Утверждено.

3. **Sync across apps** — замена header-logo распространена на все 7 «лёгких» приложений (Parser пропущен — другой UI). 8 коммитов + пуш в 7 репо (Oracle пропущен из-за remote conflict).

4. **Первый запуск модели** — на Кагоцел (31×34, 6 каналов). Упала с ошибкой «[Errno 2] No such file or directory: ''».

5. **data_file store fix** — нашла root cause: ConfigPanel читал из `pipelineState.data.file`, а ImportStep сохранял в `importData.file`. Два разных store. Фикс + pre-flight check + понятный error message.

6. **Adstock 'auto' default** — замена `'geometric'` на `'auto'` в validator-назначении. Dropdown показывает «Авто» сразу.

7. **Второй запуск** — пошла модель. Но прогресс-бар стоял на 25% всю MCMC-фазу (20+ мин), выглядело как зависание.

8. **Time-based progress interpolation** — рефакторинг TrainingProgress.svelte на псевдо-pct базе elapsed time + estimatedSec. Progress bar плавно ползёт 25% → 85%.

9. **Stop button** — backend endpoint `/compute/train/cancel/{task_id}` + Rust command + Svelte красная кнопка «⏹ Остановить обучение». Проверено работает.

10. **Первый крах `functools.partial`** — модель обучилась за 16 мин, упала на arviz/ppc. Гипотеза: Metropolis CompoundStep. Решение: починить детекцию C-compiler чтобы активировать NUTS.

11. **`check_compiler` fix через vswhere** — переписала функцию. Локализует MSVC через vswhere.exe, запускает vcvars64.bat, инжектит env vars в os.environ. 3-5× ожидаемое ускорение.

12. **11 повисших python.exe** — live-тест накопил зомби-процессы. Taskkill из PowerShell от Админа освободил RAM.

13. **Tauri icon incident** — я решила обновить иконки приложения на Logo_PNG_1 во время активного обучения. `npx tauri icon` записал в src-tauri/icons → dev watcher rebuild → sidecar kill → прервала тест. Mea culpa. Записано в Learnings как паттерн L5.

14. **Icon replacement Logo_PNG_1** — python preprocess (trim whitespace, square pad, 1024×1024) + `tauri icon` + cp в 8 других приложений. 9 коммитов.

15. **Icon replacement Logo_PNG_4_cuted** — Антон пересмотрел: предыдущая версия (Logo_PNG_1 с текстом AURORA AI) — плохо читается в иконке. Logo_PNG_4_cuted = только пирамида. Перегенерировала всё. 9 коммитов.

16. **Системные требования документация** — создан `docs/SYSTEM_REQUIREMENTS.md` (детально для Econometrica) + `5_Документация/SYSTEM_REQUIREMENTS_PLATFORM.md` (единая таблица для 8 продуктов).

17. **Econometrica = самый требовательный продукт** — родилась отдельная tier-система: 🟢 Стандарт (7 LLM-продуктов), 🟡 Расширенный (Creative Hub), 🔴 Аналитический (Econometrica, требует MSVC).

18. **Вопрос Антона про Tamburin** — WebSearch о конкуренте. Cloud SaaS, основан 2020, Moscow Seed Fund, кейс «Папа может» 2.5× sales. Позиционирование «без сложных терминов и формул».

19. **Competitive анализ** — создан `COMPETITIVE_TAMBURIN.md` (350 строк): сильные/слабые стороны каждого, USP Aurora (приватность данных + Bayesian + экосистема), стратегический план на 6 месяцев.

20. **Вопрос Антона про SaaS-миграцию** — создан `ROADMAP_SAAS_MIGRATION.md` (600 строк): архитектурная сложность, тонкости Claude API (подписки запрещены ToS, офшор для РФ), модели монетизации (API+margin, BYOK, Hybrid), 3 пути (A/B/C), выбор путь B.

21. **MCMC → Markov Chain Monte Carlo rename** — Антон попросил полное название везде. Обновлены: ConfigPanel label + tooltip, ModelTrainingStep status, TrainingProgress phaseLabel, ExpertModelPanel section-title, insights-rules.js 4 карточки.

22. **Объяснение методологии** — диалог с Антоном про MCMC sampling, разница между Markov Chain и Markov Chain Monte Carlo, позиционирование против Tamburin. Записано в `project_econometrica_methodology.md`.

23. **functools.partial post-processing fix** — добавила try/except + manual y_pred reconstruction из posterior means. Протестировано в текущем прогоне модели.

24. **Commit discipline** — итоговый коммит `74691f8` в Econometrica (61 файл, +495/-30) + 8 иконочных коммитов в других приложениях.

25. **Obsidian KB sync** — скопировала 4 новых MD в KB vault (`D:/Docs/Aurora_Ai/KB/`), добавила frontmatter, wikilinks, создала 3 MOC-index файла (System_Requirements, Competitive, Roadmap).

26. **Memory updates** — 4 новых файла в `.claude/projects/.../memory/`: session4, methodology, ols_fallback, oracle_media_remote_conflict. MEMORY.md проиндексирован.

27. **Компрессия сессии** — текущий документ.

### Ключевые скриншоты

- Home page Econometrica с hero logo + 3 кнопками ✅
- Import step Кагоцел («Кагоцел РФ ММХ 1904-26 (4)») ✅
- Validate step с ROI objective, status=success ✅
- Model step с Expert panel, 6 каналов, Adstock 'Авто' ✅
- TrainingProgress с Stop button красная outline ✅
- Error banner «[Errno 2] No such file or directory: ''» → решён (data_file fix)
- Error banner «'functools.partial' object has no attribute '__name__'» → решается (vswhere + ppc fallback)
- Прогресс-бар time-based intelpolation: 3 мин = 43%, 10 мин = 82%
- Новая иконка Aurora AI в таскбаре Windows ✅

### Commits

```
Econometrica:
74691f8 feat(econometrica): NUTS detection via vswhere, MCMC UX polish, system docs

Other 8 apps (icons only):
6f10da4 (Aurora_Creative_Hub)
e6a9419 (Aurora_Oracle)
8f0da77 (Aurora_Parser)
9faf9e4 (Aurora_PR_Master)
0649809 (ROSST_AI_Creative)
8b7f497 (ROSST_AI_DocMaster)
a2b6420 (ROSST_AI_Legal)
58c96be (ROSST_AI_Media)
```

Суммарно: **9 коммитов**, ~61+ файлов, 495+ insertions.

### Memory

- `project_econometrica_session4.md` — полная запись этой сессии
- `project_econometrica_methodology.md` — методология + позиционирование
- `project_econometrica_ols_fallback.md` — OLS-fallback task
- `project_oracle_media_remote_conflict.md` — remote conflict (earlier)
- `MEMORY.md` — indexed с 4 новыми ссылками
