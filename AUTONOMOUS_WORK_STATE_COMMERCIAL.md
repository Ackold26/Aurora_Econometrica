# АВТОНОМНАЯ РАБОТА: коммерческая готовность MMM Optimizer (волны аудита + OPP)

> **SSOT прогресса этапа.** Задание и полный контекст задач — `NEXT_SESSION_commercial_readiness.md` (читать при восстановлении).
> Протокол восстановления после компрессии/обрыва: прочитать этот файл + промт-файл → продолжить с «ОСТАЛОСЬ» БЕЗ переспроса.
> Развилки тактические решать самой; методология — с RAG-атрибуцией (`lib_vec.py search`, двуязычный запрос).
> 🫀 **HEARTBEAT (мандат Антона 2026-07-03):** в конце каждого хода — `ScheduleWakeup(600, prompt=промт из шапки NEXT_SESSION_commercial_readiness.md)`. Мандат: максимально автономно, технические развилки решать самой (глубокое обдумывание, трудозатраты↔эффект, влияние на работоспособность/стабильность), найти и устранить все ошибки и недостатки; идеи улучшений (эффективность/надёжность/удобство) копить в «Предложения Антону» и принести в конце. Снять по слову Антона.
> Метод: **число — валюта доверия · первый дефект класса — линза · батч умирает в пределах хода** (совет мат-аудита).

## 🔬 МИКРОСТАТУС (обновлять при каждом незакоммиченном изменении!)
- Батч №2 (A2 OPP-02) ГОТОВ, коммит следующим шагом. Дальше: B1 репортинг-канарейка.

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
| B1 | Репортинг-канарейка: каждое ЧИСЛО отчёта (pptx/html/xlsx) ↔ JSON движка; каждый CLAIM ↔ фактический метод; honesty-поля доставлены | ⬜ | — | — |
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
