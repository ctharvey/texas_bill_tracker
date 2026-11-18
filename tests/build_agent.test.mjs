import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync, mkdirSync, statSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {buildPages, writePages, loadBills, billRecord, slug, AGENT, loadTexts, TEXT_INLINE_MAX, BILL_DISCLAIMER, DISCLAIMER} from '../scripts/build_agent.mjs';
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
  assert.equal(hb5.links.tracker, 'https://billatlas.org/bill/HB5');
  const sb12 = JSON.parse(files.get('bills/SB12.json'));
  assert.equal(sb12.people.sponsors, null);
  assert.equal(sb12.full_text_review, null);
  assert.ok(!files.has('bills/XX1.json'));
});

test('official subjects reach the agent record and page; older snapshots say they are not reported', () => {
  const files = build({snapshot: snapshot([{...BILLS[0], subjects: ['Artificial Intelligence', 'Water--General']}, BILLS[1]])});
  assert.deepEqual(JSON.parse(files.get('bills/HB5.json')).subjects, ['Artificial Intelligence', 'Water--General']);
  assert.match(files.get('bills/HB5.md'), /- Official subjects \(Legislative Council index\): Artificial Intelligence; Water--General/);
  assert.equal(JSON.parse(files.get('bills/SB12.json')).subjects, null);
  assert.match(files.get('bills/SB12.md'), /- Official subjects \(Legislative Council index\): not in this snapshot yet/);
});

test('companion bills appear on both bills, and a companion not in the snapshot is labelled', () => {
  const bills = [{...BILLS[0], companions: [{id: 'SB12', author: 'Hughes', relation: 'Identical'}, {id: 'SB99', author: 'Doe'}]},
    BILLS[1]];
  const files = build({snapshot: snapshot(bills)});
  const hb5 = JSON.parse(files.get('bills/HB5.json')), sb12 = JSON.parse(files.get('bills/SB12.json'));
  assert.deepEqual(hb5.companions.map(c => [c.id, c.relation, c.in_snapshot]), [['SB12', 'Identical', true], ['SB99', null, false]]);
  assert.deepEqual(sb12.companions.map(c => [c.id, c.author, c.relation]), [['HB5', 'Cole', 'Identical']]);
  assert.match(files.get('bills/HB5.md'), /- Companion bills: \[SB 12\]\(https:\/\/agent.billatlas.org\/bills\/SB12\.md\), identical, by Hughes; SB 99 \(not in this snapshot yet\), by Doe/);
  assert.match(build().get('bills/HB5.md'), /- Companion bills: none listed in the source data/);
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
  // Every agent link on the overview resolves to a generated file (search is served by the sync service).
  for (const [, path] of files.get('index.md').matchAll(new RegExp(`\\]\\(${AGENT.replace(/\./g, '\\.')}([^)]+)\\)`, 'g')))
    assert.ok(path === 'search' || files.has(path), path);
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

test('keyword pages are retired in favour of search, and the 404 page says so', () => {
  const files = build();
  assert.ok(![...files.keys()].some(path => path.startsWith('words/')));
  assert.doesNotMatch(files.get('index.md'), /words\//);
  assert.match(files.get('404.md'), /replaced by search/);
});

test('full-name member addresses point to the listed-name page', () => {
  const files = build();
  assert.match(files.get('authors/house-sheryl-cole.md'), /authors\/house-cole\.md/);
  assert.match(files.get('404.md'), /authors\/house-johnson\.md/);
  assert.ok(!files.has('authors/house-hughes-hughes.md'));
});

test('review buckets add up when a new bill is queued for a retry, with pace and order notes', () => {
  const status = {format: 'texas-bill-luna-status-v1', updated_at: '2026-11-10T19:00:00Z', running: true, current: null,
    upcoming: ['SB12'], reviewed: ['HB5'], retry: ['SB12'], failed: {}};
  const progress = buildPages({snapshot: snapshot(BILLS), tags: TAGS, roster: ROSTER, status, minBills: 1}).get('review-progress.md');
  assert.match(progress, /- Not yet published: 1\n  - Under review now or queued for a retry: 1; failed, will be retried: 0; reviewed with nothing verifiable to publish: 0; queued, not started: 0/);
  assert.match(progress, /1 review was published; at that pace the 1 unpublished bill would take about 1 day\./);
  assert.match(progress, /Only the next five are listed under Up next/);
});

test('the review pace counts back from the worker status, not the last tags change', () => {
  // Tags change only when a review changes; days later the worker is still running and nothing new was published.
  const status = {format: 'texas-bill-luna-status-v1', updated_at: '2026-11-14T19:00:00Z', running: true, current: null,
    upcoming: ['SB12'], reviewed: ['HB5'], retry: [], failed: {}};
  const progress = buildPages({snapshot: snapshot(BILLS), tags: TAGS, roster: ROSTER, status, minBills: 1}).get('review-progress.md');
  assert.match(progress, /No review was published in the 24 hours before the worker's latest status/);
  const noStatus = buildPages({snapshot: snapshot(BILLS), tags: TAGS, roster: ROSTER, minBills: 1}).get('review-progress.md');
  assert.match(noStatus, /In the 24 hours before the tags were published, 1 review was published/);
});

test('unreviewed bills get a queue position only when the worker order is clear', () => {
  const many = Array.from({length: 6}, (_, i) => ({id: `HB${i + 1}`, caption: `Relating to item ${i + 1}.`, author: 'Cole',
    authors: ['Cole'], status: 'Filed', actions: ['Filed'], filed_at: '2026-11-09'}));
  const tags = {...TAGS, bills: {}};
  const status = upcoming => ({format: 'texas-bill-luna-status-v1', updated_at: '2026-11-10T19:00:00Z', running: true,
    current: null, upcoming, reviewed: [], retry: [], failed: {}});
  const page = (upcoming, id) => buildPages({snapshot: snapshot(many), tags, status: status(upcoming), minBills: 1}).get(`bills/${id}.md`);
  assert.match(page(['HB1', 'HB2'], 'HB4'), /about number 4 in the review queue/);
  assert.match(page(['HB6', 'HB5'], 'HB4'), /about number 3 in the review queue/);  // Reverse order.
  assert.doesNotMatch(page(['HB3'], 'HB4'), /review queue/);                          // Direction unknown.
});

test('the overview and filing-date index define "Filed"', () => {
  const files = build();
  assert.match(files.get('index.md'), /prefiling opened on 2026-11-09/);
  assert.match(files.get('filed/index.md'), /"Filed" is the filing date/);
});

test('recent actions page points to date search for complete periods', () => {
  assert.match(build().get('recent.md'), /search\?filed_from=YYYY-MM-DD/);
});

test('large groups are split into linked pages that cover every bill once', () => {
  const many = Array.from({length: 320}, (_, i) => ({id: `HB${i + 1}`, caption: `Relating to item ${i + 1}.`, author: 'Cole',
    authors: ['Cole'], status: 'Filed', actions: ['Filed'], action_dates: ['2026-11-09'], filed_at: '2026-11-09'}));
  const files = buildPages({snapshot: snapshot(many), minBills: 1});
  const pages = ['bills/index.md', 'bills/index--page-2.md', 'bills/index--page-3.md'];
  assert.ok(pages.every(p => files.has(p)) && !files.has('bills/index--page-4.md'));
  const seen = pages.flatMap(p => [...files.get(p).matchAll(/^\| \[HB \d+\]\(.*?bills\/(HB\d+)\.md\)/gm)].map(m => m[1]));
  assert.equal(seen.length, 320);
  assert.equal(new Set(seen).size, 320);
  assert.match(files.get('bills/index--page-2.md'), /Page 2 of 3 \(bills 151-300 of 320\)/);
  assert.match(files.get('bills/index.md'), /320 bills/);
  assert.ok(files.has('filed/2026-11-09--page-3.md'));
  // One group holding every bill says so, and the hearing index answers plainly.
  assert.match(files.get('hearing/index.md'), /No bill has a committee hearing recorded or scheduled/);
  assert.match(files.get('chamber/index.md'), /all 320 bills are in one group \("House"\)/);
});

test('bill pages link the official text and explain empty roles with coverage', () => {
  const files = build();
  const hb5 = files.get('bills/HB5.md'), sb12 = files.get('bills/SB12.md');
  assert.match(hb5, /Official bill text .*Text\.aspx\?LegSess=90R&Bill=HB5/);
  assert.equal(JSON.parse(files.get('bills/HB5.json')).links.text, 'https://capitol.texas.gov/BillLookup/Text.aspx?LegSess=90R&Bill=HB5');
  assert.match(sb12, /Pending: review status not available\. 1 of 2 bills have a published review so far/);
  // HB5 lists a coauthor, so SB12's empty coauthors are not a dataset-wide gap; no bill lists cosponsors.
  assert.match(sb12, /### Coauthors\n\n_None listed in the source snapshot\._/);
  // Sponsors and cosponsors are empty snapshot-wide: one shared note, no empty sections.
  assert.match(hb5, /_No sponsors or cosponsors listed: no bill in this snapshot lists any yet/);
  assert.doesNotMatch(hb5, /### (Sponsors|Cosponsors)/);
  assert.match(hb5, /### Coauthors\n\n- Reggie Smith/);
  assert.match(hb5, /Search all bills: https:\/\/agent\.billatlas\.org\/search\?q= followed by your words, e\.g\. https:\/\/agent\.billatlas\.org\/search\?q=Water$/m);
  assert.doesNotMatch(hb5, /<words>/);
  const overview = files.get('index.md');
  assert.match(overview, /Full-text reviewed: 1 of 2 bills/);
  assert.match(overview, /coauthors: 1; sponsors: 0; cosponsors: 0/);
  assert.deepEqual(JSON.parse(files.get('data/bills.json')).coverage.with_coauthors, 1);
  assert.match(files.get('topics/water.md'), /\| Water \| Texas Water Development Board \| full text \|/);
  assert.ok(files.has('authorship/index.md') && files.has('full-text-review/full-text-reviewed.md'));
});

test('pending and missing data are labelled, and review counts agree with published tags', () => {
  // HB5 has published tags but is being reviewed again; SB12 failed; nothing else is known.
  const status = {format: 'texas-bill-luna-status-v1', updated_at: '2026-11-10T19:00:00Z', running: false, current: null,
    upcoming: [], reviewed: ['HB5'], retry: ['HB5'], failed: {SB12: 'download'}};
  const files = buildPages({snapshot: snapshot(BILLS), tags: TAGS, roster: ROSTER, status, minBills: 1});
  const hb5 = files.get('bills/HB5.md'), sb12 = files.get('bills/SB12.md');
  assert.match(hb5, /A newer review is pending \(re-review queued\)/);
  assert.match(sb12, /_Pending: review failed at download; it will be retried\./);
  assert.match(sb12, /_No types of impact tagged yet: the full-text review is pending \(review failed at download; it will be retried\)/);
  assert.doesNotMatch(sb12, /None recorded/);
  const progress = files.get('review-progress.md');
  assert.match(progress, /Reviewed, with published tags: 1 of 2/);
  assert.match(progress, /Queued for a re-review: 1;/);
  assert.match(progress, /failed, will be retried: 1;/);
  const notFound = files.get('404.md');
  assert.match(notFound, /not in the data yet/);
  assert.match(notFound, /- HB: 1 bills between HB5 and HB5/);
  assert.match(files.get('index.md'), /## Quick reference\n\n- Search: https:\/\/agent.billatlas.org\/search\?q=<words>/);
});

test('crawlers can find every page: robots.txt allows OAI-SearchBot and names the sitemap', () => {
  const robots = build().get('robots.txt');
  const groups = robots.split(/\n\n/).filter(g => /User-agent:/.test(g));
  const oai = groups.find(g => /^User-agent: OAI-SearchBot$/m.test(g));
  assert.ok(oai && /^Allow: \/$/m.test(oai), 'OAI-SearchBot has an allow group');
  for (const g of groups) assert.doesNotMatch(g, /^Disallow: \/$/m);
  // Named crawlers skip live, rate-limited queries; any other agent (one fetching for a person) may search.
  for (const bot of ['OAI-SearchBot', 'GPTBot', 'ClaudeBot', 'Googlebot', 'Bingbot'])
    assert.match(groups.find(g => new RegExp(`^User-agent: ${bot}$`, 'm').test(g)), /^Disallow: \/search\?$/m);
  const star = groups.find(g => /^User-agent: \*$/m.test(g));
  assert.ok(star && /^Allow: \/$/m.test(star));
  assert.doesNotMatch(star, /Disallow/);
  assert.match(robots, new RegExp(`^Sitemap: ${AGENT}sitemap\\.xml$`, 'm'));
});

test('the sitemap lists exactly the Markdown pages and the HTML entry point, each once', () => {
  const files = build();
  const locs = [...files.get('sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]);
  const expected = ['index.html', ...[...files.keys()].filter(p => p.endsWith('.md') && p !== '404.md')]
    .map(p => p === 'index.md' ? AGENT : AGENT + p);
  assert.deepEqual([...locs].sort(), [...expected].sort());
  assert.equal(new Set(locs).size, locs.length);
  assert.ok(locs.includes(`${AGENT}bills/HB5.md`) && locs.includes(`${AGENT}index.html`));
  assert.ok(!locs.some(l => l.endsWith('.json') || l.endsWith('404.md')));
  assert.match(files.get('sitemap.xml'), /^<\?xml version="1\.0" encoding="UTF-8"\?>\n<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/);
});

test('the HTML entry point links every bill and the Markdown overview, escaping captions', () => {
  const evil = {...BILLS[0], id: 'HB7', caption: 'Relating to <script>alert(1)</script> & "quotes".'};
  const page = buildPages({snapshot: snapshot([...BILLS, evil]), tags: TAGS, roster: ROSTER, minBills: 1}).get('index.html');
  assert.match(page, /^<!doctype html>/);
  assert.match(page, new RegExp(`<link rel="canonical" href="${AGENT}index\\.html">`));
  for (const id of ['HB5', 'SB12', 'HB7']) assert.ok(page.includes(`<a href="${AGENT}bills/${id}.md">`), id);
  assert.ok(page.includes(`href="${AGENT}index.md"`) && page.includes(`href="${AGENT}llms.txt"`));
  assert.ok(!page.includes('<script>') && page.includes('&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;quotes&quot;'));
  assert.ok(!page.includes('XX1'));
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

test('district pages: member, their bills, bills naming the district\'s counties; none without the tables', async () => {
  const geo = await import('../src/geo.js');
  const districts = JSON.parse(readFileSync(new URL('../data/geo/districts.json', import.meta.url), 'utf8'));
  const roster = {...ROSTER, members: Object.fromEntries(Object.entries(ROSTER.members).map(([k, m]) =>
    [k, {...m, code: k === 'house|Cole' ? 'A1' : 'A2', display_name: k.split('|')[1]}]))};
  const bills = [...BILLS, {id: 'HB7', caption: 'Relating to a hospital district in Travis County.', author: 'Doe',
    authors: ['Doe'], coauthors: [], sponsors: [], cosponsors: [], status: 'Filed', last_action: '11/10/2026 H Filed',
    actions: ['Filed'], filed_at: '2026-11-10'}];
  const files = build({snapshot: snapshot(bills), roster, districts, geo});
  const hd46 = files.get('districts/house-46.md');
  assert.match(hd46, /Counties: Travis \(part\)\./);
  assert.match(hd46, /- Rep\. Sheryl Cole: .*\[their bills\]\(https:\/\/agent.billatlas.org\/authors\/house-cole\.md\)/);
  assert.match(hd46, /## Filed or signed by this district's member \(1\)[\s\S]*\[HB 5\][^\n]*Rep\. Cole: Author/);
  assert.match(hd46, /## Bills that name this district's counties or cities \(1\)[\s\S]*\[HB 7\][^\n]*Names Travis County/);
  assert.match(files.get('districts/house-62.md'), /\[HB 5\][^\n]*Rep\. Smith: Coauthor/);
  assert.doesNotMatch(files.get('districts/house-1.md'), /HB7/);  // Travis bill stays off a district outside Travis
  assert.match(files.get('districts/senate-3.md'), /No member with a known district is listed/);
  const index = files.get('districts/index.md');
  assert.equal(index.split('\n').filter(l => l.startsWith('| [')).length, 181);
  assert.match(index, /\[House District 46 \(Cole\)\]/);
  assert.match(files.get('index.md'), /\[Bills by legislative district\]\(https:\/\/agent.billatlas.org\/districts\/index\.md\) \(181 groups\)/);
  assert.ok(![...build().keys()].some(k => k.startsWith('districts/')));
});

test('a new tags or roster stamp alone leaves district and bill-index pages unchanged', async () => {
  const geo = await import('../src/geo.js');
  const districts = JSON.parse(readFileSync(new URL('../data/geo/districts.json', import.meta.url), 'utf8'));
  const before = build({districts, geo});
  const after = build({districts, geo, tags: {...TAGS, generated_at: '2026-11-10T14:05:00Z'},
    roster: {...ROSTER, generated_at: '2026-11-11T09:00:00Z'}});
  const pages = [...before.keys()].filter(k => k.startsWith('districts/') || k.startsWith('bills/index'));
  assert.ok(pages.length > 180);
  assert.deepEqual(pages.filter(k => before.get(k) !== after.get(k)), []);
  assert.match(before.get('districts/house-46.md'), /How current this is: see the \[overview\]/);
  assert.match(after.get('index.md'), /full-text tags as of 2026-11-10T14:05:00Z/);  // the overview still says
});

test('Luna extras search terms reach the agent record; a bill without extras gets an empty list', () => {
  const extras = {format: 'texas-bill-luna-extras-v1', bills: {HB5: {search_terms: ['roadkill', 'aquifer'], opposing_terms: [], headline: 'x'}}};
  const files = build({extras});
  assert.ok(JSON.parse(files.get('bills/HB5.json')).search_terms.includes('roadkill'));
  assert.deepEqual(JSON.parse(files.get('bills/SB12.json')).search_terms, []);
  assert.deepEqual(JSON.parse(build({extras: {format: 'other', bills: extras.bills}}).get('bills/HB5.json')).search_terms, []);
});

test('bill text: copied text is linked and short texts are inlined; long, missing and unsafe entries are handled', () => {
  const dir = mkdtempSync(join(tmpdir(), 'agent-text-'));
  try {
    const put = (id, versions, files) => {
      mkdirSync(join(dir, id), {recursive: true});
      writeFileSync(join(dir, id, 'index.json'), JSON.stringify({format: 'texas-bill-text-index-v1', bill_id: id, versions}));
      for (const [name, body] of Object.entries(files)) writeFileSync(join(dir, id, name), body);
    };
    put('HB5', [{code: 'I', name: 'Introduced', path: 'I.md', source_url: 'ftp://ftp.legis.state.tx.us/HB00005I.HTM'},
      {code: 'H', name: 'Committee Report', path: 'H.md', source_url: 'ftp://ftp.legis.state.tx.us/HB00005H.HTM'},
      {code: '../x', name: 'Bad', path: '../x.md'}], {'I.md': '# HB 5 - Introduced\n\nOld.', 'H.md': '# HB 5 - Committee Report\n\nSECTION 1. The <ins>new</ins> rule.\n'});
    put('SB12', [{code: 'I', name: 'Introduced', path: 'I.md'}], {'I.md': 'x'.repeat(TEXT_INLINE_MAX + 1)});
    const texts = loadTexts(dir, ['HB5', 'SB12', 'XX1']);
    assert.deepEqual(texts.get('HB5').versions.map(v => v.code), ['I', 'H']);
    assert.equal(texts.has('XX1'), false);
    assert.equal(loadTexts(join(dir, 'absent'), ['HB5']), null);

    const files = build({texts});
    const hb5 = files.get('bills/HB5.md');
    assert.match(hb5, /## Bill text\n\nThe official wording of each version/);
    assert.ok(hb5.includes('- Committee Report: https://billatlas.org/live/text/HB5/H.md (source file: ftp://ftp.legis.state.tx.us/HB00005H.HTM)'));
    assert.ok(hb5.includes('### Text of the latest version (Committee Report)\n\n````markdown\n# HB 5 - Committee Report\n\nSECTION 1. The <ins>new</ins> rule.\n````'));
    assert.ok(hb5.includes('- Full bill text (official wording, Markdown): https://billatlas.org/live/text/HB5/H.md'));
    assert.ok(hb5.indexOf('### Bill text') < hb5.indexOf('## AI analysis (Luna)'));
    const json = JSON.parse(files.get('bills/HB5.json'));
    assert.equal(json.links.full_text, 'https://billatlas.org/live/text/HB5/H.md');
    assert.deepEqual(json.text_versions.map(v => v.name), ['Introduced', 'Committee Report']);

    const sb12 = files.get('bills/SB12.md');
    assert.ok(sb12.includes(`is ${(TEXT_INLINE_MAX + 1).toLocaleString('en-US')} characters, too long to copy into this page; read it at https://billatlas.org/live/text/SB12/I.md`));
    assert.ok(!sb12.includes('````'));

    // A bill with no copied text says so; without a text folder the page has no Bill text section at all.
    const none = build({texts: new Map()}).get('bills/HB5.md');
    assert.match(none, /## Bill text\n\n_No text has been copied here yet/);
    assert.ok(!none.includes('Full bill text (official wording'));
    assert.ok(!build().get('bills/HB5.md').includes('## Bill text'));
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('bill pages separate the official record, computed fields and AI analysis, and say how current the record is', () => {
  const bills = [{...BILLS[0], source_updated: '11/17/2026 11:00:11 AM'}, BILLS[1]];
  const files = buildPages({snapshot: snapshot(bills), tags: TAGS, roster: ROSTER, minBills: 1});
  const hb5 = files.get('bills/HB5.md');
  const at = heading => hb5.indexOf(`\n${heading}\n`);
  const order = ['## Official record', '### Caption', '### Authors and sponsors', '### Recorded actions', '## Computed by this site',
    '## AI analysis (Luna)', '### Summary', '### Topics', '### Potentially affected agencies', '## Links'];
  for (const h of order) assert.ok(at(h) > 0, `missing ${h}`);
  assert.deepEqual([...order].sort((a, b) => at(a) - at(b)), order);
  assert.ok(hb5.includes('Record current as of: the Legislative Council last updated this bill\'s record 11/17/2026 11:00:11 AM; this site copied it 2026-11-10T12:00:00Z.'));
  // Rule outputs leave the official section; the action text stays there.
  const official = hb5.slice(at('## Official record'), at('## Computed by this site'));
  assert.ok(official.includes('- Most recent action: 2026-11-09 · House: Referred to Natural Resources'));
  assert.ok(!official.includes('Hearing status') && !official.includes('Author prominence'));
  assert.match(hb5.slice(at('## Computed by this site'), at('## AI analysis (Luna)')), /- Hearing status: /);
  assert.ok(hb5.includes('Changes groundwater district rules.'));
  assert.ok(hb5.trimEnd().endsWith(BILL_DISCLAIMER) && !hb5.includes(DISCLAIMER));
  assert.equal(JSON.parse(files.get('bills/HB5.json')).record_updated, '11/17/2026 11:00:11 AM');
  // Without a Legislative Council update time the line still gives the copy time.
  assert.ok(files.get('bills/SB12.md').includes('Record current as of: this site copied it 2026-11-10T12:00:00Z.'));
});
