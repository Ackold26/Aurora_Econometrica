# Промт следующей сессии — Econometrica: живая приёмка + рекомендации + Блок C (2026-07-05)

> Скопируй в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`,
> ветка `feat/econ-e1-backtest` (на момент написания синхронна с origin @`f744638`).
> Самодостаточный: контекст, точные точки кода, команды, метод приёмки, открытые вопросы.
> ⚠️ ПЕРВЫМ ДЕЛОМ — 60-сек recon: `git log --oneline -6` + `git status -sb` +
> `git rev-list --left-right --count origin/feat/econ-e1-backtest...HEAD`.
> Промт = снимок; параллельная сессия могла продвинуть работу.
> Мандат автономный (Антон, подтверждён многократно): тактику решать самой,
> визуальные UX-развилки (A4) и состав примеров (Блок C) — беречь для Антона у экрана.
> Этот файл замещает устаревший `NEXT_SESSION_examples_live_and_tails.md` (Блок B выполнен).

---

## 🎯 Где мы

Большая многоволновая сессия по Econometrica (примеры-пары + Т3 + автосезонность)
ЗАКРЫТА и на origin. Прошло 4 круга аудита по запросам Антона. Осталось:
(A) совместная живая приёмка у экрана, (C) комментарии Антона по составу примеров,
+ 2 рекомендации на его решение и пара «на будущее».

## ✅ Что сделано этой сессией (НЕ переоткрывать; всё на origin, ветка feat/econ-e1-backtest)

Хронология коммитов (свежие внизу — от 35e5851 к f744638):
- **Блок B автономки:** B2 канарейка паритета детекторов ролей
  (`tools/test_role_detectors_parity.py`), B1 справка `data-preparation.html` под
  парную схему примеров, B3 breakout-тест полосы «Категория» Фазы Б
  (`tools/test_decomposition_category_band.py`; Фаза Б УЖЕ была готова @7cc4212).
- **Аудит B (самоаудит + по запросу Антона):** fix псевдоточных чисел Ratio в
  справке (сверены с экраном программы: 11 перем./4.4, realestate 10/4.8);
  реальные значения превью-ячеек (флайтинг-месяцы); честность про heatmap-подсветку
  пар; `test_priors_calibration.py` МИГРИРОВАН под пересобранный генератор (9 red→11 green).
- **5 рекомендаций аудита (Антон утвердил):**
  1. **Календарь праздников v2.1** (`holiday_calendar_ru.py`): окно = период
     покупательской активности, значение дамми = ДОЛЯ дней периода строки в окне
     (`mode='fraction'`, честно на месячных — раньше 6/12 праздников вечно-нулевые
     от точечной даты конца месяца); дедуп имён; миграция старых моделей через
     `mode='binary_point'` + `holiday_dummies_mode` в pickle.
  2. **Календарь v2.2 — классы окон** (`window_kind`): `preparation` (праздники —
     активность ДО события: НГ-закупки/8мар/23фев/14фев/back-to-school),
     `sale_period` (распродажи — активность ОТ старта: ЧП 14 дн / Cyber Monday 7 дн /
     НГ-распродажи; узкие v2.0-окна живут в `date_range_v20` для binary_point),
     `calendar_period` (майские/госвыходные/каникулы).
  3. **Бейдж пар на карте корреляций** (`CorrelationHeatmap.svelte` +
     `channel-pairs.js::declaredPairKeys/isDeclaredPair`): пары «бюджет+метрика»
     не пугают «Мультиколлинеарностью», а помечены «ожидаемо».
  4. **Ночной гейт** (`tools/nightly_full_gate.ps1`): трип-проволока «exit=0 без
     строки-сводки прогона → FAILED» (урок A-8: exit-код пайпа маскировал 9 failed).
  5. **Гейт ссылок справки** (`tools/test_help_links.py`): якоря + локальные файлы.
- **Аудит-3:** пары в инсайт-слое (`insights-rules.js::validateInsights`) —
  доехало до второго UI-слоя (был противоречащий warning).
- **Пост-аудит (дедуп углублён + канарейка + шире insights):** whitelist алиасов
  событий БЕЗ префикса `holiday_` + гейт длины; 2 рассинхрона детекторов
  исправлены (GMV, русское «Период» знал только classify); прямой юнит статуса
  `validateInsights`.
- **Аудит-4 (🔴🔴 главная находка):** мой же дедуп СОЗДАВАЛ полную потерю контроля —
  клиентская `black_friday` без префикса падала в unknown→unused у ОБОИХ детекторов,
  а дедуп гасил авто-инжект → событие без контроля (OVB молча). FIX: SSOT-предикат
  `is_holiday_like_name` в оба детектора (classify→'holiday', validator→'control'),
  цепочка доезда до полосы «Праздники». Д1: алиас 'валентин' ловил имя человека → сужен.

**Гейты на выходе (живой прогон `nightly_full_gate.ps1`, 2026-07-05):**
python (tools/) **2221 passed · 0 failed** · vitest **875** · svelte-check **0 errors**.
Полный python с sidecar/tests/ был **2429 passed** в отдельном прогоне.

---

## 📋 БЛОК A — ЖИВАЯ ПРИЁМКА (совместно с Антоном у экрана; он = быстрейший верификатор)

**Метод:** прочитать `feedback_autonomous_visual_testing_standard` ПЕРЕД dev-прогоном.
Чистую логику — юнитами (сделано), форму echarts/GUI — живым окном. Запуск:
`npm run tauri:dev` (НЕ `tauri dev` — нужен `tauri.dev.conf.json`, мост 127.0.0.1:9223,
`window.__TAURI__`). Клик — `mcp__tauri__webview_interact` (hover синтетикой НЕ идёт).
⚠️ SvelteKit-грабли: навигация на ТОТ ЖЕ route не перемонтирует (onMount стейл) →
уйти на `/pipeline` и вернуться; Vite HMR сбрасывает сторы; `location.href`=full reload.

### A1. 🔴 Полный путь ПАР в GUI (веди палец по всей цепочке доезда — урок сессии)
На `static/sample-data/synth_fmcg_brand.xlsx`. Юниты покрыты (channel-pairs 10 + новые,
express-validate 10), но клик-путь только глазами. Цепочка доезда — на КАЖДОМ звене
проверять ФАКТ, не наличие кода:
`выбор метрики канала → perChannelInput per-колонке → modelChannelEnabled →
project.model_channel_enabled на диске → media_columns в train-config → каналы в pickle`.
1. Импорт → «Попробовать на примере» / загрузить файл.
2. **Экспресс-подтверждение** (happy-path, денежный KPI): пара spend+TRP НЕ блокирует;
   физ-половины `*_trp` уходят в disable. Проверить: в фит идут 4 `*_spend` (не 8 колонок).
3. **Expert-режим** (`/expertMode`): для «tv» радио «₽ бюджет | 📊 контакты (TRP)».
   Переключить tv→physical → должен потребоваться CPP → **проверить, что CPP-гейт
   срабатывает** (Д-7 был багом: гейт слеп к физ-выбору; исправлено на `activeModelColumns`).
4. Обучить → декомпозиция 4 группы, ROI-лестница (perf>digital>TV), сезонность полосой.
   Затем **режим Эффективности** (все каналы physical): R² 0.97 на фите — должно и в GUI.

### A2. Форма Т3 (декомпозиция) — визуальная
- 4 свёрнутые полосы (БАЗА·МЕДИА·ВНЕШНИЕ·КОНКУРЕНТЫ): цвета/наложение читаемы.
- Клик-drill (chips `[data-drill="БАЗА"]` + клик по area) → раскрытие + **морф**
  universalTransition (агрегат «перетекает», не резкая замена). «Развернуть всё»
  `[data-drill="__all__"]`. Сезонная %-кривая на второй (правой) оси.
- Фикстуры БЕЗ MCMC: обученные проекты `mmx_4groups_dw7vr06g`/`Venarus_wj1n_gsq` в
  `%TEMP%` (`C:\Users\ackol\AppData\Local\Temp\`). Или `python tmp/gen_t3_html.py` →
  `tmp/t3_report.html` (открыть через http.server, file:// заблокирован).

### A3. 🆕 Полоса «Праздники» на МЕСЯЧНОМ фите — теперь содержательная
После календаря v2.1/v2.2 месячная модель получает ненулевые праздники (fraction-доли).
⚠️ Старые pkl (mmx/Venarus в %TEMP%) обучены ДО календаря → у них
`holiday_dummies_mode` отсутствует → decomposer использует `binary_point` (старые
узкие окна). Чтобы увидеть НОВЫЕ fraction-праздники — нужен СВЕЖИЙ фит на месячных
данных примера (обучить synth_fmcg заново). Проверить: полоса «Праздники» под БАЗА
непустая, декабрь/ноябрь несут вклад (НГ-закупки, ЧП-распродажа).

### A4. 🆕 Бейдж пар на карте корреляций + инсайтах
На fmcg-примере: 4 пары `*_spend`↔`*_trp` с r≈0.99 НЕ красятся danger; в списке
зелёный бейдж «Пара канала — ожидаемо: в модель уйдёт одна колонка»; заголовок
разделяет реальные пары риска и пары каналов. InsightsPanel — info-строка, не warning.

### A5. 🆕 Клиентская колонка события без префикса
Загрузить файл с колонкой типа `black_friday` / `8_марта` (без `holiday_`) → должна
получить роль **control** (не unused), пойти полосой «Праздники», а авто-дубль
`holiday_black_friday` — погаситься (нет двойного учёта).

### A6. Баннер авто-снятой роли на Валидации (В-1)
Файл с суммарной колонкой («Бюджет ДО НДС»/«ИТОГО Бюджет») → колонка исключена
(role=unused) И предупреждение ВИДНО. Статус «Готово с предупреждениями (N)»,
кнопка «Принять» (не «Исключить» — action='acknowledge').

### A4-РАЗВИЛКИ (продуктовые суждения — решает Антон, НЕ сама; PPTX-слайд Антон решил НЕ делать)
1. **Сезонность при развороте БАЗЫ:** показывать ₽-полосой (сейчас — и полоса в
   стеке для тождества, и %-кривая поверх) ИЛИ только %-кривой? Финал — на глаз.
2. **Семантика «% к базе»:** сейчас от ФИНАЛЬНОЙ базы (после выноса факторов).
   Альтернатива — от чистого intercept+тренд. Решает Антон.

---

## 📋 БЛОК C — ЖДЁМ ОТ АНТОНА
Антон обещал СВОИ комментарии по составу примеров (каналы/отрасли/KPI/значения) —
«дам позднее». В начале сессии спросить. Генератор: `tools/synthetic_pilot_data.py`
(GROUND_TRUTH_* dicts: ROI-таргеты, decay/alpha, controls, сезонность). После правок
GROUND_TRUTH — перегенерить (`python tools/synthetic_pilot_data.py`) И прогнать
`tools/test_sample_data_ssot.py` + `tools/test_priors_calibration.py`.

---

## 📋 ОТКРЫТЫЕ РЕКОМЕНДАЦИИ (на решение Антона — обсудить вместе)

### R1. ✅ ВЫПОЛНЕН (2026-07-05, Антон выбрал «R1 автономно»; коммит `12883d3` на origin)
Метод корпус-оракула: зонд 26+19 имён через живые функции ДО правки. Фиксы:
`_sep_pattern` внутренний `_` → `[_\s\-]` (classify, чокпоинт); validator —
тройки underscore/пробел/дефис (fx/exchange/usd_rub/eur_rub/курс_* + signup/
app-install). Латентный баг убит: «usd rub» шёл в media с ROI (голый `usd`).
Канарейка 170, мутации доказаны, гейт python 2272 (+51)/vitest 875/svelte 0.
Детали → `AUTONOMOUS_WORK_STATE_SEASONALITY.md` (секция R1). Ниже — исходная
постановка (историческая):

### ~~R1. 🟠 Underscore-рефактор паттернов детекторов~~ (закрыт выше)
**Проблема:** паттерны ОБОИХ детекторов зашивают `_` внутри многословных токенов
(`индекс_цен`, `курс_доллара`, `price_index`, `usd_rub`, `sales_rub`…). Клиентская
форма с ПРОБЕЛОМ («Индекс цен», «Курс доллара») → `unknown` у обоих. Частый кейс —
реальные файлы сплошь с пробелами в названиях колонок.
- `classify_column` (`utils/column_detection.py`): SIGNED_PRICE_PATTERNS
  (`индекс_цен`, `price_index`, `avg_price`…), SIGNED_MACRO_PATTERNS
  (`курс_(рубля|доллара|евро)`, `usd_rub`, `exchange_rate`…), TARGET_* (`sales_rub`,
  `продаж..._руб`). Использует `_sep_pattern` — но внутри токена underscore буквальный.
- `detect_column_role` (`engines/validator.py`): CONTROL_PATTERNS — простой substring
  `p in lower`, тоже underscore-буквальный.
**Фикс:** заменить внутренние `_` многословных токенов на separator-class `[_\s\-]`
(classify regex); в validator — добавить пробельные варианты или нормализовать имя
перед substring. ⚠️ ОБЯЗАТЕЛЬНО с анти-ложным корпусом + мутацией (см. метод дедупа).
Мой корпус для reuse — `tools/test_client_names_detector_canary.py::CLIENT_CORPUS` +
`TestUnderscoreMacroPositive`. Средний объём, средний риск (широкий проход по паттернам).

### R2. 🟡 ё→е нормализация в `normalize_holiday_name`
Сейчас держу обе формы алиасов руками (`чёрная`/`черная`, `деньвлюблённых`/`деньвлюбленных`).
Нормализация `ё→е` в `normalize_holiday_name` (`holiday_calendar_ru.py`) сняла бы дубли.
Мелочь — сделать при следующем касании календаря.

### R3. Рекомендации «на будущее» (низкий приоритет)
- **insights-rules.js шире:** покрыт только `validateInsights`. Ещё 10 функций без
  прямых юнитов (`modelInsights`, `decomposeInsights`, `optimizeInsights`,
  `reportInsights`, `modelPreTrainingInsights`, `validateKpiInsights`…). 2000+ строк
  клиент-facing правил — регресс текста не ловится.
- **Канарейка детекторов шире:** корпус клиентских имён можно наращивать (отраслевые
  синонимы, англо-русские смеси, единицы в скобках).

---

## 🔒 Инварианты и метод (жёсткие правила сессии)
- **Фронт-изменение ⇒ ОБЯЗАТЕЛЬНО vitest** (`CI=1 npx vitest run`) — svelte-check
  контракты НЕ ловит. JS+JSDoc (НЕ TypeScript). svelte-check 0 errors.
- **Дедуп/фильтрация сущностей:** ложное срабатывание ОПАСНЕЕ пропущенного (потеря
  контроля → OVB молча) → whitelist специфичных ядер + гейт длины + анти-ложный
  корпус + доказать мутацией (длинная ложная подстрока → тест краснеет). См.
  `feedback_false_suppression_worse_than_missed_asymmetric_risk`.
- **Веди палец по цепочке доезда:** юнит зелёный ≠ фича работает. Звено ДО логики
  может делать корректную логику ВРЕДНОЙ (Д2: дедуп корректен, но роль колонки
  делала его потерей контроля). Проверять факт на каждом звене.
- **Гейт-число — из ФАКТИЧЕСКОГО прогона** ЭТОЙ итерации (не экстраполяция). Вердикт
  гейта — по СВОДКЕ pytest, не по exit-коду пайпа (`| tail` маскирует failed).
- **Расширяя классификатор** — прогнать РАНЕЕ ИСКЛЮЧЁННЫЕ ловушки (derived/эндогенные);
  защита в одном пути (авто) ≠ защита в другом (ручной прямой вызов classify).
- **Узкий git pathspec**, чужие untracked НЕ трогать: `src/tokens.generated.css`,
  `src-tauri/src/commands/model_backend.rs`, `CC-Sessions/`, `Projects/NEXT_*`,
  `src/app.css.bak*`, `tmp/`. fetch ОТДЕЛЬНО от commit (сетевой сбой рвёт &&). Пуш по ходу ок.
- **Календарь двойного режима:** decomposer re-inject воспроизводит режим train из
  pickle `normalization.holiday_dummies_mode` (старые модели без ключа → binary_point;
  их β согласованы с бинарными X). НЕ ломать — тест `test_decomposer_holiday_reinject`.
- **decomposer КРИТИЧНЫЙ** (тождество baseline+факторы+медиа==total) — гейт
  `tools/test_decomposer_invariants.py` (114). Не ломать.
- **is_holiday_like_name — SSOT** для событийных дамми: оба детектора зовут его;
  правишь алиасы `_HOLIDAY_ALIASES` — держи анти-ложную защиту (без голых коротких слов).

## 📌 Ключевые файлы (быстрый возврат)
| Что | Файл |
|---|---|
| Календарь: окна/window_kind/алиасы/is_holiday_like_name/generate_holiday_dummies(mode) | `sidecar/econometrica/utils/holiday_calendar_ru.py` |
| classify_column (kind, ветка is_holiday_like_name) | `sidecar/econometrica/utils/column_detection.py` |
| detect_column_role (роль UI, is_holiday_like_name, GMV/период патчи) | `sidecar/econometrica/engines/validator.py` |
| holiday инжект train (fraction, дедуп, mode в pickle), prior kind holiday | `sidecar/econometrica/engines/modeler.py` (~304, ~560, ~1477) |
| holiday re-inject decompose (mode из pickle), полоса «Категория»/breakout | `sidecar/econometrica/engines/decomposer.py` (~310 _BREAKOUT_TYPES, ~590 reinject) |
| Пары: declaredPairKeys/isDeclaredPair, resolvePairSelection | `src/lib/channel-pairs.js` |
| Бейдж пар на heatmap | `src/lib/components/pipeline/CorrelationHeatmap.svelte` |
| Инсайты: validateInsights (пары в корреляциях, статус) | `src/lib/insights-rules.js` (~386, ~648) |
| Справка под пары | `src-tauri/help-econometrica/data-preparation.html` |
| Генератор примеров (GROUND_TRUTH) | `tools/synthetic_pilot_data.py` |
| Ночной гейт с трип-проволокой | `tools/nightly_full_gate.ps1` |
| Реестр durable (полная история) | `AUTONOMOUS_WORK_STATE_SEASONALITY.md` |

## 📌 Гейты на входе (доказано @f744638, база чистая, ветка синхронна origin)
python nightly (tools/) **2221 passed · 0 failed** · vitest **875** · svelte-check
**0 errors**. Полный python (tools/ + sidecar/tests/) **2429 passed**. Прогон:
`powershell -File tools/nightly_full_gate.ps1` (python+vitest+svelte-check в одном,
трип-проволока на аномалии).

## ▶️ С чего начать
1. Recon 60 сек (git log/status/ahead-behind).
2. Спросить Антона: (a) готов ли к живой приёмке сейчас (Блок A требует его у экрана);
   (b) комментарии по примерам (Блок C); (c) решение по R1 (underscore-рефактор) —
   брать задачей или отложить.
3. Если Антон не у экрана / без ответов — автономно: R1 (underscore-рефактор с
   анти-ложным корпусом) ИЛИ R3 (insights шире) — тактику решать самой, каждое:
   правка → тест/зонд/мутация → гейты → коммит узким pathspec → fetch behind=0 → push.
4. Блок A — когда Антон у экрана; UX-развилки A4 решает он.
5. В конце — самоаудит своей работы (гипотезы классов → зонды, новизна слоя даёт
   урожай) + обновить `AUTONOMOUS_WORK_STATE_SEASONALITY.md`.
