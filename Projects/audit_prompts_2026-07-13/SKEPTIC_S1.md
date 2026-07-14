# SKEPTIC_S1 — адверсариальная перепроверка находок аудита промптов (2026-07-13)

Метод: лично перечитаны промпты, econ-project-context.js, ChatPanel.svelte, campaign.rs,
tier2-context.js, validator.py, decomposer.py, optimizer.py, diagnostics.py, project-state.js.

**Установленный путь доставки (общий для всех 4 находок):** для консультационных команд
econometrist единственный путь данных — `ChatPanel.svelte:697-708` → `buildProjectDataBlock`
(`econ-project-context.js:142-162`). Все триггеры UI (CommandGrid/Palette/quick-start) идут через
`pendingCommand → sendMessage` (ChatPanel.svelte:389-394), т.е. через тот же инжект.
`campaign.rs::build_message_prefix` (campaign.rs:391-409) — контекст пайплайна кампаний
(бриф/бренд/шаги), MMM-артефактов не несёт. `tier2-context.js` — поверхность InsightsPanel
(Tier-2 инсайты пайплайна), к слэш-командам кабинета отношения не имеет. Альтернативного
пути, «который всё же доставляет», НЕТ — это перепроверено.

---

## Находка 1 — why-channel.md:13 «saturation point» — ВЕРДИКТ: DOWNGRADED

**Что подтвердилось:** response_curves действительно вырезаны инжектом
(econ-project-context.js:34, `const { slsqp_diagnostics, response_curves, ...rest }`).
Точка насыщения как величина есть только в response_curves (optimizer.py:1439-1485,
ключ `response_curves` в результате: optimizer.py:1598) — в блок не попадает.
В optimization.channels[] полей с именем saturation нет (optimizer.py:1391-1411).

**Что опровергнуто — «обязательная карточка „Статус saturation" без данных»:**
channels[] оптимизации доставляется целиком и несёт:
- `mroi_current` / `mroi_optimal` + CI (optimizer.py:1403-1410) — миROAS, он же прямой
  индикатор насыщения (mROI→0 = перенасыщен, mROI≫1 = недоинвестирован);
- `current_spend` / `optimal_spend` / `delta_pct` (optimizer.py:1394-1402);
- **prescriptive action-поля**: `action`/`action_label`/`action_reasoning`/`action_confidence`
  (Scale/Hold/Watch/Reduce/Cut — optimizer.py:1419-1434, compute_channel_action) — это и есть
  готовый статус 🟢🟡🔴 в словах движка.
Дополнительно в mod-секции живой сессии приходят channelParams с Hill-параметрами
насыщения alpha/gamma/beta (ConfigPanel.svelte:496, форма: hill.js:137;
stripModelTelemetry их сохраняет — чистит только внутри diagnostics,
econ-project-context.js:58-63). Оговорка: после переоткрытия проекта channelParams=null
(pickle, project-state.js:1137) — но mroi/action из optimization доставляются всегда.

**Итог:** фантом термина «saturation point» реален (числа «точки» в блоке нет), но карточка
«Статус saturation» ЗАПОЛНИМА из доставленных mroi/action — «без данных» неверно.
Severity high → medium (лечится правкой формулировки промпта, а не доставкой данных).

---

## Находка 2 — explain-ratio.md:8,34 `n_predictors` — ВЕРДИКТ: DOWNGRADED

**Что подтвердилось:** движок отдаёт `detected.n_predictors` (validator.py:827);
summarizeValidation его НЕ пробрасывает (econ-project-context.js:116-124 — выжимка:
ratio, n_rows, date_frequency, media/control/kpi_columns, high_correlations).
Поля с именем `n_predictors` в блоке нет. `file.rows` тоже приходит под именем `n_rows`.

**Что опровергнуто — «считать не из чего»:**
- `n_predictors = len(media_cols) + len(control_cols)` — точная формула движка
  (validator.py:659), а ОБА списка инжектятся поимённо
  (econ-project-context.js:120-121) → значение выводимо ТОЧНО, простым подсчётом.
- ratio доставлен дважды: validation.ratio (econ-project-context.js:117) и mqs.ratio
  в model-diagnostics (diagnostics.py:150; там же mqs.thinness_cap:149, который
  промпт тоже просит) → n_predictors = n_rows/ratio как второй путь.
- Контракт кабинета (econometrist CLAUDE.md «Правила работы с блоком») явно разрешает
  помеченные производные расчёты — подсчёт длины списков в них укладывается.

**Итог:** расхождение имён «промпт ↔ выжимка» реально (validator отдаёт — выжимка роняет),
но класс «инжект не доставляет данные» не подтверждён: значение точно выводимо из
доставленного. Severity high → low/medium (правка имени поля в промпте или +1 поле в выжимке).

---

## Находка 3 — next-quarter-plan.md:11 секция [scenarios] — ВЕРДИКТ: DOWNGRADED

**Что подтвердилось (фантом реален, опровергнуть не удалось):**
- buildProjectDataBlock не имеет параметра scenarios и рендерит фиксированный набор секций
  [model-diagnostics]/[decomposition]/[optimization]/[validation]/[project]
  (econ-project-context.js:142-162);
- ChatPanel.svelte:702-707 передаёт только mod/dec/opt/val/projectMeta;
- артефакт optimization НЕ содержит ключа scenarios (grep optimizer.py — только комментарии
  про scenario-движок; результат: optimizer.py:1590-1598 без scenarios);
- сохранённые сценарии как функция СУЩЕСТВУЮТ (project-state.js:45,55 — `scenarios: []`
  в состоянии проекта) — т.е. пользовательские сценарии реально молча игнорируются;
- фантом продублирован в econometrist CLAUDE.md:127 («scenarios (если есть)») — подтверждено;
- альтернативных путей доставки нет (см. шапку).

**Почему severity ниже high:** промпт сам помечает секцию «(если есть)»
(next-quarter-plan.md:11), а блокирующий гейт завязан ТОЛЬКО на optimization
(next-quarter-plan.md:14: «Если данных оптимизации в блоке нет — попроси запустить…»).
Отсутствие [scenarios] → штатная ветка «нет сохранённых сценариев»: ни обязательной
секции ответа, ни принуждения к выдумке. Дефект = невыполненное продуктовое обещание
(сценарии пользователя никогда не участвуют в квартальном плане), не галлюцинационный риск.
Severity high → medium.

---

## Находка 4 — data-gaps.md:8,10 `warnings` + `suspicious_channels` — ВЕРДИКТ: CONFIRMED

**Половина «warnings» — подтверждена полностью, опровергнуть не удалось:**
- движок кладёт `warnings` на верхний уровень validation-результата (validator.py:834;
  11 генераторов предупреждений: validator.py:498,522,586,594,635,682,688,701,724,734,744);
- summarizeValidation warnings НЕ включает (econ-project-context.js:116-124 — из
  диагностик только high_correlations:123);
- data-gaps.md:8 прямо велит «Из него бери: validation — … `warnings`», и для команды
  про пробелы данных это ядро входа (нулевые периоды, тонкие данные и т.п. живут именно там);
- другого пути доставки нет (см. шапку). Класс находки «промпт требует — инжект роняет»
  выполняется дословно. High justified.

**Половина «suspicious_channels» — подтверждена как имя-фантом, с оговоркой:**
- имени `suspicious_channels` нет нигде в движке/фронте (grep по репо: только промпты
  data-gaps.md:10, explain-ratio.md:31, CLAUDE.md:133 и файлы аудита);
- реальное имя — `smell_flags` (decomposer.py:1293-1319, в результате decomposer.py:1363),
  и он ДОСТАВЛЯЕТСЯ: stripDecompTelemetry вырезает только time_series/waterfall/
  signed_factor_contributions/hierarchical (econ-project-context.js:86);
- `unit_smell` из той же строки промпта доставляется (per-channel: decomposer.py:1216;
  агрегатный флаг type='unit_smell' со списком каналов: decomposer.py:1313-1319);
- т.е. семантика «подозрительных каналов» частично присутствует под другим именем
  (roi_max именует канал-рекордсмен, unit_smell — список каналов), Claude при чтении
  реального JSON скорее сопоставит. Эта половина сама по себе тянула бы на DOWNGRADED.

**Итог:** вердикт по находке в целом — CONFIRMED: стержневая претензия (warnings существует
в артефакте движка и вырезана выжимкой при прямом требовании промпта) перепроверена и стоит
как high; фантом имени suspicious_channels также подтверждён фактически.

---

## Сводка

| # | Находка | Вердикт | Ключевое доказательство |
|---|---|---|---|
| 1 | why-channel saturation | DOWNGRADED | статус выводим из mroi/action: optimizer.py:1403,1419-1434; вырезка: econ-project-context.js:34 |
| 2 | explain-ratio n_predictors | DOWNGRADED | точно выводимо: validator.py:659 + econ-project-context.js:120-121; роняется: 116-124 |
| 3 | next-quarter-plan [scenarios] | DOWNGRADED | фантом реален (econ-project-context.js:142-162, project-state.js:55), но «(если есть)» + гейт только на optimization (next-quarter-plan.md:14) |
| 4 | data-gaps warnings/suspicious_channels | CONFIRMED | validator.py:834 отдаёт, econ-project-context.js:116-124 роняет, data-gaps.md:8 требует; suspicious_channels нигде не существует (реальное имя smell_flags, decomposer.py:1363) |
