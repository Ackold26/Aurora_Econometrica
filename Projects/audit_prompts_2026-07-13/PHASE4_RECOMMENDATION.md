# Фаза 4 — рекомендация: усиление методологии кабинета econometrist каноном (вход в aurora-upgrade)

> 2026-07-13. Финальная фаза протокола. Это НЕ реализация — вход в отдельный инструмент `aurora-upgrade`
> (подкрепление методологии первоисточниками RAG-библиотеки, не мнением).
> База: аудит Фазы 1 (методология кабинета сильная — INV-50 соблюдён, adstock/Hill/backdoor-контроли/MCMC
> на уровне первоисточников; пробелы по граням конвейера, не в ядре MMM). Корпус узла Б «econometrics»
> + Knowledge_Library уже содержат ядро: Gelman, McElreath, Pearl, Hernan-Robins (Causal Inference: What If),
> Jin 2017, Sun 2017, Chan-Perry, Wang-Jin, Robyn/Meta 2024, Davidson-Pilon, Sharp, Binet&Field, Keller, Katz.

## 1. Пробелы методологии, закрываемые каноном (по группам команд)

### pilot-design (активная) + калибровка модели экспериментом — ГЛАВНЫЙ ГЭП
- Команда `/pilot-design` проектирует пилот 4–6 недель для проверки рекомендаций оптимизатора, но канон
  **методологии geo-экспериментов / incrementality-тестов** в библиотеке тонкий: по запросу top cos ≈ 0.41
  (Robyn касается «calibrate with experimental results» вскользь; Hernan-Robins даёт общий causal-каркас,
  не рекламный geo-дизайн). Нет специализированного первоисточника дизайна пилота: контрольные/тестовые
  гео, размер эффекта, мощность, длительность, TBR-анализ. **Ядро запроса клиента — доверие к модели через
  эксперимент — опирается на самый тонкий участок канона.**
- Это же бьёт по `/mmm-model` (шаг «калибровка модели экспериментом» из best-practice MMM — Robyn/Meridian
  описывают, но метод дизайна самого эксперимента отсутствует).

### awareness-forecast / awareness-to-sales (активные) — ГЭП
- Обе команды моделируют awareness и связь awareness→продажи. Библиотека даёт **теорию бренда** (Sharp «How
  Brands Grow» — mental availability; Binet&Field «Long and Short» — brand vs activation) и **медиапланирование**
  (Katz «Media Handbook», top cos 0.56), но не **количественное моделирование awareness** как латентного
  отклика на медиадавление (awareness adstock, awareness→conversion как медиатор). Промпты строят прогноз
  awareness, канон-первоисточник метода — пробел.

### MMM-ядро (`/mmm-model`, `/mmm-decomposition`, `/mmm-optimize`) — усиление, не пробел
- Ядро покрыто сильно (Jin 2017 adstock/Hill, Robyn 2024 конвейер, Gelman/McElreath байес, Pearl/Hernan-Robins
  backdoor). Тонкие грани для углубления: **элицитация приоров для MMM** (индустриальные ROI/adstock-бенчмарки
  как приоры — Meridian-подход; Gelman даёт общий байес, MMM-специфику приоров — нет) и **триангуляция**
  (MMM + эксперимент + атрибуция как единая система доверия — Robyn упоминает, метод триангуляции тонкий).

## 2. Перечень тем для пополнения (приоритет по ценности для продукта)
1. **Geo-эксперименты и incrementality-тестирование рекламы** — наибольший пробел; ядро `/pilot-design`
   и калибровки модели (доверие клиента).
2. **Количественное моделирование awareness → продажи** — ядро двух awareness-команд.
3. **Элицитация приоров и калибровка MMM** (индустриальные бенчмарки как приоры) — усиление ядра.
4. **Триангуляция маркетинговых измерений** (MMM + эксперимент + атрибуция) — методология доверия.

## 3. Рекомендованные книги/материалы (формат: Название · авторы · год · EN/RU)

> ⚠️ INV-50: точные выходные данные (год, редакция) СВЕРИТЬ при добавлении (aurora-upgrade делает это при
> индексации). Отмечено ✅ = уже в корпусе/библиотеке.

**Geo-эксперименты / incrementality (главный пробел):**
- **«Estimating Ad Effectiveness using Geo Experiments»** · J. Vaver, J. Koehler (Google) · 2011 · EN ·
  базовая методология geo-экспериментов Google (основа дизайна пилота). RU: нет.
- **«Measuring Ad Effectiveness Using Geo Experiments in a Time-Based Regression Framework»** · Kerman,
  Wang, Vaver (Google) · 2017 · EN · TBR — прямо под пилот 4–6 недель и калибровку MMM. RU: нет.
- **«Trustworthy Online Controlled Experiments»** · R. Kohavi, D. Tang, Y. Xu · 2020 · EN; RU: «Доверительное
  A/B-тестирование» (изд. на русском есть) · дизайн экспериментов, мощность, длительность — переносится на пилот.

**Awareness → продажи (количественно):**
- **«Advertising and Sales» / «Effective Advertising: Understanding When, How, and Why Advertising Works»** ·
  Gerard J. Tellis · 2004 · EN · моделирование отклика продаж на рекламу и awareness. RU: нет полного.
- **«Marketing Metrics: The Manager's Guide to Measuring Marketing Performance»** · Farris, Bendle, Pfeifer,
  Reibstein · 2015 (3rd) · EN; RU: «Маркетинговые показатели» · awareness-метрики и связь с продажами.
- ✅ **«How Brands Grow»** · B. Sharp · 2010 · EN — уже в библиотеке (mental availability — теория под awareness).

**Приоры и калибровка MMM:**
- **Google Meridian — methodology / documentation** (новый open-source MMM Google) · Google · 2024 · EN ·
  элицитация приоров ROI/adstock, калибровка экспериментом. RU: нет.
- ✅ **«Bayesian Data Analysis», 3rd ed** · Gelman, Carlin, Stern, Dunson, Vehtari, Rubin · 2013 · EN — в корпусе.
- ✅ **Robyn / Meta 2024 (arXiv 2403.14674)** · в корпусе — конвейер MMM с калибровкой.

**Триангуляция измерений:**
- **«A Hierarchy of Needs for Measuring Marketing Effectiveness»** / отраслевые обзоры триангуляции
  (Google/Meta whitepapers по MMM+experiments+attribution) · EN · СВЕРИТЬ актуальные источники при индексации.

## 4. Как запускать (следующий шаг, отдельная сессия)
Скилл `aurora-upgrade` на кабинет econometrist: находит пробелы методологии, поднимает первоисточник
RAG-библиотекой (двуязычный запрос рус+англ одной строкой — правило кросс-языка), выдаёт диф-документ
на ревью (файл скилла/промпта не трогает). Порядок ценности:
1. **pilot-design ← geo-эксперименты** (Vaver-Koehler / Kerman TBR — добавить в библиотеку, наибольший разрыв).
2. **awareness-команды ← awareness-моделирование** (Tellis / Farris).
3. **mmm-model/optimize ← приоры Meridian** (уже частично в Robyn/Meridian-доках — дешевле всего подтянуть).

Числа канона в ответах Авроры добавляются в grounded-источники стража INV-50 (уже реализовано в блоке
«Канон методологии»), не выдаются за цифры модели клиента — согласовано с петлёй Авроры.
