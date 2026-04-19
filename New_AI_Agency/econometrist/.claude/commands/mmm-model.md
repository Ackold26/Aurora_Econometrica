ЯЗЫК ОТВЕТА: РУССКИЙ. Все комментарии, выводы, рекомендации, статусы — на русском языке. НЕ использовать английский (кроме терминов ROI, CPM, GRP).

Построй байесовскую модель маркетингового микса на данных из inbox.

1. Проверь, что данные валидированы (`/mmm-prepare`). Если нет — сначала провести валидацию
2. Автоматически определи из данных (НЕ задавай вопросы):
   - KPI: столбец с "sales", "revenue", "conversions" в названии (или первый числовой не-медиа)
   - Медиа: столбцы с "budget", "spend", "trp", "grp", "impressions" в названии
   - Контроль: остальные числовые столбцы (price, distribution, search_queries, competitors и т.д.)
   - Adstock: geometric для digital (budget/impressions), Weibull для TV (trp/grp)
   Пометь все допущения [ASSUMED]. Если не удаётся определить — используй разумный дефолт
3. Проверь наличие Python и пакетов: `pip install pymc-marketing pandas scipy matplotlib plotly prophet openpyxl`
4. Сгенерируй Python-скрипт `exports/scripts/mmm_model.py`:
   - Загрузка и подготовка данных (pandas)
   - Декомпозиция временного ряда (Prophet): тренд, сезонность, праздники
   - Adstock-трансформация для каждого медиаканала
   - Hill function saturation
   - Спецификация байесовской модели (PyMC-Marketing MMM)
   - MCMC-сэмплирование (параметры draws/chains/sampler — по правилам из секции "Windows: облегчённый MCMC" в CLAUDE.md)
   - Сохранение результатов в pickle + xlsx
5. Выполни скрипт через Bash
6. Проверь диагностику:
   - R-hat < 1.05 для всех параметров
   - Нет divergences
   - Posterior predictive check: predicted vs actual
7. Рассчитай и сообщи **MQS** (Model Quality Score): R², MAPE, R-hat → тир (Poor/Weak/Acceptable/Good/Excellent)
8. Пройди MMM Diagnostics Checklist (8 пунктов из CLAUDE.md)

Сохрани: `exports/mmm-model-[дата].xlsx` (листы: Diagnostics, Parameters, Fit) + скрипт в `exports/scripts/`

Когда модель обучена и диагностика пройдена — напиши: «Все задачи выполнены.»
