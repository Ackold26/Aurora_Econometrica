# Проверка состояния методологии MMM по коду — 2026-08-16

**Дерево:** `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_thinwt`
**Ветка:** `master`, HEAD `6fa2498` (2026-08-16, «docs: промт следующей сессии и материалы внешнего аудита блока 2.4.10»)
**Движок:** `sidecar/econometrica/`
**Режим:** только чтение. Изменений не вносилось, записей не делалось.
Все пути ниже — относительно `sidecar/econometrica/`, если не указано иное.
Поиск везде исключал `__pycache__`, `dist/`, `_internal/`, `target/`.

---

## 1. Зерно случайности (воспроизводимость) — **ЗАКРЫТО**

**Признак:** каждый вызов сэмплера несёт именованный `random_seed`, зерно разрешается
в одном месте и записывается в паспорт расчёта, который доезжает до сертификата.

**Доказательство.** Вызовов `pm.sample(` во всём движке ровно три, все в `engines/modeler.py`,
и все три с зерном:
- `engines/modeler.py:1061-1065` — Tier-1 NumPyro NUTS: `trace = pm.sample(... random_seed=mcmc_seed, ... nuts_sampler='numpyro')`
- `engines/modeler.py:1113-1118` — Tier-2 PyTensor NUTS (с callback): `random_seed=mcmc_seed`
- `engines/modeler.py:1127-1132` — Tier-2 без callback (запасной путь при `TypeError`): `random_seed=mcmc_seed`

Источник зерна один: `engines/modeler.py:783-795`
```
        resolve_seed,
    mcmc_seed, mcmc_seed_source = resolve_seed(config)
        seed=mcmc_seed,
        seed_source=mcmc_seed_source,
    f'Воспроизводимость: зерно={mcmc_seed} (источник: {mcmc_seed_source})'
```
Реализация — `utils/seeding.py:60 def resolve_seed(...)`, пробрасывается из HTTP-слоя
(`server.py:423`: «P0.2 (воспроизводимость): зерно MCMC. None → utils/seeding.resolve_seed»).

**Запись в сертификат — есть.** `engines/methodology_cert.py:585 _extract_reproducibility(...)`:
```
    return {
        'status': 'recorded',
        'seed': snapshot.get('seed'),
        'seed_source': snapshot.get('seed_source'),
        'sampler_tier': snapshot.get('sampler_tier'),
        'mcmc': snapshot.get('mcmc'),
        'versions': {...'python','numpy','pymc'...},
    }
```
Сертификат не мёртвый: единственная точка вызова — `engines/decomposer.py:599-622`
(`from engines.methodology_cert import generate_methodology_certificate`), результат кладётся
в `engines/decomposer.py:1517 result['methodology_certificate']` и читается отчётом
(`aurora_html/builder.py:590`, `engines/narrative_adapter.py:1336`).

Дополнительно зафиксирована раскладка цепей (`mark_chain_layout`, `engines/modeler.py:1051-1055`)
— при одном зерне `parallel` и `vectorized` дают разные числа, это часть паспорта.
Режим малых данных (МНК) паспорта не пишет намеренно: зерно бутстрапа зашито
(`ols_modeler.py:300,320`, `seed=42`), статус в сертификате — `deterministic`
(`engines/methodology_cert.py:600-607`).

Сторож в тестах: `tests/test_mcmc_seeding_ast.py:123` — обходом дерева проверяет,
что каждый `pm.sample(...)` в `modeler.py` несёт `random_seed`, и что вызовов не меньше трёх.

**Запись, которой закрыто:** `cfe5443` «P0.2 шаги 3-5: расчёт воспроизводим — зерно сэмплера и паспорт среды».

---

## 2. Интерполяция пропусков — **ЧАСТИЧНО** (интерполяции нет; противоречие в подсказке живо, но валидатор теперь говорит правду)

**Признак:** ищем в рабочем пути (а) реальную интерполяцию, (б) текст обещания.

**Интерполяции в коде нет.** Ни одного `.interpolate(` в `sidecar/econometrica/`.
Обучение по-прежнему заполняет нулём:
- `engines/modeler.py:569` — `raw_arr = df[col].fillna(0).values.astype(float)`
- `engines/modeler.py:578` — `X_control = df[control_cols].fillna(0).astype(float) ...`
- `engines/modeler.py:742`, `engines/modeler.py:1771`, `engines/ols_modeler.py:120,177,208,287` — то же.

**Обещание живо в двух местах интерфейса:**
- `src/lib/data/tooltip-texts.js:137` — «…**Программа интерполирует малые пробелы**; при > 20% пропусков лучше исключить столбец.»
- `src/lib/insights-rules.js:752` — `tip: 'Линейная интерполяция заполнит небольшие пробелы. При >20% пропусков столбец лучше исключить…'`

(Оба пути — в дереве `Aurora_Econometrica_thinwt`, ветка `master`. Заметь: путь подсказок
в задании указан как `src/lib/tooltip-texts.js`, фактически файл лежит в `src/lib/data/tooltip-texts.js`.)

**Что появилось с 02.08 — честное предупреждение валидатора** (`engines/validator.py:618-631`):
```
                elif role in ('media', 'control'):
                    # modeler.py: df[col].fillna(0) — пропуск становится нулём,
                    # то есть «активности не было». Интерполяции в коде нет.
                    warnings.append({ 'type': 'missing_filled_with_zero',
                        'message': (f'{col} - пропусков {_missing_pct}% ... '
                        f'При обучении они считаются нулём, то есть «активности не было». '
                        f'Восстановления пропущенных значений в расчёте нет - если данные '
                        f'просто не собраны, заполните их до обучения.'), 'severity': 'warning'})
```
Плюс отдельное предупреждение для KPI (`validator.py:605-617`): строки с пропуском целевой
метрики выбрасываются целиком вместе с медиа-данными периода.

**Чего не хватает:** интерполяция не реализована, и **два текста интерфейса продолжают обещать
то, чего движок не делает** — валидатор в том же прогоне утверждает обратное. Противоречие
не устранено, оно перенесено внутрь продукта: подсказка обещает восстановление, предупреждение
валидатора его отрицает.

---

## 3. Три проверки здоровья по Meridian — **ЧАСТИЧНО (1 из 3)**

### (а) Апостериорное предиктивное p-значение — **НЕ ЗАКРЫТО**
Ни `ppp`, ни байесовского p-значения в движке нет. Больше того, апостериорная предиктивная
выборка сознательно не считается — `engines/modeler.py:1216-1224`:
```
        # Posterior predictions - reconstructed from posterior means directly.
        # Причина: pm.sample_posterior_predictive на модели с Hill saturation
        # рекомпилирует PyTensor graph для каждого posterior draw (4×2000 = 8000),
        # что даёт 13+ минут на Windows...
        # Downstream (decomposer/optimizer) НЕ читает trace.posterior_predictive -
        # только y_pred_norm нужен для диагностики y_pred vs actual.
```
То есть база для ppp (`trace.posterior_predictive`) в модели отсутствует по решению о скорости.

Ближайшее живое — **априорная** предиктивная проверка (не та, что в пункте):
`utils/reliability_a4.py:36 def prior_predictive_check(...)` — сэмплирует из приоров и смотрит,
покрывает ли 5–95% диапазон симулированного y наблюдаемый. Вызывается в обучении
(`engines/modeler.py:746-753`) и доезжает до клиента (`narrative_adapter.py:1080`,
`aurora_html/sections.py:2449`, `aurora_pptx/builder.py:3412`). Записи: `384e504`, `bd5936b`.

### (б) Проверка отрицательного базового уровня — **ЗАКРЫТО**
`utils/negative_baseline.py` реализован и **вызывается в рабочем пути обучения** —
`engines/modeler.py:1735-1744`:
```
            from utils.negative_baseline import compute_negative_baseline
            diagnostics['negative_baseline'] = compute_negative_baseline(
                intercept_samples=..., control_betas_samples=..., x_control_norm=...,
                y_mean=y_mean, y_std=y_std)
```
Результат доезжает до сертификата (`engines/methodology_cert.py:644-657`, состояния
`passed` / `not_applicable` / `absent`) и до отчёта (`aurora_html/sections.py:1843`).
Отдельно отмечено, что «неприменимо» не выдаётся за «годно» (`methodology_cert.py:625-631`).
Записи: `278a3af` («fix: audit findings P0.6 — проверка базы не гаснет от одного отсчёта…»).

### (в) Сдвиг приор→постериор по ROI — **НЕ ЗАКРЫТО**
Поиск по `prior_posterior`, `сдвиг приор`, `shift.*prior` во всём движке даёт единственное
попадание — глоссарий слайда `aurora_pptx/builder.py:4027` («Априорное / апостериорное»).
Ни расчёта, ни диагностики, ни показа.

---

## 4. Тест на подставной канал (placebo/shuffled channel) — **НЕ ЗАКРЫТО**

Все попадания по `placebo` / `shuffle` / «плацебо» — только в причинном блоке:
`engines/causal/scm.py:175 def _placebo_inference(...)` — permutation inference по донорам
синтетического контроля (Abadie 2021), плюс упоминание в `engines/causal/common.py:41`
(`- 'placebo' - SCM permutation inference`).

Это плацебо **по единицам панели в SCM**, а не подставной/перемешанный медиа-канал в MMM:
в `engines/modeler.py` и в диагностике нет ни ветки, где в модель добавляется случайный
канал-пустышка, ни проверки, что его вклад статистически неотличим от нуля.
Шестого теста рамки mmm-eval нет.

---

## 5. Тренд отдельной компонентой — **НЕ ЗАКРЫТО**

Свободный член так и остался скаляром: `engines/modeler.py:811`
```
            intercept = pm.Normal('intercept', mu=0, sigma=0.5)  # было sigma=1
```
и входит в среднее как константа: `engines/modeler.py:974` — `mu = intercept + media_effect + control_effect`.
Переменного во времени базового уровня нет.

Что есть вместо: **сезонность** Фурье, автоматически добавляемая обычными контролями —
`engines/modeler.py:485-517` (`generate_fourier_terms`, `should_inject_seasonality`),
реализация `utils/fourier_seasonality.py` (канон Prophet §3.2). Это периодическая волна,
а не тренд; в самом модуле отмечено, что при <2 циклах «сезонность неотличима от тренда»
(`utils/fourier_seasonality.py:43`).

`GaussianRandomWalk` встречается **только в комментариях** `engines/modeler.py:316,323,332`
про режим awareness (Phase A1a); ни одного вызова `pm.GaussianRandomWalk` в дереве нет,
в `engines/awareness.py` вообще нет обращений к `pm.*`. Гауссовского процесса, узловой
интерполяции и Prophet-подобной кусочно-линейной компоненты тренда нет.

---

## 6. ROI-приор из эксперимента (Meridian) — **НЕ ЗАКРЫТО** (класс Robyn на месте, ROI-приора нет)

Реализован ровно тот класс, что и был: лифт как дополнительное наблюдение правдоподобия.
`utils/calibration.py:1-9` (шапка модуля):
```
"""E2 (2026-07-03): калибровка модели lift-тестами — подготовка и валидация.
Канон: Robyn (Meta 2024, arXiv 2403.14674) §2.2/§4.3 ...
Реализация Aurora — MAPE.LIFT-класс: измеренный lift входит в модель
ДОПОЛНИТЕЛЬНЫМ НАБЛЮДЕНИЕМ правдоподобия (см. modeler) ...
```
Вживление — `engines/modeler.py:955-960` (Deterministic `calib_contrib_{i}` на период теста).

Поиска по `roi_prior` / «приор ROI» во всём движке — ни одного попадания в расчётном коде;
единственное совпадение текстовое, в примерном тексте слайда (`aurora_pptx/builder.py:2896`).
То есть канала «эксперимент → приор на ROI канала» (Meridian) нет.

---

## 7. Обучаемый Weibull-adstock — **НЕ ЗАКРЫТО** (прямо помечено как задел)

`engines/modeler.py:938-941` — рабочая ветка построения adstock внутри модели:
```
                else:
                    # Weibull stays hardcoded (Phase 1.5 task to make learnable)
                    adstock_full = pt.as_tensor_variable(X_media[col].values)
```
То есть у геометрического adstock затухание сэмплируется (`adstock_decay`, иерархический
logit-normal, `engines/modeler.py:874-909`), а Weibull-каналы входят предпосчитанной
свёрткой с зашитыми параметрами. Комментарий `engines/modeler.py:913`:
«Weibull channels: pre-computed (decay sampling deferred to Phase 1.5)».

Выбор типа adstock из данных есть, но это отбор по BIC на быстрой МНК-модели вне байеса —
`engines/adstock_selector.py:70` (`for adstock_type in ['geometric', 'weibull']`), сравнение
`bic_geometric` / `bic_weibull`. Сами shape/scale Weibull из данных не оцениваются.
Строка «Weibull stays hardcoded» живёт с записи `228b365` и не менялась.

---

## 8. Журнал приоров экспериментов — **ЧАСТИЧНО**

**Есть сверка калибровки, привязанная к модели.** `engines/modeler.py:1863-1890`:
```
            _calib_checks.append({
                'channel': ..., 'test_type': ..., 'date_from': ..., 'date_to': ...,
                'test_lift': _calib['lift_abs'], 'test_sigma': _calib['sigma_abs'],
                'model_contrib_mean': round(float(_arr.mean()), 2),
                'model_contrib_ci90': [round(_lo, 2), round(_hi, 2)],
                'within_ci': bool(_lo <= _calib['lift_abs'] <= _hi)})
            diagnostics['calibration_check'] = _calib_checks
            diagnostics['calibration_applied'] = [...]
```
Доезжает до клиента: `engines/narrative_adapter.py:1087-1093` →
`diagnostics["calibration"] = {"applied": ..., "checks": ...}`; расхождение не замалчивается
(`within_ci=False` показывается). Запись: `9b72f22` («секция „Петля доверия“ — E1-E4 блоки»).

**Чего не хватает.** Это сверка «постериорный вклад модели против измеренного лифта»,
а не запись «как приор изменил оценку»: нигде не сохраняется оценка ДО калибровки
(модель без вживлённого наблюдения) рядом с оценкой ПОСЛЕ, нет ни дельты ROI/β,
ни накопительной истории по проекту между обучениями — `calibration_check` живёт внутри
диагностики конкретной модели и перезаписывается следующим обучением.

---

## 9. mmm-eval (открытая рамка Mutinex) — **НЕ ЗАКРЫТО** (следов ноль)

Поиск `mmm-eval` / `mmm_eval` по всему дереву `Aurora_Econometrica_thinwt`
(без `node_modules`, `.git`, `dist`, `target`, `_internal`, `__pycache__`) даёт **одно**
попадание — мой собственный маячок `Projects/PULSE_verify_method_2026-08-16.md`.
Ни скрипта прогона, ни отчёта, ни упоминания в документах, ни зависимости в
`sidecar/econometrica/requirements.txt`.
Контрольно проверила план-уровень `D:\Docs\Aurora_Ai\aurora-meta` — там тоже ноль попаданий.

---

## 10. Гео-иерархия (мультирегиональная модель) — **НЕ ЗАКРЫТО**

**Роли «регион» в распознавании колонок нет.** В `utils/column_detection.py` нет ни одного
образца по `регион` / `region` / `geo` / `город` (единственные совпадения по слову «журнал» —
это шаблон печатной прессы, `column_detection.py:402`).

**Иерархия в модели — только по типу канала.** `engines/modeler.py:359`:
«Если ≥2 канала в одной из brand/performance групп → hierarchical priors path»,
далее `use_hierarchical = is_hierarchical_eligible(channel_categories)`
(`engines/modeler.py:375`), ветка `engines/modeler.py:830-831` — «Trust Level 3: hierarchical
brand vs performance priors». Географического измерения в модели нет.

Гео живёт только в причинном блоке и как синтетика: `engines/causal/_panel_data.py:218
def synthesize_geo_split(...)` — «Synthesize geo split for AGGREGATED data (M0/M1 fallback)»,
разрезает агрегат случайной стратификацией для DiD/SCM. Комментарий там же
(`causal/_panel_data.py:11`) прямо говорит: реальных панельных данных с гео-разрезом
у клиентских наборов (Kagocel, Афала) нет.

---

## Сводная таблица

| № | Пункт | Вердикт | Доказательство |
|---|---|---|---|
| 1 | Зерно случайности | **ЗАКРЫТО** | `engines/modeler.py:1065,1118,1132` — `random_seed=mcmc_seed`; источник `utils/seeding.py:60`; в сертификат — `engines/methodology_cert.py:585-618`; сторож `tests/test_mcmc_seeding_ast.py:123`; запись `cfe5443` |
| 2 | Интерполяция пропусков | **ЧАСТИЧНО** | `.interpolate(` нет нигде; `engines/modeler.py:569,578` — `fillna(0)`; честное предупреждение `engines/validator.py:618-631`; обещание живо — `src/lib/data/tooltip-texts.js:137`, `src/lib/insights-rules.js:752` |
| 3а | Апостериорное предиктивное p-значение | **НЕ ЗАКРЫТО** | `engines/modeler.py:1216-1224` — posterior predictive сознательно не считается; ppp нет |
| 3б | Отрицательный базовый уровень | **ЗАКРЫТО** | `engines/modeler.py:1735-1744` вызывает `utils/negative_baseline.py`; в сертификат `engines/methodology_cert.py:644-657`; запись `278a3af` |
| 3в | Сдвиг приор→постериор по ROI | **НЕ ЗАКРЫТО** | единственное попадание — глоссарий слайда `aurora_pptx/builder.py:4027` |
| 4 | Подставной канал (placebo/shuffle) | **НЕ ЗАКРЫТО** | только SCM-плацебо по донорам `engines/causal/scm.py:175`; в MMM-модели ветки нет |
| 5 | Тренд отдельной компонентой | **НЕ ЗАКРЫТО** | `engines/modeler.py:811` — `intercept = pm.Normal(...)` скаляр; `pm.GaussianRandomWalk` не вызывается ни разу; есть только Фурье-сезонность `modeler.py:485-517` |
| 6 | ROI-приор из эксперимента | **НЕ ЗАКРЫТО** | `utils/calibration.py:1-9` — класс Robyn (лифт как наблюдение); `roi_prior` в расчётном коде отсутствует |
| 7 | Обучаемый Weibull-adstock | **НЕ ЗАКРЫТО** | `engines/modeler.py:939` — `# Weibull stays hardcoded (Phase 1.5 task to make learnable)` |
| 8 | Журнал приоров экспериментов | **ЧАСТИЧНО** | сверка есть — `engines/modeler.py:1863-1890`, показ `narrative_adapter.py:1087`; нет оценки «до/после приора» и накопительной истории |
| 9 | mmm-eval | **НЕ ЗАКРЫТО** | ноль попаданий по дереву и по `aurora-meta` |
| 10 | Гео-иерархия | **НЕ ЗАКРЫТО** | роли «регион» нет в `utils/column_detection.py`; иерархия только brand/performance — `engines/modeler.py:359,375,830`; гео — лишь синтетика в `causal/_panel_data.py:218` |

**Итог: 2 закрыто, 2 частично, 7 не закрыто** (пункт 3 считаю по трём подпунктам отдельно: 1 закрыт, 2 нет).

**Мёртвого кода среди проверенного не нашла:** у всех найденных реализаций
(`compute_negative_baseline`, `prior_predictive_check`, `generate_methodology_certificate`,
`resolve_seed`, `prepare_calibrations`, `_placebo_inference`) есть живые вызывающие
в рабочем пути.

ПРОВЕРКА ЗАВЕРШЕНА — 2026-08-16, 02:20.
