// Проверки сторожа состава поставки (tools/check-gateway-in-build.mjs) — N23 s58.
//
// 🔴 Зачем набор. Сторож написан 17.08 и до s58 не звался ниоткуда; проверять он умел
// только распакованный бинарь, а публикуется установщик. Здесь — разбор списка
// установщика, вердикт по байтам и прогон самой команды на архиве-фикстуре (7-Zip
// собирает его из поддельного бинаря продукта): со шлюзом — проход, без — отказ.
// Прогон на НАСТОЯЩИХ установщиках линейки — отдельно и только если они есть на машине.
import { describe, it, expect, afterEach } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import {
  isInstaller, installerTopLevelExes, judge, find7zip,
} from '../check-gateway-in-build.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const GUARD = join(HERE, '..', 'check-gateway-in-build.mjs');
const SEVEN_ZIP = find7zip();
const NSIS = 'D:/cargo-targets/ai-agency/release/bundle/nsis';
const REAL_WITH_GATEWAY = `${NSIS}/Optimizer MMM_2.5.8_x64-setup.exe`;
/** Поставка 2.4.10 уехала без шлюза (CPD-87) — живой образец того, что сторож обязан ловить. */
const REAL_WITHOUT_GATEWAY = `${NSIS}/Optimizer MMM_2.4.10_x64-setup.exe`;

const dirs = [];
afterEach(() => {
  while (dirs.length > 0) rmSync(dirs.pop(), { recursive: true, force: true });
});

function tempDir() {
  const dir = mkdtempSync(join(tmpdir(), 'gateway-guard-'));
  dirs.push(dir);
  return dir;
}

/** Байты «бинаря продукта»: контроль есть всегда, остальное — по сценарию. */
function productBytes({ gateway }) {
  const parts = ['\0cabinets.json\0content-packs\0'];
  parts.push(gateway
    ? 'gateway_executor\0aurora_gateway::cloud\0'
    : 'Облачный режим не входит в эту сборку\0');
  return Buffer.from(parts.join(''), 'utf8');
}

function runGuard(target) {
  return spawnSync(process.execPath, [GUARD, target], { encoding: 'utf8' });
}

describe('isInstaller', () => {
  it('узнаёт установщик по -setup/_setup и не путает с бинарём продукта', () => {
    expect(isInstaller('D:/x/Optimizer MMM_2.5.8_x64-setup.exe')).toBe(true);
    expect(isInstaller('D:/x/app_setup.exe')).toBe(true);
    expect(isInstaller('D:/x/aurora-econometrica-gui.exe')).toBe(false);
    expect(isInstaller('D:/x/setup-notes.txt')).toBe(false);
  });
});

describe('installerTopLevelExes — что из установщика судить', () => {
  const listing = [
    '--',
    'Path = D:\\cargo-targets\\release\\bundle\\nsis\\Optimizer MMM_2.5.8_x64-setup.exe',
    'Type = Nsis',
    '',
    '----------',
    'Path = $PLUGINSDIR\\modern-wizard.bmp',
    '',
    'Path = aurora-econometrica-gui.exe',
    'Size = 16015872',
    '',
    'Path = _up_\\sidecar\\econometrica\\econometrica-sidecar.exe',
    '',
    'Path = uninstall.exe',
  ].join('\r\n');

  it('берёт только верхний уровень и не берёт программу удаления', () => {
    expect(installerTopLevelExes(listing)).toEqual(['aurora-econometrica-gui.exe']);
  });

  it('путь к самому архиву (до черты) за содержимое не принимает', () => {
    const header = 'Path = setup.exe\r\nType = Nsis\r\n';
    expect(installerTopLevelExes(header)).toEqual([]);
  });
});

describe('judge — вердикт по байтам', () => {
  it('шлюз есть, строки «облачного режима нет» нет — проход', () => {
    expect(judge(productBytes({ gateway: true })).state).toBe('шлюз-есть');
  });

  it('имён шлюза нет, обратный признак на месте — отказ', () => {
    expect(judge(productBytes({ gateway: false })).state).toBe('шлюза-нет');
  });
});

describe.skipIf(!SEVEN_ZIP)('прогон команды на установщике-фикстуре (нужен 7-Zip)', () => {
  /** Архив с именем установщика: бинарь продукта наверху, спутник во вложенном каталоге. */
  function fixtureInstaller({ gateway }) {
    const dir = tempDir();
    const payload = join(dir, 'payload');
    const nested = join(payload, '_up_');
    mkdirSync(nested, { recursive: true });
    writeFileSync(join(payload, 'aurora-econometrica-gui.exe'), productBytes({ gateway }));
    // Спутник С шлюзом во вложенном каталоге: если сторож возьмёт его вместо верхнего
    // уровня, установщик без шлюза ложно пройдёт.
    writeFileSync(join(nested, 'helper.exe'), productBytes({ gateway: true }));
    writeFileSync(join(payload, 'uninstall.exe'), Buffer.from('uninstall'));
    const installer = join(dir, 'Optimizer MMM_9.9.9_x64-setup.exe');
    const pack = spawnSync(SEVEN_ZIP, ['a', '-tzip', installer, '.\\*'], { cwd: payload, encoding: 'utf8' });
    expect(pack.status).toBe(0);
    return installer;
  }

  it('установщик со шлюзом — проход', () => {
    const run = runGuard(fixtureInstaller({ gateway: true }));
    expect(run.status).toBe(0);
    expect(run.stdout).toMatch(/→ aurora-econometrica-gui\.exe: шлюз Авроры в поставке/);
  });

  it('установщик без шлюза — отказ, спутник со шлюзом во вложенном каталоге не выручает', () => {
    const run = runGuard(fixtureInstaller({ gateway: false }));
    expect(run.status).toBe(1);
    expect(run.stderr).toMatch(/ОТКАЗ/);
    expect(run.stderr).toMatch(/поставка собрана штатной командой/);
  });

  it('одноимённый бинарь СО шлюзом во вложенном каталоге не подменяет верхний без шлюза', () => {
    const dir = tempDir();
    const payload = join(dir, 'payload');
    mkdirSync(join(payload, '_up_'), { recursive: true });
    writeFileSync(join(payload, 'aurora-econometrica-gui.exe'), productBytes({ gateway: false }));
    writeFileSync(join(payload, '_up_', 'aurora-econometrica-gui.exe'), productBytes({ gateway: true }));
    const installer = join(dir, 'Optimizer MMM_9.9.9_x64-setup.exe');
    expect(spawnSync(SEVEN_ZIP, ['a', '-tzip', installer, '.\\*'], { cwd: payload }).status).toBe(0);
    const run = runGuard(installer);
    expect(run.status).toBe(1);
    expect(run.stderr).toMatch(/поставка собрана штатной командой/);
  });

  it('установщик, который 7-Zip не читает, — отказ, а не пропуск', () => {
    const dir = tempDir();
    const broken = join(dir, 'Broken_1.0.0_x64-setup.exe');
    writeFileSync(broken, Buffer.from('это не архив'));
    const run = runGuard(broken);
    expect(run.status).toBe(1);
    expect(run.stderr).toMatch(/7-Zip не смог прочитать установщик/);
  });
});

describe.skipIf(!SEVEN_ZIP || !existsSync(REAL_WITH_GATEWAY) || !existsSync(REAL_WITHOUT_GATEWAY))(
  'настоящие установщики линейки (только чтение)',
  () => {
    it('2.5.8 — со шлюзом — проход', () => {
      expect(runGuard(REAL_WITH_GATEWAY).status).toBe(0);
    });

    it('2.4.10 — уехал без шлюза (CPD-87) — отказ', () => {
      const run = runGuard(REAL_WITHOUT_GATEWAY);
      expect(run.status).toBe(1);
      expect(run.stderr).toMatch(/gateway_executor=0, aurora_gateway=0/);
    });
  },
);
