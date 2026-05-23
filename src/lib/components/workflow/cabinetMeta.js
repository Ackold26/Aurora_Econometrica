/** Cabinet metadata: colors, icons, names - single source of truth for workflow components
 * @type {Record<string, {name: string, icon: string, color: string}>}
 */
export const cabinetMeta = {
  'media-analyst': { name: 'Медиа-аналитик', icon: '~', color: '#3B82F6' },
  'communication-analyst': { name: 'Ком. аналитик', icon: '~', color: '#3B82F6' },
  'communication-strategist': { name: 'Ком. стратег', icon: '~', color: '#8B5CF6' },
  'creative-director': { name: 'Креативный директор', icon: '*', color: '#EC4899' },
  'copywriter': { name: 'Копирайтер', icon: '*', color: '#06B6D4' },
  'art-director': { name: 'Арт-директор', icon: '*', color: '#7C3AED' },
  'focus-groups': { name: 'Фокус-группы', icon: 'o', color: '#F97316' },
  'lawyer-contracts': { name: 'Юрист - Контракты', icon: '#', color: '#10B981' },
  'lawyer-claims': { name: 'Юрист - NDA', icon: '=', color: '#F59E0B' },
  'lawyer-advertising': { name: 'Юрист - Реклама', icon: '!', color: '#EF4444' },
  'social-listening': { name: 'Social Listening', icon: '@', color: '#0EA5E9' },
  'econometrist': { name: 'Эконометрист', icon: '$', color: '#14B8A6' },
  'psy-profiler': { name: 'PSY Profiler', icon: '%', color: '#A855F7' },
};

/** @param {string} cabinetId */
export function getMeta(cabinetId) {
  return cabinetMeta[cabinetId] || { name: cabinetId, icon: '*', color: '#888' };
}
