# Промт следующей сессии — примеры, живая приёмка, хвосты (2026-07-05)

> Скопируй в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`,
> ветка `feat/econ-e1-backtest` (синхронна с origin @f176f1c на момент написания).
> Самодостаточный: контекст, точные точки кода, команды, фикстуры, метод приёмки.
> ⚠️ ПЕРВЫМ ДЕЛОМ — 60-сек recon: `git log --oneline -6` + `git status` +
> `git rev-list --left-right --count origin/feat/econ-e1-backtest...HEAD`.
> Промт = снимок прошлого; параллельная сессия могла продвинуть работу.
> Мандат автономный (Антон: «веди максимально автономно») — тактику решать самой,
> совместное (визуальные UX-развилки) — беречь для Антона у экрана.

---

## 🎯 Что это за сессия

Хвост большой работы над **автосезонностью + декомпозицией 4 групп (Т3)** и
**пересборкой примеров программы**. Основное ЗАКРЫТО и на origin (см. ниже).
Осталось: (A) совместная живая приёмка с Антоном, (B) три автономно-выполнимые
доработки, (C) комментарии Антона по примерам (он обещал дать после моего аудита —
ещё НЕ дал, спросить в начале сессии).

## ✅ Что уже сделано (НЕ переоткрывать; всё на origin @f176f1c)

**Т3 drill-down + сезонность** (реестр `AUTONOMOUS_WORK_STATE_SEASONALITY.md`):
- `src/lib/decomposition-view.js` — SSOT view-логики (свёртка top_group → 4 полосы,
  `planViewSeries`, `seasonalityPctOfBase`, `seriesIdentity` для universalTransition).
- `ChannelTimeline.svelte` — 4 свёрнутые полосы по умолчанию + chips-раскрытие +
  «Развернуть всё» + клик по полосе + сезонная %-кривая (вторая ось) + морф
  (universalTransition.seriesKey==top_group) + tooltip-строка сезонности.
- Отчёты двухрежимные: PPTX timeline свёрнут в 4 группы; HTML кнопка «Детально ⇄
  Обзор» (`interactive.py::setupTimelineViewToggle`, payload `{overview, detail}`).
- Backend SSOT `decomposer.py::build_decomposition_series` + `collapse_series_to_top_groups`.
- 5 самоаудитов (8+8+3+1+7 находок FIX). Гейты: **vitest 857 · svelte-check 0 ·
  python зелёные · verify PPTX 43/43 · HTML 35/35+a11y 15/15 · fidelity ok**.

**Примеры программы пересобраны** (решения Антона 2026-07-05):
- `tools/synthetic_pilot_data.py` — генератор ПЕРЕПИСАН: каждый канал = ПАРА
  «бюджет ₽ (`*_spend`) + натуральный Media KPI (`*_trp`/`*_grp`/`*_impressions`/
  `*_contacts`/`*_clicks`)». spend = physical × CPP_t (дрейф → corr 0.99, не
  функциональная). Беты решены аналитически из целевых ROI; база из бюджетов +
  доли медиа. Планета истины ДОКАЗАНА живым байес-фитом: R² 0.89–0.97, лестница
  ROI perf 4.45×/RM 4.73× > digital ≈2× > TV, сезонность инжектится, Эфф R² 0.97.
  category_sales (Фаза Б) в fmcg+otc; holiday_newyear удалён (авто-праздники РФ).
- Served: `static/sample-data/synth_*.xlsx` (4 файла, 48 мес); шаблоны справки
  `src-tauri/help-econometrica/template_*.xlsx` = header-only копии (генерятся
  тем же скриптом). SSOT-гейт `tools/test_sample_data_ssot.py` (32) + PAIRED_COLUMNS.
- UI-развязка пар: `src/lib/channel-pairs.js` (`groupChannelColumns`,
  `resolvePairSelection`), `express-validate.js` (пара с ₽-парником не ломает
  happy-path), `ValidateStepV13.svelte` (обе точки confirm применяют развязку +
  `persistPairToggles`), `+page.svelte` (группировка через channel-pairs.js).
- Движок: `validator.py` — KPI_PATTERNS += leads/лид/заявк; MEDIA += contact/
  контакт/apteka/аптек; override `*_indicator`→control; short_period по датам.

---

## 📋 БЛОК A — ЖИВАЯ ПРИЁМКА (совместно с Антоном у экрана, он = быстрейший верификатор)

**Метод:** прочитать `feedback_autonomous_visual_testing_standard` ПЕРЕД dev-прогоном.
Чистую логику — юнитами (сделано), форму echarts/GUI — живым окном. Запуск:
`npm run tauri:dev` (НЕ `tauri dev` — нужен `tauri.dev.conf.json`, мост 127.0.0.1:9223).
Клик — `mcp__tauri__webview_interact` (hover синтетикой НЕ идёт). Скриншот — сверка формы.
Готовый e2e-чек-лист: `docs/e2e/T3_drilldown_driver_session.md`.

### A1. Визуальная форма Т3 (декомпозиция)
- 4 свёрнутые полосы (БАЗА·МЕДИА·ВНЕШНИЕ·КОНКУРЕНТЫ): цвета/наложение читаемы.
- Клик-drill (chips `[data-drill="БАЗА"]` + клик по area) → раскрытие в под-компоненты;
  **морф** universalTransition (агрегат «перетекает», не резкая замена).
- «Развернуть/Свернуть всё» `[data-drill="__all__"]`.
- Сезонная %-кривая на второй (правой) оси: масштаб/читаемость; tooltip-строка «Сезонность к базе +X%».
- Фикстуры БЕЗ MCMC: обученные проекты `mmx_4groups_dw7vr06g` / `Venarus_wj1n_gsq`
  в `%TEMP%` (`C:\Users\ackol\AppData\Local\Temp\`). Или готовый HTML-отчёт:
  `python tmp/gen_t3_html.py` → `tmp/t3_report.html` (открыть через http.server, file:// заблокирован).
- HTML-двухрежимность УЖЕ принята playwright'ом (обзор 2 группы MMX ↔ 8 detail,
  тождество 613 571 910). Программа — осталась.

### A2. Баннер авто-снятой роли на Валидации (В-1, аудит №3)
- Загрузить файл с суммарной колонкой («Бюджет ДО НДС»/«ИТОГО Бюджет») или текстовой.
- **Ожидаемо:** колонка исключена (role=unused) И предупреждение с причиной ВИДНО
  (раньше фильтр `activeWarnings` скрывал warnings исключённых колонок). Статус
  шага — «Готово с предупреждениями (N)», не «Валидация пройдена». Кнопка — «Принять»
  (не «Исключить» — Г-1: action='acknowledge').

### A3. 🔴 Полный путь ПАР в GUI (рекомендация 1 аудита №5 — критично проверить живьём)
Пары впервые нагрузили ADR-015 селектор метрик каналов — юнитами цепь покрыта
(`channel-pairs.test.js` 10, `express-validate.test.js` 10), но клик-путь Валидации
только глазами. Прогнать на `static/sample-data/synth_fmcg_brand.xlsx`:
1. Импорт → «Попробовать на примере» / загрузить файл.
2. **Экспресс-подтверждение** (happy-path, денежный KPI) — должно быть доступно
   (пара spend+TRP НЕ блокирует; физ-половины `*_trp` уходят в disable). Проверить:
   Модель разлочилась, в фит идут только `*_spend` (8 колонок пар → 4 ₽-канала).
3. **Expert-режим** (`/expertMode`): для канала «tv» доступен выбор радио «₽ бюджет |
   📊 контакты (TRP)». Переключить tv → physical → должен потребоваться CPP
   (unit_cost) — **проверить, что CPP-гейт срабатывает** (Д-7 был багом: гейт слеп
   к физ-выбору → ROI-артефакт 12186×; исправлено на `activeModelColumns`).
4. Обучить → декомпозиция: 4 группы, ROI-лестница красивая (perf > digital > TV),
   сезонность полосой. Затем **режим Эффективности** (все каналы physical): пройти,
   доказать что работает (R² 0.97 на фите — должно и в GUI).
- ⚠️ Грабли SvelteKit (из AVT-стандарта): навигация на ТОТ ЖЕ route не перемонтирует
  (onMount стейл) → уйти на `/pipeline` и вернуться; Vite HMR сбрасывает сторы
  (переоткрыть проект); `location.href`=полный reload (сбросит сторы) → клиентская
  навигация `<a>.click()`.

### A4. UX-развилки (продуктовые суждения — решает Антон, НЕ сама)
1. **Сезонность при развороте БАЗЫ:** показывать ₽-полосой (сейчас — и полоса в
   стеке для тождества, и %-кривая поверх) ИЛИ только %-кривой? Финал — на глаз.
2. **Семантика «% к базе»:** сейчас `pct_of_base` от ФИНАЛЬНОЙ базы (после выноса
   факторов). Альтернатива — от чистого intercept+тренд. Решает Антон.
3. **PPTX «слайд раскрытия»:** отдельный слайд детализации НЕ делался (ломает
   verify-контракт «12 slides» ×7 + рендер PPTX глазами автономно недоступен).
   Моя рекомендация — не надо (детализация уже в waterfall+таблице+HTML-toggle).
   Развилка Антону.
- Наблюдение (мелочь): dataZoom timeline сбрасывается при toggle chip drill-down.

---

## 📋 БЛОК B — АВТОНОМНО ВЫПОЛНИМОЕ (не требует Антона; тактику решать самой)

### B1. Справка «Подготовка данных» под пары (рекомендация 2 + хвост примеров)
Файл `src-tauri/help-econometrica/data-preparation.html`. Тексты ДО-ПАРНЫЕ:
- Рекомендует «30 строк» (объём, при котором сезонность не инжектится и short_period
  ругался — теперь short_period чинён по датам, но «30 строк» всё равно мало: нужен
  ≥1 год, лучше ≥2). Привести к ≥24 месяцев / ≥1–2 года.
- Описания колонок примеров устарели (нет упоминания ПАР бюджет+MediaKPI, нет
  category_sales, есть отсылки к удалённому holiday_newyear).
- Ссылки на `template_*.xlsx` (5 шт) корректны — файлы теперь header-only копии
  примеров (паритет колонок держит `test_sample_data_ssot.py::test_template_matches_sample_columns`).
- **Метод:** прочитать текущий HTML, синхронизировать с новой схемой примеров
  (колонки — из `EXPECTED_SCHEMA` в `tools/test_sample_data_ssot.py`), объяснить
  двойную подачу «бюджет ₽ ИЛИ натуральный KPI → две модели». verify после правок:
  справка НЕ в verify_aurora_html (это статичный help, не отчёт) — визуально/грепом.

### B2. Канарейка двух детекторов ролей (рекомендация 3)
Класс Д-1: `utils.column_detection.classify_column` знал `apteka_contacts`, а
`engines.validator.detect_column_role_with_confidence` — нет (разошлись). Тест-сверка:
для КАЖДОГО имени колонки из `EXPECTED_SCHEMA` (tools/test_sample_data_ssot.py) оба
детектора дают СОГЛАСОВАННУЮ роль (media↔monetary/physical, control↔signed_*/control/
category, kpi↔target_*, date↔date). Положить `tools/test_role_detectors_parity.py`.
⚠️ Маппинг kind (classify) ↔ role (validator) не 1:1 — построить таблицу
соответствия (monetary/physical → media; signed_*/control/category → control;
target_* → kpi). Тест ловит будущий рассинхрон детекторов на именах примеров.

### B3. Фаза Б хвост (категорийный контрол — частично начата)
Из реестра `AUTONOMOUS_WORK_STATE_SEASONALITY.md`:
- prior positive-leaning для category-колонок в `utils/column_detection` (сейчас
  category детектится, но prior не настроен на положительную связь спрос↔продажи).
- Подсказка на Валидации «загрузите продажи категории/рынка» (warning
  `suggest_category` УЖЕ есть — проверить формулировку/срабатывание).
- Доказательство: decompose с/без category_sales на synth_fmcg (category теперь
  в примере) → показать что фактор «Категория» выносится полосой и улучшает fit.
- ⚠️ Проверить сначала что УЖЕ сделано (verify_existing_impl) — Фаза Б помечена
  «частично начата», категория уже выносится в декомпозиции (kind='category').

---

## 📋 БЛОК C — ЖДЁМ ОТ АНТОНА
Антон обещал дать СВОИ комментарии по примерам после моего аудита (сессия
прервалась на аудите №5). **В начале сессии спросить его комментарии по примерам** —
возможно, скорректирует состав каналов/отраслей/KPI/значения.

---

## 🔒 Инварианты и метод
- **decomposer КРИТИЧНЫЙ** (тождество baseline+факторы+медиа==total) — гейт
  `tools/test_decomposer_invariants.py` (114) + `test_decomposition_series.py`. Не ломать.
- **Фронт-изменение ⇒ ОБЯЗАТЕЛЬНО vitest** (`CI=1 npx vitest run`) — svelte-check
  контракты не ловит. JS+JSDoc (НЕ TypeScript). svelte-check 0 errors.
- **Генератор примеров → SSOT:** после правок `synthetic_pilot_data.py` перегенерить
  (`python tools/synthetic_pilot_data.py`) И прогнать `test_sample_data_ssot.py`.
  Пары исключаются из анти-коллинеарной проверки через `PAIRED_COLUMNS`.
- **Живой фит-зонд примеров:** `python tmp/probe_samples_fit2.py` (байес-фит 4 файлов,
  R²/ROI/сезонность). Роли-зонд: `validate_data` на 4 файлах (все status ok/warning,
  без unknown).
- **Узкий git pathspec**, чужие untracked не трогать (`tokens.generated.css`,
  `model_backend.rs`, `CC-Sessions/`, `Projects/NEXT_*`, `app.css.bak`, `tmp/`).
  fetch ОТДЕЛЬНО от commit (сетевой сбой рвёт &&-цепочку). Пуш по ходу разрешён.
- **Гейты финала:** vitest ПОЛНЫЙ · svelte-check 0 · python (validator+ssot+
  decomposer_invariants+collapse+two_level+narrative) · verify PPTX/HTML если
  отчёты трогались.

## 📌 Гейты на входе (доказано @f176f1c, база чистая)
vitest **857** · svelte-check **0 errors** · python: validator 20, ssot 32,
decomposer_invariants 114, collapse 7, two_level 4, narrative_adapter, palette 3 ·
verify PPTX 43/43 · HTML 35/35 + a11y 15/15 · fidelity_diff ok. Ветка синхронна с origin.

## ▶️ С чего начать
1. Recon 60 сек (git log/status/ahead-behind).
2. Спросить Антона: (a) его комментарии по примерам (Блок C); (b) готов ли он к
   живой приёмке сейчас (Блок A требует его у экрана) — если нет, идти в Блок B автономно.
3. Автономный порядок Блока B: B2 канарейка детекторов (дёшево, защита) → B1 справка →
   B3 Фаза Б (сначала verify_existing_impl). Каждое: правка → тест/зонд → гейты → коммит
   узким pathspec → fetch behind=0 → push → обновить реестр.
4. Блок A — когда Антон у экрана; UX-развилки A4 решает он.
5. В конце — самоаудит своей работы (по паттерну 5 кругов сессии) + обновить
   `AUTONOMOUS_WORK_STATE_SEASONALITY.md`. Снять флаг автосезонности только по
   слову Антона «стоп/готово».
