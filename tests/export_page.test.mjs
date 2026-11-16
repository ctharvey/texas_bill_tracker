import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseHash, buildHash, VIEWS, profileFile, parseProfileFile} from '../src/prefs.js';
import {exportMarkup} from '../src/features/export/view.js';

const app = readFileSync(new URL('../src/app.js', import.meta.url), 'utf8');
const saved = {watch: new Set(['HB5', 'SJR9']), follows: ['A2010', 'A9999'],
  searches: [{id: 'abcd1234', name: 'Water <b>', filters: {query: 'water'}, seen: '2026-11-10'}], theme: 'bluebonnet'};

test('#export is its own page and keeps its address', () => {
  assert.ok(VIEWS.includes('export'));
  assert.equal(parseHash('#export').view, 'export');
  assert.equal(buildHash('export', {topic: 'Water'}), '#export');
});

test('the page lists everything saved, escaped, with a download button the save tools handle', () => {
  const html = exportMarkup({...saved, memberName: c => c === 'A2010' ? 'Rep. Example' : null});
  assert.match(html, /2 bills on its watchlist, 2 followed legislators and 1 saved search/);
  for (const part of ['<li>HB5</li>', '<li>SJR9</li>', '<li>Rep. Example</li>', '<li>A9999</li>', 'Water &lt;b&gt;', 'Colour theme: Bluebonnet.'])
    assert.ok(html.includes(part), part);
  assert.doesNotMatch(html, /<b>/);
  assert.match(html, /<button class="primary-button" id="export-watch" >Download file<\/button>/);
  // The button reuses the Watchlist's export: the save-tools click handler and the same profile file.
  assert.match(app, /clickOn\('save-tools','[^']*#export-watch/);
  assert.match(app, /if\(hit\('#export-watch'\)\)\{download\('texas-bill-atlas-saved\.json',profileFile\(/);
});

test('an empty browser says so and cannot download an empty file', () => {
  const html = exportMarkup({});
  assert.match(html, /nothing saved yet/);
  assert.match(html, /id="export-watch" disabled/);
  assert.ok(exportMarkup({theme: 'granite'}).includes('id="export-watch" >'), 'a theme alone is still worth a file');
});

test('a synced browser is told its sync link is not in the file', () => {
  assert.match(exportMarkup({...saved, synced: true}), /sync link/);
  assert.doesNotMatch(exportMarkup(saved), /sync link/);
});

test('what the page downloads imports back unchanged', () => {
  const back = parseProfileFile(profileFile(saved));
  assert.deepEqual(back.bills, ['HB5', 'SJR9']);
  assert.deepEqual(back.follows, ['A2010', 'A9999']);
  assert.deepEqual(back.searches, saved.searches);
  assert.equal(back.theme, 'bluebonnet');
});
