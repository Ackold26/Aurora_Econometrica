# Личная верификация находок внешнего аудита (2026-07-12)

> Аудитор (сабагент без имени) выдал 5 находок по diff `1f76a14..HEAD`.
> Я (Маша) верифицировала КАЖДУЮ лично по коду/данным. Итог: **5/5 реальны**
> (необычно — обычно ~40% FP; аудитор доказывал прогонами, не рассуждением).
> Durable аудитора: `Projects/audit_findings_live.md`.

## Вердикт по каждой

### 1. CRITICAL — контракт данных кабинета мёртв в проде · CONFIRMED (полная цепочка)
`ChatPanel.svelte:702` строит `messageToSend = "/interpret-model" + buildProjectDataBlock()`,
блок начинается с `\n\n=== Данные проекта ===` (`econ-project-context.js:135-137`).
`lib.rs:711 resolve_slash_command`: first_line=`/interpret-model` → команда распознана,
`arguments` = весь блок данных → `template.replace("$ARGUMENTS", arguments)`, но **ни один
из 6 командных .md не содержит `$ARGUMENTS`** (проверено grep) → resolved===template →
**блок данных отброшен**. `lib.rs:1075` econometrist попадает в `else → final_message =
resolved_message` (инжекта как у media-analyst slides.json нет). Claude не видит ни числа
модели → галлюцинация (наруш. INV-50) или «шаг не пройден».
Почему тесты не поймали: `run_eval.mjs` шлёт message в `claude -p` через stdin напрямую,
минуя `send_message`/`resolve_slash_command` — тестирует не прод-путь.
**Блокер merge.**

### 2. HIGH — stripDecompTelemetry не вырезает поточечную графику · CONFIRMED
`econ-project-context.js:78`: `const { time_series, waterfall, ...rest } = dec` — вырезает
только 2 ключа. Фикстура decomposition.json содержит ещё `signed_factor_contributions`
(dict 16 факторов × `per_period` ≈ 496 чисел) + `hierarchical` — оба остаются в блоке →
раздувание промпта + сотни служебных чисел в grounded-множестве INV-50 (маскируют
галлюцинации). Проявится в полную силу ПОСЛЕ фикса Critical.

### 3. MEDIUM-1 — рассинхрон шкал шагов · CONFIRMED (корневой, шире блока)
STEP (`tier2-context.js:22`, из ПОРТА ассистента) = 5-шаг: IMPORT0 VALIDATE1 MODEL2
DECOMPOSE3 OPTIMIZE4 REPORT5.
PIPELINE_STEPS (`project-state.js:74`, из planning-mode) = 7-шаг: …optimize4 **planning5
report6**. `$pipelineCurrentStep` = индекс PIPELINE_STEPS.
Совпадают 0-4, расходятся 5-6 (planning-mode вставил «Планирование»).
- `STEP_TERMS` (наш блок, `rag-query.js:28`) индексирован по STEP → на planning(5) даёт
  report-термины, на report(6) → undefined → DEFAULT_TERMS (тематизация отваливается).
- **`buildTier2Context` (ПОРТ, `tier2-context.js:193`) — тот же рассинхрон**: planning(5)
  ловит `case STEP.REPORT`; report(6) → `default` → отдаёт ВАЛИДАЦИЮ вместо
  model/decompose/optimize. Предсуществующий баг ветки (порт поверх planning-mode).
- `canAsk` (`InsightsPanel.svelte:345`) НЕ зависит от шага → шаги 5-6 достижимы, не теория.
Корень: STEP не согласован с PIPELINE_STEPS (single source of truth нарушен).

### 4. MEDIUM-2 — humanizeSource искажает атрибуцию на краях · CONFIRMED (низкая актуальность)
`rag-query.js:112`. Форматы `ГОД_Автор_Название` (beforeYear пусто → автор тонет в
названии) и нормативные `ГОСТ_Реклама_ГОД` (all-caps ГОСТ отфильтрован, «Реклама» ложно =
автор). Для ТЕКУЩЕГО corpus=econometrics (Jin_2017, McElreath_-_… — обрабатываются верно)
не проявляется; риск при нормативном корпусе / формате ГОД_Автор. Дефект краёв, не блокер.

### 5. LOW — focusChannelType мёртвый код · CONFIRMED
`buildRagQuery` принимает `focusChannelType` (CHANNEL_TYPE_TERMS), но единственный прод-вызов
`InsightsPanel.svelte:383` его не передаёт. Достижим только из тестов. Незавершённая фича.

## Развилки для Антона
- **Critical подход:** A) добавить `$ARGUMENTS` в 6 консультационных .md (хирургично,
  локально к econometrist) vs B) правка `resolve_slash_command` (дописывать arguments при
  отсутствии `$ARGUMENTS` — общая семантика для всех 13 кабинетов, риск регрессий).
- **Medium-1 скоуп:** корневой (согласовать STEP с 7-шкалой → чинит и STEP_TERMS, и
  buildTier2Context; трогает порт + тесты) vs узкий (только STEP_TERMS, buildTier2Context
  остаётся сломан на 5-6).

## ФИКСЫ ПРИМЕНЕНЫ (2026-07-12, решение Антона: Critical=A, Medium-1=корневой)

Все 5 находок починены, каждая с регресс-тестом. Гейты: **cargo 188 · vitest 1152 · svelte-check 0 ошибок**.

1. **Critical (A):** `$ARGUMENTS` добавлен в 6 консультационных .md (interpret-model,
   why-channel, explain-ratio, pilot-design, next-quarter-plan, data-gaps) — блок данных
   теперь доезжает через resolve_slash_command. Тесты Rust `resolve_slash_tests` (3):
   подстановка данных, документирование контракта (без плейсхолдера теряется), инвариант
   «6 промптов содержат $ARGUMENTS» (регресс-детектор — закрывает дыру эвал-харнеса,
   который шёл мимо send_message).
2. **High:** `stripDecompTelemetry` вырезает + `signed_factor_contributions` (~496 чисел
   per_period) и `hierarchical` (служебный конфиг). Медиа-вклады дублированы в channels[]
   → INV-50-safe. Тест расширен.
3. **Medium-1 (корневой):** `STEP` (tier2-context.js) согласован с 7-шкалой PIPELINE_STEPS
   (+PLANNING=5, REPORT 5→6); `buildTier2Context` +case PLANNING; переиндексированы ОБА
   `STEP_TERMS` (rag-query.js + program-help.js — третья таблица, тоже была рассинхронена).
   2 регресс-теста (planning/report тематизируются; buildTier2Context planning даёт сводку,
   не валидацию).
4. **Medium-2:** `humanizeSource` — границы года (не ловит псевдогод из большего числа),
   ГОД_Автор (фамилия не тонет), ALL-CAPS ГОСТ/ФЗ (не ложный автор). 3 теста краёв.
5. **Low:** `focusChannelType` оживлён — `detectChannelType(вопрос)` по основам слов
   (reach/performance), подключён в InsightsPanel askAI. 4 теста.

### Follow-up для Антона (НЕ сделано, вне worktree/скоупа)
- **Мерж:** ветка сцеплена с econ-kpi-units + econ-planning-mode. После мержа
  `check_cabinet_drift.py --strict-pair` сработает в основном дереве — сверить.
- **Портирование Critical — НЕ ТРЕБУЕТСЯ (решение Антона 2026-07-12):** кабинет-эконометрист
  развивается ТОЛЬКО внутри MMM-оптимайзера (продукт Econometrica), за его пределами — не
  развиваем. Critical завязан на гейт `$isEconometrica` (ChatPanel:697), true ровно в этом
  продукте, и здесь он закрыт. Копии econometrist в других репо (Creative Hub, Insights Hub,
  AI_APP_AGENCY — архив) заморожены → портирование не нужно. Hub-копии cabinet-drift —
  информационно, не трогаем.
- **Доставка промптов в прод:** dev берёт .md из New_AI_Agency напрямую; прод — из vault
  (content-pack). Для прод-редакции нужна пересборка content-pack (регламент релиза).
