// Not-found views are marked data-not-found, and a marked view is not indexed (issue #37). The app reads the mark
// to write its meta (core/location.js); scripts/check_pages.py reads the same mark.
import test from 'node:test';
import assert from 'node:assert/strict';
import {state} from '../src/core/state.js';
import {pageMeta, topicSlug} from '../src/core/routes.js';
import {agencyMarkup, topicMarkup} from '../src/features/groups/view.js';
import {memberMarkup} from '../src/features/members/view.js';
import {statuteMarkup} from '../src/features/statutes/view.js';
import {lawCodeMarkup} from '../src/features/lawcodes/view.js';
import {POLICY_AREAS} from '../src/taxonomy.js';

const marked = html => /\sdata-not-found[\s>]/.test(html);

test('a missing view points at the home page and is not indexed', () => {
  const site = 'https://billatlas.org';
  for (const [view, url] of [['agency', '/agency/zzz'], ['topic', '/topic/zzz'], ['member', '/member/A9999/x'],
    ['bill', '/bill/HB99999'], ['statute', '/law/PE/46.06'], ['lawcode', '/law/ZZ']]) {
    const meta = pageMeta(view, url, false, true);
    assert.deepEqual([meta.canonical, meta.robots], [`${site}/`, 'noindex, follow'], url);
    assert.deepEqual([pageMeta(view, url).canonical, pageMeta(view, url).robots], [site + url, null], url);
  }
});

test('unknown agency and topic are marked; known ones are not', () => {
  Object.assign(state, {bills: [], luna: null, agencyId: 'zzz', topicSlug: 'zzz'});
  assert.ok(marked(agencyMarkup()));
  assert.ok(marked(topicMarkup()));
  state.agencyId = 'tceq';
  state.topicSlug = topicSlug(POLICY_AREAS[0].name);
  assert.ok(!marked(agencyMarkup()));
  assert.ok(!marked(topicMarkup()));
});

test('unknown member is marked; a roster that failed to load is not a not-found', () => {
  state.roster = {members: {}};
  state.memberCode = 'A9999';
  assert.ok(marked(memberMarkup()));
  state.roster = null;
  assert.ok(!marked(memberMarkup()));
});

test('a law address with no section is marked', () => {
  state.statuteKey = null;
  assert.ok(marked(statuteMarkup()));
});

test('an unknown code is marked', () => {
  state.lawCode = 'ZZ';
  assert.ok(marked(lawCodeMarkup()));
});
