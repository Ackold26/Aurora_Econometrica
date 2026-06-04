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

## Фаза B — live train×3 probe (МОСТ 9223) — PENDING (чекпоинт: параллельная сессия + bridge)

Гейт ПЕРЕД 1-м train (директива #1): live байт-в-байт дифф выхода `buildTrainConfig(realState)`
против inline (git-историческая версия) на реальном OTC-проекте — сойдётся или стоп.

Затем по каждому датасету (OTC→retail→real_estate): импорт синтетик-xlsx → `buildTrainConfig` →
`econ_train` IPC-probe → decompose → сверка фактического `decomposition.json`/`diagnostics.json`/
pickle ПРОТИВ робастной истины выше (от реального входного файла, не от генератора). Особо:
- знаки контролей (см. таблицу) — РОВНО эти, не больше;
- доминирование базы (~90-95%);
- unit_smell flagged на физ.единицах;
- **OTC count-KPI: kpiType→prior эффект** (LOAD-1 связь: _is_otc_or_count→_competitor_mu=0.0 симметричный,
  modeler.py:461; данные сильно тянут негатив t=−8 → posterior обязан негативный);
- нарративная overconfidence (INV-50): не коронует ли «эффективным» канал, что вердиктом «убыточный»;
  печатает ли разные числа одинаково.
