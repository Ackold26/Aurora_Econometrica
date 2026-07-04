# Автономка: Автосезонность А→Б (durable-реестр, ФАКТ)

> Реестр отражает ФАКТ (feedback_durable_registry_is_fact_not_plan): ✅ только со
> свершившимся числом-подтверждением, ⏳ — TODO без деталей «как прошло».
> Точка входа при возврате/после компрессии: читать ЭТОТ файл + [[INDEX_econometrica]],
> продолжать БЕЗ переспроса с раздела «СЛЕДУЮЩЕЕ». Развилки решать самой (мандат Антона
> «веди максимально автономно», 2026-07-04).

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

## ⏳ СЛЕДУЮЩЕЕ (продолжать отсюда)
5a. **Финальное доказательство крепким MCMC** (опц.): MMX season с draws≥1500/target_accept
    0.95 — обгонит ли наивный (validated)? Малый MCMC зонда недосходился. Если да — полное
    доказательство; если нет — зафиксировать «улучшает, наивный на MMX силён» (честно).
5b. **Гейты полные:** pytest tools связанные (test_decomposition_series/holiday_reinject/
    server_backtest — не сломал ли перенос инжекта) + svelte(нет) + cargo. Коммит сделан.
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
