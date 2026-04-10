import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import CabinetCard from '$lib/components/CabinetCard.svelte';

const makeCabinet = (overrides = {}) => ({
  id: 'media-analyst',
  name: 'Медиа-аналитик',
  description: 'Аналитика медиа, комментарии к слайдам',
  icon: '📈',
  color: '#3B82F6',
  ...overrides,
});

describe('CabinetCard', () => {
  it('renders cabinet name and description', () => {
    const cabinet = makeCabinet();
    render(CabinetCard, { props: { cabinet, onClick: vi.fn() } });
    expect(screen.getByText('Медиа-аналитик')).toBeInTheDocument();
    expect(screen.getByText('Аналитика медиа, комментарии к слайдам')).toBeInTheDocument();
  });

  it('uses custom SVG icon for known cabinets', () => {
    const cabinet = makeCabinet({ id: 'lawyer-contracts' });
    const { container } = render(CabinetCard, { props: { cabinet, onClick: vi.fn() } });
    const svg = container.querySelector('.card-icon svg');
    expect(svg).toBeTruthy();
    // lawyer-contracts has a custom icon with polyline
    expect(svg.innerHTML).toContain('polyline');
  });

  it('uses custom SVG icon for social-listening', () => {
    const cabinet = makeCabinet({ id: 'social-listening', name: 'Social Listening', color: '#06B6D4' });
    const { container } = render(CabinetCard, { props: { cabinet, onClick: vi.fn() } });
    const svg = container.querySelector('.card-icon svg');
    expect(svg).toBeTruthy();
    // social-listening has an eye icon with circle r="3"
    expect(svg.innerHTML).toContain('r="3"');
  });

  it('falls back to generic icon for unknown cabinet', () => {
    const cabinet = makeCabinet({ id: 'unknown-cabinet' });
    const { container } = render(CabinetCard, { props: { cabinet, onClick: vi.fn() } });
    const svg = container.querySelector('.card-icon svg');
    expect(svg).toBeTruthy();
    // fallback icon has a rect
    expect(svg.innerHTML).toContain('rect');
  });

  it('applies cabinet color as CSS variable', () => {
    const cabinet = makeCabinet({ color: '#EC4899' });
    const { container } = render(CabinetCard, { props: { cabinet, onClick: vi.fn() } });
    const card = container.querySelector('.card');
    expect(card.getAttribute('style')).toContain('#EC4899');
  });

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn();
    const cabinet = makeCabinet();
    const { container } = render(CabinetCard, { props: { cabinet, onClick } });
    const card = container.querySelector('.card');
    card.click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe('All 9 cabinets render', () => {
  const cabinetIds = [
    'media-analyst',
    'communication-analyst',
    'communication-strategist',
    'creative-director',
    'focus-groups',
    'social-listening',
    'lawyer-contracts',
    'lawyer-claims',
    'lawyer-advertising',
  ];

  cabinetIds.forEach((id) => {
    it(`renders ${id} without errors`, () => {
      const cabinet = makeCabinet({ id, name: id });
      expect(() => {
        render(CabinetCard, { props: { cabinet, onClick: vi.fn() } });
      }).not.toThrow();
    });
  });
});
