// @ts-nocheck — node-side тест (fs/path/process): svelte-check checkJs не имеет
// @types/node в scope, логика проверяется через vitest, не через типы.
/**
 * Гейт: принадлежность события живёт В СОБЫТИИ, а не в памяти приёмника.
 *
 * 🔴 Найдено внешним аудитом 2026-08-03. Признак остановки был переменной
 * интерфейса и снимался следующим вопросом человека. Облачное ожидание длится до
 * минуты, «Остановить» отпускает окно немедленно — значит обычный порядок такой:
 * остановил → сразу спросил дальше → приехал хвост первой работы. Отличить его от
 * своего приёмнику было НЕЧЕМ, а у этого продукта отмена шлёт финальное событие с
 * признаком замены — то есть чужой ответ затирался целиком, а не дополнялся.
 *
 * Дефект не ловится ни тестом Rust в одиночку (там видно только форму события),
 * ни тестом интерфейса в одиночку (там видно только разбор) — ловится сверкой.
 *
 * Страховка от тихого нуля: пустой исходник — КРАСНЫЙ, а не «всё чисто».
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const EXECUTOR_RS = path.join(process.cwd(), 'src-tauri/src/commands/gateway_executor.rs');
const CHAT_PANEL = path.join(process.cwd(), 'src/lib/components/ChatPanel.svelte');

/** Рабочий код исполнителя — без модуля проверок и без пояснений.
 *
 * 🔴 Комментарии гасятся ДО поиска. Гейт, краснеющий от пояснения «почему так
 * писать нельзя», учит убирать пояснения, а не дефекты.
 */
function executorWorkingCode() {
  const source = fs.readFileSync(EXECUTOR_RS, 'utf8');
  expect(source.length, 'исходник исполнителя не прочитался — гейт смотрит не туда')
    .toBeGreaterThan(1000);
  const testsAt = source.indexOf('#[cfg(test)]');
  const working = testsAt === -1 ? source : source.slice(0, testsAt);
  return working
    .split('\n')
    .filter(line => !line.trim().startsWith('//'))
    .join('\n');
}

describe('хвост остановленной работы помечен и разбирается по пометке', () => {
  it('облачный путь помечает событие остановленной работы', () => {
    const code = executorWorkingCode();
    expect(code, 'событие остановленной работы обязано нести признак принадлежности')
      .toContain('"cancelled_run": true');
    expect(code, 'приписка обязана ехать отдельным полем: полный текст применим не всегда')
      .toMatch(/"notice":\s*notice/);
  });

  it('ни одна ветка остановки не уходит обычным финалом', () => {
    const code = executorWorkingCode();
    const marked = [...code.matchAll(/build_cancelled_event\(/g)].length;
    expect(marked, 'помеченным идут: ранний выход с припиской и общий финал')
      .toBeGreaterThanOrEqual(2);
    // Финал собирается в одном месте, и там же решается, помечать ли его.
    expect(code, 'финал обязан знать про догнавшую отмену').toContain('cancelled_notice');
    expect(code, 'признак берётся у работы, а не додумывается')
      .toMatch(/work\.cancelled\(\)\.then\(/);
    const plainFinal = [...code.matchAll(/build_result_event\(/g)].length;
    // Одно — определение функции, одно — обычная ветка внутри общего финала.
    expect(plainFinal, 'обычный финал собирается в одном месте, а не в каждой ветке')
      .toBeLessThanOrEqual(2);
  });

  it('приёмник решает по событию, а не по своей переменной', () => {
    const source = fs.readFileSync(CHAT_PANEL, 'utf8');
    expect(source.length, 'исходник интерфейса не прочитался — гейт смотрит не туда')
      .toBeGreaterThan(1000);
    expect(source, 'хвост остановленной работы обязан распознаваться по пометке события')
      .toContain('data.cancelled_run');
    expect(source, 'решение вынесено в проверяемую функцию, а не размазано по обработчику')
      .toContain('cancelledTailAction');
    expect(source, 'завершение обязано читать пометку события')
      .toMatch(/payload\?\.cancelled/);
    expect(source, 'обработчик завершения обязан получать событие, а не игнорировать его')
      .toMatch(/listen\(`claude-done-\$\{cabinetId\}`,\s*\(event\)/);
  });
});
