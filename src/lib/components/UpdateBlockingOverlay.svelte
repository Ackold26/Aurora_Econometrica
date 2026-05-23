<script>
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import { updateRequired } from '$lib/store.js';
  import AetherLogo from './AetherLogo.svelte';

  /** @type {'idle'|'downloading'|'installing'|'error'} */
  let updateState = $state('idle');
  let progress = $state(0);
  let errorMsg = $state('');

  let noUrl = $state(false);

  async function startUpdate() {
    let info = $updateRequired;

    // If URL is missing, try fetching full manifest
    if (!info.url) {
      try {
        const fullInfo = /** @type {any} */ (await invoke('check_update'));
        if (fullInfo && fullInfo.download_url) {
          updateRequired.set({
            required: true,
            url: fullInfo.download_url,
            version: fullInfo.version || info.version,
            notes: fullInfo.release_notes || info.notes,
            checksum: fullInfo.checksum || null,
          });
          info = { ...info, url: fullInfo.download_url, checksum: fullInfo.checksum || null };
        }
      } catch { /* failed to fetch manifest */ }
    }

    if (!info.url) {
      noUrl = true;
      return;
    }

    noUrl = false;
    updateState = 'downloading';
    progress = 0;
    errorMsg = '';

    const unlisten = await listen('update-progress', (event) => {
      const data = /** @type {{percent: number}} */ (event.payload);
      progress = data.percent;
    });

    try {
      const installerPath = await invoke('download_update', {
        url: info.url,
        checksum: info.checksum || '',
      });
      unlisten();
      updateState = 'installing';
      await invoke('apply_update', { installerPath });
    } catch (err) {
      unlisten();
      updateState = 'error';
      errorMsg = String(err);
    }
  }
</script>

{#if $updateRequired.required}
  <div class="overlay">
    <div class="card">
      <div class="logo-wrap">
        <AetherLogo />
      </div>

      <h2 class="title">Требуется обновление</h2>

      {#if $updateRequired.version}
        <p class="version">Версия {$updateRequired.version}</p>
      {/if}

      {#if $updateRequired.notes}
        <p class="notes">{$updateRequired.notes}</p>
      {/if}

      {#if updateState === 'idle'}
        <p class="hint">Для продолжения работы необходимо установить обновление.</p>
        {#if noUrl}
          <p class="error-text">Не удалось получить ссылку на обновление. Проверьте подключение к интернету и перезапустите приложение.</p>
        {/if}
        <button class="update-btn" onclick={startUpdate}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          {noUrl ? 'Повторить' : 'Скачать и установить'}
        </button>
      {:else if updateState === 'downloading'}
        <div class="progress-section">
          <p class="progress-label">Скачивание... {Math.round(progress)}%</p>
          <div class="progress-track">
            <div class="progress-fill" style="width: {progress}%"></div>
          </div>
        </div>
      {:else if updateState === 'installing'}
        <div class="progress-section">
          <div class="spinner"></div>
          <p class="progress-label">Установка... Приложение перезапустится</p>
        </div>
      {:else if updateState === 'error'}
        <p class="error-text">{errorMsg}</p>
        <button class="update-btn retry" onclick={startUpdate}>
          Повторить
        </button>
      {/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--overlay-bg);
    backdrop-filter: var(--blur-focus);
    -webkit-backdrop-filter: var(--blur-focus);
  }

  .card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    padding: 40px 48px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow), var(--shadow-glow);
    max-width: 420px;
    text-align: center;
  }

  .logo-wrap {
    margin-bottom: 4px;
    opacity: 0.9;
  }

  .title {
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
  }

  .version {
    font-size: 13px;
    color: var(--accent-primary);
    font-weight: 600;
    background: var(--accent-glow);
    padding: 3px 12px;
    border-radius: 20px;
  }

  .notes {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.5;
  }

  .hint {
    font-size: 12.5px;
    color: var(--text-muted);
    margin-top: 4px;
  }

  .update-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 28px;
    background: var(--gradient-primary);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-sm);
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    margin-top: 8px;
    transition: all var(--transition);
    box-shadow: var(--shadow-glow);
  }

  .update-btn:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-glow);
    filter: brightness(1.1);
  }

  .update-btn.retry {
    background: color-mix(in srgb, var(--danger) 15%, transparent);
    color: var(--danger);
    border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
    box-shadow: none;
  }

  .update-btn.retry:hover {
    background: color-mix(in srgb, var(--danger) 25%, transparent);
    transform: none;
    filter: none;
  }

  .progress-section {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    width: 100%;
    margin-top: 8px;
  }

  .progress-label {
    font-size: 13px;
    color: var(--text-secondary);
    font-weight: 500;
  }

  .progress-track {
    width: 100%;
    height: 6px;
    background: var(--bg-tertiary);
    border-radius: 3px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary));
    border-radius: 3px;
    transition: width 0.3s ease;
  }

  .spinner {
    width: 28px;
    height: 28px;
    border: 3px solid var(--border);
    border-top-color: var(--accent-primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  .error-text {
    font-size: 12.5px;
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    padding: 8px 14px;
    border-radius: 6px;
    border: 1px solid color-mix(in srgb, var(--danger) 15%, transparent);
    word-break: break-word;
  }

  /* v2.1.0 п.5.6: static spinner ring */
  @media (prefers-reduced-motion: reduce) {
    .spinner {
      border-color: var(--accent-primary);
    }
  }
</style>
