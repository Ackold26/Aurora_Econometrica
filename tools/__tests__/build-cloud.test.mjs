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
  KNOWN_GATEWAY_METHODS,
  blankNonCode,
  stripTestModules,
  implTypeName,
  tagCommitFromLsRemote,
  lockedGatewayCommit,
  assertBuiltFromTag,
  startedDirectly,
} from '../build-cloud.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));

function git(cwd, ...args) {
  execFileSync('git', args, { cwd, stdio: 'pipe' });
}

/** Тип, на котором объявлен метод общего слоя. Единый источник — сам гейт. */
function typeOf(method) {
  return (KNOWN_GATEWAY_METHODS[method] && KNOWN_GATEWAY_METHODS[method].type) || 'CloudError';
}

/** Квалифицированное имя, в котором гейт теперь и спрашивает контракт. */
function qualified(method) {
  return `${typeOf(method)}::${method}`;
}

/**
 * Исходник крейта-фикстуры: методы разложены по СВОИМ типам.
 *
 * 🔴 Прежде фикстура сваливала все методы в один `impl CloudError`, и это
 * работало ровно потому, что гейт типа не различал. Раскладка по типам — часть
 * доказательства правки: сверка спрашивает `Тип::метод`.
 */
function implSource(methods) {
  const byType = new Map();
  for (const method of methods) {
    const type = typeOf(method);
    if (!byType.has(type)) byType.set(type, []);
    byType.get(type).push(method);
  }
  const blocks = [...byType.entries()].map(([type, names]) => (
    `pub struct ${type};\nimpl ${type} {\n${
      names.map((n) => `    pub fn ${n}(&self) -> bool { true }`).join('\n')
    }\n}\n`
  ));
  return blocks.join('\n');
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
      writeFileSync(join(dir, 'src', 'cloud', 'client.rs'), implSource(usedMethods), 'utf8');
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
    writeFileSync(join(cloudDir, 'client.rs'), implSource([...usedGatewayMethods()]), 'utf8');
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
  it('молчит, когда определения крейта содержат все вызванные методы на своих типах', () => {
    const used = usedGatewayMethods();
    expect(used.size).toBeGreaterThan(0);
    const defined = new Set([...used].map(qualified));
    const { threw } = withExitTrapped(() => assertContractMethods(defined, 'тестовый источник'));
    expect(threw).toBeNull();
  });

  it('краснеет и называет метод, которого крейт не содержит — ровно форма беды is_resend_inputs на v0.5.0', () => {
    const used = usedGatewayMethods();
    const missingMethod = [...used][0];
    const defined = new Set([...used].map(qualified));
    defined.delete(qualified(missingMethod));
    const { threw, errors } = withExitTrapped(() => assertContractMethods(defined, 'тестовый источник'));
    expect(threw).not.toBeNull();
    expect(errors).toContain(missingMethod);
  });

  // 🔴 Находка пятого аудита: имя метода само по себе ничего не доказывает.
  // В Core `user_text` определён и у `CloudError`, и у `TicketProblem` — пропади
  // нужный, прежняя сверка молчала бы, потому что имя в дереве осталось.
  it('краснеет, когда метод есть, но на ЧУЖОМ типе', () => {
    const used = [...usedGatewayMethods()];
    const method = used[0];
    const defined = new Set(used.map(qualified));
    defined.delete(qualified(method));
    defined.add(`СовсемДругойТип::${method}`);
    defined.add(method); // и голое имя в дереве тоже есть — прежней сверке хватало
    const { threw, errors } = withExitTrapped(() => assertContractMethods(defined, 'тестовый источник'));
    expect(threw).not.toBeNull();
    expect(errors).toContain(qualified(method));
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

    const implOf = (names) => implSource(names);

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

// ── Находки пятого аудита (2026-08-02) ───────────────────────────────────────

describe('definedFunctionNames — три способа промолчать (High пятого аудита)', () => {
  const withTree = (files, check) => {
    const dir = mkdtempSync(join(tmpdir(), 'gw-defs5-'));
    try {
      for (const [name, text] of Object.entries(files)) {
        writeFileSync(join(dir, name), text, 'utf8');
      }
      check(definedFunctionNames(dir));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  };

  it('видит pub async fn и pub const fn — иначе ложное КРАСНОЕ на исправном крейте', () => {
    withTree({
      'a.rs': 'impl Foo {\n    pub async fn shipped(&self) {}\n    pub const fn counted() -> u8 { 1 }\n}\n',
    }, (names) => {
      expect(names.has('Foo::shipped')).toBe(true);
      expect(names.has('Foo::counted')).toBe(true);
    });
  });

  // 🔴 Находка внешнего аудита: `blankNonCode` гасит строковые литералы вместе с
  // кавычками, поэтому к разбору `pub extern "C" fn` приходит как
  // `pub extern     fn`. Требование кавычек давало ложное КРАСНОЕ на исправном
  // крейте — беда зеркальная той, ради которой формы и расширяли.
  it('видит pub extern "C" fn — кавычки к этому месту уже погашены', () => {
    withTree({ 'a.rs': 'impl Foo {\n    pub extern "C" fn ffi_name(&self) {}\n}\n' }, (names) => {
      expect(names.has('Foo::ffi_name')).toBe(true);
    });
  });

  it('НЕ считает объявлением помощника из тестового модуля', () => {
    withTree({
      'a.rs': 'impl Foo {\n    pub fn real(&self) {}\n}\n'
        + '#[cfg(test)]\nmod tests {\n    impl Foo {\n        pub fn only_in_tests(&self) {}\n    }\n}\n',
    }, (names) => {
      expect(names.has('Foo::real')).toBe(true);
      expect(names.has('Foo::only_in_tests')).toBe(false);
      expect(names.has('only_in_tests')).toBe(false);
    });
  });

  it('различает одноимённые методы разных типов', () => {
    withTree({
      'a.rs': 'impl CloudError {\n    pub fn user_text(&self) {}\n}\n'
        + 'impl TicketProblem {\n    pub fn user_text(&self) {}\n}\n',
    }, (names) => {
      expect(names.has('CloudError::user_text')).toBe(true);
      expect(names.has('TicketProblem::user_text')).toBe(true);
    });
  });

  it('НЕ считает объявлением pub(crate) fn — снаружи такой метод недоступен', () => {
    withTree({ 'a.rs': 'impl Foo {\n    pub(crate) fn hidden(&self) {}\n}\n' }, (names) => {
      expect(names.has('Foo::hidden')).toBe(false);
      expect(names.has('hidden')).toBe(false);
    });
  });

  it('не обманывается объявлением внутри строки или комментария', () => {
    withTree({
      'a.rs': 'impl Foo {\n    // pub fn commented(&self) {}\n'
        + '    pub fn real(&self) -> &str { "pub fn inside_string() {}" }\n}\n',
    }, (names) => {
      expect(names.has('Foo::real')).toBe(true);
      expect(names.has('Foo::commented')).toBe(false);
      expect(names.has('Foo::inside_string')).toBe(false);
    });
  });
});

describe('stripTestModules', () => {
  it('гасит тело #[cfg(test)] и НЕ уносит с собой живой код ниже', () => {
    const code = blankNonCode(
      'pub fn before() {}\n#[cfg(test)]\nmod tests {\n    pub fn inside() {}\n}\npub fn after() {}\n',
    );
    const stripped = stripTestModules(code);
    expect(stripped).toContain('pub fn before');
    expect(stripped).toContain('pub fn after');
    expect(stripped).not.toContain('pub fn inside');
  });

  it('объявление БЕЗ тела (mod tests;) не прячет следующий блок', () => {
    const code = blankNonCode('#[cfg(test)]\nmod tests;\nimpl Foo {\n    pub fn alive(&self) {}\n}\n');
    expect(stripTestModules(code)).toContain('pub fn alive');
  });

  it('гасит и второй тестовый модуль, а не только первый', () => {
    const code = blankNonCode(
      '#[cfg(test)]\nmod a { pub fn one() {} }\npub fn between() {}\n'
      + '#[cfg(test)]\nmod b { pub fn two() {} }\npub fn tail() {}\n',
    );
    const stripped = stripTestModules(code);
    expect(stripped).toContain('pub fn between');
    expect(stripped).toContain('pub fn tail');
    expect(stripped).not.toContain('pub fn one');
    expect(stripped).not.toContain('pub fn two');
  });
});

describe('implTypeName', () => {
  it('снимает дженерики, путь и форму "for"', () => {
    expect(implTypeName(' CloudError ')).toBe('CloudError');
    expect(implTypeName("<'a> Borrowed<'a> ")).toBe('Borrowed');
    expect(implTypeName(' std::fmt::Debug for DeviceIdentity ')).toBe('DeviceIdentity');
    expect(implTypeName(' Default for WaitLimits ')).toBe('WaitLimits');
  });
});

describe('tagCommitFromLsRemote (High пятого аудита: запись метки)', () => {
  it('у аннотированной метки берёт разыменованную запись, а не объект метки', () => {
    const out = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\trefs/tags/v1\n'
      + 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trefs/tags/v1^{}\n';
    expect(tagCommitFromLsRemote(out, 'v1')).toBe('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb');
  });

  // 🔴 Порядок строк ОБРАТНЫЙ намеренно. При обычном порядке (объект метки, затем
  // разыменованная запись) правило «бери последнюю подходящую» даёт тот же ответ,
  // что и правильное, — и проверка зеленела бы, ничего не проверяя: мутация
  // «игнорировать ^{}» её пережила. Здесь верный ответ достижим ТОЛЬКО через ^{}.
  it('берёт запись по признаку ^{}, а не по месту строки в ответе', () => {
    const out = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trefs/tags/v1^{}\n'
      + 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\trefs/tags/v1\n';
    expect(tagCommitFromLsRemote(out, 'v1')).toBe('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb');
  });

  it('у лёгкой метки берёт единственную строку', () => {
    const out = 'cccccccccccccccccccccccccccccccccccccccc\trefs/tags/v2\n';
    expect(tagCommitFromLsRemote(out, 'v2')).toBe('cccccccccccccccccccccccccccccccccccccccc');
  });

  it('не путает метку с чужой, чьё имя начинается так же', () => {
    const out = 'dddddddddddddddddddddddddddddddddddddddd\trefs/tags/v2-rc1\n';
    expect(tagCommitFromLsRemote(out, 'v2')).toBeNull();
  });
});

describe('lockedGatewayCommit (High пятого аудита: чем собрано на самом деле)', () => {
  const lockWith = (source) => `[[package]]\nname = "serde"\nversion = "1.0"\n\n`
    + `[[package]]\nname = "aurora_gateway"\nversion = "0.1.0"\nsource = "${source}"\n`;

  it('читает метку и запись из строки источника', () => {
    const sha = 'e'.repeat(40);
    const got = lockedGatewayCommit(lockWith(
      `git+https://example.com/core.git?tag=aurora_gateway-v0.6.1#${sha}`,
    ));
    expect(got.tag).toBe('aurora_gateway-v0.6.1');
    expect(got.sha).toBe(sha);
  });

  it('отдаёт null, когда крейта в замке нет вовсе', () => {
    expect(lockedGatewayCommit('[[package]]\nname = "serde"\nversion = "1.0"\n')).toBeNull();
  });

  it('НЕ выдаёт запись, когда источник не по метке — форму, которую не понял, гейт обязан назвать', () => {
    const got = lockedGatewayCommit(lockWith('git+https://example.com/core.git?branch=main#' + 'f'.repeat(40)));
    expect(got).not.toBeNull();
    expect(got.sha).toBeNull();
  });
});

describe('assertBuiltFromTag (High пятого аудита: гейт сверял клон, cargo собирал по замку)', () => {
  const sha = 'a'.repeat(40);
  const other = 'b'.repeat(40);
  const lockFor = (tag, commit) => `[[package]]\nname = "aurora_gateway"\nversion = "0.1.0"\n`
    + `source = "git+https://example.com/core.git?tag=${tag}#${commit}"\n`;

  it('молчит, когда собрано ровно по той записи, на которую метка указывает сейчас', () => {
    const { threw } = withExitTrapped(
      () => assertBuiltFromTag({ tag: 'v0.6.1', sha }, lockFor('v0.6.1', sha)),
    );
    expect(threw).toBeNull();
  });

  it('краснеет, когда замок держит ПРЕЖНЮЮ запись той же метки — метку переставили', () => {
    const { threw, errors } = withExitTrapped(
      () => assertBuiltFromTag({ tag: 'v0.6.1', sha }, lockFor('v0.6.1', other)),
    );
    expect(threw).not.toBeNull();
    expect(errors).toContain(other.slice(0, 12));
  });

  it('краснеет, когда собрано по ДРУГОЙ метке', () => {
    const { threw, errors } = withExitTrapped(
      () => assertBuiltFromTag({ tag: 'v0.6.1', sha }, lockFor('v0.6.0', sha)),
    );
    expect(threw).not.toBeNull();
    expect(errors).toContain('v0.6.0');
  });

  it('краснеет, когда крейта в замке нет вовсе — доказать нечем', () => {
    const { threw } = withExitTrapped(
      () => assertBuiltFromTag({ tag: 'v0.6.1', sha }, '[[package]]\nname = "serde"\n'),
    );
    expect(threw).not.toBeNull();
  });
});

describe('ветка метки на НАСТОЯЩЕМ вызове git (метки Core аннотированные)', () => {
  // 🔴 Разбор `tagCommitFromLsRemote` проверялся на сочинённом выводе, где строка
  // `^{}` была. А настоящий вызов её не получал: `ls-remote` отбирает по имени
  // ссылки, и под образец `<метка>` разыменованная запись `<метка>^{}` не
  // подходит. Гейт брал объект МЕТКИ, cargo писал в замок КОММИТ — сверка
  // краснела на исправной сборке. Поймано боевым прогоном, а не этим набором,
  // поэтому проверка здесь идёт через настоящий git, а не через строку.
  let repoDir;
  let commitSha;

  beforeAll(() => {
    const usedNames = [...usedGatewayNames()];
    repoDir = mkdtempSync(join(tmpdir(), 'gw-annotated-'));
    git(repoDir, 'init', '--quiet');
    git(repoDir, 'config', 'user.email', 'test@example.com');
    git(repoDir, 'config', 'user.name', 'test');
    const cloudDir = join(repoDir, 'aurora_gateway', 'src', 'cloud');
    mkdirSync(cloudDir, { recursive: true });
    writeFileSync(join(cloudDir, 'mod.rs'), `pub use protocol::{${usedNames.join(', ')}};\n`, 'utf8');
    writeFileSync(join(cloudDir, 'client.rs'), implSource([...usedGatewayMethods()]), 'utf8');
    git(repoDir, 'add', '.');
    git(repoDir, 'commit', '--quiet', '-m', 'полный состав');
    // Метка АННОТИРОВАННАЯ — как все метки Core.
    git(repoDir, 'tag', '-a', 'annotated-tag', '-m', 'метка выпуска');
    commitSha = execFileSync('git', ['rev-parse', 'annotated-tag^{}'], { cwd: repoDir, encoding: 'utf8' }).trim();
    // Таймаут увеличен (10с дефолт → 30с): семь подряд-идущих спавнов git.exe на
    // Windows CI под нагрузкой конкурентных прогонов один раз превысили 10с
    // (2026-08-09) — не сеть, локальный git, просто накладные расходы Windows
    // на создание процесса; повторов не поймано ни разу.
  }, 30000);

  afterAll(() => {
    rmSync(repoDir, { recursive: true, force: true });
  });

  it('возвращает запись КОММИТА, а не объекта метки', () => {
    let got = null;
    const { threw } = withExitTrapped(() => {
      got = verifyGatewaySource({ kind: 'tag', url: repoDir, tag: 'annotated-tag' });
    });
    expect(threw).toBeNull();
    expect(got).not.toBeNull();
    expect(got.sha).toBe(commitSha);
    // Объект метки — другая запись, и именно её брал прежний вызов.
    const tagObject = execFileSync('git', ['rev-parse', 'annotated-tag'], { cwd: repoDir, encoding: 'utf8' }).trim();
    expect(tagObject).not.toBe(commitSha);
    expect(got.sha).not.toBe(tagObject);
  });
});

describe('порядок сверки в main (иначе доказывать нечем)', () => {
  it('assertBuiltFromTag зовётся ДО восстановления дерева', () => {
    const source = readFileSync(join(HERE, '..', 'build-cloud.mjs'), 'utf8');
    const check = source.indexOf('assertBuiltFromTag(expectedTag');
    const restore = source.indexOf("restoreWorkspace('сборка закончена')");
    expect(check).toBeGreaterThan(-1);
    expect(restore).toBeGreaterThan(-1);
    expect(check).toBeLessThan(restore);
  });
});

describe('startedDirectly (High пятого аудита: гард запуска на junction)', () => {
  it('узнаёт прямой запуск по обычному пути', () => {
    expect(startedDirectly(join(HERE, '..', 'build-cloud.mjs'))).toBe(true);
  });

  it('не считает прямым запуском чужой файл', () => {
    expect(startedDirectly(join(HERE, 'build-cloud.test.mjs'))).toBe(false);
    expect(startedDirectly(undefined)).toBe(false);
  });

  // 🔴 Ровно тот случай, ради которого правка: из каталога, заведённого через
  // `mklink /J`, скрипт молча выходил кодом ноль — сборки нет, установщик
  // прежний, вызывающая сторона видит успех.
  it('узнаёт запуск через junction/символическую ссылку на каталог', () => {
    const toolsDir = join(HERE, '..');
    const linkDir = join(mkdtempSync(join(tmpdir(), 'gw-junction-')), 'tools-link');
    let made = false;
    try {
      if (process.platform === 'win32') {
        execFileSync('cmd', ['/c', 'mklink', '/J', linkDir, toolsDir], { stdio: 'pipe' });
      } else {
        execFileSync('ln', ['-s', toolsDir, linkDir], { stdio: 'pipe' });
      }
      made = true;
    } catch (e) {
      // Стечение обязано СОСТОЯТЬСЯ: молча зеленеть здесь — то же самое, чем
      // болел сам гард.
      expect.fail(`ссылку на каталог создать не удалось, стечение не воспроизведено: ${e.message}`);
    }
    try {
      const viaLink = join(linkDir, 'build-cloud.mjs');
      expect(startedDirectly(viaLink)).toBe(true);
    } finally {
      if (made) rmSync(dirname(linkDir), { recursive: true, force: true });
    }
  });
});
