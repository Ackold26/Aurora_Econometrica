---
tags: [audit, synthetic-truth, honesty, mmm, ground-truth]
type: audit-map
date: 2026-06-06
scope: synthetic-truth train×3 — проверка числовой честности движка на синтетике с известным DGP
---
# Synthetic-truth — карта истины + ход аудита

**Метод (директива Антона 2026-06-06, [[feedback_cheapest_decisive_artifact_max_adversarial_verify]]):**
в аудите честности самый вероятный лжец — аудитор. Поэтому ожидаемую истину выводим ДВУМЯ
независимыми способами и держим движок ТОЛЬКО к тому, на чём оба согласны.

- **Способ 1 (аналитика DGP):** знаки/доминирование из `GROUND_TRUTH_*` (synthetic_pilot_data.py).
- **Способ 2 (мой OLS-референс на РЕАЛЬНОМ файле с диска, независим от движка):**
  naive (z-score сырых) + dgp-xform (истинные adstock(decay)+hill(alpha,γ=0.6)).
- Инструмент: `tools/synthetic_truth_reference.py` (запуск: `python ... [otc|fmcg|retail|real_estate|all]`).

## Фаза A — валидация метода (ОФЛАЙН, 0 MCMC) ✅ ЗАВЕРШЕНА

**Консистентность:** все 4 on-disk `.xlsx` (synthetic_pilots/, ген. 2026-05-14) ≡ текущему
генератору (max rel diff 0.00e+00) → GROUND_TRUTH применим к реальному файлу (директива #3).

**Робастная истина — к чему движок ОБЯЗАН (знак + значимость dgp-xform |t|>2 + согласие с аналитикой):**

| Датасет | n | Знаки контролей (робастно) | База / mean(y) | unit_smell (физ.ед.) | ИСКЛЮЧЕНО (не восстановимо) |
|---|---|---|---|---|---|
| **OTC** (count, sales_packs) | 48 | competitor **−** (t=−8.1), weather **+** (t=+5.7), holiday_ny **+** (t=+6.0) | **89.7%** | tv_trp, apteka_ooh_ots, performance_clicks | — |
| **FMCG** (monetary, sales_rub) | 36 | competitor **−** (t=−19.1), price **−** (t=−5.5), holiday_ny **+** (t=+4.5) | **94.8%** | ooh_trp, performance_clicks | — |
| **RETAIL** (traffic_visits) | 24 | competitor **−** (t=−10.0), blackfriday **+** (t=+7.0), newyear **+** (t=+8.7) | **95.5%** | ooh_ots, promo_indicator | — |
| **REAL_ESTATE** (leads) | 36 | competitor **−** (t=−9.8), macro_cpi **−** (t=−5.7), q4 **+** (t=+4.7) | **92.2%** | ooh_ots, performance_clicks | **seasonality_q1** (GT −0.08, OLS t=−1.5 → НЕ обвинять) |

**Что метод поймал (ценность второго аудитора):**
1. **OTC competitor — гипотеза опровергнута:** ожидал НЕвосстановимость (комментарий modeler.py:443
   «competitor↔brand TRP +0.93 в OTC»). Но это про РЕАЛЬНЫЙ Кагоцел; в синтетике competitor слабо
   коллинеарен → оба OLS робастно дают негатив (t=−3.8/−8.1). Одно-методный аудит дал бы движку
   ложную поблажку. → competitor − в OTC = жёсткое требование.
2. **REAL_ESTATE q1 — реально невосстановимо:** GROUND_TRUTH q1=−0.08 (наименьший |coef|), но OLS
   t=−1.4/−1.5 (незначим, вероятно конфаунд с macro_cpi-трендом + общей сезонностью). → q1 ИСКЛЮЧЁН
   из требований. Одно-методный аудитор (только GROUND_TRUTH) ложно обвинил бы движок.

**Не-робастное (движок НЕ обязан, по памяти [[feedback_synthetic_ground_truth_recovery_test]]):**
магнитуды коэффициентов, РАНГ каналов по ROI (низкий S/N ~media-эффект мал отн. базы 90-95%).
Robust = знаки контролей + доминирование базы + unit_smell на физ.единицах.

## Метод-рефайн (директива #2 строго): «оба OLS согласны»
Первая версия харнеса считала «робастным» по dgp-xform ОДНОМУ → over-classified FMCG holiday + RE q4
(восстановимы ТОЛЬКО с oracle-трансформами; движок их ОЦЕНИВАЕТ, не знает). Исправлено: робастно ТОЛЬКО
если ОБА OLS (naive БЕЗ трансформов + dgp-xform) согласны по знаку И оба значимы. Иначе ложно обвинил бы
движок (FMCG holiday: движок −0.07, но это transform-dependent, не нарушение). **Аудитор был слишком строг
к движку — поправлено ДО объявления находки.**

## Фаза B — engine probe (ОФЛАЙН через sidecar, БЕЗ Tauri/моста) ✅ ЗАВЕРШЕНА

**Подход (дешевле live-моста):** synthetic-truth тестирует ДВИЖОК (Python), не UI. Запуск `python server.py`
из ТЕКУЩЕГО исходника + POST `/compute/train` + `/compute/decompose`. Конфиг сгенерён САМОй `buildTrainConfig`
(node) → движок получает ровно её выход (исполнение директивы #1). НЕ трогает мост 9223/параллельную сессию.

**⚠ СТАЛ-EXE ТРАП (директива #3 окупилась):** первый прогон шёл против бандл-`econometrica-sidecar.exe`
**(2026-05-25)** — ПРЕДШЕСТВУЕТ фиксам REC-1-GAP/INV-50 (decomposer.py 2026-06-04). Старый exe короновал
tv_trp «самый эффективный ROI 25×» — давно закрытый баг. Чуть не объявил находкой. Перепрогон против исходника
дал корректный инсайт. **BUILD-HYGIENE: бандл-exe устарел → если на нём собирают/шипят, продукт бежит СТАРЫЙ
движок без honesty-фиксов. Нужен ребилд (вкл. фикс F-C ниже).**

**Робастная истина (строгая) vs движок — ВСЁ PASS:**
| Датасет | Робастно (оба OLS) | Движок beta_mean | База | MCMC | Transform-dep / искл. |
|---|---|---|---|---|---|
| OTC (count) | competitor−, weather+, holiday+ | −0.156, +0.473, +0.548 ✓✓✓ | 86.4% | r̂=1.0 div=0 | — |
| FMCG (monetary) | competitor−, price− | −0.461, −0.088 ✓✓ | 96.9% | r̂=1.0 div=0 | holiday (oracle-only) → −0.07 НЕ наруш. |
| RETAIL (count) | competitor−, blackfriday+, newyear+ | −0.383, +0.178, +0.176 ✓✓✓ | 97.8% | r̂=1.0 div=0 | — |
| RE (count) | competitor−, macro_cpi− | −0.246, −0.458 ✓✓ | 94.6% | r̂=1.0 div=1 | q4 (oracle-only), q1 (невосстановимо) |

**Вердикт: движок ЧИСЛЕННО ЧЕСТЕН.** Все строго-робастные знаки восстановлены (competitor− везде, даже на
симметричном prior для count-KPI — данные тянут негатив). База доминирует. MQS честно про тонкость (cap 50-70,
ratio<4 → «артефакт переобучения»). НЕ переоценивает невосстановимые (q1/q4/holiday не нарративятся; RE q1
движок дал −0.377 при GT −0.08 — магнитуда завышена коллинеарностью с macro_cpi, но в нарратив не вынес).
Сам флагает `unit_smell`/`roi_max`/`roi_spread` high-severity.

### F-C (РЕАЛЬНО, на текущем движке) — НАЙДЕНО + ИСПРАВЛЕНО ✅
`_build_channel_insight` короновал ROI-артефакт, когда money ROI недоступен (count-KPI без kpi_unit_cost):
RETAIL `promo_indicator` (binary 0/1, spend=9, unit_cost=1) → ROI **50976×** → «самый эффективный канал».
REC-1-GAP `clean`-фильтр детектит unit_smell ПО ИМЕНИ (UNIT_HINTS) → 'promo_indicator' без unit-keyword
проходил, хотя движок САМ флагнул `roi_max` high-severity. Все verdict каналов = «Задайте ценность единицы»,
а инсайт всё равно ранжировал по нативному ROI = INV-50 противоречие.
**Фикс:** гейт `_build_channel_insight(channels, money_roi_unavailable)` (count без kpi_unit_cost) → честное
«Денежный ROI недоступен: задайте ценность единицы... продажи определяются базовым спросом». +3 теста
(`TestMoneyRoiUnavailableGate`). Верифицировано end-to-end (RETAIL+OTC инсайт исправлен) + monetary-путь
(FMCG) не затронут (INV-50 else-branch работает). pytest decomposer 15 passed.

### F-A (ПОДТВЕРЖДЁН export-баг) — ИСПРАВЛЕНО ✅
Выход decompose `kpi_kind`/`derived_mode`/`value_per_count_unit` читался из НИКОГДА не создаваемого
`v13_kpi.json` (`_load_v13_kpi_settings` → дефолт monetary/roi/None) ВНЕ зависимости от обученного `kpi_type`
(в pickle). Самопротиворечие: `kpi_kind='monetary'` но `total_sales_money=None` (count-ветка).
**Цепочка потребителя ПРОВЕРЕНА (директива «каждый consumer»):** `DecomposeStep.svelte` НЕ читает (свои сторы —
безвреден), НО `narrative_adapter.py:818` читает `decompose_data.get('kpi_kind','monetary')` → `data['kpi']` →
`aurora_pptx/aurora_html` builder → **count-KPI PPTX/HTML экспорт мислейблился monetary/₽/ROI** (реальный
user-facing баг, не латентный). Корень = LOAD-1 dead-save (v13_kpi.json).
**Фикс:** `_resolve_output_kpi_meta(v13_kpi, kpi_kind, kpi_unit_cost)` — выход берёт kpi_kind/value_per_count_unit
из pickle-резолва (внутренний kpi_kind корректен из kpi_type, decompose:405-429), v13_kpi = приоритет-override
(forward-compat если save-path оживёт); derived_mode остаётся 'roi' (frontend-концепт, нет pickle-источника, но
при kpi_kind='count' downstream is_legacy/labels уже count-форма). +4 теста (`TestResolveOutputKpiMeta`).
Верифицировано end-to-end: OTC decompose output `kpi_kind='count'` (был 'monetary'). pytest decomposer 160.
**Остаток в LOAD-1 backend-таске (п.4):** персист `kpiType`/`valuePerCountUnit`/`modelChannelEnabled` в ProjectInfo
+ ре-гидрация + cpp-гейт в `ConfigPanel.handleTrain` (re-train артефакт на reload — это frontend/Rust, отдельно).

### Артефакты пробы
`tools/_synthprobe/` (ephemeral: configs от buildTrainConfig + train/decompose JSON; НЕ коммитится).
Харнес `tools/synthetic_truth_reference.py` (durable). Движок гонялся `python server.py` из исходника.

## Адверсариальный аудит ранее-не-аудированного (2026-06-06, 3 параллельных агента + моя верификация)
Запрос: глубокий аудит частей, получивших МЕНЬШЕ всего адверсариального внимания. Принцип «аудитор —
вероятный лжец» → агенты нашли кандидатов, я верифицировал КАЖДЫЙ probe/чтением (не доверял слепо).

- **Харнес `synthetic_truth_reference.py` — SOUND по 7 осям** (агент-1, probe-доказано): OLS-математика ≡
  normal-equations (np.allclose), `_normalize` ≡ генератор, dgp-xform ≡ DGP (adstock+hill+γ0.6), робаст-критерий
  структурно не допускает ни ложного обвинения, ни ложного оправдания на 4 датасетах, OVB по competitor (опущенный
  seasonal_lift, corr +0.44) смещает оценку КОНСЕРВАТИВНО (против негатива) → вердикт «движок честен» **достоверен**.
- **FIX-1 [MEDIUM→HIGH] SET-IF-PRESENT клоббер (моя п.4 дыра) — ИСПРАВЛЕНО:** re-конфигур обученного monetary→count +
  `UnitCostsPanel/ChannelCategoriesPanel.save` (project_update БЕЗ kpi_type → ProjectInfo со СТАРЫМ disk kpi_type →
  `activeProject.set` того же id) затирал свежий выбор wizard обратно в 'sales' → re-train prior −0.3 вместо 0.0 =
  ровно prior-flip артефакт. Премиса верифицирована (`buildProjectUpdates` column-roles.js:134-139 БЕЗ kpi_type).
  Фикс: **id-guard** в rehydrate-subscribe (ре-гидрация только при смене `p.id`, не на mid-session set). +2 vitest (664).
- **FIX-2 [HIGH] F-C неполон на МОНЕТАРНОМ пути — ИСПРАВЛЕНО:** probe подтвердил — monetary-проект, artifact-канал
  (`promo_flag` roi 50000×, unit_smell=False, имя без unit-hint) короновался «самый эффективный» + переток в него
  (гейт money_roi_unavailable=False молчит, name-based unit_smell промахивается). Фикс: `_build_channel_insight`
  исключает из коронования roi >= `ROI_ARTIFACT` (100×) НЕЗАВИСИМО от kpi_kind; all-artifact → честный fallback.
  +3 pytest. Закрывает artifact-коронование на ОБОИХ путях (count + monetary).
- **FIX-3 [LOW→MED] F-A `derived_mode` хардкод 'roi' — ИСПРАВЛЕНО:** реальный derived_mode лежит в pickle
  `model_data` (persistence.py:417-423), а `_resolve_output_kpi_meta` хардкодил 'roi' → count+effectiveness экспорт
  показал бы «CPU ₽/ед.» вместо «Доля %». Фикс: call-site шлёт `model_data.get('derived_mode') or 'roi'`. +2 pytest.
- **Прочее (NOTE, не фикс):** awareness kpi_kind='proportional' (JS) → Python decompose фолбэчит monetary →
  awareness-экспорт мислейбл (смежный класс, вне F-A/F-C; проверить достигает ли awareness decompose). kpi_type/
  kpi_kind теоретич. рассинхрон (источник — сеттеры, латентно, не этот фикс). Wiring buildTrainConfig→ConfigPanel —
  агент подтвердил **побайтово** против оригинального inline (`git show 2f18f27~1`).
Гейты после фиксов: pytest decomposer **165** · svelte 0E/171W · vitest **664**.
