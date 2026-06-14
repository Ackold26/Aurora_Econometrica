/**
 * step-icons.js — иконки шагов пайплайна (Lucide-компоненты) по id из PIPELINE_STEPS.
 *
 * Вынесено из project-state.js намеренно: project-state.js — core-стор, который
 * импортируют почти все тесты. Если затащить туда barrel `from 'lucide-svelte'`
 * (~1500 компонентов), vitest-transform барреля превышает per-test timeout (5s)
 * на каждом `await import('$lib/project-state.js')`. Здесь lucide живёт изолированно
 * и тянется только .svelte-потребителями (StepWrapper / PipelineStepper), которые
 * и без того импортируют lucide.
 *
 * Имена сверены с lucide-svelte 1.0.1 (circle-check, clipboard-list — новый нейминг).
 */
import { Import, CircleCheck, Brain, Microscope, Target, ClipboardList } from 'lucide-svelte';

/**
 * id шага пайплайна → Lucide-компонент.
 * @type {Record<string, any>}
 */
export const stepIcons = {
  import: Import,
  validate: CircleCheck,
  model: Brain,
  decompose: Microscope,
  optimize: Target,
  report: ClipboardList,
};
