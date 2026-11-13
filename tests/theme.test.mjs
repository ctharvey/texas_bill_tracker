import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {THEMES, DEFAULT_THEME, cleanTheme, withTheme} from '../src/features/theme/model.js';

const read = name => readFileSync(new URL(`../${name}`, import.meta.url), 'utf8');
const others = THEMES.map(t => t.id).filter(id => id !== DEFAULT_THEME);

test('unknown or missing themes fall back to the default', () => {
  for (const bad of [undefined, null, '', 'docket', 'GRANITE', 3, ['granite'], {}]) assert.equal(cleanTheme(bad), DEFAULT_THEME);
  for (const {id} of THEMES) assert.equal(cleanTheme(id), id);
});

test('setting a theme keeps remembered filters, and a filter save keeps the theme', () => {
  const filters = {query: 'water', topic: 'Energy'};
  assert.deepEqual(withTheme({filters}, 'ranch'), {filters, theme: 'ranch'});
  assert.deepEqual(withTheme(null, 'granite'), {theme: 'granite'});
  assert.deepEqual(withTheme(['x'], 'nope'), {theme: DEFAULT_THEME});
  const app = read('src/app.js');
  assert.match(app, /writeJson\(prefsKey,\{\.\.\.keptPrefs\(\),filters:pickFilters\(state\)\}\)/);
});

test('the pre-paint script in index.html knows every non-default theme', () => {
  const html = read('index.html');
  const list = html.match(/\.theme;if\((\[[^\]]*\])\.indexOf\(t\)/);
  assert.ok(list, 'pre-paint theme script not found');
  assert.deepEqual(JSON.parse(list[1].replaceAll("'", '"')), others);
  assert.ok(html.includes("localStorage.getItem('tx-bill-atlas-prefs-v1')"));
});

test('styles.css has a palette for every non-default theme and none for removed ones', () => {
  const css = read('src/styles.css');
  const blocks = [...css.matchAll(/:root\[data-palette="([a-z-]+)"\]\{/g)].map(m => m[1]);
  assert.deepEqual(blocks, others);
});
