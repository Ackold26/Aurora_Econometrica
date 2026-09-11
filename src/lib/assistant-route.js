/**
 * Единственная ось режима работы: «полностью локально» ●———○ «через шлюз Авроры».
 *
 * 🔴 Зачем отдельный модуль. До 11.09.2026 положение складывалось на экране из двух
 * переключателей и одного согласия, и каждое место складывало по-своему: подпись в
 * настройках смотрела только на «только локально» и на свежей установке жирным
 * утверждала, что материалы уходят на наш сервер, хотя согласия ещё никто не давал.
 * Теперь положение считает продукт (`execution_mode::route_state`), а интерфейс его
 * ПЕЧАТАЕТ. Своих формулировок про маршрут данных здесь нет намеренно: две строки-
 * константы про одно и то же расходятся молча (INV-146).
 *
 * Единственный текст, который живёт здесь, — про состояние «ещё не прочитано»: в
 * продукте такого состояния нет, оно бывает только на экране.
 */

import { invoke } from '@tauri-apps/api/core';
import { derived } from 'svelte/store';
import { cloudConsent } from '$lib/store.js';

/**
 * Подпись, пока положение не прочитано.
 *
 * 🔴 Ни одно из двух утверждений тут делать нельзя. Отсутствующие значения продукт
 * печатает словом «н/д» — тем же приёмом и здесь, а не догадкой по умолчанию: до
 * ответа продукта неизвестно и «уходят», и «не уходят».
 */
export const HEADLINE_UNKNOWN =
  'Сейчас: н/д – положение режима ещё не прочитано. Пока оно неизвестно, ИИ-ассистент не отвечает.';

/** Что показать, если человек обращается к ассистенту, а положение не прочитано. */
export const NOTICE_UNKNOWN =
  'Режим работы ещё не прочитан, поэтому запрос не отправлен. Откройте Настройки и проверьте положение переключателя режима.';

/**
 * Перечитать положение у продукта и разложить по стору.
 *
 * Зовётся при запуске и после КАЖДОГО изменения (переключатель, согласие, отзыв):
 * частичная правка стора «на месте» оставляла бы фактическое положение прежним, и
 * подпись рассказывала бы про маршрут данных вчерашнюю правду.
 */
/**
 * Текст однократного сообщения о смене маршрута, если его пора показать. Пустая строка —
 * показывать нечего. Снимается вызовом `acknowledgeRouteChange()` ПОСЛЕ показа.
 */
let routeChangedNotice = '';

/** @returns {string} текст, который пора показать один раз (или пустая строка) */
export function pendingRouteChangeNotice() {
  return routeChangedNotice;
}

/**
 * Отметить, что сообщение о смене маршрута показано.
 *
 * 🔴 Признак снимается ТОЛЬКО после показа и только в durable-настройках: сними его
 * заранее — и человек, у которого маршрут данных сменился, не узнает об этом никогда.
 */
export async function acknowledgeRouteChange() {
  routeChangedNotice = '';
  try {
    await invoke('dismiss_route_notice');
  } catch (e) {
    console.warn('признак сообщения о смене маршрута не снят', e);
  }
}

export async function refreshAssistantRoute() {
  try {
    const st = /** @type {any} */ (await invoke('get_cloud_consent_status'));
    cloudConsent.set({
      advisorsEnabled: !!st?.cloud_advisors_enabled,
      granted: !st?.consent_required,
      localOnly: !!st?.local_only,
      gatewayBuiltIn: !!st?.gateway_built_in,
      routeCloud: !!st?.route_cloud,
      routeLocked: !!st?.route_locked,
      routeLockedReason: String(st?.route_locked_reason ?? ''),
      routeHeadline: String(st?.route_headline ?? ''),
      routeNotice: String(st?.route_local_notice ?? ''),
      loaded: true,
    });
    // Однократное сообщение о смене маршрута: показывается тому, у кого работа шла через
    // свой Claude Code. Признак durable — переживает закрытие программы до показа.
    if (st?.route_notice_pending) {
      routeChangedNotice = String(st?.route_changed_notice ?? '');
    }
    return true;
  } catch (e) {
    // 🔴 Отказ чтения НЕ выдаётся за левое положение и не выдаётся за правое: остаётся
    // «не прочитано». Прежний код в этом месте выставлял всё в false и загорался
    // положением по умолчанию — то есть утверждал маршрут, которого не проверял.
    console.warn('положение режима работы не прочитано', e);
    cloudConsent.set({
      advisorsEnabled: false,
      granted: false,
      localOnly: false,
      gatewayBuiltIn: false,
      routeCloud: false,
      routeLocked: false,
      routeLockedReason: '',
      routeHeadline: '',
      routeNotice: '',
      loaded: false,
    });
    return false;
  }
}

/**
 * Фактическое положение для интерфейса.
 *
 * `known === false` — положение не прочитано: ассистент молчит, подпись говорит «н/д».
 * @type {import('svelte/store').Readable<{known: boolean, cloud: boolean, locked: boolean, lockedReason: string, headline: string, notice: string, advisorsEnabled: boolean}>}
 */
export const assistantRoute = derived(cloudConsent, ($c) => {
  const known = !!$c.loaded;
  return {
    known,
    cloud: known && !!$c.routeCloud,
    locked: known && !!$c.routeLocked,
    lockedReason: known ? String($c.routeLockedReason || '') : '',
    headline: known && $c.routeHeadline ? String($c.routeHeadline) : HEADLINE_UNKNOWN,
    notice: known && $c.routeNotice ? String($c.routeNotice) : NOTICE_UNKNOWN,
    advisorsEnabled: !!$c.advisorsEnabled,
  };
});

/**
 * Можно ли обращаться к ассистенту прямо сейчас. Непрочитанное положение — нельзя.
 * @type {import('svelte/store').Readable<boolean>}
 */
export const assistantAvailable = derived(assistantRoute, ($r) => $r.known && $r.cloud);
