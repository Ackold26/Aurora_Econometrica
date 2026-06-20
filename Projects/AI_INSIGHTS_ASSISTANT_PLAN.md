# AI-ассистент инсайтов для Econometrica Optimizer — durable план + состояние

> **Назначение:** durable SSOT этой работы. Переживает компрессию контекста.
> После сжатия сессии — ПЕРВЫМ делом перечитать этот файл и продолжить с «Точки возобновления».
> Создан 2026-06-20. Обновлять по ходу (лог снизу).

---

## МАНДАТ (Антон, 2026-06-20)
Автономный режим: **изучить код → план всех работ → адверсариальный аудит (логический/технический/математический), найти все ошибки → устранить → реализация.**
Пережить компрессию: durable-файлы + точка возобновления; работа продолжается после сжатия.
Перед первой строкой кода — показать Антону проаудированный план одним экраном (страховка, продукт перед публикацией 2.1.0).

## ПРОДУКТОВАЯ КОНЦЕПЦИЯ (согласована)
- **Гибрид:** детерминированный движок инсайтов (Tier 1, оба режима, не галлюцинирует) + LLM-усилитель (Tier 2, облачный режим). LLM получает Tier-1 инсайты + JSON-факты как ВХОД и переформулирует — НЕ генерирует числа → согласованность + INV-50 by design.
- **Один продукт, два режима:** «с AI» / «только локально» (данные не уходят). Runtime-тумблер, не две сборки.
- **AI не считает — объясняет/направляет.** Числа цитируются из модели (INV-50).
- **4 слоя:** (1) интерпретатор «объясни результат»; (2) штурман — диагностика/процесс; (3) советчик — сценарии словами → оптимизатор; (4) нарратив — резюме презентации.
- Не блокирует публикацию 2.1.0. Цель — поколение ~2.2.

## РАМКИ (приняты, право вето Антона)
1. **Изоляция в отдельной ветке** (не master с собранным 2.1.0).
2. **Фазовая реализация** (каждая фаза отгружаема).
3. **Гибрид движок+LLM** как фундамент.
4. **Прокси-гейт первым** (дешёвый автотест на реальном движке до фич).

---

## ⭐ КЛЮЧЕВАЯ НАХОДКА: гибрид = ИХ ЖЕ незавершённый замысел
`InsightsPanel.svelte:4-6` докстрока: **«Tier 1: offline insights from insights-rules.js (always works). Tier 2: Claude AI (online, optional) — Phase 10.»**
- **Tier 1 ПОСТРОЕН** (insights-rules.js, 2248 строк, 11 функций на все 6 шагов пайплайна, structured `Insight{severity,text,tip,action}` + actionable-кнопки + undo). «~80% ценности при 0% стоимости» (их слова). Работает offline → оба режима.
- **Tier 2 = Phase 10, НЕ реализован** (Grep подтвердил: упоминание ТОЛЬКО в докстроке-маркере, частичной реализации нет).
⇒ Мы достраиваем их собственную архитектуру, а не навязываем чужую. Огромное снятие риска.

## ПОДТВЕРЖДЁННЫЙ ФУНДАМЕНТ (личная верификация, цитаты)
- **git:** отдельный репо, ветка `master`, HEAD `7fbfd96`, untracked-only → ветвиться безопасно.
- **honesty-gate (INV-50 ядро):** `sidecar/econometrica/utils/optimizer_honesty.py:63` `model_reliability_verdict()` → `{verdict,refused,reasons,caveat_text}`, verdict∈reliable/uncertain/unreliable/unknown. R-hat≥1.05, дивергенции, OLS small-data→max uncertain, OVB-праздники. Докстрока: «UI потребляет **verbatim** (INV-50), не пере-выводит». ⇒ Tier 2 ОБЯЗАН передавать verdict verbatim.
- **Вердикты каналов:** `decomposer.py:133` `compute_roi_verdict()` → `verdict`/`verdict_tone`.
- **Tier 1 движок:** `src/lib/insights-rules.js` — `importInsights`, `validateKpiInsights`, `validateRolesInsights`, `validateMetricsInsights`, `validateConfirmInsights`, `validateInsights`, `modelPreTrainingInsights`, `modelInsights`, `decomposeInsights`, `optimizeInsights`, `reportInsights`. Тесты: `__tests__/insights-rules-{rec1,ratio-honesty,ovb-controls}.test.js`. Ratio SSOT: `ratio-classifier.js`.
- **UI:** `InsightsPanel.svelte` — правая sidebar, реактивно по `$pipelineCurrentStep` (0-5), каждый шаг→свои инсайты. structured Insight + кнопка «Применить»/«Подробнее»/undo.
- **Два режима = compile-time feature `cloud_advisors`:** `claude.rs:87` `CLOUD_ADVISORS_ENABLED`; `run_claude`/`run_claude_pipeline` bail ДО спавна (egress недостижим, 152-ФЗ). Фронт: `get_app_status`→`cloud_advisors_enabled` (`lib.rs:1941`), `+layout.svelte:210` `advisorsEnabled`. Consent-гейт: `claude.rs:93` `ensure_cloud_consent()` + `user_config::cloud_consent_required`.
- **LLM-мост = Claude CLI** (`run_claude`, claude.rs:107): спавн `claude --print --output-format stream-json --dangerously-skip-permissions`, work_dir+cabinet_id+resume+model+effort, стрим через Tauri events. **ЕДИНЫЙ egress-чок-поинт** (claude.rs докстрока). Кабинет `econometrist` (8 команд) — облачный советник через этот мост.

## ИНВЕНТАРЬ ВХОДОВ Tier 2 (факты модели → results/*.json → stores)
- `model-diagnostics.json`: `r_hat_max`, `per_param_rhat`, `divergences`, `tail_ess_ok[]`, `mcmc{chains,draws,tune}`, `mqs{tier,score}`, `checks.ratio`.
- `decomposition.json`: per-channel `contribution`(+ci HDI90), `roi`(+ci), `efficiency_gap`, `share_of_spend/effect`, `verdict`/`verdict_tone`, `mroi_current`; `baseline`/`media_contribution`; `signed_factor_contributions`.
- `optimization.json`: `channels[delta_pct,mroi±ci]`, `response_curves`, `expected_lift_pct`, `binding_constraints`, `model_reliability{verdict,reason}`, `insight`(нарратив-строка уже есть).
- `awareness-forecast.json`: `forecast`+ci, `trend`, s-curve.
- **API sidecar** (`server.py`): `/compute/{validate,train,decompose,optimize,scenario,compare}`. `scenario`: `predict_scenario(config{media_plan},project_dir)` — чистая, фундамент слоя 3. `optimize(config,project_dir)` — чистая.
- **Stores** (`project-state.js`): `validateData`, `modelData`, `decomposeData`, `optimizeData`. Слои 1-2 НЕ требуют новых Tauri-команд.

---

## ФИНАЛЬНАЯ DELTA (новая работа поверх Tier 1)
- **A. Tier 2 ядро (их «Phase 10»):** соединить детерминир. инсайты с Claude — inline «Спросить ИИ / а почему?» прямо в InsightsPanel, через существующий `run_claude` egress-чок-поинт. LLM получает grounding-пакет {Tier-1 инсайты + JSON-факты + honesty verdict verbatim}, переформулирует, не считает.
- **B. Слой 3 советчик (НЕТ):** NL → optimizer/scenario config → чистая `predict_scenario`/`optimize` → интерпретация. Human-in-the-loop (показать распарсенный config до запуска). Самое дорогое.
- **C. Runtime-тумблер «только локально»:** egress-гейт по runtime-настройке (user_config) в ЕДИНОМ чок-поинте run_claude + UI-тумблер. Tier 1 уже offline; тумблер выключает Tier 2.
- **D. Слой 4 нарратив (опц.):** Tier 2 связное резюме слайда поверх reportInsights + факты.

## ПЛАН ФАЗ
**Фаза 0 — Фундамент + прокси-гейт (разблокиратор автономии). [M]**
- Ветка `feat/ai-insights-tier2`.
- Фикстура реального прогона: обученный проект (models/latest.pkl + results/*.json) — реальный, не happy-path.
- Прокси/INV-50-guard тест: реальные results/*.json → grounding-пакет → (мок/реальный Claude) → СТРУКТУРНАЯ проверка: все числа в ответе LLM ⊆ набор фактов (с нормализацией единиц/округления). Детерминированная проверка над недетерминир. выходом.

**Фаза 1 — Tier 2 ядро «Спросить ИИ об инсайте». [L]**
- `grounding-пакет`: сборщик {Tier-1 инсайты текущего шага + релевантные JSON-факты + honesty verdict verbatim}.
- Промпт-шаблон: факты+инсайты как контекст; запрет выдумывать числа; при неуверенности — качественно без числа (INV-50); honesty verdict не пере-выводить.
- Мост: тонкий путь через `run_claude` (лёгкий work_dir/промпт, без vault-pipeline-машинерии).
- UI: в InsightsPanel поле/кнопка «Спросить ИИ» (Tier 2), видна только cloud+consent. Ответ в панель.
- Гейт по продукту (`isEconometrica`) — не ломать другие продукты на общем shell.

**Фаза 2 — Runtime-тумблер «только локально». [S-M]**
- Rust: `ensure_not_local_only()` рядом с `ensure_cloud_consent()` в едином чок-поинте. Egress = feature ∧ consent ∧ ¬local_only.
- UI: тумблер в Настройках «Только локально (данные не уходят)» → влияет на видимость Tier 2.
- Тест: при local_only — Claude не спавнится (нет egress).

**Фаза 3 — Слой 3 советчик (сценарии словами). [L]**
- NL→config через Claude structured-output: «увеличь ТВ на 20%» → config.
- Human-in-the-loop: показать распарсенный config до запуска.
- Вызов чистой `predict_scenario`/`optimize` (детерминир. расчёт).
- Интерпретация результата через Tier 2 (числа из JSON-ответа движка).
- В local_only — фоллбэк на обычные формы-сценарии (проверить, что UI форм существует).

**Фаза 4 — Слой 4 нарратив (опц., если время). [S-M]**
- Tier 2 резюме для презентации + INV-50 + клиентская гигиена (короткое тире, без англицизмов).

**Сквозное:** каждая фаза — прокси/guard-тест зелёный, durable обновлён, git-коммит своим pathspec, INV-50 guard прогон.

## ЖУРНАЛ АДВЕРСАРИАЛЬНОГО АУДИТА ПЛАНА (найдено → устранено)
**Логика:**
- L1 Дублирование Tier 1 → план стартует с Tier 2 поверх; слои 1-2 «готово, не трогать кроме точечного расширения».
- L2 Слой 3 NL зависит от Tier 2 (LLM) → в local_only NL недоступен; деградация на формы-сценарии (оба режима). [проверить наличие форм UI в Фазе 3]
- L3 Не начат ли Phase 10 → Grep: НЕТ, только маркер. Дублирования нет. ✅
**Техника:**
- T1 run_claude тяжёл для realtime → не realtime-чат, а «спросить ИИ»; переиспользуем единый egress-чок-поинт (НЕ новый API-канал — критично для 152-ФЗ/INV-38). Лёгкий work_dir/промпт.
- T2 Общий shell (AI Agency + Econometrica) → Tier 2 гейтить по `isEconometrica`, не трогать общие пути.
- T3 Guard-тест с реальным LLM флаки → структурная проверка (числа ответа ⊆ факты), мок для CI.
- T4 Матрица consent×feature×toggle → явная таблица истинности: Tier2 доступен ⟺ feature ∧ consent ∧ ¬local_only; гейт в одном чок-поинте.
**Математика:**
- M1 INV-50 галлюцинация числа → LLM не считает; все числа из фактов+Tier1; guard проверяет ⊆.
- M2 Округление/единицы при сверке → нормализация чисел (млн/тыс/₽, значимые) в guard-тесте.
- M3 Доверительные интервалы → Tier 1 уже трактует (широкий=неуверенность); LLM наследует из контекста.
- M4 honesty verdict → передавать `caveat_text` verbatim; промпт запрещает оспаривать/пересчитывать надёжность.

---

## ТОЧКА ВОЗОБНОВЛЕНИЯ (после компрессии — читать ЭТО)
**Антон дал полный автономный мандат (2026-06-20): «действуй, дальше работай полностью автономно».**
Режим: single trackfile (этот файл), audit-before-commit, auto-commit local. Вопросы только: архитектура / push к remote / schema-migration. Push НЕ делать без approval.

**Текущее состояние: ФАЗА 1 КОД-COMPLETE ✅ (0,1.1,1.2,1.3 + ревью). Дальше: live E2E (ручная) и/или Фаза 2 (runtime-тумблер).**

Сделано:
- ✅ Ветка `feat/ai-insights-tier2` (от master `7fbfd96`). Коммит Фаза 0 `a4c4e14`.
- ✅ **Фаза 0** — Прокси-гейт INV-50: `src/lib/insights-grounding.js` (extractNumbers / collectGroundedNumbers / findUngroundedNumbers / assertGrounded) + тест на фикстуре `fixtures/kagocel-load1/decomposition.json`. 15/15.
- ✅ **Фаза 1.1 (JS-ядро Tier 2)** — `src/lib/tier2-context.js` (buildTier2Context / buildTier2Prompt / TIER2_SYSTEM_RULES / STEP). Сводка фактов по шагам (decompose реально, optimize/model/report), honesty verbatim, промпт с железными правилами INV-50. Тест `tier2-context.test.js` смыкает с guard: честный ответ из контекста проходит, выдуманное флагается. 11/11.

- ✅ **Фаза 1.2 (Rust-мост)** — Tauri-команда `econ_ask_insight(prompt) -> Result<String>` в `src-tauri/src/lib.rs` (рядом с open_cabinet, ~318), регистрация в generate_handler! рядом с `open_cabinet`. Тонкий транспорт: промпт строит фронт, Rust шлёт через ЕДИНЫЙ egress-чок-поинт `run_claude` (consent+feature гейт наследуются; local-редакция → bail, 0 egress). Stateless (resume=None, INV-50), suppress_export=true. Требует открытой сессии кабинета `econometrist` (get_work_dir). **Обе редакции компилируются** (cargo check: cloud 36s, local --no-default-features 1m43s).

- ✅ **Фаза 1.3 (UI)** — `InsightsPanel.svelte`: блок «Спросить ИИ» (поле+кнопка), гейт `canAsk = cloudConsent.advisorsEnabled && granted && isEconometrica`. `askAI()`: строит промпт (tier2-context), ленивое `open_cabinet('econometrist')` при `[ASK-NO-SESSION]`, рантайм-страж `findUngroundedNumbers` → пометка «⚠ числа не сверены». $effect сбрасывает ответ при смене шага. svelte-check: 0 ошибок в проекте. Фикс em dash в JSDoc (TS «Invalid character»).
- ✅ **Audit-before-commit (Sonnet-ревью Tier 2 цепочки)** — 5 находок. Приняты 2: (#2) honesty явно добавлен в grounding `[fullFacts, honesty]`; (#3) сброс ответа при смене шага ($effect). Отвергнуты 3 с обоснованием: #1/#4 — толеранс корректно отделяет округление от галлюцинации (осознанный компромисс); #5 — run_claude имеет 30-мин таймаут (known limitation: нет кнопки отмены). Тесты после фиксов 27/27.

**ФАЗА 1 КОД-COMPLETE.** Осталось по Фазе 1: **live E2E с реальным Claude** (открыть кабинет econometrist, задать вопрос, увидеть ответ + работу INV-50-стража) — дорогой GUI+auth прогон, оставлен на **ручную проверку с Антоном** (или отдельную dev-сессию). Дёшево верифицировано: svelte-check 0, тесты 27/27, Rust обе редакции компилируются, guard на реальной фикстуре.

**Следующий конкретный шаг — Фаза 2 (runtime-тумблер «только локально»):**
1. Rust: `ensure_not_local_only()` рядом с `ensure_cloud_consent()` (claude.rs) в едином чок-поинте. Egress = feature ∧ consent ∧ ¬local_only. Настройка в `user_config`.
2. UI: тумблер в Настройках «Только локально (данные не уходят)» → влияет на `cloudConsent`/видимость Tier 2.
3. Тест: при local_only — Claude не спавнится (нет egress).
Альтернатива по приоритету: можно сделать live E2E (с Антоном) до Фазы 2.

## ЛОГ ПРОГРЕССА
- **2026-06-20 (1) Исследование+план** — Инвентарь модели (3 Explore-субагента). Личная верификация (honesty-gate, verdict, ratio-classifier, git, insights-rules.js полнота, InsightsPanel, claude.rs мост). Открыт замысел Tier1(done)/Tier2(Phase10 pending) = наш гибрид. Delta, план фаз, адверсариальный аудит (L1-3/T1-4/M1-4). Антон дал добро + полный автономный мандат.
- **2026-06-20 (2) Фаза 0** — Ветка создана. Построен INV-50 grounding guard (insights-grounding.js) + тест на реальной фикстуре Кагоцел, 15/15 зелёных. Прокси-гейт = прокси живого прогона Tier 2 (тот же `findUngroundedNumbers` станет рантайм-стражем). Коммит локальный.
- **2026-06-20 (3) Фаза 1.1+1.2** — JS-ядро Tier 2 (tier2-context.js: контекст+промпт, 11/11). Rust-мост econ_ask_insight (lib.rs, через единый egress-чок-поинт run_claude, обе редакции компилируются). Коммиты `401eb6c`, `8041ef6`.
- **2026-06-20 (4) Фаза 1.3 + ревью** — UI «Спросить ИИ» в InsightsPanel.svelte (canAsk-гейт, askAI с ленивым open_cabinet + рантайм-страж + $effect сброс). svelte-check 0 ошибок. Sonnet audit-before-commit: 2 фикса (honesty в grounding, сброс ответа), 3 отвергнуты с обоснованием. Тесты 27/27. ФАЗА 1 код-complete; live E2E с Claude — на ручную проверку.
