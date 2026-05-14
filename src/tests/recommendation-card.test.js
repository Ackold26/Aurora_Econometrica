/**
 * RecommendationCard component tests (v1.3.2 audit followup I3).
 *
 * Tests render variants per props (tone, primaryAction, secondaryAction)
 * + click handlers. Component is presentational (no internal state) - basic
 * render coverage gives high-confidence regression prevention.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import RecommendationCard from '$lib/components/pipeline/RecommendationCard.svelte';


describe('RecommendationCard', () => {
  it('renders title + text по default tone', () => {
    render(RecommendationCard, {
      props: {
        title: 'Тестовая рекомендация',
        text: 'Сделайте X - получите Y.',
      },
    });
    expect(screen.getByText('Тестовая рекомендация')).toBeInTheDocument();
    expect(screen.getByText('Сделайте X - получите Y.')).toBeInTheDocument();
  });

  it('renders без icon когда не передан (default = null per v2.0.0 Lucide refactor)', () => {
    const { container } = render(RecommendationCard, {
      props: { text: 'plain card' },
    });
    // v2.0.0: default icon = null (Lucide icons via icon prop pattern, no fallback emoji)
    const icon = container.querySelector('.rec-icon');
    expect(icon?.textContent?.trim() ?? '').toBe('');
  });

  it('respects custom icon prop', () => {
    const { container } = render(RecommendationCard, {
      props: { icon: '📈', text: 'with custom icon' },
    });
    expect(container.querySelector('.rec-icon')?.textContent).toBe('📈');
  });

  it('applies tone class to root container', () => {
    const { container } = render(RecommendationCard, {
      props: { tone: 'success', text: 'green card' },
    });
    expect(container.querySelector('.tone-success')).toBeInTheDocument();
  });

  it('renders все 3 tones без crash', () => {
    for (const tone of ['info', 'success', 'warn']) {
      const { container } = render(RecommendationCard, {
        props: { tone, text: `card ${tone}` },
      });
      expect(container.querySelector(`.tone-${tone}`)).toBeInTheDocument();
    }
  });

  it('renders detail when provided', () => {
    render(RecommendationCard, {
      props: {
        text: 'main text',
        detail: 'Дополнительное пояснение.',
      },
    });
    expect(screen.getByText('Дополнительное пояснение.')).toBeInTheDocument();
  });

  it('hides detail when not provided', () => {
    const { container } = render(RecommendationCard, {
      props: { text: 'main only' },
    });
    expect(container.querySelector('.rec-detail')).toBeNull();
  });

  it('renders primaryAction button + invokes onClick', async () => {
    const onClick = vi.fn();
    render(RecommendationCard, {
      props: {
        text: 'with primary',
        primaryAction: { label: 'Перейти', onClick },
      },
    });
    const btn = screen.getByText(/Перейти/);
    await fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders secondaryAction button + invokes onClick', async () => {
    const onClick = vi.fn();
    render(RecommendationCard, {
      props: {
        text: 'with secondary',
        secondaryAction: { label: 'Отменить', onClick },
      },
    });
    const btn = screen.getByText('Отменить');
    await fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders both actions independently', async () => {
    const primary = vi.fn();
    const secondary = vi.fn();
    render(RecommendationCard, {
      props: {
        text: 'both actions',
        primaryAction: { label: 'Primary', onClick: primary },
        secondaryAction: { label: 'Secondary', onClick: secondary },
      },
    });
    await fireEvent.click(screen.getByText('Secondary'));
    expect(primary).not.toHaveBeenCalled();
    expect(secondary).toHaveBeenCalledTimes(1);
  });

  it('omits actions container когда оба null', () => {
    const { container } = render(RecommendationCard, {
      props: { text: 'no actions' },
    });
    expect(container.querySelector('.rec-actions')).toBeNull();
  });
});
