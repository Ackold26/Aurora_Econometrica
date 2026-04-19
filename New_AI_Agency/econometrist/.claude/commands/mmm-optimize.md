ЯЗЫК ОТВЕТА: РУССКИЙ. Все комментарии, выводы, рекомендации, статусы — на русском языке. НЕ использовать английский (кроме терминов ROI, CPM, GRP).

Найди оптимальное распределение бюджета по медиаканалам на основе обученной MMM-модели.

1. Используй дефолтные параметры (НЕ задавай вопросы, если пользователь не указал иное):
   - Общий бюджет: фиксированный (текущий total из данных)
   - Ограничения: ±50% от текущего по каждому каналу
   - Цель: max_response (максимизировать совокупный отклик)
   - Период: 12 месяцев
   Пометь все допущения [ASSUMED]
2. Рассчитай **Marginal ROI (mROI)** для каждого канала при текущих затратах — производная кривой отклика (Hill function) в точке текущего spend
3. Сгенерируй Python-скрипт `exports/scripts/mmm_optimize.py`:
   - Response curves для каждого канала
   - Constrained optimization: `scipy.optimize.minimize(method='SLSQP')`
   - Constraints: total_budget, per_channel_min, per_channel_max
   - Objective: maximize sum of response across channels
4. Выполни скрипт через Bash
5. Результат — таблица:
   | Канал | Current Spend | Optimized Spend | Delta % | Current ROAS | Marginal ROAS | Expected Lift |
6. Визуализации:
   - Response curves с точками текущих (серые) и оптимальных (синие) затрат
   - Bar chart: current vs optimized allocation
7. Ключевой вывод: «Перераспределение X% бюджета из [каналов-доноров] в [каналы-реципиенты] увеличит совокупный отклик на Y% [CI: Z1%-Z2%]»

Сохрани: `exports/mmm-optimization-[дата].xlsx` (листы: Summary, Channel_Detail, Constraints) + графики

Когда оптимизация выполнена — напиши: «Все задачи выполнены.»
