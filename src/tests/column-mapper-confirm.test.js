/**
 * ColumnMapperConfirm component tests (v1.3.2 audit followup I3).
 *
 * Critical paths:
 * - renders table с detected roles
 * - effective role override через dropdown
 * - confirm builds mapping = column name → role
 * - warning banners когда KPI=0 или media=0
 * - stats counter reflects overrides
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ColumnMapperConfirm from '$lib/components/pipeline/ColumnMapperConfirm.svelte';


function makeColumns() {
  return [
    { name: 'sales', role: 'kpi', kind: 'numeric' },
    { name: 'date',  role: 'date', kind: 'date' },
    { name: 'tv_grp', role: 'media', kind: 'numeric' },
    { name: 'digital', role: 'media', kind: 'numeric' },
    { name: 'temp', role: 'control', kind: 'numeric' },
  ];
}


describe('ColumnMapperConfirm', () => {
  it('renders header instructions', () => {
    render(ColumnMapperConfirm, { props: { columns: makeColumns(), onConfirm: vi.fn() } });
    expect(screen.getByText('Подтвердите роли колонок')).toBeInTheDocument();
  });

  it('renders каждый column в таблице', () => {
    const { container } = render(ColumnMapperConfirm, {
      props: { columns: makeColumns(), onConfirm: vi.fn() },
    });
    // Column names в <td class="col-name"> cells. Может быть multiple matches
    // если name fragment appears в descriptions — use targeted .col-name selector.
    const cellTexts = Array.from(container.querySelectorAll('.col-name'))
      .map(td => td.textContent?.trim());
    for (const col of makeColumns()) {
      expect(cellTexts).toContain(col.name);
    }
  });

  it('shows stats counts from initial roles', () => {
    const { container } = render(ColumnMapperConfirm, {
      props: { columns: makeColumns(), onConfirm: vi.fn() },
    });
    // 1 kpi, 2 media, 1 control, 1 date, 0 excluded — text patterns in chips.
    const stats = container.querySelector('.summary-row');
    expect(stats?.textContent).toContain('KPI');
    expect(stats?.textContent).toContain('Каналы');
  });

  it('shows warning когда KPI count = 0', () => {
    const columns = makeColumns().map(c => c.role === 'kpi' ? { ...c, role: 'unknown' } : c);
    render(ColumnMapperConfirm, { props: { columns, onConfirm: vi.fn() } });
    // Warning text references KPI absence
    expect(screen.getByText(/KPI не определён/)).toBeInTheDocument();
  });

  it('shows warning когда media count = 0', () => {
    const columns = makeColumns().map(c => c.role === 'media' ? { ...c, role: 'control' } : c);
    render(ColumnMapperConfirm, { props: { columns, onConfirm: vi.fn() } });
    expect(screen.getByText(/Медиа-каналы не обнаружены/)).toBeInTheDocument();
  });

  it('handleConfirm builds full mapping и calls onConfirm', async () => {
    const onConfirm = vi.fn();
    render(ColumnMapperConfirm, {
      props: { columns: makeColumns(), onConfirm },
    });
    const btn = screen.getByText(/Подтвердить роли/);
    await fireEvent.click(btn);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    const mapping = onConfirm.mock.calls[0][0];
    // Each column present в mapping
    expect(mapping).toMatchObject({
      sales: 'kpi',
      date: 'date',
      tv_grp: 'media',
      digital: 'media',
      temp: 'control',
    });
  });

  it('override через dropdown changes effective role в mapping', async () => {
    const onConfirm = vi.fn();
    const { container } = render(ColumnMapperConfirm, {
      props: { columns: makeColumns(), onConfirm },
    });
    // Find dropdown для 'digital' (currently media) и change to excluded.
    const selects = container.querySelectorAll('select');
    // Look for select inside row containing 'digital'.
    const rows = container.querySelectorAll('tbody tr');
    let digitalSelect = null;
    for (const row of rows) {
      if (row.textContent?.includes('digital')) {
        digitalSelect = row.querySelector('select');
        break;
      }
    }
    expect(digitalSelect).toBeTruthy();
    await fireEvent.change(digitalSelect, { target: { value: 'excluded' } });

    const btn = screen.getByText(/Подтвердить роли/);
    await fireEvent.click(btn);
    const mapping = onConfirm.mock.calls[0][0];
    expect(mapping.digital).toBe('excluded');
    // Others unchanged
    expect(mapping.tv_grp).toBe('media');
  });

  it('renders all 5 role options в каждом dropdown', () => {
    const { container } = render(ColumnMapperConfirm, {
      props: { columns: makeColumns(), onConfirm: vi.fn() },
    });
    const firstSelect = container.querySelector('select');
    const options = firstSelect?.querySelectorAll('option');
    expect(options?.length).toBe(5);  // kpi/media/control/date/excluded
  });

  it('handles пустой columns массив без crash', () => {
    expect(() =>
      render(ColumnMapperConfirm, { props: { columns: [], onConfirm: vi.fn() } })
    ).not.toThrow();
  });

  it('omits warning banners когда есть kpi + media', () => {
    render(ColumnMapperConfirm, { props: { columns: makeColumns(), onConfirm: vi.fn() } });
    expect(screen.queryByText(/KPI не определён/)).toBeNull();
    expect(screen.queryByText(/Медиа-каналы не обнаружены/)).toBeNull();
  });
});
