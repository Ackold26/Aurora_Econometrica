<script>
  /**
   * Trust Banner (Trust Level 1).
   * Жёлтый информационный банер, который показывается когда backend вернул
   * smell_flags - ROI > 50×, большой spread или каналы в не-денежных единицах
   * (TRPs, показы, охват). Помогает пользователю честно интерпретировать MMM
   * и не терять доверие к модели, если числа выглядят странно.
   * @component TrustBanner
   * @typedef {{ type: string, channel?: string, channels?: string[], value?: number, severity?: string }} Flag
   */
  import { pipelineCurrentStep } from '$lib/project-state.js';
  import { TriangleAlert } from 'lucide-svelte';

  /** @type {{ flags: Flag[] }} */
  let { flags } = $props();

  /** Переход на шаг Валидация (index 1 в pipeline). */
  function goToValidate() {
    pipelineCurrentStep.set(1);
  }

  const hasRoiMax = $derived(flags?.some((f) => f.type === 'roi_max'));
  const hasSpread = $derived(flags?.some((f) => f.type === 'roi_spread'));
  const unitFlag = $derived(flags?.find((f) => f.type === 'unit_smell'));
  const unitChannels = $derived(unitFlag?.channels ?? []);

  let expanded = $state(false);
</script>

{#if flags && flags.length > 0}
  <div class="trust-banner">
    <div class="row">
      <span class="icon"><TriangleAlert size={16} strokeWidth={1.5} /></span>
      <div class="body">
        <div class="title">Внимание: результаты требуют интерпретации</div>
        <div class="reasons">
          {#if hasRoiMax || hasSpread}
            <span class="chip">Экстремальный ROI{hasSpread ? ' / большой разброс' : ''}</span>
          {/if}
          {#if unitChannels.length > 0}
            <span class="chip">Не-денежные единицы: {unitChannels.slice(0, 3).join(', ')}{unitChannels.length > 3 ? '…' : ''}</span>
          {/if}
        </div>
      </div>
      <button class="btn-toggle" onclick={() => (expanded = !expanded)}>
        {expanded ? 'Свернуть' : 'Как читать'} {expanded ? '▲' : '▼'}
      </button>
    </div>

    {#if expanded}
      <div class="details">
        <div class="section">
          <div class="section-title">Возможные причины</div>
          <ul>
            <li><b>Смешанные единицы.</b> Каналы в TRPs/охвате/показах не сравнимы с рублями - ROI становится математическим артефактом.</li>
            <li><b>Brand-эффект.</b> Охватные каналы (TV/TRPs/OOH) работают на долгосрочную базу, не только на короткий инкремент. Модель может приписывать им «инкремент», хотя это сдвиг базы.</li>
            <li><b>Корреляция каналов.</b> Бренд и performance часто идут параллельно - на малых данных модель не может надёжно разделить их вклад.</li>
          </ul>
        </div>
        <div class="section">
          <div class="section-title">Как читать модель честно</div>
          <ul>
            <li>Сравнивай ROI <b>только внутри одной группы единиц</b> (рубли с рублями, TRPs с TRPs).</li>
            <li>Каналы охвата интерпретируй как <b>«вклад в базу + короткий эффект»</b>, а не чистый инкремент.</li>
            <li>Доверяй <b>Δ-распределение</b> (что куда переложить) - оно надёжнее точечных ROI.</li>
            <li>Доли вклада в % - правдоподобнее, чем абсолютные ROI.</li>
            <li>Если видишь «ROI завышен (не рубли?)» - <button class="link-btn" type="button" onclick={goToValidate}>вернись на шаг Валидация</button> и задай стоимость юнита (CPP/CPM). Декомпозиция пересчитается автоматически.</li>
          </ul>
        </div>
      </div>
    {/if}
  </div>
{/if}

<style>
  .trust-banner {
    background: color-mix(in srgb, var(--warning, #f59e0b) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #f59e0b) 30%, transparent);
    border-radius: 10px;
    padding: 12px 14px;
  }
  .row { display: flex; align-items: flex-start; gap: 10px; }
  .icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; color: var(--warning, #f59e0b); }
  .body { flex: 1; min-width: 0; }
  .title { font-size: 13px; font-weight: 600; color: var(--text-primary, #e2e8f0); }
  .reasons { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--warning, #f59e0b) 14%, transparent);
    color: var(--text-secondary, #94a3b8);
    border: 1px solid color-mix(in srgb, var(--warning, #f59e0b) 25%, transparent);
  }
  .btn-toggle {
    flex-shrink: 0;
    background: transparent;
    border: 1px solid color-mix(in srgb, var(--warning, #f59e0b) 35%, transparent);
    color: var(--warning, #f59e0b);
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    padding: 4px 10px;
    cursor: pointer;
  }
  .btn-toggle:hover { background: color-mix(in srgb, var(--warning, #f59e0b) 12%, transparent); }

  .details {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px dashed color-mix(in srgb, var(--warning, #f59e0b) 25%, transparent);
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  @media (max-width: 900px) { .details { grid-template-columns: 1fr; } }
  .section-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary, #94a3b8);
    margin-bottom: 6px;
  }
  ul { margin: 0; padding-left: 18px; font-size: 12px; color: var(--text-secondary, #94a3b8); line-height: 1.55; }
  li { margin-bottom: 4px; }
  b { color: var(--text-primary, #e2e8f0); font-weight: 600; }
  .link-btn {
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    color: var(--warning, #f59e0b);
    font-weight: 600;
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }
  .link-btn:hover { color: var(--accent-primary, #3b82f6); }
</style>
