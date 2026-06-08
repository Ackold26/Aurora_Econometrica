<script>
  /**
   * Side-by-side сравнение двух проектов. Overlay модалка, не роут.
   * Не меняет activeProject - чисто read-only view.
   * Esc / backdrop click → закрыть.
   *
   * @component ModelComparisonView
   */
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import { mqsView } from '$lib/metric-views.js';

  /** @type {{ primaryId: string, secondaryId: string, onClose: () => void }} */
  let { primaryId, secondaryId, onClose } = $props();

  /** @type {any} */
  let payload = $state(null);
  let loading = $state(true);
  /** @type {string | null} */
  let errorMsg = $state(null);
  /** @type {HTMLDialogElement | undefined} */
  let dialogEl = $state();

  onMount(() => {
    loadPayload();
    // Открываем modal после mount - dialogEl уже bound
    queueMicrotask(() => dialogEl?.showModal());
  });

  /** @param {Event} e */
  function handleCancel(e) {
    e.preventDefault(); // Escape → onClose, не default close
    onClose();
  }

  /** @param {MouseEvent} e */
  function onBackdropClick(e) {
    // Клик по самому dialog (а не по children) = backdrop click
    if (e.target === dialogEl) onClose();
  }

  async function loadPayload() {
    loading = true;
    errorMsg = null;
    try {
      payload = await invoke('project_load_comparison', { primaryId, secondaryId });
    } catch (e) {
      errorMsg = String(e);
    }
    loading = false;
  }

  // ── Snapshots ──────────────────────────────────────────────────────────
  const A = $derived(payload?.primary ?? null);
  const B = $derived(payload?.secondary ?? null);

  // Scenarios overflow detection (backend truncates до 50 newest)
  const scenariosOverflow = $derived.by(() => {
    const aTotal = A?.scenarios_total ?? A?.scenarios?.length ?? 0;
    const bTotal = B?.scenarios_total ?? B?.scenarios?.length ?? 0;
    const aShown = A?.scenarios?.length ?? 0;
    const bShown = B?.scenarios?.length ?? 0;
    if (aTotal > aShown || bTotal > bShown) {
      return { aTotal, bTotal, aShown, bShown };
    }
    return null;
  });

  /** @param {any} snap */
  function diagnostics(snap) {
    return snap?.modelDiagnostics?.diagnostics ?? {};
  }

  /** @param {any} snap @param {string} key */
  function metric(snap, key) {
    const d = diagnostics(snap);
    return d?.metrics?.[key] ?? d?.[key] ?? null;
  }

  // INV-50 анти-рецидив: MQS через единый пост-train селектор mqsView.
  /** @param {any} snap */
  const mqsScore = (snap) => mqsView(diagnostics(snap))?.score ?? null;
  /** @param {any} snap */
  const mqsLabel = (snap) => mqsView(diagnostics(snap))?.tierLabel ?? '-';

  /** @param {number | null} a @param {number | null} b @param {'higher' | 'lower'} better */
  function highlight(a, b, better) {
    if (a == null || b == null) return { a: false, b: false };
    if (a === b) return { a: false, b: false };
    const aWins = better === 'higher' ? a > b : a < b;
    return { a: aWins, b: !aWins };
  }

  /** @param {number | null | undefined} v @param {number} [dec] */
  function fmt(v, dec = 2) {
    if (v == null || !Number.isFinite(Number(v))) return '-';
    const n = Number(v);
    return n.toLocaleString('ru-RU', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }

  /** @param {number | null | undefined} v */
  function fmtInt(v) {
    if (v == null || !Number.isFinite(Number(v))) return '-';
    return Math.round(Number(v)).toLocaleString('ru-RU');
  }

  /** @param {number | null | undefined} v */
  function fmtPct(v) {
    if (v == null || !Number.isFinite(Number(v))) return '-';
    return `${Number(v).toFixed(1)}%`;
  }

  // ── KPI cards data ─────────────────────────────────────────────────────
  const kpiSpec = $derived([
    {
      label: 'MQS',
      a: mqsScore(A), b: mqsScore(B),
      subA: mqsLabel(A), subB: mqsLabel(B),
      better: /** @type {'higher'} */ ('higher'),
      format: (/** @type {number} */ v) => fmt(v, 0),
    },
    {
      label: 'R²',
      a: metric(A, 'r_squared'), b: metric(B, 'r_squared'),
      subA: 'Точность подгонки', subB: 'Точность подгонки',
      better: /** @type {'higher'} */ ('higher'),
      format: (/** @type {number} */ v) => fmt(v, 3),
    },
    {
      label: 'MAPE',
      a: metric(A, 'mape_pct'), b: metric(B, 'mape_pct'),
      subA: 'Средняя ошибка', subB: 'Средняя ошибка',
      better: /** @type {'lower'} */ ('lower'),
      format: (/** @type {number} */ v) => `${fmt(v, 1)}%`,
    },
    {
      label: 'R-hat',
      a: metric(A, 'r_hat_max'), b: metric(B, 'r_hat_max'),
      subA: 'Сходимость MCMC', subB: 'Сходимость MCMC',
      better: /** @type {'lower'} */ ('lower'),
      format: (/** @type {number} */ v) => fmt(v, 3),
    },
  ]);

  // ── Channels unified ───────────────────────────────────────────────────
  /** @param {any} snap */
  function channels(snap) {
    return snap?.decomposition?.channels ?? [];
  }

  const allChannelNames = $derived.by(() => {
    /** @type {Set<string>} */
    const s = new Set();
    channels(A).forEach((/** @type {any} */ c) => c?.name && s.add(c.name));
    channels(B).forEach((/** @type {any} */ c) => c?.name && s.add(c.name));
    return Array.from(s);
  });

  /** @param {any} snap @param {string} name */
  function findChannel(snap, name) {
    return channels(snap).find((/** @type {any} */ c) => c?.name === name) ?? null;
  }

  const channelRows = $derived(
    allChannelNames.map((name) => {
      const ca = findChannel(A, name);
      const cb = findChannel(B, name);
      const roiA = ca?.roi ?? null;
      const roiB = cb?.roi ?? null;
      const delta = (roiA != null && roiB != null) ? roiA - roiB : null;
      return {
        name,
        spendA: ca?.spend ?? null,
        spendB: cb?.spend ?? null,
        roiA, roiB,
        contribA: ca?.contribution ?? null,
        contribB: cb?.contribution ?? null,
        delta,
        highlight: highlight(roiA, roiB, 'higher'),
      };
    })
  );

  // ── Charts ─────────────────────────────────────────────────────────────
  /** @param {any} snap @param {string} color */
  function waterfallOption(snap, color) {
    const wf = snap?.decomposition?.waterfall;
    if (!wf) return null;
    const labels = Array.isArray(wf) ? wf.map((/** @type {any} */ w) => w?.category ?? '') : (wf?.labels ?? []);
    const values = Array.isArray(wf) ? wf.map((/** @type {any} */ w) => Number(w?.value ?? 0)) : (wf?.values ?? []);
    if (!labels.length) return null;
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: labels, axisLabel: { rotate: 30 } },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: values, itemStyle: { color } }],
    };
  }

  const waterfallA = $derived(waterfallOption(A, '#3b82f6'));
  const waterfallB = $derived(waterfallOption(B, '#f59e0b'));

  const roiBarsOption = $derived.by(() => {
    const names = allChannelNames;
    if (names.length === 0) return null;
    const roiA = names.map((n) => {
      const c = findChannel(A, n);
      return c?.roi != null ? Number(c.roi) : 0;
    });
    const roiB = names.map((n) => {
      const c = findChannel(B, n);
      return c?.roi != null ? Number(c.roi) : 0;
    });
    const nameA = A?.info?.name || 'Проект A';
    const nameB = B?.info?.name || 'Проект B';
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: [nameA, nameB], top: 0 },
      grid: { left: '3%', right: '4%', top: 32, bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: names, axisLabel: { rotate: 30 } },
      yAxis: { type: 'value', name: 'ROI (×)' },
      series: [
        { name: nameA, type: 'bar', data: roiA, itemStyle: { color: '#3b82f6' } },
        { name: nameB, type: 'bar', data: roiB, itemStyle: { color: '#f59e0b' } },
      ],
    };
  });

  // ── Optimize comparison ────────────────────────────────────────────────
  /** @param {any} snap */
  const optLift = (snap) => snap?.optimization?.expected_lift_pct ?? null;
  /** @param {any} snap */
  // 5c followup (2026-05-24): money-axis budget, matches XLSX/markdown/ReportStep.
  // `total_budget` = native mixed-units sum (TRPs+₽ garbage). Use money axis chain.
  const optBudget = (snap) =>
    snap?.optimization?.total_current_money
      ?? snap?.optimization?.total_budget_money
      ?? snap?.optimization?.total_budget
      ?? null;

  const hasOptimize = $derived(
    (A?.optimization?.channels?.length ?? 0) > 0 || (B?.optimization?.channels?.length ?? 0) > 0
  );

  /** @param {any} snap @param {string} name */
  function optChannel(snap, name) {
    const arr = snap?.optimization?.channels ?? [];
    return arr.find((/** @type {any} */ c) => c?.name === name) ?? null;
  }

  const optRows = $derived(
    allChannelNames
      .map((name) => {
        const ca = optChannel(A, name);
        const cb = optChannel(B, name);
        return {
          name,
          optA: ca?.optimal_spend ?? null,
          optB: cb?.optimal_spend ?? null,
          curA: ca?.current_spend ?? null,
          curB: cb?.current_spend ?? null,
        };
      })
      .filter((r) => r.curA != null || r.curB != null || r.optA != null || r.optB != null)
  );

  // ── Derived insights (text) ────────────────────────────────────────────
  const insights = $derived.by(() => {
    if (!A || !B) return [];
    /** @type {string[]} */
    const lines = [];
    const chA = channels(A), chB = channels(B);
    if (chA.length && chB.length) {
      const topA = [...chA].sort((x, y) => (y?.roi ?? 0) - (x?.roi ?? 0))[0];
      const topB = [...chB].sort((x, y) => (y?.roi ?? 0) - (x?.roi ?? 0))[0];
      if (topA && topB) {
        lines.push(
          `Топ-драйвер у **${A.info.name}** - ${topA.name} (ROI ${fmt(topA.roi)}×), у **${B.info.name}** - ${topB.name} (ROI ${fmt(topB.roi)}×).`
        );
      }
    }
    const baseA = A?.decomposition?.baseline_pct ?? A?.decomposition?.base_pct;
    const baseB = B?.decomposition?.baseline_pct ?? B?.decomposition?.base_pct;
    if (baseA != null && baseB != null) {
      lines.push(
        `Органическая база: **${A.info.name}** - ${fmtPct(baseA)}, **${B.info.name}** - ${fmtPct(baseB)}. ${baseA > baseB ? 'У A сильнее органика' : baseB > baseA ? 'У B сильнее органика' : 'Органика сопоставима'}.`
      );
    }
    const liftA = optLift(A), liftB = optLift(B);
    if (liftA != null && liftB != null) {
      lines.push(
        `Потенциал оптимизации: **${A.info.name}** - +${fmtPct(liftA).replace('%', '')}%, **${B.info.name}** - +${fmtPct(liftB).replace('%', '')}%.`
      );
    }
    const mqsA = mqsScore(A), mqsB = mqsScore(B);
    if (mqsA != null && mqsB != null && Math.abs(mqsA - mqsB) > 10) {
      lines.push(
        `⚠ Разница в MQS - ${fmt(Math.abs(mqsA - mqsB), 0)} баллов. Модели разного качества, сравнение ROI стоит смотреть осторожно.`
      );
    }
    return lines;
  });

  /** HTML escape для защиты от XSS при подстановке user-sourced значений
   *  (имена проектов / каналов из xlsx могут содержать `<`, `>`, `<script>` etc).
   *  Правило aurora-fix V40 - все `{@html}` с user-controlled строками должны
   *  пройти escape. */
  /** @param {string} s */
  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /** @param {string} md - escape HTML + simple **bold** replace */
  function renderMd(md) {
    return escapeHtml(md).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  }
</script>

<dialog
  bind:this={dialogEl}
  class="cmp-dialog"
  aria-label="Сравнение моделей"
  oncancel={handleCancel}
  onclick={onBackdropClick}
>
  <div class="cmp-shell">
    <header class="cmp-header">
      <div class="cmp-title">
        <span class="cmp-ico">⚖</span>
        <span class="cmp-names">
          <span class="n-a">{A?.info?.name ?? 'Проект A'}</span>
          <span class="vs">vs</span>
          <span class="n-b">{B?.info?.name ?? 'Проект B'}</span>
        </span>
      </div>
      <button class="cmp-close" onclick={onClose} aria-label="Закрыть">✕</button>
    </header>

    <div class="cmp-body">
      {#if loading}
        <div class="cmp-state">Загружаю снимки проектов…</div>
      {:else if errorMsg}
        <div class="cmp-state cmp-err">Ошибка: {errorMsg}</div>
      {:else if A && B}
        {#if scenariosOverflow}
          <div class="cmp-banner">
            ℹ Показаны последние 50 сценариев (A: {scenariosOverflow.aShown} из {scenariosOverflow.aTotal}, B: {scenariosOverflow.bShown} из {scenariosOverflow.bTotal})
          </div>
        {/if}
        <!-- ── KPI cards ──────────────────────────────────────────── -->
        <section class="block">
          <h2>📊 Ключевые метрики</h2>
          <div class="kpi-grid">
            {#each kpiSpec as k}
              {@const hl = highlight(k.a, k.b, k.better)}
              <div class="kpi-pair">
                <div class="kpi-card" class:win={hl.a}>
                  <div class="kpi-label">{k.label}</div>
                  <div class="kpi-val">{k.a != null ? k.format(k.a) : '-'}</div>
                  <div class="kpi-sub">{k.subA}</div>
                </div>
                <div class="kpi-card" class:win={hl.b}>
                  <div class="kpi-label">{k.label}</div>
                  <div class="kpi-val">{k.b != null ? k.format(k.b) : '-'}</div>
                  <div class="kpi-sub">{k.subB}</div>
                </div>
              </div>
            {/each}
          </div>
          <p class="legend">
            <span class="dot dot-a"></span> {A.info.name}
            <span class="dot dot-b"></span> {B.info.name}
            <span class="note">· зелёная рамка - лучшее значение</span>
          </p>
        </section>

        <!-- ── Channels table (inline для win-highlight на ROI) ────── -->
        {#if channelRows.length > 0}
          <section class="block">
            <h2>🎯 Каналы: расходы и ROI</h2>
            <div class="tbl-wrap">
              <table class="cmp-table">
                <thead>
                  <tr>
                    <th>Канал</th>
                    <th class="num">Расход A</th>
                    <th class="num">Расход B</th>
                    <th class="num">ROI A</th>
                    <th class="num">ROI B</th>
                    <th class="num">Δ ROI</th>
                  </tr>
                </thead>
                <tbody>
                  {#each channelRows as r}
                    <tr>
                      <td>{r.name}</td>
                      <td class="num">{fmtInt(r.spendA)}</td>
                      <td class="num">{fmtInt(r.spendB)}</td>
                      <td class="num" class:win={r.highlight.a}>{r.roiA != null ? `${fmt(r.roiA)}×` : '-'}</td>
                      <td class="num" class:win={r.highlight.b}>{r.roiB != null ? `${fmt(r.roiB)}×` : '-'}</td>
                      <td class="num" class:pos={r.delta != null && r.delta > 0} class:neg={r.delta != null && r.delta < 0}>
                        {r.delta != null ? `${r.delta > 0 ? '+' : ''}${fmt(r.delta)}` : '-'}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </section>
        {/if}

        <!-- ── Waterfall side-by-side ─────────────────────────────── -->
        {#if waterfallA || waterfallB}
          <section class="block">
            <h2>💧 Декомпозиция: каскад</h2>
            <div class="charts-two">
              <div class="chart-card">
                <div class="chart-ttl">{A.info.name}</div>
                {#if waterfallA}
                  <EChartBase option={waterfallA} height="320px" step={-1} />
                {:else}
                  <div class="chart-empty">Нет данных декомпозиции</div>
                {/if}
              </div>
              <div class="chart-card">
                <div class="chart-ttl">{B.info.name}</div>
                {#if waterfallB}
                  <EChartBase option={waterfallB} height="320px" step={-1} />
                {:else}
                  <div class="chart-empty">Нет данных декомпозиции</div>
                {/if}
              </div>
            </div>
          </section>
        {/if}

        <!-- ── ROI bars unified ───────────────────────────────────── -->
        {#if roiBarsOption}
          <section class="block">
            <h2>📈 ROI по каналам (A vs B)</h2>
            <EChartBase option={roiBarsOption} height="340px" step={-1} />
          </section>
        {/if}

        <!-- ── Optimize compare ───────────────────────────────────── -->
        {#if hasOptimize}
          <section class="block">
            <h2>💰 Оптимизация бюджета</h2>
            <div class="kpi-grid">
              <div class="kpi-pair">
                <div class="kpi-card">
                  <div class="kpi-label">Ожидаемый лифт</div>
                  <div class="kpi-val">{optLift(A) != null ? `+${fmtPct(optLift(A)).replace('%','')}%` : '-'}</div>
                  <div class="kpi-sub">{A.info.name}</div>
                </div>
                <div class="kpi-card">
                  <div class="kpi-label">Ожидаемый лифт</div>
                  <div class="kpi-val">{optLift(B) != null ? `+${fmtPct(optLift(B)).replace('%','')}%` : '-'}</div>
                  <div class="kpi-sub">{B.info.name}</div>
                </div>
              </div>
              <div class="kpi-pair">
                <div class="kpi-card">
                  <div class="kpi-label">Общий бюджет</div>
                  <div class="kpi-val">{fmtInt(optBudget(A))}</div>
                  <div class="kpi-sub">{A.info.name}</div>
                </div>
                <div class="kpi-card">
                  <div class="kpi-label">Общий бюджет</div>
                  <div class="kpi-val">{fmtInt(optBudget(B))}</div>
                  <div class="kpi-sub">{B.info.name}</div>
                </div>
              </div>
            </div>
            {#if optRows.length > 0}
              <div style="margin-top:12px;">
                <DataTable
                  mode="scenario"
                  headers={['Канал', 'Текущ. A', 'Оптим. A', 'Текущ. B', 'Оптим. B']}
                  rows={optRows.map((r) => [
                    r.name,
                    r.curA != null ? Math.round(Number(r.curA)) : '-',
                    r.optA != null ? Math.round(Number(r.optA)) : '-',
                    r.curB != null ? Math.round(Number(r.curB)) : '-',
                    r.optB != null ? Math.round(Number(r.optB)) : '-',
                  ])}
                />
              </div>
            {/if}
          </section>
        {/if}

        <!-- ── Derived insights ───────────────────────────────────── -->
        {#if insights.length > 0}
          <section class="block block-insights">
            <h2>💡 Выводы</h2>
            <ul>
              {#each insights as line}
                <li>{@html renderMd(line)}</li>
              {/each}
            </ul>
          </section>
        {/if}
      {/if}
    </div>
  </div>
</dialog>

<style>
  dialog.cmp-dialog {
    /* Vertical + horizontal centering native margin:auto.
       max-height/width ограничивают size; browser центрирует. */
    margin: auto;
    padding: 0;
    border: none;
    background: transparent;
    max-width: 1280px;
    width: calc(100vw - 40px);
    max-height: calc(100vh - 40px);
    color: var(--text-primary);
  }
  dialog.cmp-dialog:not([open]) { display: none; }
  dialog.cmp-dialog[open] {
    animation: cmp-rise 0.25s ease;
  }
  dialog.cmp-dialog::backdrop {
    background: var(--overlay-bg, rgba(0, 0, 0, 0.7));
    backdrop-filter: blur(6px);
    animation: cmp-fade 0.2s ease;
  }
  @keyframes cmp-fade { from { opacity: 0; } }
  @keyframes cmp-rise { from { transform: translateY(16px); opacity: 0; } }

  .cmp-shell {
    background: var(--bg-primary, #0b0f16);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: 14px;
    width: 100%;
    max-height: calc(100vh - 40px);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6);
  }
  .cmp-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 24px;
    border-bottom: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    position: sticky;
    top: 0;
    background: var(--bg-primary, #0b0f16);
    border-radius: 14px 14px 0 0;
    z-index: 2;
  }
  .cmp-title {
    display: flex;
    align-items: center;
    gap: 14px;
    font-size: 17px;
    font-weight: 700;
    color: var(--text-primary);
  }
  .cmp-ico { font-size: 20px; }
  .cmp-names { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .n-a { color: #3b82f6; }
  .n-b { color: #f59e0b; }
  .vs { color: var(--text-muted, #94a3b8); font-weight: 400; font-size: 14px; }
  .cmp-close {
    background: transparent;
    border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
    border-radius: 8px;
    color: var(--text-primary);
    width: 34px;
    height: 34px;
    font-size: 16px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .cmp-close:hover {
    background: var(--danger, #ef4444);
    border-color: var(--danger, #ef4444);
    color: #fff;
  }

  .cmp-body {
    padding: 20px 24px 32px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .cmp-state {
    padding: 48px 12px;
    text-align: center;
    color: var(--text-secondary, #94a3b8);
    font-size: 14px;
  }
  .cmp-err { color: var(--danger, #ef4444); }

  .cmp-banner {
    padding: 10px 14px;
    border-radius: 8px;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary, #3b82f6) 25%, transparent);
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
  }

  .block {
    background: var(--bg-secondary, #111827);
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    border-radius: 12px;
    padding: 18px 20px;
  }
  .block h2 {
    font-size: 15px;
    margin: 0 0 14px 0;
    font-weight: 600;
    color: var(--text-primary);
  }

  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
  }
  .kpi-pair {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .kpi-card {
    background: var(--bg-tertiary, #1e293b);
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    border-radius: 10px;
    padding: 12px 14px;
    transition: border-color 0.15s;
  }
  .kpi-card.win {
    border-color: #22c55e;
    box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.2);
  }
  .kpi-label {
    font-size: 10px;
    color: var(--text-muted, #94a3b8);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
  }
  .kpi-val {
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.1;
  }
  .kpi-sub {
    font-size: 11px;
    color: var(--text-muted, #94a3b8);
    margin-top: 4px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .legend {
    font-size: 11px;
    color: var(--text-muted, #94a3b8);
    margin: 12px 0 0 0;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin: 0 4px 0 10px;
  }
  .dot-a { background: #3b82f6; }
  .dot-b { background: #f59e0b; }
  .note { font-style: italic; opacity: 0.7; margin-left: 6px; }

  .tbl-wrap { overflow-x: auto; }
  .cmp-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .cmp-table th, .cmp-table td {
    padding: 8px 10px;
    text-align: left;
    border-bottom: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
  }
  .cmp-table th {
    color: var(--text-muted, #94a3b8);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .cmp-table td.win { color: #22c55e; font-weight: 600; }
  .cmp-table td.pos { color: #22c55e; }
  .cmp-table td.neg { color: #ef4444; }

  .charts-two {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  @media (max-width: 900px) {
    .charts-two { grid-template-columns: 1fr; }
  }
  .chart-card {
    background: var(--bg-tertiary, #1e293b);
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    border-radius: 10px;
    padding: 12px;
  }
  .chart-ttl {
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    font-weight: 600;
    margin-bottom: 6px;
  }
  .chart-empty {
    height: 320px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted, #94a3b8);
    font-size: 12px;
  }

  .block-insights ul {
    margin: 0;
    padding-left: 20px;
    color: var(--text-primary);
    font-size: 13px;
    line-height: 1.7;
  }
  .block-insights li { margin-bottom: 4px; }
  .block-insights :global(strong) {
    color: var(--accent-primary, #3b82f6);
    font-weight: 600;
  }

  /* v2.1.0 п.5.6: instant dialog appearance */
  @media (prefers-reduced-motion: reduce) {
    dialog.cmp-dialog[open] {
      animation: none;
      opacity: 1;
      transform: none;
    }
    dialog.cmp-dialog::backdrop {
      animation: none;
      opacity: 1;
    }
  }
</style>
