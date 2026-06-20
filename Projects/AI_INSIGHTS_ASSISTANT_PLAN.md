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

**Текущее состояние: ФАЗЫ 0–3 LIVE-VERIFIED ✅. Ветка ЗАПУШЕНА на origin (2026-06-20). Справка программы в контексте Авроры (`2230977`, запушен). Методология roadmap — 2 высокоприоритетных пункта применены (`1bfa62f`): caveat коллинеарности + тон honesty-gate. Дальше: push методологии / live-проверка справки+методологии / остаток roadmap (OVB-warning, takeaway-заголовки, INV causal-caveats).**

Сделано:
- ✅ Ветка `feat/ai-insights-tier2` (от master `7fbfd96`). Коммит Фаза 0 `a4c4e14`.
- ✅ **Фаза 0** — Прокси-гейт INV-50: `src/lib/insights-grounding.js` (extractNumbers / collectGroundedNumbers / findUngroundedNumbers / assertGrounded) + тест на фикстуре `fixtures/kagocel-load1/decomposition.json`. 15/15.
- ✅ **Фаза 1.1 (JS-ядро Tier 2)** — `src/lib/tier2-context.js` (buildTier2Context / buildTier2Prompt / TIER2_SYSTEM_RULES / STEP). Сводка фактов по шагам (decompose реально, optimize/model/report), honesty verbatim, промпт с железными правилами INV-50. Тест `tier2-context.test.js` смыкает с guard: честный ответ из контекста проходит, выдуманное флагается. 11/11.

- ✅ **Фаза 1.2 (Rust-мост)** — Tauri-команда `econ_ask_insight(prompt) -> Result<String>` в `src-tauri/src/lib.rs` (рядом с open_cabinet, ~318), регистрация в generate_handler! рядом с `open_cabinet`. Тонкий транспорт: промпт строит фронт, Rust шлёт через ЕДИНЫЙ egress-чок-поинт `run_claude` (consent+feature гейт наследуются; local-редакция → bail, 0 egress). Stateless (resume=None, INV-50), suppress_export=true. Требует открытой сессии кабинета `econometrist` (get_work_dir). **Обе редакции компилируются** (cargo check: cloud 36s, local --no-default-features 1m43s).

- ✅ **Фаза 1.3 (UI)** — `InsightsPanel.svelte`: блок «Спросить ИИ» (поле+кнопка), гейт `canAsk = cloudConsent.advisorsEnabled && granted && isEconometrica`. `askAI()`: строит промпт (tier2-context), ленивое `open_cabinet('econometrist')` при `[ASK-NO-SESSION]`, рантайм-страж `findUngroundedNumbers` → пометка «⚠ числа не сверены». $effect сбрасывает ответ при смене шага. svelte-check: 0 ошибок в проекте. Фикс em dash в JSDoc (TS «Invalid character»).
- ✅ **Audit-before-commit (Sonnet-ревью Tier 2 цепочки)** — 5 находок. Приняты 2: (#2) honesty явно добавлен в grounding `[fullFacts, honesty]`; (#3) сброс ответа при смене шага ($effect). Отвергнуты 3 с обоснованием: #1/#4 — толеранс корректно отделяет округление от галлюцинации (осознанный компромисс); #5 — run_claude имеет 30-мин таймаут (known limitation: нет кнопки отмены). Тесты после фиксов 27/27.

**ФАЗА 1 КОД-COMPLETE.** Осталось по Фазе 1: **live E2E с реальным Claude** (открыть кабинет econometrist, задать вопрос, увидеть ответ + работу INV-50-стража) — дорогой GUI+auth прогон, оставлен на **ручную проверку с Антоном** (или отдельную dev-сессию). Дёшево верифицировано: svelte-check 0, тесты 27/27, Rust обе редакции компилируются, guard на реальной фикстуре.

- ✅ **Фаза 2 (runtime-тумблер «только локально»)** — одна сборка, два режима:
  - Rust: `user_config.local_only: bool` (#[serde(default)], НЕ миграция — доказано тестом legacy-конфига); `local_only_enabled()`; `ensure_not_local_only()` в claude.rs добавлен в ОБА egress-чок-поинта (run_claude + run_claude_pipeline, replace_all). Egress = feature ∧ consent ∧ ¬local_only. Команда `set_local_only(enabled)`, поле `local_only` в `get_cloud_consent_status`.
  - UI: стор `cloudConsent.localOnly`; layout прокидывает из статуса; `canAsk` гейтит `!localOnly`; тумблер «Только локально» в Настройках (облачная секция).
  - Defense-in-depth: UI скрывает кнопку + backend bail. Обе редакции компилируются (cargo check 9s). user_config тесты 6/6 (вкл. 2 новых local_only). svelte-check 0.

**ФАЗА 2 КОД-COMPLETE.** Осталось (как и по Ф1): live-проверка вживую.

**Следующий конкретный шаг — выбор направления:**
- **Вариант A — live E2E (рекомендую сделать с Антоном):** запустить dev (`npm run tauri:dev`), открыть кабинет эконометриста, задать вопрос на шаге декомпозиции/оптимизации, увидеть ответ + сверку чисел + работу тумблера «только локально». Закрывает живую проверку Ф1+Ф2.
- **Вариант B — Фаза 3 (советчик «сценарии словами»):** NL → optimizer/scenario config → `predict_scenario`/`optimize` → интерпретация. Human-in-the-loop (показать config до запуска). Самое дорогое; NL только cloud, формы — оба режима. [L]
- **Вариант D — Фаза 4 (нарратив):** резюме для презентации. [S-M]

## ПЛАН ФАЗЫ 3 (советчик «сценарии словами») — В РАБОТЕ
Поток: NL-запрос → Claude разбирает в config → подтверждение (human-in-the-loop) → econ_scenario/optimize (детерминир. расчёт) → Аврора интерпретирует результат (числа из движка, INV-50).
- ✅ **3.1 JS-ядро** — `src/lib/scenario-advisor.js`: `buildScenarioParsePrompt` (NL→JSON промпт), `extractScenarioConfig` (извлечь+валидировать config), `applyChangesToMediaPlan` (дельты%→media_plan {ch:[budget]}), `describeScenario` (человекочитаемое подтверждение). Тест 17/17. Формат econ_scenario: `{projectDir, scenarioName, mediaPlan:{ch:[budget]}, unitCosts, forecastPeriods, forecastPeriodLabel, unitCostInflationPct, kpiUnitCost}` (см. `ScenarioPlayground.svelte:68`).
- ✅ **3.2 UI (svelte-check 0; live полного потока — после)** — блок «Что если» в InsightsPanel (или блок рядом с «Спросить Аврору»): поле NL → `econ_ask_insight(buildScenarioParsePrompt(text, channels))` → `extractScenarioConfig` → `describeScenario` (подтверждение) → [кнопка «Запустить»] → `applyChangesToMediaPlan` + `invoke('econ_scenario', {...})` → интерпретация Авророй (`econ_ask_insight` + tier2-context на результате сценария). Гейт `canAsk`. Каналы: `decomposeData.channels[].name` / `$modelEnabledMediaNames`. Текущие расходы: `channelBudgets` (`optimizeLiveState`) или `decomposeData.channels[].spend`.
- ✅ **3.3 Live E2E** разбора + расчёта + интерпретации (econ_scenario на реальной модели — см. лог (12)).

## ЛОГ ПРОГРЕССА
- **2026-06-20 (1) Исследование+план** — Инвентарь модели (3 Explore-субагента). Личная верификация (honesty-gate, verdict, ratio-classifier, git, insights-rules.js полнота, InsightsPanel, claude.rs мост). Открыт замысел Tier1(done)/Tier2(Phase10 pending) = наш гибрид. Delta, план фаз, адверсариальный аудит (L1-3/T1-4/M1-4). Антон дал добро + полный автономный мандат.
- **2026-06-20 (2) Фаза 0** — Ветка создана. Построен INV-50 grounding guard (insights-grounding.js) + тест на реальной фикстуре Кагоцел, 15/15 зелёных. Прокси-гейт = прокси живого прогона Tier 2 (тот же `findUngroundedNumbers` станет рантайм-стражем). Коммит локальный.
- **2026-06-20 (3) Фаза 1.1+1.2** — JS-ядро Tier 2 (tier2-context.js: контекст+промпт, 11/11). Rust-мост econ_ask_insight (lib.rs, через единый egress-чок-поинт run_claude, обе редакции компилируются). Коммиты `401eb6c`, `8041ef6`.
- **2026-06-20 (4) Фаза 1.3 + ревью** — UI «Спросить ИИ» в InsightsPanel.svelte (canAsk-гейт, askAI с ленивым open_cabinet + рантайм-страж + $effect сброс). svelte-check 0 ошибок. Sonnet audit-before-commit: 2 фикса (honesty в grounding, сброс ответа), 3 отвергнуты с обоснованием. Тесты 27/27. ФАЗА 1 код-complete; live E2E с Claude — на ручную проверку.
- **2026-06-20 (5) Фаза 2** — Runtime-тумблер «только локально» (одна сборка, два режима). Rust: local_only поле/функция/egress-гейт в обоих чок-поинтах/команда set_local_only/статус. UI: стор+layout+canAsk-гейт+тумблер настроек. Обе редакции компилируются, user_config тесты 6/6, svelte-check 0. ФАЗА 2 код-complete.
- **2026-06-20 (6) Имя ассистента → «Аврора»** (идея Антона) — «Спросить ИИ» → «Спросить Аврору»: заголовок-лицо в панели, подсказка поля, самопрезентация в промпте (TIER2_SYSTEM_RULES). svelte-check 0, тесты 12/12. Коммит `3dbe7a8`.
- **2026-06-20 (7) Live E2E (частично, через MCP-мост)** — dev-сборка запущена (`npm run tauri:dev`, облачная редакция, кабинет econometrist + sidecar здоровы). Программно (window.__TAURI__) ДОКАЗАНО на реальном приложении: get_cloud_consent_status отдаёт `local_only`; set_local_only round-trip; egress-гейт — без согласия econ_ask_insight → `[CL-CONSENT]`, при тумблере → `[CL-LOCAL-ONLY]` (раньше consent); Аврора скрыта без согласия (canAsk=false). **Осталось (требует Антона):** дать согласие (юр. действие) + открыть проект с обученной моделью → дойти до Декомпозиции → увидеть «Спросить Аврору» + реальный ответ + сверку чисел. Driver-сессия моста (порт 9223) оставлена открытой.
- **2026-06-20 (8) Имя «Аврора» + вендор-гигиена + панель модели** — «Спросить Аврору» (заголовок-лицо, промпт-самопрезентация, коммит `3dbe7a8`). Убран вендор «Anthropic (Claude)» из согласия/настроек → «внешний облачный сервис» (юр. суть трансграничности сохранена; MMM = агрегаты, не ПДн — оговорка про получателя ПДн отозвана, Антон прав). Панель «Модель Claude» скрыта в Optimizer (гейт productType; модель = Sonnet latest-алиас, авто-обновление). Коммит `ce9a92b`.
- **2026-06-20 (9) LIVE E2E УСПЕХ + итерация** — Аврора реально ответила (econ_ask_insight → run_claude → Claude CLI exit=0, через MCP-мост window.__TAURI__). Представилась по имени, простой язык, числа строго из фактов, прирост НЕ выдумала (отправила в оптимизацию = INV-50 живьём). **Находка live-теста:** 1-й ответ вычислил производное «в 39 раз» (=77.5/2.0), которого нет в фактах → страж пометил бы. Усилен TIER2_SYSTEM_RULES (запрет отношений/множителей → «в разы»). 2-й вызов вживую: «39» исчезло → «в разы результативнее», все числа grounded. **Backend Ф1+Ф2 ПОЛНОСТЬЮ доказан вживую.** Также вживую: панель модели скрыта в настройках, вендор убран (hasAnthropic=false), тумблер «только локально» виден, согласие дано. Осталось опц.: UI-проверка кнопки «Спросить Аврору» в панели инсайтов (нужен открытый проект с обученной моделью на шаге Декомпозиция).
- **2026-06-20 (10) Фаза 3.1 — ядро советчика (LIVE-VERIFIED)** — `scenario-advisor.js` (разбор NL→config + применение к расходам + подтверждение). Тест 17/17. **Live:** Claude разобрал составной запрос «урежь ТВ на 20% и добавь диджиталу половину» → `{scenario, [TV:-20, Digital:+50]}` (правильно: «половину»→+50). Конвейер на реальном ответе: extractScenarioConfig → describeScenario («TV: уменьшить на 20%; Digital: увеличить на 50%; остальные без изменений») → applyChangesToMediaPlan → `{TV:[800000],Digital:[600000],OLV:[600000]}`. Главный риск Фазы 3 (надёжность NL→config) снят вживую. Дальше: 3.2 UI-поток + 3.3 live полного расчёта.
- **2026-06-20 (11) Фаза 3.2 UI + методология библиотеки** — UI «Что если» в InsightsPanel (двухэтапный: разбор→подтверждение→econ_scenario→интерпретация). svelte-check 0, коммит `900f9a1`. + **4 агента в Knowledge_Library** (Binet&Field, Sharp, McElreath, Kahneman, Knaflic): применено в промпт Авроры (TIER2_SYSTEM_RULES правила 6–10: без жаргона, неуверенность знака, причинность/OVB, защитный эффект охватных каналов, takeaway+действие). **Live-проверка:** вопрос «сократить ТВ?» — Аврора предупредила про отложенный/защитный эффект ТВ (Sharp), «высокий ROI = маленький канал» (насыщение), структура вывод+действие. Полный отчёт + roadmap → `Projects/AVRORA_METHODOLOGY_FINDINGS.md`. Тех-долг: зачистить служебный хвост Claude CLI «Все задачи выполнены.» из ответа.
- **2026-06-20 (12) Фаза 3.3 live + UX панели** — Полный поток советчика доказан на РЕАЛЬНОЙ обученной модели (проект `кагоцел-...-0706-26`, 5 каналов): `econ_scenario` (OLV −20%) → status ok, lift +1.9% (ci [−10.5, 15.8]), roas 0.85 (ci [0.36, 1.35]) — интервалы включают ноль/безубыточность = модель честно неуверена (методология в действии). Имена каналов с `\n` совпали с pkl. **ФАЗА 3 ПОЛНОСТЬЮ LIVE-VERIFIED.** + UX (запрос Антона): панель «Аврора» поднята НАВЕРХ панели инсайтов (над списком) через flex `order: -1` + перенос разделителей; live-verified avroraTop(139) < insightsTop(278).
- **2026-06-20 (15) Методология roadmap — caveat коллинеарности + тон honesty (McElreath)** — два высокоприоритетных пункта из `AVRORA_METHODOLOGY_FINDINGS.md`. (1) **Caveat коллинеарности** в советчике «Что если»: `scenario-advisor.js` `findCollinearPairs` (пары изменённых каналов с |r|≥`COLLINEAR_THRESHOLD`=0.65 из `validateData.correlationMatrix` `{labels, matrix}`) + `collinearityCaveat` → инжект в промпт интерпретации сценария (`InsightsPanel.runScenario`, перед factLines). Несовпадение имён канал↔метка → молчаливый пропуск (безопасный перекос). (2) **Тон honesty при тонких данных** (Ratio<4): `optimizer_honesty.py` ветка `thin` — «высокий риск переобучения» → «модель намеренно сдержана, опирается на priors, интервалы честно широкие, сузятся с ростом данных» (McElreath regularizing priors); только байес, OLS-ветка не тронута; caveat обогащён prior-нотой при thin. caveat_text идёт verbatim в UI + Tier 2 (INV-50). Тесты: scenario-advisor +8 collinear (25/25), optimizer_honesty +1 тон + 2 ассерта обновлены (14/14), полный vitest **823/823**, svelte-check **0**. Коммит `1bfa62f`. **Live-долг:** сверить `correlationMatrix.labels` ↔ `decomposeData.channels[].name` (имена с `\n`); прогнать оба эффекта вживую на обученной модели.
- **2026-06-20 (14) Push ветки + справка программы в контекст Авроры** — (а) Антон дал «push сейчас» → ветка `feat/ai-insights-tier2` запушена на origin `Aurora_Econometrica` с upstream (14 коммитов, секрет-скан diff чист, stable не тронут). (б) Roadmap-пункт «справка в контекст»: новый модуль `src/lib/program-help.js` — `PROGRAM_OVERVIEW` (карта программы: 6 шагов пайплайна, вкладки результатов, сценарии, частые проблемы, поддержка — выжимка `docs/USER_GUIDE_v2_1_0.md`, числа = методологические нормативы, не результаты) + `relevantTerms` (термины glossary по шагу пайплайна `STEP_TERMS` + матч аббревиатур/основ в вопросе) + `buildHelpContext`. Импорт `GLOSSARY` из glossary.js (термины НЕ дублируются — single source). `tier2-context.js`: help-контекст в промпт И в `grounding.jsonFacts` (нормативы справки grounded → страж не флагает легитимное цитирование порогов; выдуманный результат по-прежнему ловится, INV-50). Правило ТЕМАТИКА+СПРАВКА усилено. `InsightsPanel.askAI` передаёт вопрос. Вес справки ~1.3K токенов/запрос. **Self-audit находка** (мини-аудит перед коммитом): фильтр termKeywords ≥4 убивал матч 3-буквенных аббревиатур (ROI/CPU/MMM/ESS) по вопросу — снижен до ≥3. Тесты `program-help.test.js` (16) + дополнен `tier2-context.test.js`; полный vitest **815/815**, svelte-check **0**. Коммит `2230977` локальный (push нового — на approval). **Тех-долг:** `PROGRAM_OVERVIEW` — курируемая выжимка, при крупном обновлении руководства синхронизировать вручную (помечено в шапке модуля). Live-проверка ответов «по справке» — на dev-сессию с обученной моделью.
- **2026-06-20 (13) Стиль Авроры по live-feedback Антона** — Антон протестировал в реальном UI. Промпт TIER2_SYSTEM_RULES: деловой тон (убрано «Привет/я Аврора»/обращение по имени), ТЕМАТИКА (только эконометрика/MMM/программа+справка; off-topic→возврат), БЕЗОПАСНОСТЬ (не объяснять обход лицензии/защиты), ЧИСТОТА (без тегов [STATISTICAL]/слэш-команд/«Все задачи выполнены»). + `sanitizeAvroraText` на фронте (страховка-зачистка артефактов кабинета). **Live #6:** hasStatTag/SlashCmd/Greeting/DoneTail = все false, чистый деловой ответ. Тесты 12/12, svelte-check 0. Тех-долг хвоста закрыт. **Roadmap:** подать содержимое справки (glossary.js + руководства) в контекст для ответов строго «по справке» — сейчас Аврора знает программу из системного промпта кабинета econometrist лишь частично.
