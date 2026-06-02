# ШАГ 0 — эмпирическая проверка гипотез плана коррекции (2026-06-02)

Проверка на РЕАЛЬНЫХ артефактах перед строительством волн (по мета-совету Антона:
«гипотезу проверяй на реальном pickle до того, как строить на ней волну»).

Probe прогнан на реальных проектах из `%APPDATA%\aurora-econometrica-gui\projects\`:
- NEW: `кагоцел-рф--данные-для-эконометрики---на-ммх-0206-26` (тестировался вживую 02.06)
- OLD: `кагоцел-рф-ммх-2704-26` (27.04, ранняя схема)

## Гипотеза В0 (backward-compat defaults) — В ЗНАЧИТЕЛЬНОЙ МЕРЕ ЛОЖНА → де-скоуп

| Факт | Доказательство |
|---|---|
| Старый и новый pickle — **оба `model_version '1.2'`** | probe field-dump |
| Оба загрузились без падений; defaults инжектятся | `load_model_with_compat` отработал |
| `per_channel_input`, `kpi_kind='monetary'`, `derived_mode='roi'` уже инжектятся | для 7/6 каналов |
| `kpi_unit_cost_snapshot`/`unit_costs_snapshot` читаются защитно (None-guard) | optimizer.py:321-322 |
| `config.unit_costs: {}` **пуст у ОБОИХ** — CPP никогда не вводился | project.json + pickle |
| `ProjectInfo.unit_costs` имеет `#[serde(default)]` | project.rs:27 |

**Вывод:** контракт уже аддитивно-безопасен. Отдельная «волна инжекта defaults для
unit_costs» НЕ нужна. Единственный теоретический риск — persisted `decomposition.json`
с native-ROI — снимается тем, что decompose ПЕРЕсчитывается при повторном открытии, а сам
фикс ROI = это 3A. **В0 сворачивается в мелкий version-guard внутри 3A (если вообще нужен).**

## Гипотеза 3C/GS-1 (proportional-mode) — ПОДТВЕРЖДЕНА, но КОРЕНЬ ИНОЙ

Probe сравнил forward(B) двумя способами на свежем Кагоцеле:

```
corridor: current=279334862  hi=17597464   ← current в 16× БОЛЬШЕ верхней границы!

[A] re-optimize (текущий путь _forward_at_budget, нативный total_budget):
  ВСЕ 7 бюджетов → ERROR UNIT_SMELL (TRPs без CPP)        => монотонность не определима

[B] proportional (фикс. пропорции, evaluate_flat_allocation_response):
  2.8M → 11.6M → 23.9M → 39.1M → 56.7M → 76.3M → 97.7M    => МОНОТОННА ✓
```

**Корень GS-1 — НЕ «артефакт SLSQP re-optimization» (как в плане).** На Кагоцеле путь
`_forward_at_budget` (inverse.py:51) передаёт **нативный `total_budget`** → guard `UNIT_SMELL`
(optimizer.py:484) блокирует, т.к. TRPs без CPP. Дальше `_verify_monotonicity` ловит первую
же error и возвращает `monotonic=False` → юзер видит **«Forward не монотонна / non-convex
Hill»**, хотя истинная причина — unit_smell, замаскированный под non-monotonic.

**Фикс-направление верное** (proportional монотонна + обходит smell через
`evaluate_flat_allocation_response`), но диагноз в плане исправить: GS-1 фиксится корректным
unit_cost (3A) + proportional-режимом, а не «обходом SLSQP non-convexity».

## Единый корень трёх находок

ROI-1/2, BUDGET-1/#60, GS-1 — **один корень**: не-денежный канал TRPs с `unit_cost=1.0`:
- decomposer отдаёт `roi=12186`, `mroi=9550`, **флагует `unit_smell=True`**, но абсурд течёт
  в инсайты/рекомендации (`decomposition.json` channels[0]).
- бюджет смешивает нативные TRPs с рублями (current 279M vs corridor hi 17.6M).
- Goal-Seek forward падает на smell-guard → «non-monotonic».

→ **3A (CPP-нормализация) — центральная волна. Всё остальное следует из неё.**
Обвязка unit_cost в optimizer/decomposer уже обширна (ADR-020/021); реальный gap:
(a) UI ввода CPP/CPM для не-денежных каналов в Валидации, (b) decomposer не должен отдавать
абсурдный ROI при unit_smell (требовать CPP / гасить), (c) Goal-Seek proportional-режим.

## Скорректированная последовательность

- ~~В0 отдельной волной~~ → свёрнута в 3A (мелкий guard, если нужен).
- **В1 (тексты + англицизм)** — независима, делаю первой (пакетно-автономно).
- **В2 (UX онбординг/навигация)** — независима.
- **В3 = ядро:** 3A CPP (UI ввода + decomposer ROI guard + budget units) → 3B STATE-1 →
  3C GS-1 proportional (через `evaluate_flat_allocation_response`).
