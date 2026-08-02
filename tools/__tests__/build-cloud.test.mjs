// Проверки правок аудита 4 (П-4, П-5) в `tools/build-cloud.mjs`.
//
// 🔴 Зачем набор существует. Обе находки молчаливы по своей природе: П-4 —
// проверка типов фронта, которую выпуск просто не звал; П-5 — сверка состава
// контракта, которая на ветке метки не работала вовсе, а отказ приходил из
// глубины `cargo`, спустя минуты компиляции, без внятной причины. Каждая
// проверка здесь — заведомо сломанный вход, на котором гейт обязан покраснеть,
// либо заведомо исправный, на котором он обязан молчать.
//
// Ветка метки проверяется на ЛОКАЛЬНОМ git-репозитории-фикстуре, а не на
// настоящем GitHub: без сети, без флейков, детерминированно — и то же самое
// умеет `git clone --branch`/`git ls-remote` что для локального пути, что для
// удалённого URL.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import {
  usedGatewayNames,
  gatewaySurface,
  assertContractSurface,
  verifyGatewaySource,
} from '../build-cloud.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));

function git(cwd, ...args) {
  execFileSync('git', args, { cwd, stdio: 'pipe' });
}

/**
 * Перехватить `fail()`: он зовёт `process.exit(1)`, а тест обязан получить
 * управление обратно, а не завершить весь прогон vitest.
 *
 * 🔴 Сообщения `console.error` читаются ДО `mockRestore()`: `mockRestore()`
 * делает всё то же, что `mockReset()` (стирает `.mock.calls`), и чтение после
 * восстановления всегда давало бы пустую строку — поймано первым же прогоном.
 */
function withExitTrapped(run) {
  const exitSpy = vi.spyOn(process, 'exit').mockImplementation(() => {
    throw new Error('EXIT');
  });
  const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  let threw = null;
  try {
    run();
  } catch (e) {
    threw = e;
  }
  const errors = errSpy.mock.calls.map((c) => c.join(' ')).join('\n');
  exitSpy.mockRestore();
  errSpy.mockRestore();
  return { threw, errors };
}

describe('gatewaySurface', () => {
  it('извлекает имена и из pub use { … }, и из pub mod', () => {
    const src = `
      pub mod protocol;
      pub use protocol::{Alpha, Beta, gamma_fn};
      pub use other::Single;
    `;
    const surface = gatewaySurface(src);
    expect(surface.has('Alpha')).toBe(true);
    expect(surface.has('Beta')).toBe(true);
    expect(surface.has('gamma_fn')).toBe(true);
    expect(surface.has('Single')).toBe(true);
    expect(surface.has('protocol')).toBe(true);
  });
});

describe('assertContractSurface', () => {
  it('молчит, когда поверхность содержит все имена, которые продукт реально зовёт', () => {
    const used = usedGatewayNames();
    expect(used.size).toBeGreaterThan(0);
    const { threw } = withExitTrapped(() => assertContractSurface(new Set(used), 'тестовый источник'));
    expect(threw).toBeNull();
  });

  it('краснеет и называет имя, которого поверхность лишилась', () => {
    const used = usedGatewayNames();
    const missingName = [...used][0];
    const surface = new Set(used);
    surface.delete(missingName);
    const { threw, errors } = withExitTrapped(() => assertContractSurface(surface, 'тестовый источник'));
    expect(threw).not.toBeNull();
    expect(errors).toContain(missingName);
  });
});

describe('verifyGatewaySource — ветка пути (регресс после выноса общей сверки в П-5)', () => {
  it('молчит, когда каталог содержит нужный состав', () => {
    const used = usedGatewayNames();
    const dir = mkdtempSync(join(tmpdir(), 'gw-path-'));
    try {
      mkdirSync(join(dir, 'src', 'cloud'), { recursive: true });
      writeFileSync(join(dir, 'src', 'cloud', 'mod.rs'), `pub use protocol::{${[...used].join(', ')}};\n`, 'utf8');
      const { threw } = withExitTrapped(() => verifyGatewaySource({ kind: 'path', dir }));
      expect(threw).toBeNull();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('краснеет, когда в каталоге не хватает имени, которое продукт зовёт', () => {
    const used = usedGatewayNames();
    const missing = [...used][0];
    const dir = mkdtempSync(join(tmpdir(), 'gw-path-'));
    try {
      mkdirSync(join(dir, 'src', 'cloud'), { recursive: true });
      const rest = [...used].filter((n) => n !== missing);
      writeFileSync(join(dir, 'src', 'cloud', 'mod.rs'), `pub use protocol::{${rest.join(', ')}};\n`, 'utf8');
      const { threw, errors } = withExitTrapped(() => verifyGatewaySource({ kind: 'path', dir }));
      expect(threw).not.toBeNull();
      expect(errors).toContain(missing);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe('verifyGatewaySource — ветка метки (находка П-5, аудит 4)', () => {
  // 🔴 Прежде эта ветка проверяла ТОЛЬКО существование метки в удалённом
  // репозитории — состав контракта не сверялся вовсе. Продукт, перешедший на
  // зависимость по метке (оба продукта перешли), гейт объявлял пройденным,
  // даже если метка не содержит имени, которое продукт реально зовёт: отказ
  // приходил из глубины `cargo`, спустя минуты компиляции.
  let repoDir;
  let usedNames; // массив — Set неудобно индексировать при сборке фикстуры

  beforeAll(() => {
    usedNames = [...usedGatewayNames()];
    repoDir = mkdtempSync(join(tmpdir(), 'gw-fixture-'));
    git(repoDir, 'init', '--quiet');
    git(repoDir, 'config', 'user.email', 'test@example.com');
    git(repoDir, 'config', 'user.name', 'test');
    const cloudDir = join(repoDir, 'aurora_gateway', 'src', 'cloud');
    mkdirSync(cloudDir, { recursive: true });

    // Метка "good-tag": состав включает ВСЕ имена, которые продукт реально
    // импортирует из aurora_gateway::cloud — контракт полон.
    writeFileSync(join(cloudDir, 'mod.rs'), `pub use protocol::{${usedNames.join(', ')}};\n`, 'utf8');
    git(repoDir, 'add', '.');
    git(repoDir, 'commit', '--quiet', '-m', 'полный состав');
    git(repoDir, 'tag', 'good-tag');

    // Метка "bad-tag": следующий коммит той же фикстуры лишился ОДНОГО имени —
    // ровно сценарий, который сейчас реален (Core получил новые методы,
    // метка ещё не переставлена).
    const rest = usedNames.filter((n) => n !== usedNames[0]);
    writeFileSync(join(cloudDir, 'mod.rs'), `pub use protocol::{${rest.join(', ')}};\n`, 'utf8');
    git(repoDir, 'add', '.');
    git(repoDir, 'commit', '--quiet', '-m', 'одного имени не хватает');
    git(repoDir, 'tag', 'bad-tag');
  });

  afterAll(() => {
    rmSync(repoDir, { recursive: true, force: true });
  });

  it('молчит на метке с полным составом контракта', () => {
    const { threw } = withExitTrapped(() => verifyGatewaySource({ kind: 'tag', url: repoDir, tag: 'good-tag' }));
    expect(threw).toBeNull();
  });

  it('красит на метке, где не хватает имени, которое продукт реально зовёт', () => {
    const { threw, errors } = withExitTrapped(
      () => verifyGatewaySource({ kind: 'tag', url: repoDir, tag: 'bad-tag' }),
    );
    expect(threw).not.toBeNull();
    expect(errors).toContain(usedNames[0]);
  });

  it('краснеет и на несуществующей метке — живость метки проверяется первым делом', () => {
    const { threw, errors } = withExitTrapped(
      () => verifyGatewaySource({ kind: 'tag', url: repoDir, tag: 'нет-такой-метки' }),
    );
    expect(threw).not.toBeNull();
    expect(errors).toContain('нет-такой-метки');
  });
});

describe('checkFrontendTypes вызывается не только в --test (находка П-4, аудит 4)', () => {
  it('main() зовёт её безусловно, а не только при testOnly', () => {
    const source = readFileSync(join(HERE, '..', 'build-cloud.mjs'), 'utf8');
    expect(source).not.toMatch(/if\s*\(\s*testOnly\s*\)\s*checkFrontendTypes\(\)/);
    expect(source).toMatch(/^\s*checkFrontendTypes\(\);\s*$/m);
  });
});
