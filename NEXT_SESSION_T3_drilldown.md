# Т3 — UI drill-down 4 групп + сезонная %-кривая (промт следующей сессии)

> Скопируй в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`,
> ветка `feat/econ-e1-backtest` (запушена @121fba0+). Самодостаточный: контекст,
> решения Антона, точные точки кода, открытые UX-развилки, метод live-приёмки, план.
> ⚠️ Первым делом — 60-сек recon (`git log --oneline -8` + `git status`): промт =
> снимок прошлого, параллельная сессия могла продвинуть работу.
> 🔴 ЭТО ЕДИНСТВЕННАЯ ОСТАВШАЯСЯ ЗАДАЧА автосезонности/декомпозиции — весь backend,
> надёжность, канон, отчёты, тумблер и самоаудит ЗАКРЫТЫ (11/12 + Фаза Б, на origin).

## 🎯 Задача сессии

Реализовать **двухуровневое отображение декомпозиции** в `ChannelTimeline.svelte`:
**4 верхние полосы с клик-раскрытием** под-компонентов + **помесячная сезонная
кривая ±% к базе**. Backend (SSOT) ГОТОВ и доказан — работа чисто фронтовая + живая
визуальная приёмка echarts-взаимодействия.

```
Уровень 1 (4 полосы):   БАЗА · МЕДИА · ВНЕШНИЕ ФАКТОРЫ · КОНКУРЕНТЫ
Уровень 2 (клик-раскрытие):
  БАЗА       → Базовая линия + Сезонность (±% к базе, ПОМЕСЯЧНО) + Праздники
  МЕДИА      → каждый носитель по-отдельности (incremental → ROI)
  ВНЕШНИЕ    → Цена + Дистрибуция + Погода + Макро + Категория
  КОНКУРЕНТЫ → signed_competitor факторы (± двунаправленно)
```

**Решения Антона (2026-07-04, зафиксированы, НЕ переспрашивать):**
1. Сезонность — **как % к базе** (мультипликативная подача; модель внутри аддитивна).
2. Базу **раскрывать** на под-компоненты (drill-down).
3. Фурье + категория — **слоями** (Фурье дефолт, категория усиление при DSM/IQVIA).
4. Конкуренты — **отдельная 4-я полоса** верхнего уровня.

## 📦 Контекст: что УЖЕ сделано (НЕ переоткрывать) — весь backend + пункты 1,3

**SSOT декомпозиции готов** (`sidecar/econometrica/engines/decomposer.py`):
- `build_decomposition_series` (стр.~322) строит серии с полями `{name, role∈
  {baseline,media,factor}, type, group, top_group, side, data[]}` + честное тождество
  `baseline_reduced + Σфакторы + Σмедиа == total` (зонд MMX: 0.0000%).
- `top_group ∈ {БАЗА, МЕДИА, ВНЕШНИЕ ФАКТОРЫ, КОНКУРЕНТЫ}` — уже на КАЖДОЙ серии
  (`_TOP_GROUP_MAP` стр.~329). Полоса «Сезонность» несёт `pct_of_base[]` (помесячно
  % к финальной базе, guard на вырожденную базу <1% среднего — аудит F-4).
- `_BREAKOUT_TYPES` включает seasonality+category; `_FACTOR_GROUP_LABELS`:
  seasonality→«Сезонность», category→«Категория».
- Фурье-гармоники агрегируются в ОДИН фактор «Сезонность» (ключ 'Сезонность').

**Фронт частично готов** (`src/lib/components/pipeline/ChannelTimeline.svelte`):
- Палитра `FACTOR_COLORS` + `FACTOR_LABELS`: seasonality=violet #8b5cf6 «Сезонность»,
  category=emerald #10b981 «Категория» (зеркалит PPTX charts._FACTOR_RGB + HTML
  interactive.FACTOR_COLORS).
- **✅ tooltip уже группирует по 4 верхним группам из SSOT** (пункт 3, коммит 121fba0):
  `seriesTopGroup` (name→top_group, заполняется в `buildCanonicalOption` стр.~325 из
  `s.top_group`; legacy → `fallbackTopGroup` по имени), formatter группирует по
  `TOP_GROUP_ORDER` с `TOP_GROUP_DISPLAY`. Праздники+Сезонность под «База», Категория
  под «Внешние факторы». Зонд логики зелёный.
- `buildCanonicalOption` (стр.~325) строит stacked-area: baseline (blue) + media +
  вынесенные factor-полосы (positive/negative стеки). `option = $derived.by` (стр.~398)
  предпочитает canonical `decompositionSeries`, иначе legacy `signedFactors`-путь.

**Прочее готово и на origin:** У1 сезонность в прогнозах (scenario), У2 канарейка
схем, У3 гейт ролей, У4 детектор, У5 ночной gate (теперь python+vitest+svelte, пункт 1),
Т4 палитра отчётов, Т5 ADR-033+мульти-клиент, Т6 тумблер use_seasonality, Фаза Б
категория, самоаудит (4 находки F-1..4 исправлены).

## 📋 Что ОСТАЛОСЬ реализовать (Т3)

### Т3.1 — Клик-раскрытие 4 верхних групп (главное)
Сейчас `buildCanonicalOption` рисует ВСЕ под-компоненты сразу (baseline + каждый
медиа + каждый фактор отдельными area-полосами). Нужен **свёрнутый режим по
умолчанию** (4 агрегированные полосы по top_group) + **клик разворачивает** группу
в под-компоненты.
- Агрегация: суммировать `data[]` серий одной `top_group` поэлементно → 4 полосы.
- Взаимодействие: клик по легенде/полосе/кнопке-переключателю → toggle expand группы.
  `webview_interact` умеет **click** (не hover) — drill-down делать по клику.
- Состояние expand — `$state` (Svelte 5 руны), при клике `chart.setOption`.
- ⚠️ Тождество сохранять: свёрнутая сумма 4 групп == развёрнутая сумма всех полос.

### Т3.2 — Сезонная кривая ±% к базе (pct_of_base)
Полоса «Сезонность» несёт `pct_of_base[]` (SSOT). Показать её **отдельной кривой**
(линия, вторая ось Y в %) — «февраль +60% к базе». По решению Антона это подача
сезонности. Открытая развилка — где (тултип / отдельная мини-панель / вторая ось
на том же графике) — решить на live с Антоном (см. UX-развилки ниже).

### Т3.3 — Пункт 2 (канарейка паритета палитр факторов, СРЕДНИЙ, опционально)
Три зеркальные палитры факторов (PPTX `charts._FACTOR_RGB` · HTML
`interactive.FACTOR_COLORS` · Svelte `FACTOR_COLORS`) синхронизируются руками
(дополняла дважды: сезонность, категория). Автотест-канарейка: множество типов в
каждой палитре ⊇ `decomposer._BREAKOUT_TYPES` (+ positive_control). Класс тот же,
что У2. python-тест, парсит 3 файла (regex по ключам) + сверяет с `_BREAKOUT_TYPES`.

## 🔀 Открытые UX-развилки — решить с Антоном на LIVE (продуктовые суждения)
1. **Знакопеременная сезонность в area-стеке** (мой факт-предупреждение): полоса
   «Сезонность» ± вокруг нуля; в positive-стеке ECharts зимние минусы визуально ломают
   стек. Мой вариант: полосу оставить в БАЗЕ (свёрнутой), а сезонность показать
   ОТДЕЛЬНОЙ %-кривой (ровно подача Антона «% к базе»). Финал — на глаз в живом окне.
2. **Семантика «% к базе»**: сейчас `pct_of_base` от ФИНАЛЬНОЙ базы (после выноса
   конкурентов/праздников, residual внутри). Альтернатива — от чистой intercept+тренд.
   Разница заметна только при больших внешних факторах — подача, решает Антон.
3. **OLS без сезонности** (М-3, низкий): для длинных рядов на OLS Фурье был бы полезен
   (сейчас честно отключён, F-AUD-4). Не блокирует.

## 📖 Точки кода (порядок чтения)
1. `src/lib/components/pipeline/ChannelTimeline.svelte` — ВЕСЬ (buildCanonicalOption
   ~325, buildTooltipOption ~215, option $derived ~398, seriesTopGroup ~63, палитры ~39).
2. `src/lib/components/pipeline/DecomposeStep.svelte` — вызов ChannelTimeline (~536-552,
   props `decompositionSeries` / `signedFactors` / `timeSeries`), ExpandableCard-обёртка.
3. `sidecar/econometrica/engines/decomposer.py::build_decomposition_series` (~322) —
   форма SSOT (top_group, pct_of_base). НЕ менять без нужды (critical, тождество).
4. `src/lib/components/charts/EChartBase.svelte` — обёртка echarts (onInit, option).
5. Зонды данных: `tmp/probe_decompose_4groups.py` (MMX), `tmp/probe_multiclient_decompose.py`
   (Kagocel/Venarus) — дают готовый decompose result с 4 группами для проверки формы.

## 🔬 Метод LIVE-приёмки (AVT-стандарт — прочитать `feedback_autonomous_visual_testing_standard` ПЕРЕД dev-прогоном)
- **Тестировать как программу, не картинку.** Чистую логику (агрегация top_group,
  тождество свёрнутой суммы) — ЮНИТ-ТЕСТАМИ (vitest), НЕ live-hover'ом.
- **ECharts hover/tooltip НЕ триггерится синтетикой** (offsetX/Y=0) — formatter'ы
  доказывать юнит-тестом, не live. Клик (`webview_interact`) — работает, drill-down им.
- **Готовая фикстура вместо прохода pipeline**: НЕ гнать MCMC — есть зонды-проекты
  выше; можно `invoke('econ_decompose',{projectDir})` напрямую на готовом проекте.
- **Dev-режим:** `npm run tauri:dev` (НЕ `tauri dev` — нужен `tauri.dev.conf.json` с
  `withGlobalTauri`, иначе мост `hasTauri:false`). Мост 127.0.0.1:9223.
- **SvelteKit грабли:** навигация на ТОТ ЖЕ route не перемонтирует (onMount стейл) →
  уйти на `/pipeline` и вернуться; `location.href`=полный reload (сбросит сторы) →
  клиентская навигация через `<a>.click()`; Vite HMR сбрасывает сторы (переоткрыть проект).
- **Fullscreen графика = обёртка `ExpandableCard`** (EChartBase единственный потомок).
- **Скриншот (`webview_screenshot`)** — ТОЛЬКО визуальная сверка формы 2-3 экрана.

## 🔒 Инварианты
- decomposer КРИТИЧНЫЙ (тождество baseline+факторы+медиа==total) — гейт
  `tools/test_decomposer_invariants.py` + 163 связанных. Backend НЕ трогать без нужды.
- JS+JSDoc (НЕ TypeScript). Aether Mesh токены. svelte-check 0 errors.
- **🔴 Фронт-изменение ⇒ ОБЯЗАТЕЛЬНО vitest** (урок F-2: svelte-check контракты не
  ловит; golden `build-train-config.test.js` падал только под vitest). `CI=1 npx vitest run`.
- Узкий git pathspec; чужие untracked не трогать (tokens.generated.css, model_backend.rs,
  CC-Sessions/). fetch ОТДЕЛЬНО от commit (урок: сетевой сбой рвёт &&-цепочку, ложное
  «pushed» — [[feedback_network_flap_breaks_fetch_commit_chain]]). Пуш по ходу разрешён.
- Метод: чистая логика → юнит-тест → live-форма скриншотом → находки чинить сразу.
  Автономна на исполнении/тактике; UX-развилки (выше) — с Антоном на живом окне
  (synchronous co-design: он у экрана = быстрейший верификатор).

## ▶️ С чего начать
1. Recon 60 сек: `git log --oneline -8` + `git status` (не продвинулась ли параллель).
2. Прочитать ChannelTimeline.svelte ВЕСЬ + DecomposeStep вызов + build_decomposition_series
   форму (top_group/pct_of_base) + `feedback_autonomous_visual_testing_standard`.
3. Реализовать Т3.1 (свёртка+клик) БАТЧАМИ: агрегация top_group (чистая функция +
   vitest на тождество свёрнутой суммы) → toggle-состояние → echarts setOption → svelte 0.
4. Т3.2 сезонная %-кривая. Т3.3 канарейка палитр (опц.).
5. **Поднять dev (`npm run tauri:dev`), открыть готовый проект-фикстуру, живая
   визуальная приёмка формы (скриншот) + клик-drill-down (`webview_interact`).**
   UX-развилки 1-2 решить с Антоном у экрана.
6. Гейты финала: vitest ПОЛНЫЙ · svelte-check 0 · decomposer_invariants 163 ·
   verify_aurora_pptx/html narrative (если отчёты трогались).
7. Обновить `AUTONOMOUS_WORK_STATE_SEASONALITY.md` (реестр=ФАКТ) + при завершении Т3
   доложить Антону; снять флаг автономки только по его «стоп/готово по автосезонности».

## 📌 Гейты на входе (доказано в прошлой сессии, база чистая)
python tools/ ПОЛНЫЙ **1907 passed** · vitest ПОЛНЫЙ **802** · cargo test 0 ·
svelte-check **0 errors** · verify pptx 43/43 · html 35/35. Ветка синхронна с origin.
