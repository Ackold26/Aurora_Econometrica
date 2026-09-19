#!/usr/bin/env node
/**
 * Гейт поставки перед сборкой установщика (решение владельца, 2026-09-19).
 *
 * 🔴 Зачем этот файл. Три продукта ядра (Synthetic Research, MMM Optimizer,
 * Creative Center) отгружались клиентам сборкой из рабочего дерева локальным
 * скриптом, минуя CI. За последние трое суток CI каждого из трёх — красный
 * (Frontend tests / Prompt & delivery linters + Pytest / Rust tests), но это
 * не остановило ни одну поставку: гейт СУЩЕСТВОВАЛ (задание Build Release с
 * needs: check в .github/workflows/ci.yml), но локальный путь поставки его
 * не спрашивал. Не «гейта нет» — гейт есть, красный, и его обходят. Это хуже
 * отсутствия гейта: создаёт видимость защиты. Этот файл — точка, которую
 * проходит `build-cloud.mjs` во всех трёх продуктах (Oracle/Econometrica/
 * Creative Hub) на боевом пути сборки.
 *
 * 🔴 Известный НЕЗАКРЫТЫЙ обход (внешний аудит 19.09, High, не патчено
 * намеренно — требует дизайна, не заплатки): `npm run tauri -- build` и
 * `npm run tauri:build:local` (Econometrica) зовут `tauri` CLI напрямую, минуя
 * `build-cloud.mjs`, и этот файл их не видит. `pretauri`-хук в package.json —
 * не решение: `tauri` вызывается и для `dev`/`info`/`icon`, гонять гейт перед
 * каждым из них неверно, а различить подкоманду в pre-хуке без доп. работы
 * нельзя. Отдельная задача, не в этом файле.
 *
 * Что проверяет, в этом порядке (первый провал — стоп, дальше не идёт):
 *   1. Рабочее дерево чистое (git status --porcelain пуст).
 *   2. HEAD НЕ отсоединён (не detached) и отправлен в origin (совпадает с origin/<ветка>).
 *   3. CI (workflow ci.yml) на текущем коммите — success, через `gh run list --commit`,
 *      причём success должен быть у ВСЕХ завершённых прогонов на этом коммите,
 *      не только у первого попавшегося (может быть несколько ручных перезапусков).
 *
 * Исключение — ТОЧЕЧНОЕ, не глобальное (правка после аудита 19.09, Critical).
 * Три переменные окружения, все обязательны разом:
 *   AURORA_SHIP_OVERRIDE=1
 *   AURORA_SHIP_OVERRIDE_REASON="<причина одной строкой, не пусто>"
 *   AURORA_SHIP_OVERRIDE_SCOPE=tree|push|ci   — какую ИМЕННО проверку обходим
 * 🔴 Раньше (до аудита) одна пара переменных обходила ЛЮБУЮ провалившуюся
 * проверку в рамках всего прогона — то есть исключение, названное для одной
 * причины («грязное дерево»), молча снимало заодно проверку HEAD и проверку
 * CI. Проверено живым прогоном: одна причина «проверка охвата исключения»
 * обошла все три ступени и напечатала «пройден: дерево чистое, HEAD
 * отправлен, CI зелёный» — при том что ничего из этого не было правдой.
 * Теперь `AURORA_SHIP_OVERRIDE_SCOPE` обязан совпадать с конкретной
 * проверкой, и разрешение расходуется ОДИН раз за прогон: вторая
 * провалившаяся проверка в том же процессе получает безусловный отказ,
 * даже если флаги всё ещё стоят в окружении.
 *
 * Финальное сообщение о прохождении печатается ТОЛЬКО если ни одно
 * исключение не применялось. Если применялось — печатается явно
 * «пройден С ИСКЛЮЧЕНИЕМ», со списком того, что именно обойдено (было:
 * безусловное «пройден: дерево чистое, HEAD отправлен, CI зелёный» — ложь
 * в случае применённого исключения, найдено тем же аудитом).
 *
 * Запись исключения в журнал ship-log.jsonl ОБЯЗАНА пройти успешно, иначе
 * исключение НЕ применяется (безопасный отказ вместо исключения без следа).
 * Обычные проходы/отказы БЕЗ исключения журнал пишут по возможности —
 * сбой записи их не блокирует (гейт не должен зависеть от диска для
 * штатного пути).
 *
 * Нет `gh` в PATH, нет ответа GitHub, нет ни одного прогона на этом коммите —
 * ЗАКРЫТО (провал), не пропуск. Гейт, который молчит при неопределённости,
 * ничем не отличается от гейта, которого нет.
 */

import { execFileSync } from 'node:child_process';
import { appendFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

function run(cmd, args, opts) {
    try {
        return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], ...opts }).trim();
    } catch (e) {
        return { error: true, message: e.stderr?.toString().trim() || e.message };
    }
}

// Корень дерева, которое сейчас проверяется (cwd процесса), а не каталог,
// где физически лежит этот файл. Разошлись бы, если гейт одного репозитория
// запустить с cwd другого репозитория (находка Medium, аудит 19.09) —
// журнал ложился бы не в тот репозиторий, который проверяется.
const repoRoot = run('git', ['rev-parse', '--show-toplevel']);
const LOG_PATH = typeof repoRoot === 'string'
    ? join(repoRoot, 'tools', 'ship-log.jsonl')
    : join(dirname(fileURLToPath(import.meta.url)), 'ship-log.jsonl');

function logStrict(entry) {
    appendFileSync(LOG_PATH, JSON.stringify({ ts: new Date().toISOString(), ...entry }) + '\n', 'utf8');
}

function logBestEffort(entry) {
    try { logStrict(entry); } catch { /* штатный путь не должен зависеть от диска */ }
}

function fail(reason, detail) {
    console.error(`\n[ship-gate] ОТКАЗ: ${reason}`);
    if (detail) console.error(`[ship-gate]   ${detail}`);
    logBestEffort({ result: 'blocked', reason, detail: detail || null, cwd: process.cwd() });
    process.exit(1);
}

const OVERRIDE_SPENT = { used: false };
const SCOPE_BY_STEP = { tree: 'дерево', push: 'HEAD/push', ci: 'CI' };

/**
 * Точечное исключение. `step` — 'tree' | 'push' | 'ci'. Возвращает true,
 * если исключение применено (вызывающий код продолжает), иначе завершает
 * процесс через fail() и не возвращается вовсе.
 */
function maybeOverride(step, reason, detail) {
    const on = process.env.AURORA_SHIP_OVERRIDE === '1';
    const why = (process.env.AURORA_SHIP_OVERRIDE_REASON || '').trim();
    const scope = (process.env.AURORA_SHIP_OVERRIDE_SCOPE || '').trim();

    if (!on) fail(reason, detail);
    if (!why) fail('AURORA_SHIP_OVERRIDE=1 задан без AURORA_SHIP_OVERRIDE_REASON', 'Причина обхода обязательна — без неё исключение не применяется.');
    if (!(scope === 'tree' || scope === 'push' || scope === 'ci')) {
        fail('AURORA_SHIP_OVERRIDE=1 задан без корректного AURORA_SHIP_OVERRIDE_SCOPE',
            'Ожидается tree|push|ci — исключение обязано называть КОНКРЕТНУЮ проверку, которую обходит, а не действовать на любую провалившуюся.');
    }
    if (scope !== step) {
        fail(reason, `${detail || ''} (исключение задано для проверки "${scope}", а провалилась "${step}" — не применяется к чужой проверке)`.trim());
    }
    if (OVERRIDE_SPENT.used) {
        fail(reason, `${detail || ''} (исключение уже израсходовано на предыдущей проверке в этом прогоне — второе исключение за один прогон не выдаётся)`.trim());
    }

    // Запись исключения обязана пройти — иначе исключения без следа быть не должно.
    try {
        logStrict({ result: 'overridden', step, reason, detail: detail || null, override_reason: why, cwd: process.cwd() });
    } catch (e) {
        fail('не удалось записать применение исключения в журнал — исключение не применяется',
            `${LOG_PATH}: ${e.message}. Без записи в журнал обход неотличим от отсутствия проверки.`);
    }

    console.warn(`\n[ship-gate] ⚠ ИСКЛЮЧЕНИЕ применено к проверке «${SCOPE_BY_STEP[step]}»: ${reason}`);
    console.warn(`[ship-gate]   Причина владельца: "${why}"`);
    OVERRIDE_SPENT.used = true;
    return true;
}

function main() {
    const appliedOverrides = [];

    // 1. Рабочее дерево чистое
    const status = run('git', ['status', '--porcelain']);
    if (typeof status !== 'string') fail('не удалось выполнить git status', status.message);
    if (status.length > 0) {
        const lines = status.split('\n').length;
        maybeOverride('tree', 'рабочее дерево не чистое', `${lines} незакоммиченных путей — сборка ушла бы не из того, что в истории`);
        appliedOverrides.push('дерево не проверялось на чистоту');
    }

    // 2. HEAD не отсоединён и отправлен в origin.
    // 🔴 Правка после аудита 19.09 (High): прежняя версия при detached HEAD
    // получала branch === 'HEAD' и сравнивала с `origin/HEAD` — а это ссылка,
    // которая в обычном клоне УСПЕШНО разрешается (symbolic-ref на ветку по
    // умолчанию), а не выдаёт ошибку, как предполагалось. Из-за этого
    // отсоединённое состояние ровно на вершине ветки по умолчанию проходило
    // бы проверку молча. Detached HEAD теперь ловится ЯВНО, до какого-либо
    // сравнения с origin, через `git symbolic-ref` — единственный надёжный
    // способ отличить «на ветке» от «оторван», проверено вживую 19.09
    // (`git rev-parse origin/HEAD` вернул реальный SHA, не ошибку).
    const symbolicRef = run('git', ['symbolic-ref', '-q', 'HEAD']);
    const isDetached = typeof symbolicRef !== 'string' || symbolicRef.length === 0;
    const headSha = run('git', ['rev-parse', 'HEAD']);
    if (typeof headSha !== 'string') fail('не удалось определить HEAD', headSha.message);

    let branch = null;
    if (isDetached) {
        maybeOverride('push', 'HEAD отсоединён (detached) — не на именованной ветке',
            'сборка из detached HEAD не может быть сопоставлена ни с какой веткой origin — CI по такому состоянию не идентифицируем однозначно');
        appliedOverrides.push('detached HEAD не проверялся на отправку в origin');
    } else {
        branch = run('git', ['rev-parse', '--abbrev-ref', 'HEAD']);
        if (typeof branch !== 'string') fail('не удалось определить текущую ветку', branch.message);

        // Обновить remote-tracking ссылку перед сравнением — иначе force-push
        // коллеги на удалённой ветке останется незамеченным (Medium, аудит 19.09):
        // без fetch локальный `origin/<ветка>` продолжает указывать на старый
        // коммит, который CI когда-то зазеленил, и гейт пропустит поставку
        // коммита, которого в истории origin уже нет.
        const fetchResult = run('git', ['fetch', 'origin', branch, '--quiet']);
        if (typeof fetchResult !== 'string') {
            maybeOverride('push', 'не удалось обновить origin/' + branch + ' перед сравнением',
                `git fetch завершился ошибкой: ${fetchResult.message} — сравнение пошло бы по устаревшим данным`);
            appliedOverrides.push('сверка с origin выполнена по возможно устаревшим данным (fetch не удался)');
        } else {
            const remoteSha = run('git', ['rev-parse', `origin/${branch}`]);
            if (typeof remoteSha !== 'string') {
                maybeOverride('push', 'нет ветки origin/' + branch,
                    'локальная ветка не отправлена или не отслеживает удалённую — CI по ней не запускался');
                appliedOverrides.push('ветка origin не найдена, сверка с ней не выполнена');
            } else if (remoteSha !== headSha) {
                maybeOverride('push', 'локальный HEAD расходится с origin/' + branch,
                    `локально ${headSha.slice(0, 7)}, на origin ${remoteSha.slice(0, 7)} — CI проверял не этот коммит`);
                appliedOverrides.push('расхождение с origin не остановило сборку');
            }
        }
    }

    // 3. CI на этом коммите зелёный — у ВСЕХ завершённых прогонов, не только у первого.
    const ghCheck = run('gh', ['--version']);
    if (typeof ghCheck !== 'string') {
        maybeOverride('ci', 'gh CLI недоступен', 'без него статус CI не проверить — закрыто, не пропущено');
        appliedOverrides.push('CI не проверялся (gh CLI недоступен)');
    } else {
        const repo = run('gh', ['repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner']);
        // 🔴 Правка после аудита 19.09 (Medium): раньше репозиторий вычислялся
        // собственным regex по `git remote get-url origin` — ломался на точке
        // в имени репозитория, на ssh:// с портом, на завершающем слеше.
        // `gh repo view` знает это сам, из настоящего API GitHub, а не догадкой.
        if (typeof repo !== 'string') {
            maybeOverride('ci', 'не удалось определить репозиторий GitHub', String(repo.message || repo));
            appliedOverrides.push('CI не проверялся (репозиторий не определён)');
        } else {
            // Берём с запасом (20), не один — на коммите может быть несколько
            // завершённых прогонов (ручной re-run), и порядок выдачи API не
            // гарантирован контрактом (Medium, аудит 19.09). Требуем success
            // от КАЖДОГО завершённого прогона, а не от первого попавшегося.
            const runsRaw = run('gh', ['run', 'list', '-R', repo, '--commit', headSha, '--workflow', 'ci.yml', '-L', '20',
                '--json', 'conclusion,status,createdAt,url']);
            if (typeof runsRaw !== 'string') {
                maybeOverride('ci', 'не удалось запросить прогоны CI', runsRaw.message);
                appliedOverrides.push('CI не проверялся (запрос к GitHub не удался)');
            } else {
                let runs;
                try { runs = JSON.parse(runsRaw); } catch { runs = null; }
                if (!Array.isArray(runs) || runs.length === 0) {
                    maybeOverride('ci', 'на этом коммите нет ни одного прогона CI (workflow ci.yml)',
                        `коммит ${headSha.slice(0, 7)} — CI по нему не запускался`);
                    appliedOverrides.push('CI не проверялся (прогонов нет)');
                } else {
                    const completed = runs.filter((r) => r.status === 'completed');
                    const notSuccess = completed.filter((r) => r.conclusion !== 'success');
                    const stillRunning = runs.length - completed.length;
                    if (completed.length === 0) {
                        maybeOverride('ci', 'на этом коммите нет ЗАВЕРШЁННЫХ прогонов CI',
                            `${runs.length} прогон(ов), все ещё выполняются — подождите`);
                        appliedOverrides.push('CI не проверялся (все прогоны ещё выполняются)');
                    } else if (notSuccess.length > 0) {
                        const bad = notSuccess[0];
                        maybeOverride('ci', 'CI на этом коммите не зелёный',
                            `${notSuccess.length} из ${completed.length} завершённых прогонов не success (напр. status=${bad.status} conclusion=${bad.conclusion} ${bad.url || ''})`);
                        appliedOverrides.push('красный CI не остановил сборку');
                    } else if (stillRunning > 0) {
                        // Все завершённые — success, но есть ещё выполняющиеся: не блокируем,
                        // но и не молчим — печатаем как есть в конечном сообщении по необходимости.
                        console.log(`[ship-gate] предупреждение: ${stillRunning} прогон(ов) CI ещё выполняется, завершённые (${completed.length}) — все success.`);
                    }
                }
            }
        }
    }

    if (appliedOverrides.length === 0) {
        console.log('[ship-gate] пройден: дерево чистое, HEAD отправлен, CI зелёный.');
        logBestEffort({ result: 'passed', sha: headSha, branch, cwd: process.cwd() });
    } else {
        console.warn(`\n[ship-gate] пройден С ИСКЛЮЧЕНИЕМ: ${appliedOverrides.join('; ')}.`);
        logBestEffort({ result: 'passed_with_override', sha: headSha, branch, applied: appliedOverrides, cwd: process.cwd() });
    }
}

main();
