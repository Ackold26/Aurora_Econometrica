---
tags: [testing, live-gui, visual-audit, dom-driven, autonomous]
type: test-log
date: 2026-06-03
method: DOM-driven (tauri-plugin-mcp-bridge port 9223) + probe-first
---
# Econometrica MMM Optimizer — глубокий визуальный аудит (DOM-driven, skill visual-audit)

**Объект:** dev master `c21079b` (bridge поверх плановых фиксов v2). **Метод:** DOM-driven через мост
(snapshot/find/interact-по-ref/execute_js + IPC), probe-first для математики. **Машина:** порты
5173/7529/9223 — мой инстанс, параллельной Aurora-сессии нет.

**Контекст фиксов на master (verify что ДЕРЖАТСЯ):** Волна 1 (`3f6d744` MQS-1/MQS-2/GRAM-1/NUM-1/LANG-1),
REC-1 (`a45fd62`), STATE-1 (`f864041`), англицизм-свип (`2f14a1b`), SEV-1 (`f816704`+`fbe355a`),
GS-1 proportional (`3b59a6e`), GS-2+INPUT-1 (`f462418`), ONBOARD-1 (`1aa7424`), NAV-2 (`0577798`),
3A CPP Manager (`1619c0f`) + Expert (`dda51f9`).

## NEXT (recovery при компрессе)
→ СЕССИЯ ЗАВЕРШЕНА (см. Сводку внизу). Отложено: multi-client live + полный интерактив Эксперт +
  LOAD-1 fix — все требуют свежего импорта Excel (нативный диалог через DOM не водится → desktop-control fallback).

## Категории
🔴 краш/блокер · 🟠 функц. баг · 🟡 UX-трение · 🔵 достоверность (INV-50) · 💡 идея · ✓ POS · ⤴ регрессия-verify

---

## Phase 0 — probe (математика на реальных pickle / код-пруф)

- 🟠🔵 **REC-1-GAP (НОВОЕ, high-value, код-пруф + нужна live-сверка)** — фикс REC-1 (`a45fd62`)
  не срабатывает на РЕАЛЬНЫХ данных: предикат детекта подозрительного канала расходится с движком.
  - **Код-пруф:** `insights-rules.js:1799` и `:2078` строят `suspicious` через `/подозрительно/i.test(c.verdict)`.
    Реальный decomposer (`engines/decomposer.py:120-121`) для unit_smell-канала с ROI>50 эмитит
    `verdict='ROI завышен (не рубли?)'` — подстроки «подозрительно» НЕТ (греп sidecar = 0 «подозрительно»).
    Persisted `decomposition.json` Кагоцел: TRPs `verdict="ROI завышен (не рубли?) (широкий ROI-интервал)"`,
    `unit_smell:true`, `roi:12186`, `action:"Scale"`.
  - **Следствие:** на реальных данных `suspicious=[]` → REC-1 `effectiveClean`/`activeSat`-исключение/
    аннотация «⚠ не-денежные единицы» И секция-5 unit_smell-предупреждение (`:1890`) **молчат**.
    TRPs снова может стать «лучший по mROAS» / раздуть «зона роста» — т.е. ROI-1/2 не закрыт на реале.
  - **Почему vitest зелёный:** `insights-rules-rec1.test.js:29` подаёт `verdict:'подозрительно высокий ROI...'`
    — строку, которую движок НЕ производит → тест проверяет несуществующий контракт («фикстура врёт»).
  - **Предлагаемый фикс:** детект по флагу/смыслу, не по тексту: `suspicious = decChannels.filter(c =>
    c.unit_smell === true || /не рубли|завышен|подозрительно/i.test(c.verdict||''))` (оба места :1799,:2078);
    тест переписать на реальный verdict движка `'ROI завышен (не рубли?)'` ИЛИ на `unit_smell:true`.
  - **LIVE-ПОДТВЕРЖДЕНО (Оптимизация, обученный Кагоцел):** инсайт рендерил «Предельная отдача (ROI):
    **лучший TRPs бренд (9550.62×)**, … Разброс 6275× — есть реальный потенциал перекладки» + «7 канала
    в зоне роста» + секция-5 warn МОЛЧАЛА (0 хитов «подозрительно»). ROI-1/2 НЕ был закрыт на реале.
  - **✅ ИСПРАВЛЕНО + ВЕРИФИЦИРОВАНО ВЖИВУЮ (фикс этой сессии):** `insights-rules.js:1799,2078` детект
    `c.unit_smell === true || /подозрительно/i.test(verdict)`; тест `insights-rules-rec1.test.js`
    переписан на реальный verdict движка + `unit_smell:true`. После reload инсайт: «лучший **Статьи**
    (64.95×)», «**6 каналов** в зоне роста», «**⚠ 1 канал с подозрительно высоким ROI**» — TRPs исключён
    из лидеров, защитное предупреждение сработало. vitest 14/14 ✓.
- 🟡 **GRAM-2 (НОВОЕ, исправлено по ходу)** наивная плюрализация `канал${n>1?'а':''}` давала «7 канала»
  (для 5+ нужно «каналов»). Места: `insights-rules.js:1441,1452,1829`. Фикс через `pluralizeRu` (импортирован,
  тест i18n зелёный) + verb-agreement «работает/работают», «перенасыщен/перенасыщены». LIVE: «6 каналов» ✓.

## Phase 3 — широкий-тонкий проход

### 🟠 LOAD-1 (НОВОЕ, high-value, код-пруф + live) — переключение проекта не восстанавливает роли
- **Repro:** ProjectSelector ▾ → выбрать сохранённый обученный проект (`...0206-26`). Результаты
  (Модель/Декомпозиция/Оптимизация) грузятся ✓, но Валидация показывает «Целевая метрика не определена»,
  «Медиа-каналы не обнаружены», а Декомпозиция — ложный баннер «⚠ устарела … Контрольные: было 4, стало 0,
  KPI: "Продажи в руб. бренд" → "»".
- **Код-пруф:** `src/lib/components/ProjectSelector.svelte:84-94` `selectProject()` —
  `project_activate`+`project_get`+`resetPipeline(id)`, далее `project_stats` с комментарием
  **`// TODO: populate pipelineState from stats`** — роли/KPI/каналы НЕ гидрируются в pipelineState.
  project.json при этом содержит `kpi_column`+`media_columns`(7)+`control_columns`(4).
- **Следствие:** реоткрытие завершённого проекта выглядит как «устарело/переобучите» → пользователь
  может зря переобучить (потеря времени) или потерять доверие к сохранению. Также ломает live-проверку
  любых роль-зависимых экранов (SEV-1/CPP-гейт/NAV-2) при загрузке — их надо проверять свежим импортом.
- **Severity:** 🟠 функц. **Пометка:** РЕШЕНИЕ АНТОНА — реализация TODO трогает load-flow (риск), не чиню
  вслепую. Фикс: в `selectProject` после `project_get` гидрировать роли из project.json (kpi/media/control)
  в pipelineState ДО stale-проверки декомпозиции. Нужен test-first на восстановление ролей.


### Главный экран
- ⤴✓ **LANG-1 ДЕРЖИТСЯ**: на главной карточке pipeline по-русски «Импорт → Валидация → Модель →
  Декомпозиция → Оптимизация → Отчёт» (был англ. на 2026-06-02). Fix `3f6d744`/`2f14a1b` подтверждён.
- 🟡 **TITLE-1** (новое, минор): `document.title = "AI Agency"` (реликт форка agency-кодовой базы);
  localStorage theme-ключ = `ai-agency-theme`. Окно/таб показывает чужой продукт. Место: `src/app.html`
  (`<title>`) + ключ темы в inline-script `app.html`. Фикс: «Aurora Econometrica» + ключ `econometrica-theme`.
  Чинибельно сейчас (после грепа реальных мест ключа).


### Регрессия — прошлые фиксы (verify ✓/✗)
- ⤴✓ **LANG-1** ДЕРЖИТСЯ (live): pipeline по-русски на главной карточке.
- ⤴✓ **GS-1** ДЕРЖИТСЯ (probe `_probe_audit.py` на обученном Кагоцел): `build_proportional_forward`
  монотонен (139M→10.11B … 559M→12.29B), `optimize_inverse` → **achievable=true** для достижимых
  целей (10.19B/11.89B — ниже/около текущих), чистое «недостижима в доступном диапазоне бюджета»
  для +20%. Раньше (2026-06-02) — «non-monotonic/недостижимо ВЕЗДЕ». GS-1 закрыт на реале.
- ⤴✓ **MQS-1** код-пруф + pytest (`test_diagnostics_verdict.py` зелёный): tier weak/poor + thinness_cap
  + r²≥0.7 → «высокий fit … вероятный признак переобучения», НЕ «только 98%». (Live weak-tier не
  воспроизвёлся — probe n_params=7 даёт ratio 4.4≠app 1.2; полагаюсь на тест+код.)
- ⤴✓ **3A CPP-гейт ОБА ПУТИ** код-пруф: Manager — `allChannelsConfigured` (ValidateStepV13:774-788,
  physical+ROI требует unit_cost>0 → кнопка `disabled`); Expert — `handlePerChannelConfirm`+`expertCppMissing`
  (:451-466, return+баннер `role="alert"`). + regression-test `detect-channel-unit-type-3a.test.js` зелёный.
- ⤴✓ **SEV-1 / MQS-2 / GRAM-1 / NUM-1** — фронт/бэк, покрыты зелёными тестами (vitest 604 / pytest 320)
  + код-пруф диффов (`f816704`/`fbe355a`/`3f6d744`). Live-сверка ролей-зависимых экранов блокирована LOAD-1.
- ⚠ **ONBOARD-1 / NAV-2** — НЕ верифицированы live: требуют чистого first-run (ONBOARD-1) и свежего
  импорта с ролями (NAV-2 подшаги Валидации). Код фиксов на master (`1aa7424`/`0577798`); live отложено.

### Новые классы багов (DOM-driven)
- 🟡 **TITLE-1 + a11y-announcer** (a11y-дерево, present-but-invisible) — НАЙДЕНО + ✅ ИСПРАВЛЕНО (см. выше).
- 🟠 **LOAD-1** (state-ассерт через execute_js + код-пруф) — НАЙДЕНО, документировано (Антону).
- **IPC-мониторинг — НЕ функционален в этой связке:** `ipc_monitor`/`ipc_get_captured` вернули `[]` и для
  SPA-invoke (ProjectSelector switch), и full-reload стирает hook. bridge 0.10 — класс «двойной/failed
  invoke» этим инструментом не проверен. Заметка в skill-evolution.
- a11y-дерево главного/пайплайна — чистое: интерактивные элементы названы, степпер с `/description`,
  disabled-состояния корректны. Без button-без-name/дублей roles.

## Само-аудит сделанной работы (по запросу Антона) — ЗАВЕРШЁН
Метод: само-аудит + **независимый адверсариальный ревью-агент** (verify каждую находку против кода).
Агент **подтвердил ядро REC-1-GAP фикса корректным и протестированным** (детект-проводка end-to-end через
Rust, тест эмпирически ловит регрессию, 604/604) и вскрыл **completeness-пробел**: один корень
(коронование unit_smell-артефакта «лучшим») имел **5 мест манифестации**, мой фикс `84767e5` закрыл 2.

**✅ Закрыты остальные 3 (коммит `20e7ddb` тег `v-fix-rec1-gap-crosslayer`):**
- **F1 (фронт `decomposeInsights`, insights-rules.js)** — соседняя ф-я экрана Декомпозиции коронует
  «Лучший ROI: TRPs 12186× … можно увеличить инвестиции» (все 3 ветки legacy/count/effectiveness), без
  оговорки. Агент воспроизвёл эмпирически. Фикс: фильтр `c.unit_smell!==true` из лидеров + typedef. +vitest.
- **decomposer.py:825 (backend insight Декомпозиции)** — `top=channels[0]`=артефакт (сорт ROI убыв. :715).
  Фикс: `top` среди не-unit_smell. **Probe Кагоцел: insight → «Статьи самый эффективный (77.5×)», TRPs
  исключён** (crowns_smell=false, recommends_into_smell=false). ✓
- **F2 (narrative_adapter.py:508, экспорт PPTX/HTML)** — `hero=by_mroas[0]`=артефакт → клиентский «перераспределить
  N млн в {hero}». Фикс: hero среди не-unit_smell, fallback.

**✅ GRAM follow-up (в `20e7ddb`):** F3 — мой verb-agreement врал для 21/101 («21 канал работаЮТ») → `pluralizeRu`;
F4 — 3 соседних наивных плюрализации (вкл. unit_smell-warnings) → pluralizeRu.

**✅ F5 (`6a4f7ea` тег `v-fix-title-canonical`):** TITLE «Aurora Econometrica»→канон «Aurora **AI** Econometrica».

**Подтверждено агентом и OK (не трогал):** детект-проводка ядра, optimizeInsights post-state, name-match
dec↔opt, graceful degradation на legacy pickle, отсутствие over-trigger, валидность теста (revert→3 asserts FAIL).
**Гейты:** svelte 0E/171W · pytest 320 · vitest 605. Этот пробел — живая иллюстрация нового skill-урока «кросс-слой».

## Сводка (Phase 5, 2026-06-03 DOM-driven)
**Объект:** dev master `c21079b`→(фиксы сессии). Метод: DOM-driven мост 9223 + probe-first. Машина —
мой инстанс, без параллельной Aurora-сессии.

**ИСПРАВЛЕНО + ВЕРИФИЦИРОВАНО (3 коммита+теги, локально на master, НЕ запушено):**
- 🟠🔵 **REC-1-GAP** (`84767e5`): unit_smell-детект по флагу, не по тексту verdict → TRPs больше не
  «лучший по mROAS», секция-5 warn сработала. Live ✓ + vitest. Самая ценная находка (ROI-1/2 не был
  закрыт на реале, хотя фикс `a45fd62` числился сделанным; тест врал на строке verdict, что движок не эмитит).
- 🟡 **GRAM-2** (в `84767e5`): плюрализация «7 канала»→«6 каналов» (pluralizeRu) + verb-agreement. Live ✓.
- 🟡 **TITLE-1** (`6e62569`): document.title «AI Agency»→«Aurora Econometrica» (фикс a11y-announcer). Live ✓.

**ВЕРИФИЦИРОВАНО ЧТО ДЕРЖИТСЯ:** LANG-1 (live), GS-1 (probe), MQS-1 (pytest+код), 3A CPP оба пути (код+тест),
SEV-1/MQS-2/GRAM-1/NUM-1 (тесты).

**НОВЫЙ БАГ К ПОЧИНКЕ (решение Антона — load-flow, риск):** 🟠 **LOAD-1** — переключение проекта теряет
роли (`ProjectSelector.svelte:94` TODO), ложное «декомпозиция устарела». Фикс не делал вслепую (safety-first).

**ОТЛОЖЕНО (блок: нативный файл-диалог через DOM + LOAD-1):** полный интерактив Эксперт (custom prior/
per-channel min-max live), multi-client (Венарус/MMX) live, ONBOARD-1 (чистый first-run), NAV-2 (подшаги).
→ отдельная desktop-control сессия ИЛИ после фикса LOAD-1 (тогда loaded-проекты верифицируемы DOM-driven).

**Гейты на конец:** svelte **0E**/171W · pytest **320** · vitest **604**. Все на baseline, 0 регрессий.

---

## LOAD-1 ИСПРАВЛЕН (2026-06-03, code-proof по плану precious-orbiting-kahan)

**Метод:** LOAD-1 доказан code-proof'ом (юнит-тесты на РЕАЛЬНЫХ project.json+decomposition.json Кагоцела),
GUI оставлен на одну финальную сверку. Корень подтверждён (2 слоя), не переоткрывался.

**✅ A+C (`499c2fc`, тег `v-fix-load1-roles-hydration-stale-guard`):** реконструкция ролей из project.json
когда нет validation.json (обученные проекты `data_file:null`).
- `applyProjectRolesToColumns` (column-roles.js) — инверсия buildProjectUpdates, precedence
  kpi>media>control>excluded, round-trip lossless по ролевым полям.
- `hydrateRolesFromProjectIfEmpty` (project-state.js) — врезка в `restoreProjectResults` (else-ветка
  `hasValidation`), race-safe (fallback `project_get`; не затирает реальный validateData), nObs из
  decomposition.dates → корректные RATIO/MQS (не 0).
- Guard C в `modelStaleStatus`: пустые роли / флаг `reconstructed_from_project_json` → stale=false
  (реконструированные роли = сам сохранённый конфиг → ложное «устарела» погашено).
- Тесты: `project-roles-hydration.test.js` (9, РЕАЛЬНЫЕ фикстуры: 7 media+4 control+1 kpi+16 excluded→unused,
  nObs=31, round-trip, race guard) · `model-stale-status.test.js` (+3).

**✅ B2 (`d07ce23`, тег `v-fix-load1-b-validation-persist`):** validation.json больше не теряется (будущие
проекты). Слой 1 корня: econ_validate форвардил bare project_id как project_dir → sidecar писал в
относительный CWD. Фикс: `resolve_project_dir_arg` (Rust) — None→None, абс→passthrough (backward-compat),
bare-id→`project_dir(id)` под path-traversal guard. Python harden: не пишет при неабсолютном пути (видимый
лог вместо молчаливой записи-не-туда). Тесты: cargo (5) + `test_validation_persist.py` (3).

**Адверсариальный ревью диффа (независимый агент) — верифицировано против кода:**
- date-колонка не реконструируется → **не регрессия**: `date_column` НЕ хранится в схеме project.json
  (нет поля ни в файле, ни в ProjectInfo) → реконструировать неоткуда; nObs из decomposition.dates, date-инсайты
  после переимпорта (graceful, как VIF). JSDoc уточнён для честности (INV-50).
- `project_get`→null → **не баг**: возвращает Err (не Ok(null)) → invoke бросает → ловится внешним try/catch
  в restoreProjectResults → graceful (как до фикса).
- Python logging `%s` → **ложная тревога**: корректная стандартная ленивая идиома.

**Wiring code-proof:** `project_load_results` отдаёт `validation`(null для Кагоцела→hasValidation=false→else) +
`decomposition`(31 дата). End-to-end путь реконструкции доказан без окна.

**Гейты:** cargo **145** (140+5) · pytest **323** (320+3) · vitest **617** (605+12) · svelte **0E**/171W. 0 регрессий.

**⏳ Осталось (live, мост 9223):** одна финальная GUI-сверка LOAD-1 (переключить проект → роли восстановлены,
нет «устарела», RATIO/MQS≠0) + Часть 2 плана (MQS-1/SEV-1/REC-1-F1 live, NAV-2, ONBOARD-1, Эксперт) + Часть 3
(multi-client Венарус/MMX через desktop-control-импорт).

---

## Широкий visual-audit после LOAD-1-фикса (2026-06-03, мост 9223, DOM-driven)

LOAD-1 разблокировал роль-зависимые экраны на loaded-проекте → verify-hold прошлых фиксов выполнен вживую
БЕЗ свежего импорта. Объект: обученный Кагоцел 0206-26 (7 каналов, не-денежный TRPs, R² 0.976, n=31).

**✅ ПОДТВЕРЖДЕНО ВЖИВУЮ (держится):**
1. **LOAD-1 (все 4 коммита)** — реальный путь Продолжить→pipeline→Валидация: роли восстановлены (KPI «Продажи
   в руб. бренд», 7 медиа, 4 контроля в сторе), баннеры «не определена/не обнаружены» ушли, ratio=2.82,
   MQS=75, nObs=31. Декомпозиция: НЕТ ложного «устарела» (guard C live). Весь pipeline (6 шагов) рендерится.
2. **REC-1-GAP F1** (Декомпозиция) — «Лучший ROI: **Статьи** = 77.49×», НЕ TRPs (TRPs 12186× помечен
   «ROI завышен (не рубли?)» = unit_smell, исключён из «лучшего»). mentionsTRPsBest=false.
3. **unit_smell-пропагация в Оптимизацию** — баннер «⚠ Не-денежные единицы: TRPs бренд (W 25-54)» +
   «Экстремальный ROI / большой разброс». Защитная пометка доходит до шага советов (ROI-1/2 family).
4. **Режим Эксперт↔Маркетолог** — тоггл чистый (expertMode true↔false, label синхронен, без краша,
   Отчёт рендерится в обоих).

**✅ ВЕРИФИЦИРОВАНА КАК BY-DESIGN (не баг):**
- Badge-счётчики подшага «Роли колонок» (Контроль 3/Не-исп 14 vs стор 4/16). Корень: `filteredColumns`
  (ValidateStepV13:600-617) намеренно скрывает count-unit колонки `/(в уп\.|в шт\.)/i` при денежном KPI
  (REORDER_SUBSTEPS design). Кагоцел: скрыты «Продажи в уп. конкуренты»(control)+«Продажи в уп. бренд»+
  «SOM в уп.»(excluded) = ровно 3. Счётчики = видимая таблица. Стор реконструкции корректен (28). НЕ дефект.

**📋 НАБЛЮДЕНИЯ (не подтверждённые баги, follow-up):**
- Отчёт: «ПРИРОСТ ОТ ОПТИМИЗАЦИИ +0.0%» на Кагоцеле (из pre-computed optimization.json). Может быть
  легитимно (уже-оптимальная аллокация) ИЛИ flat-response/CPP-артефакт — нужна живая ре-оптимизация.
- Отчёт: post-hoc MQS=50 «Слабое» vs prognosis MQS=75 на Валидации — разные метрики, проверить согласованность
  формулировок (не вводит ли «Слабое» в заблуждение при R²=0.976).
- Модель на loaded-проекте показывает config-панель (не diagnostics/MQS-1 view) — MQS-1 live не досмотрен
  (покрыт pytest+код ранее).

**⏳ ОСТАЛОСЬ (отдельный focused-блок — нужен свежий импорт через desktop-control файл-диалог):**
- Multi-client: Венарус, MMX, синтетические FMCG/OTC/недвижимость/ритейл (/sample-data) — полный pipeline,
  сравнение нарративов, MMX длинный ряд → flat-response Goal-Seek (#59).
- Эксперт глубоко: custom priors (ConfigPanel), per-channel min/max (Оптимизация), VIF-таблица
  (ExpertValidatePanel), CPP-гейт оба пути.
- ONBOARD-1 (чистый first-run), NAV-2 (подшаги), MQS-1 diagnostics live.

**Гейты на момент:** svelte 0E/171W · pytest 323 · vitest 617 · cargo 145. 0 регрессий.

---

## Multi-dataset блок (2026-06-03, DOM-driven, без desktop-control)

LOAD-1 разблокировал загрузку обученных проектов; импорт реплицирован DOM-driven
(`econ_data_preview`+`importData`+`project_create` — нативный диалог даёт лишь путь).

**✅ LOAD-1 реконструкция — ВТОРОЙ датасет (Венарус `венарус-ммх-0205-26--2`, 7 медиа+7 контролей):**
загружен через selectProject-путь (resetPipeline). vd 29 cols {media:7, control:7, kpi:1, unused:14},
reconstructed=true, **stale=false**, ratio=2.21, MQS=75, nObs=31. Декомпозиция: нет «устарела», нет ошибок,
«Лучший ROI: Social 7.35×» (разумный), главный драйвер TRPs по вкладу 33%, «95% базовые / 5% реклама».
Оптимизация рендерится. Реконструкция обобщается на ДРУГОЙ состав ролей. ✓

**✅✅✅ B2 (persist validation.json) — ВЕРИФИЦИРОВАН ВЖИВУЮ (ТРЕТИЙ датасет, MMX):**
свежий импорт `MMX 2021-2025 исходник.xlsx` [43×31] DOM-driven → создан проект `mmx-audit-43x31` →
autoRunValidate вызвал РЕАЛЬНЫЙ `econ_validate(projectId=bare-id)` → B2 резолвил bare-id→абс.путь →
Python записал **validation.json (54KB) в `projects/mmx-audit-43x31/results/`** (правильная папка, не CWD
сайдкара). Это ровно probe плана «Glob validation.json ≥1». **Цикл LOAD-1 замкнут:** существующие проекты
без validation.json → реконструкция (A); новые → validation.json персистится (B2) → реоткрытие через
hasValidation=true (без реконструкции). Аудит-проект удалён после теста.

**✅ SEV-1 (ratio severity) — ВЖИВУЮ на MMX (raw import, 22 авто-медиа):** ratio 1.65 (43 набл/26 предикторов),
label «Критически мало», severity «warning-high», issue «Ratio данных 1.7:1 — критически мало, модель почти
наверняка переобучится, β случайны» (severity critical). Честное предупреждение (INV-50) — валидация делает
работу. Пользователь уточнил бы роли (исключить Показы/Клики/Визиты, оставить Бюджет).

**📋 Мелкое наблюдение (низкий приоритет):** issue-сообщение «1.7:1» vs метрика 1.65 — косметический
рассинхрон округления (`round(ratio,1)` в тексте vs raw в badge).

**Покрытие датасетов:** Кагоцел (4 контроля) ✓, Венарус (7 контролей) ✓, MMX (22 raw-медиа, ratio-fail) ✓.
LOAD-1 A+C+wiring + B2 + guard C + SEV-1 + REC-1-GAP — все верифицированы вживую через мост 9223.

**Осталось (heavy, отдельный заход):** полный fresh train (MCMC) синтетики FMCG/OTC/недвижимость/ритейл +
MMX до Декомпозиции (flat-response Goal-Seek #59 на длинном ряду); Эксперт глубоко (custom priors/per-channel);
ONBOARD-1/NAV-2.

---

## Synthetic-truth аудит: «врёт ли продукт на числах» (2026-06-03)

**Метод (skill Phase 0 probe-first):** synth_fmcg_brand сгенерирован `tools/synthetic_pilot_data.py`
с ИЗВЕСТНЫМ ground truth (GROUND_TRUTH_FMCG). Probe пересчитал истинную декомпозицию КАК генерируются
данные (не наивно по β — tv обгоняет digital из-за adstock 0.70). Затем полный прогон РЕАЛЬНОГО движка
(import→validate→train MCMC 22.4с→decompose через Tauri-команды) и сверка.

**ВЕРДИКТ: математика движка ЧЕСТНАЯ, НЕ фабрикует. Нарратив переоценивал уверенность (исправлено).**

| Проверка | Эталон | Движок | Итог |
|---|---|---|---|
| Доминирование базы | 94.8% | 96.9% | ✓ восстановлено |
| Знак competitor (TARGET) | β −0.18 | β **−0.46** (отриц) | ✓ знак верен |
| Знак price | −0.04 | −0.09 (отриц) | ✓ |
| unit_smell физ.единиц | ooh+perf | ooh_trp+performance_clicks | ✓ flagged |
| Честная неопределённость | — | все «широкий ROI-интервал», roi_spread 57988 | ✓ |
| Ранг вкладов каналов | tv>digital>perf>ooh | perf>digital>ooh>tv | ✗ НЕ восстановлен* |

*Ранг не восстановлен, НО на медиа-сигнале ~5% (низкий S/N) и при честно-огромных интервалах —
ожидаемый предел данных, не фабрикация. Движок честно сигналит неопределённость.

**🔧 ИСПРАВЛЕНО (INV-50) — `decomposer.py` инсайт «самый эффективный канал»:**
Корень: digital ROI 0.04× получал ОДНОВРЕМЕННО вердикт «Глубоко убыточный» И инсайт «самый эффективный
канал (ROI 0.0×)» — прямое противоречие + `{:.1f}` печатал 0.04× и 0.02× как одинаковые «0.0×».
Фикс: извлечён `_build_channel_insight` (SSOT) + `_fmt_roi` (точность: |ROI|<1 → 2 знака). Гейт: если
лучший денежный канал сам убыточен (ROI < ROI_BREAKEVEN) → «Ни один канал не окупается напрямую (лучший —
X, ROI 0.04×); продажи в основном базовый спрос» вместо ложного «эффективный»; совет перераспределения в
убыточный top подавлен (ROI-1/2 класс). Тест `test_decomposer_insight_honesty.py` (8). pytest 331 (323+8).

**📋 КРОСС-СЛОЙ (export follow-up, тот же корень):** «самый эффективный канал» БЕЗ гейта живёт также в
`aurora_html/sections.py:634` (HTML hero) и `aurora_pptx/builder.py:744` (PPTX hero) — их hero-селекция
отдельная, нужен свой анализ профитабельности/unit_smell-гейта. GUI-первичный (decomposer) закрыт.

**Артефакты теста удалены** (probe + проект fmcg-truth-test). Гейты: pytest 331 · svelte 0E · vitest 617 · cargo 145.

### КРОСС-СЛОЙ INV-50 ЗАКРЫТ (HTML + PPTX hero)
`aurora_html/sections.py:623` + `aurora_pptx/builder.py:740`: «самый эффективный канал» гейтился только при
`honest_narrative` (media<10%) → при media≥10% И hero<breakeven (honest=False) убыточный hero корон(
тот же баг). Фикс: breakeven-гейт РАСЦЕПЛЁН от honest (`if hero_m < 1.0 and mode != 'effectiveness'` →
«лучший среди медиа, но под breakeven»), зеркалит decomposer. effectiveness-mode исключён (метрика=доля,
breakeven неприменим, прецедент all_below_breakeven). Все 3 слоя инсайта консистентны. pytest 331, импорт OK.

---

## Fresh-train end-to-end аудит (2026-06-04) — 2 реальных бага, невидимых на loaded-фикстурах

Свежий train→decompose→optimize реальной MMX (43 мес, money-каналы) через движок (мост 9223).

**🔴 БАГ-1 (HIGH) — NaN в result-JSON → Rust молча роняет → «модель не загружена».**
Корень: вырожденная/слабая модель даёт `r_hat_max/intercept/sigma=NaN`. `model-diagnostics.json`
писался голым `json.dump` (allow_nan=True) → литерал `NaN` (RFC 8259 violation). Python читает, но Rust
`serde_json` (strict) ПАДАЕТ → `project_load_results.read_json` (`.ok()...unwrap_or(Null)`) **молча**
отдаёт null → Отчёт «⚠ Данные не загружены: модель», хотя обучение прошло и файл валиден для Python.
Невидим на Кагоцел/Венарус (их diagnostics без NaN). `atomic_write_json` УЖЕ имел `allow_nan=False`
(аудит H-02 знал!), но result-JSON писались мимо него.
Фикс: `sanitize_nonfinite` (utils/safe_io, NaN/Inf→null, numbers.Real покрывает numpy) применён ко ВСЕМ 5
Rust-читаемым result-JSON (validator/modeler/ols_modeler/decomposer/optimizer). + defense-in-depth: Rust
`read_json` теперь логирует ошибку парса, не молчит. Тест `test_sanitize_nonfinite.py` (7). Live: 9 NaN→null
→ Rust грузит модель → Отчёт работает.

**🟠 БАГ-2 (INV-50, кросс-слой) — «ПРИРОСТ ОТ ОПТИМИЗАЦИИ +0.0% / план уже оптимален».**
OptimizeStep уже честен (dual-pillar media/KPI, фикс 2026-05-04), но ReportStep брал только canonical
`expected_lift_pct` (тонет в органической базе 90-95%) → при lift≤0.5 писал «**план уже оптимален**», хотя
`media_only_lift_pct=+4.4%` (переаллокация реально улучшает медиа-отдачу). Фикс не пропагирован в Отчёт.
Фикс: ReportStep — `liftDrownsInBase` (lift<3 & media>2 & разрыв>2) → метрика «+0.7% · эффективность медиа
+4.4% (база доминирует)» + интерпретация «не потому что план оптимален, а потому что база доминирует».
Зеркалит OptimizeStep. Live-подтверждено на MMX (canonical 0.7% / media 4.4%).

**Наблюдение:** MMX money-модель R²=−1.73 (хуже среднего) — слабый сигнал на месячных данных с летними
пропусками; не баг, ожидаемо. Подтверждает: «+0.0% прирост» = эффект доминирующей базы, не дефект оптимизатора.

**Гейты:** pytest 338 (331+7) · cargo 145 · svelte 0E/171W. Тест-проект удалён.
