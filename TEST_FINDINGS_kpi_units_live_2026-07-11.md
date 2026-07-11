# TEST FINDINGS — живой прогон KPI-units (INV-33), 2026-07-11

**Метод:** AVT — live-probe реального Python-движка на 4 фикстурах (`tmp/kpi_fixtures/`: monetary,
count_leads_vpcu, count_leads_novpcu, effectiveness) на готовом pickle (без переобучения). База —
`tmp/avt_project/models/latest.pkl` (2 канала).

## ✅ Подтверждено корректным (реальный движок, реальные данные)
- monetary: ось «Продажи, ₽», метрика ROI, mROAS× — контроль не сломан.
- count+ценность: ось «Лиды», метрика «CPU, ₽/лид», breakeven «CPU > 80 ₽/лид».
- count без ценности: вердикты «Задайте ценность единицы для оценки» (НЕ огульный «Cut»), подсказка есть.
- effectiveness: метрика «Доля %» (ось «Продажи, ₽» верна — kpi_type=sales, результат в выручке,
  метрика канала = доля; матрица работает).

## 🟠 НАХОДКА-1 (Тип 4, реальная утечка, пропущена Фазой 2/3)
`engines/decomposer.py:113,124` — `_build_channel_insight` пишет «самый эффективный канал (ROI X×)» и
«Ни один канал не окупается напрямую (ROI X×)» БЕЗ проверки kpi_kind/derived_mode. Поле `result['insight']`
идёт в API → UI-карточки декомпозиции. Для count должно быть CPU, для effectiveness — доля.
- Repro: probe на фикстуре effectiveness/count → insight содержит «ROI X×».
- Причина: функция принимает `money_roi_unavailable`, но не kpi_kind/kpi_type/derived_mode; вызов
  decompose ~:1212 их не прокидывает.
- Примечание: HTML/PPTX-отчёты это поле не используют (там нарратив render_executive_summary) — утечка
  в API/фронт-карточках.
- ✅ ИСПРАВЛЕНО: `_build_channel_insight` получил kpi_kind/kpi_type/derived_mode; monetary → «ROI X×»
  (как было), count → «CPU N ₽/лид», effectiveness → «доля эффекта N%». При ревью фикса субагента поймана
  вторичная ошибка: effectiveness прогонял roi через format_metric → бессмысленные «250% доли»; исправлено
  на реальную долю вклада (contribution_pct/share_of_effect), ранжирование по доле. Live-probe:
  «ТВ – наибольшая доля эффекта (62.0%). Онлайн-видео – 38.0%». Тесты 17 + регрессия 70.

## ⏳ Осталось на визуальный прогон в окне (код структурно не докажет)
- Рендер осей/легенд ECharts, карточки вердикта/action/insight в SvelteKit UI (3 режима).
- Полный HTML-отчёт (matplotlib+jinja2) и PPTX-экспорт (python-pptx) — визуальная сверка.
- Planning mode KPI-path (отдельно не проверялся).
