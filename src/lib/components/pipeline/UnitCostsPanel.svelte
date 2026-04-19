<script>
  /**
   * UnitCostsPanel — Trust Level 2 (CPP-нормализация).
   *
   * Для медиа-каналов с не-денежными единицами (TRP/GRP/OTS/показ/охват)
   * запрашиваем стоимость 1 юнита в валюте KPI. Это позволяет считать ROI
   * корректно и сравнивать каналы в одной шкале.
   *
   * Дефолты по медиа-данным РФ 2026, согласованы с Антоном.
   * Для каналов в рублях input не показывается (unit_cost = 1.0 неявно).
   *
   * Key UX:
   * - Hydrate draft один раз при появлении каналов (потом не затираем пользовательский ввод).
   * - Кнопка «Сохранить» активна только когда есть dirty-изменения.
   * - После save инвалидируем decomposeData/optimizeData → banner «требуется пересчёт».
   * - Preview «22 100 × 250 000 = 5.5B ₽» сразу под вводом.
   * - Anomaly warning если введён CPP ≥10× отклоняется от дефолта.
   *
   * @component UnitCostsPanel
   */
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId, activeProject, unitCosts,
    decomposeData, optimizeData,
  } from '$lib/project-state.js';

  /** @type {{ columns: any[] }} */
  let { columns } = $props();

  // Дефолты CPP/CPM по медиа-данным РФ 2026 (согласованы с Антоном).
  // Порядок важен: более специфичные паттерны идут выше.
  const DEFAULTS = [
    { re: /(W\s*25[-– ]?54|25[-– ]?54).*TRP|TRP.*(W\s*25[-– ]?54|25[-– ]?54)/i, value: 250000, label: 'TV brand W 25-54 (250 000₽/TRP)' },
    { re: /(W\s*18[-– ]?44|18[-– ]?44).*TRP|TRP.*(W\s*18[-– ]?44|18[-– ]?44)/i, value: 180000, label: 'TV brand W 18-44 (180 000₽/TRP)' },
    { re: /(PERFORMANCE|ПЕРФ).*TRP|TRP.*(PERFORMANCE|ПЕРФ)/i, value: 120000, label: 'TV performance (120 000₽/TRP)' },
    { re: /TRP|РЕЙТИНГ/i, value: 250000, label: 'TV TRP (250 000₽/TRP, дефолт)' },
    { re: /GRP/i, value: 250000, label: 'GRP (≈ TRP, 250 000₽)' },
    { re: /RADIO|РАДИО/i, value: 30000, label: 'Radio GRP W 25-54 (30 000₽)' },
    { re: /(OOH|НАРУЖК)/i, value: 80, label: 'OOH CPT (80₽ за 1000 контактов)' },
    { re: /(CPM|ПОКАЗ|IMPRESSION)/i, value: 200, label: 'Digital CPM (200₽ за 1000 показов)' },
    { re: /OTS|ОХВАТ/i, value: 5, label: 'OTS (5₽ за охват, прикидка)' },
  ];
  // Синхронизируем с UNIT_HINTS в decomposer.py — важно чтобы frontend и backend
  // видели одни и те же каналы как «не-денежные».
  // NB: word boundaries (\b) не используем — в JS \b не работает с кириллицей,
  // плюс нам нужно ловить «TRPs бренд» где после TRP идёт буква.
  const UNIT_HINT = /TRP|GRP|OTS|РЕЙТИНГ|ОХВАТ|ПОКАЗ|ПРОСМОТР|КЛИК|ВИЗИТ|ПУНКТ|IMPRESSION|CLICK/i;

  /** @type {Record<string, string>} */
  const CATEGORY_HELP = {
    brand_reach: 'Brand-Reach — охватные каналы (TV/TRPs/OOH/радио), работают на долгосрочный brand-эффект.\n\nЧто это: строят знание и доверие к бренду, влияние раскрывается месяцами.\n\nКак читать: ROI интерпретируй как «вклад в базу + короткий эффект», не чистый инкремент. Сравнивай только с другими Brand-Reach каналами.',
    performance: 'Performance — каналы прямого отклика (Digital/Search/Social/контекст), работают на короткий инкремент.\n\nЧто это: закрывают спрос здесь и сейчас, эффект виден в пределах недель.\n\nКак читать: ROI — чистая отдача на рубль. Сравнивай с другими Performance каналами.',
  };

  /** @param {string} name */
  function suggestDefault(name) {
    const n = (name || '').toUpperCase();
    for (const d of DEFAULTS) {
      if (d.re.test(n)) return d;
    }
    return null;
  }

  // Формат с разделителями тысяч + EN-space (узкий пробел).
  /** @param {number | null | undefined} n */
  function fmt(n) {
    if (n == null || !Number.isFinite(n)) return '—';
    return Math.round(n).toLocaleString('ru-RU').replace(/,/g, ' ');
  }

  // Каналы, которым предположительно нужна нормализация (media-role + non-money hint).
  const nonMoneyChannels = $derived(
    (columns ?? []).filter(/** @param {any} c */ (c) =>
      c.role === 'media' && UNIT_HINT.test(String(c.name || ''))
    )
  );

  // Сумма raw-spend канала из валидационного sample — для preview money.
  // validator.py пишет сумму в col.stats.sum.
  /** @param {string} name */
  function rawSumForChannel(name) {
    const col = (columns ?? []).find(/** @param {any} c */ (c) => c.name === name);
    const v = col?.stats?.sum;
    return (typeof v === 'number' && Number.isFinite(v)) ? v : null;
  }

  /** @type {Record<string, string>} рабочая копия инпутов (строки — для удобного ввода) */
  let draft = $state({});
  /** @type {Record<string, number>} последнее сохранённое состояние — для dirty-detect */
  let savedSnapshot = $state(/** @type {Record<string, number>} */ ({}));
  let saving = $state(false);
  /** @type {string} */
  let savedMsg = $state('');

  // Hydrate draft один раз при появлении/смене набора каналов. Не затираем ввод,
  // если пользователь уже что-то вводит (сверяем по Set имён).
  /** @type {string} сигнатура текущих каналов — для определения «нужна ли регидратация» */
  let lastChannelsSig = $state('');
  $effect(() => {
    const sig = nonMoneyChannels.map(/** @param {any} c */ (c) => c.name).sort().join('|');
    if (sig === lastChannelsSig) return; // тот же набор — не трогаем draft
    lastChannelsSig = sig;

    const stored = get(unitCosts) || {};
    /** @type {Record<string, string>} */
    const next = {};
    /** @type {Record<string, number>} */
    const snap = {};
    for (const ch of nonMoneyChannels) {
      const name = ch.name;
      if (stored[name] != null) {
        next[name] = String(stored[name]);
        snap[name] = stored[name];
      } else {
        const d = suggestDefault(name);
        // Дефолт — только в поле ввода (placeholder-like). Не кладём в snapshot,
        // чтобы видеть dirty, если пользователь примет дефолт нажатием «Сохранить».
        next[name] = d ? String(d.value) : '';
      }
    }
    draft = next;
    savedSnapshot = snap;
  });

  /** Распарсить строку в положительное число. Пустая строка → null (=удалить). */
  /** @param {string} raw */
  function parseValue(raw) {
    const s = String(raw || '').replace(/\s+/g, '').replace(',', '.');
    if (s === '') return null;
    const v = parseFloat(s);
    return (Number.isFinite(v) && v > 0) ? v : null;
  }

  /** @type {Record<string, number>} текущие значения после парсинга (реактивные) */
  const parsed = $derived.by(() => {
    /** @type {Record<string, number>} */
    const out = {};
    for (const [k, v] of Object.entries(draft)) {
      const p = parseValue(v);
      if (p !== null) out[k] = p;
    }
    return out;
  });

  // Dirty-detect: draft отличается от savedSnapshot → есть что сохранять.
  const dirty = $derived.by(() => {
    const keysA = Object.keys(parsed);
    const keysB = Object.keys(savedSnapshot);
    if (keysA.length !== keysB.length) return true;
    for (const k of keysA) {
      if (Math.abs((parsed[k] ?? 0) - (savedSnapshot[k] ?? 0)) > 1e-9) return true;
    }
    return false;
  });

  /** @param {string} name */
  function anomalyHint(name) {
    const def = suggestDefault(name);
    if (!def) return null;
    const val = parsed[name];
    if (val == null) return null;
    const ratio = val / def.value;
    if (ratio >= 10) return `В ${ratio.toFixed(1)}× выше рыночного — проверь единицы`;
    if (ratio <= 0.1) return `В ${(1 / ratio).toFixed(1)}× ниже рыночного — проверь единицы`;
    return null;
  }

  async function save() {
    const pid = get(activeProjectId);
    if (!pid) return;
    saving = true;
    savedMsg = '';
    try {
      const info = /** @type {any} */ (await invoke('project_update', {
        projectId: pid,
        updates: { unit_costs: parsed },
      }));
      activeProject.set(info);
      unitCosts.set(parsed);
      savedSnapshot = { ...parsed };
      // Инвалидируем downstream результаты — старые числа больше не актуальны.
      decomposeData.set(null);
      optimizeData.set(null);
      savedMsg = '✓ Сохранено · Декомпозиция будет пересчитана автоматически';
      setTimeout(() => (savedMsg = ''), 5000);
    } catch (e) {
      savedMsg = 'Ошибка: ' + String(e);
    } finally {
      saving = false;
    }
  }

  function resetToDefaults() {
    /** @type {Record<string, string>} */
    const next = {};
    for (const ch of nonMoneyChannels) {
      const d = suggestDefault(ch.name);
      next[ch.name] = d ? String(d.value) : '';
    }
    draft = next;
  }
</script>

{#if nonMoneyChannels.length > 0}
  <section class="unit-costs">
    <div class="header">
      <div class="title">Стоимость юнита для каналов в не-денежных единицах</div>
      <div class="hint">
        Чтобы модель считала ROI корректно, укажи стоимость 1 юнита канала (CPP/CPM).
        Дефолты — по медиа-данным РФ 2026. После сохранения пересчитай декомпозицию.
      </div>
    </div>

    <div class="rows">
      {#each nonMoneyChannels as ch}
        {@const def = suggestDefault(ch.name)}
        {@const val = parsed[ch.name]}
        {@const rawSum = rawSumForChannel(ch.name)}
        {@const preview = (val != null && rawSum != null) ? rawSum * val : null}
        {@const warn = anomalyHint(ch.name)}
        <div class="row" class:row-warn={!!warn}>
          <div class="row-name">
            {ch.name}
            {#if ch.category && CATEGORY_HELP[ch.category]}
              <span
                class="cat-chip"
                class:brand={ch.category === 'brand_reach'}
                class:perf={ch.category === 'performance'}
                title={CATEGORY_HELP[ch.category]}
              >
                {ch.category === 'brand_reach' ? 'Brand-Reach' : 'Performance'}
              </span>
            {/if}
          </div>
          <div class="row-input">
            <input
              type="text"
              inputmode="decimal"
              bind:value={draft[ch.name]}
              placeholder={def ? String(def.value) : '—'}
              aria-label="Стоимость 1 юнита для {ch.name}"
            />
            <span class="unit">₽ за юнит</span>
          </div>
          <div class="row-meta">
            {#if def}
              <div class="row-default" title="Дефолт по медиа-данным РФ 2026">≈ {def.label}</div>
            {:else}
              <div class="row-default muted">Дефолт не найден — задай вручную</div>
            {/if}
            {#if preview != null}
              <div class="row-preview">
                Эквивалент: <b>{fmt(rawSum)} × {fmt(val)} ₽ = {fmt(preview)} ₽</b>
              </div>
            {/if}
            {#if warn}
              <div class="row-warn-msg">⚠ {warn}</div>
            {/if}
          </div>
        </div>
      {/each}
    </div>

    <div class="footer">
      <button class="btn-save" onclick={save} disabled={saving || !dirty}>
        {saving ? 'Сохраняю…' : (dirty ? 'Сохранить стоимости' : 'Нет изменений')}
      </button>
      <button class="btn-reset" type="button" onclick={resetToDefaults} disabled={saving} title="Вернуть рыночные дефолты">
        ↺ Дефолты
      </button>
      {#if savedMsg}
        <span class="saved-msg" class:err={savedMsg.startsWith('Ошибка')}>{savedMsg}</span>
      {/if}
    </div>
  </section>
{/if}

<style>
  .unit-costs {
    padding: 14px 16px;
    background: color-mix(in srgb, var(--accent-primary) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 18%, transparent);
    border-radius: 12px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .title {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-secondary, #94a3b8);
  }
  .hint {
    margin-top: 4px;
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.55;
  }
  .rows { display: flex; flex-direction: column; gap: 8px; }
  .row {
    display: grid;
    grid-template-columns: minmax(160px, 1.1fr) minmax(180px, auto) minmax(240px, 1.6fr);
    align-items: center;
    gap: 12px;
    padding: 8px 10px;
    background: var(--bg-surface-quiet, rgba(30,33,44,0.6));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 8px;
    transition: border-color 0.15s;
  }
  .row.row-warn { border-color: color-mix(in srgb, var(--warning, #f59e0b) 35%, transparent); }
  @media (max-width: 700px) {
    .row { grid-template-columns: 1fr; gap: 4px; }
  }
  .row-name {
    font-size: 13px;
    color: var(--text-primary, #e2e8f0);
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .cat-chip {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    padding: 1px 6px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--text-secondary) 12%, transparent);
    color: var(--text-secondary);
    cursor: help;
  }
  .cat-chip.brand {
    background: color-mix(in srgb, var(--warning, #f59e0b) 15%, transparent);
    color: var(--warning, #f59e0b);
  }
  .cat-chip.perf {
    background: color-mix(in srgb, var(--success, #10b981) 15%, transparent);
    color: var(--success, #10b981);
  }
  .row-input { display: flex; align-items: center; gap: 8px; }
  input[type="text"] {
    flex: 1;
    min-width: 0;
    padding: 6px 10px;
    background: var(--bg-card, #0b0d13);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
  input[type="text"]:focus {
    outline: none;
    border-color: var(--accent-primary, #3b82f6);
  }
  .unit { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
  .row-meta { display: flex; flex-direction: column; gap: 2px; }
  .row-default { font-size: 11px; color: var(--text-muted); line-height: 1.3; }
  .row-default.muted { opacity: 0.6; font-style: italic; }
  .row-preview {
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    line-height: 1.3;
  }
  .row-preview b { color: var(--text-primary, #e2e8f0); font-weight: 600; font-variant-numeric: tabular-nums; }
  .row-warn-msg {
    font-size: 11px;
    color: var(--warning, #f59e0b);
    font-weight: 500;
    margin-top: 2px;
  }
  .footer { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .btn-save {
    padding: 7px 18px;
    background: var(--accent-primary, #3b82f6);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
  }
  .btn-save:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-save:hover:not(:disabled) { background: var(--accent-hover, #2563eb); }
  .btn-reset {
    padding: 7px 14px;
    background: transparent;
    color: var(--text-secondary, #94a3b8);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 8px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  .btn-reset:hover:not(:disabled) {
    background: var(--hover-bg, rgba(255,255,255,0.04));
    color: var(--text-primary, #e2e8f0);
  }
  .btn-reset:disabled { opacity: 0.5; cursor: not-allowed; }
  .saved-msg { font-size: 12px; color: var(--success, #10b981); font-weight: 500; }
  .saved-msg.err { color: var(--danger, #ef4444); }
</style>
