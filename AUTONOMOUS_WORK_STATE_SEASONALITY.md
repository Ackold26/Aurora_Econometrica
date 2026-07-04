# Автономка: Автосезонность А→Б (durable-реестр, ФАКТ)

> Реестр отражает ФАКТ (feedback_durable_registry_is_fact_not_plan): ✅ только со
> свершившимся числом-подтверждением, ⏳ — TODO без деталей «как прошло».
> Точка входа при возврате/после компрессии: читать ЭТОТ файл + [[INDEX_econometrica]],
> продолжать БЕЗ переспроса с раздела «СЛЕДУЮЩЕЕ». Развилки решать самой (мандат Антона
> «веди максимально автономно», 2026-07-04).
> 🟢 **САМОДОСТАТОЧНЫЙ ПРОМТ СЛЕД. СЕССИИ = `NEXT_SESSION_decomposition_4groups.md`** —
> декомпозиция 4-групп (Т1-Т6) + **5 УТВЕРЖДЁННЫХ улучшений аудита У1-У5** (Антон принял
> все, 2026-07-04): У1 сезонность в прогнозах · У2 канарейка паритета фронт↔схемы ·
> У3 числовой гейт ролей · У4 детектор длинного периода · У5 ночной gate. Отчёт аудита
> `docs/audits/AUDIT_SESSION_WORK_2026_07_04.md` (6 находок F-AUD-1..6 исправлены).

## Контекст (зачем)
Антон принял (2026-07-04) фичу **автосезонность А→Б** для закрытия боевой грабли
worse_than_naive: на Kagocel/MMX backtest-витрина честно бракует модель, т.к. праздники
РФ (holiday_calendar_ru, уже авто) ловят календарные всплески, но НЕ гладкую сезонную
волну спроса. Решение А — Фурье-компонента (Prophet §3.2 / Robyn), Б — категорийный
контрол. Доказательство = бэктест до/после на Kagocel (worse_than_naive → validated/лучше).
Ветка: `feat/econ-e1-backtest` (та же, что GUI-прогон G-1/G-2/G-4).

## ✅ СДЕЛАНО (с подтверждением)
- **Recon движка:** detect_seasonality (forecast_validation.py:129, возвращает
  {period, autocorr, candidates_tested}|None) УЖЕ есть; seasonality_detected вычисляется
  в modeler.py:1486 и персистится (persistence.py), но НЕ используется как регрессор.
  Праздники РФ авто (modeler.py:304-328, гейт use_holidays). Готовый pymc_marketing.mmm.fourier
  есть в зависимостях (не используем — свой модуль для контроля). Фурье-регрессоров в нашем
  коде НЕТ (grep engines чист).
- **Модуль `sidecar/econometrica/utils/fourier_seasonality.py` СОЗДАН:**
  generate_fourier_terms (n_obs×2K sin/cos по t-индексу, детерминизм, [-1,1]),
  decide_n_harmonics (K=min(4,P//4), Nyquist-cap P//2), should_inject_seasonality
  (гейт INV-50: detected + period≥2 + autocorr≥0.2 + n_obs≥2·period), list_fourier_columns
  (паритет). Префикс колонок `season_fourier_sin_K`/`_cos_K`.
- **Тесты `tools/test_fourier_seasonality.py`: 20/20 passed** (форма, значения, период,
  детерминизм, вырожденные, decide_n_harmonics параметризован, гейт: None/короткие/
  квартальная-на-Kagocel/анти-фаза/невалидный-период/годовая, list паритет).
- **Ключевой факт нормализации:** контроли в modeler нормализуются Z-score
  `(X_control - mean)/std` (modeler.py:457), НЕ делением на mean → Фурье (mean≈0) БЕЗОПАСНЫ.
- **Точка инжекта найдена:** modeler.py после n_obs (381), до X_control (414). y (380),
  n_obs (381), control_cols (208) доступны; X_control (414) подхватит новые control_cols.
- **✅ ИНЖЕКТ В ДВИЖОК ГОТОВ (коммит ниже):** modeler.py (после n_obs, мастер-флаг
  use_seasonality, detect_granularity+detect_seasonality→should_inject→generate_fourier_terms
  →df+control_cols, пересчёт n_params, fourier_seasonality_meta, non-fatal try) + persist
  model_data['fourier_seasonality'] (рядом с seasonality_detected) + persistence.py setdefault
  (backward-compat) + decomposer.py re-inject по t-индексу (не датам, после holiday-блока).
  Синтаксис+импорт чисты.
- **✅ ИНТЕГРАЦИОННЫЕ ТЕСТЫ 4/4** (tools/test_fourier_integration.py): годовая синтетика
  инжектит (period 26/52, columns в pickle через load_model_with_compat), короткий ряд
  не инжектит, decompose-паритет ok, мастер-флаг off. MCMC {chains:2,draws:80}.
- **🔴 RED-TEAM ВСКРЫЛ ЛОЖНОЕ СРАБАТЫВАНИЕ (исправлено):** на бессезонной синтетике
  калибровки (n=26) detect_seasonality дал ложный period=3, autocorr 0.265 > фикс.порога
  0.2 → Фурье инжектился где не должен → test_calibrated_recovers упал. КОРЕНЬ: фикс.порог
  0.2 ниже статзначимости. ФИКС: n-зависимый порог Bartlett `max(0.2, 1.96/√n)` (для n=26 →
  0.384 > 0.265 → отказ). test_calibration 5/5 восстановлен; юниты Фурье 22/22 (+2 на шум/
  масштабирование порога). Методологически честнее: сезонность должна быть СТАТЗНАЧИМА.

- **🔴 RED-TEAM #2: BACKTEST×СЕЗОННОСТЬ ПАДАЛ (исправлено, критичный):** бэктест-зонд на
  MMX (43 мес, годовая autocorr 0.63) вскрыл: backtest С сезонностью → ALL_WINDOWS_FAILED
  «6 отсутствующих контрольных season_fourier_*». КОРЕНЬ: config.control_columns сохраняет
  Фурье (modeler:1454 list(control_cols)); backtest-окно читает сырой data_file (Фурье нет) →
  валидация control (modeler:366) падала РАНЬШЕ моего инжекта (был на 383, holiday на 304 ДО
  валидации — потому holiday работал). ФИКС: перенёс Фурье-инжект ПЕРЕД валидацией control
  (после media-валидации) + синхро `control_cols = [c for c if not fourier_prefix or c in df]`
  (робастность: короткое окно/другой период/use_seasonality off — убрать несгенерированные
  Фурье). Регресс-тест test_backtest_with_seasonality_not_error. Бэктест-зонд теперь ok.
- **✅ ДОКАЗАТЕЛЬСТВО (MMX, живой зонд `tmp/probe_seasonality_backtest.py`):** БЕЗ сезонности
  MAPE модели 12.55%/worse_than_naive; С сезонностью (Фурье period 12, K=3) MAPE **10.2%**
  (−2.35пп, ближе к наивному 9.54). Автосезонность УЛУЧШАЕТ модель и работает с backtest.
  Вердикт всё ещё worse_than_naive (наивный сезонный на регулярной месячной MMX очень силён +
  малый MCMC зонда 300 draws/461 div недосходится). **ГРАБЛЯ ВОСПРОИЗВЕДЕНА** (worse_than_naive
  без сезонности) и ЧАСТИЧНО закрыта (MAPE ↓). Kagocel (31 нед): годовая неоценима (гейт ≥2
  цикла, 31<52 — честный отказ), сильная сезонность autocorr 0.86 есть но ряд короток.

- **✅ ФИНАЛЬНЫЙ MCMC (крепкий 4×1500) + ЧЕСТНЫЙ ВЫВОД:** MMX season verdict=worse_than_naive,
  MAPE 14.0 (наивный 9.54). ВАЖНО: крепкий 14.0 ХУЖЕ малого 10.2 → разброс = ШУМ backtest
  на коротких окнах MMX (43 мес, окна малы, seed-чувствительно), НЕ свойство автосезонности.
  **Вывод:** validated на MMX НЕ достигается — наивный сезонный на регулярной месячной
  сезонности труднопобедим (его идеальный случай: копирует прошлый год). Это НЕ провал фичи.
  **Главная ценность автосезонности — не победа в backtest, а ЧЕСТНОСТЬ ROI:** без сезонных
  контролей модель приписывает сезонную волну спроса медиа → завышенный ROI; Фурье отделяет
  сезон → чище декомпозиция (следует из канона Prophet, доказывать отдельным зондом
  decompose-с/без — опц. в Фазе Б). Грабля worse_than_naive воспроизведена; MAPE улучшается
  в прогонах; фича методологически корректна и интегрирована во все слои.
- **✅ ГЕЙТЫ 5b ЗЕЛЁНЫЕ:** Фурье 22 юнита + 5 интеграция + rolling_backtest/decomposer_invariants/
  decomposer_edge/server_backtest 163 + pptx_backtest/persistence_phase2 25 — ВСЕ passed.
  Перенос инжекта ДО валидации ничего не сломал. cargo/svelte не трогались (python-only).

- **🟢 ГЛАВНОЕ ДОКАЗАТЕЛЬСТВО — ROI-ЧЕСТНОСТЬ (зонд decompose с/без, MMX draws 800):**
  БЕЗ сезонности медиа-вклад **88М** → С Фурье **62М** = **−30%**. Performance-канал
  29.4М→9.2М (−69%!), Спецпроект 11.5→5.5. Без сезонных контролей модель ЗАВЫШАЛА медиа-ROI
  на 30%, приписывая рекламе сезонную волну спроса (каналы, коррелирующие с сезонным пиком,
  ловили всю волну). Фурье отделил сезон → честный (меньший) медиа-вклад. **Это ГЛАВНАЯ
  ценность (INV-50 честность метрик), убедительнее backtest-вердикта.** Автосезонность А
  ДОКАЗАНА полностью: грабля воспроизведена + MAPE↓ + ROI-честность (медиа −30%) +
  интеграция во все слои + тесты зелёные + 2 red-team фикса.

## 🟢 СОГЛАСОВАННАЯ СТРУКТУРА ОТОБРАЖЕНИЯ ДЕКОМПОЗИЦИИ (Антон, 2026-07-04, обсуждено с RAG)
Антон запросил обсуждение «как правильно с точки зрения бизнеса и эконометрической
методологии» показывать сезонность (реакция на ROI-доказательство медиа −30%). RAG-канон:
- **Chan & Perry 2017 §4.2.2** — сезонность даёт SELECTION BIAS если медиа таргетится на
  спрос (пример БУКВАЛЬНО наш: cold medicine = Kagocel!); MMM обязаны контролировать сезонность
  прокси → обоснование ОБЯЗАТЕЛЬНОСТИ отображения.
- **Jin 2017** — аддитивная декомпозиция y = base + Σ media (incremental).
- **Gelman Bayesian Workflow гл.27 / Brodersen 2015 BSTS** — аддитивное разложение на
  отдельно отображаемые компоненты (тренд/сезонность/эффекты); сезонность дней рождения —
  мультипликативная подача.
- **Wang & Jin §5.2** — конкуренты = отдельные CONTROL VARIABLES (не база, не медиа);
  знак signed (FMCG −каннибализация / OTC +растущий рынок — совпадает с modeler signed_competitor).

**РЕШЕНИЯ АНТОНА (все развилки закрыты):**
1. Сезонность показывать **как % к базе** (мультипликативная подача, даже если модель аддитивна).
2. Базу **раскрывать на под-компоненты** (поэтапный drill-down).
3. Фурье+категория **слоями** (не альтернатива): Фурье = база по умолчанию (0 затрат данных,
   всегда), категория (Фаза Б) = усиление точности когда клиент грузит DSM/IQVIA (сильнее —
   реальный спрос, полная защита от bias по Chan&Perry). Приоритет реализации: Фурье готов.
4. Конкуренты — **отдельная 4-я полоса верхнего уровня** (не в «Внешних»).

**ИТОГОВАЯ СТРУКТУРА (4 полосы верхнего уровня + drill-down):**
```
Уровень 1 (4 полосы):  БАЗА · МЕДИА · ВНЕШНИЕ ФАКТОРЫ · КОНКУРЕНТЫ
Уровень 2 (клик-раскрытие):
  БАЗА      → базовая линия (intercept+тренд) + Сезонность (±% к базе, ПОМЕСЯЧНО) + Праздники
  МЕДИА     → каждый носитель по-отдельности (incremental → отсюда ROI)
  ВНЕШНИЕ   → Цена + Дистрибуция + Категория
  КОНКУРЕНТЫ→ signed_competitor факторы (± двунаправленно)
```

## ✅ Т1+Т2+У4 BACKEND-ЯДРО ДЕКОМПОЗИЦИИ 4-ГРУПП ГОТОВО (2026-07-04, коммит 10ab909 на origin)
- **Т1 — Фурье → видимый фактор «Сезонность»:** `column_detection` — новый kind
  `'seasonality'` (паттерн `season_fourier`, registry+priority, паритет-якорь с
  FOURIER_COL_PREFIX); `modeler` — явная ветка prior mu=0.0 zero-centered (защита
  семантики sin/cos, поведение не изменилось — else уже давал 0.0, red-team ✓);
  `decomposer` — агрегация 2K sin/cos в ОДИН фактор «Сезонность» (ключ 'Сезонность',
  без beta_mean), вынос полосой из baseline, `_BREAKOUT_TYPES`+='seasonality',
  label='Сезонность'. **% к базе:** build_decomposition_series даёт `pct_of_base[]`
  = 100·эффект/base_reduced (финальная база после выноса, guard /0).
- **Т2 — верхний уровень 4 групп:** поле `top_group` в каждой серии (аддитивно),
  `_TOP_GROUP_MAP`: БАЗА{База,Сезонность,Праздники}·МЕДИА·ВНЕШНИЕ{Цена,Погода,Макро,
  Дистрибуция,Категория}·КОНКУРЕНТЫ.
- **У4 — детектор длинного периода:** detect_seasonality предпочитает НАИБОЛЬШИЙ
  период среди strong (autocorr≥0.8·max); fallback на сильный короткий. Не сломал
  MMX (period 12 сохранился) и yearly-тест (==52).
- **Red-team (8 проверок ✓):** prior не изменился · json_export/cert type='seasonality'
  честнее · narrative прокидывает · control_kinds персист не читается логикой ·
  decomposer_invariants синтетика без Фурье не активирует путь.
- **✅ ДОКАЗАТЕЛЬСТВО (живой зонд `tmp/probe_decompose_4groups.py`, MMX draws 400):**
  4 группы видны (БАЗА 514М incl. Сезонность + МЕДИА 99.6М); ОДНА полоса «Сезонность»
  top_group=БАЗА, суммарно ≈0 (перераспределяет), размах 6.77М ₽; **волна % к базе:
  пик май 2023 +41.6%, провал авг 2022 −31.5%** (летний спад/весенний пик — осмысленно);
  **тождество энергосохранения 0.0000%.**
- **✅ ГЕЙТЫ:** fourier 22+8 · forecast_validation 40 (+2 У4) · decomposition_series
  11 (+6 новых) · decomposer_invariants 163 · смежные (decomposer_edge/rolling_backtest/
  server_backtest/narrative/scenario_invariants/persistence_phase2/server_train_flags)
  335 в пакете — ВСЕ passed. cargo/svelte не трогались (python-only).

## ✅ У1/Т5б СЕЗОННОСТЬ В ПРОГНОЗАХ ГОТОВА (2026-07-04, коммит 477105b на origin)
`predict_scenario` учитывает детерминированную будущую Фурье-волну (helper
`_compute_scenario_seasonality`: Σ β·fourier(t_future=n_obs+i)·y_std к baseline,
z-score теми же control_means/stds обучения). Проведён СИММЕТРИЧНО через point-путь
(predicted/baseline_total/current-reconstruction) и posterior CI (per-period samples/
baseline_total_samples) → сезон в scenario+current+baseline_total, incremental/lift =
чистый медиа (сезон не течёт в «медиа»), но per-period прогноз и неполный цикл несут
волну; полный цикл Σ≈0 (промис «на Год» не смещён). Нули без Фурье. **Тесты 6**
(фаза/Σ-цикл/неполный/нет-Фурье/рассинхрон/живая волна) + гейты scenario_invariants
174·adr020 11·promises/backtest/server 34 passed. ⚠️ **Открыто:** optimizer goal-seek
имеет свой forward (не через predict_scenario) — сезонное согласование отдельным вопросом.

## ✅ У2 КАНАРЕЙКА СХЕМ (коммит 732f160) · У3 ЧИСЛОВОЙ ГЕЙТ РОЛЕЙ (f337743) · Т5 МУЛЬТИ-КЛИЕНТ+ADR (2026-07-04)
- **У2** (`tools/test_frontend_schema_parity.py`, 4 passed): каждый ключ buildTrainConfig ∈
  TrainRequest И TrainStartRequest; обе схемы синхронны; мастер-флаги на обеих сторонах.
  Якоря в train-config.js + server.py. 🔴 Находка (→Т6): buildTrainConfig НЕ шлёт
  use_seasonality — флаг всегда default True из GUI (полный тумблер = Т6).
- **У3** (`engines/validator._is_numeric_parseable` + гейт в validate_data; тесты 13):
  media/control нечисловым столбцам роль снимается до 'unused'+подсказка non_numeric_role;
  money-строки («3 836 962 ₽», двойная стратегия запятой) сохраняют роль. validator 511 passed.
- **Т5 ADR** `aurora-meta/DECISIONS/ADR-033-econometrica-decomposition-4-groups.md` (создан;
  коммит aurora-meta — отдельный репо, синк /sync-aurora). Атрибуция Chan&Perry/Jin/Wang&Jin/
  Gelman/Brodersen/Prophet + 4 решения Антона.
- **✅ Т5 МУЛЬТИ-КЛИЕНТ** (`tmp/probe_multiclient_decompose.py`, оба 31 мес): **Kagocel** —
  Фурье НЕ инжектнулась (гейт), полоса «Сезонность» корректно отсутствует; **Venarus** —
  годовая инжектнулась (period 12, K=3), волна −38.8%..+61.4% к базе. Оба: 4 группы
  (БАЗА/МЕДИА/КОНКУРЕНТЫ — competitor как 4-я полоса работает), тождество 0.0000%, полоса
  согласована с pickle. Инвариант ≥2 датасета выполнен.

## ✅ Т4 ПАРИТЕТ ОТЧЁТОВ (8462928) · tooltip-fix (10ab909→...) · Т6 ТУМБЛЕР (b132842) · У5 GATE (2026-07-04)
- **Т4** (коммит 8462928): цвет+подпись фактора «Сезонность» (violet #8b5cf6) в 3 зеркальных
  палитрах — PPTX charts._FACTOR_RGB · HTML interactive.FACTOR_COLORS · ChannelTimeline
  FACTOR_COLORS+LABELS. Сезонность автоматически рендерится полосой (role=factor) во всех
  потребителях SSOT. Гейты: PPTX/HTML 60 · verify pptx 43/43 · html 35/35 · svelte 0.
- **tooltip-fix ChannelTimeline:** «Сезонность:» падала в группу «Медиа» (баг) → теперь в
  «База» (решение Антона: сезонность ∈ БАЗА). svelte 0.
- **Т6 тумблер** (b132842): сквозная доставка use_seasonality (закрыта находка У2) —
  SeasonalityControl.svelte (тумблер + строка честности «Сезонность учтена: период, ρ=X» из
  diagnostics) · стор+гидрация+stale (project-state) · buildTrainConfig · Rust project.rs
  (поле+update+конструкторы) · modeler diagnostics['seasonality']. Гейты: канарейка У2 4/4
  (стережёт) · server_train_flags 4/4 · cargo check+tests OK · svelte 0.
- **У5** (ночной gate): tools/nightly_full_gate.ps1 (UTF-8 BOM, parse OK, механика доказана)
  против F-AUD-6.

## ✅ ФАЗА Б КАТЕГОРИЙНЫЙ КОНТРОЛЬ ГОТОВА (2026-07-04, коммит 7cc4212 на origin)
Продажи категории/рынка = экзогенный контроль спроса (Chan&Perry, «слой 2» решения Антона,
усиление сезонности). column_detection: kind 'category' (комбо ТЕМА+ОБЪЁМ, F-AUD-5 защищён;
classify_column-only) · modeler prior mu 0.3 (shared demand) · decomposer breakout-полоса
«Категория»→ВНЕШНИЕ ФАКТОРЫ · палитра emerald #10b981 (PPTX/HTML/UI)+tooltip · validate_data
прицельная подсказка (competitor есть, category нет). **Зонд Venarus:** category детект →
полоса «Категория»→ВНЕШНИЕ, тождество 0.0000%. Тесты 14+band+регресс 614+46·verify 43/43+35/35.
Реальная ROI-честность — на файле рынка DSM/IQVIA (механика доказана).

## ✅ САМОАУДИТ РАБОТЫ СЕССИИ ЗАКРЫТ (2026-07-04, коммит 685203d; область 64c2dc8..07b427d)
Метод: гипотезы классов → зонды. **4 находки исправлены с тестами:** F-1 🔴 derived-метрики
(«Доля рынка в руб»/«Market share value»/«SOM в руб. категория» = ТЕМА+ОБЪЁМ) падали в
kind 'category' → positive prior 0.3 на эндогенную долю при ручном override в Roles UI —
derived-гейт (доля/share/som/sov) + тест ×7 · F-2 🟠 vitest не гонялся за сессию → 3 golden
buildTrainConfig красные от use_seasonality — golden обновлён + тесты флага ×3 (урок: фронт-
изменение ⇒ vitest, svelte-check контракты не ловит) · F-3 🟡 SeasonalityControl после OLS
вечно «Обучите модель» — ols diagnostics.seasonality {detected:False, reason:'ols_mode'} →
честная строка · F-4 🟡 pct_of_base на вырожденной базе (<1% среднего) дал бы «+4000%» —
относительный guard. **Закрытые гипотезы (дефекта НЕТ):** drift_check фаза t_future бит-в-бит
(У1 закрыл М-1 и для drift) ✓ · backtest holdout фаза ✓ · seasonal-naive из жёсткой карты
(У4 бенчмарк не трогает) ✓ · WaterfallChart факторы не рендерит ✓ · narrative текстов нет ✓ ·
доставка diagnostics.seasonality E2E (train+restore) ✓. **Живой зонд У1×бэктест MMX:** MAPE
14.79→11.16 (сезонный holdout-прогноз лучше), naive 9.54, 4 окна ok — У1 бэктест улучшил, не
сломал. **Гейты: python ПОЛНЫЙ 1907 · vitest ПОЛНЫЙ 802 · cargo test 0 · svelte 0.**
Заметки на Т3 (не дефекты): знакопеременная полоса «Сезонность» в positive area-стеке —
решить визуально на live (вариант: % кривая отдельно, полоса в БАЗЕ) · tooltip-группировку
UI перевести на s.top_group из SSOT (сейчас по префиксу имени — хрупко) · pct_of_base
семантика = финальная база (residual внутри; альтернатива intercept+тренд — решение подачи).

## ✅ АУДИТ-УЛУЧШЕНИЯ 1,3 СДЕЛАНЫ (2026-07-04, коммит 121fba0; Антон заказал п.1,3)
- **Пункт 1 (надёжность):** `tools/nightly_full_gate.ps1` расширен python-only → ТРИ гейта
  (python tools/ + vitest + svelte-check, gate FAILED если любой упал; опц. -IncludeCargo).
  Проверено: `npm run check` даёт exit 1 при svelte-ошибке (гейт не декорация). Урок F-2:
  фронт-контракты ловит vitest, не svelte-check.
- **Пункт 3 (Т3-предшаг):** ChannelTimeline tooltip группирует по 4 верхним группам из SSOT
  (`seriesTopGroup` name→top_group из `s.top_group`; legacy → `fallbackTopGroup` по имени),
  вместо хрупкого префикса имени (класс «Сезонность→Медиа» закрыт системно). Праздники+
  Сезонность под «База», Категория под «Внешние факторы». Зонд логики зелёный. svelte 0 · vitest 802.

## 🎯 ТОЧКА ВХОДА Т3 (следующая сессия) = `NEXT_SESSION_T3_drilldown.md`
Самодостаточный промпт: задача (4 полосы клик-раскрытие + сезонная %-кривая), весь готовый
контекст, точные точки кода, 3 открытые UX-развилки для live (знакопеременная сезонность в
стеке / семантика % к базе / OLS), AVT-метод приёмки, план Т3.1-3.3 (+ опц. пункт 2 канарейка
палитр), инварианты (фронт-изменение ⇒ vitest; fetch отдельно от commit). Свежим заходом.

## ✅ Т3 — КОД ГОТОВ + ПРОГРАММНАЯ ПРИЁМКА (2026-07-04, коммит 6a50a91 на origin)
- **Реализовано:** `src/lib/decomposition-view.js` — SSOT view-логики (`planViewSeries`
  свёртка по top_group / drill-down, `seasonalityPctOfBase`, `presentTopGroups`).
  `ChannelTimeline.svelte` — свёрнутый режим 4 полос по умолчанию + chips-раскрытие
  групп (`$state expanded`) + клик по полосе, сезонная %-кривая на второй оси Y
  (тумблер-chip, «февраль +60% к базе»), tooltip: сезонность отдельной строкой вне
  total, highlight пропускает %-линию. Legacy signedFactors-путь не тронут.
- **Гейты:** vitest **828** (802 база + 26 новых, тождество свёрнуто/развёрнуто/edge) ·
  svelte-check **0** · decomposer_invariants **114**. Backend не трогался.
- **Программная приёмка на РЕАЛЬНЫХ данных** (готовые pkl без MCMC, `tmp/probe_t3_*`):
  MMX_4groups + Venarus — top_group на всех сериях, pct_of_base (MMX ±31.5/+41.6%,
  Venarus −38.8/+61.4%), тождество Σplan==Σисходных свёрнуто И развёрнуто (maxErr ~1e-7).
  🟡 Знакопеременная полоса «Конкуренты» Venarus (Σ≈0, ±67M) — НАСЛЕДИЕ (1 член,
  свёрнуто=развёрнуто), не регрессия Т3. Находки → `TEST_FINDINGS_2026-07-04_T3-drilldown.md`.
- **✅ САМОАУДИТ Т3 (по запросу Антона, коммит 46da855): 8 находок, все исправлены** —
  А-1 🔴 tooltip-дубль свёрнутой группы · А-2 🟠 сброс dataZoom на toggle (моя регрессия)
  · А-3 🟠 «Сезонность: Сезонность» в легенде · А-4 🟡 несимметричная %-ось
  (symmetricPctBound: MMX ±45, Venarus ±65) · А-5 осиротевший JSDoc · А-6 aria-pressed ·
  А-7 typedef top_group/pct_of_base · А-8 тур decompose-timeline описывал старый вид.
  Гейты после фиксов: **vitest 834** (828+6) · svelte-check 0 · канарейка 3/3.
  Осознанные решения + предсуществующее — в findings-протоколе.

## ✅ 5 УЛУЧШЕНИЙ ПОСЛЕ АУДИТА (по запросу Антона «реализуй все 5», 2026-07-04)
Коммиты f84ba44 (П1/П3/П4/П5) + b82203c (П2) на origin.
- **П1 плавная анимация раскрытия:** series.id + groupId(==top_group) +
  universalTransition → агрегат «перетекает» в составляющие (one-to-many morph),
  не резкая замена. `seriesIdentity()` в decomposition-view.js (+3 теста). Деградирует
  безопасно, если движок не морфит.
- **П5 «Развернуть/Свернуть всё»:** chip-кнопка (allExpanded $derived + toggleAll).
- **П4 канарейка py↔js:** `decomposition-view-parity.test.js` (9) — множество+ПОРЯДОК
  `_TOP_GROUP_ORDER` + подписи `_TOP_GROUP_DISPLAY` + fallbackTopGroup согласован с
  `_TOP_GROUP_MAP`. Тест поймал реальный gap 'Внешние'→МЕДИА — закрыт.
- **П3 регрессия drill-down:** юнит (seriesIdentity/planViewSeries тождество в
  гейтах) + driver_session-сценарий `docs/e2e/T3_drilldown_driver_session.md` для
  живого прогона (мост 9223 не бежит в CI — честно разделено).
- **П2 двухуровневость отчётов:** timeline в PPTX+HTML свёрнут в 4 группы (паритет
  с программой); детализация — waterfall + таблица каналов. `collapse_series_to_
  top_groups` SSOT (7 py-тестов, тождество вкл. реальный MMX). Приёмка: PPTX 43/43
  narrative (brand 0-регресс) · HTML 35/35 + a11y 15/15 (brand 0-регресс) ·
  **playwright живьём**: HTML timeline рендерит 2 группы (MMX), тождество
  613 571 910 на рендере, цвета корректны. Детали → TEST_FINDINGS.
  ⚠️ PPTX «отдельный слайд раскрытия» НЕ делался — ломает 12-slide verify-контракт
  + нужна визуальная проверка рендера PPTX (нет автономно). Развилка вынесена Антону.

Гейты после 5 улучшений: **vitest 846** · svelte-check 0 · python
decomposer_invariants 114 + collapse 7 + decomposition_series 13 + palette 3 · verify отчётов зелёные vs baseline.

## ✅ САМОАУДИТ №2 (неаудированная часть — 5 улучшений; по запросу Антона, коммит 452a477)
**8 находок, все исправлены:** Б-1 🔴 морф П1 не работал (series-groupId не существует
→ universalTransition.seriesKey, доказано типами echarts 5.6) · Б-5 🟠 двухуровневость
HTML была одноуровневой → payload {overview, detail} + кнопка «Детально ⇄ Обзор» +
тест two_level (4: overview==SSOT-свёртка, detail-полнота, Σ==Σ) · Б-2/Б-3 🟠 подписи
PPTX/HTML врали («вклад каждого канала») → фактический состав групп + baseline_label
«База» · Б-4 🟠 fidelity_diff устарел молча → канон-проверки, живой зонд ok ·
Б-6 🟡 ReportStep тексты · Б-7 🟡 aria-pressed у кнопки с меняющимся лейблом ·
Б-8 🔴 «Сезонность: Сезонность» в HTML detail (поймано ТОЛЬКО живым playwright-
прогоном). Живая приёмка: обзор 2 ↔ 8 detail серий, тождество 613 571 910 в обоих.
Гейты: vitest 846 · svelte 0 · python 141 · verify PPTX 43/43 · HTML 35/35+15/15 ·
brand==baseline. Предсуществующее отмечено (Бюджет ДО НДС медиа-серией; «по неделям»).

## ✅ 3 УЛУЧШЕНИЯ ИЗ АУДИТА №2 (Антон «1,2,4 на реализацию», коммит 88a9012)
- **П1 total-budget гейт:** «Бюджет ДО НДС» авто-детект media → обучается каналом
  (зонд: 6.45% вклада, дублирует сумму, рассинхрон timeline↔таблица). Дроп из
  timeline НЕВОЗМОЖЕН (тождество 613М→574М). FIX на ВХОДЕ: гейт validate_data по
  критерию `_normalize_channel_name → None` (единый с _merge_channels) → 'unused' +
  warning total_budget_as_media (паттерн У3). +2 теста. Обученные честны, новые не
  задваивают. — **П2 гранулярность:** `_period_unit()` (detect_granularity) →
  «Продажи по месяцам» вместо «по неделям»; kicker/s08 нейтрализованы; «stacked
  area» убран (живой MMX подтвердил). — **П4:** тултип «Итоговая сумма продаж
  одинакова в обоих режимах». — П3 (PPTX слайд) отложен Антоном.
- Гейты: python 48 · fidelity ВСЕ PASS · HTML 35/35+15/15 · PPTX 43/43.

## ✅ САМОАУДИТ №3 (фиксы Б-* + П1/П2/П4; по запросу Антона, коммит 543a731)
3 находки FIX / 12 чисто: **В-1 🔴** фильтр activeWarnings прятал АВТО-снижения ролей
(У3 non_numeric_role и П1 total_budget_as_media невидимы с первого рендера — колонка
уже unused) → типы авто-снижения видимы всегда + statusLabel честнее · **В-2 🟡**
«устойчивом baseline» → «устойчивой базе» (s08_leader) · **В-3 🟡** импорт из цикла.
Чисто: читатели timeline, ds= один, theme-override сохраняет TL_VIEW, импорты,
краевые имена, legacy-подпись, PNG-режим, тултипы. Гейты: vitest 846 · svelte 0 ·
py 19 · HTML 35/35+15/15. ⏳ live: баннер warning в GUI Валидации + морф Б-1.

## ✅ 4 ПРЕДЛОЖЕНИЯ АУДИТА №3 РЕАЛИЗОВАНЫ (Антон «по балансу», коммит c414683)
П-1 стоп-токены «итого/всего/сумма/total» (ИТОГО-Бюджет больше не канал; единый
критерий таблица+гейт; Total TV/Диджитал-всего целы; +7 тестов) · П-2 fidelity
PPTX-группы строгим равенством · П-4 kicker динамический «ПРОДАЖИ ПО МЕСЯЦАМ» ·
П-3 чек-лист live дополнен (баннер В-1 + морф Б-1). Гейты: py 29 · fidelity ok ·
HTML 35/35+15/15 · PPTX 43/43.

## ✅ САМОАУДИТ №4 (2026-07-05, коммит 0f5ae4a) — кривая аудитов СОШЛАСЬ: 8→8→3→1
**Г-1 🟡 FIX:** кнопка «Исключить» на уже исключённой валидатором колонке
(авто-warnings несли action='exclude') → action='acknowledge', фронт рендерит
«Принять»; тест фиксирует контракт. **23 подозрения чисто** (blast radius
стоп-токенов согласован по всем потребителям _normalize_channel_name с fallback;
коллизия под-агрегатов — штатный first-wins; PPTX строгий матч валиден при
_short-обрезании; идемпотентность bulk-ролей). Гейты: py 25.

## ✅ ПРИМЕРЫ ПРОГРАММЫ ПЕРЕСОБРАНЫ (3 решения Антона 2026-07-05, коммит cbc20ee)
**Аудит 9 файлов** (4 synth Импорта + 5 шаблонов справки) вскрыл: leads не KPI
(real_estate падал error), holiday_newyear двоил авто-праздники, шаблоны 0 строк
со шквалом ложных warnings, short_period врал на месячных, нет пар и категории.
**Реализовано конец-в-конец:** (1) КАЖДЫЙ канал = пара «бюджет ₽ + релевантный
Media KPI» (TRP/GRP/показы/контакты/клики; spend=physical×CPP_t, corr 0.99, CPP
= дефолты панели) → обе модели проходимы; (2) planted truth с целевыми ₽-ROI и
выводимой базой (медиа 30-33%, A/S 11%) — **доказано живым байес-фитом движками
программы: R² 0.89-0.97, лестница perf 4.45×/RM 4.73× > digital ≈2× > TV,
сезонность инжектится во всех, режим Эффективности R² 0.97**; генеративное ядро
приведено к форме модели (2 итерации по фиту: γ-хилл от среднего сырого adstock
+ dark-паузы + 48 мес); (3) category_sales (Фаза Б) в fmcg+otc, NY-dummy удалён
(FORBIDDEN), шаблоны = header-only копии (паритет держит SSOT-гейт).
**UI-развязка пар (ADR-015 впервые нагружен):** `channel-pairs.js` (группировка
по базе имени + resolvePairSelection; прежняя inline-группировка +page не
спаривала), express-план: пара с ₽-парником не ломает happy-path (физ-половина
→ disable), V13 применяет развязку в обеих точках; KPI_PATTERNS += leads/лиды/
заявки. Гейты: vitest 857 · svelte 0 · py 94 · SSOT-corr пропускает PAIRED.
⏳ Хвост примеров: справка data-preparation.html (текст «30 строк», описания
колонок) не переписана под пары; short_period гранулярность (движок) — отдельно.

## ✅ САМОАУДИТ №5 — пакет примеров (2026-07-05, коммит 844b4b9): 7 FIX из 20 подозрений
**Д-1 🔴** apteka_contacts→unknown в ролевом детекторе (SSOT-classify знал; ОТС «без
правок» ломался) → MEDIA_PATTERNS += contact/контакт/apteka/аптек · **Д-2 🔴**
promo_indicator→media («promo») → override *_indicator→control · **Д-3 🟠**
short_period считал строки неделями («36 — менее 1 года» на 3 годах месячных) →
длительность по датам (<358 дн) + критерий «<24 точек» · **Д-6 🔴 развязка пар была
бы декорацией**: ConfigPanel пересобирает тумблеры из persisted → persistPairToggles()
в confirm+express · **Д-7 🔴** cppSatisfied получал БАЗЫ при колоночных ключах →
physical-выбор невидим гейту (класс ROI 12186×) → activeModelColumns · **Д-9/10 🟡**
selectionByBase для сводки Manager и предвыбора radio после reload. Совместимость:
Manager-confirm строит снапшот по базам = вход нового confirm ✓; ConfigPanel цел ✓.
Живой зонд 4 файлов: unknown нет, promo→control, short_period молчит, fmcg/otc
status=ok. +6 тестов. Гейты: **vitest 857 (прогнан)** · svelte 0 · py 52.
Отчётная честность: прежнее «857» было экстраполяцией — теперь подтверждено.

## 🎯 ТОЧКА ВХОДА СЛЕД. СЕССИИ = `NEXT_SESSION_examples_live_and_tails.md`
Самодостаточный промт: Блок A (живая приёмка Т3 + путь ПАР в GUI + баннер В-1 +
UX-развилки — совместно с Антоном), Блок B (автономно: B2 канарейка детекторов
ролей, B1 справка data-preparation под пары, B3 Фаза Б хвост), Блок C (ждём
комментарии Антона по примерам). Recon + фикстуры + гейты + инварианты внутри.

## ⏳ ОСТАЛОСЬ — совместная визуальная live-приёмка Т3 (Антон у экрана = быстрейший верификатор)
- **Визуальная форма echarts** (код структурно не докажет): 4 свёрнутые полосы + цвета/
  наложение, клик-drill (chips + area), сезонная %-кривая на второй оси (масштаб/читаемость),
  tooltip-строка сезонности. Запуск `npm run tauri:dev` (мост 9223), фикстуры без MCMC:
  `mmx_4groups_dw7vr06g` / `Venarus_wj1n_gsq` в %TEMP%.
- **UX-развилки для Антона** (продуктовые суждения, не решаю сама): (1) сезонность ₽-полосой
  при развороте БАЗЫ vs только %-кривой; (2) семантика «% к базе» от финальной базы vs
  intercept+тренд. Наблюдение: dataZoom сбрасывается при toggle chip (мелочь).
- **Т3.3 канарейка палитр** (опц., СРЕДНИЙ): python-тест ⊇ `_BREAKOUT_TYPES` для 3 палитр.
- **Фаза Б хвост:** prior positive-leaning для category-колонок в column_detection + подсказка
  на Валидации «загрузите продажи категории» + доказательство decompose-с/без категории.

## ⏳ (архив плана) РЕАЛИЗАЦИЯ ОТОБРАЖЕНИЯ (recon СДЕЛАН — инфра ГОТОВА)
**✅ RECON (2026-07-04): инфраструктура декомпозиции по группам УЖЕ существует** —
`decomposer.py::build_decomposition_series` (стр.322) строит полосы с полями
{name, role∈{baseline/media/factor}, type, **group**, side, data[] помесячно} и честным
тождеством `baseline_reduced + Σфакторы + Σмедиа == total`. `_BREAKOUT_TYPES` (310) +
`_FACTOR_GROUP_LABELS` (313): signed_competitor→«Конкуренты», signed_price→«Цена»,
holiday→«Праздники» и т.д. `signed_factor_contributions` (880) классифицирует контроли
через `classify_column`→`factor_type_map` (899). **GAP: Фурье-колонки season_fourier_*
падают в 'positive_control' (не в map) → ОСТАЮТСЯ В BASELINE, не выносятся.** Стройка НЕ
нужна — точечная доработка (verify_existing_impl сэкономил огромно).

**ТОЧНЫЙ ПЛАН (5 точек, backend-ядро):**
Р1. `utils/column_detection.classify_column`: `season_fourier_*` → новый kind 'seasonality'
    (сейчас unknown/control). + prior positive-symmetric.
Р2. `decomposer.py:899 factor_type_map`: 'seasonality'→'seasonality'. **АГРЕГАЦИЯ:** 6 колонок
    sin/cos_K объединить в ОДИН фактор «Сезонность» (Σ per_period по всем season_fourier_*),
    не 6 полос — цикл 894 группирует по префиксу перед записью в signed_factor_contributions.
Р3. `_BREAKOUT_TYPES` (310) += 'seasonality'; `_FACTOR_GROUP_LABELS` (313): 'seasonality'→'Сезонность'.
Р4. **Верхний уровень 4 групп** (маппинг group→top): БАЗА{baseline,seasonality,holiday} ·
    МЕДИА{media} · ВНЕШНИЕ{price,weather,macro,category} · КОНКУРЕНТЫ{competitor}. Добавить
    поле 'top_group' в series ИЛИ маппинг в UI/отчётах. Сезонность помесячно как **% к
    baseline_reduced** (подача, решение Антона).
Р5. UI drill-down (топ 4 → раскрытие) + PPTX/HTML 4-групп + сезонная кривая. Тесты (агрегация
    Фурье в 1 фактор, тождество сохранено, % к базе) + доказательство decompose.
⚠️ decomposer — КРИТИЧНЫЙ (energy conservation, тождества baseline+факторы+медиа==total);
не ломать. Тесты decomposer_invariants 163 — гейт. ADR в aurora-meta (метод-решение + атрибуция).

## ⏳ Фаза Б — категорийный контрол (частично начата)
- **✅ Backend category-детект (коммит 5e66e81):** validator detect_column_role — «продажи
  категории/рынка» (объём) → control (приоритет над KPI, после derived: доля рынка остаётся
  unused). Тесты 40/40. **⏳ Осталось Б:** prior для category (positive-leaning shared demand
  в column_detection classify_column) + подсказка на Валидации «загрузите продажи категории» +
  доказательство decompose-с/без категории. автодетект колонки «продажи категории»
   (MMX уже имеет «Продажи в руб. конкуренты» — competitor-класс в validator; категория ⊃
   competitor) + подсказка на Валидации; «категория минус бренд» для доминаторов; 0 egress.
   Опц. зонд decompose-с/без для доказательства ROI-честности (медиа-вклад ↓ когда сезон/
   категория отделены). Recon: utils/column_detection classify_column + validator CONTROL_PATTERNS.
7. **UI/отчёт (опц.):** тумблер use_seasonality (как use_holidays в ConfigPanel); строка
   «сезонность учтена (период N)» в диагностике/отчёте — честность что модель контролирует сезон.
8. **Merge веток — решение Антона.**
   обучить с/без сезонности → backtest вердикт до (worse_than_naive) vs после. Ожидание:
   квартальная (P=13, гейт 31≥26 ✓) улучшит; если нет — честно зафиксировать (может, Kagocel
   грабля не квартальная). Мульти-клиент: MMX (длинный ряд → годовая P=52).
6. **Гейты:** pytest -n 4 (tools), vitest (если фронт трогали — вряд ли), svelte 0, cargo,
   verify_aurora_pptx_narrative 43/43. Коммит узким pathspec + пуш (режим пуша по ходу).
7. **UI/отчёт (опц., по объёму):** тумблер use_seasonality (как use_holidays в ConfigPanel);
   строка «сезонность учтена (период N)» в отчёте/диагностике — честность что модель
   контролирует сезон. Решить после доказательства А.
8. **Фаза Б (после А):** автодетект колонки «продажи категории» + подсказка на Валидации
   (экзогенный контрол; фарма DSM/IQVIA; «категория минус бренд»; 0 egress) — малый батч.

## Инварианты этой работы
- Детерминизм/pickle-совместимость (additive) не ломать; Фурье по t-индексу (не датам).
- Гейт ≥2 цикла — не подавать недоказуемую сезонность (INV-50). Мастер-флаг для opt-out.
- Мульти-клиент (≥2 датасета) перед ship narrative-изменений. Метод: зонд→верификация→тест→коммит.
- Снять флаг автономки когда Антон скажет «стоп/готово по автосезонности».
