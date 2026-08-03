<script>
  /**
   * BrandChip — фирменный чип названия приложения (левый верхний угол).
   * Стандарт Aurora Core (эталон Creative Hub .brand-rosst): чип-бейдж с
   * accent-рамкой + accent-фоном + accent-текстом (electric-blue в dark, адаптив
   * под тему). Логотип Aurora Horizon (крупный) + название в две строки.
   * Название — английским (по требованию): ECONOMETRICA / MMM OPTIMIZER.
   * Токены — локальные Эконометрики (Aether Mesh), без хардкода hex.
   */
</script>

<div class="brand-chip">
  <img src="/logo-horizon.png" alt="Aurora AI" class="brand-chip-logo" />
  <div class="brand-chip-text">
    <span class="brand-chip-product">Econometrica</span>
    <span class="brand-chip-sub">MMM Optimizer</span>
  </div>
</div>

<style>
  .brand-chip {
    display: inline-flex;
    align-items: center;
    gap: 10px;
  }

  /* Логотип Horizon — крупный, как на главной (размер 87px). */
  .brand-chip-logo {
    height: 87px;
    width: auto;
    display: block;
  }

  /* Чип-бейдж electric-blue (стандарт Aurora Core, эталон Creative Hub .brand-rosst):
     accent-рамка + accent-фон + accent-текст, адаптируется под тему. Две строки. */
  .brand-chip-text {
    display: flex;
    flex-direction: column;
    gap: 1px;
    line-height: 1.15;
    padding: 5px 12px;
    color: var(--accent-primary);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 40%, transparent);
    background: color-mix(in srgb, var(--accent-primary) 8%, transparent);
    border-radius: var(--radius-chip, 8px);
  }

  .brand-chip-product {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: var(--accent-primary);
    text-transform: uppercase;
  }

  .brand-chip-sub {
    font-size: 9.5px;
    font-weight: 600;
    letter-spacing: 0.16em;
    color: color-mix(in srgb, var(--accent-primary) 72%, var(--text-secondary));
    text-transform: uppercase;
  }
</style>
