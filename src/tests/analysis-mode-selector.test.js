/**
 * AnalysisModeSelector component tests - v2.0.0.
 *
 * Tests:
 *   - 2 cards in Manager mode (expertMode=false)
 *   - 3rd «Смешанный (Expert)» card visible when expertMode=true
 *   - Click ROI/Effectiveness/Expert cards → analysisMode store updated
 *   - Selected card receives .selected CSS class
 *   - WhyThisStep panel collapsed by default
 *   - onSelect callback fires with correct mode
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import AnalysisModeSelector from '$lib/components/pipeline/AnalysisModeSelector.svelte';
import { analysisMode, expertMode } from '$lib/project-state.js';


// Reset stores before each test
beforeEach(() => {
  analysisMode.set('roi');
  expertMode.set(false);
});


describe('AnalysisModeSelector', () => {

  // ─── Card count ─────────────────────────────────────────────────────────

  it('renders exactly 2 cards when expertMode=false (Manager mode)', () => {
    expertMode.set(false);
    const { container } = render(AnalysisModeSelector);
    const cards = container.querySelectorAll('.mode-card');
    expect(cards.length).toBe(2);
  });

  it('renders 3 cards when expertMode=true', () => {
    expertMode.set(true);
    const { container } = render(AnalysisModeSelector);
    const cards = container.querySelectorAll('.mode-card');
    expect(cards.length).toBe(3);
  });

  it('third card title is «Смешанный (Expert)» when expertMode=true', () => {
    expertMode.set(true);
    render(AnalysisModeSelector);
    expect(screen.getByText('Смешанный (Expert)')).toBeInTheDocument();
  });

  it('Expert card NOT visible in Manager mode', () => {
    expertMode.set(false);
    render(AnalysisModeSelector);
    expect(screen.queryByText('Смешанный (Expert)')).toBeNull();
  });

  // ─── Card click → store update ──────────────────────────────────────────

  it('click ROI card → analysisMode store = roi', async () => {
    render(AnalysisModeSelector);
    const roiCard = screen.getByText('ROI режим').closest('button');
    await fireEvent.click(roiCard);
    expect(get(analysisMode)).toBe('roi');
  });

  it('click Эффективность card → analysisMode store = effectiveness', async () => {
    render(AnalysisModeSelector);
    const effCard = screen.getByText('Эффективность режим').closest('button');
    await fireEvent.click(effCard);
    expect(get(analysisMode)).toBe('effectiveness');
  });

  it('click Смешанный Expert card → analysisMode store = mixed', async () => {
    expertMode.set(true);
    render(AnalysisModeSelector);
    const mixedCard = screen.getByText('Смешанный (Expert)').closest('button');
    await fireEvent.click(mixedCard);
    expect(get(analysisMode)).toBe('mixed');
  });

  // ─── Selected CSS class ─────────────────────────────────────────────────

  it('ROI card has .selected class when analysisMode=roi', () => {
    analysisMode.set('roi');
    const { container } = render(AnalysisModeSelector);
    const roiBtn = container.querySelector('.mode-card.tone-monetary');
    expect(roiBtn?.classList.contains('selected')).toBe(true);
  });

  it('Effectiveness card has .selected after click', async () => {
    analysisMode.set('roi');
    const { container } = render(AnalysisModeSelector);
    const effCard = screen.getByText('Эффективность режим').closest('button');
    await fireEvent.click(effCard);
    expect(effCard?.classList.contains('selected')).toBe(true);
  });

  it('ROI card loses .selected after switching to effectiveness', async () => {
    analysisMode.set('roi');
    const { container } = render(AnalysisModeSelector);
    const roiCard = screen.getByText('ROI режим').closest('button');
    const effCard = screen.getByText('Эффективность режим').closest('button');
    await fireEvent.click(effCard);
    expect(roiCard?.classList.contains('selected')).toBe(false);
  });

  // ─── WhyThisStep panel ──────────────────────────────────────────────────

  it('WhyThisStep why-panel is hidden by default', () => {
    const { container } = render(AnalysisModeSelector);
    expect(container.querySelector('.why-panel')).toBeNull();
  });

  it('why-link button has aria-expanded=false by default', () => {
    render(AnalysisModeSelector);
    const whyBtn = screen.getByRole('button', { name: /Зачем выбирать режим/ });
    expect(whyBtn.getAttribute('aria-expanded')).toBe('false');
  });

  it('clicking why-link expands why-panel', async () => {
    const { container } = render(AnalysisModeSelector);
    const whyBtn = screen.getByRole('button', { name: /Зачем выбирать режим/ });
    await fireEvent.click(whyBtn);
    expect(container.querySelector('.why-panel')).toBeInTheDocument();
  });

  // ─── onSelect callback ──────────────────────────────────────────────────

  it('onSelect callback fires with mode=roi on ROI card click', async () => {
    const onSelect = vi.fn();
    render(AnalysisModeSelector, { props: { onSelect } });
    const roiCard = screen.getByText('ROI режим').closest('button');
    await fireEvent.click(roiCard);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith('roi');
  });

  it('onSelect callback fires with mode=effectiveness', async () => {
    const onSelect = vi.fn();
    render(AnalysisModeSelector, { props: { onSelect } });
    const effCard = screen.getByText('Эффективность режим').closest('button');
    await fireEvent.click(effCard);
    expect(onSelect).toHaveBeenCalledWith('effectiveness');
  });

  it('onSelect callback fires with mode=mixed when expert card visible', async () => {
    expertMode.set(true);
    const onSelect = vi.fn();
    render(AnalysisModeSelector, { props: { onSelect } });
    const mixedCard = screen.getByText('Смешанный (Expert)').closest('button');
    await fireEvent.click(mixedCard);
    expect(onSelect).toHaveBeenCalledWith('mixed');
  });

  it('renders without crash when no props provided', () => {
    expect(() => render(AnalysisModeSelector)).not.toThrow();
  });
});
