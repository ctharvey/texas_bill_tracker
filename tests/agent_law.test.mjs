import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {buildPages, loadLaw, LAW_INLINE_MAX} from '../scripts/build_agent.mjs';

const BILLS = [{id: 'HB486', caption: 'Relating to hunting from a public road.', author: 'Doe', authors: ['Doe'],
  status: 'Filed', last_action: '11/10/2026 H Filed', actions: ['Filed'], filed_at: '2026-11-10'},
  {id: 'HB9', caption: 'Relating to nothing in statute.', author: 'Doe', authors: ['Doe'], status: 'Filed',
    last_action: '11/10/2026 H Filed', actions: ['Filed'], filed_at: '2026-11-10'}];
const snapshot = {session: '90R', data_mode: 'official-ftp', author_profiles: {}, bills: BILLS};
const SHA = 'a'.repeat(64);

function live({longText = false, statutes = true} = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'agent-law-'));
  mkdirSync(join(dir, 'statutes'));
  mkdirSync(join(dir, 'law', 'PW'), {recursive: true});
  if (statutes) writeFileSync(join(dir, 'statutes', 'index.json'), JSON.stringify({format: 'texas-bill-statutes-v1', codes: {},
    sections: {'PW 62.0031': {h: '', b: [['HB486', 'm']]}, 'PW 62.0032': {h: '', b: [['HB486', 'n']]},
      'PW 99.001': {h: '', b: [['HB486', 'r']]}, '../x 1.1': {h: '', b: [['HB486', 'm']]}}, bills: {}}));
  writeFileSync(join(dir, 'law', 'index.json'), JSON.stringify({format: 'texas-bill-law-v1',
    codes: {PW: {name: 'Parks and Wildlife Code', copied_at: '2026-11-19T00:00:00+00:00'}}}));
  writeFileSync(join(dir, 'law', 'PW', 'index.json'), JSON.stringify({format: 'texas-bill-law-v1', code: 'PW', chapters: {
    62: {heading: 'CHAPTER 62. RESTRICTIONS', file: 'PW/62.md', sha256: SHA,
      sections: [['62.003', 'Sec. 62.003. HUNTING FROM VEHICLES.'], ['62.0031', 'Sec. 62.0031. HUNTING FROM PUBLIC ROAD.']]},
    evil: {heading: 'x', file: '../../etc/passwd', sections: [['99.001', 'Sec. 99.001. X.']]}}}));
  const body = longText ? 'x'.repeat(LAW_INLINE_MAX + 10) : '(a) A person may not hunt from a public road.';
  writeFileSync(join(dir, 'law', 'PW', '62.md'), '# Parks and Wildlife Code, CHAPTER 62\n\n## Sec. 62.003. HUNTING FROM VEHICLES. '
    + 'Other text.\n\n## Sec. 62.0031. HUNTING FROM PUBLIC ROAD. ' + body + '\n\nAdded by Acts 1991.\n');
  return dir;
}

test('a bill page shows current law for each section it changes', (t) => {
  const dir = live(); t.after(() => rmSync(dir, {recursive: true, force: true}));
  const law = loadLaw(dir, ['HB486', 'HB9']);
  const items = law.get('HB486');
  assert.deepEqual(items.map(i => [i.section, i.action]),
    [['62.0031', 'amended'], ['62.0032', 'added (new section)'], ['99.001', 'repealed']]);
  const amended = items[0];
  assert.equal(amended.url, 'https://billatlas.org/live/law/PW/62.md');
  assert.equal(amended.official, 'https://statutes.capitol.texas.gov/Docs/PW/htm/PW.62.htm');
  assert.equal(amended.copy_sha256, SHA);
  assert.match(amended.text, /^Sec\. 62\.0031\. HUNTING FROM PUBLIC ROAD\. \(a\) A person may not hunt/);
  assert.match(amended.text, /Added by Acts 1991\./);
  assert.doesNotMatch(amended.text, /62\.003\. HUNTING FROM VEHICLES/);  // only the cited section
  assert.equal(items[2].url, null);  // a chapter whose file is not its own path is never read
  const page = buildPages({snapshot, minBills: 1, law}).get('bills/HB486.md');
  assert.match(page, /### Current law this bill changes/);
  assert.match(page, /Parks and Wildlife Code §62\.0031 \(amended\): Sec\. 62\.0031\. HUNTING FROM PUBLIC ROAD\./);
  assert.match(page, /§62\.0032 \(added \(new section\)\)\n {2}- New section: no current text\./);
  assert.match(page, /§99\.001 \(repealed\)\n {2}- Not found in this site's copy of current law\./);
  assert.doesNotMatch(page, /\.\.\/x/);
  assert.doesNotMatch(buildPages({snapshot, minBills: 1, law}).get('bills/HB9.md'), /Current law/);
  assert.equal(JSON.parse(buildPages({snapshot, minBills: 1, law}).get('bills/HB486.json')).current_law.length, 3);
});

test('a long section is linked, not copied', (t) => {
  const dir = live({longText: true}); t.after(() => rmSync(dir, {recursive: true, force: true}));
  const item = loadLaw(dir, ['HB486']).get('HB486')[0];
  assert.equal(item.text, null);
  assert.equal(item.url, 'https://billatlas.org/live/law/PW/62.md');
});

test('without a law copy or statute index the section is left out', (t) => {
  const dir = live({statutes: false}); t.after(() => rmSync(dir, {recursive: true, force: true}));
  assert.equal(loadLaw(dir, ['HB486']), null);
  assert.doesNotMatch(buildPages({snapshot, minBills: 1, law: null}).get('bills/HB486.md'), /Current law/);
});
