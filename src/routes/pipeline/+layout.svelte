<script>
  /**
   * Pipeline shell layout.
   * C1: Guard - only accessible for econometrica product type.
   * C4: InsightsPanel width clamp(240px, 22%, 360px), auto-collapse < 1100px.
   * C5: Sidecar status indicator in footer.
   */
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { goto } from '$app/navigation';
  import { invoke } from '@tauri-apps/api/core';
  import { save as saveDialog } from '@tauri-apps/plugin-dialog';
  import { productType } from '$lib/creative-store.js';
  import { theme, toggleTheme } from '$lib/store.js';
  import {
    pipelineCurrentStep,
    pipelineStepMeta,
    activeProjectId,
    activeProject,
    expertMode,
    sidecarHealthy,
    sidecarStatus,
    isComputing,
    computeStatus,
    resetPipeline,
    validateData,
    importData,
    validateSubStep,
  } from '$lib/project-state.js';
  import PipelineStepper from '$lib/components/pipeline/PipelineStepper.svelte';
  import InsightsPanel from '$lib/components/pipeline/InsightsPanel.svelte';
  import ProjectSelector from '$lib/components/ProjectSelector.svelte';
  // Phase 1.1: kick off SSOT classifier patterns fetch на startup
  // (cache-with-fallback - UI usable immediately even если backend slow).
  import { ensurePatternsLoaded } from '$lib/services/classifier-patterns.js';
  // Phase 2.16: trust-signal toast после successful migration.
  import MigrationCompletedToast from '$lib/components/MigrationCompletedToast.svelte';
  import ErrorState from '$lib/components/pipeline/ErrorState.svelte';
  import { ChartColumn } from 'lucide-svelte';

  let { children } = $props();

  // C1: Pipeline guard - econometrica only
  const isEconometrica = $derived($productType === 'econometrica');

  let userCollapsed = $state(false); // явное намерение пользователя
  let windowWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 1200);
  /** @type {HTMLElement | undefined} Главный скрол-контейнер шагов */
  let mainEl = $state();

  // Phase 2.16 - migration-completed toast state.
  let migrationToast = $state({
    show: false,
    fromVersion: '',
    toVersion: '',
    movedCount: 0,
  });

  // H-20a - migration error surface (audit). Раньше ошибки уходили в
  // console.warn - customer not notified. Теперь banner с retry button.
  /** @type {{ show: boolean, message: string, projectId: string | null }} */
  let migrationError = $state({ show: false, message: '', projectId: null });

  async function retryMigration() {
    if (!migrationError.projectId) return;
    const id = migrationError.projectId;
    migrationError = { show: false, message: '', projectId: null };
    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: id }));
      if (!projectDir) return;
      const result = /** @type {any} */ (await invoke('econ_migrate_project', { projectDir }));
      if (result?.status === 'ok') {
        const movedCount = (result.migrated_columns || []).length;
        // 2026-05-18 pilot UX: toast только при meaningful classification change.
        // No-op migrations (формат данных обновлён без изменения классификации)
        // перекрывали кнопку «далее» и отвлекали пилот.
        if (movedCount > 0) {
          migrationToast = {
            show: true,
            fromVersion: result.from_version || '',
            toVersion: result.to_version || '',
            movedCount,
          };
        }
      }
    } catch (err) {
      migrationError = {
        show: true,
        message: String(err),
        projectId: id,
      };
    }
  }

  // C4: Auto-collapse on small screens; on large - уважаем userCollapsed
  const insightsCollapsed = $derived(windowWidth < 1100 ? true : userCollapsed);

  function toggleInsights() {
    if (windowWidth >= 1100) userCollapsed = !userCollapsed;
  }

  // Quick save: .aurora archive экспорт с любого шага пайплайна.
  let archivingChip = $state(false);
  /** @type {string} */
  let archiveChipMsg = $state('');
  async function quickSaveArchive() {
    if (!$activeProject || !$activeProjectId || archivingChip) return;
    const safeName = ($activeProject.name || 'project')
      .replace(/[^\p{L}\p{N}._ -]/gu, '_')
      .slice(0, 100);
    archivingChip = true;
    archiveChipMsg = '';
    try {
      const outputPath = await saveDialog({
        defaultPath: `${safeName}.aurora`,
        filters: [{ name: 'Aurora Project', extensions: ['aurora', 'zip'] }],
        title: 'Сохранить проект как архив',
      });
      if (!outputPath) {
        archivingChip = false;
        return;
      }
      await invoke('project_export_archive', {
        projectId: $activeProjectId,
        outputPath,
      });
      archiveChipMsg = '✓ Сохранено';
      setTimeout(() => { archiveChipMsg = ''; }, 4000);
    } catch (e) {
      archiveChipMsg = `Ошибка: ${e}`;
      setTimeout(() => { archiveChipMsg = ''; }, 6000);
    } finally {
      archivingChip = false;
    }
  }

  /** @param {number} step */
  function handleNavigate(step) {
    const meta = $pipelineStepMeta[step];
    if (!meta || meta.status === 'locked') return;
    pipelineCurrentStep.set(step);
  }

  function goBack() {
    const prev = $pipelineCurrentStep - 1;
    if (prev >= 0) {
      pipelineCurrentStep.set(prev);
    } else {
      // Шаг 0 - возвращаем пользователя в главное меню
      goto('/');
    }
  }

  // Справка - одна кнопка в header, контент зависит от текущего шага pipeline.
  // Index в массиве соответствует PIPELINE_STEPS. См. src-tauri/help-econometrica/*.html.
  const HELP_PAGES = ['data-preparation', 'data-preparation', 'methodology', 'pipeline', 'pipeline', 'pipeline', 'pipeline'];
  async function openStepHelp() {
    const page = HELP_PAGES[$pipelineCurrentStep] ?? 'index';
    try {
      await invoke('open_help', { cabinetId: page });
    } catch (e) {
      console.error('Failed to open help:', e);
    }
  }

  function goNext() {
    // 2026-07-10: перескакиваем запертые шаги (опциональное Планирование заперто
    // без подтверждённого медиаплана → «Далее» с Оптимизации ведёт сразу в Отчёт).
    for (let next = $pipelineCurrentStep + 1; next < 7; next++) {
      if ($pipelineStepMeta[next]?.status !== 'locked') {
        pipelineCurrentStep.set(next);
        return;
      }
    }
  }

  // При смене шага сбрасываем scroll наверх - иначе scroll-позиция от прошлого шага
  // оставляет пользователя в середине/внизу нового, и кажется, что страница пустая.
  $effect(() => {
    // Подписка на pipelineCurrentStep - при изменении прокручиваем main в начало.
    const _step = $pipelineCurrentStep;
    if (mainEl) mainEl.scrollTop = 0;
  });

  // C5: Start sidecar and track its status in footer
  async function initSidecar() {
    sidecarStatus.set('Запуск...');
    try {
      await invoke('econ_sidecar_wait_ready', { timeoutMs: 15000 });
      sidecarHealthy.set(true);
      sidecarStatus.set('Готов');
    } catch (/** @type {any} */ err) {
      sidecarHealthy.set(false);
      sidecarStatus.set(`Ошибка: ${err}`);
    }

    // Crash recovery: if training was in progress but sidecar restarted
    const savedTask = typeof localStorage !== 'undefined' ? localStorage.getItem('econ-training-task') : null;
    if (savedTask) {
      try {
        const progress = /** @type {any} */ (await invoke('econ_train_progress'));
        if (progress.status !== 'running') {
          // Sidecar lost state - clean up stale task
          localStorage.removeItem('econ-training-task');
        }
      } catch {
        localStorage.removeItem('econ-training-task');
      }
    }
  }

  onMount(() => {
    // C1: redirect if not econometrica
    if (!isEconometrica) {
      goto('/');
      return;
    }

    // C4: resize handler
    function onResize() { windowWidth = window.innerWidth; }
    window.addEventListener('resize', onResize, { passive: true });

    // Phase 1.1: load SSOT classifier patterns (non-blocking). Result cached
    // в localStorage с TTL 1h; embedded fallback engages если backend slow/down.
    ensurePatternsLoaded().catch(() => { /* fallback handled internally */ });

    // Phase 1.4: opportunistic project.json schema migration на activeProject
    // load. Idempotent - backend returns no_migration_needed если schema_version
    // current. Errors silenced (sync version; async modal UI defer к v2.0.2).
    activeProjectId.subscribe(async (id) => {
      if (!id) return;
      try {
        const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: id }));
        if (!projectDir) return;
        const result = /** @type {any} */ (await invoke('econ_migrate_project', { projectDir }));
        if (result?.status === 'ok') {
          const movedCount = (result.migrated_columns || []).length;
          console.info(
            `[migration] project ${id}: ${result.from_version} → ${result.to_version}, ` +
            `moved ${movedCount} cols`,
          );
          // Phase 2.16 - surface trust-signal toast (audit P-customer-confidence).
          // 2026-05-18 pilot UX: показываем только при meaningful classification
          // change. No-op миграции (формат-only) перекрывали «далее» и отвлекали.
          if (movedCount > 0) {
            migrationToast = {
              show: true,
              fromVersion: result.from_version || '',
              toVersion: result.to_version || '',
              movedCount,
            };
          }
        }
      } catch (err) {
        // H-20a: surface error к UI вместо silent console.warn. Customer видит
        // banner + retry button. Без этого corruption / lock timeout уходили
        // в DevTools console - никто не видел.
        console.warn('[migration] failed:', err);
        migrationError = {
          show: true,
          message: String(err),
          projectId: id,
        };
      }
    });

    // Check for ?new=1 - user clicked "Новый проект в Pipeline" on home
    const forceNew = typeof window !== 'undefined'
      && new URLSearchParams(window.location.search).get('new') === '1';

    if (forceNew) {
      // Clean slate: ignore backend-stored active project, stay at step 0
      activeProjectId.set(null);
      activeProject.set(null);
      pipelineCurrentStep.set(0);
    } else if (!$activeProjectId) {
      // Restore active project from backend if not already set
      (async () => {
        try {
          const id = /** @type {string|null} */ (await invoke('project_get_active'));
          if (id) {
            const info = await invoke('project_get', { projectId: id });
            activeProject.set(info);   // LOAD-1: set ДО restore, чтобы hydrate видел роли без fallback
            activeProjectId.set(id);
            // LOAD-1 fix: resetPipeline = loadPipelineForProject (сброс data-сторов)
            // + restoreProjectResults в ПРАВИЛЬНОМ порядке (restore/hydrate последним).
            // Раньше голый loadPipelineForProject обнулял validateData, а restore
            // (через subscribe) гонился с ним → роли терялись на загруженном проекте.
            resetPipeline(id);
          }
        } catch { /* no active project yet */ }
      })();
    } else {
      // Load pipeline metadata for current project (A4: data never persisted).
      // LOAD-1 fix: resetPipeline (не голый loadPipelineForProject) — гарантирует
      // restoreProjectResults после сброса. Иначе на re-entry в уже-активный
      // проект (activeProjectId уже set → subscribe-guard пропускает restore)
      // validateData оставался null → пустая Валидация + ложное «устарела».
      resetPipeline($activeProjectId);
      // Fix 2026-05-24: post-reload state desync — activeProjectId восстановлен
      // (header показывает slug) но activeProject store null. Guards в OptimizeGoalSeek
      // / других местах проверяют $activeProject?.path → ошибка «Откройте проект сначала».
      // Восстановить info parallel к pipeline meta.
      if (!get(activeProject)) {
        (async () => {
          try {
            const info = await invoke('project_get', { projectId: $activeProjectId });
            if (info) activeProject.set(info);
          } catch { /* ignore */ }
        })();
      }
    }

    // C5: initialise sidecar
    initSidecar();

    return () => window.removeEventListener('resize', onResize);
  });

  // v2.1.0 (пилот 2026-05-16): на под-шаге «Роли колонок» (subStep === -1)
  // главная кнопка «Далее» блокируется до нажатия «Подтвердить роли»
  // внутри ColumnMapperConfirm. После confirm subStep меняется → «Далее»
  // снова активна. Защищает от пропуска явного подтверждения ролей.
  const rolesNotConfirmed = $derived(
    $pipelineCurrentStep === 1 && $validateSubStep === -1
  );

  const canGoNext = $derived(
    $pipelineCurrentStep < 6
    && $pipelineStepMeta[$pipelineCurrentStep + 1]?.status !== 'locked'
    && !rolesNotConfirmed
  );

  // NAV-2 (2026-06-02): на подшагах Валидации футерная «Далее» заблокирована
  // (следующий шаг Модель locked, пока валидация не завершена). Раньше это
  // выглядело «кнопка не работает» без объяснения. Теперь tooltip ведёт к
  // рабочей контентной кнопке «Далее ▶» в секции. Полный контекстный проброс
  // (футер двигает подшаг) требует подъёма confirm-контрактов из дочерних
  // компонентов подшагов - отдельная задача с GUI-прогоном.
  const validateIncomplete = $derived(
    $pipelineCurrentStep === 1
    && !!$validateData?.result
    && $pipelineStepMeta[2]?.status === 'locked'
    && !rolesNotConfirmed
  );

  const nextBtnTitle = $derived(
    rolesNotConfirmed
      ? 'Сначала нажмите «Подтвердить роли» ниже'
      : validateIncomplete
        ? 'Завершите подшаги валидации - кнопка «Далее ▶» в секции ниже'
        : ''
  );

  // Objective overlay is open: step 1 (validate) with no validation result yet
  const isObjectiveOverlay = $derived(
    $pipelineCurrentStep === 1 && !$validateData?.result
  );

  // Hide insights panel when there's no data to comment on yet
  const hideInsightsPanel = $derived(
    isObjectiveOverlay ||
    ($pipelineCurrentStep === 0 && !$importData?.file)
  );
</script>

{#if isEconometrica}
  <div class="pipeline-shell">
    <!-- Stepper header with project selector -->
    <div class="pipeline-header">
      <!-- Логотип Aurora AI (левый верхний угол, как на главной) + проект-селектор/чип -->
      <div class="header-left">
        <a href="/" class="pipeline-logo-link" title="На главную" aria-label="На главную">
          <img src="/logo-horizon.png" alt="Aurora AI" class="pipeline-logo" />
        </a>
        {#if $pipelineCurrentStep === 0}
          <div class="project-area">
            <ProjectSelector />
          </div>
        {:else}
          <!-- Keep header layout stable but show a read-only chip after import -->
          <div class="project-area">
            {#if $activeProject}
              <span class="project-chip" title="Активный проект - переключение доступно на шаге «Импорт»">
                <ChartColumn size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> {$activeProject.name}
              </span>
              <button
                class="save-chip-btn"
                onclick={quickSaveArchive}
                disabled={archivingChip}
                title="Сохранить проект как .aurora архив"
                aria-label="Сохранить проект"
              >
                {archivingChip ? '…' : '💾'}
              </button>
              {#if archiveChipMsg}
                <span class="archive-chip-msg" class:err={archiveChipMsg.startsWith('Ошибка')}>
                  {archiveChipMsg}
                </span>
              {/if}
            {/if}
          </div>
        {/if}
      </div>
      <PipelineStepper onNavigate={handleNavigate} />
      <div class="header-right">
        {#if $pipelineCurrentStep >= 1 && !isObjectiveOverlay}
          <button
            class="mode-toggle"
            class:expert={$expertMode}
            onclick={() => expertMode.update(v => !v)}
            title={$expertMode ? 'Переключить в режим маркетолога' : 'Переключить в экспертный режим'}
          >
            {$expertMode ? 'Эксперт' : 'Маркетолог'}
          </button>
        {/if}
        <button class="header-icon-btn" title="Переключить тему" onclick={toggleTheme}>
          {#if $theme === 'dark'}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          {:else if $theme === 'light'}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
          {:else}
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>
          {/if}
        </button>
        <a href="/settings" class="header-icon-btn" title="Настройки">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </a>
        <button class="header-icon-btn" title="Справка по этому шагу" onclick={openStepHelp}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Body: main content + insights panel -->
    <div class="pipeline-body">
      <main class="pipeline-main" bind:this={mainEl}>
        {@render children()}
      </main>

      <!-- InsightsPanel: shown only when there's data to comment on (not on empty Import, not on Objective overlay) -->
      {#if !hideInsightsPanel}
        <InsightsPanel
          collapsed={insightsCollapsed}
          onToggle={toggleInsights}
        />
      {/if}
    </div>

    <!-- Footer: navigation + C5 sidecar status -->
    <div class="pipeline-footer">
      <button
        class="nav-btn secondary"
        onclick={goBack}
        title={$pipelineCurrentStep === 0 ? 'В главное меню' : 'На предыдущий шаг'}
      >
        ◀ Назад
      </button>

      <div class="footer-center">
        {#if $isComputing}
          <span class="computing-indicator" role="status">
            ⟳ {$computeStatus || 'Обработка...'}
          </span>
        {/if}
      </div>

      <button
        class="nav-btn primary"
        disabled={!canGoNext}
        onclick={goNext}
        title={nextBtnTitle}
      >
        Далее ▶
      </button>

      <!-- C5: Sidecar status dot -->
      <div
        class="sidecar-status"
        class:healthy={$sidecarHealthy}
        class:errored={!$sidecarHealthy && $sidecarStatus !== 'Запуск...'}
        title="Python sidecar: {$sidecarStatus}"
      >
        <span class="sidecar-dot"></span>
        <span class="sidecar-label">Python: {$sidecarStatus || '...'}</span>
      </div>
    </div>
  </div>

  <!-- Phase 2.16 - migration trust-signal toast (visible after schema upgrade) -->
  <MigrationCompletedToast
    show={migrationToast.show}
    fromVersion={migrationToast.fromVersion}
    toVersion={migrationToast.toVersion}
    movedCount={migrationToast.movedCount}
    onDismiss={() => { migrationToast = { ...migrationToast, show: false }; }}
  />

  <!-- H-20a - migration error banner с retry. Раньше ошибки уходили в console.warn -->
  {#if migrationError.show}
    <div class="migration-error-wrap" data-testid="migration-error-banner">
      <ErrorState
        title="Не удалось обновить формат проекта"
        message="Резервная копия project.json сохранена. Попробуйте ещё раз - если ошибка повторится, закройте остальные вкладки и проверьте свободное место на диске."
        severity="error"
        errorCode="MIGRATION_FAILED"
        retryText="Повторить"
        onRetry={retryMigration}
        detailText={migrationError.message}
      />
    </div>
  {/if}
{/if}

<style>
  .migration-error-wrap {
    position: fixed;
    top: 80px;
    right: 24px;
    z-index: 9999;
    max-width: 480px;
    box-shadow: var(--shadow, 0 4px 32px rgba(0,0,0,0.55));
  }

  .pipeline-shell {
    display: flex;
    flex-direction: column;
    /* CLAUDE.md Rule 13: 100%, not 100vh */
    height: 100%;
    overflow: hidden;
  }

  .pipeline-header {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 16px;
    flex-shrink: 0;
  }
  .pipeline-header > :global(*:nth-child(1)) { justify-self: start; }
  .pipeline-header > :global(*:nth-child(2)) { justify-self: center; }
  .pipeline-header > :global(*:nth-child(3)) { justify-self: end; }

  .header-left {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
  }
  .pipeline-logo-link {
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    line-height: 0;
  }
  .pipeline-logo {
    height: 65px;
    width: auto;
    user-select: none;
    pointer-events: none;
  }

  .project-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    font-size: 12px;
    color: var(--text-secondary);
    background: var(--bg-surface-quiet);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm, 6px);
    cursor: default;
    white-space: nowrap;
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .project-area {
    flex-shrink: 0;
    min-width: 260px;
    max-width: 460px;
    padding: 8px 0 8px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: nowrap;
  }

  .save-chip-btn {
    flex-shrink: 0;
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm, 6px);
    color: var(--text-secondary);
    font-size: 14px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .save-chip-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 12%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 45%, transparent);
    color: var(--accent-primary, #3b82f6);
  }
  .save-chip-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .archive-chip-msg {
    font-size: 11px;
    color: var(--success, #22c55e);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 180px;
  }
  .archive-chip-msg.err { color: var(--danger, #ef4444); }

  .header-right {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-right: 16px;
    flex-shrink: 0;
  }

  .header-icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    color: var(--text-muted, #94a3b8);
    border-radius: var(--radius-sm, 6px);
    transition: all 0.15s;
    text-decoration: none;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
  }
  .header-icon-btn:hover {
    color: var(--text-primary, #e2e8f0);
    background: var(--bg-tertiary, rgba(255,255,255,0.06));
  }

  .mode-toggle {
    padding: 5px 14px;
    min-width: 100px;
    text-align: center;
    border-radius: 14px;
    border: 1px solid color-mix(in srgb, var(--accent-primary) 35%, transparent);
    background: color-mix(in srgb, var(--accent-primary) 10%, transparent);
    color: var(--accent);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.03em;
    cursor: pointer;
    transition: all 0.25s;
  }
  .mode-toggle:hover { background: color-mix(in srgb, var(--accent-primary) 18%, transparent); }
  .mode-toggle.expert {
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    border-color: color-mix(in srgb, var(--danger) 40%, transparent);
    color: var(--danger);
  }
  .mode-toggle.expert:hover { background: color-mix(in srgb, var(--danger) 20%, transparent); }

  .pipeline-body {
    flex: 1;
    display: flex;
    overflow: hidden;
    min-height: 0;
  }

  .pipeline-main {
    flex: 1;
    overflow: auto;
    position: relative;
    min-width: 0;
  }

  .pipeline-footer {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 24px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    flex-shrink: 0;
  }

  .footer-center {
    flex: 1;
    display: flex;
    justify-content: center;
    min-width: 0;
  }

  .computing-indicator {
    font-size: 12px;
    color: var(--accent-primary, #3b82f6);
  }
  /* H-13: pulse-анимация только при no-preference (INV-12).
     Reduced-motion users видят static indicator без визуального мерцания.
     Training может занимать 20-60s - без guard'a вестибулярные нарушения
     получают непрерывную раздражающую анимацию. */
  @media (prefers-reduced-motion: no-preference) {
    .computing-indicator {
      animation: pulse 1.5s ease-in-out infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.45; }
    }
  }

  .nav-btn {
    padding: 7px 18px;
    border-radius: 8px;
    border: none;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
    flex-shrink: 0;
  }
  .nav-btn.primary {
    background: var(--accent-primary, #3b82f6);
    color: #fff;
  }
  .nav-btn.primary:hover:not(:disabled) { background: #2563eb; }
  .nav-btn.secondary {
    background: rgba(255,255,255,0.07);
    color: var(--text-secondary, #94a3b8);
  }
  .nav-btn.secondary:hover:not(:disabled) { background: rgba(255,255,255,0.12); }
  .nav-btn:disabled { opacity: var(--disabled-opacity, 0.32); cursor: not-allowed; }

  /* C5: Sidecar status */
  .sidecar-status {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-shrink: 0;
    margin-left: auto;
  }
  .sidecar-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: rgba(148,163,184,0.35);
    transition: background 0.3s, box-shadow 0.3s;
    flex-shrink: 0;
  }
  .sidecar-status.healthy .sidecar-dot {
    background: var(--success, #22c55e);
    box-shadow: 0 0 5px color-mix(in srgb, var(--success) 40%, transparent);
  }
  .sidecar-status.errored .sidecar-dot {
    background: var(--error, #ef4444);
  }
  .sidecar-label {
    font-size: 11px;
    color: var(--text-muted);
    white-space: nowrap;
  }
</style>
