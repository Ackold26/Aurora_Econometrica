# Пульс 3а – единый источник вердикта о надёжности

## Задача своими словами
Программа одновременно отключает рекомендации по переброске бюджета (расчёт не сошёлся) и
пишет клиенту «результат надёжен для бюджетных решений» – две шкалы живут порознь.
Нужно завести один источник согласованной фразы (по ступени качества + признаку отказа),
починить корень в `generate_diagnostics_summary`, и заставить все одиннадцать мест
звать этот источник или зеркалить его дословно под тестом-сторожем.
Числа при этом клиент видеть должен – гейтим утверждение о надёжности, не данные.

## План
1. Разведка по факту: `optimizer_honesty.py`, `diagnostics.py`, все места из карты.
2. Python: функция-источник в `utils/diagnostics.py` + починка корня.
3. Python-потребители: `aurora_html/sections.py`, `aurora_pptx/builder.py`.
4. Тесты движка + мутации на каждый сторож.
5. Rust `report.rs` – дословное зеркало + тест-сторож (прогон только по сигналу лида).
6. Фронт `MQSBadge`.
7. Финальный поиск по сигнатуре класса дефекта в своих же правках.

## СТАРТ
2026-08-09 – ветка `master`, голова `d897362`. Начинаю разведку по факту.

## Разведка по факту (сделано)
Прочитала целиком: `utils/diagnostics.py`, `utils/optimizer_honesty.py`; по местам –
`report.rs` (30-160, 270-302, 480-640, 640-754, 1240-1352), `aurora_html/sections.py`
(400-490, 740-968, 1956-2070, 2340-2420), `aurora_pptx/builder.py` (1000-1058, 3185-3359),
`MQSBadge.svelte` целиком, `engines/modeler.py` 1340-1422, `tools/recompute_mqs.py` 60-129.

Адреса из карты подтвердились. Уточнения:
- `sidecar/econometrica/_internal/` и `target/` – артефакты сборки, вне системы версий
  (`git ls-files` пуст). Правлю только исходники.
- Вторая точка MQS в HTML – не только `render_at_a_glance:888-948`, но и
  `render_sources:1956-2070` (карточка «Качество модели»). В карте её не было.
- `MQSBadge.svelte` своего текста о надёжности не держит: печатает `diagnostics.verdict`
  из корня. Чинится корнем, кода трогать не нужно.
- Признак отказа доступен всюду: `optimize.model_reliability.refused` (Rust),
  `honesty_verdict == 'unreliable'` (builder/sections). В корне – НЕТ, там только
  `r_hat_max`/`divergences`, а порог по дивергенциям зависит от числа черновиков
  (`max(20, 1% draws)`), которых корню не передают. Значит нужен общий предикат
  + проброс `total_draws` из `modeler.py` (там `chains`/`draws` уже под рукой).
- 🔴 Ловушка: сторож `test_thinness_caveat_mirror.py::test_rust_does_not_carry_abandoned_alarmism`
  запрещает в клиентском тексте `report.rs` оборот `результат\w*\s+(?:не\s*)?надёжн`.
  Значит фразу «Результаты ненадёжны – …» в Rust зеркалить нельзя (и не нужно).

## Решение (до кода)
Единый источник – `utils/diagnostics.py::reliability_statement(tier, refused, thin, high_fit)`
+ шесть именованных констант-фраз. Предикат отказа – `optimizer_honesty::model_did_not_converge`,
им же пользуется сам `model_reliability_verdict` (разойтись физически не могут).
Правило, которое ввожу: **где печатается ступень MQS, там при отказе печатается
согласованная фраза**; при отсутствии отказа тексты не меняются (хирургия).

## Сделано (Python)
1. Базовый прогон ДО правок: `Projects/gate_3a_baseline_sidecar.log` –
   **1037 passed, 1 skipped, 40.46s**, выход 0.
2. `utils/optimizer_honesty.py` – заведены `REFUSING_VERDICT`, `verdict_refuses()`,
   `divergence_refuse_threshold()`, `model_did_not_converge()`; сам
   `model_reliability_verdict` переведён на общий порог.
3. `utils/diagnostics.py` – шесть констант-фраз + `reliability_statement()`.
4. `utils/diagnostics.py::generate_diagnostics_summary` – новый параметр
   `total_draws`, зовёт общий предикат отказа, вердикт собирается как
   «зачин + фраза из источника + оговорка о тонких данных».
5. `engines/modeler.py:1363` и `tools/recompute_mqs.py:89` – передают `total_draws`.
6. `aurora_html/sections.py` – `render_at_a_glance` (подпись под баллом) и
   `render_sources` (карточка «Качество модели»).
7. `aurora_pptx/builder.py` – подпись выводов s5 и фраза под карточкой MQS слайда.

Зонд доказанного сценария: `Projects/gate_3a_probe_root.log` –
MQS 88 «Отличное» на месте, `refused=True`, вердикт стал
«Модель объясняет 97% вариации продаж (R²). Расчёт не сошёлся – цифры показаны
как есть, но опираться на них при распределении бюджета рано; переобучите модель.»

Прогон после правок Python: `Projects/gate_3a_python_after.log` –
**1037 passed, 1 skipped, 40.34s**, выход 0. Ни один существующий текст не сломан.

## Сторожа и мутации (сделано)
Новые файлы: `sidecar/econometrica/tests/test_reliability_statement_single_source.py`,
`sidecar/econometrica/tests/test_reliability_statement_mirror.py`,
`src/lib/__tests__/insights-rules-refusal-honesty.test.js`.

Тринадцать мутаций, каждая – краснота по адресу, откат, зелень. Журналы:
`gate_3a_mut1_root.log` … `gate_3a_mut13_js_structural.log`.
Гейт вёрстки презентации при этом поймал НАСТОЯЩЕЕ наложение: фраза под карточкой
MQS налезала на блок «PRIMARY» (y=6.0). Перенесла внутрь карточки под сетку
метрик – `gate_3a_guard_py.log`, 29 passed.

🔴 Помеха прогонов: два моих pytest-прогона запустились одновременно и намертво
встали на 94% (гонка, о которой прямо предупреждает `pytest.ini`). Снимала
точечно по PID (машина общая, чужие python-процессы не трогала), перезапустила
один – 30.90s.

## Финальный приём – поиск по сигнатуре
Сигнатура: «утверждение о применимости/надёжности печатается без проверки признака
отказа». Поиск по своим правкам ungated-мест не дал. **Но поиск нашёл двенадцатое
место, которого не было в карте лида:** `src/lib/insights-rules.js:1385` и `:2334` –
панель выводов и сводка отчёта печатали «Результаты надёжны для принятия решений»
из одной ступени MQS, и слова «refused» в файле не встречалось ВООБЩЕ. Починила
тем же приёмом (зеркало в `src/lib/mqs-tiers.js` + сторожа).

## Итоговые прогоны
- Python sidecar: `Projects/gate_3a_python_final.log` – **1070 passed, 1 skipped, 38.68s**, выход 0 (база была 1037).
- Python tools (как в CI): `Projects/gate_3a_tools_full.log` – **2288 passed, 7 skipped, 109.67s**, выход 0.
- vitest: `Projects/gate_3a_js_final.log` – **1465 passed, 99 файлов, 101.73s**, выход 0.
- svelte-check: `Projects/gate_3a_svelte_check.log` – **0 ERRORS**, 177 предупреждений (все прежние).

## Rust – сигнал получен, прогнано
Довесок лида (чисто текстовый): `claude.rs:159` и `rag_client.rs:87` –
«данные не уходят (на серверы)» → «материалы не уходят с этой машины».
Тестов на этот текст нет – проверила поиском, зависимостей не нашлось.
🔴 Уточнение: лид сослалась на `claude.rs:150` как на образец новой формулировки,
но там комментарий со СТАРОЙ («данные не уходят»). Взяла образец из
`InsightsPanel.svelte:460`, где формулировка действительно новая.

- `cargo test`: `Projects/gate_3a_cargo_test.log` – **397 passed, 4 failed, 3 ignored, 57.19s**.
  Все четыре падения – сетевые тесты `content_updater` (порты 9169/9173/9222/9224),
  моего кода не касаются.
- Перепроверка отдельным прогоном: `Projects/gate_3a_cargo_content_updater.log` –
  **53 passed, 0 failed** при `--test-threads=1`. Падения средовые (гонка портов).
- Мои пять Rust-тестов: **все ok** (проверила поимённо в журнале).
- Счёт тестов: `git show HEAD:report.rs` – 24 `#[test]`, сейчас 29. Значит lib-набор
  был 399, стал 404. Ориентир лида «401» разошёлся на два – не мой регресс.
- `cargo clippy` как в CI (`-- -D warnings`, без `--all-targets`):
  `Projects/gate_3a_cargo_clippy_ci.log` – **выход 0, чисто**.
- `cargo clippy --all-targets`: 8 ошибок, все прежние и в чужом тестовом коде
  (`metrics/collector.rs`, `sidecar_runtime.rs`), ни одной в моих файлах.
  CI эту цель не гейтит. Журнал: `Projects/gate_3a_cargo_clippy.log`.
- Зеркала сверены после правок Rust: `Projects/gate_3a_final_mirror.log` – 44 passed.
