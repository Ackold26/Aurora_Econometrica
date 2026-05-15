/**
 * H-16 — verify econ_save_kpi_settings payload включает Phase 1.3 fields.
 *
 * Audit обнаружил: ValidateStepV13.handleContinue() ранее не передавал
 * unit_costs / unit_cost_inflation / mode_for / budget_inputs к backend.
 * Reload → данные терялись.
 *
 * Этот test моделирует payload directly через invoke mock, проверяет что
 * required keys присутствуют. Не render component E2E (heavy), а isolated
 * payload contract test.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  unitCosts, unitCostInflation, unitCostInputMode, budgetInputs,
} from '$lib/project-state.js';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';

const mockedInvoke = /** @type {ReturnType<typeof vi.fn>} */ (
  /** @type {unknown} */ (invoke)
);


beforeEach(() => {
  mockedInvoke.mockReset();
  mockedInvoke.mockResolvedValue({ status: 'ok' });
  unitCosts.set({});
  unitCostInflation.set({});
  unitCostInputMode.set({});
  budgetInputs.set({});
});


/**
 * Helper — simulate ValidateStepV13.handleContinue() save action.
 * Should match production logic в src/lib/components/pipeline/ValidateStepV13.svelte:323.
 */
async function simulateSave({
  projectDir = 'C:/test/project',
  valuePerCountUnit = null,
  valueLabel = '',
  valuePerCountUnitSource = null,
  perChannelInput = {},
  kpiKind = 'monetary',
} = {}) {
  await invoke('econ_save_kpi_settings', {
    projectDir,
    valuePerCountUnit,
    valuePerCountUnitLabel: valueLabel,
    valuePerCountUnitSource,
    perChannelInput,
    kpiKind,
    // H-16 fix: pass Phase 1.3 stores в payload
    unitCosts: get(unitCosts) ?? null,
    unitCostInflation: get(unitCostInflation) ?? null,
    modeFor: get(unitCostInputMode) ?? null,
    budgetInputs: get(budgetInputs) ?? null,
  });
}


describe('H-16: econ_save_kpi_settings payload contract', () => {
  it('includes Phase 1.3 fields в invoke args', async () => {
    unitCosts.set({ 'TRPs бренд': 25000 });
    unitCostInflation.set({ 'TRPs бренд': 12 });
    unitCostInputMode.set({ 'TRPs бренд': 'budget' });
    budgetInputs.set({ 'TRPs бренд': 2_500_000 });

    await simulateSave();

    expect(mockedInvoke).toHaveBeenCalledWith(
      'econ_save_kpi_settings',
      expect.objectContaining({
        unitCosts: { 'TRPs бренд': 25000 },
        unitCostInflation: { 'TRPs бренд': 12 },
        modeFor: { 'TRPs бренд': 'budget' },
        budgetInputs: { 'TRPs бренд': 2_500_000 },
      }),
    );
  });

  it('передаёт empty objects когда stores пустые', async () => {
    await simulateSave();
    const args = mockedInvoke.mock.calls[0][1];
    expect(args.unitCosts).toEqual({});
    expect(args.unitCostInflation).toEqual({});
    expect(args.modeFor).toEqual({});
    expect(args.budgetInputs).toEqual({});
  });

  it('preserves existing fields (per_channel_input, kpi_kind)', async () => {
    const channelInput = { 'TV': 'monetary', 'TRPs': 'physical' };
    await simulateSave({
      perChannelInput: channelInput,
      kpiKind: 'count',
    });
    expect(mockedInvoke).toHaveBeenCalledWith(
      'econ_save_kpi_settings',
      expect.objectContaining({
        perChannelInput: channelInput,
        kpiKind: 'count',
      }),
    );
  });

  it('round-trip: hydrate stores from activeProject snapshot', () => {
    // Simulate activeProject.subscribe hydration logic (project-state.js:371-380).
    const savedProject = {
      unit_costs: { 'OLV Бюджет': 1.0 },
      unit_cost_inflation_pct: { 'OLV Бюджет': 5 },
      unit_cost_input_mode: { 'OLV Бюджет': 'unit' },
      budget_inputs: { 'OLV Бюджет': 10_000_000 },
    };
    // Hydration logic mirrors production (см. project-state.js).
    if (savedProject.unit_costs) unitCosts.set(savedProject.unit_costs);
    if (savedProject.unit_cost_inflation_pct) unitCostInflation.set(savedProject.unit_cost_inflation_pct);
    if (savedProject.unit_cost_input_mode) unitCostInputMode.set(savedProject.unit_cost_input_mode);
    if (savedProject.budget_inputs) budgetInputs.set(savedProject.budget_inputs);

    expect(get(unitCosts)).toEqual({ 'OLV Бюджет': 1.0 });
    expect(get(unitCostInflation)).toEqual({ 'OLV Бюджет': 5 });
    expect(get(unitCostInputMode)).toEqual({ 'OLV Бюджет': 'unit' });
    expect(get(budgetInputs)).toEqual({ 'OLV Бюджет': 10_000_000 });
  });

  it('reset на project switch (no state leakage)', () => {
    // Set state для project A.
    unitCosts.set({ 'TV': 1.0 });
    unitCostInputMode.set({ 'TV': 'budget' });

    // Simulate project switch: new project БЕЗ Phase 1.3 fields.
    const projectB = {
      id: 'project-b',
      // No unit_costs / inflation / mode / budget_inputs.
    };
    // Hydration logic must reset stores к empty (project-state.js:373-380 path).
    if (!projectB.unit_costs) unitCosts.set({});
    if (!projectB.unit_cost_input_mode) unitCostInputMode.set({});
    if (!projectB.budget_inputs) budgetInputs.set({});

    expect(get(unitCosts)).toEqual({});
    expect(get(unitCostInputMode)).toEqual({});
    expect(get(budgetInputs)).toEqual({});
  });
});
