# Планирование (прогноз вперёд) — мастер-промпт продолжения (durable)

> 🔴 ОБНОВЛЕНО 2026-07-10 (конец сессии, wrap-up mini): живой ретест v2.2.0 ПРОЙДЕН (8/8, `TEST_FINDINGS_retest_v220_2026_07_10.md`), фикс-пакет 8/9 закрыт, ПЕРВАЯ приёмка Планирования Антоном в dev дала комментарии — см. «ПРИЁМКА АНТОНА» ниже. 24 коммита, запушено до `6875b3c`.

## 🎯 ПРИЁМКА АНТОНА (первое тестирование Планирования, 2026-07-10) — доработать в след. сессии
1. 🔴 **P-1 «Ничего не понятно» + секция «Варианты медиаплана» пуста:** кнопка «+ Создать вариант» в коде есть (PlanningStep:498-503), на экране НЕ видна; экран статичен — нет ни прогноза, ни действия. **Решение (одобренный дизайн):** при подтверждённом медиаплане СРАЗУ авто-строить прогноз базового плана (econ_scenario с channels из media_plan.json, carry_in=true, once-guard по source_hash) → график история+прогноз (ContinuationChart, веер из predictions_ci_*) + карточка итога; варианты — поверх базового; кнопку сделать заметной (btn-primary). Разобраться, почему кнопка не отрендерилась у Антона.
2. 🔴 **PPTX: раздел планирования НЕ найден** — раздел условный (появляется при сохранённых вариантах в results/scenarios + planning.json), а вариант на приёмке не сохранялся (P-1). После авто-прогноза базового плана — писать planning.json автоматически, чтобы раздел жил без ручного сохранения варианта. Проверить цепочку до PPTX/HTML/XLSX живьём.
3. 🟠 **Демо-файлы — ТРЕБОВАНИЯ АНТОНА (2026-07-10, «продолжение следует» — ждать дополнений!):** два эталонных демо — **FMCG и Pharma**; продлить историю и включить медиаплан-хвост; данные удобны для тестирования: **медиа вносит ЗНАЧИТЕЛЬНЫЙ вклад в продажи** (не 3-9% как сейчас — нынешняя синтетика даёт base 90%+ и «план уже оптимален», из-за чего демо не показывает силу продукта), **высокий ratio** (наблюдений достаточно, ≥4:1), **разнообразная структура каналов — больше двух** (ТВ/OLV/OOH/performance/радио… с парами бюджет+метрика). Генератор — `tools/synthetic_pilot_data.py` (planted truth с бетами из ROI — задать ROI-лестницу с ощутимым медиа-вкладом и оптимумом НЕ в текущей точке, чтобы оптимизатор показывал видимый lift). **Финальная формулировка Антона: демо-файлы должны быть «удобные во всех смыслах и значениях» и раскрывать работу оптимайзера ПОЛНОСТЬЮ — данные достаточны, показательны, дают хороший интересный результат.** Практически это чек-лист на каждый файл: (а) история ≥36-48 мес (высокий ratio, работает «Проверка на истории» ≥3 окон — на приёмке 24 мес не хватило!); (б) медиа-вклад ~25-40%; (в) 4-6 каналов с парами и РАЗНОЙ отдачей/насыщением → Анализ даёт содержательное перераспределение (не +0.0%), Планирование — интересный lift; (г) сезонность+праздники выражены (декомпозиция красива, drill есть что раскрывать); (д) медиаплан-хвост 6-12 мес; (е) кириллические имена каналов; (ж) после генерации — ПОЛНЫЙ живой прогон обоих файлов по всем 7 шагам + отчёты (демо = витрина продукта, каждый экран должен «играть»). Пересобрать static/sample-data + Desktop.
4. ✅ Правило навигации СДЕЛАНО (`6875b3c`): Планирование активно только при подтверждённом медиаплане; иначе Оптимизация→сразу Отчёт (кнопка правдива, goNext перескакивает locked, confirmed в сторе).
5. ✅ «Зачем шаг „Отчёт"» на Планировании — починено (stepIdMap + контент planning в contextual-help).
6. ✅ «ceteris paribus» — русская оговорка.
7. 🟡 **P-3:** текст «Сбывшихся рекомендаций» ссылается на старое место («блок „Что если", режим „Планирование"») — обновить на «кнопка „Зафиксировать прогноз" выше на этом шаге».
8. 🔶 **П2-1 drill:** приёмка подтвердила на dev — чипы КЛИКАЮТСЯ (active-стиль, «Свернуть всё»), но живой график остаётся агрегатным; в jsdom тот же код работает (4 компонентных клик-теста зелёные). Вставлен console.debug в _canonicalView (число серий при пересчёте) + защита setOption в EChartBase. **След. шаг диагностики:** dev + консоль (F12) при клике чипа: (а) если debug-строка появляется с бОльшим числом серий → рвётся в EChartBase/echarts (смотреть [EChartBase] setOption failed); (б) если не появляется → derived не пересчитывается в webview-сборке (искать разницу vite prod/dev трансформации рун). Затем убрать console.debug.

## 🔍 АУДИТ СЛЕДУЮЩЕЙ СЕССИЕЙ (обязательный, Антон)
Вся работа ПОСЛЕ fix-коммита `a188986` НЕ аудирована внешним аудитором: фиксы ретеста (`e3da594` A6-1 нормализатор, `8afdbb7` инсайты+тексты отчётов, `690953f`+`2fa8190` матрица/adstock/клик-тест/EChartBase-защита, `c0f49ab` consent-тексты, `6875b3c` правило навигации+WhyThisStep). Прогнать wrap-up шаги 4-7 (handoff по диффу a188986..HEAD → 2 аудитора opus (фронт+python) → триаж → fix-коммит).

> **Точка входа при возврате / после компрессии.** Читать ПЕРВЫМ. Продолжать БЕЗ переспроса с раздела «ОСТАЛОСЬ», развилки решать самой (мандат Антона: автономна на исполнении и тактике). Снять режим — по слову Антона «стоп/готово по планированию».

## Что делаем
Разделяем шаг «Оптимизация» на два лица одного движка: **«Оптимизация (ретроспектива)»** → **«Планирование (прогноз вперёд)»**. Модель одна, оптимизатор один. Вход планирования — тот же обучающий Excel, где после истории идут будущие месяцы (даты за концом истории, KPI пуст, инвестиции по каналам заполнены = медиаплан). Движок прогоняет медиаплан через обученную модель → прогноз + варианты. Отдельный прогноз-раздел в отчётности для руководства + ретро-выводы для аналитика.
**Цель:** не повторить Robyn/Meridian, а стать образцом — эконометрика ТОП-уровня силами обычного планера.

**Полный план (после 2 раундов адверс-аудита):** `C:\Users\ackol\.claude\plans\synchronous-stirring-wilkinson.md` (план v3, находки A1-A12, S1-S7, U1-U10).

## Ветка и режим работы
- Ветка **`feat/econ-planning-mode`** от `feat/econ-e1-backtest` (НЕ запушена — пуш по слову Антона). Репо `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`.
- В репо живут чужие незакоммиченные (`installer_hooks.nsh` M, `model_backend.rs` ??) — НЕ трогать, коммитить своим pathspec.
- Кодинг — субагентам на sonnet, я (Opus) — оркестрация + ЛИЧНАЯ верификация (прогон тестов сама, git diff, сырые выводы — урок про фантом-агента [[feedback_agent_report_requires_raw_outputs]]).
- Запуск тестов: из `sidecar/econometrica`: `python -m pytest tests/ -q -m "not requires_real_data"`. Фронт: `CI=1 npx vitest run`, `npm run check`. Rust: `cd src-tauri && CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" cargo check`.

## ✅ СДЕЛАНО (6 коммитов, все гейты зелёные)
Гейты на HEAD: **sidecar pytest 475 passed** (1 правомерный OLS-skip), **vitest 996**, **svelte-check 0**, **cargo check Finished**.
- `424efe8` Фаза 0+1b+1a-i+2 — скелет: детектор хвоста (`engines/planning.py` detect_media_plan_tail/load_frames/compute_source_hash), carry-in математика (`utils/adstock.py` — точечный+batch+диспетчер), 7-й шаг пайплайна `planning` (миграция localStorage 6→7 с ремапом currentStep, сторы mediaPlanDetected/planningManifest, PlanningStep-заглушка).
- `0898ea1` INT-1 — SSOT-разделение история/хвост: notna(kpi)-фильтр у modeler/optimizer/backtest/persistence + детекция в validator (пишет media_plan.json). Регресс-инвариант: файл без хвоста → no-op. Чинит существующий NaN-краш likelihood.
- `e4f2769` INT-2 — carry-in + праздники + horizon-cap + disclaimers в scenario.py (planning-режим); ScenarioRequest +future_dates +carry_in.
- `ef3a461` A3 — carry-in в backtest-витрине (forecast_periods в окна) + доказательство веера A2 (обе границы CI поднимаются, posterior-фикстура) + A9 (holiday∩fourier исключён).
- `9efb490` Фаза 3+4 — баннер медиаплана (ValidateStepV13, подтверждение A6) + полный PlanningStep.svelte (U1-U10) + Rust econ_scenario проброс future_dates/carry_in.
- `af12181` Фаза 6a — прогноз-раздел PPTX (s_forecast_plan) + HTML (render_forecast_plan) + load_saved_forecast + narrative/export проброс.

**Ключевое доказано числами:** carry-in реально поднимает `predictions[0]` (разделяющий зонд на обученной модели), линия и веер согласованы. Backtest наследовал ту же дыру (A3) — теперь carry-in чинит и справедливость вердиктов worse_than_naive.

## ⏳ ОСТАЛОСЬ (продолжать отсюда, порядок по приоритету)
1. **Фаза 5 — чистка OptimizeStep (expand-contract contract-шаг).** Удалить planning-блоки из `OptimizeStep.svelte` (4269 строк): planning-mode-toggle, ForecastHorizonPicker, planning-banner, hierarchicalWarning, блок «Прогноз с медиаинфляцией», fixForecastPromise/PromisesCard, econ_forecast_context $effect, planning-ветку effectiveBaseBudget/runOptimize. `planningMode` стор — удалить (grep читателей) или зафиксировать 'analyst'. ПЕРЕД удалением — характеризующий тест OptimizeStep. Гейт: svelte 0, vitest, analyst-оптимизация не сломана. (Делается ПОСЛЕ того как PlanningStep доказан живым — сейчас PlanningStep готов, но живьём не прогнан → аккуратно.)
2. ✅ **Фаза 6 (отчётность) ЗАВЕРШЕНА ЦЕЛИКОМ** (коммиты af12181+59d47da+d2c50cd): прогноз-раздел PPTX+HTML+XLSX-лист «Прогноз», график сравнения вариантов подключён (HTML img + PPTX в слайде, overflow чист), ретро-блок «что улучшить» (render_retro_insights, отделяет аналитику от руководства). pytest 486.
3. ✅ **F-AVT-3 (TODO-команды) СДЕЛАНЫ** (коммит 14de2db): `econ_download_media_plan_template` (U5, замкнутый цикл доказан на реальной модели) + `econ_confirm_media_plan` (персист confirmed). Живьём вскрыты+починены 2 бага реального артефакта (голый pickle.load на posterior-моделях → load_model_with_compat; date_column не в config → детект). pytest 499.
4. **optimizer planning carryover (остаток Фазы 1, вторично):** carry-in в `evaluate_flat_allocation_response` (utils/forecasting.py) + optimizer planning-mode. Основной путь (scenario) carry-in уже имеет; это для «оптимизировать будущий бюджет».
5. **Фаза 7 — живой прогон ЧАСТИЧНО ПРОЙДЕН (2026-07-10, AVT):** backend-путь доказан ЧИСЛАМИ на реальной фикстуре (детекция кириллицы после фикса F-AVT-1 · carry-in predictions[0] 20.77M vs 12.32M +68% · disclaimers · праздники) + GUI-вёрстка PlanningStep вживую через мост :9223 (7 шагов, U1/U2/U5/U6/U9, 0 англицизмов, скриншот tmp/avt_planning_step.jpg). **Нашёл+починил F-AVT-1** (медиаплан не читался для русских каналов — критично; коммит 5d6e738 + регресс-тест). Находки → `TEST_FINDINGS_planning_AVT_2026_07_10.md`. **ОСТАЛОСЬ по Фазе 7:** ✅ F-AVT-3 команды СДЕЛАНЫ (14de2db). ✅ Функциональный прогон через ЖИВОЕ приложение (свежий sidecar bayesian synth-fmcg, ipc econ_scenario): carry-in вживую pred[0] 148.35M vs 145.24M, **ДИ-веер [137.4M,160.7M] на bayesian — A2 закрыт живьём** (в CI скипался на OLS), disclaimers ×3. **ОСТАЛОСЬ:** (в) **пересборка sidecar** `build_sidecar.py` (fat-client — все Python-правки внутри) + финальный гейт + installer по aurora-fix + публикация по слову Антона. (Опц.: полный GUI-клик-путь импорт→график, но функциональный ipc-путь уже доказал движок в приложении.)
6. **Фаза 7-старое — пересборка + релиз (детали):** 🔴 Пересобрать sidecar `build_sidecar.py` (fat-client — `npm run tauri build` sidecar НЕ пересобирает, V39). Живой GUI-прогон полного пути через tauri-мост (AVT-метод, `npm run tauri:dev` для моста :9223): создать тестовый Excel с хвостом → Импорт → Валидация (баннер) → Модель → Декомпозиция → Оптимизация → **Планирование** (варианты, сравнение, disclaimers, фиксация) → Отчёт (прогноз-раздел). Durable TEST_FINDINGS. Разделяющий зонд carry-in первым ходом (с/без — числа отличаются). CI-веер carry-in (A2) на живой bayesian-модели проверить (в CI скипался на OLS). Финальный гейт: pytest+vitest+svelte 0+cargo+verify. Installer по `aurora-fix`; публикация — по слову Антона (канал `aurora-econometrica-gui`; V52; локальная M1 отдельным манифестом).

## Контракт данных (якорь)
- `results/media_plan.json`: `{n_future_periods, period_labels[], granularity, channels:{col:[float]}, future_dates[], detected_at, source_file, source_hash, confirmed:bool, warnings[]}`.
- `results/planning.json` (манифест): `{variant_ids[], accepted_variant, disclaimers[]}`; данные вариантов — в `results/scenarios/*.json`.
- Результат сценария (planning): `predictions[]`, `predictions_ci_low/high[]`, `total_kpi`, `total_spend_money`, `roas_money`, `carry_in_applied`, `disclaimers[]`, `future_dates[]`.

## Внешний аудит блока (2026-07-10, два opus-аудитора по диффу, чистый контекст) — ЗАКРЫТ
**2 Critical + 5 High подтверждены триажом и ИСПРАВЛЕНЫ** (fix-коммит, все гейты зелёные: pytest 500 · vitest 8 · svelte 0 · cargo ok):
- A-Crit: carry_in читал историю+хвост из data_file (перенос от конца ХВОСТА, не истории; исполняемый зонд: 4.92M vs 6.51M) → notna-фильтр в scenario + решающий тест «файл-с-хвостом == файл-только-история».
- A-H: ols_modeler и decomposer — незакрытые потребители data_file (fillna(0)-обучение на фейковых нулях; хвост тёк в декомпозицию) → notna симметрично modeler.
- A-H: horizon-cap тихо не срабатывал без data_file → первичный источник training_n = len(y_actual) из pickle.
- B-Crit: project.rs НЕ читал planning/media_plan (субагент Фазы 2 заявил и не сделал — ещё одно попадание [[feedback_test_asserts_what_agent_claims]]) → ключи добавлены + hasPlanning в restore/reconcile + сброс mediaPlanDetected при смене проекта.
- B-H: миграция localStorage писала payload проекта в глобальный ключ (кросс-проектная протечка) → persist только в исходный ключ.
- B-H: $effect PlanningStep перетирал ввод бюджетов при ретриггере $optimizeData → guard «сеять только пустой ввод».

**Medium-бэклог аудита (подтверждены, НЕ чинились — забрать в след. сессию):**
1. holiday: валидировать len(future_dates)==n_periods (сдвиг праздников при рассинхроне).
2. holiday_dummies_mode: дефолт scenario 'binary_point' vs modeler пишет 'fraction' — персистить режим и в OLS-путь/легаси.
3. NaT в датах хвоста протекает в future_dates → фильтровать в detect.
4. compute_source_hash: 512KB+size — правка дальней ячейки при равном размере не ловится → полный хэш для файлов ≤50MB.
5. Тихий except в carry-in блоке scenario — логировать причину (наблюдаемость).
6. goToReport помечает Планирование complete при 0 вариантов (пустой манифест) → не complete/не писать манифест.
7. saveVariant при battом totals добавляет вариант с KPI=0 → валидировать predicted_kpi.
8. Тест миграции не покрывает per-project ключ (`econ-pipeline-meta-<id>`).
9. confirm/dismiss медиаплана глотают ошибку invoke → retry/индикация (диск↔UI рассинхрон confirmed).
10. downloadTemplate: status ok без path → показать ошибку.
11. (pre-existing, вне блока) validate_project_dir ловит только `..` — absolute вне projects-root не блокируется Rust-слоем (sidecar прикрывает; усилить allow-list'ом).

## Грабли / уроки сессии
- carry-in форма ОБЯЗАНА совпасть с обучением (рекуррентный geometric, posterior-decay, нормировка adstock_mean_posterior) — иначе перенос в неверном масштабе (A5). Weibull carry-in — фаза 2 (только JAX-backend).
- horizon-cap раньше жил под `plan_n==1` — обходился медиапланом-вектором (A4, закрыто).
- backtest carry-in гейтится по forecast_periods — надо ПЕРЕДАВАТЬ явно (A3, закрыто).
- Субагенты параллельно на пересекающихся файлах → коллизия в дереве (resumed INT-2 + мои backtest-правки). Разруливать зондом git status/diff, не доверять отчёту агента об атрибуции.
- Rust econ_scenario конвертит camelCase (futureDates→future_dates) авто.
