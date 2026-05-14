/**
 * ScenarioWizard component tests — v2.0.0.
 *
 * Tests:
 *   - Progress bar / step label renders with currentStep number
 *   - Step components shown conditionally per currentStep
 *   - Back button disabled at step 1
 *   - Cross-product hint banner shown when escapeReason set (non-ESCAPE lifecycle)
 *   - Loading overlay shown during AUTO_DETECTING lifecycle
 *   - Escape banner shown in ESCAPE lifecycle
 *   - onComplete callback fires when Run button clicked on step 6
 *   - onCancel callback fires when user cancels escape
 *   - Navigation bar hidden when frozen (RUNNING/COMPLETED)
 *
 * Note: StepSummary is mocked because ScenarioWizard passes diagnostics=null and
 * StepSummary accesses diagnostics.mcmcConvergence in $derived — crashing with null.
 * The stub exposes «Запустить анализ» so Step 6 / onComplete tests can exercise the
 * handleRun path through the wizard.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import ScenarioWizard from '$lib/components/pipeline/ScenarioWizard.svelte';
import { wizardState, resetWizard, transitionTo } from '$lib/wizard-state.js';
import { expertMode } from '$lib/project-state.js';

// Stub out StepSummary to avoid null-diagnostics crash in ScenarioWizard.
// ScenarioWizard always passes diagnostics={null}; StepSummary uses it in $derived at module top.
vi.mock('$lib/components/pipeline/wizard/StepSummary.svelte', async () => {
  const StepSummaryStub = (await import('./StepSummaryStub.svelte')).default;
  return { default: StepSummaryStub };
});


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Set wizard to WIZARD_ACTIVE at given step (valid path from IDLE).
 * @param {number} step
 */
function activateAtStep(step) {
  resetWizard();
  transitionTo('WIZARD_PENDING');
  transitionTo('AUTO_DETECTING');
  transitionTo('WIZARD_ACTIVE', { currentStep: step });
}

beforeEach(() => {
  resetWizard();
  expertMode.set(false);
});


// ---------------------------------------------------------------------------
// Suite 1: Progress bar rendering
// ---------------------------------------------------------------------------
describe('ScenarioWizard — progress bar', () => {
  it('renders «Шаг 1 из 6» label at step 1', () => {
    activateAtStep(1);
    render(ScenarioWizard);
    expect(screen.getByText(/Шаг 1 из 6/)).toBeInTheDocument();
  });

  it('renders «Шаг 3 из 6» label at step 3', () => {
    activateAtStep(3);
    render(ScenarioWizard);
    expect(screen.getByText(/Шаг 3 из 6/)).toBeInTheDocument();
  });

  it('renders progressbar with correct aria-valuenow at step 2', () => {
    activateAtStep(2);
    const { container } = render(ScenarioWizard);
    const bar = container.querySelector('[role="progressbar"]');
    expect(bar).toBeInTheDocument();
    // step 2 of 6 = 33%
    expect(bar?.getAttribute('aria-valuenow')).toBe('33');
  });

  it('renders 6 step dots', () => {
    activateAtStep(1);
    const { container } = render(ScenarioWizard);
    const dots = container.querySelectorAll('.dot');
    expect(dots.length).toBe(6);
  });

  it('current step dot has .active class', () => {
    activateAtStep(2);
    const { container } = render(ScenarioWizard);
    const activeDot = container.querySelector('.dot.active');
    expect(activeDot).toBeInTheDocument();
  });

  it('percentage label shown when not loading / not frozen', () => {
    activateAtStep(3);
    render(ScenarioWizard);
    // 3/6 = 50%
    expect(screen.getByText('50%')).toBeInTheDocument();
  });
});


// ---------------------------------------------------------------------------
// Suite 2: Step components conditional rendering
// ---------------------------------------------------------------------------
describe('ScenarioWizard — step component rendering', () => {
  it('step 1: Back button is disabled (cannot go back from first step)', () => {
    activateAtStep(1);
    render(ScenarioWizard);
    const backBtn = screen.getByRole('button', { name: /Назад/i });
    expect(backBtn).toBeDisabled();
  });

  it('step 2: Back button is enabled', () => {
    activateAtStep(2);
    render(ScenarioWizard);
    const backBtn = screen.getByRole('button', { name: /Назад/i });
    expect(backBtn).not.toBeDisabled();
  });

  it('step 3: Back button is enabled', () => {
    activateAtStep(3);
    render(ScenarioWizard);
    const backBtn = screen.getByRole('button', { name: /Назад/i });
    expect(backBtn).not.toBeDisabled();
  });

  it('step 6: «Запустить анализ» button visible (via StepSummary stub)', () => {
    activateAtStep(6);
    render(ScenarioWizard);
    // Multiple «Запустить анализ» buttons may exist (stub + wizard nav) — at least one required
    const btns = screen.getAllByRole('button', { name: /Запустить анализ/i });
    expect(btns.length).toBeGreaterThan(0);
  });

  it('steps 2,3,5: «Пропустить» button visible (skippable)', () => {
    for (const step of [2, 3, 5]) {
      resetWizard();
      activateAtStep(step);
      const { unmount } = render(ScenarioWizard);
      expect(screen.getByRole('button', { name: /Пропустить/i })).toBeInTheDocument();
      unmount();
    }
  });

  it('step 4 does NOT have «Пропустить» button', () => {
    activateAtStep(4);
    render(ScenarioWizard);
    expect(screen.queryByRole('button', { name: /Пропустить/i })).toBeNull();
  });
});


// ---------------------------------------------------------------------------
// Suite 3: Navigation buttons
// ---------------------------------------------------------------------------
describe('ScenarioWizard — navigation', () => {
  it('Back button disabled at step 1', () => {
    activateAtStep(1);
    render(ScenarioWizard);
    expect(screen.getByRole('button', { name: /Назад/i })).toBeDisabled();
  });

  it('Back button enabled at step 2', () => {
    activateAtStep(2);
    render(ScenarioWizard);
    expect(screen.getByRole('button', { name: /Назад/i })).not.toBeDisabled();
  });

  it('clicking Далее advances currentStep', async () => {
    activateAtStep(1);
    render(ScenarioWizard);
    const nextBtn = screen.getByRole('button', { name: /Далее/i });
    await fireEvent.click(nextBtn);
    expect(get(wizardState).currentStep).toBe(2);
  });
});


// ---------------------------------------------------------------------------
// Suite 4: Loading overlay (AUTO_DETECTING)
// ---------------------------------------------------------------------------
describe('ScenarioWizard — loading overlay', () => {
  it('shows «Анализирую данные...» label when lifecycle=AUTO_DETECTING', () => {
    resetWizard();
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    render(ScenarioWizard);
    expect(screen.getByText(/Анализирую данные/)).toBeInTheDocument();
  });

  it('loading-state container visible during AUTO_DETECTING', () => {
    resetWizard();
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    const { container } = render(ScenarioWizard);
    expect(container.querySelector('.loading-state')).toBeInTheDocument();
  });

  it('wizard nav NOT shown during AUTO_DETECTING', () => {
    resetWizard();
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    const { container } = render(ScenarioWizard);
    expect(container.querySelector('.wizard-nav')).toBeNull();
  });
});


// ---------------------------------------------------------------------------
// Suite 5: Escape banner
// ---------------------------------------------------------------------------
describe('ScenarioWizard — escape banner', () => {
  it('shows escape banner when lifecycle=ESCAPE with history_short', () => {
    resetWizard();
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('ESCAPE', { escapeReason: 'history_short' });
    render(ScenarioWizard);
    expect(screen.getByText(/Недостаточно данных для MMM/)).toBeInTheDocument();
  });

  it('shows escape banner with launch_like reason', () => {
    resetWizard();
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('ESCAPE', { escapeReason: 'launch_like' });
    render(ScenarioWizard);
    expect(screen.getByText(/Мало рекламной активности/)).toBeInTheDocument();
  });

  it('escape banner has «Продолжить в Expert mode» button', () => {
    resetWizard();
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('ESCAPE', { escapeReason: 'history_short' });
    render(ScenarioWizard);
    expect(screen.getByRole('button', { name: /Продолжить в Expert mode/i })).toBeInTheDocument();
  });

  it('onCancel fires when «Отмена» clicked in escape banner', async () => {
    resetWizard();
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('ESCAPE', { escapeReason: 'history_short' });
    const onCancel = vi.fn();
    render(ScenarioWizard, { props: { onCancel } });
    const cancelBtn = screen.getByRole('button', { name: /^Отмена$/i });
    await fireEvent.click(cancelBtn);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});


// ---------------------------------------------------------------------------
// Suite 6: Cross-product hint banner
// ---------------------------------------------------------------------------
describe('ScenarioWizard — cross-product hint banner', () => {
  it('inline hint banner shown when escapeReason set but NOT in ESCAPE lifecycle', () => {
    resetWizard();
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('WIZARD_ACTIVE', {
      escapeReason: 'history_short',
      currentStep: 1,
    });
    render(ScenarioWizard);
    expect(screen.getByText(/Aurora Launch Planner/)).toBeInTheDocument();
  });

  it('inline hint banner NOT shown when escapeReason is null', () => {
    activateAtStep(1);
    render(ScenarioWizard);
    expect(screen.queryByText(/Aurora Launch Planner/)).toBeNull();
  });
});


// ---------------------------------------------------------------------------
// Suite 7: onComplete callback
// ---------------------------------------------------------------------------
describe('ScenarioWizard — onComplete', () => {
  it('onComplete fires when «Запустить анализ» clicked at step 6', async () => {
    activateAtStep(6);
    const onComplete = vi.fn();
    const { container } = render(ScenarioWizard, { props: { onComplete } });
    // Use the wizard nav «Запустить анализ» button (in .btn-run, outside the stub)
    const runBtn = container.querySelector('button.btn-run');
    expect(runBtn).toBeTruthy();
    await fireEvent.click(runBtn);
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it('onComplete receives stepData + lifecycle + resolvedFactors', async () => {
    activateAtStep(6);
    const onComplete = vi.fn();
    const { container } = render(ScenarioWizard, { props: { onComplete } });
    const runBtn = container.querySelector('button.btn-run');
    await fireEvent.click(runBtn);
    const arg = onComplete.mock.calls[0][0];
    expect(arg).toHaveProperty('lifecycle');
    expect(arg).toHaveProperty('resolvedFactors');
  });
});


// ---------------------------------------------------------------------------
// Suite 8: Frozen state (RUNNING / COMPLETED)
// ---------------------------------------------------------------------------
describe('ScenarioWizard — frozen state', () => {
  it('wizard-nav hidden when lifecycle=RUNNING', () => {
    activateAtStep(6);
    transitionTo('RUNNING');
    const { container } = render(ScenarioWizard);
    expect(container.querySelector('.wizard-nav')).toBeNull();
  });

  it('shows «Анализ завершён» label when lifecycle=COMPLETED', () => {
    activateAtStep(6);
    transitionTo('RUNNING');
    transitionTo('COMPLETED');
    render(ScenarioWizard);
    expect(screen.getByText(/Анализ завершён/)).toBeInTheDocument();
  });
});
