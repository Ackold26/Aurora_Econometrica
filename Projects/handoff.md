# Handoff — честный масштаб вклада для count-KPI (2.3.1, аудит-фиксы)

База diff: `aa32040` (docs-коммит до правок сессии; base-sha файл указывает на HEAD → база
взята явно по последнему коммиту до блока). HEAD: `1255db4`. Блок = `dc01a9c` + `1255db4`.

## Цель блока
Устранить занижение «вклада канала» в 1e6 раз для count-KPI (лиды/упаковки/регистрации)
в отчётах Econometrica (HTML + PPTX + JS-инсайты). Корень: вклад делился на 1e6
безусловно («₽ млн»-логика), а единица count-KPI подписывалась без «млн» → клиент видел
«1.3 лид.» вместо «1.3 млн лид.» (занижение в миллион раз). Нарушение INV-50 (честность
метрик). Фикс — согласованный выбор масштаба+единицы через `_contrib_scale`/`_fmt_contrib`.

## Ключевые инварианты
- **monetary/effectiveness поведение НЕ меняется:** масштаб 1e6, единица «₽ млн», формат
  как раньше. Регрессия здесь недопустима (основной сценарий клиентов).
- **count:** масштаб адаптивный по макс |вклад| (≥1e6→млн, ≥1e4→тыс, иначе полное число),
  единица результата из паспорта (`target_unit`), масштаб-маркер («млн»/«тыс.») в единице.
- **`display × scale ≈ raw`** — значение не занижено (анти-регресс тест на это).
- **HTML ↔ PPTX mirror:** `aurora_html.sections._contrib_scale/_fmt_contrib` и
  `aurora_pptx.kpi_helpers.contrib_scale/fmt_contrib` ОБЯЗАНЫ давать идентичный результат
  (тест `test_html_pptx_contrib_parity`). Разделитель тысяч — `chr(0xA0)` в обоих.
- **Итог столбца в ТОМ ЖЕ масштабе, что ячейки** (contrib_scale согласован шапка↔ячейка↔итог).

## Осознанные компромиссы
- **Дублирование хелперов** в HTML + PPTX модулях (не общий util): kpi_helpers импортируется
  без aurora_tokens-зависимости (для тестов), общий модуль её потянул бы. Паритет держит тест.
- **`total_contrib_mln` в narrative_adapter оставлен** (= raw/1e6) для обратной совместимости;
  consumer'ы домножают обратно `tc_raw = total_contrib_mln * 1e6` — upstream не рефакторил,
  чтобы не задеть других читателей поля.
- **Масштаб по visible каналам** (channels[:10]) — один масштаб на столбец; при сильно
  разнородных вкладах в топ-10 мелкие теряют точность (by-design, компактность таблицы).

## Зоны неуверенности
1. **Обратное домножение `tc_raw = total_contrib_mln * 1e6`** (sections.py итог + PPTX итог):
   float деление→умножение. Проверить, что итог не расходится с суммой ячеек на граничных
   значениях и что для count итог в согласованном масштабе (не «₽ млн»-формате).
2. **insights-rules.js:1566** выводит `contribution.toLocaleString` = ПОЛНОЕ число + единица
   («вклад 1 300 000 лид.»), тогда как таблица — масштабированное («1.3 млн лид.»). Обе честны,
   но масштаб РАЗНЫЙ между инсайтом и таблицей — возможная UX-несогласованность.
3. **Drill-панель** (interactive.py + builder.py:mroas_details) считает масштаб per-channel
   (по одному значению `[contribution]`), а таблица — по всем visible. Один канал в drill может
   получить масштаб, отличный от табличного (напр. канал 5000 лидов: drill «5 000 лид.», а в
   таблице при max 2млн столбец в «млн» → «0.0»). Проверить согласованность drill ↔ таблица.
4. **effectiveness-режим:** `_contrib_scale` для non-count возвращает (1e6, money_unit). Убедиться,
   что для effectiveness (доли/проценты) вклад-столбец не сломан (units["contrib"] корректен).

## Затронутые файлы
- `sidecar/econometrica/aurora_html/sections.py` — хелперы `_contrib_scale`/`_fmt_contrib` +
  применение в шапке/ячейке/итоге/CPU-единице/заголовке графика mROAS.
- `sidecar/econometrica/aurora_html/builder.py` — drill CHART_DATA count-aware (`contrib_display`/`label`).
- `sidecar/econometrica/aurora_html/interactive.py` — drill JS-подпись из `contrib_label`/`display`.
- `sidecar/econometrica/aurora_pptx/kpi_helpers.py` — mirror `contrib_scale`/`fmt_contrib`.
- `sidecar/econometrica/aurora_pptx/builder.py` — PPTX ячейка/шапка/итог count-aware.
- `sidecar/econometrica/engines/narrative_adapter.py` — комментарий-первопричина исправлен (логика не менялась).
- `src/lib/insights-rules.js` — единица к вкладу в инсайте «Топ-3 драйверов».
- `sidecar/econometrica/tests/test_report_text_kpi_aware.py` — анти-регресс тесты (значение + паритет).
- `src-tauri/{Cargo.toml,tauri.conf.json}` — bump 2.3.1 (не логика).
- `src-tauri/installer_hooks.nsh` — U+2014→«–» в комментариях + MessageBox (productName revert).
- `src/lib/components/pipeline/DecomposeStep.svelte` — tooltip «Вклад» KPI-нейтральный.
