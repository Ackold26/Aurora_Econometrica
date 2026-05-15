<script>
  import { onMount } from 'svelte';

  let time = $state('');

  function update() {
    time = new Date().toLocaleTimeString('ru-RU', {
      timeZone: 'Europe/Moscow',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }

  onMount(() => {
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  });
</script>

<span class="clock" title="Московское время (МСК)">{time}</span>

<style>
  .clock {
    font-family: var(--font-mono, 'Consolas', monospace);
    font-size: 12px;
    font-weight: 500;
    color: var(--clock-color, #CCFF00);
    letter-spacing: 0.06em;
    opacity: 0.85;
    user-select: none;
    animation: clock-tick 1s step-end infinite;
  }

  @keyframes clock-tick {
    from { opacity: 0.75; }
    to   { opacity: 0.9; }
  }

  /* v2.1.0 п.5.6: steady opacity for clock */
  @media (prefers-reduced-motion: reduce) {
    .clock {
      opacity: 0.85;
    }
  }
</style>
