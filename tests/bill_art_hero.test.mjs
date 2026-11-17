import test from 'node:test';
import assert from 'node:assert/strict';
import {HERO_MEDIA, heroFits} from '../src/features/art/view.js';

test('the title goes on the banner only on wide screens', () => {
  assert.equal(HERO_MEDIA, '(min-width: 900px)');
});

test('a title of one or two lines fits; three lines, or no layout yet, does not', () => {
  const line = 32.5, number = 20;
  assert.equal(heroFits(number + line, number, line), true);
  assert.equal(heroFits(number + 2 * line, number, line), true);
  assert.equal(heroFits(number + 3 * line, number, line), false);
  assert.equal(heroFits(0, 0, line), false);
  assert.equal(heroFits(number + line, number, 0), false);
  assert.equal(heroFits(number + line, number, NaN), false);
});
