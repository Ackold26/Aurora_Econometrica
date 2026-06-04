/**
 * Сборка train-конфига (TrainStartRequest-shape) из снимка состояния ConfigPanel.
 *
 * Чистый VERBATIM-порт inline-сборки `ConfigPanel.svelte:336-365` (extract 2026-06-06,
 * enabler для synthetic-truth: позволяет построить АУТЕНТИЧНЫЙ конфиг вне Svelte-рантайма
 * и прогнать `econ_train`-probe, а не хрупко реконструировать payload). НЕ читает сторы —
 * все ~15 входов передаются явно (та же техника, что `cppSatisfied(snapshot)` /
 * `shouldRelockModel({...})` в project-state.js).
 *
 * БАЙТ-В-БАЙТ с inline по построению: те же дефолты (`|| {}`, `|| 'sales'`,
 * `|| 'geometric'`, `|| 'date'`), тот же `mcmc_override`-тернар, та же `kpi_unit_cost`
 * count-логика, ТОТ ЖЕ ПОРЯДОК КЛЮЧЕЙ. Изменение любого из этих элементов = ДРУГАЯ модель
 * на обучении → synthetic-truth ложно обвинит движок в баге этого extract'а
 * (см. feedback_cheapest_decisive_artifact_max_adversarial_verify). До первого train через
 * эту функцию — байт-в-байт дифф её выхода против inline на РЕАЛЬНОМ проекте.
 *
 * @param {{
 *   projectDir: string,
 *   dataFile: string,
 *   kpiColumn: string,
 *   mediaColumns: string[],
 *   controlColumns: string[],
 *   dateColumn: string|null|undefined,
 *   channelAdstock: Record<string, string>,
 *   engine: string,
 *   showAdvanced: boolean,
 *   mcmcChains: number,
 *   mcmcDraws: number,
 *   mcmcTune: number,
 *   unitCosts: Record<string, number>|null|undefined,
 *   kpiType: string|null|undefined,
 *   valuePerCountUnit: number|null|undefined,
 *   kpiKind: string,
 *   mergeRules: Record<string, string[]>,
 *   channelCategories: Record<string, string>|null|undefined,
 * }} state
 * @returns {Record<string, any>} TrainStartRequest-shaped config
 */
export function buildTrainConfig(state) {
  const {
    projectDir,
    dataFile,
    kpiColumn,
    mediaColumns,
    controlColumns,
    dateColumn,
    channelAdstock,
    engine,
    showAdvanced,
    mcmcChains,
    mcmcDraws,
    mcmcTune,
    unitCosts,
    kpiType,
    valuePerCountUnit,
    kpiKind,
    mergeRules,
    channelCategories,
  } = state;

  return {
    project_dir: projectDir,
    data_file: dataFile,
    kpi_column: kpiColumn,
    media_columns: mediaColumns,
    control_columns: controlColumns,
    date_column: dateColumn || 'date',
    adstock_config: Object.fromEntries(
      mediaColumns.map(ch => [ch, channelAdstock[ch] || 'geometric'])
    ),
    mcmc_override: (engine === 'bayesian' && showAdvanced)
      ? { chains: mcmcChains, draws: mcmcDraws, tune: mcmcTune }
      : null,
    unit_costs: unitCosts || {},
    // v2.1.0 (ADR-020): kpi_type для smart math (mixed mode count
    // KPI разрешается, awareness rejected). Backend default 'sales'
    // - preserving backward compat для legacy callers без kpiType.
    kpi_type: kpiType || 'sales',
    // v2.1.0 (ADR-021): ценность единицы count KPI (₽/упак., ₽/лид).
    // Persisted в pickle snapshot. None = ROI/lift в native units.
    kpi_unit_cost: (kpiKind === 'count' && typeof valuePerCountUnit === 'number' && valuePerCountUnit > 0)
      ? valuePerCountUnit
      : null,
    merge_rules: mergeRules,
    mode: engine,
    // Trust Level 3 (v1.1.0): brand vs performance categorization.
    // Backend modeler decides hierarchical vs single-prior на основе ≥2 в группе.
    channel_categories: channelCategories || {},
  };
}
