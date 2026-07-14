/**
 * E4 (2026-07-03): PromisesCard — «Сбывшиеся рекомендации».
 * Контракт: пустое состояние подсказывает, где кнопка «Зафиксировать прогноз»;
 * статус-бейджи честные (kept/missed одинаково заметны, missed с оговоркой);
 * «Сверить с фактом» обновляет статусы; экстраполяция помечена.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { get } from 'svelte/store';
import { activeProjectId, promisesVersion } from '$lib/project-state.js';
import PromisesCard from '$lib/components/pipeline/PromisesCard.svelte';

function promiseFixture(overrides = {}) {
  return {
    id: 'p1',
    created_at: '2026-07-03T10:00:00+00:00',
    source: 'planning_whatif',
    action_text: 'Бюджет 12 000 000 ₽ на Q3 по плану оптимизации',
    channel_changes: {},
    expected: { kpi_total: 4000, ci_low: 3600, ci_high: 4400, horizon_periods: 4 },
    extrapolation_flag: false,
    check_after_index: 40,
    status: 'pending',
    status_ru: 'ожидает данных',
    checked_at: null,
    actual_kpi_total: null,
    verdict_note: 'Свежих периодов 0 из 4 — обновите данные, и продукт сверит обещание сам.',
    ...overrides,
  };
}

function mockInvoke({ list = [promiseFixture()], check = null } = {}) {
  vi.mocked(invoke).mockImplementation(async (cmd) => {
    if (cmd === 'project_get_dir') return 'C:/fake/project';
    if (cmd === 'econ_promises_list') return { status: 'ok', promises: list, total: list.length };
    if (cmd === 'econ_promises_check') {
      if (check instanceof Error) throw check;
      return check ?? { status: 'ok', promises: list, total: list.length, checked: 0 };
    }
    return null;
  });
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  activeProjectId.set('p-test');
});

describe('PromisesCard', () => {
  it('пусто → подсказка, где «Зафиксировать прогноз»', async () => {
    mockInvoke({ list: [] });
    render(PromisesCard);
    await waitFor(() => {
      expect(screen.getByText(/Зафиксировать прогноз/)).toBeInTheDocument();
    });
  });

  it('pending со счётчиком «0 из 4» и метой ожидания с интервалом', async () => {
    mockInvoke();
    render(PromisesCard);
    await waitFor(() => {
      expect(screen.getByTestId('pr-status')).toHaveTextContent('ожидает данных');
    });
    expect(screen.getByText(/Свежих периодов 0 из 4/)).toBeInTheDocument();
    expect(screen.getByText(/4 000.*\[3 600 – 4 400\].*за 4 пер\./)).toBeInTheDocument();
  });

  it('«Сверить с фактом» → kept-бейдж и вердикт-строка', async () => {
    const kept = promiseFixture({
      status: 'kept', status_ru: 'сбылось', actual_kpi_total: 4040,
      verdict_note: 'Факт 4 040 попал в обещанный интервал [3 600 – 4 400].',
    });
    mockInvoke({ check: { status: 'ok', promises: [kept], total: 1, checked: 1 } });
    render(PromisesCard);
    const btn = await screen.findByRole('button', { name: /Сверить с фактом/ });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByTestId('pr-status')).toHaveTextContent('сбылось');
    });
    expect(screen.getByText(/попал в обещанный интервал/)).toBeInTheDocument();
  });

  it('missed показывается честно, с оговоркой «не каузальный вывод»', async () => {
    const missed = promiseFixture({
      status: 'missed', status_ru: 'не сбылось', actual_kpi_total: 5200,
      verdict_note: 'Факт 5 200 вне обещанного интервала [3 600 – 4 400]. Это сверка прогноза, не каузальный вывод.',
    });
    mockInvoke({ list: [missed] });
    render(PromisesCard);
    await waitFor(() => {
      expect(screen.getByTestId('pr-status')).toHaveTextContent('не сбылось');
    });
    expect(screen.getByText(/не каузальный вывод/)).toBeInTheDocument();
  });

  it('экстраполяция помечена у обещания', async () => {
    mockInvoke({ list: [promiseFixture({ extrapolation_flag: true })] });
    render(PromisesCard);
    await waitFor(() => {
      expect(screen.getByText(/экстраполяция/)).toBeInTheDocument();
    });
  });

  it('сбой сверки → alert + Повторить', async () => {
    mockInvoke({ check: new Error('sidecar недоступен') });
    render(PromisesCard);
    const btn = await screen.findByRole('button', { name: /Сверить с фактом/ });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('sidecar недоступен');
    });
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  // G-4 (2026-07-04, живой GUI-прогон): карточка не размонтируется при навигации
  // (панели visibility, не {#if}), потому onMount был однократным — обещание,
  // зафиксированное ПОСЛЕ первого показа, оставалось невидимым. Реактивный $effect
  // на promisesVersion лечит: bump после фиксации перечитывает список.
  it('bump promisesVersion перечитывает список (обещание, созданное после монтирования)', async () => {
    let current = [];
    vi.mocked(invoke).mockImplementation(async (cmd) => {
      if (cmd === 'project_get_dir') return 'C:/fake/project';
      if (cmd === 'econ_promises_list') return { status: 'ok', promises: current, total: current.length };
      return null;
    });
    promisesVersion.set(0);
    render(PromisesCard);
    // Первый показ — обещаний ещё нет (как при первом входе на Оптимизацию).
    await waitFor(() => {
      expect(screen.getByText(/Прогнозов пока не зафиксировано/)).toBeInTheDocument();
    });
    // Пользователь жмёт «Зафиксировать прогноз»: обещание появилось на диске +
    // OptimizeStep инкрементит версию. Карточка НЕ размонтирована.
    current = [promiseFixture()];
    promisesVersion.set(get(promisesVersion) + 1);
    // Реактивно перечиталось — обещание видно без перезагрузки проекта.
    await waitFor(() => {
      expect(screen.getByTestId('pr-status')).toHaveTextContent('ожидает данных');
    });
  });
});
