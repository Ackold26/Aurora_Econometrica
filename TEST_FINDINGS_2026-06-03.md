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
