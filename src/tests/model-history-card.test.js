/**
 * E3 (2026-07-03): ModelHistoryCard — «История модели» (поколения, сравнение,
 * дрейф). Контракт: пустой архив — спокойная строка; дрейф «пора переобучить» —
 * заметная плашка; сравнение — headline + вердикты с CI (включая нелестные).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { activeProjectId } from '$lib/project-state.js';
import ModelHistoryCard from '$lib/components/pipeline/ModelHistoryCard.svelte';

const VERSIONS = [{ timestamp: '20260401_120000', mqs_score: 71, n_channels: 2 }];

function compareFixture(overrides = {}) {
  return {
    status: 'ok',
    baseline: { timestamp: '20260401_120000', trained_at: '2026-04-01T12:00:00+00:00' },
    current: { trained_at: '2026-07-03T10:00:00+00:00' },
    channels: [
      {
        name: 'TV', roi_old: 3.2, roi_new: 3.4,
        roi_ci_old: [2.6, 3.9], roi_ci_new: [2.8, 4.0],
        delta_pct: 6.3, verdict: 'stable', verdict_ru: 'стабильно',
        method: 'ci_overlap', decay_shift: false, contribution_new: 900,
      },
      {
        name: 'Digital', roi_old: 2.0, roi_new: 4.8,
        roi_ci_old: [1.6, 2.4], roi_ci_new: [4.2, 5.4],
        delta_pct: 140.0, verdict: 'shift_strong', verdict_ru: 'резкий сдвиг',
        method: 'ci_overlap', decay_shift: false, contribution_new: 500,
      },
    ],
    added_channels: [], removed_channels: [],
    summary: {
      counts: { stable: 1, shift_within_ci: 0, shift_strong: 1 },
      headline: 'ROI TV: был 3.2 [2.6–3.9], стал 3.4 [2.8–4.0] — стабильно.',
      strong_shifts: ['Digital'],
      probable_causes: ['Новые наблюдения изменили оценку вклада.'],
    },
    generated_at: '2026-07-03T10:05:00+00:00',
    ...overrides,
  };
}

/**
 * @param {{versions?: any[], savedCompare?: any, drift?: any, runCompare?: any}} opts
 */
function mockInvoke({ versions = VERSIONS, savedCompare = { status: 'not_found' },
                      drift = { status: 'insufficient' }, runCompare = compareFixture() } = {}) {
  vi.mocked(invoke).mockImplementation(async (cmd, args) => {
    if (cmd === 'project_get_dir') return 'C:/fake/project';
    if (cmd === 'econ_model_history') return { status: 'ok', versions };
    if (cmd === 'econ_generation_compare') {
      if (/** @type {any} */ (args)?.readOnly) return savedCompare;
      if (runCompare instanceof Error) throw runCompare;
      return runCompare;
    }
    if (cmd === 'econ_drift_check') return drift;
    return null;
  });
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  activeProjectId.set('p-test');
});

describe('ModelHistoryCard', () => {
  it('пустой архив → спокойная строка «после первого переобучения»', async () => {
    mockInvoke({ versions: [] });
    render(ModelHistoryCard);
    await waitFor(() => {
      expect(screen.getByText(/после\s+первого переобучения/)).toBeInTheDocument();
    });
  });

  it('дрейф «пора переобучить» → заметная плашка-alert', async () => {
    mockInvoke({
      drift: {
        status: 'ok', verdict: 'retrain_recommended',
        message: 'Пора переобучить: ошибка на свежих точках 42.0% против 8.0% на обучении.',
      },
    });
    render(ModelHistoryCard);
    await waitFor(() => {
      expect(screen.getByTestId('mh-drift')).toHaveTextContent('Пора переобучить');
    });
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('дрейф в норме → тихая строка без alert', async () => {
    mockInvoke({
      drift: { status: 'ok', verdict: 'fresh_ok', message: 'Поколение держит точность — переобучение не требуется.' },
    });
    render(ModelHistoryCard);
    await waitFor(() => {
      expect(screen.getByTestId('mh-drift')).toHaveTextContent('переобучение не требуется');
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('кнопка сравнения → headline + вердикты с CI (нелестный «резкий сдвиг» виден)', async () => {
    mockInvoke();
    render(ModelHistoryCard);
    const btn = await screen.findByRole('button', { name: /Что изменилось с прошлого поколения/ });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByTestId('mh-headline')).toHaveTextContent('был 3.2 [2.6–3.9]');
    });
    expect(screen.getByText('стабильно')).toBeInTheDocument();
    expect(screen.getByText('резкий сдвиг')).toBeInTheDocument();
    expect(screen.getByText(/3\.2 \[2\.6–3\.9\] →\s*3\.4 \[2\.8–4\.0\]/)).toBeInTheDocument();
    // Причины резких сдвигов — в раскрытии
    expect(screen.getByText(/Резкие сдвиги: Digital/)).toBeInTheDocument();
  });

  it('сохранённое сравнение показывается сразу (read_only), без кнопки', async () => {
    mockInvoke({ savedCompare: compareFixture() });
    render(ModelHistoryCard);
    await waitFor(() => {
      expect(screen.getByTestId('mh-headline')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /Что изменилось/ })).not.toBeInTheDocument();
  });

  it('сбой сравнения → alert с текстом и «Повторить»', async () => {
    mockInvoke({ runCompare: new Error('sidecar недоступен') });
    render(ModelHistoryCard);
    const btn = await screen.findByRole('button', { name: /Что изменилось/ });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('sidecar недоступен');
    });
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });
});
