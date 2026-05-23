<script>
  /**
   * CorridorSlider - v1.3.0 reusable slider with safe-corridor visualization.
   *
   * Per ADR-014: показывает зелёные/жёлтые/красные зоны на bar slider.
   * 🟢 [lo, hi] - safe (модель валидна).
   * 🟡 ±10% от границ - extrapolation warning.
   * 🔴 > 10% за пределами - заблокировано (кнопка disable).
   *
   * @component CorridorSlider
   */

  const {
    value = 0,            // current value (binded)
    min = 0,              // absolute slider min
    max = 100,            // absolute slider max
    corridorLo,           // safe corridor lower bound
    corridorHi,           // safe corridor upper bound
    yellowZonePct = 0.10, // warn zone width (10% per side default)
    step = 1,
    label = '',
    unit = '',
    formatFn,             // (v) => string
    onChange,             // (v) => void
    onZoneChange,         // (zone: 'green' | 'yellow' | 'red') => void
  } = $props();

  /** @param {number} v @returns {'green' | 'yellow' | 'red'} */
  function classifyZone(v) {
    if (v >= corridorLo && v <= corridorHi) return 'green';
    const lo10 = corridorLo - corridorLo * yellowZonePct;
    const hi10 = corridorHi + corridorHi * yellowZonePct;
    if (v >= lo10 && v <= hi10) return 'yellow';
    return 'red';
  }

  let currentZone = $derived(classifyZone(value));
  let displayValue = $derived(formatFn ? formatFn(value) : `${value.toLocaleString('ru-RU')}${unit ? ' ' + unit : ''}`);

  // Compute pixel positions for zones (CSS gradient).
  const greenStart = $derived((Math.max(corridorLo, min) - min) / (max - min) * 100);
  const greenEnd = $derived((Math.min(corridorHi, max) - min) / (max - min) * 100);
  const yellowLoStart = $derived(Math.max(0, (corridorLo - corridorLo * yellowZonePct - min) / (max - min) * 100));
  const yellowHiEnd = $derived(Math.min(100, (corridorHi + corridorHi * yellowZonePct - min) / (max - min) * 100));

  $effect(() => {
    onZoneChange?.(currentZone);
  });

  /** @param {Event} e */
  function handleInput(e) {
    const target = /** @type {HTMLInputElement} */ (e.target);
    const newVal = parseFloat(target.value);
    onChange?.(newVal);
  }
</script>

<div class="corridor-slider">
  {#if label}
    <div class="label-row">
      <label for="slider">{label}</label>
      <span class="value-display zone-{currentZone}">{displayValue}</span>
    </div>
  {/if}

  <div class="track-container">
    <!-- Track background с zones -->
    <div
      class="zones"
      style="
        --green-start: {greenStart}%;
        --green-end: {greenEnd}%;
        --yellow-lo-start: {yellowLoStart}%;
        --yellow-hi-end: {yellowHiEnd}%;
      "
    ></div>
    <!-- Native range input на top -->
    <input
      id="slider"
      type="range"
      {min}
      {max}
      {step}
      {value}
      oninput={handleInput}
      class="slider"
    />
  </div>

  <div class="zone-legend">
    <span class="legend-item">
      <span class="dot zone-green"></span>
      Безопасный коридор: {formatFn ? formatFn(corridorLo) : corridorLo.toLocaleString('ru-RU')} - {formatFn ? formatFn(corridorHi) : corridorHi.toLocaleString('ru-RU')}{unit ? ' ' + unit : ''}
    </span>
    <span class="legend-item">
      <span class="dot zone-yellow"></span>
      Расширенный (±{(yellowZonePct * 100).toFixed(0)}%)
    </span>
    <span class="legend-item">
      <span class="dot zone-red"></span>
      Экстраполяция - рекомендации не валидны
    </span>
  </div>
</div>

<style>
  .corridor-slider {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
  }
  .label-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 13px;
  }
  .label-row label { color: var(--text-secondary); font-weight: 500; }
  .value-display {
    font-size: 16px;
    font-weight: 700;
    color: var(--text-primary);
    transition: color 0.2s;
  }
  .value-display.zone-green { color: var(--success, #4ade80); }
  .value-display.zone-yellow { color: var(--warning, #fbbf24); }
  .value-display.zone-red { color: var(--danger, #f87171); }

  .track-container {
    position: relative;
    height: 32px;
    display: flex;
    align-items: center;
  }
  .zones {
    position: absolute;
    inset: 12px 0;
    border-radius: 999px;
    background: linear-gradient(
      to right,
      color-mix(in srgb, var(--danger, #f87171) 30%, transparent) 0%,
      color-mix(in srgb, var(--danger, #f87171) 30%, transparent) calc(var(--yellow-lo-start, 0%) - 0.5%),
      color-mix(in srgb, var(--warning, #fbbf24) 35%, transparent) var(--yellow-lo-start, 0%),
      color-mix(in srgb, var(--warning, #fbbf24) 35%, transparent) var(--green-start, 0%),
      color-mix(in srgb, var(--success, #4ade80) 45%, transparent) var(--green-start, 0%),
      color-mix(in srgb, var(--success, #4ade80) 45%, transparent) var(--green-end, 100%),
      color-mix(in srgb, var(--warning, #fbbf24) 35%, transparent) var(--green-end, 100%),
      color-mix(in srgb, var(--warning, #fbbf24) 35%, transparent) var(--yellow-hi-end, 100%),
      color-mix(in srgb, var(--danger, #f87171) 30%, transparent) var(--yellow-hi-end, 100%),
      color-mix(in srgb, var(--danger, #f87171) 30%, transparent) 100%
    );
    pointer-events: none;
  }
  .slider {
    width: 100%;
    appearance: none;
    background: transparent;
    height: 32px;
    cursor: pointer;
    margin: 0;
    padding: 0;
  }
  .slider::-webkit-slider-runnable-track {
    height: 32px;
    background: transparent;
  }
  .slider::-webkit-slider-thumb {
    appearance: none;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--text-primary, #fff);
    border: 2px solid var(--accent-primary);
    margin-top: 7px;
    cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  .slider::-moz-range-track {
    height: 32px;
    background: transparent;
  }
  .slider::-moz-range-thumb {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--text-primary, #fff);
    border: 2px solid var(--accent-primary);
    cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }

  .zone-legend {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 10px;
    color: var(--text-muted);
  }
  .legend-item { display: flex; gap: 4px; align-items: center; }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
  }
  .dot.zone-green { background: var(--success, #4ade80); }
  .dot.zone-yellow { background: var(--warning, #fbbf24); }
  .dot.zone-red { background: var(--danger, #f87171); }
</style>
