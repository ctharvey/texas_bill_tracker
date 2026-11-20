// SEO chunk 5 phase 3: the static about pages carry exactly what the app's views draw.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {aboutPages, buildPages} from '../scripts/build_agent.mjs';
import {methodMarkup} from '../src/features/pages/method.js';
import {savingMarkup} from '../src/features/pages/saving.js';
import {ABOUT_HEADINGS} from '../src/features/pages/headings.js';
import {state} from '../src/core/state.js';

const live = name => JSON.parse(readFileSync(new URL(`./e2e/fixtures/live/${name}`, import.meta.url), 'utf8'));

test('about pages are the app views, with their headings and addresses', () => {
  const pages = JSON.parse(buildPages({snapshot: live('bills.json'), tags: live('luna/tags.json'), roster: live('members.json'),
    status: live('luna/status.json'), minBills: 1}).get('data/pages.json')).about;
  assert.deepEqual(pages.map(p => [p.view, p.path]), [['method', '/about/method'], ['saving', '/about/saving'], ['data', '/about/data']]);
  assert.equal(pages[0].html, methodMarkup());
  assert.equal(pages[1].html, savingMarkup({linked: null, syncAvailable: true}));
  for (const p of pages) assert.deepEqual(p.heading, ABOUT_HEADINGS[p.view]);
  assert.match(pages[2].html, /Loaded records<\/span><span class="data-value">1384</);
  assert.match(pages[2].html, /Live server snapshot/);
});

test('drawing the about pages leaves the shared state as it was', () => {
  const before = state.bills;
  aboutPages({bills: [{id: 'HB1'}], snapshot: {data_mode: 'official-ftp'}});
  assert.equal(state.bills, before);
});
