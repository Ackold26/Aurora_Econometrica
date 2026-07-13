<script>
  import { invoke } from '@tauri-apps/api/core';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { activeCabinet, messages, isLoading, pendingCommand, lastCabinetId, recordRecentCommand, cabinetOnboarding, theme, toggleTheme, inboxFiles, cloudConsent, cloudConsentPromptOpen } from '$lib/store.js';
  import { ChartColumn } from 'lucide-svelte';
  import { activeProject } from '$lib/project-state.js';
  import { getProductName, getCommandBrief, getCommandMeta } from '$lib/command-meta.js';
  import CommandBrief from '$lib/components/CommandBrief.svelte';
  import { productType, activeBrand, isCreativeHub } from '$lib/creative-store.js';
  import { toast } from '$lib/toast.js';
  import { endSession, pluralRu, milestones, getCabinetMastery } from '$lib/psy.js';
  import { parseResponseSections, isSlideDeckResponse, isStructuredResponse, splitSlideSections, groupSlidesByBlocks } from '$lib/response-parser.js';
  import ChatPanel from '$lib/components/ChatPanel.svelte';
  import FileList from '$lib/components/FileList.svelte';
  import SlidePanel from '$lib/components/SlidePanel.svelte';
  import CommandGrid from '$lib/components/CommandGrid.svelte';
  import CabinetOnboarding from '$lib/components/CabinetOnboarding.svelte';
  import { shouldShowOnboarding, completeOnboarding, getOnboardingConfig } from '$lib/onboarding-config.js';

  // Redirect if no active cabinet
  if (!$activeCabinet) {
    goto('/');
  }

  // Кабинеты-советники требуют согласия на облачную обработку (облачная редакция).
  // Единый funnel: все точки открытия кабинета ведут на /cabinet, поэтому гейт здесь
  // покрывает NavRail / главную / Ctrl+K / pipeline-chain. Graceful: без согласия вернуть
  // на главную и открыть экран согласия — MMM-анализ при этом полностью доступен.
  $effect(() => {
    if ($cloudConsent.loaded && $cloudConsent.advisorsEnabled && !$cloudConsent.granted) {
      cloudConsentPromptOpen.set(true);
      goto('/');
    }
  });

  // C4: Cabinet Mastery Badge (Self-Determination Theory)
  // $milestones читается для реактивности - пересчитывается при каждом запросе
  const masteryBadge = $derived.by(() => {
    if (!$activeCabinet) return null;
    void $milestones; // подписка для реактивного пересчёта
    return getCabinetMastery($activeCabinet.id);
  });

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

  // ── CommandBrief: pending brief state ──
  /** @type {string|null} */
  let pendingBriefCommand = $state(null);
  /** @type {import('$lib/command-meta.js').BriefField[]|null} */
  let pendingBriefFields = $state(null);

  /**
   * Check if command requires files and inbox is empty.
   * @param {string} command - slash command (e.g. "/analytics")
   * @returns {boolean} true if OK to proceed
   */
  function checkInboxRequired(command) {
    const slug = command.split(/\s/)[0]; // "/analytics Param..." → "/analytics"
    const meta = getCommandMeta(slug);
    if (meta?.needsFile && $inboxFiles.length === 0) {
      toast('Загрузите файл во «Входящие» перед запуском этой команды', 'error', 5000);
      return false;
    }
    return true;
  }

  /**
   * Called when user clicks a command card.
   * Commands with briefFields → show brief panel; others → execute immediately.
   * @param {string} command
   */
  function executeCommand(command) {
    if ($activeCabinet) recordRecentCommand($activeCabinet.id, command);
    const brief = getCommandBrief(command);
    if (brief) {
      // Brief panel will call runWithBrief → check happens there
      pendingBriefCommand = command;
      pendingBriefFields = brief.fields;
    } else {
      if (!checkInboxRequired(command)) return;
      pendingCommand.set(command);
      workspaceMode = 'execution';
    }
  }

  /** Run command with built brief text. */
  function runWithBrief(/** @type {string} */ text) {
    if (!checkInboxRequired(pendingBriefCommand || text)) return;
    pendingBriefCommand = null;
    pendingBriefFields = null;
    pendingCommand.set(text);
    workspaceMode = 'execution';
  }

  /** Cancel brief → return to CommandGrid. */
  function cancelBrief() {
    pendingBriefCommand = null;
    pendingBriefFields = null;
  }

  // Reset brief when cabinet changes (NavRail switch without remount)
  $effect(() => {
    void $activeCabinet?.id;
    pendingBriefCommand = null;
    pendingBriefFields = null;
  });

  // ── Onboarding ──
  const showOnboarding = $derived.by(() => {
    if (!$activeCabinet) return false;
    return shouldShowOnboarding(
      $activeCabinet.id,
      $milestones.cabinetRequests || {},
      $cabinetOnboarding
    );
  });

  const noviceCommands = $derived.by(() => {
    if (!$activeCabinet) return undefined;
    const uses = ($milestones.cabinetRequests || {})[$activeCabinet.id] || 0;
    if (uses < 5) {
      const config = getOnboardingConfig($activeCabinet.id);
      return config?.noviceCommands || undefined;
    }
    return undefined;
  });

  // PSY-7: Zen Mode
  let zenMode = $state(false);

  // ── SlidePanel: detect PPTX slide-deck responses ──
  let slidePanelVisible = $state(false);
  let activeSlideIdx = $state(-1);

  /** Auto-detect last structured response (slide-deck or any ## sections) */
  let slideData = $derived.by(() => {
    if ($isLoading) return null;
    const msgs = $messages;
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role !== 'assistant') continue;
      const sections = parseResponseSections(msgs[i].content);
      if (isSlideDeckResponse(sections)) {
        const { slides, synthesis } = splitSlideSections(sections);
        return { slides, synthesis, messageIndex: i };
      }
      if (isStructuredResponse(sections)) {
        const titled = sections.filter(s => s.title && s.title.trim());
        return { slides: titled, synthesis: [], messageIndex: i };
      }
    }
    return null;
  });

  /** Resolve which sections to show (manual selection or auto-detected) */
  let activeSlideData = $derived.by(() => {
    if (activeSlideIdx >= 0) {
      const msgs = $messages;
      if (msgs[activeSlideIdx]?.role === 'assistant') {
        const sections = parseResponseSections(msgs[activeSlideIdx].content);
        if (isSlideDeckResponse(sections)) {
          const { slides, synthesis } = splitSlideSections(sections);
          return { slides, synthesis, messageIndex: activeSlideIdx };
        }
        if (isStructuredResponse(sections)) {
          const titled = sections.filter(s => s.title && s.title.trim());
          return { slides: titled, synthesis: [], messageIndex: activeSlideIdx };
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
      if (pendingBriefCommand) { cancelBrief(); return; }
      if (workspaceMode === 'execution') { workspaceMode = 'selection'; return; }
      if (zenMode) { zenMode = false; return; }
      goBack();
    }
  }

  // ── Dependency check for PPTX pipeline ──
  /** @type {{python_available: boolean, python_version: string, missing_packages: string[], all_ok: boolean}|null} */
  let depStatus = $state(null);
  let depInstalling = $state(false);

  async function checkDeps() {
    try {
      depStatus = await invoke('check_pptx_dependencies');
    } catch { depStatus = null; }
  }

  async function installDeps() {
    if (!depStatus?.missing_packages?.length) return;
    depInstalling = true;
    try {
      await invoke('install_pptx_dependencies', { packages: depStatus.missing_packages });
      toast('Зависимости установлены', 'success');
      await checkDeps();
    } catch (e) {
      toast(`Ошибка установки: ${e}`, 'error');
    } finally {
      depInstalling = false;
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleCabinetKeydown);
    checkDeps();
    return () => window.removeEventListener('keydown', handleCabinetKeydown);
  });

  // Update window title to match cabinet name
  $effect(() => {
    document.title = $activeCabinet ? `${getProductName($productType)} - ${$activeCabinet.name}` : getProductName($productType);
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
    // PSY-8: Session Arc - показать summary при уходе
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
        <!-- Логотип + название продукта - тот же layout что в главном меню (src/routes/+page.svelte) -->
        <div class="topbar-left">
          <img src="/logo-horizon.png" alt="Aurora AI" class="topbar-logo" />
          <div class="brand">
            <span class="brand-product">ECONOMETRICA</span>
            <span class="brand-sub">OPTIMIZER MMM</span>
          </div>
        </div>
        {#if $activeProject}
          <span class="breadcrumb-project" title="Активный проект - переключение в pipeline">
            <ChartColumn size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> {$activeProject.name}
          </span>
        {/if}

        <div class="header-spacer"></div>
        <button class="header-icon-btn" title="Переключить тему" onclick={toggleTheme}>
          {#if $theme === 'dark'}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
          {:else if $theme === 'light'}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <circle cx="12" cy="12" r="5"/>
              <line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
              <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
            </svg>
          {:else}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 8h1a4 4 0 0 1 0 8h-1"/>
              <path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z"/>
              <line x1="6" y1="1" x2="6" y2="4"/>
              <line x1="10" y1="1" x2="10" y2="4"/>
              <line x1="14" y1="1" x2="14" y2="4"/>
            </svg>
          {/if}
        </button>
        <a href="/settings" class="header-icon-btn" title="Настройки">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </a>
        <button class="zen-toggle-btn" onclick={() => zenMode = true} title="Режим фокуса (Ctrl+Shift+Z)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
          </svg>
        </button>
        {#if $activeCabinet.id !== 'econometrist'}
          <button class="help-btn" onclick={openHelp} title="Инструкция">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="12" cy="12" r="10"/>
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </button>
        {/if}
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
        <!-- SlidePanel - LEFT side (like PowerPoint), visible alongside FileList -->
        {#if slidePanelVisible && activeSlideData && workspaceMode === 'execution'}
          <SlidePanel
            sections={activeSlideData.slides}
            synthesis={activeSlideData.synthesis}
            onClose={() => { slidePanelVisible = false; }}
          />
        {/if}

        <!-- Selection mode: Command Grid / CommandBrief -->
        <div class="selection-panel" class:hidden={workspaceMode === 'execution'}>
          {#if pendingBriefCommand && pendingBriefFields}
            <CommandBrief
              command={pendingBriefCommand}
              fields={pendingBriefFields}
              onRun={runWithBrief}
              onCancel={cancelBrief}
            />
          {:else if showOnboarding}
            <CabinetOnboarding
              cabinetId={$activeCabinet?.id ?? ''}
              onExecuteCommand={executeCommand}
              onComplete={() => completeOnboarding($activeCabinet?.id ?? '')}
            />
          {:else}
            {#if depStatus && !depStatus.all_ok}
              <div class="dep-banner">
                {#if !depStatus.python_available}
                  <p class="dep-text">Для работы с PPTX-презентациями необходим Python 3</p>
                  <a href="https://www.python.org/downloads/" target="_blank" rel="noopener" class="dep-btn dep-btn-primary">Скачать Python</a>
                {:else if depStatus.missing_packages.length > 0}
                  <p class="dep-text">Не установлены пакеты: {depStatus.missing_packages.join(', ')}</p>
                  <button class="dep-btn dep-btn-primary" onclick={installDeps} disabled={depInstalling}>
                    {depInstalling ? 'Установка...' : 'Установить автоматически'}
                  </button>
                {/if}
              </div>
            {/if}
            <CommandGrid cabinetId={$activeCabinet?.id} onExecute={executeCommand} />
          {/if}
          <!-- FileList sidebar stays visible during onboarding -->
          <div class="selection-input-area">
            <button class="footer-back-btn" onclick={goBack} title="В главное меню" aria-label="Назад">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
              </svg>
              Назад
            </button>
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
    height: 100px;
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
      color-mix(in srgb, var(--accent-secondary) 50%, transparent) 80%,
      transparent 100%
    );
    flex-shrink: 0;
    opacity: 0.6;
  }

  /* ── Breadcrumb ── */
  .breadcrumb {
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .breadcrumb-logo {
    height: 22px;
    width: auto;
    vertical-align: middle;
    margin-right: 6px;
    opacity: 0.9;
  }

  .breadcrumb-root {
    font-size: 11px;
    color: var(--text-secondary);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  /* Логотип+бренд - идентично главному меню (/+page.svelte) */
  .topbar-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .topbar-logo {
    height: 87px;
    width: auto;
  }
  .brand {
    display: flex;
    flex-direction: column;
    gap: 0px;
    line-height: 1;
  }
  .brand-product {
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: var(--text-primary);
    text-transform: uppercase;
  }

  .brand-sub {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.18em;
    color: var(--text-secondary);
    text-transform: uppercase;
    margin-top: 2px;
  }

  /* Активный проект - chip рядом с логотипом, как в pipeline */
  .breadcrumb-project {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: 10px;
    padding: 4px 10px;
    font-size: 11.5px;
    color: var(--text-secondary);
    background: var(--bg-surface-quiet, rgba(30,33,44,0.6));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 999px;
    white-space: nowrap;
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
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
    font-weight: var(--font-weight-heading);
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }

  .mastery-badge {
    font-size: 10px;
    font-weight: 500;
    color: var(--accent-primary);
    background: rgba(var(--accent-primary-rgb, 99, 102, 241), 0.08);
    border: 1px solid rgba(var(--accent-primary-rgb, 99, 102, 241), 0.2);
    padding: 2px 7px;
    border-radius: var(--radius-chip);
    cursor: default;
    user-select: none;
    white-space: nowrap;
  }

  .brand-badge {
    font-size: 10px;
    color: var(--text-secondary);
    background: var(--accent-glow);
    border: 1px solid var(--accent-glow);
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
    background: var(--accent-glow);
    color: var(--text-primary);
    border-color: var(--accent-glow);
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
    flex: 1 1 0;        /* basis: 0 - height from flex container, not content */
    display: flex;
    flex-direction: column;
    overflow: hidden;
    opacity: 1;
    transition: opacity 200ms ease-out;
  }

  /* Visibility + height: 0 вместо display:none - сохраняет CSS transitions */
  .selection-panel.hidden,
  .execution-panel.hidden {
    opacity: 0;
    height: 0;
    overflow: hidden;
    pointer-events: none;
    position: absolute;
    visibility: hidden;
  }

  /* Nav-back в footer - слева от поля ввода команды (симметрия с pipeline footer). */
  .footer-back-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    height: 38px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.12));
    border-radius: var(--radius-sm, 6px);
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    flex-shrink: 0;
  }
  .footer-back-btn:hover {
    color: var(--text-primary, #e2e8f0);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 50%, transparent);
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 6%, transparent);
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
    border-radius: var(--radius-input);
    font-size: 14px;
    font-family: inherit;
    resize: none;
    min-height: 42px;
    max-height: 100px;
    line-height: 1.5;
    transition: border-color var(--transition-fast);
  }

  .selection-input:focus {
    border-color: var(--border-active);
    box-shadow: 0 0 0 2px var(--accent-glow);
  }

  .selection-send {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 42px;
    height: 42px;
    background: var(--gradient-primary);
    border-radius: var(--radius-btn);
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
    border-color: var(--accent-glow-strong);
  }

  /* ── Header icon buttons (theme, settings) ── */
  .header-icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    border: none;
    cursor: pointer;
    transition: all var(--transition-fast);
    flex-shrink: 0;
    text-decoration: none;
  }

  .header-icon-btn:hover {
    color: var(--text-primary);
    background: var(--bg-tertiary);
  }

  .header-icon-btn.header-icon-active {
    color: var(--accent-primary);
    background: var(--accent-glow);
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
    border-color: var(--accent-glow);
    background: var(--accent-glow);
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
    background: var(--hover-bg);
  }

  .zen-exit-label {
    font-weight: 500;
  }

  /* ── Dependency banner ── */
  .dep-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 20px;
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-radius: var(--radius-sm);
    margin: 8px 20px 0;
    flex-shrink: 0;
  }

  .dep-text {
    flex: 1;
    font-size: 13px;
    color: var(--text-secondary);
    margin: 0;
  }

  .dep-btn {
    padding: 6px 14px;
    border-radius: var(--radius-sm);
    font-size: 12px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    white-space: nowrap;
    transition: all var(--transition-fast);
    text-decoration: none;
  }

  .dep-btn-primary {
    background: var(--accent-primary);
    color: var(--text-on-accent, #fff);
    border: none;
  }

  .dep-btn-primary:hover:not(:disabled) {
    filter: brightness(1.1);
  }

  .dep-btn-primary:disabled {
    opacity: 0.6;
    cursor: default;
  }
</style>
