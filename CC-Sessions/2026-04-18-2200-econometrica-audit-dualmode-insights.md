---
tags: [session, compressed, audit, dual-mode, insights, rebrand, phase7, phase8, phase9]
type: session
updated: 2026-04-18
---
# Quick Reference
Масштабный аудит Econometrica v1.0.1: найдено и исправлено 20+ багов (13 незарегистрированных команд, ребрендинг Analytics Hub, ECharts theme, taskId persist). Реализованы Phase 7A (offline insights engine — 30 правил), Phase 7B (miROAS в UI), Phase 8 (dual-mode marketer/expert с 3 ExpertPanel компонентами), Phase 9 (assisted pipeline с auto-fix recommendations). Создан Next-Gen Plan v2 с критическим аудитом (12 проблем найдены и исправлены в плане). Использован NotebookLM (40 источников по MMM-индустрии 2025-2026).

Topic: Econometrica audit + dual-mode + insights
Key files: lib.rs, cabinet.rs, econometrica.rs, project-state.js, insights-rules.js, InsightsPanel.svelte, OptimizeStep.svelte, ExpertValidatePanel.svelte, ExpertModelPanel.svelte, ExpertDecomposePanel.svelte, pipeline/+layout.svelte, manifest.json, server.py
Status: Phases 7A, 7B, 8, 9 DONE. Next: Phase 10 (Claude AI Tier 2), Phase 11 (diagnostics), Phase 12 (cross-product), PPTX/XLSX export

## Learnings

### False positives от Explore-агентов
- Агент заявил `xSafe` undefined в hill.js:32 — проверка показала что определён корректно
- Агент заявил gamma scaling mismatch modeler↔frontend — на самом деле модель работает с normalized data, optimizer и frontend оба используют `max(gamma * current_spend, 1)` — формулы идентичны
- **Правило:** Всегда верифицировать находки агентов вручную (`feedback_verify_agent_findings.md` подтверждён)

### mod.rs не автоматически содержит все .rs файлы
- project.rs и report.rs существовали как файлы, были в mod.rs, НО mod.rs фактически НЕ содержал их (они были добавлены в эту сессию)
- Cargo check поймал ошибку — `could not find report in commands`
- Всегда проверять и mod.rs И lib.rs invoke_handler при добавлении команд

### `<` в Svelte template = парсится как HTML тег
- ExpertDecomposePanel: `Efficiency < 1.0x` в тексте → Svelte Error "Expected valid element name"
- Fix: `&lt;` и `&gt;` для HTML entities в text content

### Content-packs manifest.json + help/ файлы
- manifest.json ссылался на 20+ help/*.html которые НЕ существовали → verify_manifest() ВСЕГДА FAIL → content_packs_verified = false → dynamic content packs никогда не загружались
- Fix: убрал help/ из manifest, пересчитал хеши, переподписал через aurora-pack.py

### aurora-pack.py не знала "econometrica"
- PRODUCT_CABINETS dict не содержал "econometrica" → argparse reject
- Fix: добавил `"econometrica": ["econometrist"]` в dict

## Solutions & Fixes

### Коммит b56a369 — Phase 7A+7B + аудит (24 файла)
| Категория | Исправление | Файлы |
|-----------|------------|-------|
| **SHOWSTOPPER** | 13 project/report команд зарегистрированы | lib.rs, commands/mod.rs |
| **SHOWSTOPPER** | ProjectSelector подключён в pipeline layout | pipeline/+layout.svelte |
| **SHOWSTOPPER** | filter_by_product: добавлен "econometrica" | cabinet.rs |
| Ребрендинг | manifest.json product "econometrica", help/ убраны | content-packs/* |
| Ребрендинг | Error dialogs → "Econometrica" | lib.rs:3160,3173 |
| Ребрендинг | WebView cache: +com.aurora.econometrica | lib.rs:2886 |
| Ребрендинг | CSS class brand-rosst → brand-product | +page.svelte |
| Ребрендинг | command-meta-data.json: +econometrica section | content-packs |
| Bug fix | ECharts theme-reactive через CSS vars | EChartBase.svelte, echarts-setup.js, ResponseCurves.svelte |
| Bug fix | taskId persist в localStorage | ModelTrainingStep.svelte |
| Bug fix | retryTraining реально ретраит | ModelTrainingStep.svelte |
| Bug fix | confirm перед resetDownstream | ImportStep.svelte |
| Bug fix | column mapping persist | ValidateStep.svelte |
| Bug fix | server.py task retention 5 мин | server.py |
| Bug fix | onboarding-data → econometrist | onboarding-data.json |
| Perf | Static reqwest::Client (OnceLock) | econometrica.rs |
| Policy | trash::delete для project_delete | project.rs, Cargo.toml |
| UX | Оценка времени обучения | ConfigPanel.svelte |
| **Phase 7A** | insights-rules.js: 30 offline правил | insights-rules.js (NEW) |
| **Phase 7A** | InsightsPanel: severity badges, tips | InsightsPanel.svelte |
| **Phase 7B** | miROAS в OptimizeStep | OptimizeStep.svelte |

### Коммит bbfc451 — Phase 8+9 (9 файлов)
| Категория | Исправление | Файлы |
|-----------|------------|-------|
| **Phase 8** | expertMode store (persisted) | project-state.js |
| **Phase 8** | Toggle Маркетолог/Эксперт | pipeline/+layout.svelte |
| **Phase 8** | ExpertValidatePanel (corr, VIF, stats) | ExpertValidatePanel.svelte (NEW) |
| **Phase 8** | ExpertModelPanel (MCMC diag, params) | ExpertModelPanel.svelte (NEW) |
| **Phase 8** | ExpertDecomposePanel (spend vs effect) | ExpertDecomposePanel.svelte (NEW) |
| **Phase 9** | Auto-fix recommendations UI | ValidateStep.svelte |
| **Phase 9** | Quick-nav "Далее: Валидация" | ImportStep.svelte |

## Decisions

### Архитектурные (из аудита Next-Gen Plan v2)
1. **AI Insights двухуровневые:** Tier 1 offline rules (insights-rules.js) + Tier 2 Claude optional — решает противоречие offline-first vs AI
2. **Expert panels = отдельные компоненты:** Не `{#if}` × 75, а 1 `{#if}` per step → ExpertPanel. Инкапсуляция, lazy-load
3. **Auto-fix разделены на safe/risky:** Safe = авто с уведомлением. Risky (merge каналов, обнулить отрицательные, winsorize) = только warning + confirm
4. **"Assisted Pipeline" вместо "One-Click":** auto-detect + confirmation step (30 сек) перед training. Domain knowledge нельзя угадать
5. **Промпты AI не в content-packs:** manifest.sig = Ed25519 bottleneck. Промпты в vault кабинета
6. **Progress bar честный:** Не 33% при старте (манипуляция для B2B = потеря доверия)
7. **Subtle feedback вместо фейерверков:** Зелёная пульсация, не анимация для CFO-инструмента
8. **miROAS = marginalROI() из hill.js:** Функция уже существовала, просто показали в UI
9. **Trace plots server-side PNG:** Full trace 50-200MB → matplotlib → PNG в project_dir/models/diagnostics/
10. **Cross-product через файлы:** Aurora products = отдельные .exe, нет IPC. Конвенция: `%USERPROFILE%/Aurora AI/Exports/{product}/`

### Стратегические
- **Ниша:** Единственный десктопный MMM без SaaS. Privacy by architecture.
- **Не конкурируем по цене** с SaaS ($100-500K/год). Конкурируем по privacy + AI interpretation + Aurora ecosystem
- **NotebookLM insight:** Bayesian MMM = стандарт 2026, campaign-level = вектор развития, триангуляция (MMM + incrementality) = must-have

## Pending

### Следующие фазы (по оптимизированному плану)
- **Phase 10:** Claude AI Insights Tier 2 — кнопка "Спросить AI", prompt templates в vault [2 дня]
- **Phase 11:** Advanced Diagnostics — trace plots PNG, CI на waterfall, model versioning, sensitivity [2-3 дня]
- **Phase 12:** Cross-Product Integration — file convention, /mmm-to-slides, /mmm-to-doc, brand context [3-5 дней]

### PPTX/XLSX Export (спецификация готова, код нет)
- PPTX: 10-12 слайдов с графиками через python-pptx в sidecar
- XLSX: 7 листов (vs 4 текущих), формулы, charts, conditional formatting, глоссарий
- Спецификация в: `C:\Users\ackol\Desktop\Aurora Econometrica — Next-Gen Plan v2.md` и plan file

### Непокрытые процессы
- P1: Undo/Rollback для auto-fix (previousState)
- P2: Model versioning (models/history/)
- P3: Sidecar crash recovery (timeout → UI reset)
- P4: ECharts lazy-init (step-aware, dispose on leave)
- P5: Cross-product IPC через файловую конвенцию

### Память проекта обновлена
- `project_econometrica.md`: v1.0.2 + v1.0.3 описаны, статус фаз обновлён

## Errors & Workarounds

### Explore-агенты отклонены пользователем
- **Ситуация:** Запустил 2 Explore-агента в начале сессии
- **Реакция:** Антон отклонил, сказал "продолжай"
- **Workaround:** Использовал Glob/Grep/Read напрямую
- **Lesson:** Для этого проекта — прямые инструменты, не агенты

### mod.rs не содержал project/report
- **Ошибка:** Добавил commands в lib.rs invoke_handler, но mod.rs не имел `pub mod project; pub mod report;`
- **Cargo check:** `could not find report in commands` (14 errors)
- **Fix:** Добавил 2 строки в mod.rs → 0 errors за 1 итерацию

### Дублирующие переменные mcmcChains
- **Ошибка:** Добавил `let mcmcChains = $state(2)` в ConfigPanel, но они уже были ниже на строке 76
- **Grep:** Нашёл дубли
- **Fix:** Убрал свои строки

### `<` в Svelte text → parse error
- **Ошибка:** `Efficiency < 1.0x` в ExpertDecomposePanel → "Expected valid element name"
- **Fix:** `&lt;` entity

### NotebookLM auth failed
- **Ошибка:** `nlm login` → Chrome DevTools port 9223 unavailable
- **Workaround:** Антон авторизовался вручную (`nlm login --manual`)

### unused imports warning
- **Ошибка:** `use commands::{..., project, report, ...}` → warning "unused imports project and report"
- **Причина:** Команды зарегистрированы через полный путь `commands::project::project_list`
- **Fix:** Убрал project, report из use statement

## Full Session Notes

### Хронология
1. Загрузка памяти проекта (project_econometrica.md, architecture_v3.md)
2. Plan mode: исследование кодовой базы (Glob, Grep, Read — 20+ файлов)
3. Первый план (15 файлов, 5 phases) → критический аудит → 12 проблем найдены → план v2
4. Реализация Phase 1-5 (showstoppers, ребрендинг, content packs, UX fixes, policy)
5. Компиляция: cargo check 0 errors, svelte-check 0 errors, cargo test 120/120
6. manifest.sig переподписан через aurora-pack.py
7. Технический аудит кода: 2 Explore-агента → false positives отсеяны → 6 реальных багов
8. Исправление 6 багов (retryTraining, confirm, column mapping, server task, time estimate)
9. NotebookLM: 3 запроса (AI+MMM, UX best practices, метрики/визуализации)
10. Next-Gen Plan v2 написан (9 разделов) → критический аудит плана (12 проблем) → план исправлен
11. PPTX/XLSX спецификация (10-12 слайдов, 7 листов)
12. Phase 7A: insights-rules.js (30 правил) + InsightsPanel переписан
13. Phase 7B: miROAS в OptimizeStep
14. Phase 8: expertMode store + toggle + 3 ExpertPanel компонента
15. Phase 9: auto-fix recommendations + quick-nav
16. 3 коммита, 2 тега, всё запушено

### Git
```
b56a369 feat: pipeline audit fixes, rebrand, insights engine, miROAS  (tag: v1.0.2-audit-fixes-insights)
bbfc451 feat: dual-mode (marketer/expert) + assisted pipeline UX      (tag: v1.0.3-dual-mode-assisted)
```

### Ключевые документы
- Next-Gen Plan v2: `C:\Users\ackol\Desktop\Aurora Econometrica — Next-Gen Plan v2.md`
- Аудит плана: `C:\Users\ackol\.claude\plans\lucky-tumbling-kahn.md`
- NotebookLM: `2e7d71d1-b5c1-4be4-be78-ca5105348172` (40 источников MMM 2025-2026)
