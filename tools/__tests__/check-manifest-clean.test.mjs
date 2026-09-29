// Проверки чистоты манифеста (tools/check-manifest-clean.mjs) — N24 s58, V70, H-3 аудита плана.
//
// 🔴 Зачем набор. Проверка стоит в `beforeBuildCommand` базового tauri.conf.json и потому
// исполняется ВНУТРИ облачной сборки — при подменённом манифесте, резерве и живом замке.
// Прежняя версия отказала бы ей по трём признакам сразу и остановила бы выпуск. Здесь —
// дерево-фикстура в каждом из состояний: своя облачная сборка обязана проходить, обычная
// сборка с грязным манифестом и обычная сборка во время ЧУЖОЙ облачной — останавливаться.
import { describe, it, expect, afterEach } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inspectTree, treePaths, CLOUD_BUILD_ENV } from '../check-manifest-clean.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const CLEAN_MANIFEST = '[package]\nname = "aurora-econometrica-gui"\n\n[dependencies]\ntauri = "2"\n';
const DIRTY_MANIFEST = `${CLEAN_MANIFEST}aurora_gateway = { git = "x", tag = "y" }\n`;
const CLEAN_LOCK = '[[package]]\nname = "tauri"\n';
/** Номер, которого заведомо нет среди живых процессов. */
const DEAD_PID = 2147483000;

const dirs = [];
afterEach(() => {
  while (dirs.length > 0) rmSync(dirs.pop(), { recursive: true, force: true });
});

/** Дерево-фикстура: только те файлы, что смотрит проверка. */
function tree({
  manifest = CLEAN_MANIFEST, lock = CLEAN_LOCK, manifestBackup, lockBackup, runLock,
} = {}) {
  const root = mkdtempSync(join(tmpdir(), 'manifest-clean-'));
  dirs.push(root);
  mkdirSync(join(root, 'src-tauri'));
  const p = treePaths(root);
  writeFileSync(p.manifest, manifest);
  writeFileSync(p.lockfile, lock);
  if (manifestBackup !== undefined) writeFileSync(p.manifestBackup, manifestBackup);
  if (lockBackup !== undefined) writeFileSync(p.lockfileBackup, lockBackup);
  if (runLock !== undefined) writeFileSync(p.runLock, JSON.stringify(runLock));
  return root;
}

/** Состояние дерева посреди облачной сборки — ровно то, что пишет build-cloud.mjs. */
function midCloudBuild(pid, overrides = {}) {
  return tree({
    manifest: DIRTY_MANIFEST,
    manifestBackup: CLEAN_MANIFEST,
    lockBackup: CLEAN_LOCK,
    runLock: { pid, started: '2026-09-29T10:00:00.000Z' },
    ...overrides,
  });
}

describe('обычная сборка', () => {
  it('чистое дерево проходит', () => {
    const { problems, ownCloudBuild } = inspectTree(tree(), {});
    expect(problems).toEqual([]);
    expect(ownCloudBuild).toBeNull();
  });

  it('грязный манифест останавливает (V70)', () => {
    const { problems } = inspectTree(tree({ manifest: DIRTY_MANIFEST }), {});
    expect(problems.join('\n')).toMatch(/обычный манифест упоминает крейт шлюза/);
  });

  it('брошенный резерв останавливает', () => {
    const { problems } = inspectTree(tree({ manifestBackup: CLEAN_MANIFEST }), {});
    expect(problems.join('\n')).toMatch(/остался служебный файл облачной сборки/);
  });
});

describe('облачная сборка изнутри (H-3 аудита плана 2.5.9)', () => {
  it('своя облачная сборка — номер в переменной совпадает с живым замком — проходит', () => {
    const root = midCloudBuild(process.pid);
    const { problems, ownCloudBuild } = inspectTree(root, { [CLOUD_BUILD_ENV]: String(process.pid) });
    expect(problems).toEqual([]);
    expect(ownCloudBuild && ownCloudBuild.pid).toBe(process.pid);
  });

  it('то же состояние БЕЗ переменной — обычная сборка во время облачной — останавливается', () => {
    const { problems } = inspectTree(midCloudBuild(process.pid), {});
    const text = problems.join('\n');
    expect(text).toMatch(/облачная сборка идёт прямо сейчас/);
    expect(text).toMatch(/обычный манифест упоминает крейт шлюза/);
  });

  it('переменная с ЧУЖИМ номером ничего не снимает', () => {
    const { problems, ownCloudBuild } = inspectTree(
      midCloudBuild(process.pid),
      { [CLOUD_BUILD_ENV]: String(process.pid + 1) },
    );
    expect(ownCloudBuild).toBeNull();
    expect(problems.length).toBeGreaterThan(0);
  });

  it('переменная, совпавшая с замком МЁРТВОГО прогона, ничего не снимает', () => {
    const { problems, ownCloudBuild } = inspectTree(
      midCloudBuild(DEAD_PID),
      { [CLOUD_BUILD_ENV]: String(DEAD_PID) },
    );
    expect(ownCloudBuild).toBeNull();
    expect(problems.join('\n')).toMatch(/остался служебный файл облачной сборки/);
  });

  it('переменная без замка ничего не снимает: грязный манифест — отказ', () => {
    const { problems } = inspectTree(
      tree({ manifest: DIRTY_MANIFEST }),
      { [CLOUD_BUILD_ENV]: String(process.pid) },
    );
    expect(problems.join('\n')).toMatch(/обычный манифест упоминает крейт шлюза/);
  });

  it('своя облачная сборка, но резерв манифеста с крейтом шлюза — отказ', () => {
    const root = midCloudBuild(process.pid, { manifestBackup: DIRTY_MANIFEST });
    const { problems } = inspectTree(root, { [CLOUD_BUILD_ENV]: String(process.pid) });
    expect(problems.join('\n')).toMatch(/резерв обычного манифеста упоминает крейт шлюза/);
  });

  it('своя облачная сборка без резерва манифеста — отказ', () => {
    const root = midCloudBuild(process.pid);
    rmSync(treePaths(root).manifestBackup);
    const { problems } = inspectTree(root, { [CLOUD_BUILD_ENV]: String(process.pid) });
    expect(problems.join('\n')).toMatch(/резерва обычного манифеста нет/);
  });
});

describe('место вызова (V70)', () => {
  const conf = JSON.parse(readFileSync(join(HERE, '..', '..', 'src-tauri', 'tauri.conf.json'), 'utf8'));
  const local = JSON.parse(readFileSync(join(HERE, '..', '..', 'src-tauri', 'tauri.local.conf.json'), 'utf8'));
  const pkg = JSON.parse(readFileSync(join(HERE, '..', '..', 'package.json'), 'utf8'));

  it('beforeBuildCommand базовой настройки начинается с проверки манифеста', () => {
    expect(conf.build.beforeBuildCommand).toMatch(/^npm run check:manifest && /);
    expect(pkg.scripts['check:manifest']).toBe('node tools/check-manifest-clean.mjs');
  });

  it('оверлей локальной редакции проверку не переопределяет — tauri:build:local её наследует', () => {
    expect(pkg.scripts['tauri:build:local']).toMatch(/--config src-tauri\/tauri\.local\.conf\.json/);
    expect(local.build && local.build.beforeBuildCommand).toBeUndefined();
  });
});
