<script>
  /**
   * CorrelationHeatmap - Canvas-based correlation matrix visualization.
   * Hover shows r-value for any cell.
   * Cells with |r| > 0.8 are highlighted in red (multicollinearity warning).
   *
   * @component CorrelationHeatmap
   */
  import { onMount } from 'svelte';
  import { TriangleAlert, Check } from 'lucide-svelte';

  /**
   * @type {{
   *   correlationMatrix?: {labels: string[], matrix: number[][]},
   *   highCorrelations?: {col1: string, col2: string, correlation: number, risk: string}[],
   * }}
   */
  let {
    correlationMatrix = { labels: [], matrix: [] },
    highCorrelations = [],
  } = $props();

  /** @type {HTMLCanvasElement | null} */
  let canvas = $state(null);

  /** @type {{col1: string, col2: string, r: number, x: number, y: number} | null} */
  let tooltip = $state(null);

  // Cell size (px)
  const CELL = 36;
  // Label area
  const LABEL_W = 100;
  const LABEL_H = 80;
  const FONT_CELL = '9px sans-serif';
  const FONT_LABEL = '10px sans-serif';

  /**
   * Map r-value [-1,1] to a CSS-like RGB color.
   * @param {number} r
   * @param {boolean} [isHigh]
   */
  function rToColor(r, isHigh = false) {
    const abs = Math.abs(r);
    if (isHigh) {
      // Red tones for |r| > 0.8
      const alpha = 0.35 + abs * 0.55;
      return `rgba(239, 68, 68, ${alpha.toFixed(2)})`;
    }
    if (r > 0) {
      const alpha = 0.08 + r * 0.55;
      return `rgba(59, 130, 246, ${alpha.toFixed(2)})`;   // blue for positive
    }
    if (r < 0) {
      const alpha = 0.08 + Math.abs(r) * 0.55;
      return `rgba(168, 85, 247, ${alpha.toFixed(2)})`;   // purple for negative
    }
    return 'rgba(30, 41, 59, 0.4)'; // diagonal / zero
  }

  function draw() {
    if (!canvas) return;
    const { labels, matrix } = correlationMatrix;
    const n = labels.length;
    if (n === 0) return;

    const W = LABEL_W + n * CELL;
    const H = LABEL_H + n * CELL;
    canvas.width  = W;
    canvas.height = H;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, W, H);

    // Background
    ctx.fillStyle = 'rgba(15, 23, 42, 0.0)';
    ctx.fillRect(0, 0, W, H);

    const highSet = new Set(
      (highCorrelations ?? []).map(h => `${h.col1}|||${h.col2}`)
    );

    /** @param {string} r1 @param {string} r2 */
    function isHigh(r1, r2) {
      return highSet.has(`${r1}|||${r2}`) || highSet.has(`${r2}|||${r1}`);
    }

    // Draw cells
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const r = matrix[i]?.[j] ?? 0;
        const x = LABEL_W + j * CELL;
        const y = LABEL_H + i * CELL;
        const high = i !== j && isHigh(labels[i], labels[j]);

        ctx.fillStyle = i === j ? 'rgba(30, 41, 59, 0.6)' : rToColor(r, high);
        ctx.fillRect(x, y, CELL - 1, CELL - 1);

        // r-value text (only show if cell is large enough)
        if (n <= 12) {
          ctx.fillStyle = Math.abs(r) > 0.5 ? 'rgba(255,255,255,0.9)' : 'rgba(148,163,184,0.7)';
          ctx.font = FONT_CELL;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          const label = i === j ? '1.0' : r.toFixed(2);
          ctx.fillText(label, x + CELL / 2 - 0.5, y + CELL / 2);
        }

        // High correlation border
        if (high) {
          ctx.strokeStyle = 'color-mix(in srgb, var(--danger) 70%, transparent)';
          ctx.lineWidth = 1.5;
          ctx.strokeRect(x + 0.75, y + 0.75, CELL - 2.5, CELL - 2.5);
        }
      }
    }

    // Row labels (right side of label area)
    ctx.fillStyle = 'rgba(148, 163, 184, 0.85)';
    ctx.font = FONT_LABEL;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i < n; i++) {
      const y = LABEL_H + i * CELL + CELL / 2;
      const label = labels[i].length > 12 ? labels[i].slice(0, 11) + '…' : labels[i];
      ctx.fillText(label, LABEL_W - 5, y);
    }

    // Column labels (rotated, above cells)
    ctx.save();
    ctx.fillStyle = 'rgba(148, 163, 184, 0.85)';
    ctx.font = FONT_LABEL;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (let j = 0; j < n; j++) {
      const x = LABEL_W + j * CELL + CELL / 2;
      const label = labels[j].length > 10 ? labels[j].slice(0, 9) + '…' : labels[j];
      ctx.save();
      ctx.translate(x, LABEL_H - 6);
      ctx.rotate(-Math.PI / 4);
      ctx.fillText(label, 0, 0);
      ctx.restore();
    }
    ctx.restore();
  }

  // ── Mouse hover → tooltip ──────────────────────────
  /** @param {MouseEvent} e */
  function onMousemove(e) {
    if (!canvas) return;
    const { labels, matrix } = correlationMatrix;
    const n = labels.length;
    if (n === 0) return;

    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const j = Math.floor((mx - LABEL_W) / CELL);
    const i = Math.floor((my - LABEL_H) / CELL);

    if (i >= 0 && i < n && j >= 0 && j < n) {
      const r = matrix[i]?.[j] ?? 0;
      tooltip = {
        col1: labels[i],
        col2: labels[j],
        r,
        x: e.offsetX + 12,
        y: e.offsetY + 12,
      };
    } else {
      tooltip = null;
    }
  }

  function onMouseleave() {
    tooltip = null;
  }

  // Redraw when data changes
  $effect(() => {
    const _ = correlationMatrix; // dependency
    // Use microtask to ensure canvas is mounted
    Promise.resolve().then(draw);
  });

  onMount(() => { draw(); });
</script>

<div class="heatmap-wrapper">

  {#if correlationMatrix.labels.length === 0}
    <p class="empty-msg">Нет данных для корреляционной матрицы</p>
  {:else}
    <div class="heatmap-header">
      <h4>Корреляционная матрица</h4>
      {#if highCorrelations.length > 0}
        <span class="high-count">
          <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> {highCorrelations.length} пар с |r| > 0.8
        </span>
      {:else}
        <span class="no-high"><Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Мультиколлинеарность не обнаружена</span>
      {/if}
    </div>

    <div class="canvas-container" style="position: relative;">
      <canvas
        bind:this={canvas}
        onmousemove={onMousemove}
        onmouseleave={onMouseleave}
        style="display:block; max-width:100%;"
      ></canvas>

      <!-- Tooltip -->
      {#if tooltip}
        <div
          class="heatmap-tooltip"
          style="left:{tooltip.x}px; top:{tooltip.y}px;"
        >
          {#if tooltip.col1 === tooltip.col2}
            <strong>{tooltip.col1}</strong>
            <span class="r-val">r = 1.000</span>
          {:else}
            <strong>{tooltip.col1}</strong>
            <span class="tooltip-sep">×</span>
            <strong>{tooltip.col2}</strong>
            <span class="r-val" class:r-high={Math.abs(tooltip.r) > 0.8}>
              r = {tooltip.r.toFixed(3)}
            </span>
            {#if Math.abs(tooltip.r) > 0.8}
              <span class="r-warn">Мультиколлинеарность</span>
            {/if}
          {/if}
        </div>
      {/if}
    </div>

    <!-- Legend -->
    <div class="legend">
      <div class="legend-item">
        <span class="legend-swatch" style="background: color-mix(in srgb, var(--accent-primary) 60%, transparent)"></span>
        <span>Положительная корреляция</span>
      </div>
      <div class="legend-item">
        <span class="legend-swatch" style="background: rgba(168,85,247,0.6)"></span>
        <span>Отрицательная корреляция</span>
      </div>
      <div class="legend-item">
        <span class="legend-swatch" style="background: color-mix(in srgb, var(--danger) 70%, transparent); border: 1px solid color-mix(in srgb, var(--danger) 80%, transparent)"></span>
        <span>|r| > 0.8 - риск мультиколлинеарности</span>
      </div>
    </div>

    <!-- High correlations list -->
    {#if highCorrelations.length > 0}
      <div class="high-list">
        {#each highCorrelations as h}
          <div class="high-item">
            <span class="high-pair">{h.col1} × {h.col2}</span>
            <span class="high-r" class:high-r-extreme={Math.abs(h.correlation) > 0.95}>
              r = {h.correlation.toFixed(3)}
            </span>
            <span class="high-risk">{h.risk}</span>
          </div>
        {/each}
      </div>
    {/if}
  {/if}

</div>

<style>
  .heatmap-wrapper {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .empty-msg {
    font-size: 12px;
    color: var(--text-muted);
    text-align: center;
    padding: 24px;
    margin: 0;
    font-style: italic;
  }

  .heatmap-header {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .heatmap-header h4 {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .high-count {
    font-size: 11px;
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
    border-radius: 20px;
    padding: 2px 9px;
  }

  .no-high {
    font-size: 11px;
    color: #86efac;
    background: color-mix(in srgb, var(--success) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--success) 20%, transparent);
    border-radius: 20px;
    padding: 2px 9px;
  }

  .canvas-container {
    overflow-x: auto;
    overflow-y: visible;
  }

  /* ── Tooltip ── */
  .heatmap-tooltip {
    position: absolute;
    pointer-events: none;
    background: var(--bg-card);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    color: var(--text-primary);
    border-radius: var(--radius-sm, 8px);
    padding: 7px 12px;
    display: flex;
    flex-direction: column;
    gap: 3px;
    z-index: 100;
    min-width: 140px;
    backdrop-filter: blur(6px);
  }

  .heatmap-tooltip strong {
    font-size: 11px;
    color: var(--text-primary, #e2e8f0);
  }

  .tooltip-sep {
    font-size: 10px;
    color: var(--text-muted);
    text-align: center;
  }

  .r-val {
    font-size: 13px;
    font-weight: 700;
    color: var(--accent-primary);
  }

  .r-val.r-high {
    color: var(--danger);
  }

  .r-warn {
    font-size: 10px;
    color: var(--danger);
    font-style: italic;
  }

  /* ── Legend ── */
  .legend {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    color: var(--text-muted);
  }

  .legend-swatch {
    width: 12px;
    height: 12px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  /* ── High correlations list ── */
  .high-list {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .high-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 5px 10px;
    background: color-mix(in srgb, var(--danger) 7%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 18%, transparent);
    border-radius: 8px;
    font-size: 11px;
    flex-wrap: wrap;
  }

  .high-pair {
    color: var(--text-primary, #e2e8f0);
    font-weight: 500;
    flex: 1;
  }

  .high-r {
    color: var(--danger);
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  .high-r-extreme {
    color: #ef4444;
  }

  .high-risk {
    color: var(--text-muted);
    font-style: italic;
  }
</style>
