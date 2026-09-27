# PULSE s51 phaseC — правка интерфейса CPD-84 (JS-класс дыры)

## Задача (своими словами)
В Rust уже закрыт CPD-84: неизвестный продукт → "unknown" → пустой список кабинетов (закрыто по умолчанию), "media" — без ограничения (явная ветка). В JS тот же класс дыры жив в трёх местах: filterCabinetsByProduct (незнакомый продукт видит ВСЕ кабинеты), creative-store.js (ошибка определения продукта → 'agency' = все кабинеты), insights-rules.js (сумма долей топ-3 целым числом вместо десятых). Нужно свести JS с Rust-поведением, добавить тесты с мутационной проверкой, прогнать vitest+check.

## План
1. Изучить command-meta.js/command-meta-data.json + cabinet.rs → таблица продуктов
2. Править filterCabinetsByProduct: явный список "без ограничения" продуктов, unknown/незнакомое → []
3. creative-store.js: 'agency' → 'unknown' (init + catch), grep потребителей productType
4. insights-rules.js: top3Sum.toFixed(0) → formatChannelSharePct(top3Sum), grep других toFixed(0) для долей канала
5. Тесты (а) filterCabinetsByProduct (б) creative-store unknown (в) insights top3 форматирование
6. Мутации по каждому тесту с отметкой в маячке
7. vitest run + npm run check, логи в Projects/

## Старт
04:37:25
Начало работы.
ЕСЛИ МЕНЯ ОБОРВЁТ, ПРОДОЛЖАТЬ ОТСЮДА: изучаю command-meta.js и cabinet.rs, п.1 плана.

04:40:40 — п.1 и п.3 исследованы, правка insights-rules.js:1692 внесена (top3Sum.toFixed(0) → formatChannelSharePct(top3Sum)). Другие toFixed(0) в insights-rules.js и src/lib/components/pipeline — все НЕ про долю канала в медиа-вкладе (base_pct, MQS, R², спред бюджет/эффект и т.п.) либо УЖЕ через formatChannelSharePct. Таблица продуктов (Rust cabinet.rs vs JS command-meta-data.json):

| Ключ | Rust filter_by_product | JS _products.cabinets сейчас | JS после |
|---|---|---|---|
| agency | None (все) | null → все (верно) | явный список UNRESTRICTED → все |
| creative-hub | None (все) | null → все (верно) | явный список UNRESTRICTED → все |
| media | None (все, ловушка B чужая линия ROSST_AI_Media) | [media-analyst,communication-analyst,social-listening,econometrist] → ОГРАНИЧЕНО (расхождение с Rust) | явный список UNRESTRICTED → все (как Rust) |
| legal/creative/docmaster/analytics-hub/econometrica | Some([...]) | [...] соответствует | без изменений |
| unknown | Some([]) пусто | НЕТ записи → !allowed true → ВСЕ (дыра CPD-84) | [] пусто |
| любой другой незнакомый ключ | Some([]) пусто (умолчание _) | НЕТ записи → ВСЕ (дыра CPD-84) | [] пусто |

ЕСЛИ МЕНЯ ОБОРВЁТ, ПРОДОЛЖАТЬ ОТСЮДА: правлю filterCabinetsByProduct в command-meta.js (добавить UNRESTRICTED_PRODUCT_KEYS = agency/creative-hub/media, unknown → []), затем creative-store.js (agency→unknown), затем тесты.

## Продолжение (исполнитель 2)
Оставшаяся задача: (1) creative-store.js catch-ветка 'agency'→'unknown' + grep потребителей productType/$productType на 'agency'-default и падения при 'unknown'; (2) тесты vitest: filterCabinetsByProduct (unknown/выдуманный/agency/creative-hub/media/econometrica), creative-store (init fail → unknown, начальное значение), decomposeInsights (топ-3 доля X.Y%); (3) мутация-подтверждение каждого теста в маячке; (4) vitest run + npm run check, логи в Projects/.
План: п.1 grep+правка → п.2 тесты по образцу существующих в __tests__ → п.3 мутации по очереди → п.4 прогоны.
05:12:30 — старт продолжения, изучила diff предшественника (command-meta.js/creative-store.js/insights-rules.js готовы согласно заданию), начинаю п.1.
ЕСЛИ МЕНЯ ОБОРВЁТ, ПРОДОЛЖАТЬ ОТСЮДА: правлю creative-store.js catch-ветку на 'unknown', затем grep потребителей productType.

05:13:48 — п.1 готово. creative-store.js catch-ветка 'agency'→'unknown' внесена (строка ~72-73). Grep потребителей productType/$productType по src/ — список мест:
- routes/cabinet/+page.svelte: getProductName($productType) — фолбэк 'Aurora AI' на unknown, безопасно
- routes/+page.svelte: filterCabinetsByProduct($layoutCabinets, $productType) — пусто на unknown, но +layout.svelte комментарий (строка 179-181) подтверждает: initCreativeStore() await ЗАВЕРШАЕТСЯ до get_cabinets() — порядок уже защищает от гонки (productType готов раньше, чем список кабинетов заполняется)
- routes/+layout.svelte: то же + NavRail получает filteredCabinets (пусто — не падает, местная редакция Econometrica уже штатно работает с 0 кабинетами-советниками, loading флаг НЕ завязан на count — комментарий в +page.svelte строка 53-54 это подтверждает)
- routes/settings/+page.svelte: filterCabinetsByProduct дважды + `{#if $productType !== 'econometrica'}` — unknown проходит как "не econometrica", безопасно (существующая ветка UI для прочих продуктов)
- routes/pipeline/+layout.svelte: isEconometrica = $derived($productType === 'econometrica') — false на unknown, безопасно
- command-meta.js: getProductName и filterCabinetsByProduct — уже разобраны выше/в диффе
- tests/feedback-report-button-header.test.js: явно productType.set('econometrica') — не завязан на default
Падений не найдено: пустой список кабинетов — уже штатное состояние UI (локальная редакция Econometrica), gate по productType!=='econometrica' покрывает unknown безопасной веткой. Правок сверх creative-store.js не требуется.
ЕСЛИ МЕНЯ ОБОРВЁТ, ПРОДОЛЖАТЬ ОТСЮДА: пишу тесты (а) filterCabinetsByProduct (б) creative-store (в) decomposeInsights.

05:17:05 — п.2 тесты написаны и зелёные (10/10, 3 файла):
- src/lib/__tests__/command-meta-filter-cabinets-unknown-product.test.js (6 тестов: unknown/выдуманный → [], agency/creative-hub/media → все, econometrica → ["econometrist"])
- src/lib/__tests__/creative-store-product-type-unknown.test.js (3 теста: начальное значение 'unknown', отказ get_product_type → 'unknown', успех не переопределяется)
- src/lib/__tests__/insights-top3-driver-share-one-decimal.test.js (1 тест: топ-3 фикстура 50.14/35.34/2.06/12.46 → топ-3 сумма 97.94 → "97.9%", не "98%")
Начинаю п.3 — мутации по очереди с подтверждением в маячке.

05:17:51 — МУТАЦИЯ ВНЕСЕНА: src/lib/command-meta.js:168-171 (тело filterCabinetsByProduct откачено на старую версию `if (!allowed) return cabinets`, без UNRESTRICTED_PRODUCT_KEYS и без CPD-84 умолчания в []).

05:18:26 — МУТАЦИЯ ОТКАЧЕНА (command-meta.js): тест покраснел ожидаемо — 3 из 6 упали (unknown → все вместо [], выдуманный ключ → все вместо [], "media" вернул подмножество content-pack вместо всех — расхождение из-за отсутствия UNRESTRICTED). После отката — снова 6/6 зелёных. git diff --stat -- src/lib:
 src/lib/command-meta.js   | 26 +++++++++++++++++++++++---
 src/lib/creative-store.js | 10 +++++++---
 src/lib/insights-rules.js |  2 +-
 3 files changed, 31 insertions(+), 7 deletions(-)

05:18:39 — МУТАЦИЯ ВНЕСЕНА: src/lib/creative-store.js:16 (writable('agency') вместо 'unknown') и :72 (catch → productType.set('agency') вместо 'unknown').

05:19:33 — МУТАЦИЯ ОТКАЧЕНА (creative-store.js): тест покраснел ожидаемо (2 из 3 — начальное значение и отказ-ветка; тест успешного ответа не задет мутацией, верно). После отката — 3/3 зелёных. git diff --stat -- src/lib:
 src/lib/command-meta.js   | 26 +++++++++++++++++++++++---
 src/lib/creative-store.js | 10 +++++++---
 src/lib/insights-rules.js |  2 +-
 3 files changed, 31 insertions(+), 7 deletions(-)

05:19:40 — МУТАЦИЯ ВНЕСЕНА: src/lib/insights-rules.js:1692 (formatChannelSharePct(top3Sum) → top3Sum.toFixed(0)%, прежняя строка).

05:20:12 — МУТАЦИЯ ОТКАЧЕНА (insights-rules.js): тест покраснел ожидаемо ("98%" вместо "97.9%"). После отката — тест снова зелёный (вместе с insights-channel-share-one-decimal.test.js — 3/3, старый тест не задет). git diff --stat -- src/lib:
 src/lib/command-meta.js   | 26 +++++++++++++++++++++++---
 src/lib/creative-store.js | 10 +++++++---
 src/lib/insights-rules.js |  2 +-
 3 files changed, 31 insertions(+), 7 deletions(-)
начинаю vitest run полный, ~2-4 минуты без отметок
05:22:35 — vitest run ушёл в фон (>120с таймаут foreground), жду уведомления о завершении.

05:23:18 — vitest run завершён: Test Files 133 passed (133), Tests 1664 passed (1664), Duration 161.46s, EXIT:0. 1654 прежних + 10 новых сошлось. Начинаю npm run check, ~1-2 минуты без отметок.
