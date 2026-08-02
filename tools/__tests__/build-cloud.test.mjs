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
  usedGatewayMethods,
  gatewaySurface,
  definedFunctionNames,
  assertContractSurface,
  assertContractMethods,
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
  it('молчит, когда каталог содержит нужный состав — имена и методы', () => {
    const used = usedGatewayNames();
    const usedMethods = [...usedGatewayMethods()];
    const dir = mkdtempSync(join(tmpdir(), 'gw-path-'));
    try {
      mkdirSync(join(dir, 'src', 'cloud'), { recursive: true });
      writeFileSync(join(dir, 'src', 'cloud', 'mod.rs'), `pub use protocol::{${[...used].join(', ')}};\n`, 'utf8');
      // Методы (находка П-5, продолжение) — отдельное пространство от имён:
      // без impl-файла usedGatewayMethods() нашла бы имена на месте, а методы
      // ни на чём не определены, и проверка ложно покраснела бы.
      writeFileSync(
        join(dir, 'src', 'cloud', 'client.rs'),
        `pub struct CloudError;\nimpl CloudError {\n${
          usedMethods.map((n) => `    pub fn ${n}(&self) -> bool { true }`).join('\n')
        }\n}\n`,
        'utf8',
      );
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
    // импортирует из aurora_gateway::cloud — контракт полон. Методы (находка
    // П-5, продолжение) тоже нужны здесь: без них проверка методов покраснела
    // бы на этой же метке по СВОЕЙ, отдельной причине.
    writeFileSync(join(cloudDir, 'mod.rs'), `pub use protocol::{${usedNames.join(', ')}};\n`, 'utf8');
    const usedMethodsForNameFixture = [...usedGatewayMethods()];
    writeFileSync(
      join(cloudDir, 'client.rs'),
      `pub struct CloudError;\nimpl CloudError {\n${
        usedMethodsForNameFixture.map((n) => `    pub fn ${n}(&self) -> bool { true }`).join('\n')
      }\n}\n`,
      'utf8',
    );
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

describe('definedFunctionNames', () => {
  it('находит pub fn в любом файле дерева, включая вложенные каталоги и impl-блоки', () => {
    const dir = mkdtempSync(join(tmpdir(), 'gw-defs-'));
    try {
      writeFileSync(join(dir, 'a.rs'), 'pub fn alpha() {}\n', 'utf8');
      mkdirSync(join(dir, 'nested'));
      writeFileSync(
        join(dir, 'nested', 'b.rs'),
        'impl X {\n    pub fn beta(&self) -> bool { true }\n}\n',
        'utf8',
      );
      const names = definedFunctionNames(dir);
      expect(names.has('alpha')).toBe(true);
      expect(names.has('beta')).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe('usedGatewayMethods (находка П-5, продолжение — аудит 4)', () => {
  // 🔴 Продукт зовёт методы общего слоя не только через use-импорт (тот случай
  // ловит usedGatewayNames), но и на уже импортированном значении:
  // `matches!(&outcome, Err(e) if e.is_resend_inputs())`. Тип (`CloudError`) в
  // адаптере при этом не назван ни разу буквально — выводится компилятором.
  it('находит хотя бы один реально вызванный метод из KNOWN_GATEWAY_METHODS', () => {
    const used = usedGatewayMethods();
    expect(used.size).toBeGreaterThan(0);
  });
});

describe('assertContractMethods', () => {
  it('молчит, когда определения крейта содержат все вызванные методы', () => {
    const used = usedGatewayMethods();
    expect(used.size).toBeGreaterThan(0);
    const { threw } = withExitTrapped(() => assertContractMethods(new Set(used), 'тестовый источник'));
    expect(threw).toBeNull();
  });

  it('краснеет и называет метод, которого крейт не содержит — ровно форма беды is_resend_inputs на v0.5.0', () => {
    const used = usedGatewayMethods();
    const missingMethod = [...used][0];
    const defined = new Set(used);
    defined.delete(missingMethod);
    const { threw, errors } = withExitTrapped(() => assertContractMethods(defined, 'тестовый источник'));
    expect(threw).not.toBeNull();
    expect(errors).toContain(missingMethod);
  });
});

describe('verifyGatewaySource — метод общего слоя отсутствует в крейте (находка П-5, продолжение)', () => {
  // 🔴 Ровно тот дефект, что нашла team lead: имя (`CloudError`) на месте — оно
  // свободно объявляется в мод.rs фикстуры, — а МЕТОДА на нём нет. Прежняя
  // сверка (assertContractSurface, имена из use-импортов) этого не видит:
  // имя есть. Проверка методов — отдельное измерение контракта.
  let repoDir;
  let usedMethods;

  beforeAll(() => {
    usedMethods = [...usedGatewayMethods()];
    const usedNames = [...usedGatewayNames()];
    repoDir = mkdtempSync(join(tmpdir(), 'gw-methods-fixture-'));
    git(repoDir, 'init', '--quiet');
    git(repoDir, 'config', 'user.email', 'test@example.com');
    git(repoDir, 'config', 'user.name', 'test');
    const cloudDir = join(repoDir, 'aurora_gateway', 'src', 'cloud');
    mkdirSync(cloudDir, { recursive: true });
    writeFileSync(join(cloudDir, 'mod.rs'), `pub use protocol::{${usedNames.join(', ')}};\n`, 'utf8');

    const implOf = (names) => `pub struct CloudError;\nimpl CloudError {\n${
      names.map((n) => `    pub fn ${n}(&self) -> bool { true }`).join('\n')
    }\n}\n`;

    writeFileSync(join(cloudDir, 'client.rs'), implOf(usedMethods), 'utf8');
    git(repoDir, 'add', '.');
    git(repoDir, 'commit', '--quiet', '-m', 'полный состав, включая методы');
    git(repoDir, 'tag', 'methods-good');

    // Метка без ОДНОГО метода — та же форма беды, что у `is_resend_inputs` на
    // aurora_gateway-v0.5.0: свободное имя есть, метода на нём нет.
    const withoutOne = usedMethods.filter((n) => n !== usedMethods[0]);
    writeFileSync(join(cloudDir, 'client.rs'), implOf(withoutOne), 'utf8');
    git(repoDir, 'add', '.');
    git(repoDir, 'commit', '--quiet', '-m', 'одного метода не хватает');
    git(repoDir, 'tag', 'methods-bad');
  });

  afterAll(() => {
    rmSync(repoDir, { recursive: true, force: true });
  });

  it('молчит на метке, где определены все вызванные методы', () => {
    expect(usedMethods.length).toBeGreaterThan(0);
    const { threw } = withExitTrapped(
      () => verifyGatewaySource({ kind: 'tag', url: repoDir, tag: 'methods-good' }),
    );
    expect(threw).toBeNull();
  });

  it('красит на метке, где не хватает метода, который продукт реально зовёт', () => {
    const { threw, errors } = withExitTrapped(
      () => verifyGatewaySource({ kind: 'tag', url: repoDir, tag: 'methods-bad' }),
    );
    expect(threw).not.toBeNull();
    expect(errors).toContain(usedMethods[0]);
  });
});

describe('checkFrontendTypes вызывается не только в --test (находка П-4, аудит 4)', () => {
  it('main() зовёт её безусловно, а не только при testOnly', () => {
    const source = readFileSync(join(HERE, '..', 'build-cloud.mjs'), 'utf8');
    expect(source).not.toMatch(/if\s*\(\s*testOnly\s*\)\s*checkFrontendTypes\(\)/);
    expect(source).toMatch(/^\s*checkFrontendTypes\(\);\s*$/m);
  });
});
