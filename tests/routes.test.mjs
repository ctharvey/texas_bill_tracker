import test from 'node:test';
import assert from 'node:assert/strict';
import {ROUTES, routeForPath, routeForView, slugify} from '../src/core/routes.js';
import {VIEWS, FILTER_DEFAULTS, parseHash, parseLocation, buildUrl, isAppPath} from '../src/prefs.js';

// Splits a built address the way the browser does, then reads it back.
function reread(url) {
  const u = new URL(url, 'https://billatlas.org');
  return parseLocation(u.pathname, u.hash, u.search);
}

const KEYS = {bill: {bill: 'HB5'}, statute: {statute: 'PE 46.06'}, member: {member: 'A4395'}};

test('every view has exactly one route, and fixed paths are unique', () => {
  assert.deepEqual([...ROUTES.map(r => r.view)].sort(), [...VIEWS].sort());
  const paths = ROUTES.filter(r => r.path).map(r => r.path);
  assert.equal(new Set(paths).size, paths.length);
  for (const r of ROUTES) assert.equal(typeof r.indexable, 'boolean', r.view);
  assert.equal(routeForPath('/today/').view, 'today');
  assert.equal(routeForPath('/index.html').view, 'home');
  assert.equal(routeForPath('/nope'), null);
  assert.equal(routeForView('nope'), null);
});

test('every view round-trips through its path', () => {
  for (const view of VIEWS) {
    const url = buildUrl(view, {}, KEYS[view] || {});
    assert.ok(!url.includes('#'), `${view}: ${url}`);
    const p = reread(url);
    assert.equal(p.view, view, url);
    if (KEYS[view]) assert.equal(p[Object.keys(KEYS[view])[0]], Object.values(KEYS[view])[0], url);
  }
  assert.equal(buildUrl('all', {}), '/explorer');
  assert.equal(buildUrl('local', {}), '/near-you');
  assert.equal(buildUrl('method', {}), '/about/method');
  assert.equal(buildUrl('home', {}), '/');
  assert.equal(buildUrl('nope', {}), '/explorer');  // An unknown view is the explorer, as when reading.
});

test('every filter round-trips in the query string of the explorer and the watchlist, defaults left out', () => {
  const filters = {query: 'clean water & "air"', topic: 'Water', area: 'houston', agency: 'tceq', chamber: 'House', party: 'R',
    stage: 'Heard', action: 'Passed', outlook: 'Scheduled', sort: 'latest', onlyWatch: true, companion: true};
  assert.deepEqual(Object.keys(filters).sort(), Object.keys(FILTER_DEFAULTS).sort());
  for (const view of ['all', 'watchlist']) {
    const url = buildUrl(view, filters);
    assert.match(url, /^\/(explorer|watchlist)\?/);
    assert.deepEqual(reread(url).filters, filters, url);
  }
  assert.equal(buildUrl('all', {...FILTER_DEFAULTS, topic: 'Water'}), '/explorer?topic=Water');
  assert.equal(buildUrl('all', {onlyWatch: false, companion: true}), '/explorer?companion=1');
  // Views without filters never write them, and a query on them is ignored.
  assert.equal(buildUrl('today', {topic: 'Water'}), '/today');
  assert.deepEqual(parseLocation('/today', '', '?topic=Water'), parseHash('#today'));
  assert.equal(parseLocation('/explorer', '', '?sort=__proto__').filters.sort, undefined);
});

test('a key in the path: bills, sections, chapters and members', () => {
  assert.equal(buildUrl('statute', {}, {statute: 'PE 46'}), '/law/PE/46');
  assert.deepEqual([reread('/law/pe/12a').view, reread('/law/pe/12a').statute], ['statute', 'PE 12A']);
  assert.equal(buildUrl('member', {}, {member: 'A4395', slug: 'Kyle Alders'}), '/member/A4395/kyle-alders');
  for (const path of ['/member/A4395', '/member/A4395/', '/member/a4395/kyle-alders', '/member/A4395/wrong-name'])
    assert.equal(parseLocation(path, '').member, 'A4395', path);
  // A route's shape with a bad key is the explorer; a path that is no route reads its fragment, as before.
  for (const path of ['/member/B1234', '/bill/HB0', '/law/PE/123456789']) assert.equal(parseLocation(path, '').view, 'all', path);
  for (const path of ['/member/B12', '/member/A4395/x/y', '/nope']) assert.deepEqual(parseLocation(path, '#today'), parseHash('#today'), path);
  // A keyed view without its key keeps the old form, which opens the explorer.
  assert.equal(buildUrl('member', {}, {member: null}), '/#member');
});

test('slugs are plain lowercase words joined by dashes', () => {
  assert.equal(slugify('José Menéndez'), 'jose-menendez');
  assert.equal(slugify("  O'Brien, Jr. "), 'o-brien-jr');
  assert.equal(slugify(''), '');
  assert.equal(slugify(null), '');
  assert.ok(slugify('a'.repeat(100)).length <= 60);
});

test('every old #view link opens the same view as its path', () => {
  const old = {home: '', today: '#today', all: '#all?topic=Water&sort=latest', local: '#local', watchlist: '#watchlist?party=D',
    following: '#following', agencies: '#agencies', review: '#review', method: '#method', saving: '#saving', export: '#export',
    data: '#data', bill: '#bill?id=hb5', statute: '#statute?law=PE&sec=46.06', member: '#member?code=A4395'};
  assert.deepEqual(Object.keys(old).sort(), [...VIEWS].sort());
  for (const [view, hash] of Object.entries(old)) {
    const p = parseLocation('/', hash);
    assert.equal(p.view, view, hash);
    const url = buildUrl(p.view, p.filters, {bill: p.bill, statute: p.statute, member: p.member});
    assert.ok(!url.startsWith('/#'), `${hash} -> ${url}`);
    assert.deepEqual(reread(url), p, `${hash} -> ${url}`);
  }
  assert.equal(parseLocation('/', '#chapter?law=PE&ch=46').statute, 'PE 46');
  assert.equal(parseLocation('/', '#?query=water').view, 'all');
});

test('a shared list, an open bill and a sync key stay in the fragment, never the path or query', () => {
  const sync = 'abcdefghijklmnopqrstuv';
  for (const view of VIEWS) {
    const url = buildUrl(view, {topic: 'Water'}, {...(KEYS[view] || {}), list: ['HB5', 'SB2'], sync, ...(view === 'bill' ? {} : {bill: 'HB7'})});
    const [beforeFragment] = url.split('#');
    assert.ok(!beforeFragment.includes(sync) && !beforeFragment.includes('list=') && !beforeFragment.includes('bill=HB7'), url);
    const p = reread(url);
    assert.deepEqual([p.list, p.sync], [['HB5', 'SB2'], sync], url);
  }
  assert.equal(buildUrl('all', {}, {sync}), `/explorer#sync=${sync}`);
  assert.equal(buildUrl('home', {}, {list: ['HB5']}), '/#list=HB5');
  assert.deepEqual(reread('/#list=HB5').list, ['HB5']);
  assert.equal(reread('/#list=HB5').view, 'home');
  // A sync key or list in the query (never written) is not read: only the fragment carries them.
  assert.equal(parseLocation('/explorer', '', `?sync=${sync}&list=HB5`).sync, null);
  assert.equal(parseLocation('/explorer', '', `?sync=${sync}&list=HB5`).list, null);
});

test('#move is left alone: at the root it reads as it always has, and on a path it never changes the view', () => {
  assert.deepEqual(parseLocation('/', '#move'), parseHash('#move'));
  assert.deepEqual(parseLocation('/today', '#move'), parseHash('#today'));
  assert.deepEqual(parseLocation('/bill/HB5', '#move').bill, 'HB5');
});

test("only the app's own paths open in place; files and unknown paths are left to the browser", () => {
  for (const view of VIEWS) assert.ok(isAppPath(buildUrl(view, {}, KEYS[view] || {}).split(/[?#]/)[0]), view);
  for (const path of ['/law/PE/46', '/member/A4395/kyle-alders', '/today/'])
    assert.ok(isAppPath(path), path);
  for (const path of ['/live/feeds/HB1.xml', '/live/sitemap.xml', '/app.css', '/agent/', '/nope', '/bill/', '/law/PE'])
    assert.ok(!isAppPath(path), path);
});
