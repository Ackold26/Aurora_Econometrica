# ADR-016: KPI Kinds (monetary vs count) и Binary Verdict Semantics

**Status:** Accepted
**Date:** 2026-05-12
**Owner:** Маша маленькая (review Антон)
**Related:** ADR-015, REFACTOR_PLAN_v1.3.0.md

## Context

В v1.2.0 все user-facing вердикты, инсайты и тексты отчётов **money-bound**:
- «Глубоко убыточный» (ROI < 0.5)
- «На грани окупаемости» (ROI < 1.0)
- «Лучший ROI: X — Y×» (insights panel)
- «1 ₽ → X ₽ выручки» (recommendations)
- «Marginal ROI последнего рубля» (reports)

Это методологически некорректно когда KPI — **немонетарная считаемая метрика**:
- Продажи в упаковках (sales_packs)
- Лиды (leads, заявки)
- Регистрации / активации (registrations)
- Выданные карты лояльности (loyalty_cards_issued)
- Подписки (subscriptions, MRR)
- Конверсии (app_installs, custom counted metrics)

В этих случаях:
- «ROI 0.12×» становится «отдача 0.12 упак/₽» — бессмысленно для CMO.
- «Глубоко убыточный» требует знания **value per unit** (маржа продукта / LTV лида / etc.).
- «Перелейте N ₽ → +M ₽ выручки» нужно заменить на «+K упак продаж».

## Decision

Вводим бинарное разделение KPI по семантике:

**`kpi_kind` ∈ {`monetary`, `count`}** — поле в KPIConfig + project state.

| Поле | `monetary` | `count` |
|---|---|---|
| Target column | sales_rub, revenue, profit, GMV | sales_packs, leads, registrations, loyalty_cards, subscriptions, app_installs, custom |
| Основная метрика канала | **ROI** (₽ выручки / ₽ затрат) | **CPU** (₽ затрат / count_unit) |
| Эталон сравнения | ROI vs 1.0 (окупаемость) | CPU vs `value_per_count_unit` (маржа / ценность лида / MRR / etc.) |
| Cross-channel сравнимая | Да (безразмерная) | Да (₽/unit для всех каналов) |
| Сравнения «убыточный/окупаемый» | ROI < 0.5/0.8/1.0 | CPU > 2×value / > value / ≈ value |

**Generic `value_per_count_unit`** — per-project поле, не registry constant:
- Для `sales_packs` → «Маржа на упаковку, ₽».
- Для `leads` → «Ценность лида, ₽» (CPL benchmark или LTV × conversion).
- Для `registrations` → «Ценность регистрации, ₽» (LTV × CR_reg→active).
- Для `loyalty_cards_issued` → «Ценность выданной карты, ₽» (avg_basket × frequency × retention_months).
- Для `subscriptions` → «MRR на подписку, ₽».
- Для `app_installs` → «Ценность установки, ₽» (LTV × CR_install→paying).
- Для `custom` → юзер задаёт свой label сам.

Auto-suggest формулы — см. `tools/value_per_count_unit_suggestions.py` (Stage 1 deliverable).

**Verdict tables бинарно:**

| Условие | KPI=monetary | KPI=count |
|---|---|---|
| ROI < 0.5 / CPU > 2×value | Глубоко убыточный | Глубоко убыточный (CPU > 2× ценности единицы) |
| ROI < 0.8 / CPU > value | Убыточный | Убыточный (CPU выше ценности единицы) |
| ROI < 1.0 / CPU ≈ value | На грани окупаемости | На грани окупаемости (CPU близко к ценности) |
| ROI > 50 + unit_smell | ROI завышен (не рубли?) | CPU подозрительно низкий (проверьте единицы) |
| ROI > 100 | ROI нереалистичен (артефакт) | CPU нереалистичен (артефакт) |
| wide CI | (широкий ROI-интервал) | (широкий интервал CPU) |

**Семантика «убыточный»** сохраняется в обеих ветках — это про возврат на затраты. Просто метрика разная: ROI vs CPU.

**Awareness KPI** (`kpi_kind='proportional'`) — **вне scope v1.3.0**. Переходит в Phase B (Aurora Brand Tracker), сохраняется в registry с пометкой `out_of_scope_v13=True`.

## Rationale

**Бинарность (не 3 семантики monetary/efficiency/proportional):**

Антон явно требует **2 типа комментариев** на этапе плана (2026-05-12). Awareness — отдельный продукт линейки (Aurora Brand Tracker), его специфика не должна загромождать MMM Optimizer.

**Generic `value_per_count_unit` (не hard-coded margin):**

Унифицирует UX через разные count KPI. Один UI, один store, один verdict-comparison flow. Только UI label адаптируется per KPI type.

**Семантика «убыточный» сохраняется:**

Антон отверг вариант полностью убрать «убыточный/окупаемый» для count KPI. Аргумент: для CMO/CFO вопрос «окупается ли канал» центральный независимо от того, считается ли он в рублях или в упаковках. Главное — правильно ввести `value_per_count_unit`.

## Alternatives Considered

| Альтернатива | Отвергнуто потому что |
|---|---|
| Без kpi_kind (текущий v1.2) | Money-bound тексты бьют по count KPI use cases |
| 3 семантики (monetary/efficiency/proportional) | Awareness не in scope; усложняет matrix без value |
| Только share-based для count (без CPU) | Теряем «убыточный/окупаемый» семантику; CMO нужны абсолютные метрики |
| Per-KPI hard-coded margin (без generic value_per_count_unit) | Не масштабируется на leads/registrations/custom |

## Consequences

**Positive:**
- 1 generic `value_per_count_unit` поле работает для всех count KPI types.
- Verdict семантика «убыточный/окупаемый» унифицирована.
- Расширение в будущем (новые count KPI) не требует новой логики.
- UI/reports параметризуются по 1-биту `kpi_kind`.

**Negative:**
- Юзер для count KPI должен ввести `value_per_count_unit` — дополнительное поле (mitigated через auto-suggest).
- Без `value_per_count_unit` verdict для count KPI деградирует в нейтральные share-based тексты.

**Neutral:**
- Awareness KPI помечен `out_of_scope_v13` в registry. Существующие awareness projects (если есть) — продолжают работать как в v1.2, но не получают KPI-aware enhancements v1.3.

## Implementation

**Backend:**
- `sidecar/econometrica/utils/kpi_registry.py` — расширить:
  - Поле `kpi_kind: Literal['monetary', 'count', 'proportional']` в `KPIConfig`.
  - 6 новых entry: `sales_packs`, `leads`, `registrations`, `loyalty_cards`, `subscriptions`, `app_installs`, `custom`.
  - `sales` → `kpi_kind='monetary'`.
  - `awareness` → `kpi_kind='proportional', out_of_scope_v13=True`.

- `sidecar/econometrica/engines/decomposer.py` — refactor `compute_roi_verdict`:
  - Lookup table `verdict_table[kpi_kind][threshold]`.
  - Для count KPI — compute CPU + сравнить с `value_per_count_unit` из project state.

- `sidecar/econometrica/utils/value_per_count_unit_suggestions.py` (NEW) — auto-suggest формулы.

**Frontend:**
- `src/lib/components/pipeline/ValuePerCountUnitInput.svelte` (NEW) — поле с per-KPI label.
- `src/lib/components/pipeline/DecomposeStep.svelte` — REWRITE: conditional CPU/ROI column.
- `src/lib/strings/strings_ru.json` + `strings_en.json` — добавить `*_unit` ключи.

**Migration:**
- v1.2 bundles default `kpi_kind='monetary'` (старые проекты — все money).
- Старое поле `kpi_column` сохраняется; новое `kpi_kind` injectится default в memory.

## References

- ADR-015 (Mode as derived state).
- Aurora KPI Registry v2.0 — `MATH_REFERENCE.md` § "KPI Registry".
- REFACTOR_PLAN_v1.3.0.md — матрица 4 базовых режимов.
- Антон директива 2026-05-12: «2 типа комментариев — для рублей и штук».
