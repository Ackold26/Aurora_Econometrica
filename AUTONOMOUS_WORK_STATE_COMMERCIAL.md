# АВТОНОМНАЯ РАБОТА: коммерческая готовность MMM Optimizer (волны аудита + OPP)

> **SSOT прогресса этапа.** Задание и полный контекст задач — `NEXT_SESSION_commercial_readiness.md` (читать при восстановлении).
> Протокол восстановления после компрессии/обрыва: прочитать этот файл + промт-файл → продолжить с «ОСТАЛОСЬ» БЕЗ переспроса.
> Развилки тактические решать самой; методология — с RAG-атрибуцией (`lib_vec.py search`, двуязычный запрос).
> 🫀 **HEARTBEAT (мандат Антона 2026-07-03):** в конце каждого хода — `ScheduleWakeup(600, prompt=промт из шапки NEXT_SESSION_commercial_readiness.md)`. Мандат: максимально автономно, технические развилки решать самой (глубокое обдумывание, трудозатраты↔эффект, влияние на работоспособность/стабильность), найти и устранить все ошибки и недостатки; идеи улучшений (эффективность/надёжность/удобство) копить в «Предложения Антону» и принести в конце. Снять по слову Антона.
> Метод: **число — валюта доверия · первый дефект класса — линза · батч умирает в пределах хода** (совет мат-аудита).

## 🔬 МИКРОСТАТУС (обновлять при каждом незакоммиченном изменении!)
- Батч №5 = B1-fix-2 ГОТОВ (закрыты R-09, R-12, R-13, R-14; R-15/R-18 = FALSE/OK verify): timeline-headline и SCQAR-рекомендации 02/03 больше не выдумывают («пульсирующее -15-20%», «ретаргетинг по сегментам» → контроль насыщения / снятие неопределённости / сверка прогноза с фактом); «X% продаж» → «X% медиа-вклада» (finding-01 + divider); SCQAR ПРОБЛЕМА↔ВОПРОС↔ОТВЕТ согласованы по фактам (binding/lift<0.5 → честные хвосты); «+0/+0.0 пп» → «Незначим (<0.5 пп)»; finding-04 честен при Uncertain-вердиктах; scqar-headline «Снять неопределённость перед ре-аллокацией» при большинстве Uncertain; «mROAS устойчив» только при ci_low≥1; колофон без «уровня ведущих консалтинговых групп»; склонение каналов. Канарейка +6 запрет-маркеров. Живой Kagocel: все запреты 0, новый нарратив доставлен. Gate: tools 1680 / sidecar 379 / narrative 65/65 / svelte 0. КОММИТ СЛЕДУЮЩИМ ШАГОМ.
- R-15 = OK (пороги 1.01/0.7 — канон Vehtari/индустрии как «целевое», продуктовый refuse 1.05 не противоречит). R-18 = FALSE (65.1 = реальный mroi_current 65.0622, честно; CI совпал с 90% HDI).
- Батч №7 = XLSX-глоссарий (Rust report.rs :1615) «CI (95%)»→«CI (90% HDI)» — последняя точка семейства R-07. Markdown-отчёт Rust был честен (90% :375, приоры 0.3/Gamma(5,3) = факт modeler); scenario-export.js честен (CI 90%). **B1 ЗАКРЫТА ЦЕЛИКОМ** (3 формата + 2 бонусных проверены). Rust 165 passed. КОММИТ СЛЕДУЮЩИМ ШАГОМ.
- Батч №8 = OPP-05 ГОТОВ: Rust `econ_preflight` (post /compute/preflight, train_client) + регистрация lib.rs + UI-гейт в ConfigPanel.trainModel (перед train_start; fail-open при сбое гейта — страховка F-13 остаётся) + баннер warn/danger с warnings/recommendation + «Обучить всё равно» (overrideable) / «Изменить настройки». Кнопка теперь onclick={() => trainModel(false)} (MouseEvent-ловушка обойдена, строгое === true). Живой зонд на Kagocel: 0.4с, tier=insufficient (coverage 42% fail), все поля для UI на месте. Gate: rust 165 / svelte 0 ошибок. КОММИТ СЛЕДУЮЩИМ ШАГОМ.
- Следующее: OPP-03 (единый язык extrapolation-тиров на forward-оптимизации: optimizer.py per-period vs p95/p99 + UI бейдж; compare-страница сценариев: бейдж из сохранённого поля) → OPP-08 (forecast-scaling: Rust-команда есть (:3279), проверить фронт — подключить к forward или снести).

## Шапка
- **Статус: 🟡 В РАБОТЕ (старт 2026-07-03).**
- **Ветка:** `feat/econ-commercial-readiness` (от `feat/econ-math-audit` @ 10e14fb)
- **База:** мат-аудит завершён (31 находка, отчёт `docs/audits/MATH_REAUDIT_2026_07.md`); математику ядра повторно НЕ аудировать. Компас: класс «вычисленная, но не доставленная честность».
- **Среда:** Python 3.12 глобальный; pymc 5.28.4 / jax 0.7.2 / numpyro 0.20.1; g++ НЕТ (NUTS через JAX). Реальные данные: `D:\Docs\Aurora_Ai\TestData\Econometrica` (Kagocel_RF 31×34, `\n` в заголовках!).
- **Базлайн зелёный:** tools 1662 / sidecar 379 / standalone 156+82 / svelte 0 / cargo 48.
- **Команды:** tools: `python -m pytest tools/ -m "not slow and not integration and not requires_real_data" -q` (воркеры теперь в ini); sidecar: `python -m pytest sidecar/econometrica/tests/ -q`; standalone: `python tools/test_math_correctness.py` (156), `python tools/test_posterior_ci.py` (82); svelte: `npm run check`; rust: `CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" cargo test`. Живой gate: по образцу `tmp/probe_live_kagocel_audit.py` (mcmc_override chains 2 / draws 600 / tune 600 NUTS, ~3 сек).
- **Коммиты:** узкий pathspec `sidecar/econometrica/** src/** src-tauri/** docs/** tools/** pytest.ini AUTONOMOUS_WORK_STATE_COMMERCIAL.md`. Чужие untracked НЕ трогать: `src-tauri/src/commands/model_backend.rs`, `CC-Sessions/*`, `Projects/*`, `src/app.css.bak-*`, `tmp/*` (кроме своих зондов — их не коммитить).
- **Грабли:** commit из PowerShell — here-string `@'...'@` без прямых двойных кавычек внутри; rg без lookahead; `decompose(project_dir)` — строка; `res['channels']` — list; `predict_scenario(config, project_dir)`, план в native units, single value = TOTAL.

## Реестр задач (id, суть, статус; полные ТЗ — в NEXT_SESSION_commercial_readiness.md)

### Блок A — OPP-реализация
| ID | Суть | Статус | Verify | Fix |
|---|---|---|---|---|
| A1 | OPP-01 стабильный прогон: воркеры в pytest.ini | ✅ ЗАКРЫТА (4572c8d) | 3×(tools 1662 + sidecar 379) зелёные; -n 0 override жив | -n 4 --dist worksteal в addopts |
| A2 | OPP-02 ⭐ «бюджет под P=80%» (квантильная бисекция на posterior_sampler) | ✅ ЗАКРЫТА | зонд tmp/probe_a2_sampler_cost.py (12-15мс/вызов, бисекция 163мс, q20 монотонен, narrow +5.8%/wide +86.1%, p_hit=0.800) + живой Kagocel (+83.8%, все PASS) | движок confidence-kwarg + server + Rust Option<f64> + UI сегмент-переключатель + карточка (label/медианный прогноз/unavailable-плашка/fallback с процентом) + 12 тестов test_goalseek_confidence.py |
| A3 | OPP-05+03+08 пакет «доставка честности» (preflight до кнопки / язык тиров на forward+compare / forecast-scaling подключить-или-снести) | ⬜ | — | — |
| A4 | OPP-04 CI на оптимальный сплит (subsample SLSQP, Jin 2017) | ⬜ | — | — |
| A5 | OPP-07 awareness до канона (ESOV Binet&Field / Weibull-хвост / CI эластичности) | ⬜ | — | — |
| A6 | OPP-06 мягкая остановка MCMC (последний приоритет, не трогать без боли) | ⬜ | — | — |

### Блок B — Волна 1 «деньги и лицо» 🔴
| ID | Суть | Статус | Verify | Fix |
|---|---|---|---|---|
| B1 | Репортинг-канарейка: каждое ЧИСЛО отчёта (pptx/html/xlsx) ↔ JSON движка; каждый CLAIM ↔ фактический метод; honesty-поля доставлены | ✅ ЗАКРЫТА (батчи №3-7: ebce61f, 0ab3ad3, 7f0af9f, dcf25a7, +XLSX) | зонд на реальном Kagocel ×3 прогона + sources.json сверка + код-верификация всех 18 находок; канарейка 8 тестов (31 запрет-маркер, PPTX+HTML) | PPTX 16/18 fix (2 FALSE/OK verify) + HTML то же семейство + XLSX-глоссарий 90% HDI; markdown и scenario-export были честны |

#### B1-R: реестр находок PPTX (зонд 2026-07-03, все верифицированы кодом)
| ID | Где (builder.py / adapter) | Суть | Класс |
|---|---|---|---|
| R-01 | :260 + narrative_adapter (ess_min) | ESS в отчёте = wireframe-дефолт **1247**; реальные ess_bulk_min=590.7 / ess_tail_min=**382.7 (<400 Vehtari!)** не доставлены — маппер ищет metrics.ess_min, которого нет после F-11 (перименованы). Реальная проблема сходимости замаскирована выдуманным числом | LIE-BY-DEFAULT 🔴 |
| R-02 | :199-201 + маппер | period_label='Q1 2026' / data_window_label='W01 W13 2026' / forecast='Q3-Q4 2026' — wireframe на ЛЮБОМ живом отчёте (адаптер не передаёт), при реальном периоде 2023-01..2025-07 в time_series.dates (слайд 9 показывает правильный → внутреннее противоречие отчёта) | LIE-BY-DEFAULT 🔴 |
| R-03 | :2832 | «Наблюдений» = active_count×13 (=52) — выдуманная арифметика; реально len(dates)=31 | FABRICATED-MATH 🔴 |
| R-04 | :2834-2835 | «Частота: Еженедельно (Пн-Вс)» (данные месячные!), «Полнота: 100% (0 пропусков)» — hardcode; вычислимы из dates | FABRICATION 🔴 |
| R-05 | :2873, :2895+ | PRIMARY/SECONDARY источники: Mediascope TV / Yandex.Metrica / GA / VK Ads / бренд-трекер — выдуманы целиком; клиент таких данных не давал | FABRICATION 🔴 |
| R-06 | :2725/:2733 | «Приоры: 12+ FMCG-проектов Aurora (2024-2026)» — недоказуемое заявление (INV-50) | UNSUPPORTED-CLAIM |
| R-07 | :2026-2028, :2988 | Подписи «доверительный интервал 95%» / «bootstrap CI 95%» / глоссарий «CI (95%)» против фактических **90% HDI** (DEFAULT_HDI_PROB=0.9; OLS bootstrap hdi_prob=0.9) — семейство F-18, не догрепанное правкой b501708 | METHOD-LIE 🔴 |
| R-08 | s10 :~2650 | Спецификация «β_i ~ HalfNormal(0.5)» — устаревший приор (факт: 0.3 с 2026-04-19; hierarchical 0.7/0.3/mixed) | DOC-DRIFT |
| R-09 | :2485, :2488, :2501, :2047 | Рекомендации «Пульсирующее размещение — экономия 15-20% без потери охвата», «Целевой ретаргетинг (сегменты / W25-54 CTV/OLV)» — выдуманные советы с числами; модель flighting/сегменты НЕ вычисляет | FABRICATED-RECO 🔴 |
| R-10 | :3069 | «Следующая волна анализа - через 90 дней» — шаблонное обещание | FABRICATION (low) |
| R-11 | s02 | «Время ~12 мин / Слов ~2 800» — декоративный hardcode | COSMETIC (low) |
| R-12 | s03/s06 findings | «Social - 32% продаж при 6% бюджета» БЕЗ квалификатора: 32% = доля в МЕДИА-вкладе (38% продаж) → реально 12% продаж; honest_narrative-гейт только <10% медиа-доли; слайд 4 с квалификатором «инкрементальных» честен — findings нет | MISLEADING 🔴 |
| R-13 | s09 SCQAR | ПРОБЛЕМА «Banners 44% бюджета / 23% эффекта. Требует перебалансировки» ↔ ОТВЕТ «Сохранить текущую аллокацию» при lift=0 — противоречие; binding_constraints=True в facts есть, шаблон игнорирует | NARRATIVE-BUG |
| R-14 | s02 находка 04 | «ни одного канала к росту/сокращению» + «чёткая рекомендация по каждому» при ВСЕХ вердиктах Uncertain | NARRATIVE-BUG |
| R-15 | глоссарий :2965+ | «R² целевое >0.7» / «R-hat ≤1.01» — сверить с фактическими гейтами MQS/honesty | VERIFY |
| R-16 | маппер | honesty-вердикт модели и preflight (в зонде: prior_predictive=FAIL coverage 42%!) в отчёт НЕ доставлены вовсе — отчёт молчит о ненадёжности | HONESTY-GAP 🔴 |
| R-17 | :~2836 | «Аномалии: обработаны (праздничные недели)» — hardcode | FABRICATION |
| R-18 | :841 _build_action_table_rows | mROAS средняя точка 65.1 в таблице — источник поля сверить (CI совпал с mroi_current_ci 90% HDI) | VERIFY |
| B2 | Лицензии: матрица сценариев боем (стенд), #61 offline-smoke закрыть | ⬜ | — | — |
| B3 | Обновления: цепочка публикация→манифест→доставка→установка→откат | ⬜ | — | — |

### Блок C — Волна 2 «первый день клиента» 🟠
| ID | Суть | Статус | Verify | Fix |
|---|---|---|---|---|
| C1 | Импорт грязных xlsx (коллекция мутаций реальных файлов → понятные сообщения) | ⬜ | — | — |
| C2 | Chaos: крах в MCMC / диск полон / антивирус / OneDrive / два окна / сон | ⬜ | — | — |
| C3 | Прицельный click-path по местам правок мат-аудита (tauri:dev + MCP-мост, AVT) | ⬜ | — | — |

### Блок D — Волна 3 «поставка и обещания» 🟡
| ID | Суть | Статус | Verify | Fix |
|---|---|---|---|---|
| D1 | «0 egress» локальной редакции — доказать сниффером, протокол для сейлов | ⬜ | — | — |
| D2 | Двухредакционная упаковка (identifier коллизия) — согласовать с выдачей лицензий | ⬜ | — | — |
| D3 | Безопасность дистрибутива (NSIS, capabilities/IPC, CSP, секреты) | ⬜ | — | — |
| D4 | Перф на 8 ГБ ноутбуке + NOTICE лицензий третьих сторон | ⬜ | — | — |

## ПОРЯДОК
A1 → A2⭐ → B1 → A3 → B2 → B3 → C1→C2→C3 → D1→D2→D3→D4 → A4, A5, A6. Каждый пункт = durable-батч с коммитом; после каждого блока — живой gate Kagocel + полный pytest.

## СДЕЛАНО
- (2026-07-03) Ветка `feat/econ-commercial-readiness` создана от feat/econ-math-audit @ 10e14fb. Реестр заведён.
- (2026-07-03) **Батч №1 = A1 OPP-01 (4572c8d):** pytest.ini addopts += `-n 4 --dist worksteal`; 3× полных прогона зелёные (tools 1662 ×3: 23/34/32с; sidecar 379 ×3: 9/10/12с — sidecar тоже параллелится без флака); `-n 0` переопределение живо. MEMORY.md: флаг автономки обновлён (переживает компрессию).

## ОСТАЛОСЬ
1. B1 репортинг-канарейка: каждое ЧИСЛО отчёта (pptx/html/xlsx) ↔ JSON движка; каждый CLAIM narrative_adapter ↔ фактический метод; honesty-поля мат-аудита (extrapolation, delta_posterior, p_hit_method, capped, preflight, ci_method awareness, + новое confidence A2) — доставлены или осознанно исключены (решение записать).
2. Дальше по ПОРЯДКУ (A3 → B2 → B3 → C → D → A4-A6).

## Предложения Антону (копить по ходу, принести в конце)
- (пока нет)

## Решения, ждущие Антона
- (пока нет)
