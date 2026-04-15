<script>
  /** @type {{zoom: number, view: 'simple'|'canvas', onZoomIn: () => void, onZoomOut: () => void, onFitAll: () => void, onResetLayout: () => void, onToggleView: () => void}} */
  let { zoom = 1, view = 'canvas', onZoomIn, onZoomOut, onFitAll, onResetLayout, onToggleView } = $props();
</script>

<div class="toolbar">
  <div class="toolbar-group">
    <button class="tb-btn" class:active={view === 'simple'} onclick={onToggleView} title="Simple View">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>
    </button>
    <button class="tb-btn" class:active={view === 'canvas'} onclick={onToggleView} title="Canvas View">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M5 8v2a4 4 0 0 0 4 4h2m8-6v2a4 4 0 0 1-4 4h-2"/></svg>
    </button>
  </div>

  <div class="toolbar-separator"></div>

  <div class="toolbar-group">
    <button class="tb-btn" onclick={onZoomOut} title="Zoom out">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
    </button>
    <span class="zoom-label">{Math.round(zoom * 100)}%</span>
    <button class="tb-btn" onclick={onZoomIn} title="Zoom in">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
    </button>
  </div>

  <div class="toolbar-separator"></div>

  <button class="tb-btn" onclick={onFitAll} title="Fit all (F)">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>
  </button>
  <button class="tb-btn" onclick={onResetLayout} title="Reset layout">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
  </button>
</div>

<style>
  .toolbar { display: flex; align-items: center; gap: 4px; padding: 6px 10px; background: var(--bg-tertiary); backdrop-filter: var(--blur-quiet); border: 1px solid var(--border-subtle, rgba(255,255,255,0.07)); border-radius: 10px; }
  .toolbar-group { display: flex; align-items: center; gap: 2px; }
  .toolbar-separator { width: 1px; height: 20px; background: var(--border); margin: 0 4px; }
  .tb-btn { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 6px; border: none; background: transparent; color: var(--text-secondary, #aaa); cursor: pointer; transition: all 0.12s ease; }
  .tb-btn:hover { background: var(--hover-bg); color: var(--text-primary); }
  .tb-btn.active { background: var(--accent-glow-strong); color: var(--accent-primary); }
  .zoom-label { font-size: 11px; color: var(--text-muted, #888); min-width: 36px; text-align: center; font-variant-numeric: tabular-nums; }
</style>
