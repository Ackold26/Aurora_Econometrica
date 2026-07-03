/**
 * E1 (2026-07-03): BacktestCard — карточка «Проверка на истории».
 *
 * Контракт: мгновенное чтение сохранённой витрины (read_only) при монтировании;
 * запуск пересчёта кнопкой с честным предупреждением о времени; вердикты
 * validated/coverage_low/worse_than_naive/insufficient — включая нелестные;
 * пометка устаревания при переобучении модели после проверки.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { activeProjectId } from '$lib/project-state.js';
import BacktestCard from '$lib/components/pipeline/BacktestCard.svelte';

/** Минимальная валидная витрина (как отдаёт /compute/backtest). */
function vitrinaFixture(overrides = {}) {
  return {
    status: 'ok',
    verdict: 'validated',
    verdict_text: 'Модель подтверждена на удержанной истории: MAPE 6.1%.',
    granularity: 'M',
    horizon_periods: 3,
    mode: 'ols',
    n_windows: 4,
    windows_hit_total: 3,
    windows_with_interval: 4,
    coverage_per_window: 0.75,
    coverage_per_period: 0.9167,
    n_holdout_points: 12,
    n_holdout_points_with_interval: 12,
    mape_model: 6.1,
    naive_mape: { naive_last: 9.4, seasonal_naive: 8.2 },
    mape_naive_best: 8.2,
    naive_best_name: 'seasonal_naive',
    pi_method: 'conformal_90',
    pi_level: 0.9,
    generated_at: '2026-07-03T10:00:00+00:00',
    model_trained_at: '2026-07-03T09:00:00+00:00',
    model_trained_at_current: '2026-07-03T09:00:00+00:00',
    windows: [
      {
        window: '2025-01-31 — 2025-03-31', train_periods: 24, test_periods: 3,
        actual_total: 3100, predicted_total: 2950,
        pi_low_total: 2700, pi_high_total: 3250, hit_total: true, mape: 5.2,
        per_period: [],
      },
      {
        window: '2025-04-30 — 2025-06-30', train_periods: 27, test_periods: 3,
        actual_total: 3400, predicted_total: 2900,
        pi_low_total: 2650, pi_high_total: 3150, hit_total: false, mape: 8.9,
        per_period: [],
      },
    ],
    ...overrides,
  };
}

/**
 * Мок-маршрутизатор invoke: project_get_dir → путь; econ_backtest —
 * readOnly-ветка и полный запуск раздельно.
 */
function mockInvoke({ saved = { status: 'not_found' }, run = vitrinaFixture() } = {}) {
  vi.mocked(invoke).mockImplementation(async (cmd, args) => {
    if (cmd === 'project_get_dir') return 'C:/fake/project';
    if (cmd === 'econ_backtest') {
      if (/** @type {any} */ (args)?.readOnly) return saved;
      if (run instanceof Error) throw run;
      return run;
    }
    return null;
  });
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  activeProjectId.set('p-test');
});

describe('BacktestCard — чтение сохранённой витрины', () => {
  it('монтирование с сохранённой витриной → done: вердикт, герой «3 из 4», MAPE', async () => {
    mockInvoke({ saved: vitrinaFixture() });
    render(BacktestCard);
    await waitFor(() => {
      expect(screen.getByTestId('bt-verdict')).toHaveTextContent('Модель подтверждена на истории');
    });
    expect(screen.getByTestId('bt-hero')).toHaveTextContent('3 из 4');
    expect(screen.getByText(/кварталов — факт внутри 90%-интервала/)).toBeInTheDocument();
    expect(screen.getByText(/наивный прогноз: 8.2%/)).toBeInTheDocument();
    // Устаревания нет: model_trained_at == model_trained_at_current
    expect(screen.queryByText(/результат устарел/)).not.toBeInTheDocument();
  });

  it('витрины нет → empty с кнопкой и честным предупреждением о времени', async () => {
    mockInvoke({ saved: { status: 'not_found' } });
    render(BacktestCard);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Проверить модель на истории' })).toBeInTheDocument();
    });
    expect(screen.getByText(/несколько минут/)).toBeInTheDocument();
  });

  it('модель переобучена после проверки → жёлтая пометка устаревания', async () => {
    mockInvoke({
      saved: vitrinaFixture({ model_trained_at_current: '2026-07-03T12:00:00+00:00' }),
    });
    render(BacktestCard);
    await waitFor(() => {
      expect(screen.getByText(/результат устарел/)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Обновить' })).toBeInTheDocument();
  });

  it('нелестный вердикт worse_than_naive показан честно (tone bad)', async () => {
    mockInvoke({
      saved: vitrinaFixture({
        verdict: 'worse_than_naive',
        verdict_text: 'Модель на удержанной истории точна как наивный прогноз или хуже.',
      }),
    });
    render(BacktestCard);
    await waitFor(() => {
      expect(screen.getByTestId('bt-verdict')).toHaveTextContent('Модель не точнее наивного прогноза');
    });
    expect(screen.getByTestId('bt-verdict').classList.contains('bt-bad')).toBe(true);
  });

  it('нестандартный горизонт → слово «окон проверки», не «кварталов»', async () => {
    mockInvoke({ saved: vitrinaFixture({ horizon_periods: 4 }) });
    render(BacktestCard);
    await waitFor(() => {
      expect(screen.getByText(/окон проверки — факт внутри/)).toBeInTheDocument();
    });
  });
});

describe('BacktestCard — запуск проверки', () => {
  it('кнопка → running → done с вердиктом', async () => {
    mockInvoke({ saved: { status: 'not_found' }, run: vitrinaFixture() });
    render(BacktestCard);
    const btn = await screen.findByRole('button', { name: 'Проверить модель на истории' });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByTestId('bt-verdict')).toBeInTheDocument();
    });
    expect(screen.getByTestId('bt-hero')).toHaveTextContent('3 из 4');
  });

  it('insufficient → честная плашка «истории недостаточно», не ошибка', async () => {
    mockInvoke({
      saved: { status: 'not_found' },
      run: { status: 'insufficient', message: 'Истории недостаточно для проверки: окон 1 (нужно ≥ 3).' },
    });
    render(BacktestCard);
    const btn = await screen.findByRole('button', { name: 'Проверить модель на истории' });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByText(/Истории недостаточно/)).toBeInTheDocument();
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('сбой запуска → alert с текстом и кнопкой «Повторить»', async () => {
    mockInvoke({ saved: { status: 'not_found' }, run: new Error('sidecar недоступен') });
    render(BacktestCard);
    const btn = await screen.findByRole('button', { name: 'Проверить модель на истории' });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('sidecar недоступен');
    });
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('таблица окон в details: подписи периодов и попадание ✓/✕', async () => {
    mockInvoke({ saved: vitrinaFixture() });
    render(BacktestCard);
    await waitFor(() => {
      expect(screen.getByText(/Окна проверки \(4\)/)).toBeInTheDocument();
    });
    expect(screen.getByText('2025-01-31 — 2025-03-31')).toBeInTheDocument();
    const hits = Array.from(document.querySelectorAll('.bt-hit')).map((el) => el.textContent);
    expect(hits).toContain('✓');
    expect(hits).toContain('✕');
  });
});
