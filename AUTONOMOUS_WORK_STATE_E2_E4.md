# E2 Калибровка lift-тестами + E4 Рекомендации-обещания — durable-реестр

> **Старт:** 2026-07-03 · ветка `feat/econ-e1-backtest` (продолжение дня E1→UX→UXP→E3)
> **Вход:** ROADMAP v3 §E2+§E4 (Фаза 3, методологический пик + замыкание петли доверия).
> **Мандат:** автономно, развилки самой, реестр = ФАКТ, heartbeat 600, батчи с гейтами.
> **При старте/компрессии:** читать этот файл, продолжать БЕЗ переспроса. Мост tauri НЕ вызывать.

## RAG-канон (поднят, батч E24-0)
- **Robyn (Meta 2024, arXiv 2403.14674) §2.2/§4.3:** калибровка экспериментами =
  метод идентификации, двигает оценки по «спектру инкрементальности» к RCT-ground-truth;
  MAPE.LIFT как целевая ошибка калибровки в multi-objective оптимизации.
- **Jin et al. 2017 (Google):** experiments as informative priors для MMM.
- **Gelman BW:** proper priors; предупреждение об overfitting при model selection.

## Ключевые дизайн-решения (E24-0)
- **D-E2-1 Калибровка = ДОПОЛНИТЕЛЬНОЕ НАБЛЮДЕНИЕ правдоподобия, не ручной приор.**
  ROADMAP предлагал «prior=Normal вокруг калиброванного β», но β_calib зависит от
  sat/adstock (курица-яйцо). Каноничнее (Robyn MAPE.LIFT-класс): в PyMC-модель
  добавляется observed-узел: суммарный вклад канала за период теста (в norm-шкале)
  ~ Normal(измеренный lift_norm, σ_norm из интервала теста). α/γ/decay/β
  согласуются сами. Пометка в отчёте остаётся «[CALIBRATED]».
- **D-E2-2 Вход теста:** {channel, date_from, date_to, lift_abs (в единицах KPI),
  lift_low, lift_high, confidence_level (0.8/0.9/0.95), test_type}. σ_abs =
  (hi−lo)/(2·z(level)). Подготовка/валидация дат→индексы — чистый модуль
  utils/calibration.py (юниты без PyMC).
- **D-E2-3 Честность расхождения:** pm.Deterministic per калибровка →
  после сэмплирования diagnostics.calibration_check: {channel, model_contrib
  mean/CI, test_lift, within_ci: bool}; расхождение вне CI → warning в
  диагностику и отчёт (НЕ замалчивать — §E2.4).
- **D-E2-4 Только bayesian:** OLS без приоров/likelihood-узлов — честный отказ
  «калибровка требует байесовского режима» на этапе валидации конфига.
- **D-E2-5 Pickle additive:** config.calibrations + diagnostics.calibration_check;
  старые пиклы без полей работают как раньше.
- **D-E4-1 Обещание:** results/promises.json (atomic): [{id, created_at,
  action_text, channel_changes {ch: delta_pct}, expected {kpi_total, ci_low,
  ci_high, horizon_periods}, extrapolation_flag, check_after_index (номер
  наблюдения данных, после которого можно сверять), status pending/kept/missed/
  inconclusive, checked_at, actual_kpi_total}]. Создание — из результата
  optimize/goal-seek (CI и extrapolation уже есть в движках).
- **D-E4-3 (решение Антона 2026-07-04):** кнопка называется
  **«Зафиксировать прогноз»** (не «Зафиксировать как обещание»).
- **D-E4-2 Сверка фактом:** promise_check(df): факт = сумма KPI за
  horizon_periods строк данных ПОСЛЕ check_after_index; kept = внутри CI;
  missed = вне; inconclusive = данных ещё не хватает. Оговорка о внешних
  факторах — в текст карточки/отчёта (честность: сверка ожидания, не каузальный
  вывод).

## Реестр задач (статус — только по факту)
| # | Задача | Статус |
|---|---|---|
| E24-0 | RAG + аудит лесов (зона likelihood modeler:730-735, channel_action, scenario CI) + реестр | ✅ 2026-07-03 |
| E2-1 | Движок: utils/calibration.py (prepare+валидация) + вживление lift-наблюдений и Deterministic в modeler + calibration_check в диагностику + характеризующий тест (синтетика с зашитым lift: калиброванная ближе к истине) | ✅ 5 тестов за 50с (характеризующий ПРОШЁЛ на коррелированной синтетике; calibration_check доставлен; OLS-отказ; ошибки русские) |
| E2-2 | Доставка: config.calibrations через TrainRequest → UI-форма «Результат эксперимента» (ConfigPanel advanced) + persist | ✅ server model_dump (Rust прозрачен), buildTrainConfig bayesian-гейт, CalibrationPanel + store per-project, 10 vitest + 15 регресс |
| E2-3 | Отчёт: [CALIBRATED] у канала + строка «приор откалиброван тестом от <дата>» + честное расхождение (PPTX/narrative) | ✅ адаптер diagnostics.calibration → [CALIBRATED]-run в таблице каналов + строки на «Данные и качество» (расхождение within_ci=false золотом «разберите с аналитиком»); 18 PPTX-тестов + verify 43/43; svelte 0 (грабля: engine — локальное имя, в шаблоне $modelEngine) |
| E4-1 | Движок promises.py: create_from_optimize / list / check_all + тесты (kept/missed/inconclusive, extrapolation-пометка) | ✅ 7 тестов (kept/missed с честной оговоркой «не каузальный вывод», pending со счётчиком, окончательные не пересматриваются, битый json) |
| E4-2 | Доставка: endpoints + Rust + UI-карточка «Сбывшиеся рекомендации» (кнопка «Зафиксировать прогноз» в Optimize) | ✅ 5 server + 6 vitest; кнопка у what-if планирования (сценарий с CI будущего → обещание; гейт planner; экстраполяция помечена); карточка с честными бейджами |
| E4-3 | PPTX/narrative «Сбывшиеся рекомендации» + живой зонд (синтетика двух обновлений данных) + сводный отчёт docs/audits/E2_E4_2026_07.md | ✅ строки «сбылось N, не сбылось M» + примеры (только сверенные; pending не показывается) на «Данные и качество»; живой цикл 7/7 через транспорт (kept, факт 4040 в CI, PPTX со строкой, 0 маркеров); отчёт написан. **Финальные гейты Фазы 3: python-регресс 58 · vitest 791/791 · svelte 0 · verify 43/43 · cargo чисто** |

## Волна MC — multi-client прогон отчётного пути (правило памяти: ≥2 клиента) — ✅ ЗАВЕРШЕНА
| # | Задача | Статус |
|---|---|---|
| MC-1 | Венарус: validate→train→decompose→optimize→backtest→PPTX, 0 маркеров | ✅ ВСЁ ЗЕЛЁНОЕ: train bayesian 96с 200 ok (после F-MC-1), дека 12, 0 маркеров, бэктест честный insufficient (короткий ряд). Дефект зонда (промежуточные «Показы/Клики» в каналах) — продукт честно требовал цену единицы; отбор чищен |
| MC-2 | MMX 2021-2025 (длинный ряд): тот же путь | ✅ ВСЁ ЗЕЛЁНОЕ: train 22с, **бэктест ok 6 окон (153с, worse_than_naive — честно, сезонность без контролов, как Kagocel)**, дека 13 со слайдом витрины №6, заголовки живые (глазами), 0 маркеров |
| MC-3 | MATH_REFERENCE-дополнение (E1 предиктивный интервал, E3 перекрытие CI, E2 калибровка-likelihood) | ✅ раздел «Trust loop E1–E4» перед Literature + NaN-гигиена швов |
| MC-4 | Тест класса F-MC-1 на шов | ✅ tools/test_server_nan_safe.py 3/3 (monkeypatch NaN/Inf → 200 с null) + регресс server 28 |

**Итог multi-client: три клиентских датасета (Kagocel + Венарус + MMX) прошли
отчётный путь с новыми блоками; wireframe-маркеров 0 на всех.**

## Находки по ходу
- **F-MC-1 (Венарус-зонд, ИСПРАВЛЕНА в коде, повторный прогон pending):**
  train на Венарусе (21 медиа → 8 в зонде, две целевых) вернул HTTP 500
  «Out of range float values are not JSON compliant: nan» — модель обучилась,
  но HTTP-ОТВЕТ содержал NaN в диагностике (вырожденный канал): файлы
  санитайзились (sanitize_nonfinite), а ответы endpoints — НЕТ (класс P3
  NaN-blindspot из аудита v2.0.1-rc2). Фикс: sanitize_nonfinite на ответах
  train-семейства — /compute/train, /compute/train/result/{id}, /compute/decompose.
  Для клиента это был бы «500 на кнопке Обучить» на первом дне.

## Журнал батчей (только совершённое)
- **E24-0 (2026-07-03):** RAG-канон поднят (Robyn §4.3 калибровка-как-идентификация
  и MAPE.LIFT; Jin 2017; Gelman BW); зона вживления найдена (modeler:703-735 —
  per-channel вклад `media_betas[i]*saturated` доступен как pt-выражение в цикле;
  likelihood на 733-735); дизайн-решения D-E2-1..5, D-E4-1..2; реестр создан.
- **E2-1 (2026-07-03):** utils/calibration.py (prepare_calibrations: даты→индексы,
  сплошность периода, ≥2 наблюдений, траты>0, σ из интервала по z(0.8/0.9/0.95),
  русские CalibrationError); modeler: prepare после y_norm (CALIBRATION_INVALID
  до сэмплирования) + в цикле каналов pm.Deterministic(calib_contrib_N) +
  pm.Normal(lift_obs_N, mu=вклад за период теста, σ_norm, observed=lift_norm) +
  после сэмплирования diagnostics.calibration_check (mean/CI90 native vs
  test_lift, within_ci) и calibration_applied; ols_modeler: честный отказ
  CALIBRATION_REQUIRES_BAYESIAN. Тесты tools/test_calibration.py **5 зелёных
  за 50с**, включая ХАРАКТЕРИЗУЮЩИЙ (критерий ROADMAP): TV/Digital r≈0.97 →
  некалиброванная размывает вклад; lift-тест по TV (σ=15%) подтянул полный
  вклад TV ближе к истине (|err_calib| < |err_uncalib|, печать чисел в тесте).
- **E4-1 (2026-07-03):** engines/promises.py: create_promise (точка отсчёта =
  n_obs данных на момент обещания через C3-резолвер; валидации BAD_HORIZON/
  EMPTY_ACTION/NO_DATA), list_promises, check_promises (факт = сумма KPI строк
  ПОСЛЕ точки отсчёта за horizon; kept/missed по CI ожидания с честной
  оговоркой «сверка прогноза, не каузальный вывод»; pending со счётчиком
  «X из Y»; inconclusive без CI; окончательные вердикты не пересматриваются);
  atomic promises.json. Тесты tools/test_promises.py **7 зелёных**.
