---
tags: [session, compressed, econometrica, pipeline, ux, live-test]
type: session
updated: 2026-04-18
---
# Quick Reference
Масштабный UX overhaul Pipeline Econometrica: 2 коммита (7e802c9 + 6192eea), 32 файла, ~1160 строк. Actionable инсайты с кнопками, кликабельные роли, реактивная валидация, theme contrast fix, автодетект ролей (RU). Live-тест прошёл Import+Validate, следующее — Model+.

Topic: econometrica-pipeline-ux-overhaul-live-test
Key files: insights-rules.js, InsightsPanel.svelte, ValidateStep.svelte, TrafficLight.svelte, ColumnMapper.svelte, ConfigPanel.svelte, ExpertValidatePanel.svelte, project-state.js, validator.py, app.css, +page.svelte, +layout.svelte (pipeline)
Status: Import+Validate полностью протестированы и доработаны. Model/Decompose/Optimize/Report — следующая сессия.

## Learnings

### Svelte 5 реактивность
- `get(store)` внутри `$derived` — НЕ реактивно. Используй `$storeName` для авто-подписки
- `$effect` с `$state` — если effect устанавливает state обратно (как insightsCollapsed), он перекрывает пользовательский ввод. Решение: отдельный `userCollapsed` state + `$derived`
- `{@const}` можно использовать ТОЛЬКО внутри `{#if}/{#each}`, не в `<div>` — Svelte compilation error

### Python sidecar
- Hot-reload НЕ перезапускает Python sidecar. Для обновления validator.py нужен полный рестарт приложения
- `result.dtypes` из `econ_data_preview` — это dict `{col: dtype}`, НЕ массив. Нужна нормализация в ImportStep
- Файлы нужно обновлять в ДВУХ местах: `sidecar/econometrica/engines/` И `sidecar/econometrica/_internal/engines/`

### WebView2 (Tauri)
- Нативный `<select>` dropdown обрезается overflow:auto контейнерами. Решение: кастомный dropdown с position:fixed
- HTML5 drag-drop в WebView2 нестабилен. Добавлен click-to-assign как fallback

### Темы
- Hardcoded цвета (rgba(148,163,184,...), #93c5fd, #86efac) не работают в светлых темах
- Всегда использовать CSS-переменные: var(--text-primary), var(--text-muted), var(--success), etc.
- Светлая тема не имела --success/--warning/--danger — добавлены

## Decisions

### Терминология ролей (утверждено Антоном)
- "Медиа" → **"Медиа и управляемые факторы"**: бюджет, показы, клики, визиты, цены, промо
- "Контроль" → **"Неуправляемые внешние факторы"**: SOM, SOV, SOS, конкуренты, сезонность, погода
- **SOM — НЕ KPI**, а внешний фактор (относительная метрика, зависит от конкурентов)
- **"конкурент" в названии** → ВСЕГДА внешний фактор (приоритетное правило в autodetect)
- **Цены и промо** — управляемые факторы (медиа), НЕ внешние

### UX решения
- Главная: только Visual Pipeline по центру, кабинеты убраны
- completeStep() НЕ авто-переключает шаг — пользователь сам нажимает "Далее"
- Кнопка Маркетолог/Эксперт: синяя/красная, скрыта на шаге Импорт
- Экспертные панели: красная рамка/фон
- Инсайты: actionable с кнопками "Исключить"/"Оставить бюджет" → обновляют validateData реактивно
- Предупреждения фильтруются при исключении каналов
- Тема/настройки доступны на всех шагах pipeline

### Автодетект ролей (MEDIA_PATTERNS / CONTROL_PATTERNS)
- MEDIA: показ, клик, визит, прочтен, просмотр, бюджет, расход, olv, banner, social, retail media, performance, радио, пресса, ooh, ots, digital, programmatic, цен, промо
- CONTROL: som, sov, sos, share_of, конкурент, сезон, дистрибуц, погод, праздни, запрос
- KPI: sales, revenue, market_share, conversions, units, volume, продажи, выручка, конверси, заказ

## Files Modified

### Коммит 1: 7e802c9 (Pipeline UX Overhaul) — 16 files, +916 -291
- `src/routes/+page.svelte` — Visual Pipeline центрирован, кабинеты убраны
- `src/routes/pipeline/+layout.svelte` — mode toggle, theme/settings кнопки, insights collapse fix
- `src/lib/components/pipeline/InsightsPanel.svelte` — rule-based инсайты, drag-resize, action buttons
- `src/lib/components/pipeline/ImportStep.svelte` — dtypes нормализация, shape/fileName
- `src/lib/components/pipeline/ValidateStep.svelte` — reactive result, filtered warnings
- `src/lib/components/pipeline/ModelTrainingStep.svelte` — $validateData реактивность
- `src/lib/components/pipeline/TrafficLight.svelte` — adaptive colors
- `src/lib/components/pipeline/ColumnMapper.svelte` — click-to-assign, labels
- `src/lib/components/pipeline/ExpertValidatePanel.svelte` — clickable roles, expert styling
- `src/lib/components/pipeline/ExpertModelPanel.svelte` — expert styling
- `src/lib/components/pipeline/ExpertDecomposePanel.svelte` — expert styling
- `src/lib/components/ConfigPanel.svelte` — custom dropdown (position:fixed)
- `src/lib/components/DataTable.svelte` — number formatting (Intl.NumberFormat ru-RU)
- `src/lib/insights-rules.js` — enhanced insights with actions
- `src/lib/project-state.js` — removed auto-advance from completeStep
- `sidecar/econometrica/engines/validator.py` — expanded RU patterns

### Коммит 2: 6192eea (Theme Contrast + Roles) — 16 files, +243 -102
- `src/app.css` — --success/--warning/--danger для светлой темы
- `src/lib/insights-rules.js` — dynamic ratio insight с кнопкой
- `src/lib/components/pipeline/TrafficLight.svelte` — clickable roles, adaptive val colors
- `src/lib/components/pipeline/ValidateStep.svelte` — collapsible sections, full width
- `src/lib/components/pipeline/ColumnMapper.svelte` — theme-aware chips/zones
- `src/lib/components/pipeline/InsightsPanel.svelte` — var(--text-muted) everywhere
- 6+ других pipeline компонентов — hardcoded colors → CSS vars
- `sidecar/econometrica/engines/validator.py` — SOM→control, OTS→media, competitor priority

## Pending

### Следующая сессия (TEST 5+):
1. **Шаг Модель** — проверить KPI/каналы после авто-детекта, запустить обучение
2. **Шаг Декомпозиция** — waterfall chart, base sales
3. **Шаг Оптимизация** — budget optimizer, response curves
4. **Шаг Отчёт** — XLSX/PPTX export
5. **Drag-drop** в ColumnMapper — не работает в WebView2, нужно дебажить или оставить click-to-assign
6. **Claude AI insights** — подключить Opus для глубокого анализа данных (требует новый Tauri command без cabinet session)
7. **Сборка prod** — после завершения live-теста

### Нерешённые UX вопросы:
- Скриншоты 398x344 — инструмент захвата пользователя сжимает, не найден в настройках CC
- ColumnMapper: drag-drop не работает в WebView2, только click-to-assign
- Инсайты на шаге Валидации до запуска валидации — пустые (норма, но можно улучшить)

## Errors & Workarounds

| Проблема | Причина | Решение |
|----------|---------|---------|
| `{@const}` compilation error | Нельзя внутри `<div>`, только в `{#if}/{#each}` | Вынесли в script как `$derived` |
| KPI/каналы пустые на шаге Модель | `get(validateData)` не реактивен в `$derived` | Заменили на `$validateData` |
| Инсайты пустые при импорте | `result.dtypes` — dict, не array; `for...of` падает | Нормализация в ImportStep: `Object.entries().map()` |
| Кнопка свернуть Инсайты не работает | `$effect` сразу возвращает `insightsCollapsed=false` | Отдельный `userCollapsed` state + `$derived` |
| Авто-переход шагов | `completeStep()` вызывал `pipelineCurrentStep.set(step+1)` | Убрали auto-advance |
| Шрифты нечитаемы в light/fun | Hardcoded rgba(148,...) для dark theme | Массовая замена на var(--text-muted/--text-secondary) |
| `<select>` обрезается | WebView2 не рендерит нативный dropdown за overflow | Кастомный dropdown с position:fixed |
| "TRPs конкуренты" → media | "trp" в MEDIA перебивает "конкурент" в CONTROL | Приоритетное правило: competitor check ДО pattern counting |

## Full Session Notes

Сессия длилась ~3 часа. Антон тестировал Econometrica v1.0.7 в dev-режиме, отправлял скриншоты, давал обратную связь по UX. Каждый баг фиксился на лету через hot-reload (фронтенд) или рестарт (Python sidecar).

Ключевой инсайт: валидация данных — это не просто "проверка", а **интерактивная подготовка данных** для моделирования. Пользователь должен видеть проблемы, получать конкретные рекомендации, и применять их одним кликом. Инсайты должны пересчитываться реактивно при каждом изменении.

Терминология ролей утверждена на основе маркетинговой экономики: цены и промо — управляемые факторы (часть Marketing Mix), SOM/SOV — неуправляемые (зависят от конкурентов).
