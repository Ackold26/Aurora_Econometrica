<script>
  /**
   * Inline SVG preview of adstock decay curve.
   * Zero dependencies - pure SVG math.
   *
   * @component AdstockPreview
   */
  /** @type {{ type: 'geometric' | 'weibull' }} */
  let { type = 'geometric' } = $props();

  const W = 200;
  const H = 60;
  const PAD = 6;
  const STEPS = 12;

  /** Compute Y values in [0,1] for the given adstock type */
  const yValues = $derived.by(() => {
    const pts = [];
    if (type === 'geometric') {
      // Geometric decay: y[t] = 0.72^t
      for (let t = 0; t < STEPS; t++) pts.push(Math.pow(0.72, t));
    } else {
      // Weibull PDF shape: k=2, lambda=3
      const k = 2, lam = 3;
      for (let t = 0; t < STEPS; t++) {
        const x = t === 0 ? 0.01 : t;
        pts.push((k / lam) * Math.pow(x / lam, k - 1) * Math.exp(-Math.pow(x / lam, k)));
      }
    }
    // Normalize to [0,1]
    const mx = Math.max(...pts);
    return pts.map(v => v / mx);
  });

  /** Convert values to SVG polyline points */
  const linePoints = $derived.by(() => {
    const stepX = (W - PAD * 2) / (STEPS - 1);
    return yValues.map((v, i) => {
      const x = PAD + i * stepX;
      const y = PAD + (1 - v) * (H - PAD * 2);
      return `${x},${y}`;
    }).join(' ');
  });

  /** Fill polygon (line + bottom corners) */
  const fillPoints = $derived.by(() => {
    const stepX = (W - PAD * 2) / (STEPS - 1);
    const pts = yValues.map((v, i) => {
      const x = PAD + i * stepX;
      const y = PAD + (1 - v) * (H - PAD * 2);
      return `${x},${y}`;
    });
    // Close fill shape along bottom
    const lastX = PAD + (STEPS - 1) * stepX;
    pts.push(`${lastX},${H - PAD}`);
    pts.push(`${PAD},${H - PAD}`);
    return pts.join(' ');
  });
</script>

<svg
  width={W}
  height={H}
  viewBox="0 0 {W} {H}"
  class="adstock-preview"
  aria-label="Adstock curve: {type}"
>
  <!-- Gradient fill -->
  <defs>
    <linearGradient id="adstock-fill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--accent-primary, #3b82f6)" stop-opacity="0.25" />
      <stop offset="100%" stop-color="var(--accent-primary, #3b82f6)" stop-opacity="0.02" />
    </linearGradient>
  </defs>

  <!-- Fill area -->
  <polygon points={fillPoints} fill="url(#adstock-fill)" />

  <!-- Line -->
  <polyline
    points={linePoints}
    fill="none"
    stroke="var(--accent-primary, #3b82f6)"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
  />
</svg>

<style>
  .adstock-preview {
    display: block;
    border-radius: 4px;
    background: rgba(0, 0, 0, 0.15);
  }
</style>
