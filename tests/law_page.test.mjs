import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHash, parseLocation, buildUrl, lawPath} from '../src/prefs.js';

test('a law section has its own address', () => {
  assert.equal(buildUrl('statute', {}, {statute: 'PE 46.06'}), '/law/PE/46.06');
  assert.equal(buildUrl('statute', {}, {statute: 'ED 30A.151'}), '/law/ED/30A.151');
  assert.equal(lawPath('PE 46.06'), '/law/PE/46.06');
  const p = parseLocation('/law/PE/46.06', '');
  assert.deepEqual([p.view, p.statute], ['statute', 'PE 46.06']);
  assert.equal(parseLocation('/law/PE/46.06/', '').statute, 'PE 46.06');
  assert.equal(parseLocation('/law/ed/30a.151', '').statute, 'ED 30A.151');
});

test('a law address round-trips through buildUrl', () => {
  for (const key of ['PE 46.06', 'GV 2271.002', 'CR 42.12', 'ED 29.002']) {
    const url = buildUrl('statute', {}, {statute: key});
    const [path, hash = ''] = url.split('#');
    assert.equal(parseLocation(path, hash ? `#${hash}` : '').statute, key);
  }
});

test('an old #statute link still opens the section, and is rewritten to the law address', () => {
  const p = parseLocation('/', '#statute?law=PE&sec=46.06');
  assert.deepEqual([p.view, p.statute], ['statute', 'PE 46.06']);
  assert.equal(buildUrl(p.view, p.filters, {statute: p.statute}), '/law/PE/46.06');
});

test('a law page keeps an open bill and a shared list in the fragment; the path wins over law and sec', () => {
  const url = buildUrl('statute', {topic: 'Water'}, {statute: 'PE 46.06', bill: 'HB5', list: ['HB5', 'SB2']});
  assert.equal(url, '/law/PE/46.06#list=HB5,SB2&bill=HB5');
  const p = parseLocation('/law/PE/46.06', '#list=HB5,SB2&bill=HB5');
  assert.deepEqual([p.statute, p.bill, p.list], ['PE 46.06', 'HB5', ['HB5', 'SB2']]);
  assert.equal(parseLocation('/law/PE/46.06', '#law=GV&sec=1.01').statute, 'PE 46.06');
});

test('a malformed law address never opens a section, and other views have their own paths', () => {
  assert.equal(parseLocation('/law/PE/46', '').statute, 'PE 46');  // A whole chapter, not a malformed section.
  for (const path of ['/law/PEN/46.06', '/law/PE/46.06/extra']) {
    assert.deepEqual(parseLocation(path, '#all'), parseHash('#all'));  // Not a law address: the fragment decides.
  }
  assert.equal(parseLocation('/law/PE/1.12345678901234567', '').view, 'all');  // Shaped right but too long.
  assert.equal(lawPath('PE'), null);
  assert.equal(lawPath(null), null);
  assert.equal(buildUrl('statute', {}, {statute: null}), '/#statute');
  assert.equal(buildUrl('member', {}, {member: 'A4875'}), '/member/A4875');
  assert.deepEqual(parseLocation('/', '#all?topic=Water'), parseHash('#all?topic=Water'));
});
