# Три зонда по зонам неуверенности — 2026-09-09

## Зонд 1. Побочные эффекты в скрытом блоке (OptimizeStep.svelte)

**Вопрос:** выключение блока `{#if false}` (было `{#if $planningMode !== 'planner'}`) в OptimizeStep.svelte изменило только видимость или ещё что-то?

**Что делал:**
- `grep -n '\{#if false\}'` — нашёл открытие блока: строка 1953.
- `awk` от строки 1953 до закрывающего `{/if}` — нашёл закрытие: строка 1986. Вывел весь диапазон 1953–1986 целиком.
- `sed -n '1953,1986p' | grep -nE '\{[a-zA-Z_$]|onclick|onchange|oninput|ontoggle|\$[a-zA-Z]'` — искал внутри диапазона любые Svelte-выражения `{...}`, обработчики событий, обращения к `$store`.
- `sed -n '1953,1986p' | grep -n '{'` — контрольный проход: показать вообще ВСЕ фигурные скобки в диапазоне, чтобы не пропустить нестандартный синтаксис.

**Факт:**
Блок (строки 1953–1986) — статический HTML: один `<div class="planning-warn">` с вложенными `<div>`, `<strong>`, `<ul><li>` и русским текстом-предупреждением про «Optimizer показывает оптимум для бюджета периода обучения…», плюс блок «🚧 В roadmap: …». Внутри диапазона фигурные скобки встречаются только в самих директивах `{#if false}` (строка 1953) и `{/if}` (строка 1986) — больше ни одной `{`. Ни выражений-подстановок, ни `$store`, ни `onclick`/`ontoggle`, ни вызовов функций.

**Положительный контроль:** тем же способом (`grep -n '{[a-zA-Z_][a-zA-Z0-9_]*(' ... | grep -v onclick|ontoggle|...`) нашёл на строке 1859 вызов функции внутри другого `{#if}`-блока: `<div class="status-value">{fmtBudget(currentTotalBudget)}</div>` (блок `{#if $planningMode === 'planner' && currentTotalBudget > 0}`, строки 1839–1844, и вложенные разметки после). Также нашёл `onclick={(e) => {...}}` c присвоениями переменных внутри блока `{#if hasGroupSplit}` (строка 2038, кнопка «Сбросить per-group», строки 2050–2066) — метод находит и обработчики событий с side-эффектами. Метод поиска подтверждённо «умеет краснеть».

**Вывод:** свойство **выполнено** — выключение блока `{#if false}` не убрало ничего, кроме статической разметки-предупреждения; никакого вызова функции, обращения к хранилищу или обработчика событий внутри не было.

---

## Зонд 2. Полнота словаря PARAM_TYPE_LABELS (SensitivityTornado.svelte)

**Вопрос:** содержит ли словарь `PARAM_TYPE_LABELS` (6 видов: `beta`, `adstock_decay`, `hill_alpha`, `hill_gamma`, `intercept`, `factor_beta`) все значения `param_type`, которые реально порождает Python-ядро для этого поля в ответе, идущем на фронтенд?

**Что делал:**
- `grep -n param_type sidecar\econometrica\**\*.py` — по всему `sidecar\econometrica` (без `dist/`).
- Прочитал файл целиком в местах конструирования кандидатов: `sidecar\econometrica\engines\sensitivity.py:205-287` (функция `get_candidate_parameters`).
- Прочитал `_parse_override_name` (537–561) и её единственных вызывателей (`_compute_roi_with_override`, `_channel_contribution` — строки 505–520, 565–600) — это единственное место, где `param_type` вычисляется динамически, а не литералом.
- Проверил публичную точку входа `compute_sensitivity_tornado` (строки 60–176) — что именно уходит в `'parameters'` поле ответа: список `evaluated`, построенный из `_evaluate_candidate(candidate=cand, ...)`, где `cand` — элемент результата `get_candidate_parameters()`.
- `sed -n '81,86p' SensitivityTornado.svelte` — вывел функцию `paramLabel` целиком.

**Факт — полный список значений `param_type`, которые ядро реально кладёт в это поле для фронтенда:**
`get_candidate_parameters()` (sensitivity.py:205–287) формирует кандидатов ровно шестью литеральными присвоениями:
- `sensitivity.py:232` → `'param_type': 'beta'`
- `sensitivity.py:241` → `'param_type': 'adstock_decay'`
- `sensitivity.py:250` → `'param_type': 'hill_alpha'`
- `sensitivity.py:259` → `'param_type': 'hill_gamma'`
- `sensitivity.py:269` → `'param_type': 'intercept'`
- `sensitivity.py:281` → `'param_type': 'factor_beta'`

`_evaluate_candidate` (609–672) просто копирует `candidate['param_type']` в возвращаемый словарь (`672: 'param_type': param_type`) без трансформации. Докстринг `get_candidate_parameters` (195–196) прямо подтверждает список: *«One of 'beta', 'adstock_decay', 'hill_alpha', 'hill_gamma', 'intercept', 'factor_beta'»*.

Есть второе место вычисления `param_type` — функция `_parse_override_name` (537–561), у которой **есть fallback** `return override_param, None` (строка 561) на случай, если строка не начинается ни с одного из 5 известных префиксов — тогда `param_type` = произвольная сырая строка. НО эта функция используется только внутри `_compute_roi_with_override`/`_channel_contribution` для служебного сопоставления имени канала (`if channel_name == col`), её результат не попадает в JSON, возвращаемый фронтенду — наружу уходит только `param_type` из `get_candidate_parameters()`. Прямого пути от `_parse_override_name` к отображаемому в Tornado-диаграмме полю нет.

**Сравнение со словарём:** все 6 значений, которые ядро реально отдаёт наружу, дословно совпадают с 6 ключами `PARAM_TYPE_LABELS` в SensitivityTornado.svelte:61-71. Расхождений нет.

**Код `paramLabel` целиком:**
```js
function paramLabel(p) {
  const key = /** @type {keyof typeof PARAM_TYPE_LABELS} */ (p.param_type ?? '');
  const root = PARAM_TYPE_LABELS[key];
  if (!root) return p.name;
  return p.channel ? `${root} · ${p.channel}` : root;
}
```
- **Отсутствующее поле** (`p.param_type === undefined`): `key = ''` (через `??`), `PARAM_TYPE_LABELS['']` → `undefined`, `root` ложно → возврат `p.name`.
- **Пустая строка** (`p.param_type === ''`): то же самое — `key = ''` → `root` не найден → возврат `p.name`.
- **Неизвестное значение** (например `'unknown_type'`): `key = 'unknown_type'`, в словаре такого ключа нет → `root` не найден → возврат `p.name`.
Во всех трёх случаях функция не падает и не показывает «сырой» `param_type` — откатывается к исходному `p.name`, как и заявлено в комментарии к словарю (строки 74–76).

**Положительный контроль:** живой поиск `param_type` в Python-коде дал 20 совпадений в одном файле, первое: `sidecar\econometrica\engines\sensitivity.py:82`. Поиск исправен (не ноль).

**Вывод:** свойство **выполнено полностью** — словарь покрывает все значения `param_type`, реально доходящие до фронтенда; fallback-путь через `_parse_override_name` теоретически может произвести произвольную строку, но она не экспонируется наружу как отображаемый `param_type`, поэтому не является практической дырой. `paramLabel` корректно и безопасно деградирует на всех трёх граничных случаях.

---

## Зонд 3. Ссылки на перенесённые пункты меню (CommandPalette.svelte)

**Вопрос:** остались ли в коде другие места, ведущие на `/workflow` и `/data-chat`, кроме перенесённых пунктов палитры команд; живы ли сами маршруты; как вычисляется `$isCreativeHub`?

**Что делал:**
- `grep -rn '/workflow|/data-chat' src\` (весь каталог `src`, рекурсивно).
- `ls` на `src\routes\workflow` и `src\routes\data-chat`.
- `grep -rn isCreativeHub` по всему `src` — нашёл определение и все точки использования.
- Прочитал `CommandPalette.svelte:30-60` целиком, чтобы увидеть структуру `baseNavItems` / `creativeHubNavItems` / `navItems`.
- Прочитал `creative-store.js` вокруг `productType`/`isCreativeHub`/`initCreativeStore`.
- Положительный контроль: тот же `grep -rn '/settings'` по `src`.

**Факт — все места, ссылающиеся на `/workflow` и `/data-chat`:**
- `src\routes\workflow\+page.svelte:65,85,93` — `goto(`/workflow/${wf.id}`)` — внутренняя навигация ВНУТРИ самого workflow-маршрута (переход к конкретному воркфлоу), не внешняя ссылка на сам раздел.
- `src\routes\workflow\[id]\+page.svelte:279,506` — `goto('/workflow')` — кнопка «Назад к списку» внутри дочернего маршрута `/workflow/[id]`, тоже внутренняя навигация фичи.
- `src\routes\data-chat\+page.svelte:7` — только импорт `classifyIntent`/`formatGreetingAnswer`, ссылок на сам маршрут `/data-chat` в файле нет.
- `src\lib\components\CommandPalette.svelte:47` — `{ id: 'nav-workflow', ..., action: () => { goto('/workflow'); onClose(); } }`
- `src\lib\components\CommandPalette.svelte:48` — `{ id: 'nav-data-chat', ..., action: () => { goto('/data-chat'); onClose(); } }`

Оба пункта (строки 47–48) находятся в массиве `creativeHubNavItems` (объявлен строками 46–51, третий пункт там же — «Бренды» → `/brands`), который подмешивается в итоговый `navItems` только условно:
```js
let navItems = $derived([
  ...baseNavItems,
  ...($isCreativeHub ? creativeHubNavItems : []),
]);
```
(CommandPalette.svelte:50-53). В самом файле (строки 41-45) есть коммент разработчика от 2026-09-09, поясняющий решение: «Workflows» и «Data Chat» — возможности Creative Hub; в Эконометрике их экраны отсылают к «Брендам» (закрытой тем же гейтом) и обещают невыпущенную функциональность («Полный анализ данных бренда — в v0.5.0»); палитра команд была единственной дверью к ним; маршруты не удалены, прямой переход по адресу работает.

Других мест (сайдбар, топ-навигация, кнопки на других экранах, `+layout.svelte`) с ссылками на `/workflow` или `/data-chat` в `src` не найдено — полнотекстовый рекурсивный grep по всему `src` дал ровно перечисленные 7 совпадений, все они либо внутренняя навигация самой фичи, либо два пункта CommandPalette.

**Существование маршрутов на диске:** оба существуют.
- `src\routes\workflow\+layout.js`, `src\routes\workflow\+page.svelte` (10982 байт), `src\routes\workflow\[id]\` (подпапка) — есть.
- `src\routes\data-chat\+page.svelte` (19053 байт) — есть.
Маршруты не удалены, только скрыт вход в них из общего меню для не-Creative-Hub продукта.

**Как вычисляется `$isCreativeHub`:**
```js
// creative-store.js:13
export const productType = writable('agency');
// creative-store.js:16
export const isCreativeHub = derived(productType, $p => $p === 'creative-hub');
```
`productType` — обычный Svelte `writable`, стартовое значение `'agency'`. Устанавливается в `initCreativeStore()` (creative-store.js:63-70):
```js
export async function initCreativeStore() {
  try {
    const type = await invoke('get_product_type'); // Tauri IPC → бэкенд
    productType.set(type);
  } catch {
    productType.set('agency');
  }
  ...
}
```
То есть `$isCreativeHub` зависит от значения, которое бэкенд Tauri (команда `get_product_type`) отдаёт при инициализации приложения; при ошибке вызова — откат на `'agency'` (то есть `isCreativeHub === false`). Других мест присвоения `productType` в `src` не найдено.

**Положительный контроль:** `grep -rn '/settings' src\` дал 8 совпадений в разных файлах (`routes/+page.svelte` ×4, `routes/cabinet/+page.svelte` ×2, `routes/pipeline/+layout.svelte` ×1, `CommandPalette.svelte` ×1) — поиск исправен, «ноль» по `/workflow`/`/data-chat` вне двух известных мест не является артефактом сломанного поиска.

**Вывод:** свойство **выполнено** — единственный внешний вход на оба перенесённых маршрута вне их собственного внутреннего кода находится в `CommandPalette.svelte:47-48`, и он уже гейтится тем же условием `$isCreativeHub`, что и «Бренды». Маршруты физически не удалены, прямой переход по адресу (или из самого workflow) работает независимо от гейта.
