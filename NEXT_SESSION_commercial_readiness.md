# NEXT SESSION: MMM Optimizer — коммерческая готовность (волны аудита + OPP)

> **Промт запуска (вставить в новую сессию):** «Работаем по `Dev/Aurora_Econometrica/NEXT_SESSION_commercial_readiness.md`: прочитай файл целиком, заведи durable-реестр по образцу мат-аудита и веди работу автономно батчами по разделу ПОРЯДОК. Развилки тактические решай сама; методология — с RAG-атрибуцией; в конце каждого хода — ScheduleWakeup(900) с этим же промтом (страховка от обрывов). Стоп — по слову Антона.»

## Контекст (кто/что/где)

- **Продукт:** Aurora AI Econometrica / MMM Optimizer. Десктоп: Tauri v2 (Rust `src-tauri/`) + SvelteKit (`src/`, JS+JSDoc, НЕ TS) + Python-сайдкар (`sidecar/econometrica/`: FastAPI + PyMC/JAX). Цена 700 тыс. ₽/год, этап — первые пилоты. Репо: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`.
- **Сделано (2026-07-02):** мат-аудит ядра ЗАВЕРШЁН — 31 находка (18 FIX + 33 теста, 7 FALSE, 6 TRADEOFF), ветка **`feat/econ-math-audit` запушена** (b788041..ba05bf0), живой gate на реальном Kagocel зелёный. Отчёт: `docs/audits/MATH_REAUDIT_2026_07.md`; реестр: `AUTONOMOUS_WORK_STATE_MATH_AUDIT.md`; мат-истина: `docs/MATH_REFERENCE.md` (актуализирован). **Математику ядра повторно НЕ аудировать.**
- **Сквозной вывод мат-аудита (компас этой сессии):** системный класс дефектов — **«вычисленная, но не доставленная честность»** (движок считает правильно → слой доставки: UI/отчёт/подпись — не доносит или врёт). Искать в первую очередь этот класс.
- **Ветвление:** новую работу вести в новых ветках от `feat/econ-math-audit` (или его merge-результата): `feat/econ-opp-XX` / `feat/econ-commercial-wave1` и т.п. Общий репозиторий — коммитить узким pathspec, чужие untracked не трогать.

## Метод (проверен мат-аудитом — воспроизводить)

1. Durable-реестр находок/задач в корне репо (образец: `AUTONOMOUS_WORK_STATE_MATH_AUDIT.md`): таблица {id, где, суть, класс, verify, fix}, секции МИКРОСТАТУС / СДЕЛАНО / ОСТАЛОСЬ; обновлять при каждом шаге, коммитить с каждым батчем.
2. Ритм: **дешёвый решающий зонд → verify лично (агенты дают ~40% ложных находок; они систематически пропускают `tools/` — смотрят только `sidecar/tests/`) → фикс батчем → характеризующий тест → коммит → живой gate**.
3. Классы находок: BUG / METHOD-GAP (fix с RAG-атрибуцией: `"D:\Docs\Knowledge_Library\.venv\Scripts\python.exe" "D:\Docs\Knowledge_Library\lib_vec.py" search "<рус+англ одной строкой>" --k 4`) / DOCUMENTED-TRADEOFF (не чинить — проверить раскрытие, INV-50) / FALSE.
4. Хирургия: трогать только требуемое; числа клиентов не «улучшать» — править честность; детерминизм (I4/D13) и pickle-совместимость (1.0…1.3) не ломать; pin Кагоцела переустанавливать только осознанно с обоснованием.
5. Живой gate: реальный Kagocel-прогон по образцу `tmp/probe_live_kagocel_audit.py` (обучение JAX-NUTS ~3 сек с `mcmc_override {'chains':2,'draws':600,'tune':600,'sampler':'NUTS'}` + весь пайплайн).

## Среда и команды (проверено боем)

- Python 3.12 глобальный; pymc 5.28.4 / arviz 0.23.4 / jax 0.7.2 / numpyro 0.20.1; **g++ НЕТ** (штатно — NUTS идёт через JAX). Реальные данные: `D:\Docs\Aurora_Ai\TestData\Econometrica\` (Kagocel_RF 31×34 — колонки с `\n` внутри!, Venarus, MMX, Planning).
- Тесты: `python -m pytest tools/ -m "not slow and not integration and not requires_real_data" -n 4 -q` (⚠ НЕ `-n auto`: 24 воркера ловят гонку jaxlib-DLL — OPP-01). Sidecar: `python -m pytest sidecar/econometrica/tests/ -q`. Standalone (в collect_ignore, гонять отдельно): `python tools/test_math_correctness.py` (156), `python tools/test_posterior_ci.py` (82). Базлайн зелёный: 1662+379+156+82; svelte: `npm run check` → 0 ошибок.
- Фикстуры: `tools/conftest.py` — `synthetic_trained_project` / `kagocel_pathology_project` (готовые pickle без MCMC); хелпер `_build_project` в `tools/test_goalseek_honesty.py` (импортируется соседним тест-модулем).
- Грабли: git commit из PowerShell — here-string `@'...'@`, ВНУТРИ никаких прямых двойных кавычек (рвёт аргумент; ёлочки «» ок); rg-lookahead не работает (без -P); `decompose(project_dir)` — первый аргумент строка; `res['channels']` — list, не dict; сигнатура сценария: `predict_scenario(config, project_dir)`, план в native units, single value = TOTAL (распределяется по периодам).

---

# ЗАДАЧИ

## Блок A — OPP-реализация (из мат-аудита; полный текст: реестр §OPP + отчёт §Рекомендации)

### A1. OPP-01 — стабильный тестовый прогон (5 минут, сделать первым мимоходом)
Зафиксировать воркеры в `pytest.ini` (`addopts = -n 4` или `--dist worksteal`): `-n auto`=24 на Windows ловит гонку загрузки jaxlib-DLL → флаки-развал (наблюдён боем). Критерий: три подряд полных прогона зелёные.

### A2. OPP-02 — «Бюджет под вероятность» ⭐ ставка Маши (продуктовый дифференциатор)
**Суть:** Goal-Seek сейчас отдаёт медианный бюджет (P(hit)≈50% by construction — бисекция останавливается на S(B*)≈target). Добавить режим «бюджет под P=80%» (квантильная бисекция: минимальный B, при котором доля posterior-draws S(B)≥target ≥ 0.8).
**Готовая механика:** `optimize/inverse.py` → `build_proportional_forward()` возвращает в meta `posterior_sampler(B)` → np.ndarray продаж per-draw (создан в мат-аудите, F-02/F-03). Квантильный forward: `q_fwd(B) = np.quantile(sampler(B), 0.2)` монотонен по B (как обычный) → та же `bisect_for_target` с forward_fn=обёртка.
**Реализация:** (1) параметр `confidence: float|None` в `optimize_inverse` (None=прежнее поведение, back-compat; 0.8 = квантильный режим); (2) при confidence: bisect по квантильному forward; CI/extrapolation/p_hit — той же механикой (p_hit при найденном B* будет ≥confidence — само-подтверждение); (3) Rust `econ_optimize_inverse` — пробросить необязательный параметр (`src-tauri/src/commands/econometrica.rs:619`); (4) UI `OptimizeGoalSeek.svelte` — переключатель «Обычный (медиана) / Осторожный (80%)» + подпись; `GoalSeekResultCard` — показать «бюджет под вероятность 80%»; (5) тесты в `tools/test_goalseek_honesty.py`-стиле: B*(0.8) ≥ B*(медиана) на wide-posterior; back-compat без параметра; живой прогон Kagocel.
**Осторожно:** сатурация — при высоком confidence цель может стать недостижимой (честный fallback_max уже есть); мок-тесты `sidecar/tests/test_inverse_flat_response_marker.py` не сломать (kwargs с default).

### A3. OPP-05 + OPP-03 + OPP-08 — пакет «доставка честности» (делать вместе)
- **OPP-05:** preflight-гейт ДО кнопки «Обучить». Endpoint `/compute/preflight` готов (server.py:844 — engine recommend + quick_proxy + prior_predictive, overall_tier + overrideable). Нет Rust-команды и UI. Сделать: `econ_preflight` в `commands/econometrica.rs` (по образцу соседей, `post_json('/compute/preflight',...)`, train_client — до 15 сек) + регистрация в lib.rs (~:3274) + вызов в `ModelTrainingStep.svelte` перед `econ_train_start` (баннер tier: reliable/directional/insufficient + кнопка «Обучить всё равно» при overrideable). In-train вариант (F-13) оставить (страховка).
- **OPP-03:** единый язык extrapolation-тиров 0-3 на всех вкладках: маркеры уже в goal-seek (`result.extrapolation`) и сценариях; ДОБАВИТЬ на forward-оптимизацию (optimizer.py возвращает optimal_spend_money per-channel — сравнить per-period с p95/p99 истории, переиспользовать паттерн `extrapolation_reporter` из inverse.py) и на compare-страницу сценариев (`src/routes/pipeline/compare/+page.svelte` — бейдж из сохранённого scenario JSON, поле уже пишется).
- **OPP-08:** после подключения preflight — `/compute/forecast-scaling` (server.py:1291) либо подключить к forward-вкладке (быстрый статус ~12ms), либо снести с упоминаниями. Решение по месту: если OPP-03 покрывает потребность — сносить.
**Критерий пакета:** пользователь видит предупреждения честности ДО обучения, НА оптимизации, В сценариях и В goal-seek одним языком; мёртвых endpoint'ов нет.

### A4. OPP-04 — CI на оптимальный сплит долей (методология, канон Jin 2017)
«Доля канала A: 38% [27–46%]; при перекрытии CI — разница статистически не выделяется». Реализация: пере-оптимизация SLSQP на подвыборке 50–100 posterior-draws (subsample из `posterior_samples`, точечные параметры per-draw → optimize → распределение оптимальных долей → HDI). Дорого по времени (50-100×SLSQP ~секунды-десятки сек) → отдельная кнопка/фон, НЕ в интерактивном пути. MATH_REFERENCE H11-Status уже честно описывает разрыв — обновить после реализации. RAG: Jin 2017 (оптимальный микс имеет дисперсию).

### A5. OPP-07 — awareness до канона кабинета
`engines/awareness.py` (сейчас честный MVP + мой честный AR(1)-CI). Добавить: (1) ESOV-модуль — вход SOV/SOM колонки (в Kagocel есть `SOV`, `SOM в руб`!) → Binet & Field: рост SOM ≈ 0.05×ESOV/год (RAG-корпус: The Long and Short of It — точные цитаты поднимаются запросом «избыточная доля голоса ESOV Binet Field»); (2) Weibull-хвост медиа→awareness (знание строится медленно — kernel из utils/adstock.py); (3) CI на эластичность S-кривой (pcov из curve_fit уже возвращается — delta-метод). Канон кабинета: `New_AI_Agency/econometrist/CLAUDE.md` §/awareness-forecast.

### A6. OPP-06 — мягкая остановка MCMC при отмене (последний приоритет)
Сейчас cancel помечает задачу, поток дорабатывает вхолостую (задокументировано, server.py:1076 docstring). numpyro прерывание нетривиально; направления: порционное сэмплирование (несколько коротких sample-вызовов с проверкой флага между) или kill процесса-воркера. Не трогать без замера реальной боли.

## Блок B — Волна 1 аудита: «деньги и лицо» 🔴

### B1. Репортинг — доставка в PPTX/HTML/xlsx (начать с него: метод готов, риск максимальный)
**Зачем:** отчёт — артефакт для CMO клиента; мат-аудит добавил в движок новые поля честности (extrapolation, delta_posterior CI, p_hit_method, capped, preflight, ci_method awareness) — по нашему же выводу вероятность «отчёты их не подхватили» высокая. Глоссарий PPTX уже врал трижды (исправлено b501708) — полной сверки не было; report-fidelity-аудит был 2026-06-07, ДО всех правок.
**Файлы:** `sidecar/econometrica/aurora_pptx/builder.py` (156 КБ!), `aurora_html/` (builder/sections/interactive), `engines/narrative_adapter.py` (44 КБ — формулировки!), `engines/json_export.py`, `lib/scenario-export.js`.
**Метод (канарейка, как D1):** сгенерировать отчёты на synthetic-фикстуре + реальном Kagocel → каждое ЧИСЛО отчёта сверить с JSON движка программно; каждый CLAIM-текст narrative_adapter — с фактическим методом (маркеры [MODELED]/[ASSUMED], CI-проценты, названия методов); новые honesty-поля — видимы или осознанно исключены (решение записать). Существующие тесты: `test_aurora_pptx_*`, `test_narrative_*`, `test_deliverable_thinness_disclosure` (образец: THIN/FAT фикстуры).
**Критерий:** 0 расхождений число-отчёт↔движок; 0 методологических claim'ов без опоры; extrapolation/насыщение доставлены в отчёт.

### B2. Лицензирование и активация
**Зачем:** обход = потерянные деньги; ложный отказ = сорванный день-1 пилота (хуже). Известная дыра: «#61 license offline-smoke НЕ проверен» (live-тест 2026-06-02) до сих пор открыт.
**Файлы:** `src-tauri/src/commands/license.rs` (Ed25519 offline fallback), `online_auth.rs` (v2 приоритетная — ДВЕ системы параллельно, зона рассинхрона), `crypto/` (AES-256-GCM, HKDF, fingerprint), `session/manager.rs` (vault-распаковка: tar начинается с "." — НЕ set_overwrite(false)!), `vault.rs`. Грабля из CLAUDE.md: путаница raw-hex(~200)/fingerprint(SHA-256, 64)/hash(64) — самая частая ошибка; выдача: `2_Выдача_лицензий/CLAUDE.md`.
**Матрица сценариев (боем на стенде):** активация онлайн / офлайн fallback / отзыв / истечение / смена железа (обновление Windows, замена диска → fingerprint drift) / вторая машина / перевод часов назад / переустановка / повреждённый license.json / vault на кириллическом пути и в OneDrive. Rust-тесты: `cargo test` (48) — прогнать с `CARGO_TARGET_DIR="D:/cargo-targets/ai-agency"`.
**Критерий:** матрица покрыта (боем или автотестом), «#61» закрыт, поведение при каждом отказе — понятное пользователю сообщение (не сырой Rust-error).

### B3. Обновления (updater.rs + content_updater.rs + Supabase-канал)
Цепочка публикация→манифест→доставка→установка→откат на битом манифесте. Метод-инвариант: правка доехала ПО СВОЕМУ каналу (aurora_contentpack_dualsource_runtime: проверять из установленного `%LOCALAPPDATA%`, не из рабочей папки). Регламент publishing: skill `aurora-release-update`.

## Блок C — Волна 2 аудита: «первый день клиента» 🟠

### C1. Импорт грязных клиентских данных
Первый шаг пилота — чужой xlsx: объединённые ячейки, `\n` в заголовках (у Kagocel реально есть), проценты строками, две шапки, 1С-выгрузки, пустые листы, дубли колонок. Файлы: `engines/validator.py`, `utils/column_detection.py` (33 КБ), merge_rules. Метод: собрать коллекцию «плохих файлов» (мутации реальных из TestData) → прогон validate/preflight → каждое падение = находка (нужно понятное сообщение, не traceback). Существующие тесты: `test_validator_input_robustness`, `test_column_detection*`.

### C2. Выживаемость / chaos-проход
Сценарии: крах посреди MCMC (fix_interrupted_campaigns есть — проверить боем), диск полон, антивирус держит pickle, папка проекта в OneDrive, два окна приложения одновременно (file_lock проверен на потоках — теперь на процессах), спящий режим посреди обучения. Файлы: `engines/persistence*.py`, `utils/file_lock.py`, `server.py` lifecycle (+ мой `_cleanup_stale_training_tasks`).

### C3. Прицельный click-path по местам правок мат-аудита (день, не неделя)
Полный GUI-аудит был 2026-06-02 (лог `TEST_FINDINGS_2026-06-02.md`; топ: онбординг-перегруз). Сейчас — только вживую пройти новое: бейдж экстраполяции goal-seek (severity 1 warn / 2+ danger), плашка экстраполяции сценариев у слайдера, починенный what-if слайдер (план из current_spend×множитель; подсказка при отсутствии оптимизации), подписи торнадо ±20%, баннер насыщения при capped-CI, «дельта-метод по постериору» в футере. Метод: `npm run tauri:dev` (мост MCP: mcp__tauri__* работает ТОЛЬКО с tauri:dev, не tauri dev) по стандарту AVT (`feedback_autonomous_visual_testing_standard`). Live-rebuild пункты копить в ОДИН проход окна (`feedback_batch_live_rebuild_checklist_one_window_pass`).

## Блок D — Волна 3 аудита: «поставка и обещания» 🟡

### D1. Клятва «0 egress» локальной редакции — доказать боем
Продажное обещание для фармы (152-ФЗ): сборка `--no-default-features` (feature `cloud_advisors` off → `claude.rs` ранний bail) — поднять сниффер (или firewall-лог) на чистой машине → полный пайплайн → 0 внешних соединений (кроме localhost sidecar). INV-52: `withGlobalTauri` не должен течь в prod. Результат — воспроизводимый протокол доказательства (для сейлов).

### D2. Двухредакционная упаковка (известный TODO из CLAUDE.md продукта)
У облачной и локальной редакций один identifier `com.aurora.econometrica` → затирают друг друга при установке. Решение: отдельный productName/identifier локальной (следствия: пути %APPDATA%, лицензии per-app, updater-канал). Дешёво, но трогает выдачу лицензий — согласовать формат с `2_Выдача_лицензий`.

### D3. Безопасность дистрибутива
Было: SECURITY_AUDIT_aurora_model_v2_1_0 (формат модели), attack-vectors/path-traversal тесты. Добрать: NSIS-инсталлятор (права, пути), Tauri capabilities/IPC scope (skill tauri-capabilities/tauri-scope), CSP, отсутствие секретов в бандле. Skill: security-review.

### D4. Производительность на «машине маркетолога» + NOTICE
8 ГБ ноутбук без g++: после F-28 обучение полноценное 4×2000×2000 — замерить время на слабом CPU (JAX single-device предупреждение уже видели), калибровать прогресс-текст. PyInstaller-размер сайдкара. Плюс 30 минут: NOTICE-файл лицензий третьих сторон (PyMC/JAX/arviz Apache|MIT, InterVariable OFL, ECharts Apache) в дистрибутив.

---

# ПОРЯДОК (рекомендация Маши)

1. **A1** (5 мин, мимоходом) → 2. **A2 OPP-02** (⭐ день: продуктовый дифференциатор на готовой механике) → 3. **B1 репортинг-канарейка** (самый дорогой риск, метод готов) → 4. **A3 пакет честности** (OPP-05+03+08) → 5. **B2 лицензии** (нужен стенд; параллелить с B1 нельзя — другая природа) → 6. **B3 обновления** → 7. **C1→C2→C3** → 8. **D1→D2→D3→D4** → 9. **A4, A5, A6** (методология вторym эшелоном). Каждый пункт = свой durable-батч с коммитом; после каждого блока — живой gate Kagocel + полный pytest.

# Совет исполнителю от прошлой сессии (мета-урок, вне метода)

**Двигайся со скоростью зондов, а не со скоростью правок.** Мат-аудит дал 18 правок с НУЛЁМ откатов не потому, что правки были быстрые, а потому что ни одна не начиналась без числа-доказательства из зонда и не заканчивалась без числа-подтверждения (12.80%=12.80%; −21.6% vs +1.9%; coverage 42%; ESS 704/458). Три шестерёнки:
1. **Число — валюта доверия.** Находка без воспроизводимого числа не получает права на правку. «Вижу баг в коде» → сначала зонд, потом фикс. Мандат Антона «чини всё сразу, решай сама» заработан числами и держится, пока каждое решение приходит доказанным.
2. **Первый дефект класса — линза, не единица.** Дефекты серийны: нашла один — немедленно просканируй шаблоном ВСЕ аналогичные места (так «preflight мёртв» за полчаса дал forecast-scaling, глоссарий, tooltip). В B1: первое враньё подписи → сразу grep всего семейства подписей.
3. **Батч умирает в пределах хода.** Хвост через пробуждение/компрессию стоит втрое (восстановление нити). Размер батча = «что доведу до коммита в этом ходе». И кради готовые леса (`_build_project`, `tmp/probe_live_kagocel_audit.py`, паттерн `extrapolation_reporter`) — не строй свои.

# Критерий готовности сессии
Реестр без «?»; каждый FIX с тестом; gate зелёный (tools+sidecar+standalone+svelte+живой Kagocel); отчёт-приложение к `docs/audits/` (політика: НЕ создавать MATH_AUDIT_v*, аудит-отчёты → docs/audits/); сводка Антону с остатками и решениями, которые ждут его.
