# pharma manufacturer - запрос regional data для Aurora Econometrica Causal v1.0.15

**Created:** 2026-04-27
**Контекст:** Sprint 3 Pharma Causal backend M0-M4 + UI shipped в v1.0.14 на synthetic-only validation (DGP-controlled ground truth recovery, 488 tests PASS). Real-customer validation запланирован в v1.0.15 - требуются geo-disaggregated данные pharma manufacturer.
**Action:** Антон отправляет запрос; шаблон ниже.

---

## Шаблон письма / сообщения

> **Тема:** Запрос данных для нового модуля Aurora Econometrica - региональная аналитика causal-эффектов
>
> Привет [имя],
>
> Мы выкатили новый модуль причинно-следственного анализа в Aurora Econometrica - поверх MMM добавили три causal-метода: Difference-in-Differences (для оценки эффекта пилотных регионов), Synthetic Control Method (для post-hoc оценки holdout markets) и Causal Forest (heterogeneous treatment effects по сегментам).
>
> Чтобы валидировать модуль на реальных данных pharma manufacturer и подготовить v1.0.15 c case-study на pilot datasets, нам нужна региональная разбивка данных, которые у вас и так трекаются:
>
> 1. **Регион / город** - идентификатор административной единицы (область, город, ФО - что у вас в источнике).
> 2. **Месячные данные продаж по бренду** в каждом регионе:
>     - Продажи в рублях (ваш текущий KPI)
>     - Продажи в упаковках (опционально)
> 3. **Treatment markers** - для каждого региона × месяца флаг получал ли регион specific marketing activity. Например:
>     - Был ли активный TV-флайт в этом регионе?
>     - Было ли промо ритейлеров?
>     - Был ли запуск новой кампании / digital push?
>     - Любые другие региональные интервенции, которые вы и так отслеживаете.
>
>    Удобный формат: бинарный флаг 0/1 per region × month per intervention type.
>
> 4. **(Опционально) контрольные переменные** - региональные демографические / экономические показатели если есть (численность, средний доход, доля городского населения, etc.). Для Causal Forest сегментирующих features.
>
> Период - те же 31 неделя что в существующем pilot pharma dataset, плюс если можно - extended history до 2-2.5 лет (для SCM нужно ≥6 pre-treatment периодов на каждое регион × intervention).
>
> Формат: xlsx или csv в long-format (одна строка = регион × месяц × kpi × treatment markers). Если у вас сейчас wide-format - мы трансформируем сами, главное чтобы был региональный idиентификатор и временная ось.
>
> Если регионального split на бренд-уровне нет, но есть на уровне SKU или цепочка → distribution channel → регион, тоже подходит - мы можем агрегировать.
>
> С удовольствием организую короткий созвон чтобы обсудить - что у вас уже есть в готовом виде vs что нужно подсобрать. Также могу прислать synthetic example датасета чтобы показать желаемый формат.
>
> Cпасибо!
>
> Антон

---

## Минимально необходимый объём для validation

| Метод | Минимум | Ideal |
|-------|---------|-------|
| **DiD** | 4 региона × 12 месяцев × treatment column (1 для treated регионов в post-period) | 8+ регионов × 24 месяца + 2-3 контрольных переменных |
| **SCM** | 5 регионов × 18 месяцев (6 pre + 12 post) | 10+ регионов × 24-36 месяцев |
| **Causal Forest** | 100 observations (например 5 регионов × 20 месяцев), binary T, 2-3 features | 300+ obs, 5+ features |

Для validation v1.0.15 достаточно "минимум" по любому из 3 методов - затем UI live-test через все 3 endpoints (`/compute/causal/did`, `/scm`, `/forest`) на real data, comparison с ground-truth client knowledge.

---

## Что Aurora Econometrica делает с данными после получения

1. Загружаем в `causal/` workspace проекта pharma manufacturer (изолированный pickle/JSON, не смешивается с MMM моделями)
2. Запускаем `/compute/causal/preflight` - определяет какие методы applicable
3. Прогоняем все applicable methods через UI route `/causal`
4. Cross-method consistency check: triangulation verdict (методы согласуются?)
5. Сравниваем ATT с known business-knowledge: "pilot pharma dataset флайт в Q3 дал ~X% lift в регионах А/Б/В" - ATT estimate должен попадать в ожидаемый диапазон
6. Если consistency='agree' и diagnostics ok → ship v1.0.15 с pharma manufacturer case-study slide deck
7. Если 'disagree' → debug assumptions через honest_disclosure block, либо downgrade к directional-only claim

---

## Privacy / data handling

- Данные хранятся локально на машине Антона (`%USERPROFILE%\AppData\Local\aurora-econometrica-gui\projects\<id>\causal\`)
- В Aurora pickle/JSON артефакты не uploaded никуда автоматически
- Если pharma manufacturer просит NDA - готовы подписать перед передачей
- После validation v1.0.15 ship - данные продолжают использоваться только Антоном для дальнейших client analyses, не share к третьим лицам без отдельного permission
