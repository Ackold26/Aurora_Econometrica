<script>
  import { invoke } from '@tauri-apps/api/core';
  import { activeCabinet, isLoading, pendingCommand } from '$lib/store.js';

  /** @type {Array<{group: string, label: string, command: string}>} */
  let commands = $state([]);
  let searchQuery = $state('');
  let viewMode = $state('grid'); // 'grid' or 'list'

  /** @type {string|undefined} */
  let lastCabinetId = $state('__init__');
  $effect(() => {
    const cabinetId = $activeCabinet?.id;
    if (cabinetId === lastCabinetId) return;
    lastCabinetId = cabinetId;
    if (!cabinetId) { commands = []; return; }
    invoke('get_cabinet_commands', { cabinetId }).then((cmds) => {
      commands = /** @type {typeof commands} */ (cmds);
    }).catch(() => { commands = []; });
  });

  let filtered = $derived(
    searchQuery.trim()
      ? commands.filter(c =>
          c.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
          c.command.toLowerCase().includes(searchQuery.toLowerCase()))
      : commands
  );

  /** @param {string} command */
  function executeCommand(command) {
    if ($isLoading) return;
    pendingCommand.set(command);
  }

  // Command descriptions for enriched display
  /** @type {Record<string, string>} */
  const descriptions = {
    '/write': 'Полный цикл генерации текста',
    '/adapt': 'Адаптация под бренд/формат/ЦА',
    '/audit': 'Оценка ToV + метрики + правки',
    '/pack': 'Одно ядро -> все каналы',
    '/mine': 'Извлечение голоса клиента',
    '/brand-setup': 'Настройка бренд-профиля',
    '/format-add': 'Свой тип текста',
    '/visual': 'Полный цикл визуала',
    '/edit': 'Правки существующего',
    '/logo': '3-5 концепций логотипа',
    '/identity': 'Паттерны, палитры, типографика',
    '/packaging': 'Дизайн упаковки продукта',
    '/brand-visual': 'Визуальный DNA из материалов',
    '/storyboard': 'Раскадровка видеоролика',
    '/strategy': 'Полный стратегический цикл',
    '/positioning': 'Позиционирование бренда',
    '/brief': 'Креативный бриф (JWT/BBDO)',
    '/messages': 'Messaging framework',
    '/comm-audit': 'Аудит коммуникаций',
    '/cycle': 'Полный креативный цикл (5 фаз)',
    '/creative': 'Быстрая генерация концепций',
    '/ad-variants': '10+ вариантов объявлений',
    '/brand-memory': 'ДНК бренда из материалов',
    '/media-monitor': 'Анализ медиаполя',
    '/sentiment': 'Детальная тональность',
    '/effectiveness': 'Сводный PR-отчёт',
    '/competitors': 'Сравнение с конкурентами',
    '/content-performance': 'Эффективность контента',
    '/strategy-fg': 'Стратегическая фокус-группа',
    '/creative-fg': 'Тест креативных концепций',
    '/copy-test': 'A/B тест текстов',
    '/contract': 'Анализ договора',
    '/qa': 'Проверка рекламы',
  };
</script>

{#if commands.length > 0}
  <div class="gallery" style="--cabinet-color: {$activeCabinet?.color || '#6366f1'}">
    <div class="gallery-header">
      <div class="gallery-search">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input
          class="gallery-input"
          type="text"
          placeholder="Поиск..."
          bind:value={searchQuery}
        />
      </div>
      <div class="view-toggle">
        <button class="toggle-btn" class:toggle-active={viewMode === 'grid'} onclick={() => viewMode = 'grid'} title="Сетка">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
        </button>
        <button class="toggle-btn" class:toggle-active={viewMode === 'list'} onclick={() => viewMode = 'list'} title="Список">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
        </button>
      </div>
    </div>

    <div class="gallery-content" class:gallery-grid={viewMode === 'grid'} class:gallery-list={viewMode === 'list'}>
      {#each filtered as cmd, idx}
        <button
          class="template-card"
          class:template-recommended={idx === 0}
          onclick={() => executeCommand(cmd.command)}
          disabled={$isLoading}
          title={cmd.command}
        >
          {#if idx === 0}
            <span class="recommended-badge">Рекомендуем</span>
          {/if}
          <div class="template-cmd">{cmd.command}</div>
          <div class="template-label">{cmd.label}</div>
          {#if descriptions[cmd.command]}
            <div class="template-desc">{descriptions[cmd.command]}</div>
          {/if}
          <div class="template-group">{cmd.group}</div>
        </button>
      {/each}
    </div>
  </div>
{/if}

<style>
  .gallery {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .gallery-header {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .gallery-search {
    display: flex;
    align-items: center;
    gap: 5px;
    flex: 1;
    padding: 4px 8px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 6px;
    color: var(--text-muted);
  }

  .gallery-input {
    flex: 1;
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 11px;
    outline: none;
  }

  .gallery-input::placeholder { color: var(--text-muted); opacity: 0.5; }

  .view-toggle {
    display: flex;
    gap: 2px;
  }

  .toggle-btn {
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s;
  }

  .toggle-btn:hover { color: var(--text-secondary); }
  .toggle-active { color: var(--text-primary); border-color: rgba(255,255,255,0.1); }

  .gallery-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px;
  }

  .gallery-list {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .template-card {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 10px;
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    cursor: pointer;
    text-align: left;
    color: var(--text-secondary);
    transition: all 0.15s ease;
    position: relative;
  }

  .template-card:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.04);
    border-color: rgba(255, 255, 255, 0.12);
    border-left: 2px solid var(--cabinet-color);
  }

  .template-card:disabled { opacity: 0.3; cursor: default; }

  /* ── Recommended first item ── */

  .template-recommended {
    padding: 12px 14px;
    border-color: rgba(46, 91, 255, 0.2);
    background: rgba(46, 91, 255, 0.03);
  }

  .gallery-grid .template-recommended {
    grid-column: 1 / -1;
  }

  .template-recommended:hover:not(:disabled) {
    border-color: var(--accent-primary);
    background: rgba(46, 91, 255, 0.06);
    border-left: 2px solid var(--accent-primary);
  }

  .recommended-badge {
    position: absolute;
    top: 4px;
    right: 6px;
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--accent-primary);
    background: rgba(46, 91, 255, 0.1);
    padding: 2px 6px;
    border-radius: 4px;
  }

  .template-cmd {
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--cabinet-color);
    font-weight: 500;
  }

  .template-label {
    font-size: 11.5px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .template-desc {
    font-size: 10px;
    color: var(--text-muted);
    line-height: 1.3;
  }

  .gallery-grid .template-desc { display: none; }
  .gallery-grid .template-recommended .template-desc { display: block; }

  .template-group {
    font-size: 9px;
    color: var(--text-muted);
    opacity: 0.5;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 2px;
  }

  .gallery-grid .template-group { display: none; }
</style>
