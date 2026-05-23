/**
 * Phase 2.15 state components tests - EmptyState / LoadingSkeleton / ErrorState.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import EmptyState from '$lib/components/pipeline/EmptyState.svelte';
import LoadingSkeleton from '$lib/components/pipeline/LoadingSkeleton.svelte';
import ErrorState from '$lib/components/pipeline/ErrorState.svelte';


describe('EmptyState', () => {
  it('renders title + body', () => {
    const { getByTestId } = render(EmptyState, {
      props: { title: 'Нет данных', body: 'Загрузите файл.' },
    });
    const el = getByTestId('empty-state');
    expect(el.textContent).toContain('Нет данных');
    expect(el.textContent).toContain('Загрузите файл.');
  });

  it('renders icon если provided', () => {
    const { container } = render(EmptyState, {
      props: { title: 'Test', icon: '📊' },
    });
    expect(container.querySelector('.empty-icon')?.textContent).toContain('📊');
  });

  it('renders CTA button when ctaText + onCta provided', () => {
    const onCta = vi.fn();
    const { getByTestId } = render(EmptyState, {
      props: { title: 'Test', ctaText: 'Action', onCta },
    });
    const btn = getByTestId('empty-state-cta');
    expect(btn).toBeInTheDocument();
    expect(btn.textContent?.trim()).toBe('Action');
  });

  it('does NOT render CTA without onCta callback', () => {
    const { queryByTestId } = render(EmptyState, {
      props: { title: 'Test', ctaText: 'Action' },
    });
    expect(queryByTestId('empty-state-cta')).toBeNull();
  });

  it('calls onCta when button clicked', async () => {
    const onCta = vi.fn();
    const { getByTestId } = render(EmptyState, {
      props: { title: 'Test', ctaText: 'Click me', onCta },
    });
    await fireEvent.click(getByTestId('empty-state-cta'));
    expect(onCta).toHaveBeenCalledTimes(1);
  });

  it('applies variant class', () => {
    const { container } = render(EmptyState, {
      props: { title: 'Test', variant: 'action' },
    });
    expect(container.querySelector('.empty-state--action')).toBeInTheDocument();
  });

  it('has role="status" для screen readers', () => {
    const { getByTestId } = render(EmptyState, {
      props: { title: 'Test' },
    });
    expect(getByTestId('empty-state').getAttribute('role')).toBe('status');
  });
});


describe('LoadingSkeleton', () => {
  it('renders card variant by default', () => {
    const { getByTestId, container } = render(LoadingSkeleton);
    expect(getByTestId('loading-skeleton')).toBeInTheDocument();
    expect(container.querySelectorAll('.skeleton-block').length).toBeGreaterThanOrEqual(1);
  });

  it('renders N rows for list variant', () => {
    const { container } = render(LoadingSkeleton, {
      props: { variant: 'list', rows: 5 },
    });
    expect(container.querySelectorAll('.skeleton-block').length).toBe(5);
  });

  it('renders channel-row variant с 3 internal blocks per row', () => {
    const { container } = render(LoadingSkeleton, {
      props: { variant: 'channel-row', rows: 2 },
    });
    const rows = container.querySelectorAll('.skeleton-channel-row');
    expect(rows.length).toBe(2);
    // 3 blocks per row × 2 rows = 6 blocks
    expect(container.querySelectorAll('.skeleton-block').length).toBe(6);
  });

  it('has aria-live="polite"', () => {
    const { getByTestId } = render(LoadingSkeleton);
    const el = getByTestId('loading-skeleton');
    expect(el.getAttribute('aria-live')).toBe('polite');
    expect(el.getAttribute('role')).toBe('status');
  });

  it('uses custom label', () => {
    const { getByTestId } = render(LoadingSkeleton, {
      props: { label: 'Загружаю классификатор...' },
    });
    const el = getByTestId('loading-skeleton');
    expect(el.getAttribute('aria-label')).toBe('Загружаю классификатор...');
  });
});


describe('ErrorState', () => {
  it('renders default warning severity', () => {
    const { container } = render(ErrorState, {
      props: { title: 'Test error' },
    });
    expect(container.querySelector('.error-state--warning')).toBeInTheDocument();
  });

  it('renders error severity', () => {
    const { container } = render(ErrorState, {
      props: { title: 'Critical', severity: 'error' },
    });
    expect(container.querySelector('.error-state--error')).toBeInTheDocument();
  });

  it('renders title + message', () => {
    const { getByTestId } = render(ErrorState, {
      props: { title: 'Backend ошибка', message: 'Sidecar не отвечает' },
    });
    const el = getByTestId('error-state');
    expect(el.textContent).toContain('Backend ошибка');
    expect(el.textContent).toContain('Sidecar не отвечает');
  });

  it('renders errorCode if provided', () => {
    const { getByTestId } = render(ErrorState, {
      props: { title: 'Bad', errorCode: 'UNIT_COST_OUT_OF_RANGE' },
    });
    expect(getByTestId('error-code').textContent).toBe('UNIT_COST_OUT_OF_RANGE');
  });

  it('renders retry button + calls onRetry', async () => {
    const onRetry = vi.fn();
    const { getByTestId } = render(ErrorState, {
      props: { title: 'Failed', onRetry },
    });
    await fireEvent.click(getByTestId('error-retry'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('does NOT render retry without onRetry callback', () => {
    const { queryByTestId } = render(ErrorState, {
      props: { title: 'No retry' },
    });
    expect(queryByTestId('error-retry')).toBeNull();
  });

  it('shows detail when toggle clicked', async () => {
    const { getByText, queryByTestId, container } = render(ErrorState, {
      props: { title: 'Err', detailText: 'Stack trace here' },
    });
    expect(queryByTestId('error-detail')).toBeNull();
    const toggle = getByText('Показать детали');
    await fireEvent.click(toggle);
    expect(container.querySelector('[data-testid="error-detail"]')).toBeInTheDocument();
  });

  it('has role="alert"', () => {
    const { getByTestId } = render(ErrorState, {
      props: { title: 'Err' },
    });
    expect(getByTestId('error-state').getAttribute('role')).toBe('alert');
  });
});
