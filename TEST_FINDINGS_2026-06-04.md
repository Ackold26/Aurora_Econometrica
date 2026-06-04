---
tags: [testing, live-gui, visual-audit, dom-driven, autonomous]
type: test-log
date: 2026-06-04
method: DOM-driven (tauri-plugin-mcp-bridge port 9223) + probe-first
session: ONBOARD-1 / NAV-2 / synthetic-truth (OTC/retail/real-estate) / Эксперт-интерактив
---
# Econometrica visual-audit (продолжение) — ONBOARD-1, NAV-2, synthetic-truth, Эксперт

**Объект:** dev `2.1.0-rc7` свежий `npm run tauri:dev` (мост 9223, сидкар PID-свежий с NaN-фиксами).
**Машина:** убиты вчерашние зомби (vite/sidecar/bridge), запущен чистый dev. Параллельной Aurora-сессии нет.
**Гейты baseline:** svelte 0E/171W · pytest 338 · cargo 145 · vitest 617.

## Категории
🔴 краш/блокер · 🟠 функц. баг · 🟡 UX-трение · 🔵 достоверность (INV-50) · 💡 идея · ✓ POS

---

## ДЕТАЛЬНЫЙ САМО-АУДИТ (3 независимых адверсариальных агента, 2026-06-04) — ещё дыра в NAV-2 фиксе

По запросу Антона — критический аудит проделанной работы. 3 параллельных агента (NAV-2 completeness /
ONBOARD+InsightsPanel регрессии / skill+методология), каждая находка верифицирована против кода. Само-аудит
поймал то, что forward-e2e пропустил (он шёл только ВПЕРЁД) — третья итерация неполноты фикса.

**🔴🔵 HOLE-1 (goBack/reload) — ПОДТВЕРЖДЁН Agent 1 + Agent 2, ИСПРАВЛЕН:**
- `completeStep(1)` — **one-way latch** (никогда не ре-локает), а футер «Далее» (`+layout goNext`/`canGoNext`)
  проверяет только `stepMeta[2] !== 'locked'`, НЕ `allChannelsConfigured` (CPP-гейт). Контентная кнопка
  gated (`:1165 disabled={!allChannelsConfigured}`), футер — НЕТ.
- **Repro goBack:** дошёл до подшага 3 (Модель ready) → goBack на 2 (`goBack`/done-dot nav, не ре-локают
  stepMeta) → убрал CPP физ.канала → футер «Далее» активен → перескок на Модель без unit_cost = ROI-артефакт.
- **Repro reload:** reload посреди валидации → `reconcileStepMetaFromDisk` ставит Модель 'ready' (validation.json
  на диске), но `unit_costs` НЕ персистированы (персист в handleContinue ПОСЛЕ CPP) → футер → Модель без CPP.
  Backstop на шаге Модель отсутствует (`ModelTrainingStep` грепнут на CPP/unit_cost = 0 совпадений).
- **Фикс:** `lockStep(step)` (project-state.js, ре-лок 'ready'→'locked', не трогает 'complete'/'error') +
  reactive guard в ValidateStepV13: `$effect` ре-локает Модель пока `subStep<3 || !allChannelsConfigured`
  (покрывает И goBack И reload-с-subStep=-2). Легитимный разлок — только handlePerChannelConfirm. Guard idle
  на forward-flow (subStep=3 + CPP заполнен → условие false → forward e2e не затронут).
- **Тесты:** +3 в `nav2-footer-gate.test.js` (lockStep: ready→locked, не трогает complete, идемпотентен).
  Гейты: vitest 6/6 · svelte 0E/171W. guard в bundle (fetch-verified). **goBack-live-verify: pending** —
  блокирован хрупкостью webview-репликации (UI рассинхрон: Валидация не монтируется активной через
  программный stepMeta-setup; та же грабля); рекомендация — driver_session WebDriver регрессия (аутентичные
  клики goBack) след.заход. Логика guard верифицирована (forward idle / goBack срабатывает) + unit + bundle.

**🟡 Документационный дрейф (Agent 2 B1) — ИСПРАВЛЕН:** комментарии «completeStep(1) перенесён в handleContinue»
(ValidateStepV13 autoRunValidate :232-236, InsightsPanel :217) устарели — реальное место handlePerChannelConfirm.

**🟡 Мёртвый код (Agent 2 A1) — ИСПРАВЛЕН:** `hasCompletedOnboarding` импорт в `+layout.svelte:7` стал unused
после удаления авто-OnboardingOverlay (грепнут — только импорт, не используется) → убран. OnboardingOverlay —
компонент-сирота (by-design ONBOARD-1, сохранён в кодовой базе).

**✓ Проверено OK (Agent 1+2, by-design):** Expert (тот же handlePerChannelConfirm за CPP-гейтом), legacy
ValidateStep (мёртв — `useDerivedModeUX=writable(true)`, нет .set(false)), count-KPI (через value-step→
handlePerChannelConfirm), loaded-проекты (reconcileStepMetaFromDisk независим, не затронут), effectiveness/manual
(CPP неприменим by-design), subStep=3 единственный путь (handlePerChannelConfirm), setStepError(1,null)
семантически безопасен, степпер монотонен (PipelineStepper i<curStep→complete, не зависит от Валидация='complete').

**💡 Методология (Agent 3 C) — step-unlock SSOT (предложение Антону, НЕ реализовано):** корень того, что фикс
был неполным 3×, — один gate (разблокировка Модели) реализован N императивными `completeStep(1)` в N
компонентах + футер проверяет только `locked`. Предложение: декларативный `STEP_PRECONDITIONS[N]` (чистый
предикат «можно ли разлочить шаг N» на основе явных store-условий, включая CPP-гейт ОДНОЙ clause) +
`recomputeStepGates()` на derived-подписке; компоненты перестают звать `completeStep`, только мутируют data-сторы.
Убивает класс «N рассинхронизированных источников» + LOAD-1-класс. Миграция: validate→model boundary первым
(под nav2-footer-gate.test). Решение за Антоном (средняя миграция, корневой фикс).

---

---

## ONBOARD-1 — чистый first-run (localStorage), DOM-driven ✅ ИЗМЕРЕНО

**Метод:** удалены 11 онбординг-ключей (НЕ трогая 11 проектных) → `location.reload()` → подсчёт
механизмов программно (`webview_execute_js`, не глазами) + 1 скриншот для визуальной оценки наслоения.

**Карта механизмов first-run (полная):**
| Механизм | Ключ persist | Авто-старт | Где | Объём |
|---|---|---|---|---|
| OnboardingOverlay | `ai-agency-onboarding-complete` | ✓ | главная `/` | 4 слайда (что за продукт) |
| FirstRunTour | `aurora.firstRunTourCompleted` | ✓ | `/pipeline` | 8 шагов (где что нажимать) |
| PipelineWhyThisStep ×6 | `aurora.whyThisStep.visited.*` | ✓ auto-open | каждый шаг | 6 панелей (контекст шага) |
| IntroTutorial | `aurora-intro-completed` | ✗ (фикс 2026-06-02 убрал авто) | вручную | 8 слайдов теории MMM |
| per-step coach-marks | `aurora-econ-onboarding-enabled` | приглушены first-run | шаги | — |

**✓ ВЕРДИКТ: НЕ одновременный навал «4 модалки», а координированная ПОСЛЕДОВАТЕЛЬНАЯ воронка.**
- Главная `/`: ровно **1** механизм (OnboardingOverlay, z=1000). «Пропустить» персистит ключ ✓.
- `/pipeline` first-run: FirstRunTour (модал z=9100, backdrop) ПОВЕРХ + WhyThisStep import (inline) ПОД.
  Скриншот: **backdrop FirstRunTour корректно фокусирует** на туре, WhyThisStep затемнён → откроется
  ПОСЛЕ закрытия тура. Визуального хаоса нет.
- IntroTutorial авто-старт **убран** (фикс `+layout.svelte:95-97` держится) — открывается вручную
  («Что такое MMM?» на главной / Settings). ✓
- coach-marks приглушены на first-run (`shouldShowOnboarding` → false при `firstRunTourCompleted===null`). ✓
- Исходная находка 2026-06-02 «4 онбординга подряд ~20 шагов» сокращена до **3 авто-механизмов**
  (IntroTutorial выбит из авто), наслоение IntroTutorial устранено.

**🟡 Остаточное трение (продуктовое суждение — РЕШЕНИЕ АНТОНА, не слепой фикс):**
1. **Объём обучения нового юзера велик:** OnboardingOverlay(4) + FirstRunTour(8) + WhyThisStep(6) ≈ 18
   обучающих экранов до первой работы. Координировано (каждый со skip/persist), но объёмно.
2. **Концептуальный дубль welcome:** OnboardingOverlay (главная, «Aurora Econometrica MMM Optimizer,
   MMM без программирования…») и FirstRunTour (pipeline, «Добро пожаловать в Aurora, инструмент для MMM…»)
   оба — вводный welcome про продукт. OnboardingOverlay сам анонсирует FirstRunTour (слайд 3: «каждый шаг
   с встроенным онбордингом»). Намеренная воронка концепция→практика, но первый экран частично дублирует.
3. **Узкая координация (низкий риск, фикс-кандидат):** WhyThisStep import auto-open срабатывает
   ОДНОВРЕМЕННО с FirstRunTour (хоть под backdrop) → после закрытия тура WhyThisStep уже развёрнут.
   Кандидат: приглушить WhyThisStep auto-open пока `firstRunTourCompleted===null` (зеркало coach-marks
   паттерна `shouldShowOnboarding`). `PipelineWhyThisStep.svelte:46-54` — guard не учитывает firstRunTour.

**Варианты решения (на Антона):**
- (A) Оставить как есть — воронка координирована, не хаос.
- (B) Узкий фикс координации #3 (WhyThisStep guard на firstRunTour) — убирает под-слой, низкий риск.
- (C) Убрать концептуальный дубль: сократить OnboardingOverlay до 1-2 слайдов ИЛИ убрать авто-старт
  OnboardingOverlay (FirstRunTour покрывает welcome). Продуктовое.

**🟢 РЕКО (дано Антону 2026-06-04, ждёт его финального GO):** убрать **авто-старт OnboardingOverlay**
(`+page.svelte:183` `{#if !$hasCompletedOnboarding}`) + узкий фикс координации **WhyThisStep**
(`PipelineWhyThisStep.svelte:46-54` — не auto-open пока `aurora.firstRunTourCompleted===null`).
Обоснование по уникальности: OnboardingOverlay слайд-1 дублирует FirstRunTour шаг-1, слайды 2-4
(теория NumPyro/как начать/отчёты) дублируют IntroTutorial → собственного уникального контента нет;
FirstRunTour (практика, подсветка кнопок) + WhyThisStep (per-step контекст) + IntroTutorial (теория
opt-in) уникальны и покрывают всё. Компонент OnboardingOverlay не удалять — оставить доступным вручную.
Итог: ~14 экранов вместо 18, 0 концептуального дубля, без наслоения FirstRunTour+WhyThisStep.

---

## NAV-2 — навигация подшагов Валидации ✅ ПРОВЕРЕНО (DOM-driven, FMCG-синтетика)

**Метод:** импорт реплицирован webview (econ_data_preview + importData.set + project_create +
completeStep(0)), проект `nav2-test-fmcg` (FMCG-синтетика 36×9, KPI sales_rub, 2 физ.канала
ooh_trp/performance_clicks в ROI-режиме). Навигация инструментирована subscribe-логгером на
validateSubStep/pipelineCurrentStep. ValidateStepV13 авто-валидировал при монтировании → Валидация
complete, Модель ready.

**✓ КОРРЕКТНО (держится):**
1. **Контентная «Далее ▶»** двигает подшаг: -2 (Целевая метрика) → -1 (Роли колонок) → 2 (Метрики
   каналов; подшаг 1 «value» пропущен — KPI монетарный, skipValueStep). navlog подтвердил.
2. **Подшаг -1 (Роли) — гейт работает:** футерная «Далее ▶» **disabled** + tooltip «Сначала нажмите
   «Подтвердить роли» ниже»; контентная заменена на «Подтвердить роли →»; фантомных «Далее» нет
   (totalNext=1). `rolesNotConfirmed` (step==1 && subStep==-1) корректно блокирует футер.
3. **3A CPP-гейт срабатывает на КОНТЕНТНОМ пути:** после «Подтвердить роли» → подшаг 2 «Метрики
   каналов» с alert «⚠ 2 канала с физическими метриками … для ROI режима их нужно перевести в ₽».

**🔴🔵 НАХОДКА — NAV-2/3A-FOOTER-BYPASS: футерная «Далее ▶» обходит 3A CPP-гейт.**
- **Repro (live):** на подшаге 2 (Метрики каналов), CPP-поля физ.каналов ПУСТЫЕ (placeholder
  «~2.8 млрд ₽» / «~908 млн ₽»), футерная «Далее ▶» **АКТИВНА** (disabled=false) → клик → переход
  pipelineCurrentStep 1→**2 (Модель)**. На Модели: «Запустить модель» **активна**, медиа-каналы
  включают ooh_trp/performance_clicks, **0 упоминаний CPP/физ.единиц** (`unitCosts={}`,
  `perChannelInput={}`). Обучение → физ.каналы в ROI без unit_cost = ROI-артефакт (класс ROI-1/2,
  TRPs 12186×).
- **Хуже:** футерная активна и с подшага **-2** (сразу после авто-валидации Модель='ready' →
  validateIncomplete=false, rolesNotConfirmed=false при subStep≠-1) → юзер может перейти на Модель,
  минуя ВСЕ подшаги (роли, KPI-confirm, метрики каналов, подтверждение).
- **Код-пруф:** `pipeline/+layout.svelte:165` `goNext()` проверяет ТОЛЬКО
  `stepMeta[next].status !== 'locked'` — ни CPP, ни allChannelsConfigured, ни завершённость подшагов.
  `canGoNext:323-327` = step<5 && stepMeta[next]≠locked && !rolesNotConfirmed — тоже не учитывает CPP.
  `validateIncomplete:335-340` гейтит футер только когда `stepMeta[2]==locked`, но авто-валидация
  разлочивает Модель ('ready') → гейт мёртв. 3A-фикс (`ValidateStepV13:461 handlePerChannelConfirm`
  + `allChannelsConfigured:774`) закрыл КОНТЕНТНЫЙ путь (Manager+Expert), футерный pipeline-путь —
  ТРЕТИЙ, непокрытый.
- **Severity:** 🟠 функц. + 🔵 достоверность (ведёт к ROI-артефакту на физ.каналах).
- **Фикс-направление (РЕШЕНИЕ АНТОНА — трогает pipeline-навигацию + контракт авто-валидации):**
  (A) `canGoNext`/`goNext` на step==1 учитывают CPP-гейт — блокируют переход пока есть physical+ROI
  канал без unit_cost (зеркало `allChannelsConfigured`); ИЛИ (B) не разлочивать Модель (stepMeta[2])
  пока подшаг «Подтверждение» (subStep 3) не пройден — авто-валидация разлочивает преждевременно;
  ИЛИ (C) `validateIncomplete` проверяет не только `stepMeta[2]==locked`, а незавершённость подшагов
  (subStep < финальный) при наличии неконфигурированных физ.каналов. Test-first.
- **✅ РЕШЕНИЕ АНТОНА 2026-06-04: Вариант B** (не разлочивать Модель пока подшаг «Подтверждение»
  subStep 3 не пройден — корень в преждевременном разлоке авто-валидацией). Применить в батче, test-first.

**🔧 ИСПРАВЛЕНО (Вариант B, 2026-06-04) — НЕ закоммичено (push/тег по команде Антона):**
- `ValidateStepV13.svelte`: убран `completeStep(1)` из `autoRunValidate:231` (преждевременный разлок
  Модели сразу после econ_validate) → перенесён в `handleContinue()` (финал подшага 3 «Подтверждение»),
  поставлен В НАЧАЛО функции (до persist — разлок не зависит от econ_save_kpi_settings; settings живут
  в store). Дойти до handleContinue можно лишь пройдя подшаг 2, где handlePerChannelConfirm:461 требует
  unit_cost для physical+ROI (иначе early-return) → CPP-гейт теперь на ЕДИНСТВЕННОМ пути к разлоку Модели.
- **Live-верифицировано (мост 9223, свежий импорт FMCG):** после автовалидации `stepMeta[2]` (Модель) =
  **locked** (было 'ready' до фикса), футерная «Далее ▶» **disabled** (было active → перескок на Модель).
  Gate-bypass закрыт.
- **Тесты:** новый `src/tests/nav2-footer-gate.test.js` (3, regression-guard инварианта: Импорт-complete
  не разлочивает Модель; Модель locked после только-валидации; completeStep(1) разлочивает). Гейты:
  **svelte-check 0E/171W · vitest 8/8** (nav2-footer-gate 3 + save-kpi 5) · check 4091 files 0 errors.
- **🔧 ИСПРАВЛЕНИЕ ДОПОЛНЕНО — e2e вскрыл НЕПОЛНОТУ первого фикса (2026-06-04, коммит 2):**
  Первый фикс (перенос completeStep(1) autoRunValidate→handleContinue) был НЕПРАВИЛЬНЫМ по двум причинам,
  пойманным ТОЛЬКО полным e2e-проходом (классика «один корень — N мест» + «live ловит, что код пропустил»):
  1. **ВТОРОЙ источник разлока — `InsightsPanel.svelte:161-211`** `syncStepLockAfterValidate` ($effect при
     любой чистой валидации на шаге 1) вызывал `completeStep(1)` → Модель разлочивалась сразу после
     подтверждения ролей (subStep→2), до CPP-гейта. Это ОСНОВНОЙ преждевременный источник, параллельный
     autoRunValidate. Фикс: `setStepError(1, null)` (только снять ошибку), без разлока Модели.
  3. **handleContinue МЁРТВ:** контентная кнопка подшага 3 убрана (`ModeDerivedExplanation:398-403` — стала
     инфо-строкой «готовы к обучению», `_onContinue` unused; переход подшаг 3→Модель делает футер goNext).
     → completeStep(1) в handleContinue НИКОГДА не вызвался бы → Модель не разлочилась бы = **БЛОКЕР**
     (футер disabled т.к. Модель locked, разлочить нечем). Фикс: completeStep(1) убран из handleContinue,
     перенесён в **`handlePerChannelConfirm`** (перед `subStep=3`) — единственная точка перехода на подшаг 3,
     ПОСЛЕ CPP-гейта (physical+ROI без unit_cost → early-return выше).
  Итог: 3 преждевременных источника закрыты (autoRunValidate + InsightsPanel), 1 легитимный оставлен
  (handlePerChannelConfirm за CPP-гейтом).
- **✅✅✅ ПОЛНЫЙ e2e ВЕРИФИЦИРОВАН (мост 9223, FMCG, аутентичный проход кликами):**
  - Подшаги -2/-1/2: Модель=**locked**, футер «Далее»=**disabled** (bypass закрыт; после ролей Модель
    осталась locked — part2 InsightsPanel).
  - «Подтвердить выбор» (handlePerChannelConfirm, CPP заполнен) → подшаг 3: Модель=**ready**,
    футер=**enabled** (нет блокера/тупика).
  - Футер «Далее» на подшаге 3 → pipelineCurrentStep 1→2 (**дошёл до Модели** легитимным путём).
  - CPP-гейт обязателен: без unit_cost физ.каналов handlePerChannelConfirm делает early-return (не подшаг 3).
  Гейты: svelte 0E/171W · vitest nav2-footer-gate 3/3 · check 4091 files 0 errors.

---

## Synthetic-truth — OTC validate-robustness ✅ + scope-решение

**Метод:** прямой IPC `econ_validate(file_path, project_dir)` (чистый movement-probe, без UI-репликации).

**✅ OTC (synth_otc_pharma 48×10, count-KPI sales_packs, 3 физ.канала tv_trp/apteka_ooh_ots/
performance_clicks + 1 money digital_spend) — движок РОБАСТНО ЧЕСТЕН:**
- Роли распознаны точно: sales_packs→kpi (count), все 4 канала→media, competitor_trp/weather_temp_low/
  holiday_newyear_preshop/avg_temp→control. issues=0.
- ratio=6 (48/8 предикторов), verdict «ГОТОВ К МОДЕЛИРОВАНИЮ (с оговорками)», status=warning — честно.
- **Поймал коллинеарность** weather_temp_low ↔ avg_temp r=−0.883 (по построению synthetic — weather
  выведен из avg_temp) → «один из столбцов избыточен». Не пропустил.
- Поймал holiday 83.3% нулей + малую выборку (48<52 рекоменд). available_kpi_types корректны для count.
- Подтверждает: на новой структуре (count-KPI + физ-heavy) движок не фабрикует, честно сигналит риски.

**Структуры остальных (preview, для следующего захода):** retail (24×9, traffic_visits count, **24 набл —
ratio-риск**, promo_indicator binary, ooh_ots физ); real_estate (36×11, leads count, macro_cpi двойной +
seasonality_q1/q4 signed, 2 физ-канала).

**📋 SCOPE-РЕШЕНИЕ (risk-based, явный — НЕ silent cap):** полный train+decompose×3 (нарративная честность
INV-50, знаки контролей на decompose-уровне) + Эксперт-интерактив ВЫНЕСЕНЫ в remaining. Причина: train-config
контракт объёмен (ConfigPanel ~130 строк: роли/adstock/priors/режим/unit_costs), реконструкция через IPC
хрупка (риск собрать неверно → артефакт, спутанный с багом движка = ложная находка); 3× MCMC дорого;
**FMCG synthetic-truth (2026-06-03) уже доказал decompose-честность** движка, OTC validate подтвердил
robustness на новой структуре. Оставшийся бюджет направлен на главную ценность сессии — **фикс
NAV-2/3A-FOOTER-BYPASS (Вариант B)**. Для следующего захода: train×3 через АУТЕНТИЧНЫЙ GUI-проход config
(не IPC-реконструкция) ИЛИ извлечь buildTrainConfig в чистую функцию + unit-тест (skill: extract pure fn).

## Эксперт-интерактив — ВЫНЕСЕН в remaining
Render-clean уже подтверждён 2026-06-04 (панели Валидация/Модель/Оптимизация чистые, CPP gate-bypass 3A
закрыт на контентном пути). Глубокий интерактив (живое редактирование custom priors, per-channel слайдеры,
VIF на реальных данных) требует свежего импорта + config через GUI-проход — следующий заход вместе с train×3.

---

## Эксперт-интерактив (ожидает)
<!-- заполняется по ходу -->
