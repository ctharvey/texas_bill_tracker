import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {THEMES, DEFAULT_THEME, cleanTheme, withTheme, MODES, DEFAULT_MODE, cleanMode, shownMode, withMode} from '../src/features/theme/model.js';

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

test('light or dark: a choice wins, Match device follows the device, anything else is Match device', () => {
  assert.equal(DEFAULT_MODE, 'system');
  assert.deepEqual(MODES.map(m => m.id), ['system', 'light', 'dark']);
  assert.deepEqual(['dark', 'light', 'nope', null].map(cleanMode), ['dark', 'light', 'system', 'system']);
  assert.deepEqual([shownMode('system', true), shownMode('system', false), shownMode('light', true), shownMode('dark', false), shownMode('x', true)],
    ['dark', 'light', 'light', 'dark', 'dark']);
  const filters = {topic: 'Taxes'};
  assert.deepEqual(withTheme(withMode({filters}, 'dark'), 'ranch'), {filters, mode: 'dark', theme: 'ranch'});
  assert.deepEqual(withMode(['x'], 'nope'), {mode: 'system'});
});

test('the pre-paint script sets light or dark, from the device when the saved mode is missing or storage fails', () => {
  const html = read('index.html');
  assert.match(html, /var m=p\.mode;if\(m!=='light'&&m!=='dark'\)try\{m=matchMedia\('\(prefers-color-scheme: dark\)'\)\.matches\?'dark':'light'\}catch\(e\)\{m='light'\}d\.dataset\.mode=m/);
  // Storage is read inside its own try, so a blocked localStorage still reaches the device check.
  assert.match(html, /try\{p=JSON\.parse\(localStorage\.getItem\('tx-bill-atlas-prefs-v1'\)\|\|'null'\)\|\|\{\}\}catch\(e\)\{\}/);
});

test('every theme has dark base tokens, and dark mode sets color-scheme', () => {
  const css = read('src/styles.css');
  const dark = [...css.matchAll(/:root\[data-mode="dark"\]\[data-palette="([a-z-]+)"\]\{([^}]*)\}/g)];
  assert.deepEqual(dark.map(m => m[1]), others);
  for (const [, id, body] of dark)
    for (const token of ['--bg', '--surface', '--ink', '--muted', '--line', '--accent', '--accent-ink', '--nav-bg', '--nav-ink', '--mark'])
      assert.ok(body.includes(`${token}:`), `${id} dark is missing ${token}`);
  assert.match(css, /:root\[data-mode="dark"\]\{color-scheme:dark;/);
});
