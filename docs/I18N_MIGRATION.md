# i18n Migration Guide

**Foundation laid:** 2026-05-15 (sprint v2.0.1-rc2)
**Framework:** [svelte-i18n](https://github.com/kaisermann/svelte-i18n) v4
**Status:** 🟡 Infrastructure ready, existing strings NOT yet migrated
**Translation target:** v2.2.0+ (после native reviewer pass)

## Состояние

- ✅ svelte-i18n установлен (`package.json::dependencies`)
- ✅ `src/lib/i18n/index.js` — module entry с locale store + persistence
- ✅ `src/lib/i18n/locales/ru.json` — основной источник UI strings (skeletal)
- ✅ `src/lib/i18n/locales/en.json` — английский placeholder (skeletal)
- ⏳ Existing 100+ компонентов с inline русскими strings — НЕ мигрированы
- ⏳ Backend Python error messages — НЕ локализованы
- ⏳ PPTX / HTML / Methodology Certificate templates — НЕ локализованы

## Соглашения

### Ключи

Иерархические, snake_case, формат `<area>.<context>.<concept>`:

```
common.save
errors.migration_failed
pipeline.validate.confirm_roles
industry.pharma_otc
```

**Areas:**
- `common` — генерические UI слова (Save, Cancel, etc.)
- `errors` — error messages user-facing
- `pipeline` — шаги главного pipeline (Import, Validate, Model, etc.)
- `validate` — Validate шаг + substeps
- `industry` — industry enum labels (Phase 4.1)
- `model`, `decomposition`, `optimization`, `report` — pipeline шаги (TBD)

### Pluralization

Через ICU MessageFormat (svelte-i18n v4 native):

```json
{
  "channels": {
    "count": "{count, plural, one {# канал} few {# канала} other {# каналов}}"
  }
}
```

Использование:
```svelte
<p>{$_('channels.count', { values: { count: 5 } })}</p>
```

### Interpolation параметры

```json
{ "greeting": "Добро пожаловать, {name}!" }
```

```svelte
<p>{$_('greeting', { values: { name: 'Антон' } })}</p>
```

## Использование

### В Svelte компонентах

```svelte
<script>
  import { _ } from 'svelte-i18n';
</script>

<button>{$_('common.save')}</button>
<h3>{$_('validate.substep.kpi')}</h3>
```

### В сервисах / utils / event handlers

```js
import { translate } from '$lib/i18n';

function showError(code) {
  const msg = translate(`errors.${code}`);
  toast.error(msg);
}
```

### Locale switcher

```svelte
<script>
  import { locale, supportedLocales } from '$lib/i18n';
</script>

<select bind:value={$locale}>
  {#each supportedLocales as lang}
    <option value={lang}>{lang.toUpperCase()}</option>
  {/each}
</select>
```

## Migration approach

### Этап 1 (текущий, sprint v2.0.1-rc2)
Инфраструктура только. Новые компоненты с этого момента ОБЯЗАНЫ использовать
`$_('key')` для всех user-facing strings. Inline russian strings в новом коде —
запрещены (review gate).

### Этап 2 (v2.2.0, ~30-40h)
Extract UI strings из existing 100+ компонентов к ru.json:
1. Grep inline russian strings — `Grep "[А-Яа-я]" --type svelte`
2. Per-file: replace inline → `$_('key')`, add ключ к ru.json
3. Translate ru.json → en.json (LLM draft → native reviewer)

**Приоритет компонентов:**
1. `pipeline/*.svelte` (60% user-visible)
2. `routes/*.svelte` (top-level pages)
3. `components/*.svelte` (shared)

### Этап 3 (v2.3.0)
- Backend Python error messages (Pydantic + log_event)
- PPTX/HTML export templates
- Methodology Certificate PDF

## Тесты

Vitest setup в `src/tests/setup.js` НЕ инициализирует i18n — компоненты,
которые используют `$_('key')` в тестах должны импортировать `addMessages` +
`init` напрямую ИЛИ использовать fallback (если key не найден → key returned
verbatim, что выглядит как technical string but не падает).

Для критичных компонентов (например, MigrationCompletedToast) — добавить
тест с initialized i18n в test setup. См. example: TBD when first component migrated.

## Соображения

### Что НЕ переводим (мaintain в RU only)

- Commit messages
- Engineering docs (CHANGELOG, design docs, ADRs) — для разработчиков
- Internal log events (structured logs к sidecar.json.log) — для IT-admin debugging
- ENGINEERING_INVARIANTS.md
- Sprint trackers

### Что переводим (EN target)

- ВСЕ user-facing UI labels / buttons / tooltips
- Customer-facing error messages
- Customer-facing email / notification templates (when exist)
- PPTX/HTML export labels (когда дойдёт до этого этапа)

### Riskiest translations

**Pharma-specific terminology**, требует native reviewer:
- adstock / saturation / decay rate
- confounding / endogeneity / posterior
- MQS (model quality score)
- CPP (cost per point), CPM, CPC, CPV, CPA
- TRP, GRP (telerating points)

**Methodology Certificate** — самое чувствительное, customer верит content,
ошибка в терминологии = liability.
