/**
 * Rule-Based Insights Engine (Tier 1 — offline, always works).
 * Generates contextual recommendations from pipeline data without API calls.
 * Covers ~80% of insight value at 0% cost.
 *
 * @module insights-rules
 */

/**
 * @typedef {Object} Insight
 * @property {'info'|'success'|'warning'|'error'} severity
 * @property {string} text
 * @property {string} [tip]
 */

// ── Import Step ─────────────────────────────────────────

/**
 * @param {{ rows: number, cols: number, columns: any[], zeros: Record<string, number> }} data
 * @returns {Insight[]}
 */
export function importInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data) return out;

  const { rows, cols, columns, zeros } = data;

  if (rows < 26) {
    out.push({ severity: 'warning', text: `Мало данных: ${rows} наблюдений. Для стабильной модели рекомендуется минимум 52 недели.`, tip: 'Байесовская модель может работать с малыми выборками, но доверительные интервалы будут широкими.' });
  } else if (rows >= 104) {
    out.push({ severity: 'success', text: `${rows} наблюдений — отличный объём данных для MMM.` });
  } else {
    out.push({ severity: 'info', text: `${rows} наблюдений, ${cols} столбцов.` });
  }

  const mediaCount = columns?.filter(c => c.role === 'media').length ?? 0;
  if (mediaCount > 8) {
    out.push({ severity: 'warning', text: `${mediaCount} медиаканалов — много. Рассмотрите объединение мелких каналов.`, tip: 'Чем больше каналов, тем больше параметров оценивает модель. При малом объёме данных это снижает точность.' });
  }

  if (zeros) {
    for (const [col, pct] of Object.entries(zeros)) {
      if (pct > 80) {
        out.push({ severity: 'warning', text: `Столбец «${col}» на ${pct.toFixed(0)}% состоит из нулей — модель может не найти значимый эффект.` });
      }
    }
  }

  return out;
}

// ── Validate Step ───────────────────────────────────────

/**
 * @param {{ status: string, warnings: any[], correlations: Record<string, Record<string, number>>, columns: any[] }} result
 * @returns {Insight[]}
 */
export function validateInsights(result) {
  /** @type {Insight[]} */
  const out = [];
  if (!result) return out;

  if (result.status === 'ok') {
    out.push({ severity: 'success', text: 'Данные прошли валидацию без критических проблем.' });
  }

  // High correlation pairs
  if (result.correlations) {
    const seen = new Set();
    for (const [a, row] of Object.entries(result.correlations)) {
      for (const [b, r] of Object.entries(row)) {
        if (a === b) continue;
        const key = [a, b].sort().join('|');
        if (seen.has(key)) continue;
        seen.add(key);
        const absR = Math.abs(/** @type {number} */ (r));
        if (absR > 0.85) {
          out.push({ severity: 'warning', text: `Мультиколлинеарность: ${a} и ${b} (r=${absR.toFixed(2)}). Модель может не разделить их вклады.`, tip: 'Рассмотрите исключение одного из каналов или объединение в группу. В expert mode доступна VIF-таблица.' });
        }
      }
    }
  }

  // Missing values
  const missing = result.columns?.filter(c => c.stats?.missing_pct > 5) ?? [];
  if (missing.length > 0) {
    const names = missing.map(c => c.name).join(', ');
    out.push({ severity: 'warning', text: `Пропуски >5% в столбцах: ${names}. Модель будет менее точной.`, tip: 'Интерполяция заполнит небольшие пропуски. Для больших — рассмотрите дополнительные источники данных.' });
  }

  return out;
}

// ── Model Step ──────────────────────────────────────────

/**
 * @param {{ diagnostics: { mqs: { score: number, tier_label: string }, r_squared: number, mape: number, r_hat: number, divergences: number }, channelParams: Record<string, any> }} data
 * @returns {Insight[]}
 */
export function modelInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data?.diagnostics) return out;

  const d = data.diagnostics;
  const mqs = d.mqs?.score ?? 0;
  const label = d.mqs?.tier_label ?? '';

  if (mqs >= 80) {
    out.push({ severity: 'success', text: `MQS = ${mqs.toFixed(0)} (${label}) — высокое качество модели. Результаты надёжны для принятия решений.` });
  } else if (mqs >= 60) {
    out.push({ severity: 'info', text: `MQS = ${mqs.toFixed(0)} (${label}) — приемлемое качество. Рассмотрите добавление контрольных переменных для улучшения.` });
  } else {
    out.push({ severity: 'warning', text: `MQS = ${mqs.toFixed(0)} (${label}) — модель требует доработки.`, tip: 'Попробуйте: добавить промо-переменные, увеличить draws, проверить качество данных.' });
  }

  if (d.r_hat > 1.05) {
    out.push({ severity: 'error', text: `R-hat = ${d.r_hat.toFixed(3)} — MCMC цепи не сошлись. Результаты ненадёжны.`, tip: 'Увеличьте количество draws (2000+) и tune (1000+). Если не помогает — упростите модель (меньше каналов).' });
  } else if (d.r_hat > 1.01) {
    out.push({ severity: 'warning', text: `R-hat = ${d.r_hat.toFixed(3)} — цепи почти сошлись. Рассмотрите увеличение draws.` });
  }

  if (d.mape > 15) {
    out.push({ severity: 'warning', text: `MAPE = ${d.mape.toFixed(1)}% — модель объясняет тренд, но не улавливает краткосрочные скачки.`, tip: 'Добавьте промо-переменные (акции, праздники) как контрольные факторы.' });
  }

  if (d.r_squared < 0.5) {
    out.push({ severity: 'warning', text: `R² = ${d.r_squared.toFixed(3)} — модель объясняет менее 50% вариации. Добавьте контрольные переменные.` });
  } else if (d.r_squared >= 0.8) {
    out.push({ severity: 'success', text: `R² = ${d.r_squared.toFixed(3)} — модель объясняет ${(d.r_squared * 100).toFixed(0)}% вариации продаж.` });
  }

  if (d.divergences > 0) {
    out.push({ severity: 'warning', text: `${d.divergences} дивергенций в MCMC. Модель может быть нестабильна.`, tip: 'Увеличьте target_accept (0.9→0.95) или tune. Дивергенции означают, что сэмплер не смог исследовать всё пространство параметров.' });
  }

  return out;
}

// ── Decompose Step ──────────────────────────────────────

/**
 * @param {{ base_pct: number, channels: Array<{ name: string, contribution_pct: number, spend: number, roi: number }> }} data
 * @returns {Insight[]}
 */
export function decomposeInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data) return out;

  if (data.base_pct > 80) {
    out.push({ severity: 'info', text: `Base sales = ${data.base_pct.toFixed(0)}% — большинство продаж органические. Медиа-эффект относительно слабый.`, tip: 'Это может означать сильный бренд (хорошо) или что модель не смогла уловить медиа-эффект (проверьте adstock).' });
  } else if (data.base_pct < 40) {
    out.push({ severity: 'info', text: `Base sales = ${data.base_pct.toFixed(0)}% — бренд сильно зависит от рекламы. Остановка медиа может привести к значительному падению.` });
  }

  if (!data.channels?.length) return out;

  // Spend share vs effect share divergence
  const totalSpend = data.channels.reduce((s, c) => s + (c.spend || 0), 0);
  const totalEffect = data.channels.reduce((s, c) => s + (c.contribution_pct || 0), 0);

  for (const ch of data.channels) {
    if (!totalSpend || !totalEffect) continue;
    const spendShare = ch.spend / totalSpend;
    const effectShare = (ch.contribution_pct || 0) / totalEffect;
    if (spendShare > 0.15 && effectShare > 0 && spendShare / effectShare > 2.5) {
      out.push({ severity: 'warning', text: `${ch.name}: ${(spendShare * 100).toFixed(0)}% бюджета, но лишь ${(effectShare * 100).toFixed(0)}% эффекта. ROI ниже среднего.` });
    }
    if (effectShare > 0.15 && spendShare > 0 && effectShare / spendShare > 2) {
      out.push({ severity: 'success', text: `${ch.name}: ${(effectShare * 100).toFixed(0)}% эффекта при ${(spendShare * 100).toFixed(0)}% бюджета — высокоэффективный канал.` });
    }
  }

  // Top/bottom ROI
  const sorted = [...data.channels].sort((a, b) => (b.roi || 0) - (a.roi || 0));
  if (sorted.length >= 2) {
    const top = sorted[0];
    const bottom = sorted[sorted.length - 1];
    if (top.roi > 2) {
      out.push({ severity: 'success', text: `Лучший канал по ROI: ${top.name} (${top.roi.toFixed(1)}x).` });
    }
    if (bottom.roi < 1 && bottom.roi > 0) {
      out.push({ severity: 'warning', text: `${bottom.name}: ROI = ${bottom.roi.toFixed(1)}x — расходы превышают вклад. Рассмотрите сокращение.` });
    }
  }

  return out;
}

// ── Optimize Step ───────────────────────────────────────

/**
 * @param {{ expected_lift_pct: number, total_budget: number, channels: Array<{ name: string, current_spend: number, optimal_spend: number }> }} data
 * @returns {Insight[]}
 */
export function optimizeInsights(data) {
  /** @type {Insight[]} */
  const out = [];
  if (!data) return out;

  const lift = data.expected_lift_pct ?? 0;

  if (lift > 15) {
    out.push({ severity: 'success', text: `Потенциальный рост: +${lift.toFixed(1)}% — значительный потенциал оптимизации.`, tip: 'Перераспределите бюджет согласно оптимальному плану. Рекомендуется пилотный период 4-6 недель.' });
  } else if (lift > 5) {
    out.push({ severity: 'info', text: `Потенциальный рост: +${lift.toFixed(1)}% — умеренный потенциал. Текущее распределение неплохое, но можно улучшить.` });
  } else if (lift > 0) {
    out.push({ severity: 'info', text: `Потенциальный рост: +${lift.toFixed(1)}% — текущее распределение уже близко к оптимальному.` });
  }

  if (!data.channels?.length) return out;

  // Biggest changes
  const changes = data.channels
    .map(ch => ({ name: ch.name, delta: (ch.optimal_spend - ch.current_spend), deltaPct: ch.current_spend > 0 ? (ch.optimal_spend - ch.current_spend) / ch.current_spend * 100 : 0 }))
    .sort((a, b) => Math.abs(b.deltaPct) - Math.abs(a.deltaPct));

  const biggest = changes[0];
  if (biggest && Math.abs(biggest.deltaPct) > 20) {
    const dir = biggest.deltaPct > 0 ? 'увеличить' : 'сократить';
    out.push({ severity: 'info', text: `Главное изменение: ${dir} ${biggest.name} на ${Math.abs(biggest.deltaPct).toFixed(0)}%.` });
  }

  return out;
}
