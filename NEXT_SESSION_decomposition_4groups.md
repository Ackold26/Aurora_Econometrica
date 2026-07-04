# Декомпозиция 4-групп + сезонность помесячно — промт следующей сессии

> Скопируй в начало новой сессии (cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`,
> ветка `feat/econ-e1-backtest`, запушена @cc1916e+). Самодостаточный: контекст,
> решения Антона, точные строки кода, план, инварианты.
> ⚠️ Первым делом — 60-сек recon «что сдвинулось» (git log/status): промт = снимок
> прошлого, параллельная сессия могла продвинуть работу.

## 🎯 Задача сессии

Реализовать **отображение декомпозиции продаж в 4 группы верхнего уровня с
поэтапным раскрытием** и **помесячной сезонностью в % к базе** — по структуре,
согласованной с Антоном 2026-07-04 (все развилки закрыты, ничего не переспрашивать):

```
Уровень 1 (4 полосы):   БАЗА · МЕДИА · ВНЕШНИЕ ФАКТОРЫ · КОНКУРЕНТЫ
Уровень 2 (drill-down):
  БАЗА       → Базовая линия (intercept+тренд) + Сезонность (±% к базе, ПОМЕСЯЧНО) + Праздники
  МЕДИА      → каждый носитель по-отдельности (incremental → отсюда ROI)
  ВНЕШНИЕ    → Цена + Дистрибуция + Погода + Макро + Категория
  КОНКУРЕНТЫ → signed_competitor факторы (± двунаправленно — 4-я полоса, решение Антона)
```

**Решения Антона (2026-07-04, зафиксированы):**
1. Сезонность показывать **как % к базе** (мультипликативная подача; модель внутри аддитивна).
2. Базу **раскрывать на под-компоненты** (drill-down).
3. Фурье + категория — **слоями**, не альтернатива: Фурье = дефолт (0 затрат, всегда есть),
   категория = усиление, когда клиент грузит DSM/IQVIA.
4. Конкуренты — **отдельная 4-я полоса верхнего уровня** (не внутри «Внешних»).

**Методологическая атрибуция (RAG-библиотека, для ADR и текстов):**
- Chan & Perry 2017 §4.2.2 — сезонность = selection bias, пример cold medicine (= наш Kagocel);
  MMM обязаны контролировать сезонность прокси спроса.
- Jin et al. 2017 — аддитивная декомпозиция y = base + Σ media (incremental → ROI).
- Wang & Jin §5.2 — конкуренты = отдельные control variables (не база, не медиа), знак signed.
- Gelman, Bayesian Workflow гл.27 + Brodersen 2015 (BSTS) — аддитивное разложение на отдельно
  отображаемые компоненты; сезонность в мультипликативной подаче.

## 📦 Контекст: что УЖЕ сделано (не переоткрывать)

**Автосезонность А — полностью реализована и доказана** (коммиты e7a1d5b→cc1916e на origin):
- `sidecar/econometrica/utils/fourier_seasonality.py` — Фурье-гармоники (Prophet §3.2):
  `generate_fourier_terms` (sin/cos по t-индексу, детерминизм), `decide_n_harmonics`
  (K=min(4,P//4), Nyquist-cap), `should_inject_seasonality` — гейт INV-50: ≥2 полных цикла
  + **n-зависимый порог значимости Bartlett `max(0.2, 1.96/√n)`** (red-team фикс #1: без
  него ложный инжект на шуме n=26).
- Инжект в `modeler.py` **ДО валидации control_columns** (red-team фикс #2: backtest-окна
  падали «отсутствующие season_fourier_*» — Фурье сохраняются в config.control_columns,
  а окно читает сырой файл; инжект перенесён перед валидацией + синхро
  `control_cols = [c for c if not fourier_prefix or c in df]`). Мастер-флаг
  `use_seasonality` (default True). Persist `model_data['fourier_seasonality']`
  {period, n_harmonics, columns, granularity, autocorr}; persistence.py setdefault;
  decomposer re-inject по t-индексу (после holiday-блока).
- **Доказательства** (MMX 43 мес, годовая autocorr 0.63; зонды в `tmp/`):
  · MAPE 12.55% → 10.2% (backtest, `tmp/probe_seasonality_backtest.py`);
  · **ROI-честность: медиа-вклад 88М → 62М (−30%), Performance −69%** — без сезонных
    контролей модель приписывала сезонную волну рекламе. Это главный аргумент фичи.
  · validated на MMX НЕ достигнут (наивный сезонный труднопобедим на регулярной месячной
    сезонности + шум малых окон 10.2↔14.0 между прогонами) — честно, не скрывать.
- Тесты: `tools/test_fourier_seasonality.py` 22 + `tools/test_fourier_integration.py` 5
  (вкл. backtest-регресс) + связанные 163 (rolling_backtest/decomposer_invariants/edge/
  server_backtest) + 25 (pptx_backtest/persistence_phase2) — ВСЕ зелёные.

**Фаза Б — частично начата** (коммит 5e66e81): `engines/validator.py` detect_column_role —
category-override: «продажи категории/рынка» (ОБЪЁМ) → control 0.85, приоритет над KPI,
после derived (доля рынка/SOM → unused, endogenous). Тесты validator 40/40.

**Recon отображения СДЕЛАН — инфраструктура ГОТОВА, стройка не нужна:**
- `decomposer.py::build_decomposition_series` (стр.~322) — канонический SSOT серий
  timeline-декомпозиции для UI (ChannelTimeline) и ВСЕХ отчётов (HTML/PPTX/XLSX). Строит
  полосы `{name, role∈{baseline,media,factor}, type, group, side, data[] помесячно}` с
  **честным тождеством**: `baseline_reduced + Σ(вынесенные факторы) + Σ(медиа) == total`.
- `_BREAKOUT_TYPES` (стр.~310) = {signed_competitor, signed_price, signed_weather,
  signed_macro, holiday}; `_FACTOR_GROUP_LABELS` (стр.~313): competitor→«Конкуренты»,
  price→«Цена», weather→«Погода», macro→«Макро-факторы», holiday→«Праздники».
- `signed_factor_contributions` формируется в decompose (стр.~880-920): цикл по control_cols,
  `classify_column(col)` → `factor_type_map` (стр.~899) → per-factor {value, pct, type,
  beta_mean, per_period[]}. **GAP: season_fourier_* колонки падают в 'positive_control'
  → остаются В BASELINE, не выносятся полосой.**

## 📋 Задачи (приоритет сверху)

### Т1. Backend-ядро: Фурье → видимый фактор «Сезонность» (главное)
1. `utils/column_detection.py::classify_column`: колонки `season_fourier_*` → новый kind
   `'seasonality'` (проверить регексы-паттерны файла; сейчас падают в unknown/control).
2. `decomposer.py` цикл ~894 + `factor_type_map` ~899: kind 'seasonality' → factor_type
   'seasonality'. **АГРЕГАЦИЯ: 2K колонок sin/cos (обычно 6) объединить в ОДИН фактор
   «Сезонность»** — суммировать per_period поэлементно, beta_mean не осмыслен для суммы
   (можно опустить/None), pct от Σ. Не 6 полос гармоник!
3. `_BREAKOUT_TYPES` += 'seasonality'; `_FACTOR_GROUP_LABELS`['seasonality'] = 'Сезонность'.
4. **Помесячная сезонность в % к базе**: в build_decomposition_series (или рядом) добавить
   для фактора «Сезонность» производный ряд `pct_of_base[t] = 100·data[t]/baseline_reduced[t]`
   (guard деления на ~0). Подача «февраль +60% к базе».
5. Тождество НЕ ломать: вынос сезонности из baseline уже поддержан механикой (вычитание
   любого знака, стр.~364). Гейт: `tools/test_decomposer_invariants.py` + все 163.
6. Тесты на класс: агрегация 2K→1, тождество с сезонностью, % к базе, пустой случай
   (нет Фурье → нет полосы), паритет с fourier_seasonality из pickle.

### Т2. Верхний уровень 4 групп
Маппинг group→top_group: БАЗА{База, Сезонность, Праздники} · МЕДИА{Медиа} ·
ВНЕШНИЕ{Цена, Погода, Макро-факторы, Дистрибуция, Категория} · КОНКУРЕНТЫ{Конкуренты}.
Добавить поле `top_group` в series build_decomposition_series (аддитивно — потребители
старого формата не сломаются) ЛИБО маппинг на стороне потребителей. Рекомендация: поле
в SSOT (один источник истины, INV-50-паттерн «все читатели из одного места»).

### Т3. UI: drill-down 4 полос + сезонная кривая
ChannelTimeline (читает build_decomposition_series) → топ-уровень 4 полосы, клик
раскрывает под-компоненты группы. Помесячная кривая сезонности ±% к базе (тултип/панель).
JS+JSDoc (НЕ TS). Уважать существующий дизайн (Aether Mesh токены). svelte-check 0.

### Т4. Отчёты PPTX/HTML/XLSX
Те же 4 группы + сезонная кривая из SSOT build_decomposition_series (паритет автоматический,
если Т1/Т2 в SSOT). Проверить слайд декомпозиции + HTML-секцию. Канарейка: 0 wireframe,
verify_aurora_pptx_narrative 43/43.

### Т5. Доказательство + гигиена
- Живой зонд на MMX: decompose → 4 группы видны, «Сезонность» ≈ той величине, что дала
  ROI-честность (~26М из 88−62), тождество сходится. Переиспользовать/расширить
  `tmp/probe_seasonality_backtest.py`.
- Мульти-клиент: Kagocel (сезонность НЕ инжектится — ряд короток: полоса «Сезонность»
  корректно отсутствует) + Венарус.
- ADR в `aurora-meta/DECISIONS/` (проверить конвенцию нумерации!): методологическое решение
  структуры декомпозиции с атрибуцией (Chan&Perry/Jin/Wang&Jin/Gelman) + решения Антона.

### Т5б. Сезонная волна в прогнозах (методологическая находка аудита М-1)
predict_scenario трактует контроли как средние (z-score 0, комментарий P1-3) — для
обычных контролей разумно, но Фурье ДЕТЕРМИНИРОВАН: будущие значения известны точно
(t продолжается). Прогнозы на часть цикла (квартал) систематически смещены — в сезон
занижены, вне сезона завышены; на полный цикл (год) волна усредняется (промисы «на Год»
корректны). Затрагивает scenario / промисы E4 / drift_check / goal-seek.
Фикс: в predict_scenario при fourier_seasonality в pickle добавлять
`Σ β_fourier · fourier(t_future) · y_std` к baseline_per_period (t_future = n_obs + i).
Осторожно: прогнозный путь критичный (goal-seek бисекция, CI, экстраполяция) — тест
на класс + сверка промиса-цикла E4 (зонд tmp/probe_e4_live_cycle.py).

### Т6. Хвосты (после ядра, по времени)
- UI-тумблер `use_seasonality` в ConfigPanel (рядом с «Авто-праздники РФ», паттерн
  use_holidays: стор в project-state, buildTrainConfig уже шлёт use_seasonality? — проверить
  train-config.js; stale-детект аналогично use_holidays).
- Строка «Сезонность учтена (период N, ρ=X)» в диагностике/отчёте — честность.
- Фаза Б остаток: prior для category-колонок (positive-leaning shared demand) в
  column_detection; подсказка на Валидации «загрузите продажи категории — модель точнее»
  (для фармы прицельно); доказательство decompose-с/без категории на MMX
  («Продажи в руб. конкуренты» уже есть в файле как competitor; категорию симулировать
  суммой бренд+конкуренты или дождаться реального файла).
- Роутер `NEXT_SESSION_PROMPT.md` обновить по факту.

## 📖 Файлы для чтения (порядок)
1. `AUTONOMOUS_WORK_STATE_SEASONALITY.md` — durable-реестр (ФАКТ, вся история + план).
2. `sidecar/econometrica/engines/decomposer.py` — build_decomposition_series (~322),
   _BREAKOUT_TYPES (~310), signed_factor_contributions (~880-920), factor_type_map (~899).
3. `sidecar/econometrica/utils/fourier_seasonality.py` + `utils/column_detection.py`
   (classify_column) + `engines/validator.py` (category-override, ~100).
4. `src/lib/components/pipeline/` — ChannelTimeline/DecomposeStep (потребители серий).
5. `docs/MATH_REFERENCE.md` §Trust loop — куда дописать сезонность.

## 🔒 Инварианты (соблюдать всегда)
- **decomposer КРИТИЧНЫЙ**: тождество baseline+факторы+медиа==total (energy conservation)
  не ломать; гейт `tools/test_decomposer_invariants.py` + 163 связанных ЗЕЛЁНЫЕ после
  каждого батча. INV-50: числа не «улучшать», править честность.
- Детерминизм и pickle-совместимость (additive поля) не ломать. Фурье по t-индексу.
- JS+JSDoc (НЕ TS). Тесты `-n 4` (xdist в pytest.ini — свои флаги -p не передавать).
- PowerShell-коммиты here-string `@'...'@` БЕЗ прямых двойных кавычек; узкий pathspec;
  чужие untracked не трогать (tokens.generated.css, model_backend.rs, CC-Sessions/).
- Метод: зонд → личная верификация → батч+тест → коммит+пуш (разрешён по ходу) → живой
  gate; реестр = ФАКТ (статусы только после числа-подтверждения); мульти-клиент ≥2
  датасета перед ship narrative-изменений; развилки решать самой (мандат «максимально
  автономно»), стратегические — Антону с рекомендацией.
- Фоновый полный vitest может НЕ вернуть управление (echarts/jsdom držа event loop) —
  писать `>LOG 2>&1; echo EXIT=$? >>LOG` и читать ЛОГ, не ждать возврата; CI=1; таргетить.
- MCMC-тесты: {chains:2, draws:80-300} достаточно для механики; latest.pkl читать
  `load_model_with_compat`, НЕ сырым pickle.load (aurora-model ZIP формат).
- Данные: MMX `D:\Docs\Aurora_Ai\TestData\Econometrica\MMX_2021-2025_source.xlsx`
  (43 мес, KPI «Продажи в руб. бренд», дата «Месяц», медиа = колонки с «Бюджет»);
  Kagocel: Desktop `...Кагоцел РФ+_данные для эконометрики + наши данные 29.08.xlsx` (31 нед).

## ▶️ С чего начать
1. Recon 60 сек: `git log --oneline -8` + `git status` (не продвинула ли параллельная сессия).
2. Прочитать durable-реестр + decomposer (точные строки выше).
3. Начать Т1 (backend-ядро) батчами: classify → агрегация → BREAKOUT → % к базе → тесты →
   зонд MMX → коммит. Затем Т2 → Т3 → Т4 → Т5 → Т6.
Стоп-слово Антона: «стоп/готово по автосезонности» (снять флаг в MEMORY.md).
