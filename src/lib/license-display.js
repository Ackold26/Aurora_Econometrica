/**
 * Определение приоритетного статуса лицензии для экрана Настроек (#61, LI-001 fix).
 *
 * Два независимых источника лицензирования (CLAUDE.md правило 8):
 *   - online_auth.rs (check_online_auth) — приоритетный онлайн-путь
 *   - license.rs (get_license_status)    — офлайн Ed25519 fallback
 *
 * Баг LI-001: Настройки учитывали только onlineStatus → при offline (exception
 * или status='offline'/'blocked') показывали «не подтверждена», игнорируя
 * валидную офлайн-лицензию. Эта функция — единый источник истины приоритета.
 *
 * Приоритет: онлайн-подтверждение → валидная офлайн-лицензия → кэш онлайн-авторизации → ничего.
 * Локальная Ed25519-лицензия (offline-valid) важнее устаревшего кэша (cached): она
 * криптографически проверена сейчас, кэш — снимок прошлого ответа сервера.
 *
 * @param {{status?: string}|null|undefined} onlineStatus - ответ check_online_auth
 * @param {{valid?: boolean}|null|undefined} licenseStatus - ответ get_license_status
 * @returns {'online-ok'|'offline-valid'|'cached'|'none'}
 */
export function resolveLicenseTier(onlineStatus, licenseStatus) {
  if (onlineStatus?.status === 'ok') return 'online-ok';
  if (licenseStatus?.valid) return 'offline-valid';
  if (onlineStatus?.status === 'cached') return 'cached';
  return 'none';
}
