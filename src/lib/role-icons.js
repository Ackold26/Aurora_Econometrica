/**
 * role-icons.js — единый источник иконок ролей колонок (Lucide-компоненты).
 *
 * Раньше каждый из ColumnMapper / TrafficLight / ExpertValidatePanel держал
 * собственную копию `{ id, icon: 'эмодзи', label }` с триплицированными эмодзи.
 * Теперь иконка ролей живёт здесь одним местом — компоненты импортируют карту
 * и рендерят `<svelte:component this={roleIcons[id]} />` (или {@const}), а
 * локальные массивы несут только id/label/desc.
 *
 * Имена lucide-svelte сверены с node_modules (1.0.1 новый нейминг):
 *   sliders-horizontal (НЕ sliders), trending-up, tv, calendar, ban.
 */
import { TrendingUp, Tv, SlidersHorizontal, Calendar, Ban } from 'lucide-svelte';

/**
 * Канон роль → Lucide-компонент.
 * @type {Record<string, any>}
 */
export const roleIcons = {
  kpi: TrendingUp,
  media: Tv,
  control: SlidersHorizontal,
  date: Calendar,
  unused: Ban,
};
