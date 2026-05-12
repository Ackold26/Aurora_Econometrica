<script>
  import { getCabinetUsageCount, milestones } from '$lib/psy.js';

  /** @type {{cabinet: {id: string, name: string, description: string, icon: string, color: string}, onClick: () => void}} */
  let { cabinet, onClick } = $props();

  // PSY-9: mastery counter - реактивный через milestones store
  let usageCount = $derived.by(() => {
    $milestones; // track reactivity
    return getCabinetUsageCount(cabinet.id);
  });

  // Tech SVG icon map keyed by cabinet id
  // Each value is the inner SVG content (paths/circles/etc) for viewBox="0 0 24 24"
  /** @type {Record<string, string>} */
  const iconMap = {
    'media-analyst': `
      <path d="M3 3v18h18"/>
      <path d="M7 16l4-4 4 4 4-6"/>
      <circle cx="7" cy="16" r="1.2" fill="currentColor"/>
      <circle cx="11" cy="12" r="1.2" fill="currentColor"/>
      <circle cx="15" cy="16" r="1.2" fill="currentColor"/>
      <circle cx="19" cy="10" r="1.2" fill="currentColor"/>`,

    'communication-analyst': `
      <path d="M2 12c0-5.5 4.5-10 10-10s10 4.5 10 10"/>
      <path d="M5 12c0-3.9 3.1-7 7-7s7 3.1 7 7"/>
      <path d="M8 12c0-2.2 1.8-4 4-4s4 1.8 4 4"/>
      <circle cx="12" cy="12" r="1.5" fill="currentColor"/>`,

    'communication-strategist': `
      <circle cx="12" cy="12" r="10"/>
      <circle cx="12" cy="12" r="3"/>
      <line x1="12" y1="2" x2="12" y2="9"/>
      <line x1="12" y1="15" x2="12" y2="22"/>
      <line x1="2" y1="12" x2="9" y2="12"/>
      <line x1="15" y1="12" x2="22" y2="12"/>`,

    'creative-director': `
      <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/>`,

    'lawyer-contracts': `
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="8" y1="13" x2="16" y2="13"/>
      <line x1="8" y1="17" x2="13" y2="17"/>`,

    'lawyer-claims': `
      <path d="M12 2L2 7l10 5 10-5-10-5z"/>
      <path d="M2 17l10 5 10-5"/>
      <path d="M2 12l10 5 10-5"/>`,

    'lawyer-advertising': `
      <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"/>
      <path d="M4.93 4.93l14.14 14.14"/>
      <path d="M9 9h.01M15 9h.01M9 15h6"/>`,

    'social-listening': `
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
      <circle cx="12" cy="12" r="3"/>`,

    'doc-master': `
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <path d="M8 13h3l2-2 2 2h1"/>
      <line x1="8" y1="17" x2="16" y2="17"/>`,

    'focus-groups': `
      <circle cx="12" cy="7" r="4"/>
      <path d="M5.5 21a6.5 6.5 0 0 1 13 0"/>
      <circle cx="5" cy="9" r="2.5"/>
      <circle cx="19" cy="9" r="2.5"/>`,
  };

  // Fallback: generic terminal/chip icon
  const fallbackIcon = `
    <rect x="4" y="4" width="16" height="16" rx="2"/>
    <line x1="9" y1="9" x2="15" y2="9"/>
    <line x1="9" y1="12" x2="15" y2="12"/>
    <line x1="9" y1="15" x2="12" y2="15"/>`;


</script>

<button
  class="card"
  style="--card-color: {cabinet.color}"
  onclick={onClick}
>
  <!-- top accent line -->
  <div class="card-accent-line"></div>

  <div class="card-body">
    <div class="card-icon">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <!-- aurora-fix:safe V40 - iconMap/fallbackIcon содержат статические SVG-фрагменты из константы в этом же файле, без user input -->
        {@html iconMap[cabinet.id] ?? fallbackIcon}
      </svg>
    </div>
    <h3 class="card-name">{cabinet.name}</h3>
    <p class="card-desc">{cabinet.description}</p>
  </div>

  <div class="card-footer">
    <span class="card-hint">Открыть</span>
    {#if usageCount > 0}
      <span class="card-mastery" title="Количество запросов">{usageCount}</span>
    {/if}
    <svg class="card-arrow" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M5 12h14M12 5l7 7-7 7"/>
    </svg>
  </div>
</button>

<style>
  .card {
    display: flex;
    flex-direction: column;
    width: 100%;
    padding: 0;
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    -webkit-backdrop-filter: var(--blur-quiet);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    cursor: pointer;
    text-align: left;
    color: var(--text-primary);
    overflow: hidden;
    position: relative;
    transition: var(--hover-timing);
    box-shadow: var(--shadow-elevation-1);
  }

  .card::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: radial-gradient(ellipse 60% 40% at 50% 0%, var(--hover-bg) 0%, transparent 75%);
    pointer-events: none;
  }

  .card:hover {
    background: var(--bg-glass-hover);
    border-color: var(--border);
    transform: var(--hover-transform);
    box-shadow: var(--shadow-elevation-2), 0 0 0 1px var(--card-color) inset;
  }

  .card:active {
    transform: translateY(-1px);
  }

  /* top accent line */
  .card-accent-line {
    height: 1.5px;
    background: var(--card-color);
    opacity: 0;
    transition: opacity var(--transition-smooth);
  }

  .card:hover .card-accent-line {
    opacity: 1;
  }

  /* ── Body - 10% more compact than original ── */
  .card-body {
    padding: 18px 19px 10px;
    flex: 1;
  }

  /* SVG icon in card-color */
  .card-icon {
    width: 26px;
    height: 26px;
    margin-bottom: 12px;
    color: var(--card-color);
    transition: filter var(--transition-smooth);
  }

  .card-icon svg {
    width: 100%;
    height: 100%;
  }

  .card:hover .card-icon {
    filter: drop-shadow(0 0 5px var(--card-color));
  }

  .card-name {
    font-size: 13.5px;
    font-weight: var(--font-weight-heading);
    letter-spacing: -0.01em;
    margin-bottom: 5px;
    color: var(--text-primary);
  }

  .card-desc {
    font-size: 11.5px;
    color: var(--text-secondary);
    line-height: 1.5;
    min-height: 2.95em;
  }

  /* ── Footer ── */
  .card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 19px 15px;
    border-top: 1px solid var(--hover-bg);
    margin-top: 5px;
  }

  .card-hint {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-muted);
    transition: color var(--transition-fast);
  }

  .card:hover .card-hint {
    color: var(--card-color);
  }

  .card-arrow {
    color: var(--card-color);
    opacity: 0;
    transform: translateX(-5px);
    transition: all var(--transition-smooth);
    flex-shrink: 0;
  }

  .card:hover .card-arrow {
    opacity: 1;
    transform: translateX(0);
  }

  /* PSY-9: Mastery counter */
  .card-mastery {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--hover-bg);
    padding: 2px 7px;
    border-radius: 10px;
    margin-left: auto;
    margin-right: 6px;
    font-variant-numeric: tabular-nums;
    transition: all var(--transition-fast);
  }

  .card:hover .card-mastery {
    color: var(--card-color);
    background: var(--hover-bg);
  }
</style>
