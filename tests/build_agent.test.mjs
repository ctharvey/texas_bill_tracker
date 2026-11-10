import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync, mkdirSync, statSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {buildPages, writePages, loadBills, billRecord, slug, AGENT} from '../scripts/build_agent.mjs';
import {assessHearing, lastActionInfo, normalizeBill} from '../src/taxonomy.js';

const snapshot = (bills, extra = {}) => ({session: '90R', data_mode: 'official-ftp', generated_at: '2026-11-10T12:00:00Z',
  author_profiles: {}, bills, ...extra});
const BILLS = [
  {id: 'HB5', caption: 'Relating to water | groundwater districts and the Texas Water Development Board.',
    author: 'Cole', authors: ['Cole'], coauthors: ['Smith'], sponsors: [], cosponsors: [],
    status: 'Referred to Natural Resources', last_action: '11/09/2026 H Referred to Natural Resources',
    actions: ['Filed', 'Referred to Natural Resources'], action_dates: ['2026-11-08', '2026-11-09'], filed_at: '2026-11-08'},
  {id: 'SB12', caption: 'Relating to public school finance.', author: 'Hughes', authors: ['Hughes'],
    coauthors: [], sponsors: null, cosponsors: null, status: 'Filed', last_action: '11/10/2026 S Filed', actions: ['Filed'],
    filed_at: '2026-11-10'},
  {id: 'XX1', caption: 'Not a bill id'},
];
const TAGS = {format: 'texas-bill-luna-tags-v1', generated_at: '2026-11-10T13:00:00Z', agencies: {twdb: 'Texas Water Development Board'},
  bills: {HB5: {reviewed_at: '2026-11-10', summary: 'Changes groundwater district rules.', text_version: 'Introduced',
    policy_tags: [{tag: 'Water'}], agencies: [{id: 'twdb', impact: 'direct', explanation: 'Named in section 2.'}]}}};
const ROSTER = {format: 'texas-bill-members-v1', generated_at: '2026-11-10T09:00:00Z', members: {
  'house|Cole': {full_name: 'Sheryl Cole', chamber: 'house', party: 'Democratic', district: 46, years_served: 8, first_year: 2019,
    service: [{}], links: {lrl: 'https://lrl.texas.gov/x', bad: 'javascript:alert(1)'}},
  'house|Smith': {full_name: 'Reggie Smith', chamber: 'house', party: 'Republican', district: 62, years_served: 6, service: [{}], links: {}}}};
const build = (over = {}) => buildPages({snapshot: snapshot(BILLS), tags: TAGS, roster: ROSTER, minBills: 1, ...over});

test('bill records use the tracker pipeline: Luna overlay, roster, hearing and last action', () => {
  const files = build();
  const hb5 = JSON.parse(files.get('bills/HB5.json'));
  const raw = normalizeBill(BILLS[0], {});
  assert.equal(hb5.last_action.category, lastActionInfo(raw).label);
  assert.equal(hb5.hearing.status, assessHearing(raw).label);
  assert.deepEqual(hb5.topics, ['Water']);
  assert.deepEqual(hb5.agencies.map(a => [a.id, a.name, a.relationship, a.source]),
    [['twdb', 'Texas Water Development Board', 'direct', 'luna-full-text']]);
  assert.equal(hb5.authorship_party.label, 'Bipartisan authors');
  assert.equal(hb5.people.authors[0].full_name, 'Sheryl Cole');
  assert.deepEqual(hb5.people.authors[0].links, {lrl: 'https://lrl.texas.gov/x'});
  assert.equal(hb5.full_text_review.summary, 'Changes groundwater district rules.');
  assert.equal(hb5.links.tracker, 'https://bills.ctharvey.me/#all?bill=HB5');
  const sb12 = JSON.parse(files.get('bills/SB12.json'));
  assert.equal(sb12.people.sponsors, null);
  assert.equal(sb12.full_text_review, null);
  assert.ok(!files.has('bills/XX1.json'));
});

test('markdown pages escape table cells and list every group with tracker links', () => {
  const files = build();
  assert.match(files.get('bills/index.md'), /water \\\| groundwater/);
  assert.match(files.get('bills/HB5.md'), /^# HB 5: /);
  assert.match(files.get('bills/HB5.md'), /1\. 2026-11-08: Filed/);
  assert.ok(files.has(`topics/${slug('Water')}.md`));
  assert.match(files.get('topics/water.md'), /#all\?topic=Water/);
  assert.ok(files.has('agencies/twdb.md'));
  assert.ok(files.has('authors/house-cole.md') && files.has('authors/house-smith.md'));
  assert.match(files.get('authors/house-smith.md'), /\| coauthor \|/);
  assert.equal(files.get('llms.txt'), files.get('index.md'));
  // Every agent link on the overview resolves to a generated file.
  for (const [, path] of files.get('index.md').matchAll(new RegExp(`\\]\\(${AGENT.replace(/\./g, '\\.')}([^)]+)\\)`, 'g')))
    assert.ok(files.has(path), path);
  const all = JSON.parse(files.get('data/bills.json'));
  assert.deepEqual(all.bills.map(b => b.id), ['HB5', 'SB12']);
  assert.equal(all.tags_as_of, '2026-11-10T13:00:00Z');
});

test('output is deterministic: identical inputs give identical files', () => {
  const a = build(), b = build();
  assert.deepEqual([...a], [...b]);
});

test('unofficial or incomplete snapshots are refused', () => {
  assert.throws(() => loadBills({snapshot: snapshot(BILLS, {data_mode: 'curated'}), minBills: 1}), /Refusing/);
  assert.throws(() => loadBills({snapshot: snapshot(BILLS)}), /Refusing/);  // Fewer than 1000 bills.
});

test('missing or malformed tags and roster fall back to caption rules', () => {
  const files = buildPages({snapshot: snapshot(BILLS), tags: {format: 'other'}, roster: {members: []}, minBills: 1});
  const hb5 = JSON.parse(files.get('bills/HB5.json'));
  assert.equal(hb5.full_text_review, null);
  assert.equal(hb5.people.authors[0].matched, false);
  assert.ok(hb5.agencies.every(a => a.source === 'caption-rules'));
});

test('writePages rewrites only changed files, removes stale pages and keeps unrelated files', () => {
  const dir = mkdtempSync(join(tmpdir(), 'agent-'));
  try {
    const first = writePages(dir, build());
    assert.equal(first.unchanged, 0);
    const before = statSync(join(dir, 'bills', 'HB5.md')).mtimeMs;
    writeFileSync(join(dir, 'bills', 'HB9.md'), 'stale');
    mkdirSync(join(dir, 'keep'));
    writeFileSync(join(dir, 'keep', 'note.html'), 'not ours');
    const fewer = buildPages({snapshot: snapshot([BILLS[0]]), tags: TAGS, roster: ROSTER, minBills: 1});
    const second = writePages(dir, fewer);
    assert.ok(second.removed >= 3);  // HB9 stale page and both SB12 files.
    assert.ok(!existsSync(join(dir, 'bills', 'HB9.md')) && !existsSync(join(dir, 'bills', 'SB12.json')));
    assert.ok(existsSync(join(dir, 'keep', 'note.html')));
    assert.equal(statSync(join(dir, 'bills', 'HB5.md')).mtimeMs, before);
    assert.equal(readFileSync(join(dir, 'llms.txt'), 'utf8'), fewer.get('llms.txt'));
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
