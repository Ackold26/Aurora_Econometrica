<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { activeCabinet, messages, isLoading, pendingCommand, lastCabinetId, recordRecentCommand } from '$lib/store.js';
  import { getProductName } from '$lib/command-meta.js';
  import { productType, activeBrand, isCreativeHub } from '$lib/creative-store.js';
  import { toast } from '$lib/toast.js';
  import { endSession, pluralRu } from '$lib/psy.js';
  import { parseResponseSections, isSlideDeckResponse, splitSlideSections } from '$lib/response-parser.js';
  import ChatPanel from '$lib/components/ChatPanel.svelte';
  import FileList from '$lib/components/FileList.svelte';
  import SlidePanel from '$lib/components/SlidePanel.svelte';
  import CommandGrid from '$lib/components/CommandGrid.svelte';

  // Redirect if no active cabinet
  if (!$activeCabinet) {
    goto('/');
  }

  // ── Workspace mode: selection (command grid) / execution (chat) ──
  /** @type {'selection' | 'execution'} */
  let workspaceMode = $state('selection');

  // Sync mode with messages: switch to execution when messages exist, selection when empty
  $effect(() => {
    if ($messages.length > 0) {
      workspaceMode = 'execution';
    } else {
      workspaceMode = 'selection';
    }
  });

  /** @param {string} command */
  function executeCommand(command) {
    if ($activeCabinet) {
      recordRecentCommand($activeCabinet.id, command);
    }
    pendingCommand.set(command);
    workspaceMode = 'execution';
  }

  /** Selection mode input */
  let selectionInput = $state('');

  function submitSelectionInput() {
    const text = selectionInput.trim();
    if (!text) return;
    selectionInput = '';
    pendingCommand.set(text);
    workspaceMode = 'execution';
  }

  /** @param {KeyboardEvent} e */
  function handleSelectionKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitSelectionInput();
    }
  }

  // PSY-7: Zen Mode
  let zenMode = $state(false);

  // ── SlidePanel: detect PPTX slide-deck responses ──
  let slidePanelVisible = $state(false);
  let activeSlideIdx = $state(-1);

  /** Auto-detect last slide-deck message (only when not streaming) */
  let slideData = $derived.by(() => {
    if ($isLoading) return null;
    const msgs = $messages;
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role !== 'assistant') continue;
      const sections = parseResponseSections(msgs[i].content);
      if (isSlideDeckResponse(sections)) {
        return { slides: splitSlideSections(sections).slides, messageIndex: i };
      }
    }
    return null;
  });

  /** Resolve which slides to show (manual selection or auto-detected) */
  let activeSlideData = $derived.by(() => {
    if (activeSlideIdx >= 0) {
      const msgs = $messages;
      if (msgs[activeSlideIdx]?.role === 'assistant') {
        const sections = parseResponseSections(msgs[activeSlideIdx].content);
        if (isSlideDeckResponse(sections)) {
          return { slides: splitSlideSections(sections).slides, messageIndex: activeSlideIdx };
        }
      }
    }
    return slideData;
  });

  /** Auto-show sidebar when new slide data is detected */
  $effect(() => {
    if (slideData && slideData.messageIndex !== activeSlideIdx) {
      slidePanelVisible = true;
      activeSlideIdx = slideData.messageIndex;
    }
  });

  /** @param {KeyboardEvent} e */
  function handleCabinetKeydown(e) {
    // Ctrl+Shift+Z → toggle zen mode
    if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      zenMode = !zenMode;
      return;
    }
    // Escape → execution→selection → zen off → back to home
    if (e.key === 'Escape' && !['INPUT', 'TEXTAREA'].includes(/** @type {HTMLElement} */ (e.target)?.tagName)) {
      if (workspaceMode === 'execution') { workspaceMode = 'selection'; return; }
      if (zenMode) { zenMode = false; return; }
      goBack();
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleCabinetKeydown);
    return () => window.removeEventListener('keydown', handleCabinetKeydown);
  });

  // Update window title to match cabinet name
  $effect(() => {
    document.title = $activeCabinet ? `${getProductName($productType)} — ${$activeCabinet.name}` : getProductName($productType);
  });

  async function openHelp() {
    const cabinetId = $activeCabinet?.id;
    if (!cabinetId) return;
    try {
      await invoke('open_help', { cabinetId });
    } catch (e) {
      console.error('Failed to open help:', e);
    }
  }

  async function goBack() {
    const cabinetId = $activeCabinet?.id;
    if (cabinetId) lastCabinetId.set(cabinetId);
    // PSY-8: Session Arc — показать summary при уходе
    const session = endSession();
    if (session && session.requests > 0) {
      const reqWord = pluralRu(session.requests, 'запрос', 'запроса', 'запросов');
      toast(`Сессия: ${session.requests} ${reqWord}, ~${session.durationMin} мин`, 'info', 4000);
    }
    if (cabinetId) {
      try {
        await invoke('close_cabinet', { cabinetId });
      } catch {
        // ignore
      }
    }
    messages.set([]);
    slidePanelVisible = false;
    activeSlideIdx = -1;
    activeCabinet.set(null);
    document.title = getProductName($productType);
    goto('/');
  }
</script>

{#if $activeCabinet}
  <div class="workspace" class:zen={zenMode}>
    <!-- ── Cabinet Header ── -->
    {#if !zenMode}
      <header class="header" style="--cabinet-color: {$activeCabinet.color}">
        <button class="back-btn" onclick={goBack} title="Назад">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 12H5M12 19l-7-7 7-7"/>
          </svg>
        </button>

        <div class="breadcrumb">
          <span class="breadcrumb-root">AURORA</span>
          <svg class="breadcrumb-sep" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18l6-6-6-6"/>
          </svg>
          <span class="breadcrumb-icon">{$activeCabinet.icon}</span>
          <span class="breadcrumb-name">{$activeCabinet.name}</span>
        </div>

        {#if $activeBrand}
          <span class="brand-badge">{$activeBrand.name}</span>
        {/if}
        <div class="header-spacer"></div>
        <button class="zen-toggle-btn" onclick={() => zenMode = true} title="Режим фокуса (Ctrl+Shift+Z)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
          </svg>
        </button>
        <button class="help-btn" onclick={openHelp} title="Инструкция">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
        </button>
      </header>

      <!-- accent gradient rule under header -->
      <div class="header-rule" style="--cabinet-color: {$activeCabinet.color}"></div>
    {:else}
      <!-- Zen mode: minimal top bar -->
      <div class="zen-bar">
        <button class="zen-exit-btn" onclick={() => zenMode = false} title="Выйти из режима фокуса (Esc)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>
          </svg>
          <span class="zen-exit-label">{$activeCabinet.name}</span>
        </button>
      </div>
    {/if}

    {#key $activeCabinet?.id}
      <div class="content">
        <!-- SlidePanel — LEFT side (like PowerPoint), visible alongside FileList -->
        {#if slidePanelVisible && activeSlideData && workspaceMode === 'execution'}
          <SlidePanel
            sections={activeSlideData.slides}
            onClose={() => { slidePanelVisible = false; }}
          />
        {/if}

        <!-- Selection mode: Command Grid -->
        <div class="selection-panel" class:hidden={workspaceMode === 'execution'}>
          <CommandGrid cabinetId={$activeCabinet?.id} onExecute={executeCommand} />
          <div class="selection-input-area">
            <textarea
              class="selection-input"
              bind:value={selectionInput}
              onkeydown={handleSelectionKeydown}
              placeholder="Выберите и запустите команду..."
              rows="1"
            ></textarea>
            <button class="selection-send" onclick={submitSelectionInput} disabled={!selectionInput.trim()} aria-label="Отправить">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                <path d="M5 12h14M12 5l7 7-7 7"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Execution mode: Chat Panel -->
        <div class="execution-panel" class:hidden={workspaceMode === 'selection'}>
          {#if workspaceMode === 'execution'}
            <button class="back-to-selection" onclick={() => workspaceMode = 'selection'}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
              </svg>
              К командам
            </button>
          {/if}
          <div class="chat-wrapper">
            <ChatPanel onShowSlides={(idx) => { activeSlideIdx = idx; slidePanelVisible = true; }} />
          </div>
        </div>

        {#if !zenMode}
          <FileList />
        {/if}
      </div>
    {/key}
  </div>
{/if}

<style>
  .workspace {
    height: 100%;
    display: flex;
    flex-direction: column;
  }

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 20px;
    height: 48px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-glass);
    backdrop-filter: var(--blur-quiet);
    -webkit-backdrop-filter: var(--blur-quiet);
    flex-shrink: 0;
    z-index: 10;
  }

  .header-rule {
    height: 1.5px;
    background: linear-gradient(
      90deg,
      transparent 0%,
      var(--cabinet-color) 20%,
      rgba(204, 255, 0, 0.5) 80%,
      transparent 100%
    );
    flex-shrink: 0;
    opacity: 0.6;
  }

  .back-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    transition: all var(--transition-fast);
    flex-shrink: 0;
  }

  .back-btn:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }

  /* ── Breadcrumb ── */
  .breadcrumb {
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .breadcrumb-root {
    font-size: 12.5px;
    color: var(--text-secondary);
    font-weight: 500;
  }

  .breadcrumb-sep {
    color: var(--text-muted);
    opacity: 0.7;
  }

  .breadcrumb-icon {
    font-size: 14px;
    line-height: 1;
  }

  .breadcrumb-name {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }

  .brand-badge {
    font-size: 10px;
    color: var(--text-secondary);
    background: rgba(99, 102, 241, 0.1);
    border: 1px solid rgba(99, 102, 241, 0.2);
    padding: 2px 8px;
    border-radius: 4px;
    margin-left: 8px;
  }

  .header-spacer {
    flex: 1;
  }

  .help-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    cursor: pointer;
    transition: all var(--transition-fast);
    flex-shrink: 0;
  }

  .help-btn:hover {
    background: rgba(46, 91, 255, 0.08);
    color: var(--text-primary);
    border-color: rgba(46, 91, 255, 0.2);
  }

  /* ── Content ── */
  .content {
    flex: 1 1 0;
    display: flex;
    overflow: hidden;
  }

  /* ── Selection / Execution panels ── */
  .selection-panel,
  .execution-panel {
    flex: 1 1 0;        /* basis: 0 — height from flex container, not content */
    display: flex;
    flex-direction: column;
    overflow: hidden;
    opacity: 1;
    transition: opacity 200ms ease-out;
  }

  /* Visibility + height: 0 вместо display:none — сохраняет CSS transitions */
  .selection-panel.hidden,
  .execution-panel.hidden {
    opacity: 0;
    height: 0;
    overflow: hidden;
    pointer-events: none;
    position: absolute;
    visibility: hidden;
  }

  /* ── Selection input area ── */
  .selection-input-area {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 12px 20px;
    border-top: 1px solid var(--border);
    background: var(--panel-bg);
    flex-shrink: 0;
  }

  .selection-input {
    flex: 1;
    background: var(--input-bg);
    border: 1px solid var(--input-border);
    color: var(--text-primary);
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 14px;
    font-family: inherit;
    resize: none;
    min-height: 42px;
    max-height: 100px;
    line-height: 1.5;
    transition: border-color var(--transition-fast);
  }

  .selection-input:focus {
    border-color: rgba(46, 91, 255, 0.4);
    box-shadow: 0 0 0 2px rgba(46, 91, 255, 0.1);
  }

  .selection-send {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 42px;
    height: 42px;
    background: linear-gradient(135deg, #2E5BFF 0%, #5A8AFF 60%, rgba(204,255,0,0.8) 100%);
    border-radius: 8px;
    border: none;
    color: white;
    cursor: pointer;
    flex-shrink: 0;
    transition: all var(--transition-fast);
  }

  .selection-send:hover:not(:disabled) {
    transform: translateY(-1px);
    filter: brightness(1.1);
  }

  .selection-send:disabled {
    opacity: 0.4;
    cursor: default;
  }

  /* ── Chat wrapper (flex child for proper scroll) ── */
  .chat-wrapper {
    flex: 1 1 0;        /* basis: 0 forces height from flex, not content */
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Back to selection button ── */
  .back-to-selection {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    margin: 8px 20px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-secondary);
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    transition: all var(--transition-fast);
    flex-shrink: 0;
    align-self: flex-start;
  }

  .back-to-selection:hover {
    background: var(--hover-bg);
    color: var(--text-primary);
    border-color: rgba(46, 91, 255, 0.3);
  }

  /* ── PSY-7: Zen Mode ── */
  .zen-toggle-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    border: 1px solid transparent;
    cursor: pointer;
    transition: all var(--transition-fast);
    flex-shrink: 0;
  }

  .zen-toggle-btn:hover {
    color: var(--accent-primary);
    border-color: rgba(46, 91, 255, 0.2);
    background: rgba(46, 91, 255, 0.06);
  }

  .zen-bar {
    display: flex;
    align-items: center;
    padding: 4px 12px;
    height: 32px;
    flex-shrink: 0;
    opacity: 0.4;
    transition: opacity 0.2s;
  }

  .zen-bar:hover {
    opacity: 1;
  }

  .zen-exit-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 11px;
    padding: 4px 8px;
    border-radius: 6px;
    transition: all 0.15s;
  }

  .zen-exit-btn:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.04);
  }

  .zen-exit-label {
    font-weight: 500;
  }
</style>
