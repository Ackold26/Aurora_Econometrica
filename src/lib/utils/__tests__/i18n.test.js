import { describe, it, expect } from 'vitest';
import { pluralizeRu } from '$lib/utils/i18n.js';

describe('pluralizeRu', () => {
  const forms = /** @type {[string, string, string]} */ (['канал', 'канала', 'каналов']);
  it.each([
    [1, 'канал'],
    [2, 'канала'],
    [3, 'канала'],
    [4, 'канала'],
    [5, 'каналов'],
    [10, 'каналов'],
    [21, 'канал'],   // exception — units digit 1 but not 11
    [22, 'канала'],
    [25, 'каналов'],
    [101, 'канал'],
    [121, 'канал'],  // exception — units digit 1 but not 11
  ])('%i → %s', (n, expected) => {
    expect(pluralizeRu(n, forms)).toBe(expected);
  });
});
