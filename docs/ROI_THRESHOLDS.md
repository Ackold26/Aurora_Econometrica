# ROI Threshold Calibration (Aurora AI Econometrica)

**Status:** Live — `compute_roi_verdict` в `engines/decomposer.py`
**Version:** v1.0.13 (Phase 0.2, plan immutable-bouncing-noodle §0.2 — L4 fix)
**Last review:** 2026-04-25
**Owner:** Aurora AI methodology

## Назначение

`compute_roi_verdict()` присваивает каналу human-readable verdict + tone (good / warn / bad / neutral) на основе ROI, efficiency gap, posterior CI и категории. Verdict потребляется UI декомпозиции (`DecomposeStep.svelte`, `ExpertDecomposePanel.svelte`).

Pre-fix логика была серией inline if/elif с двумя hard thresholds (0.8 и 1.0) и двумя gap-based (-10/-5/+5/+10). Хрупко на post-Hill-fix распределениях ROI и не разделяет «неопределённость posterior» vs «уверенно убыточный».

## Hybrid 4-step decision flow

Решение принимается в 4 шага, выходим на первом подходящем:

### Step 1 — Posterior uncertainty (если CI данные есть)

Если `(roi_ci_high - roi_ci_low) > roi`, то posterior шире самой оценки → `('Высокая неопределённость', 'warn')`.

Гарантия: верное наблюдение «не тяните решение по точечной оценке если CI больше неё». Активируется в Phase 1.9 (full posterior propagation). До тех пор `roi_ci_low/high=None` → шаг пропускается.

### Step 2 — Absolute hard caps

Срабатывают независимо от категории:

| Условие | Verdict | Tone | Why |
|---|---|---|---|
| `roi > 50 + unit_smell` | ROI завышен (не рубли?) | warn | Канал в TRP/clicks/импрешнах с unit_cost=1 — ROI inflated by unit mismatch |
| `roi > 100` | ROI нереалистичен (артефакт) | warn | Безусловный верхний предел: 100×ROI = artifact (overfitting / sparse data / scale bug) |
| `roi < 0.5` | Глубоко убыточный | bad | <50% возврата — не workable даже как brand investment |
| `roi < 0.8` | Убыточный | bad | <80% возврата — нужно снижать или останавливать |
| `roi < 1.0` | На грани окупаемости | warn | Возврат < вложений — risky, требует пересмотра |

### Step 3 — Relative quantile (требует N ≥ 20 + portfolio benchmarks)

Когда у нас есть данные по 20+ каналам и `category_quantiles` benchmark per category:

| Условие | Verdict | Tone |
|---|---|---|
| `roi < p10` | Bottom-10% по категории | bad |
| `roi >= p90` | Top-10% по категории | good |
| `roi >= p75` | Top-25% по категории | good |
| `roi < p25` | Bottom-25% по категории | warn |
| иначе | Средний по категории | neutral |

Активируется автоматически когда `config['category_quantiles']` populated. Требует aggregation across portfolio — отдельная Phase (Aurora maintains synthetic priors из anonymized client base, plan §M2).

### Step 4 — Efficiency gap fallback (small-N safe)

Когда quantiles недоступны (типичный case 5-12 каналов):

| Условие | Verdict | Tone |
|---|---|---|
| `roi > 5 and not unit_smell` | Высокоэффективен | good |
| `gap <= -10 пп` | Перенасыщен | warn |
| `gap <= -5 пп` | Слабее своей доли | warn |
| `gap >= +10 пп` | Высокоэффективен | good |
| `gap >= +5 пп` | Эффективен | good |
| иначе | Сбалансирован | neutral |

`efficiency_gap = share_of_effect - share_of_spend` (пп) — насколько канал даёт больше или меньше effect чем спендит.

## Thresholds — обоснование

### Absolute floors

- `0.5` (deep loss) — ниже = безоговорочно cut, любая стратегия проигрывает кэшу
- `0.8` (loss) — ниже 80% возврата = не purpose-served (≥10% margin требуется для покрытия overhead)
- `1.0` (breakeven) — ниже = убыток в моменте; возможно accept для long-term brand но требует `decision`

Источник: industry consensus FMCG/retail (Lemmens & Croux 2006, Robyn case studies 2021-2024). На post-fix Hill normalization (spend/mean) ROI становится менее inflated, поэтому 0.8 floor реалистичен (vs 0.5 раньше).

### Absolute ceiling

- `5.0` (high) — выше = above-typical-FMCG ROI (1.5-3× — типично; 5× — редкие cases like new-launch performance digital)
- `50.0` (unit_smell warn) — выше при unit_smell = unit mismatch confirmed (TRP с unit_cost=1)
- `100.0` (artifact) — выше = безусловный артефакт (overfitting / Hill numerical instability / leakage)

Источник: Aurora-observed Kagocel + benchmarks 2025-2026 (тонкий tail при post-Hill-fix).

### Efficiency gap thresholds

- ±5/±10 пп — перенесены из pre-fix как working — типично для visualization (значимая разница на share-of-spend chart, но не на dust-level).

## Recalibration triggers

Этот файл должен быть обновлён когда:

1. **Live-test reveals systematic drift** — например, post-fix ROI теперь centered higher → 0.8 floor эфирно отлавливает healthy channels.
2. **Portfolio aggregation ships** (Phase 1+) — добавятся real `category_quantiles` для brand_reach / performance / mixed; threshold semantics станут relative.
3. **Industry benchmarks shift** — annual review.
4. **Phase 1.9 full posterior propagation ships** — Step 1 будет реально активен.

## Connections

- `engines/decomposer.py` — call site (`compute_roi_verdict()` invoked per-channel)
- `tools/test_roi_verdict.py` — 36 unit tests covering all 4 steps + tone enum + backward compat
- `engines/narrative_adapter.py::derive_verdict` — отдельная 5-way classification (Scale/Hold/Watch/Reduce/Cut) для PPTX/HTML; этот ROI verdict ей не участвует
- `MATH_AUDIT_v1_2_POST_FIX.md` § A2 — original L4 finding triggered this work

## Backward compatibility

Все 9 pre-fix verdict labels still producible:

- `Убыточный`, `На грани окупаемости`, `Перенасыщен`, `Слабее своей доли`,
- `Эффективен`, `Высокоэффективен`, `Сбалансирован`,
- `ROI завышен (не рубли?)` (preserved priority over artifact warning)

Новые labels: `Глубоко убыточный`, `ROI нереалистичен (артефакт)`, `Высокая неопределённость`, `Bottom/Top-10/25% по категории`, `Средний по категории`.

UI components читают `verdict_tone` enum — `{good, warn, bad, neutral}` invariant preserved.
