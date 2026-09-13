/**
 * planning-live-state.js – живое состояние шага «Планирование» для панели подсказок.
 *
 * ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Подсказки шага обязаны быть условными от НАСТОЯЩИХ чисел
 * прогноза (ширина правдоподобного диапазона, перекрытие диапазонов вариантов,
 * разброс бюджетов) – INV-50. Эти числа живут в `PlanningStep.svelte` как локальное
 * состояние, а читает их `InsightsPanel.svelte`. Приём тот же, что `optimizeLiveState`
 * для шага «Оптимизация»: шаг пишет снимок, панель читает.
 *
 * Снимок – производная от того, что УЖЕ на экране: панель не пересчитывает прогноз
 * и ничего не досочиняет, она комментирует ровно те числа, которые клиент видит.
 */
import { writable } from 'svelte/store';

/**
 * @typedef {Object} PlanningLiveBaseline
 * @property {number} totalKpi              центр прогноза базового плана за горизонт
 * @property {number|null} totalSpend       бюджет плана в деньгах; null – движок НЕ перевёл все каналы в рубли
 * @property {number|null} ciLowTotal       нижняя граница правдоподобного диапазона
 * @property {number|null} ciHighTotal      верхняя граница
 */

/**
 * @typedef {Object} PlanningLiveVariant
 * @property {string} name
 * @property {number} budget                суммарный бюджет варианта за горизонт
 * @property {number} predictedKpi
 * @property {number} [ciLow]
 * @property {number} [ciHigh]
 */

/**
 * `acceptedName` – имя ПРИНЯТОГО плана, вычисленное единственным правилом
 * выбора (`acceptedPlanName` в PlanningStep.svelte). Тем же именем шаг пишет
 * манифест `results/planning.json`, по которому документ судит принятый план.
 * Панель подсказок обязана называть ровно его, а не выбирать заново: иначе
 * экран и унесённый документ называют принятыми РАЗНЫЕ планы (находка 2
 * внешнего аудита s47, INV-50).
 *
 * @type {import('svelte/store').Writable<{
 *   acceptedName: string | null,
 *   baseline: PlanningLiveBaseline | null,
 *   variants: PlanningLiveVariant[],
 * }>}
 */
export const planningLiveState = writable({
  acceptedName: null,
  baseline: null,
  variants: [],
});
