/**
 * MigrationCompletedToast tests - Phase 2.16.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import MigrationCompletedToast from '$lib/components/MigrationCompletedToast.svelte';


beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});


describe('MigrationCompletedToast', () => {
  it('does not render when show=false', () => {
    const { container } = render(MigrationCompletedToast, {
      props: { show: false },
    });
    expect(container.querySelector('[data-testid="migration-completed-toast"]')).toBeNull();
  });

  it('renders when show=true', () => {
    const { getByTestId } = render(MigrationCompletedToast, {
      props: { show: true, fromVersion: '1.0', toVersion: '2.0.1', movedCount: 0 },
    });
    expect(getByTestId('migration-completed-toast')).toBeInTheDocument();
  });

  it('displays toVersion в title', () => {
    const { getByTestId } = render(MigrationCompletedToast, {
      props: { show: true, fromVersion: '1.0', toVersion: '2.0.1' },
    });
    const toast = getByTestId('migration-completed-toast');
    expect(toast.textContent).toContain('v2.0.1');
  });

  it('displays moved columns count в Russian plural (one form)', () => {
    const { getByTestId } = render(MigrationCompletedToast, {
      props: { show: true, fromVersion: '1.0', toVersion: '2.0.1', movedCount: 1 },
    });
    expect(getByTestId('migration-completed-toast').textContent).toMatch(/1\s+столбец/);
  });

  it('displays Russian plural for 3 columns (few form)', () => {
    const { getByTestId } = render(MigrationCompletedToast, {
      props: { show: true, fromVersion: '1.0', toVersion: '2.0.1', movedCount: 3 },
    });
    expect(getByTestId('migration-completed-toast').textContent).toMatch(/3\s+столбца/);
  });

  it('displays Russian plural for 5+ columns (many form)', () => {
    const { getByTestId } = render(MigrationCompletedToast, {
      props: { show: true, fromVersion: '1.0', toVersion: '2.0.1', movedCount: 7 },
    });
    expect(getByTestId('migration-completed-toast').textContent).toMatch(/7\s+столбцов/);
  });

  it('shows neutral message when movedCount=0', () => {
    const { getByTestId } = render(MigrationCompletedToast, {
      props: { show: true, fromVersion: '1.0', toVersion: '2.0.1', movedCount: 0 },
    });
    const toast = getByTestId('migration-completed-toast');
    expect(toast.textContent).toContain('без изменения классификации');
  });

  it('calls onDismiss when × clicked', async () => {
    const onDismiss = vi.fn();
    const { container } = render(MigrationCompletedToast, {
      props: { show: true, onDismiss },
    });
    const closeBtn = container.querySelector('.toast-close');
    expect(closeBtn).toBeInTheDocument();
    await fireEvent.click(closeBtn);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('auto-dismisses after autoDismissMs ms', async () => {
    const onDismiss = vi.fn();
    render(MigrationCompletedToast, {
      props: { show: true, onDismiss, autoDismissMs: 5000 },
    });
    expect(onDismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(4999);
    expect(onDismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('does NOT auto-dismiss when autoDismissMs=0', () => {
    const onDismiss = vi.fn();
    render(MigrationCompletedToast, {
      props: { show: true, onDismiss, autoDismissMs: 0 },
    });
    vi.advanceTimersByTime(60000);
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('has aria-live="polite" для screen reader', () => {
    const { getByTestId } = render(MigrationCompletedToast, {
      props: { show: true },
    });
    const toast = getByTestId('migration-completed-toast');
    expect(toast.getAttribute('aria-live')).toBe('polite');
    expect(toast.getAttribute('role')).toBe('status');
  });

  it('close button has aria-label', () => {
    const { container } = render(MigrationCompletedToast, {
      props: { show: true },
    });
    const closeBtn = container.querySelector('.toast-close');
    expect(closeBtn?.getAttribute('aria-label')).toBe('Закрыть уведомление');
  });
});
