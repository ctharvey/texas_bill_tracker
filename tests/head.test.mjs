import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {HOME_TITLE, HOME_DESCRIPTION, clip, titleCase, fullTitle, billHead, memberHead, groupHead, lawHead, chapterHead,
  headingHead, holdHead, writeHead} from '../src/core/head.js';
import {memberTitle} from '../src/features/members/names.js';

const FIXTURE = JSON.parse(readFileSync(new URL('./fixtures/page_heads.json', import.meta.url), 'utf8'));

// The same inputs as tests/test_page_head.py gives build_feeds, through the app's head builders.
function head(c) {
  if (c.kind === 'bill') return billHead(c.number, c.caption, c.headline);
  if (c.kind === 'member') return memberHead(memberTitle(c));
  if (c.kind === 'topic' || c.kind === 'agency') return groupHead(c.kind, c.name);
  if (c.kind === 'law') return lawHead(c.code_name, c.code, c.number, c.h);
  return chapterHead(c.code_name, c.chapter, c.h);
}

test('the app writes the static pages\' titles and bill descriptions', () => {
  for (const c of FIXTURE.cases) {
    const got = head(c);
    assert.equal(fullTitle(got.title), c.expected.title, JSON.stringify(c));
    if (c.expected.description) assert.equal(got.description, c.expected.description);
  }
});

test('home is index.html\'s own head', () => {
  const index = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.equal(index.match(/<title>(.*?)<\/title>/)[1], HOME_TITLE);
  assert.equal(index.match(/<meta name="description" content="([^"]*)">/)[1], HOME_DESCRIPTION);
});

test('clip and title case follow build_feeds', () => {
  assert.equal(clip('short', 70), 'short');
  assert.equal(clip('aaaa bbbb, cccc', 12), 'aaaa bbbb…');
  assert.equal(clip('x'.repeat(20), 10), 'x'.repeat(9) + '…');
  assert.equal(titleCase('OFFENSES AGAINST  THE PERSON'), 'Offenses Against the Person');
  assert.equal(titleCase('THE NON-PROFIT ACT'), 'The Non-Profit Act');
  assert.deepEqual(headingHead('How it works.'), {title: 'How it works', description: null});
});

test('the head is held only at the static page\'s own address', () => {
  assert.equal(holdHead('/bill/HB1', '/bill/HB1'), true);
  assert.equal(holdHead('/bill/HB1', '/bill/HB1?c=abc#x'), true);
  assert.equal(holdHead('/bill/HB1', '/bill/HB2'), false);
  assert.equal(holdHead('/bill/HB1', '/explorer?query=x'), false);
  assert.equal(holdHead(null, '/bill/HB1'), false);
});

// Just enough of a document for writeHead: elements keyed by their selector.
function fakeDoc(selectors) {
  const els = new Map(selectors.map(s => [s, {attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, remove() { els.delete(s); }}]));
  return {
    els, title: '',
    querySelector: s => els.get(s) || null,
    createElement: () => {
      const el = {attrs: {}, setAttribute(k, v) { this.attrs[k] = v; if (k !== 'content') el.key = `meta[${k}="${v}"]`; }, remove() { els.delete(el.key); }};
      return el;
    },
    head: {append: el => els.set(el.key, el)},
  };
}

test('writeHead sets title, canonical, robots, description, og and twitter', () => {
  const doc = fakeDoc(['link[rel="canonical"]', 'meta[name="robots"]', 'meta[property="og:title"]']);
  writeHead(doc, {title: 'HB 1: Water', description: 'Relating to water.', canonical: 'https://billatlas.org/bill/HB1', robots: null});
  assert.equal(doc.title, 'HB 1: Water · Texas Bill Atlas');
  assert.equal(doc.els.get('link[rel="canonical"]').href, 'https://billatlas.org/bill/HB1');
  assert.equal(doc.els.has('meta[name="robots"]'), false);  // Indexable: the robots meta goes.
  const content = key => doc.els.get(key)?.attrs.content;
  assert.equal(content('meta[property="og:title"]'), 'HB 1: Water');
  assert.equal(content('meta[name="twitter:title"]'), 'HB 1: Water');
  assert.equal(content('meta[name="description"]'), 'Relating to water.');
  assert.equal(content('meta[property="og:description"]'), 'Relating to water.');
  assert.equal(content('meta[property="og:url"]'), 'https://billatlas.org/bill/HB1');
  assert.equal(content('meta[property="og:image"]'), 'https://billatlas.org/social-card.png');
  writeHead(doc, {title: HOME_TITLE, description: HOME_DESCRIPTION, canonical: 'https://billatlas.org/', robots: 'noindex, follow'});
  assert.equal(doc.title, HOME_TITLE);  // Not "... · Texas Bill Atlas" twice.
  assert.equal(content('meta[name="robots"]'), 'noindex, follow');
});
