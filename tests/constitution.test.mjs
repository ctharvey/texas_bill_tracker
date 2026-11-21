// The Texas Constitution (#20): keys "CN <article>.<section>" (CN 8.1-b) at /law/CN/<article>/<section>; articles
// are its chapters ("CN 8" at /law/CN/8). The section part keeps the official case ("CN 1.3a").
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, rmSync, writeFileSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {parseLocation, parseHash, buildUrl, buildHash, lawPath, chapterPath, isAppPath} from '../src/prefs.js';
import {STATUTE_KEY, isChapterKey, chapterOf, isLawFollowQuery, statuteFile, statuteLabel, officialStatuteUrl,
  parseStatuteQuery, parseChapterQuery, canonicalLawKey, lawChapterOutline, lawCopyUnits, lawSearchMatches,
  LAW_CODE_NAMES, lawCopyVersions, closestLawVersion} from '../src/features/statutes/model.js';
import {lawCodeList, codeChapters} from '../src/features/lawcodes/model.js';
import {lawHead, chapterHead, lawCodeHead} from '../src/core/head.js';
import {loadLaw} from '../scripts/build_agent.mjs';

test('a section address names its article and section, and round-trips', () => {
  assert.equal(lawPath('CN 8.1-b'), '/law/CN/8/1-b');
  assert.equal(buildUrl('statute', {}, {statute: 'CN 3.49-d-14'}), '/law/CN/3/49-d-14');
  for (const key of ['CN 8.1-b', 'CN 1.3a', 'CN 16.13A', 'CN 3.49-d-14', 'CN 1.1']) {
    const p = parseLocation(buildUrl('statute', {}, {statute: key}), '');
    assert.deepEqual([p.view, p.statute], ['statute', key], key);
  }
  assert.equal(parseLocation('/law/CN/1/3a/', '').statute, 'CN 1.3a');
  assert.equal(parseLocation('/law/cn/8/1-b', '').statute, 'CN 8.1-b');
  assert.ok(isAppPath('/law/CN/8/1-b'));
});

test('an article is the chapter view', () => {
  assert.equal(chapterPath('CN 8'), '/law/CN/8');
  const p = parseLocation('/law/CN/8', '');
  assert.deepEqual([p.view, p.statute], ['statute', 'CN 8']);
  assert.ok(isChapterKey('CN 8'));
  assert.ok(!isChapterKey('CN 123'));
  assert.equal(chapterOf('CN 8.1-b'), 'CN 8');
});

test('malformed Constitution addresses are not sections', () => {
  for (const path of ['/law/CN/8/1--b', '/law/CN/123/1', '/law/CN/8/-b', '/law/CN/0/1']) {
    assert.notEqual(parseLocation(path, '').statute, path.includes('123') ? 'CN 123.1' : 'CN 8.1--b', path);
    assert.ok(!['CN 8.1--b', 'CN 123.1', 'CN 8.-b', 'CN 0.1'].includes(parseLocation(path, '').statute), path);
  }
  assert.ok(!STATUTE_KEY.test('PE 1-b'));
  assert.ok(!STATUTE_KEY.test('PE 46.06-a'));
  assert.ok(STATUTE_KEY.test('PE 46.06'));
});

test('the old hash form keeps working', () => {
  assert.equal(parseHash('#statute?law=CN&sec=8.1-b').statute, 'CN 8.1-b');
  assert.equal(parseHash('#chapter?law=CN&ch=8').statute, 'CN 8');
  assert.equal(buildHash('statute', {}, {statute: 'CN 8.1-b'}), '#statute?law=CN&sec=8.1-b');
});

test('labels, files and official links', () => {
  assert.equal(statuteLabel('CN 8.1-b'), 'Tex. Const. art. 8, \u00a7 1-b');
  assert.equal(statuteLabel('CN 8'), 'Texas Constitution, Article 8');
  assert.equal(statuteFile('CN 8.1-b'), 'CN-8.1-b.json');
  assert.equal(officialStatuteUrl('CN 8.1-b'), 'https://statutes.capitol.texas.gov/Docs/CN/htm/CN.8.htm#8.1-b');
  assert.equal(officialStatuteUrl('CN 8'), 'https://statutes.capitol.texas.gov/Docs/CN/htm/CN.8.htm');
  assert.equal(lawHead('Texas Constitution', 'CN', '8.1-b', 'HOMESTEADS').title, 'Tex. Const. art. 8, \u00a7 1-b: HOMESTEADS');
  assert.equal(chapterHead('Texas Constitution', '8', 'TAXATION AND REVENUE', 'Article').title,
    'Texas Constitution, Article 8: Taxation and Revenue');
  assert.equal(lawCodeHead('Texas Constitution').title, 'Texas Constitution: every article');
  assert.equal(lawCodeHead('Penal Code').title, 'Texas Penal Code: every chapter');
});

test('Constitution keys are follows, typed in any case or as a citation', () => {
  assert.ok(isLawFollowQuery('CN 8.1-b'));
  assert.ok(isLawFollowQuery('CN 8'));
  assert.equal(canonicalLawKey('cn 8.1-b'), 'CN 8.1-b');
  assert.equal(canonicalLawKey('pe 46.06'), 'PE 46.06');
  assert.deepEqual(parseStatuteQuery('Tex. Const. art. 8, \u00a7 1-b'), {code: 'CN', sec: '8.1-b'});
  assert.deepEqual(parseStatuteQuery('Texas Constitution 8.1-b'), {code: 'CN', sec: '8.1-b'});
  assert.equal(parseChapterQuery('Texas Constitution article 8'), 'CN 8');
  assert.equal(parseChapterQuery('Texas Constitution article 123'), null);
});

test('the code list names the Constitution and its 17 articles, without the appendix and preamble', () => {
  assert.equal(LAW_CODE_NAMES.CN, 'Texas Constitution');
  const headings = {8: 'ARTICLE 8. TAXATION AND REVENUE', 1: 'ARTICLE 1. BILL OF RIGHTS', 10: 'ARTICLE 10. RAILROADS',
    ap: '', pr: ''};
  const index = {format: 'texas-bill-law-v1', codes: {CN: {name: 'The Texas Constitution', headings}}};
  assert.deepEqual(codeChapters(index, 'CN').map(([c]) => c), ['1', '8', '10']);
  assert.deepEqual(codeChapters(index, 'CN')[1], ['8', 'TAXATION AND REVENUE']);
  assert.deepEqual(lawCodeList(index).map(r => r[0]), ['CN']);
});

test('an article file reads as an outline, and a section is found by its own number', () => {
  const md = '# The Texas Constitution, ARTICLE 8. TAXATION AND REVENUE\n\nARTICLE 8. TAXATION AND REVENUE\n\n'
    + '## Sec. 1. EQUALITY AND UNIFORMITY. Taxation shall be equal.\n\n## Sec. 1-b. HOMESTEAD EXEMPTIONS. Homesteads are exempt.\n';
  const outline = lawChapterOutline(md);
  assert.equal(outline.heading, 'TAXATION AND REVENUE');
  assert.deepEqual(outline.sections.map(s => s[0]), ['1', '1-b']);
  const units = lawCopyUnits(md, '1-b');
  assert.ok(units && units.some(u => /Homesteads are exempt/.test(u.text)));
  assert.ok(!lawCopyUnits(md, '1-b').some(u => /Taxation shall be equal/.test(u.text)));
});

test('heading search keeps Constitution rows', () => {
  const shard = [['CN 8.1-b', 'HOMESTEAD EXEMPTIONS'], ['CN 8', 'TAXATION AND REVENUE'], ['CV 1.1', 'HOMESTEAD THINGS']];
  assert.deepEqual(lawSearchMatches(shard, ['homestead']), [['CN 8.1-b', 'HOMESTEAD EXEMPTIONS']]);
});

test('the route list serves Constitution sections', () => {
  const routes = JSON.parse(readFileSync(new URL('../public/routes.json', import.meta.url), 'utf8'));
  const statute = new RegExp(routes.routes.find(r => r.view === 'statute').match);
  for (const path of ['/law/CN/8/1-b', '/law/CN/3/49-d-14', '/law/CN/1/3a', '/law/CN/8', '/law/PE/46.06'])
    assert.ok(statute.test(path), path);
  for (const path of ['/law/CN/8/1-b/x', '/law/cn/8/1-b', '/law/PE/46/1']) assert.ok(!statute.test(path), path);
});

test('the agent edition reads a section from its own article', () => {
  const dir = mkdtempSync(join(tmpdir(), 'agent-cn-'));
  try {
    mkdirSync(join(dir, 'statutes'));
    mkdirSync(join(dir, 'law', 'CN'), {recursive: true});
    writeFileSync(join(dir, 'statutes', 'index.json'), JSON.stringify({format: 'texas-bill-statutes-v1', codes: {},
      sections: {'CN 8.1': {h: '', b: [['HJR1', 'm']]}}, bills: {}}));
    writeFileSync(join(dir, 'law', 'index.json'), JSON.stringify({format: 'texas-bill-law-v1',
      codes: {CN: {name: 'The Texas Constitution'}}}));
    writeFileSync(join(dir, 'law', 'CN', 'index.json'), JSON.stringify({format: 'texas-bill-law-v1', code: 'CN', chapters: {
      1: {heading: 'ARTICLE 1. BILL OF RIGHTS', file: 'CN/1.md', sha256: 'a'.repeat(64), sections: [['1', 'Sec. 1. FREEDOM.']]},
      8: {heading: 'ARTICLE 8. TAXATION', file: 'CN/8.md', sha256: 'b'.repeat(64), sections: [['1', 'Sec. 1. EQUALITY.']]}}}));
    writeFileSync(join(dir, 'law', 'CN', '1.md'), '# CN 1\n\n## Sec. 1. FREEDOM. Texas is a free state.\n');
    writeFileSync(join(dir, 'law', 'CN', '8.md'), '# CN 8\n\n## Sec. 1. EQUALITY. Taxation shall be equal.\n');
    const [item] = loadLaw(dir, ['HJR1']).get('HJR1');
    assert.equal(item.section, '8.1');
    assert.equal(item.heading, 'Sec. 1. EQUALITY.');
    assert.match(item.text, /Taxation shall be equal/);
    assert.equal(item.official, 'https://statutes.capitol.texas.gov/Docs/CN/htm/CN.8.htm#8.1');
    assert.equal(item.local, undefined);
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
});

test('citations name an article in Roman numerals, without a comma, or in the order bills use', () => {
  const cases = {
    'Tex. Const. art. VIII, \u00a7 1-b': '8.1-b',
    'Tex. Const. art. VIII \u00a7 1-b': '8.1-b',
    'Texas Constitution article 8 section 1-b': '8.1-b',
    'Texas Constitution, Article XVII, Section 1': '17.1',
    'Section 1-b, Article VIII, Texas Constitution': '8.1-b',
    'Sec. 49-d-14, Art. III, Tex. Const.': '3.49-d-14',
    'Section 1(g)': null,
  };
  for (const [text, sec] of Object.entries(cases))
    assert.deepEqual(parseStatuteQuery(text), sec ? {code: 'CN', sec} : null, text);
  assert.equal(parseStatuteQuery('Tex. Const. art. IIII, \u00a7 1'), null, 'a malformed numeral is not an article');
  assert.equal(parseStatuteQuery('Tex. Const. art. VX, \u00a7 1'), null);
  assert.equal(parseChapterQuery('Texas Constitution article VIII'), 'CN 8');
  assert.equal(parseChapterQuery('Tex. Const. art. XIV'), 'CN 14');
  assert.deepEqual(parseStatuteQuery('Penal Code \u00a7 46.06', {PE: 'Penal Code'}), {code: 'PE', sec: '46.06'});
});

test('a number used for two sections keeps both, and a bill is set against the one it rewrites', () => {
  const md = '# The Texas Constitution, ARTICLE 8. TAXATION AND REVENUE\n\n'
    + '## Sec. 1-n. EXEMPTION OF RAW COCOA AND GREEN COFFEE. (a) The legislature may exempt raw cocoa and green coffee held in Harris County.\n\n'
    + '## Sec. 1-n. EXEMPTION OF GOODS IN TRANSIT. (a) To promote economic development, goods held temporarily in a warehouse are exempt.\n';
  const versions = lawCopyVersions(md, '1-n');
  assert.equal(versions.length, 2);
  assert.match(versions[0][0].text, /RAW COCOA/);
  assert.match(versions[1][0].text, /GOODS IN TRANSIT/);
  assert.deepEqual(lawCopyUnits(md, '1-n'), versions[0], 'one text still reads as the first');
  const dir = mkdtempSync(join(tmpdir(), 'agent-cn-dup-'));
  try {  // The agent edition keeps both texts too, in file order.
    mkdirSync(join(dir, 'statutes'));
    mkdirSync(join(dir, 'law', 'CN'), {recursive: true});
    writeFileSync(join(dir, 'statutes', 'index.json'), JSON.stringify({format: 'texas-bill-statutes-v1', codes: {},
      sections: {'CN 8.1-n': {h: '', b: [['HJR1', 'm']]}}, bills: {}}));
    writeFileSync(join(dir, 'law', 'index.json'), JSON.stringify({format: 'texas-bill-law-v1', codes: {CN: {name: 'The Texas Constitution'}}}));
    writeFileSync(join(dir, 'law', 'CN', 'index.json'), JSON.stringify({format: 'texas-bill-law-v1', code: 'CN', chapters: {
      8: {heading: 'ARTICLE 8. TAXATION', file: 'CN/8.md', sha256: 'b'.repeat(64),
        sections: [['1-n', 'Sec. 1-n. RAW COCOA.'], ['1-n', 'Sec. 1-n. GOODS IN TRANSIT.']]}}}));
    writeFileSync(join(dir, 'law', 'CN', '8.md'), md);
    const [item] = loadLaw(dir, ['HJR1']).get('HJR1');
    assert.ok(item.text.indexOf('RAW COCOA') < item.text.indexOf('GOODS IN TRANSIT') && item.text.includes('RAW COCOA'));
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
  const bill = [{label: 'a', text: '(a) To promote economic development, goods and wares held temporarily in a warehouse are exempt.'}];
  assert.equal(closestLawVersion(versions, bill), versions[1]);
  assert.equal(closestLawVersion(versions, [{label: 'a', text: 'raw cocoa and green coffee'}]), versions[0]);
  assert.equal(closestLawVersion(versions, []), versions[0], 'with no wording to go on, the first');
});
