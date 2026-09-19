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
 * отсутствия гейта: создаёт видимость защиты. Этот файл — единственная точка,
 * которую обязаны пройти все локальные сценарии поставки (build-cloud.mjs
 * у Econometrica/Creative Hub, обёртка ship.mjs у Oracle).
 *
 * Что проверяет, в этом порядке (первый провал — стоп, дальше не идёт):
 *   1. Рабочее дерево чистое (git status --porcelain пуст).
 *   2. Текущий HEAD отправлен в origin (не расходится с origin/<ветка>).
 *   3. CI (workflow ci.yml) на текущем коммите — success, через `gh run list --commit`.
 *
 * Исключение — оба флага сразу, иначе исключения нет:
 *   AURORA_SHIP_OVERRIDE=1
 *   AURORA_SHIP_OVERRIDE_REASON="<причина одной строкой, не пусто>"
 * Исключение печатает предупреждение и пишет запись в ship-log.jsonl рядом
 * с этим файлом (append-only, не перезаписывается) — причина обхода не
 * теряется, даже если поставка ушла по решению момента.
 *
 * Нет `gh` в PATH, нет ответа GitHub, нет ни одного прогона на этом коммите —
 * ЗАКРЫТО (провал), не пропуск. Гейт, который молчит при неопределённости,
 * ничем не отличается от гейта, которого нет.
 */

import { execFileSync } from 'node:child_process';
import { appendFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const LOG_PATH = join(HERE, 'ship-log.jsonl');

function run(cmd, args) {
    try {
        return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
    } catch (e) {
        return { error: true, message: e.stderr?.toString().trim() || e.message };
    }
}

function log(entry) {
    try {
        appendFileSync(LOG_PATH, JSON.stringify({ ts: new Date().toISOString(), ...entry }) + '\n', 'utf8');
    } catch { /* журнал не должен ронять гейт */ }
}

function fail(reason, detail) {
    console.error(`\n[ship-gate] ОТКАЗ: ${reason}`);
    if (detail) console.error(`[ship-gate]   ${detail}`);
    log({ result: 'blocked', reason, detail: detail || null, cwd: process.cwd() });
    process.exit(1);
}

function maybeOverride(reason, detail) {
    const on = process.env.AURORA_SHIP_OVERRIDE === '1';
    const why = (process.env.AURORA_SHIP_OVERRIDE_REASON || '').trim();
    if (on && why) {
        console.warn(`\n[ship-gate] ⚠ ИСКЛЮЧЕНИЕ применено: ${reason}`);
        console.warn(`[ship-gate]   Причина владельца: "${why}"`);
        log({ result: 'overridden', reason, detail: detail || null, override_reason: why, cwd: process.cwd() });
        return true;
    }
    if (on && !why) {
        fail('AURORA_SHIP_OVERRIDE=1 задан без AURORA_SHIP_OVERRIDE_REASON', 'Причина обхода обязательна — без неё исключение не применяется.');
    }
    fail(reason, detail);
}

function main() {
    // 1. Рабочее дерево чистое
    const status = run('git', ['status', '--porcelain']);
    if (typeof status !== 'string') fail('не удалось выполнить git status', status.message);
    if (status.length > 0) {
        const lines = status.split('\n').length;
        if (!maybeOverride('рабочее дерево не чистое', `${lines} незакоммиченных путей — сборка ушла бы не из того, что в истории`)) return;
    }

    // 2. HEAD отправлен в origin
    const branch = run('git', ['rev-parse', '--abbrev-ref', 'HEAD']);
    if (typeof branch !== 'string') fail('не удалось определить текущую ветку', branch.message);
    const headSha = run('git', ['rev-parse', 'HEAD']);
    if (typeof headSha !== 'string') fail('не удалось определить HEAD', headSha.message);
    const remoteSha = run('git', ['rev-parse', `origin/${branch}`]);
    if (typeof remoteSha !== 'string') {
        if (!maybeOverride('нет ветки origin/' + branch, 'локальная ветка не отправлена или не отслеживает удалённую — CI по ней не запускался')) return;
    } else if (remoteSha !== headSha) {
        if (!maybeOverride('локальный HEAD расходится с origin/' + branch, `локально ${headSha.slice(0, 7)}, на origin ${remoteSha.slice(0, 7)} — CI проверял не этот коммит`)) return;
    }

    // 3. CI на этом коммите зелёный
    const ghCheck = run('gh', ['--version']);
    if (typeof ghCheck !== 'string') {
        if (!maybeOverride('gh CLI недоступен', 'без него статус CI не проверить — закрыто, не пропущено')) return;
    } else {
        const originUrl = run('git', ['remote', 'get-url', 'origin']);
        const repoMatch = typeof originUrl === 'string' ? originUrl.match(/github\.com[:/]([^/]+\/[^/.]+)(\.git)?$/) : null;
        if (!repoMatch) {
            if (!maybeOverride('не удалось определить репозиторий GitHub из origin', String(originUrl))) return;
        } else {
            const repo = repoMatch[1];
            const runsRaw = run('gh', ['run', 'list', '-R', repo, '--commit', headSha, '--workflow', 'ci.yml', '-L', '1',
                '--json', 'conclusion,status,createdAt,url']);
            if (typeof runsRaw !== 'string') {
                if (!maybeOverride('не удалось запросить прогоны CI', runsRaw.message)) return;
            } else {
                let runs;
                try { runs = JSON.parse(runsRaw); } catch { runs = null; }
                if (!Array.isArray(runs) || runs.length === 0) {
                    if (!maybeOverride('на этом коммите нет ни одного прогона CI (workflow ci.yml)', `коммит ${headSha.slice(0, 7)} — CI по нему не запускался`)) return;
                } else {
                    const latest = runs[0];
                    if (latest.status !== 'completed' || latest.conclusion !== 'success') {
                        if (!maybeOverride('CI на этом коммите не зелёный', `status=${latest.status} conclusion=${latest.conclusion} ${latest.url || ''}`)) return;
                    }
                }
            }
        }
    }

    console.log('[ship-gate] пройден: дерево чистое, HEAD отправлен, CI зелёный.');
    log({ result: 'passed', sha: headSha, branch, cwd: process.cwd() });
}

main();
