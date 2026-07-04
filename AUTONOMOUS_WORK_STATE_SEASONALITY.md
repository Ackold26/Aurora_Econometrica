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

## ⏳ СЛЕДУЮЩЕЕ (продолжать отсюда)
1. **Инжект Фурье в modeler.py** после строки 382 (n_params): мастер-флаг
   `use_seasonality = config.get('use_seasonality', True)`; detect_granularity+detect_seasonality
   на y; should_inject → generate_fourier_terms → df[col]=... + control_cols.append(col);
   пересчитать n_params; собрать `fourier_seasonality_meta` (period, n_harmonics, columns,
   granularity, autocorr). try/except non-fatal (как holiday).
2. **Persist в model_data:** рядом с seasonality_detected (modeler.py:1487) сохранить
   `model_data['fourier_seasonality'] = fourier_seasonality_meta`. Обновить persistence.py
   (setdefault + docstring) для backward-compat старых pickle.
3. **decomposer.py re-inject** (детерминизм, как holiday decomposer.py:482): при декомпозиции
   переинжектить те же Фурье-колонки из fourier_seasonality_meta (generate_fourier_terms
   по n_obs+period+K) ДО применения модели, иначе X-матрица не сойдётся.
4. **Тесты интеграции** (tools/): (а) modeler инжектит при годовой синтетике ≥2 цикла,
   не инжектит на коротком ряду; (б) decomposer паритет колонок; (в) fourier_seasonality
   в pickle. Возможно tools/test_server_*.py шов.
5. **Бэктест-доказательство на Kagocel** (живой зонд, headless sidecar :7529 или tmp/probe):
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
