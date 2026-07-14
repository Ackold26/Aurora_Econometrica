# TEST_FINDINGS — Econometrica visual-audit 2026-07-01

**Ветка:** `feat/rag-core-adopt` (dev запущен из текущего рабочего дерева; НЕ tier2).
**Редакция:** облачная (`cloud_advisors`), v2.1.0. Мост `:9223`, sidecar `:7529` healthy.
**Фикстура:** активный `кагоцел-...-на-ммх-2306-26` (обучен: latest.pkl + decomposition + optimization + scenarios).
**Объём:** широкий-тонкий проход входного экрана (главная). Полный проход пайплайна отложен — Антон переориентировал на актуализацию дизайна (нет смысла глубоко аудировать UI, который будем перестраивать).

## Легенда severity
🔴 краш/блокер · 🟠 баг · 🟡 UX · 🔵 достоверность/наблюдение · ⚪ снято/by-design

---

## 🟠 F1 — «Продолжить проект →» не появляется на холодном старте (lifecycle-регрессия)
- **Экран:** главная `/` после перезапуска приложения.
- **Наблюдение (DOM/a11y):** на главной только кнопки «Новый проект» + ссылка «Что такое MMM?». Кнопки «Продолжить проект →» и «Перейти к командам» нет, хотя на диске есть активный обученный проект `...2306-26`.
- **Repro:** запустить приложение с холода → главная → кнопки «Продолжить проект →» нет.
- **Корень (код-пруф):**
  - Кнопка гейтится стором: `src/routes/+page.svelte:339 {#if $activeProject}`.
  - Стор `activeProject` (`project-state.js:21 writable(null)`) ставится **только** в pipeline-компонентах (ImportStep/DecomposeStep/OptimizeStep/…) и `ProjectSelector` — то есть при активной работе в текущей сессии.
  - `+page.svelte onMount` (166) активный проект НЕ гидрирует; в `+layout.svelte` гидрации `activeProject` **нет вообще**.
  - Итог: `active_project.json` (backend, диск) пишется, но на старте фронт его в стор не читает → кнопка мертва на холодном входе.
- **Замысел (verify-hold):** коммит `539e11f` «feat(ux): home hero logo, 3-button nav, project lifecycle» — Primary «Продолжить проект → (when active project exists)». Фича заявлена, но на возвратном сценарии (перезапуск назавтра) не срабатывает.
- **Fix-направление:** на старте (layout onMount или главная) прочитать активный проект из backend (`get_active_project`/`project_list` + active_project.json) и гидрировать `activeProject`/`activeProjectId` в стор — тогда гейт `{#if $activeProject}` отработает. Учесть LOAD-1 (роль-полная гидрация, `resetPipeline` порядок) чтобы не сломать pipeline-сторы.
- **Severity:** 🟠 UX (средний). Не блокер (проект достижим через ProjectSelector), но ключевой возвратный сценарий коммерческого продукта не работает.
- **✅ ИСПРАВЛЕНО (2026-07-02, ветка feat/design-adopt-hybrid-ds):** гидрация активного проекта в `+page.svelte` onMount — `project_get_active` → `project_get` → `activeProject.set`/`activeProjectId.set` (паттерн из ProjectSelector:75-79). Только стор (id+info), pipeline-сторы оставлены `/pipeline` resetPipeline (не задевает LOAD-1). Live-verified: «Продолжить проект →» появляется на холодном старте.

## ⚪ Таймер шапки показывает МСК-часы, не счёт вверх — СНЯТО (by-design на этой ветке)
- Первое наблюдение: таймер `22:46 МСК` = стенные часы, не elapsed от 00:00:00.
- Проверка: на `feat/rag-core-adopt` таймер = `DigitalClock.svelte` (`title="Московское время (МСК)"`) — часы реального времени by-design. SessionTimer (счёт вверх) живёт на ДРУГОЙ ветке `feat/ai-insights-tier2` (коммиты `d711129`/`42e525b`/`ddda116`), сюда не влит.
- **Вывод:** НЕ баг для этой ветки. Ложная тревога снята код-верификацией (Phase 4 п.1). NB: две ветки расходятся в поведении шапки-таймера — при слиянии решить, какая версия канон.

## 🟡 F2 — a11y GlossaryPanel (из лога компиляции vite)
- `GlossaryPanel.svelte:78-79` — div с click-handler без ARIA role / tabindex / keyboard-handler (диалоговая роль без tabindex). Плюс `:18` — `initialTerm` захвачен как начальное значение (возможно, нужен `$derived`).
- Перекликается с backlog'ом из памяти: div-overlay модалки катают focus-trap руками → кандидаты на native `<dialog>`.
- **Severity:** 🟡 UX/a11y, косметика. Не влияет на работу.

---

## Заметки метода
- Аудит вёлся на `feat/rag-core-adopt` — важно: дизайн-трек (SessionTimer/InsightCard-tint/BrandChip) на `feat/ai-insights-tier2`, поведение шапки между ветками расходится.
- Полный пайплайн-аудit (Валидация→Модель→Декомпозиция→Оптимизация→Отчёт) + верификация INV-50 кросс-слой `6bc41ac` в отчётах — отложен до после редизайна.
