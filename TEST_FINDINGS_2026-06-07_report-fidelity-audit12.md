# Аудит #12 «отчёты = программа» — probe-findings + скорректированный план

Дата: 2026-06-07. Режим: автономный, probe-first (см. урок `feedback_single_source_of_truth_for_displayed_metrics`).
Тестовый проект: `кагоцел-рф--данные-для-эконометрики---на-ммх-0706-26` (MQS 70, обучен).

## 0. Источник истины (decomposition.json) — PROBE подтверждён
- `channels`: **5** медиа (roi + contribution).
- `waterfall`: **7** баров (Baseline + 5 медиа + Итого). net-вклады. Контроли свёрнуты в Baseline.
- `signed_factor_contributions`: **14** факторов (1 запросы=positive_control, 1 конкуренты=signed_competitor, 12 праздников=holiday). У всех `value/pct ≈ 0` (net-нулевые), но `per_period` ненулевой у ~8 (5 праздников нулевые по всем периодам).
- `time_series`: {dates, baseline (ВКЛЮЧАЕТ control_effect, decomposer.py:816-825), channels(5 медиа)}.

## 1. Карта потребителей
| Потребитель | waterfall | channel-table | timeline (по периодам) |
|---|---|---|---|
| Программа DecomposeStep | `data.waterfall` (7) ✓ | `data.channels` (5) ✓ | **ChannelTimeline**: baseline + 5 медиа + **signed-факторы полосами** (конкуренты/праздники) |
| XLSX report.rs | лист «Декомпозиция» из `waterfall` ✓ | листы из `channels` ✓ | лист (стр.1185) Base+медиа — **БЕЗ signed** |
| HTML aurora_html | builder.py из `waterfall` ✓ | из `channels` ✓ | CHART_DATA.timeline (builder.py:317) baseline+channels — **БЕЗ signed** |
| PPTX pptx_export | из ctx waterfall ✓ | из ctx channels ✓ | timeline — **БЕЗ signed** |

## 2. КОРЕНЬ (один, не три)
Все 3 билдера рендерят timeline как `baseline + media` и **не сворачивают `signed_factor_contributions`**. Программа сворачивает их в `ChannelTimeline.svelte` (фронт). → «программа показывает больше факторов».
Поправка к handoff: расхождение НЕ в waterfall (там 7=7), а в **timeline**. «~18» = 5 медиа + ~8 ненулевых signed.

## 3. Латентный INV-50 баг в ChannelTimeline (честность)
`time_series.baseline` уже включает control_effect (все контроли). ChannelTimeline вычитает из baseline только факторы с mean<0 (строка 328), а положительные праздники добавляет полосой сверху **не вычитая** → double-count на пиковых периодах праздников. Честный фикс обязателен (не тиражировать в отчёты).

## 4. Честный SSOT-фикс (дизайн)
Вынести разбивку в backend ОДИН раз → программа + 3 отчёта читают одно поле.
- decomposer.py: новая `build_decomposition_series(dates, baseline_ts, time_series_channels, signed_factor_contributions, channel_order)`:
  - `baseline_reduced = baseline_ts`; для каждого выносимого фактора (тип signed_*/holiday; positive_control остаётся в baseline; all-zero per_period — пропуск) **вычесть** per_period из baseline_reduced (и +, и −) → тождество `baseline_reduced + Σbands + Σmedia = total` сохраняется.
  - side = 'negative' если mean<0 иначе 'positive'.
  - emit `decomposition_series = {dates, series:[{name, role, type, group, side, data}]}`; role∈{baseline,media,factor}.
- ChannelTimeline.svelte: рендер из `data.decomposition_series` (fallback на старую логику если поля нет — legacy). Цвета/tooltip-группировка остаются в фронте (презентация).
- HTML builder.py + interactive.py: timeline.factors из decomposition_series.
- PPTX pptx_export: factor-серии в timeline.
- XLSX report.rs: колонки факторов в time-series листе.
Цвет — в каждом рендерере по `type` (презентация). Набор факторов + per_period + side — из backend (SSOT-критично).

## 5. #10 (легенда highlight) — корень в коде
ChannelTimeline highlight (стр.146-159) аккумулирует `cum` от 0 вверх — ищет слой только в положительном стеке. Отрицательные полосы (конкуренты под нулём) не подсвечиваются. Фикс: учитывать negative-стек (cum вниз от 0 для отрицательных серий).

## 6. #9 (панель «Экспорт») — CSS высота, ReportStep.svelte:~908 .generate-card.

## Скорректированный staged-план (audit+commit после каждого)
- [x] Этап 0 — probe + этот документ.
- [x] Этап 1 — fidelity-diff harness (`tools/fidelity_diff.py`). **RED подтверждён:** backend нет decomposition_series; HTML 5 серий, нет 8 факторов (конкуренты+7 праздников); PPTX 7 серий, нет факторов + нет канала OLV. Тождество per-period проверяется. Commit+tag.

### Side-findings (вне аудита #12, записать/решить позже)
- **SF-1 (HTML офлайн):** `Asset integrity failure: echarts.common.5.5.1.min.js expected sha256 66f1700… got a42cc53…` при build_html. Возможна деградация офлайн-инлайна echarts (память утверждала «инлайнится ~0.7МБ»). Проверить builder._echarts_js() / shell.html — hash в коде vs реальный asset. Кандидат на отдельный фикс.
- **SF-2 (PPTX медиа):** PPTX timeline недосчитывает канал OLV (7 серий, expected 5 медиа + факторы). Проверить при фиксе Этапа 3.
- [ ] Этап 2 — backend `decomposition_series` + pytest (тождество, набор, no-double-count). Commit+tag.
- [ ] Этап 3 — потребители (ChannelTimeline + HTML + PPTX + XLSX) читают decomposition_series. Harness GREEN. npm check 0E. Commit+tag.
- [ ] Этап 4 — #9 CSS + #10 negative-stack highlight. Commit+tag.
- [ ] Этап 5 — #4 аудит режимов оптимизации (probe optimization.json ↔ билдеры; econ_optimize/optimize_inverse/«от задачи»). Commit+tag.
- [ ] Этап 6 — #5 recompute_mqs --all (dry-run+решение) + #6 Tier-3 OVB-guardrails (scope-оценка). Commit+tag.
- [ ] Этап 7 (финал) — полный аудит (npm check + pytest + cargo test + harness), общий коммит, обновление памяти. **rc10 build/publish — HOLD до подтверждения Антона (наружу).**

## Инварианты
INV-50 честность; единый источник для метрик; JS+JSDoc; npm check 0E; pytest зелёный; коммит+тег на этап; push/release ТОЛЬКО по команде Антона.
