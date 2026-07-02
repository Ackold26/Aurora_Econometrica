# АВТОНОМНАЯ РАБОТА: мат-аудит ядра MMM Optimizer

> **SSOT прогресса аудита.** Метод и фазы — в плане `C:\Users\ackol\.claude\plans\rippling-growing-hamming.md`.
> Протокол восстановления после компрессии/обрыва: прочитать этот файл + план → продолжить с «ОСТАЛОСЬ» БЕЗ переспроса.
> Развилки решать самой; методологические правки — с RAG-атрибуцией (`lib_vec.py search`, двуязычный запрос).
> 🫀 **HEARTBEAT (поручение Антона 2026-07-02, страховка от «API Error: socket closed»):**
> в КОНЦЕ КАЖДОГО хода вызывать `ScheduleWakeup(delaySeconds≈900, prompt=<восстановительный промпт ниже>)` —
> сессия сама просыпается через ~15 мин и продолжает работу без вмешательства Антона.
> Восстановительный промпт: «Продолжай автономный мат-аудит MMM Optimizer: прочитай
> Dev/Aurora_Econometrica/AUTONOMOUS_WORK_STATE_MATH_AUDIT.md (секция ОСТАЛОСЬ + микростатус)
> и продолжи БЕЗ переспроса. Если это пробуждение после обрыва — восстановись по durable-состоянию.
> В конце хода снова вызови ScheduleWakeup(900) с этим же промптом. Стоп — только по слову Антона.»
> Снять heartbeat, когда Антон скажет «стоп/готово по мат-аудиту».

## 🔬 МИКРОСТАТУС (обновлять при каждом незакоммиченном изменении!)
- Незакоммиченного нет (батч №3 закоммичен, см. СДЕЛАНО). Следующий шаг — п.1 раздела ОСТАЛОСЬ.

## Шапка
- **Статус: ✅ АУДИТ ЗАВЕРШЁН (2026-07-02).** Все 31 находка реестра закрыты (18 FIX с тестами, 7 FALSE разоблачены пробами, 6 TRADEOFF задокументированы). Сводный отчёт: `docs/audits/MATH_REAUDIT_2026_07.md`. Финальный gate: tools 1662 passed / sidecar 379 / math_correctness 156/156 / posterior_ci 82/82 / svelte-check 0 ошибок. **Ждёт Антона:** решение по push ветки `feat/econ-math-audit` (12 коммитов) + приоритезация OPP-01..08. Heartbeat снят (работа выполнена).
- **Ветка:** `feat/econ-math-audit` (от `feat/design-adopt-hybrid-ds` @ 9054f7f)
- **Safety-тег:** `v-pre-math-reaudit`
- **Среда (0.1 ✅):** глобальный Python 3.12.10 (`C:\Users\ackol\AppData\Local\Programs\Python\Python312`); pymc 5.28.4 / arviz 0.23.4 / numpy 2.4.2 / scipy 1.17.1 / pandas 3.0.1 / jax 0.7.2 + numpyro 0.20.1 / pytest+xdist. g++ НЕТ (pytensor.cxx='') → **режим аудита = Tier-1 NUTS via JAX** (Tier-2 PyTensor-NUTS будет медленный Python-mode). Реальные данные ЕСТЬ: `D:\Docs\Aurora_Ai\TestData\Econometrica` (Kagocel_RF, Venarus, MMX_2021-2025, Planning) → requires_real_data тесты работают.
- **Фикстуры:** conftest.py даёт session-scoped `synthetic_trained_project` (v1.2, 5 каналов, 200 samples, БЕЗ MCMC) + `kagocel_pathology_project` (v1.3 hierarchical, TRP native+money, mROAS-асимметрия) — готовые для зондов decompose/optimize/inverse. NB: pytest collect_ignore: test_math_correctness.py, test_posterior_ci.py, test_roi_verdict.py, test_narrative_adapter.py и causal-m* — standalone-скрипты, гонять `python tools/test_X.py` отдельно.
- **Отчёт:** `docs/MATH_AUDIT_v2_1_CORE_REAUDIT.md` [не создан]
- **Коммиты аудита:** узкий pathspec `sidecar/econometrica/** docs/** tools/** AUTONOMOUS_WORK_STATE_MATH_AUDIT.md`. Чужой untracked `src-tauri/src/commands/model_backend.rs` НЕ трогать.

## Реестр находок (дедуп 4 разведчиков + личное чтение; класс: BUG / METHOD-GAP / TRADEOFF / FALSE / ?)

### P0 — математика/оптимизация
| ID | Где | Гипотеза | Класс | Verify | Fix |
|---|---|---|---|---|---|
| F-01 | optimize/inverse.py | ✅ ЗАКРЫТА. Подтверждена зондом (B*=3.3×, все 5 каналов 2.1–2.3× исторического max, маркера нет) + UI-слой: правка 2026-06-07 сделала corridorHi=achievableCeiling (потолок модели при 5× бюджете) → зелёная зона закрашивала глубокую экстраполяцию, подсказка обещала обратное. FIX: `extrapolation_reporter` в meta (канонические тиры p95/p99 через forecast_validation.extrapolation_severity на per-period тратах vs история; Chan&Perry 2017 Fig.2) + `result['extrapolation']` + UI-бейдж (warn/danger) + развязка corridorHi(observed)/sliderMax(ceiling) | METHOD-GAP/INV-50 | ✅ зонд | ✅ FIX+тесты |
| F-02 | optimize/inverse.py | ✅ ЗАКРЫТА. Подтверждена зондом: narrow(sd 0.05)/wide(sd 0.45) → одинаковые 12.80% отн. ширины (ratio 1.00) — CI=константа 1.28δ. FIX: `posterior_sampler` в meta (per-sample S(B) через evaluate_flat_allocation_response — SSOT формулы, I8; включая intercept-разброс; epistemic без σ_obs) → правильный delta: sd(B)=z₀.₉·sd_post(S)/|grad|, method='delta_posterior' (Gelman Bayesian Workflow: неопределённость из posterior-симуляций). Fallback 'delta' для OLS/legacy сохранён. + `capped`-флаг (упор в cap 50% = плоская зона → баннер насыщения) | BUG+METHOD | ✅ зонд | ✅ FIX+тесты |
| F-03 | optimize/inverse.py | ✅ ЗАКРЫТА. Подтверждена зондом: p_hit≈0.500 ВСЕГДА (бисекция останавливается на S(B*)≈target → z≈0). FIX: p_hit = доля posterior draws ≥ цели (те же samples), `p_hit_method: posterior/heuristic`. NB: на самом B* доля ~0.5 by construction (медиана у цели) — честно; настоящая ценность p_hit — при maxBudget-капе и в будущем «бюджет под P=80%» (→ OPP-02) | METHOD | ✅ зонд | ✅ FIX+тесты |
| F-04 | engines/scenario.py | ✅ ЗАКРЫТА. Уточнение: machinery существовала (extrapolation_severity + endpoint /compute/forecast-scaling ~12ms), но НЕ ДОСТАВЛЕНА (endpoint не вызывается фронтом нигде — мёртв; движок план не помечал). FIX: predict_scenario сам возвращает `extrapolation:{severity,channels[]}` (пик per-period плана vs p95/p99 истории; Chan&Perry 2017 Fig.2) + UI ScenarioCompare (warn-плашка у слайдера + суффикс в статусе загрузки медиаплана). Мёртвый endpoint — кандидат в OPP (снести или подключить) | BUG-wiring/INV-50 | ✅ код+grep | ✅ FIX+3 теста |
| F-05 | engines/optimizer.py + MATH_REFERENCE | ✅ ЗАКРЫТА (verify+doc-fix): CI на сплит НЕ реализован; хуже — MATH_REFERENCE H11 описывал «full per-draw + UI toggle» как существующие (grep: их нет) — док-дрейф. FIX: честный Status-блок в MATH_REFERENCE (дизайн ≠ реализация); сама фича CI-на-сплит (~1000 SLSQP) — крупная, → OPP-04 | METHOD-GAP+DOC-DRIFT | ✅ grep | ✅ doc-fix, фича→OPP-04 |
| F-06 | sensitivity.py + tooltip-texts.js | ✅ ЗАКРЫТА. Хуже гипотезы: tooltip UI говорил «±10%», движок считает ±20% (_VARIATION_DEFAULT=0.20) — ЧИСЛО ВРАЛО. FIX: подписи ±20% + явно «детерминированный стресс-тест устойчивости, не статистическая неопределённость». Posterior-вариант sensitivity → OPP (не переделываем — стресс-подход валиден при честной подписи) | METHOD/INV-50 | ✅ код | ✅ FIX |
| F-07 | utils/adstock.py | ✅ ЗАКРЫТА (набл.): подтверждён тихий geometric-fallback для любого неизвестного типа ('Weibull'/'weibul'/мусор). FIX: однократный warning-лог на процесс per тип; ЧИСЛА НЕ ТРОНУТЫ (детерминизм I4/D13 цел, fallback сохранён — back-compat) | BUG (observability) | ✅ код | ✅ FIX |
| F-08 | utils/adstock.py | ✅ ЗАКРЫТА (набл.): weights.sum()==0 (underflow экстрем. shape/scale) уходил в convolve молча → канал ~нулевой без следа. FIX: warning-лог; численное поведение сохранено | BUG (observability, low) | ✅ код | ✅ FIX |
| F-31 | ScenarioCompare.svelte | ✅ ЗАКРЫТА (BUG подтверждён боем): Rust — чистый прокси, множитель уходил как native-траты → «план» на 6₽ → predicted=голый baseline → **lift −21.6% при ползунке +15%** (честный: +1.9%) — слайдер показывал бред при любом положении. FIX: план = current_spend канала (из результата оптимизации) × множитель; без результата оптимизации — честная подсказка вместо мусора | BUG (UI what-if) | ✅ проба | ✅ FIX |
| F-28 | engines/modeler.py get_mcmc_params | ✅ ЗАКРЫТА (BUG качества): решал check_compiler(), но Tier-1 NUTS = numpyro/JAX, которому g++ не нужен → клиентская поставка с вендоренным JAX без g++ получала ложный даунгрейд 2×1000×500 (2 цепи вместо канонических 4 — Vehtari) + ложный ярлык sampler=Metropolis (ключ нигде не читается, Metropolis запрещён). FIX: критерий = JAX или компилятор → 4/2000/2000; урезка только для PyTensor Python-mode; ярлык честный NUTS | BUG (качество MCMC) | ✅ grep+код | ✅ FIX+4 теста |
| F-09 | utils/saturation.py | ✅ ЗАКРЫТА. Проба: hill(1e155,α=2)=NaN подтверждён (inf/inf); порог экстремальный (мусорный вход), NaN уплывал в JSON как null. FIX: overflow-предел hill→1.0 / hill'→0.0 во всех 4 вариантах; нормальный диапазон byte-exact (array_equal-тест), NaN-вход не маскируется; pin Кагоцела цел. deriv(x→0,α<1)→∞ = истинная математика C-shape (floor 1e-10 смягчает) и α<0 недостижим из Gamma-prior — задокументированы в MATH_REFERENCE как свойства, не баги | BUG (numerics, low-порог) | ✅ проба | ✅ FIX+5 тестов |
| F-10 | optimize/inverse.py | Покрытие тестами inverse в tools/ почти нет (только sidecar/tests/test_inverse_*) | ? GAP-тестов | — | — |

### P0 — статистика
| ID | Где | Гипотеза | Класс | Verify | Fix |
|---|---|---|---|---|---|
| F-11 | diagnostics/modeler/honesty | ✅ ЗАКРЫТА. Подтверждено: ESS нигде не был gate (MATH_REFERENCE декларировал WARN — код не знал; только tail_ess_ok per-channel без потребителя). FIX: modeler собирает min bulk/tail-ESS (β/α/γ/decay/intercept) → metrics+checks.ess (ключ только при измеренном; unknown≠pass) → honesty-gate uncertain с reason «<400, Vehtari et al. 2021, R-hat ненадёжен». RAG-верификация: Vehtari 2021 «recommended threshold of 400» поднята из корпуса. MQS не изменён | METHOD-GAP+DOC-DRIFT | ✅ grep+RAG | ✅ FIX+9 тестов |
| F-12 | то же | ✅ ЗАКРЫТА. E-BFMI отсутствовал вовсе. FIX: az.bfmi(trace) min по цепям (NUTS-only, ADVI→None) → checks.bfmi (порог 0.3 = эвристика Stan/PyMC, НЕ Betancourt — урок T3.10 соблюдён, тест проверяет отсутствие атрибуции Betancourt) → honesty uncertain + подсказка non-centered | METHOD-GAP | ✅ grep | ✅ FIX (в тех же 9) |
| F-13 | modeler/server/honesty | ✅ ЗАКРЫТА. Уточнение: prior predictive РЕАЛИЗОВАН (reliability_a4) и вызывался в /compute/preflight — но endpoint НЕ подключён к UI (Rust-команды нет; фронт зовёт train напрямую) — ВТОРОЙ недоставленный контур честности (после forecast-scaling). FIX: in-train preflight в modeler (quick_proxy + prior_predictive 300 samples до MCMC) → diagnostics['preflight'] → honesty-gate (fail→uncertain; warn→инфо). MATH_REFERENCE Status актуализирован. UX-гейт до кнопки → OPP-05. Атрибуция: McElreath, Gelman BW §5.10 (RAG) | BUG-wiring/INV-50 | ✅ grep+код | ✅ FIX+3 теста |
| F-14 | engines/modeler.py:470-509 | ✅ TRADEOFF (закрыта): fallback μ=0 НЕ молчит (logger.warning:507 «classification fallback... using uniform mu=0»); unknown-kind осознанно uninformative 0.0 (комментарий :498-500 «data will dominate»). Имя-based классификация — общее ограничение детекта (валидатор, Фаза 3 F-23-семейство) | TRADEOFF | ✅ код | — |
| F-15 | engines/decomposer.py:853 | ✅ FALSE: guard уже есть — `float(control_stds.get(c,1)) or 1` превращает 0.0→1 (falsy). NaN-хвост теоретический (в сохранённых training-stds NaN не бывает). Разведчик не заметил `or 1` | FALSE | ✅ код | — |
| F-16 | decomposer/optimizer mean | ✅ FALSE (покрыто): adstock_mean_posterior-консистентность train↔downstream пронизывает 8 тест-файлов (optimizer_invariants, kagocel_redistribution, persistence_phase2, brand_perf_integration...) — C1-фикс закреплён; legacy fallback задокументирован | FALSE | ✅ grep | — |
| F-17 | utils/ols_bootstrap.py:135-166 | ✅ FALSE: массивы фиксированной длины n_boot, индексация по boot_i (индекс цикла); LinAlgError→continue → presence_mask[boot_i] остаётся False → сэмпл корректно исключён из HDI (это и есть C-OLS-2 маска). Off-by-one нет | FALSE | ✅ код | — |
| F-18 | conformal + aurora_pptx/builder.py | ✅ ЗАКРЫТА. Движок отдаёт coverage_caveat (:245), но UI conformal не упоминает ВООБЩЕ; единственная точка для пользователя — PPTX-глоссарий — заявляла «с гарантией покрытия» (противоречие собственному F3-caveat) + «n=1000» (движок 200) + «95% CI» (движок 90% HDI). FIX b501708: глоссарий приведён к правде | INV-50 | ✅ grep+код | ✅ FIX |
| F-19 | decomposer count-KPI | ✅ TRADEOFF (задокументирована): kpi_unit_cost константен во времени — допущение ADR-021; строка в MATH_REFERENCE (media-инфляция обрабатывается, KPI-сторона — допущение) | TRADEOFF | ✅ код | ✅ doc |
| F-20 | engines/modeler.py:~975 | ✅ ЗАКРЫТА. Подтверждено: y_pred=zeros при сбое реконструкции → R²/MAPE от константы «выглядят как плохая модель» (причина только в логе). FIX: флаг y_pred_reconstruction_failed → diagnostics → honesty-вердикт unknown («качество не измерено», не «модель плохая») + понятный caveat | BUG (obs/honesty) | ✅ код | ✅ FIX+2 теста |

### P1-P2 — общая логика
| ID | Где | Гипотеза | Класс | Verify | Fix |
|---|---|---|---|---|---|
| F-21 | server.py | ✅ ЗАКРЫТА (гипотеза разведчика частично ложна): consumed_at СТАВИТСЯ в /train/result (:1096, C3) — но терминальные задачи, чей result никто не забрал (error/cancelled/брошенные), жили вечно с полным result в памяти. FIX: _cleanup_stale_training_tasks — второй критерий (терминальные без consumed_at >60 мин); running не трогаем | BUG (остаточная утечка) | ✅ код | ✅ FIX+3 теста |
| F-22 | server.py train lifecycle | ✅ FALSE/TRADEOFF: «потеря result» не теряет модель (она на диске: latest.pkl+diagnostics; пайплайн читает pickle); cancel-не-прерывает-MCMC задокументирован в docstring (:1076). Расход CPU на брошенное обучение → OPP (graceful-прерывание PyMC/numpyro нетривиально) | FALSE/TRADEOFF | ✅ код | — |
| F-23 | engines/validator.py | ✅ TRADEOFF: warning-не-блок = осознанный advisory-UX; жёсткая честность живёт в optimizer_honesty (thin→uncertain, INV-50) и MQS thinness-cap. Канон «4:1 минимум» доносится, но не запирает пользователя | TRADEOFF | ✅ код | — |
| F-24 | utils/canonical_hash.py | ✅ TRADEOFF: datetime → явный CanonicalizationError «unsupported type» (проба) — информативное исключение ЛУЧШЕ тихого fallback; потребитель (project_migration) строит JSON-safe payload by construction | TRADEOFF | ✅ проба | — |
| F-26 | engines/awareness.py | ✅ ЗАКРЫТА. Аудит vs канон: AR(1)-структура (decay×aw[t-1]+impact×spend) — компактный MVP (перенос через лаговое awareness); S-кривая awareness→sales с порогом/насыщением есть. Дефекты: (а) «CI» = std×0.5 КОНСТАНТА (прогноз на 12 периодов «уверен» как на 1) → FIX: честный прогнозный интервал AR(1) var[h]=σ²·Σdecay^2i, 90%, растёт с горизонтом, сходится к асимптоте; (б) ESOV-модуль (Binet&Field: SOM growth≈0.05×ESOV — RAG-корпус) отсутствует → OPP-07; (в) Weibull-хвост медиа→awareness отсутствует (AR(1) частично компенсирует) → OPP-07 | METHOD (CI) + GAP (ESOV) | ✅ код+RAG | ✅ FIX CI + 2 теста; ESOV→OPP |
| F-25 | utils/file_lock.py | ✅ FALSE: проба двух потоков через project_lock — строго сериализованы (A-in,A-out,B-in,B-out), deadlock/гонки нет | FALSE | ✅ проба | — |
| F-27 | граница сайдкар↔Rust | ✅ verify: sanitize_nonfinite покрыт tests (NaN/Inf→null, nested, numpy types); serde_json f64 roundtrip без потерь; рискованные поля (per-period CI) уже проходят sanitize (scenario:790, decomposer:1178). Контракт держится | OK (покрыто) | ✅ тесты | — |

### Реестр возможностей (OPP — поручение Антона 2026-07-02: эффективнее/надёжнее/стабильнее/удобнее; НЕ дефекты — рекомендации, вернуться к Антону по итогам)
| ID | Область | Идея | Эффект |
|---|---|---|---|
| OPP-01 | Надёжность CI | Зафиксировать `-n 4` (или `--dist worksteal` + лимит) в pytest.ini addopts: `-n auto`=24 воркера на Windows ловит гонку загрузки jaxlib-DLL → флаки-развал прогона (наблюдён боем) | Стабильный CI-прогон |
| OPP-02 | Продукт/UX Goal-Seek | «Бюджет под заданную вероятность»: сейчас B* = медианный бюджет (p_hit≈50% by construction). Квантильная бисекция по posterior-samples → «бюджет, при котором цель достигается с вероятностью 80%» — прямой ответ CFO, дифференциатор. Механика уже готова (posterior_sampler) | Сильная продуктовая фича на готовой механике |
| OPP-03 | UX честности | Единый язык extrapolation-тиров 0-3 по всем вкладкам: маркер теперь у goal-seek и сценариев (движок); endpoint /compute/forecast-scaling МЁРТВ (фронт не вызывает — снести или подключить к forward-оптимизации); богатая compare-страница сценариев бейдж пока не показывает | Единый язык честности |
| OPP-04 | Методология | CI на оптимальный СПЛИТ долей (канон Jin 2017: «доля A 38% [27-46%]», при перекрытии CI — «разница не выделяется»): full per-draw оптимизация (~1000 SLSQP или дешевле — reoptimize на подвыборке 50-100 draws). H11-дизайн уже описан в MATH_REFERENCE; после аудита — оценить стоимость и ценность с Антоном | Канон-полнота ключевой рекомендации |
| OPP-05 | UX честности | Подключить полноценный preflight-гейт ДО кнопки «Обучить»: endpoint /compute/preflight готов (S1), Rust-команды нет; in-train вариант (F-13) доносит постфактум — UX-гейт даст «предупредить до», с overrideable-баннером | Доставка S1-moat пользователю |
| OPP-06 | Стабильность | Graceful-остановка MCMC при cancel: сейчас поток дорабатывает вхолостую (документировано); numpyro прерывание нетривиально — вариант: chunked-сэмплирование или процесс-уровень kill по task_id | Экономия CPU/батареи на брошенных обучениях |
| OPP-07 | Методология awareness | Довести awareness-движок до канона кабинета: ESOV-модуль (Binet&Field: рост SOM ≈ 0.05×ESOV/год, в digital-эру сильнее — корпус), Weibull-хвост медиа→awareness (строится медленно), CI на эластичность S-кривой (pcov из curve_fit уже доступен) | Канон-полнота awareness-контура |
| OPP-08 | Чистка | Мёртвые endpoint'ы: /compute/forecast-scaling и /compute/preflight не вызываются фронтом (Rust-команд нет) — либо подключить (OPP-03/05), либо снести с доков; сейчас вводят в заблуждение при чтении кода | Меньше ложных якорей в кодовой базе |

### Закрыто в ходе аудита
| ID | Где | Что | Класс | Статус |
|---|---|---|---|---|
| F-29 | tools/test_priors_calibration.py | Дрейф тест-инфраструктуры: файл написан под СТАРУЮ схему synthetic_pilot_data (GROUND_TRUTH_RETAIL→RETAIL_ECOM, generate_retail_chain→retail_ecom, holiday_newyear_preshop→holiday_newyear, apteka_ooh_ots→_contacts, real_estate q1/q4-колонки→baked+дамми из дат) → ImportError → **весь набор калибровки priors молча не гонялся**. Плюс 3 стухших абсолютных допуска (scale-фактор y-нормализации ~2-3× документирован в самом файле; ratio-проверка: comp −0.4533≈2.06×GT, weather 0.3015≈2.5×GT — recovery верный с точностью до масштаба) → приведены к паттерну «знак+bounded+R²» как у FMCG-competitor. | BUG (test-infra) | ✅ FIX, 11/11 passed |
| F-30 | pytest -n auto | 24 xdist-воркера на Windows → гонка загрузки jaxlib-DLL (OSError у части воркеров, «different tests collected») → флаки-развал прогона. Мит: `-n 4`. | ИНЖ (CI-грабля) | ✅ workaround, кандидат в OPP (зафиксировать -n в pytest.ini addopts) |

### Отброшено разведчиками ошибочно / уже покрыто (НЕ переоткрывать)
- ~~сумма декомпозиции ≈ продажам не проверяется~~ → **FALSE**: D1 energy conservation (residual absorption) + test_D1 ×15 seeds.
- ~~ROI без CI~~ → **FALSE** для v1.2+: D12 + test_posterior_ci; для v1.0/1.1 — задокументированная compat-таблица.
- ~~нет тестов scenario/sensitivity~~ → **частично FALSE**: tools/test_scenario_invariants.py, test_scenario_edge_cases.py существуют (разведчик смотрел не туда). Sensitivity — проверить.
- ~~mROAS формула~~ → I6 chain rule ×50 combos покрыт.
- ~~Metropolis-fallback опасен~~ → **TRADEOFF задокументирован**: modeler.py:691-695 «Metropolis НЕ используется как Tier-3» — честный fail MMM_SAMPLER_EXHAUSTED. Windows-режим 2×1000×500 (get_mcmc_params:127) — verify, применяется ли вообще.

## СДЕЛАНО
- 2026-07-02: План одобрен (2 раунда самоаудита R1+R2). Ветка `feat/econ-math-audit` + тег `v-pre-math-reaudit`. Реестр собран (27 гипотез + F-28..30 по ходу).
- Фаза 0 ✅: флаг в MEMORY.md; среда (Tier-1 NUTS/JAX, реальные данные ЕСТЬ); критерии прочитаны (MATH_REFERENCE — НЕ создавать новых MATH_AUDIT_v*.md, отчёт → docs/audits/ + правки мат-истины → MATH_REFERENCE); baseline 1623 passed после починки F-29 (коммит `b788041`).
- **F-29 ✅** (дрейф test_priors_calibration — набор молча выключен) — коммит `b788041`.
- **Батч «goal-seek honesty» ✅ (F-01+F-02+F-03):** зонд tmp/probe_inverse_f01_f02.py доказал все три числом (12.80%=12.80%, p_hit≡0.5, 5 каналов 2.1-2.3× max без пометки) → правки inverse.py (posterior_sampler/extrapolation_reporter в meta; delta_posterior CI; честный p_hit; capped→баннер) + UI (развязка corridorHi/sliderMax; бейдж экстраполяции; methodLabel) + tools/test_goalseek_honesty.py (9 тестов). RAG-атрибуции: Chan&Perry 2017 Fig.2, Gelman Bayesian Workflow. Гейт: 1632 passed/0 failed, svelte-check 0 ошибок, 15 контрактных sidecar-тестов inverse зелёные.

## ОСТАЛОСЬ (next actions, по порядку)
✅ **Фаза 2 ЗАКРЫТА ЦЕЛИКОМ** (F-06/11/12/13/14/15/16/17/18/19/20 — статусы в реестре; канарейки decompose зелёные: D1 live gap=0.000%, ROI=contribution/spend, доли 100/100 — tmp/probe_canary_decompose.py).
3. **Фаза 3:** ✅ ЗАКРЫТА кроме F-26 (батч №9 `023d338`: F-21 FIX-утечка, F-28 FIX-ложный MCMC-даунгрейд без g++, F-31 FIX-слайдер-бред; F-22/23/24/25/27 — FALSE/TRADEOFF/OK с пробами). **Остаток: F-26 awareness-методология** (engines/awareness.py: ESOV Binet&Field, natural decay, лаг, S-кривая vs канон; RAG-запрос «избыточная доля голоса ESOV excess share of voice Binet Field advertising effectiveness»).
4. **Фаза 4 (финал):** (а) F-26 → закрыть; (б) OPP-05/06 дозаписать (недоставленный /compute/preflight UX-гейт; graceful-прерывание MCMC при cancel); (в) отчёт `docs/audits/MATH_REAUDIT_2026_07.md` — свод: 31 находка (статусы из реестра), классы, коммиты b788041..HEAD, RAG-атрибуции, FALSE-разоблачения; (г) раздел «Рекомендации Антону» из OPP-01..06; (д) полный gate `pytest tools/ -m "not slow and not integration and not requires_real_data" -n 4` + standalone `python tools/test_math_correctness.py` + `python tools/test_posterior_ci.py`; (е) пополнить реестры инвариантов (GS-инвариант honesty? extrapolation-маркер как инвариант S15/GS1) — по формату registry; (ж) сводка Антону + снять вопрос про push (ветка не запушена!).

## Грабли и решения
- pytest гнать из корня `Dev/Aurora_Econometrica` (pytest.ini: testpaths=tools). В tools/ свой conftest — проверить sys.path к sidecar/econometrica.
- Правки БЕЗ слома pickle-compat (1.0/1.0-ols/1.1/1.1.5/1.2/1.3) и детерминизма (I4/D13).
- Guard экстраполяции — мягкий (пометка+CI), не блокирующий.
- pin Кагоцел: если методологическая правка легитимно меняет число — переустановить pin С ОБОСНОВАНИЕМ (правка+первоисточник), не подгонять молча.
- Два режима движка (planning Option C / analyst Hill-of-mean) — правки проверять в обоих.

## Аудит-чеклист финала
- [ ] Все 27 находок реестра имеют класс + verify-статус (нет «?»)
- [ ] Все BUG/METHOD-GAP исправлены ИЛИ осознанно отложены с записью причины
- [ ] Методологические правки — с RAG-атрибуцией (или честный [ASSUMED] fallback)
- [ ] Каждая правка — характеризующий тест в tools/
- [ ] Реестры инвариантов пополнены (формат statement/rationale/test)
- [ ] Полный `pytest tools/ -n auto` зелёный; pin Кагоцел объяснён
- [ ] Smoke пайплайна на фикстуре в двух режимах
- [ ] Отчёт Антону: находки/правки/атрибуции/остаточные риски + раздел «Рекомендации» (OPP)
