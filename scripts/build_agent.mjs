// Agent pages for agent.bills.ctharvey.me: what the tracker shows, as Markdown and JSON, with no JavaScript.
// Reuses the tracker's own bill pipeline (src/taxonomy.js) and link format (src/prefs.js), so tags, hearing
// status, last-action categories and author party match the human site. Output is deterministic: a file is
// rewritten only when its content changes, and pages for bills or groups that disappear are removed.
import {mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync, chmodSync} from 'node:fs';
import {dirname, join, relative, sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {AGENCY_NAME, LAST_ACTION_TYPES, applyLunaTags, assessHearing, attachMembers, authorInfluence, authorshipParty,
  lastActionInfo, memberSummary, normalizeBill, officialUrl, reviewProgress} from '../src/taxonomy.js';
import {buildHash} from '../src/prefs.js';

export const SITE = 'https://bills.ctharvey.me/';
export const AGENT = 'https://agent.bills.ctharvey.me/';
export const DISCLAIMER = 'Unofficial, independent open-source project; not a state website. Bill data comes from the '
  + 'Texas Legislative Council bulk files and can lag or contain errors. Topic, agency and impact tags are automated '
  + '(caption rules or the Luna model reading the full text) and can be wrong. Not legal advice. Confirm on Texas '
  + 'Legislature Online before relying on anything here.';
const OWNED = /\.(md|json|txt)$/;
const HEARING_ORDER = ['Heard', 'Scheduled', 'Referred', 'Not rated'];

export const slug = text => String(text).toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '').slice(0, 80) || 'unnamed';
const cell = value => String(value ?? '').replace(/\r?\n/g, ' ').replace(/\|/g, '\\|').trim();
const linkText = value => cell(value).replace(/([[\]])/g, '\\$1');
const tracker = (filters = {}, extra = {}) => SITE + buildHash('all', filters, extra);
const byRecent = (a, b) => (b.lastAction.date || '').localeCompare(a.lastAction.date || '') || a.id.localeCompare(b.id, 'en', {numeric: true});

export function loadBills({snapshot, tags = null, roster = null, minBills = 1000}) {
  if (snapshot?.session !== '90R' || snapshot.data_mode !== 'official-ftp' || !Array.isArray(snapshot.bills)
      || snapshot.bills.length < minBills) throw new Error('Refusing an incomplete or unofficial snapshot');
  let bills = snapshot.bills.map(raw => normalizeBill(raw, snapshot.author_profiles)).filter(Boolean);
  const tagged = tags?.format === 'texas-bill-luna-tags-v1' && tags.bills && typeof tags.bills === 'object' && !Array.isArray(tags.bills);
  const lunaNames = tagged && tags.agencies && typeof tags.agencies === 'object' ? tags.agencies : {};
  if (tagged) bills = bills.map(b => Object.hasOwn(tags.bills, b.id) && tags.bills[b.id] && typeof tags.bills[b.id] === 'object'
    ? applyLunaTags(b, tags.bills[b.id], lunaNames) : b);
  if (roster?.format === 'texas-bill-members-v1' && roster.members && typeof roster.members === 'object' && !Array.isArray(roster.members))
    bills = bills.map(b => attachMembers(b, roster));
  const agencyName = a => a.name || AGENCY_NAME[a.id] || lunaNames[a.id] || a.id;
  return bills.map(b => ({...b, agencyNames: Object.fromEntries(b.agencies.map(a => [a.id, agencyName(a)])),
    lastAction: lastActionInfo(b), hearing: assessHearing(b)}));
}

function person({name, member}) {
  if (!member) return {name, matched: false, summary: memberSummary(null)};
  return {name, matched: true, full_name: member.full_name || name, party: member.party || null,
    party_basis: member.party_basis || null, chamber: member.chamber || null, district: member.district || null,
    years_served: member.years_served ?? null, first_year: member.first_year ?? null, summary: memberSummary(member),
    links: Object.fromEntries(Object.entries(member.links || {}).filter(([, v]) => typeof v === 'string' && /^https?:/.test(v)))};
}

export function billRecord(b) {
  const party = authorshipParty(b), influence = authorInfluence(b), last = b.lastAction, h = b.hearing;
  const roles = Object.fromEntries(['authors', 'coauthors', 'sponsors', 'cosponsors'].map(key => [key,
    b[key] == null ? null : b.people?.[key] ? b.people[key].map(person) : b[key].map(name => ({name, matched: false}))]));
  return {
    id: b.id, number: b.number, session: '90R', chamber: b.chamber, title: b.title, caption: b.caption,
    status: b.status, filed_at: b.filed_at || null,
    last_action: {category: last.label, key: last.key, chamber: last.chamber, date: last.date || null, text: last.text},
    actions: Array.isArray(b.actions) ? b.actions.filter(a => typeof a === 'string') : [],
    action_dates: Array.isArray(b.action_dates) ? b.action_dates : null,
    hearing: {status: h.label, detail: h.detail, evidence: h.facts},
    authorship_party: {label: party.label, detail: party.detail},
    author_prominence: {label: influence.label, factors: influence.factors},
    people: roles,
    topics: b.topics,
    agencies: b.agencies.map(a => ({id: a.id, name: b.agencyNames[a.id], relationship: a.relationship,
      source: a.source === 'luna' ? 'luna-full-text' : 'caption-rules', reason: a.reason || ''})),
    impacts: b.impacts,
    affected_groups: b.constituencies || [],
    locations: (b.locations || []).map(l => ({name: l.name, kind: l.kind || null, explanation: l.explanation || null})),
    full_text_review: b.luna ? {reviewed_at: b.luna.reviewed_at || null, text_version: b.luna.text_version || null,
      summary: b.luna.summary || null, fields_from_full_text: b.luna.fields || []} : null,
    links: {tracker: tracker({}, {bill: b.id}), official: officialUrl(b), rss: `${SITE}live/feeds/${b.id}.xml`,
      markdown: `${AGENT}bills/${b.id}.md`, json: `${AGENT}bills/${b.id}.json`},
  };
}

function billMarkdown(b) {
  const r = billRecord(b), last = r.last_action;
  const list = items => items.length ? items.map(t => `- ${cell(t)}`).join('\n') : '- None recorded';
  const people = key => {
    const rows = r.people[key];
    if (rows === null) return '_Not reported in this dataset._';
    if (!rows.length) return '_None listed in the source snapshot._';
    return rows.map(p => `- ${cell(p.full_name || p.name)}${p.matched ? ` (${cell(p.summary)})` : ' (not matched to the 90th Legislature roster)'}`
      + ` · [bills](${AGENT}authors/${authorKey(p, key, b)}.md)`).join('\n');
  };
  const dated = r.action_dates && r.action_dates.length === r.actions.length;
  const actions = r.actions.length ? r.actions.map((a, i) => `${i + 1}. ${dated ? `${r.action_dates[i]}: ` : ''}${cell(a)}`).join('\n') : '_No actions recorded._';
  const agencies = r.agencies.length ? r.agencies.map(a => `- **${cell(a.name)}** (${a.relationship}, ${a.source}): ${cell(a.reason) || 'Relationship not yet annotated'}`).join('\n')
    : '_No agency has been tagged yet. This does not establish that none are affected._';
  const review = r.full_text_review;
  return `# ${r.number}: ${cell(r.title)}

90th Legislature (90R) · ${r.chamber} · Status: ${cell(r.status)}

- Filed: ${r.filed_at || 'unknown'}
- Most recent action: ${cell(last.category)}${last.chamber ? ` · ${last.chamber}` : ''} · ${last.date || 'date unknown'}: ${cell(last.text)}
- Hearing status: ${r.hearing.status}. ${cell(r.hearing.detail)}
- Authorship: ${cell(r.authorship_party.label)}. ${cell(r.authorship_party.detail)}
- Author prominence: ${cell(r.author_prominence.label)}. ${r.author_prominence.factors.map(cell).join('; ')}

## Caption

${cell(r.caption) || '_No caption available._'}

## Full-text review (Luna)

${review ? `Reviewed ${review.reviewed_at || 'date unknown'}${review.text_version ? ` · ${cell(review.text_version)} text` : ''}. Fields from the full text: ${review.fields_from_full_text.join(', ') || 'none'}; other fields use caption inference.

${cell(review.summary) || '_No summary._'}` : '_Not reviewed yet. Tags below come from rules applied to the caption._'}

## Topics

${list(r.topics)}

## Potentially affected agencies

Possible links are rule or model inferences, not confirmed legal obligations.

${agencies}

## Types of impact

${list(r.impacts)}

## People and institutions affected

${list(r.affected_groups)}
${r.locations.length ? `\n## Locations\n\n${r.locations.map(l => `- ${cell(l.name)}${l.kind ? ` (${cell(l.kind)})` : ''}${l.explanation ? `: ${cell(l.explanation)}` : ''}`).join('\n')}\n` : ''}
## Authors and sponsors

Authors and coauthors serve in the originating chamber; sponsors and cosponsors in the other chamber. Authorship does not indicate a vote or caucus position.

### Authors

${people('authors')}

### Coauthors

${people('coauthors')}

### Sponsors

${people('sponsors')}

### Cosponsors

${people('cosponsors')}

## Recorded actions

${actions}

## Links

- Official bill history: ${r.links.official}
- Open in the tracker: ${r.links.tracker}
- RSS feed of actions: ${r.links.rss}
- This page as JSON: ${r.links.json}

---
${DISCLAIMER}
`;
}

function authorKey(p, role, b) {
  const origin = b.chamber.toLowerCase(), other = origin === 'house' ? 'senate' : 'house';
  return `${role === 'authors' || role === 'coauthors' ? origin : other}-${slug(p.name)}`;
}

function table(bills) {
  if (!bills.length) return '_No bills._\n';
  return '| Bill | Title | Last action | Date |\n|---|---|---|---|\n' + [...bills].sort(byRecent).map(b =>
    `| [${b.number}](${AGENT}bills/${b.id}.md) | ${cell(b.title)} | ${cell(b.lastAction.label)} | ${b.lastAction.date || ''} |`).join('\n') + '\n';
}

function groupPage(title, intro, bills, humanLink) {
  return `# ${cell(title)}\n\n${intro}\n\n${bills.length} ${bills.length === 1 ? 'bill' : 'bills'}, most recent action first.`
    + `${humanLink ? ` Same view in the tracker: ${humanLink}` : ''}\n\n${table(bills)}\n---\n${DISCLAIMER}\n`;
}

function indexPage(title, intro, rows) {
  return `# ${cell(title)}\n\n${intro}\n\n| Group | Bills |\n|---|---|\n`
    + rows.map(([label, href, n]) => `| [${linkText(label)}](${AGENT}${href}) | ${n} |`).join('\n') + `\n\n---\n${DISCLAIMER}\n`;
}

function groupBy(bills, keysOf) {
  const groups = new Map();
  for (const b of bills) for (const key of keysOf(b)) {
    if (typeof key !== 'string' || !key) continue;
    if (!groups.has(key)) groups.set(key, []);
    if (!groups.get(key).includes(b)) groups.get(key).push(b);
  }
  return groups;
}

export function buildPages({snapshot, tags = null, roster = null, status = null, minBills = 1000}) {
  const bills = loadBills({snapshot, tags, roster, minBills});
  const files = new Map();
  const put = (path, text) => files.set(path, text);
  const asOf = `Bill data as of ${snapshot.generated_at}${tags?.generated_at ? `; full-text tags as of ${tags.generated_at}` : ''}${roster?.generated_at ? `; member roster as of ${roster.generated_at}` : ''}.`;

  for (const b of bills) {
    put(`bills/${b.id}.md`, billMarkdown(b));
    put(`bills/${b.id}.json`, JSON.stringify(billRecord(b), null, 1) + '\n');
  }
  put('bills/index.md', groupPage('All bills', asOf, bills, SITE + '#all'));

  const indexes = [];
  const addGroups = (dir, title, intro, groups, label, human) => {
    const rows = [...groups].sort((a, b) => b[1].length - a[1].length || String(label(a[0])).localeCompare(String(label(b[0]))))
      .map(([key, list]) => {
        put(`${dir}/${slug(key)}.md`, groupPage(label(key), intro, list, human ? human(key) : null));
        return [label(key), `${dir}/${slug(key)}.md`, list.length];
      });
    put(`${dir}/index.md`, indexPage(title, intro, rows));
    indexes.push([title, `${dir}/index.md`, rows.length]);
  };
  addGroups('topics', 'Bills by topic', 'Policy topics, from the Luna full-text review where available and caption rules otherwise.',
    groupBy(bills, b => b.topics), k => k, k => tracker({topic: k}));
  addGroups('agencies', 'Bills by potentially affected agency', 'Possible links are inferences, not confirmed legal obligations.',
    groupBy(bills, b => b.agencies.map(a => a.id)), k => bills.find(b => b.agencyNames[k])?.agencyNames[k] || k, k => tracker({agency: k}));
  addGroups('last-action', 'Bills by most recent action', 'Categories of the most recent recorded action, along the legislative path.',
    groupBy(bills, b => [b.lastAction.label]), k => k, k => tracker({action: k}));
  addGroups('hearing', 'Bills by hearing status', 'Procedural evidence from recorded actions; not a prediction.',
    new Map([...groupBy(bills, b => [b.hearing.label])].sort((a, b) => HEARING_ORDER.indexOf(a[0]) - HEARING_ORDER.indexOf(b[0]))),
    k => k, k => tracker({outlook: k}));
  addGroups('chamber', 'Bills by chamber', 'The chamber where the bill was filed.', groupBy(bills, b => [b.chamber]), k => k,
    k => tracker({chamber: k}));

  // Authors: every named member and the bills they author, coauthor or sponsor.
  const people = new Map();
  for (const b of bills) for (const role of ['authors', 'coauthors', 'sponsors', 'cosponsors']) for (const p of billRecord(b).people[role] || []) {
    const key = authorKey(p, role, b);
    if (!people.has(key)) people.set(key, {name: p.full_name || p.name, summary: p.matched ? p.summary : 'Not matched to the 90th Legislature roster', roles: new Map()});
    people.get(key).roles.set(b, [...(people.get(key).roles.get(b) || []), role.replace(/s$/, '')]);
  }
  const personRows = [...people].sort((a, b) => a[1].name.localeCompare(b[1].name)).map(([key, p]) => {
    const rows = [...p.roles].sort((x, y) => byRecent(x[0], y[0]));
    put(`authors/${key}.md`, `# ${cell(p.name)}\n\n${cell(p.summary)}\n\n${rows.length} ${rows.length === 1 ? 'bill' : 'bills'}.\n\n| Bill | Role | Title | Last action | Date |\n|---|---|---|---|---|\n`
      + rows.map(([b, roles]) => `| [${b.number}](${AGENT}bills/${b.id}.md) | ${roles.join(', ')} | ${cell(b.title)} | ${cell(b.lastAction.label)} | ${b.lastAction.date || ''} |`).join('\n')
      + `\n\n---\n${DISCLAIMER}\n`);
    return [`${p.name} (${key.split('-')[0]})`, `authors/${key}.md`, rows.length];
  });
  put('authors/index.md', indexPage('Bills by member', 'Authors and coauthors serve in the originating chamber; sponsors and cosponsors in the other.', personRows));
  indexes.push(['Bills by member', 'authors/index.md', personRows.length]);

  put('recent.md', groupPage('Most recent actions', `The 100 bills with the most recent recorded actions. ${asOf}`,
    [...bills].sort(byRecent).slice(0, 100), tracker({sort: 'latest'})));

  const progress = reviewProgress(bills.map(b => b.id), status, Object.keys(tags?.bills || {}));
  const ids = list => list.length ? list.map(id => `[${id}](${AGENT}bills/${id}.md)`).join(', ') : '_None._';
  put('review-progress.md', `# Full-text review progress\n\nLuna reads each bill's full text and publishes citation-verified tags. ${status?.updated_at ? `Status as of ${status.updated_at}.` : ''}\n\n`
    + `- Reviewed: ${progress.reviewed.length}\n- In progress or retrying: ${progress.inProgress.length + (progress.current ? 1 : 0)}\n- Failed: ${progress.failed.length}\n- Not started: ${progress.notStarted.length}\n\n`
    + `## Under review now\n\n${progress.current ? ids([progress.current]) : '_Nothing right now._'}\n\n## Up next\n\n${ids(progress.upcoming)}\n\n## Reviewed\n\n${ids(progress.reviewed)}\n\n## Failed\n\n${ids(progress.failed.map(f => f.id))}\n\n---\n${DISCLAIMER}\n`);

  put('saving.md', SAVING);
  put('data/bills.json', JSON.stringify({format: 'texas-bill-atlas-agent-v1', session: '90R', disclaimer: DISCLAIMER,
    bill_data_as_of: snapshot.generated_at, tags_as_of: tags?.generated_at || null, roster_as_of: roster?.generated_at || null,
    coverage_note: snapshot.coverage_note || null, sources: snapshot.sources || null, count: bills.length,
    bills: [...bills].sort((a, b) => a.id.localeCompare(b.id, 'en', {numeric: true})).map(billRecord)}) + '\n');

  const overview = overviewPage(bills.length, asOf, indexes);
  put('index.md', overview);
  put('llms.txt', overview);
  return files;
}

function overviewPage(count, asOf, indexes) {
  return `# Texas Bill Atlas (agent edition)

> Plain-text and JSON access to everything the Texas Bill Atlas tracker (${SITE}) shows for the 90th Texas Legislature: ${count} bills with captions, authors and sponsors (party, district, tenure), recorded actions, hearing status, most recent action, topics, potentially affected agencies, impacts, affected groups and Luna full-text reviews. No JavaScript, login or API key needed.

${asOf} Pages regenerate hourly; files change only when their data does.

${DISCLAIMER}

## Start here

- [All bills](${AGENT}bills/index.md): one row per bill, most recent action first
- [Most recent actions](${AGENT}recent.md)
- One bill: \`${AGENT}bills/<ID>.md\` or \`.json\`, for example [HB 1](${AGENT}bills/HB1.md). IDs have no spaces: HB1, SB12, HJR5, SCR3.
- [Everything as one JSON file](${AGENT}data/bills.json): the same records as the per-bill JSON, for your own filtering or search

## Browse like the tracker's filters

${indexes.map(([title, href, n]) => `- [${title}](${AGENT}${href}) (${n} groups)`).join('\n')}
- [Full-text review progress](${AGENT}review-progress.md)

## Mapping tracker links

The tracker keeps its state after \`#\` in the address. Equivalents here:

- \`${SITE}#all?bill=HB1\` -> \`${AGENT}bills/HB1.md\`
- \`#all?topic=<topic>\` -> \`${AGENT}topics/index.md\`; \`#all?agency=<id>\` -> \`${AGENT}agencies/index.md\`; \`#all?action=<category>\` -> \`${AGENT}last-action/index.md\`; \`#all?outlook=<status>\` -> \`${AGENT}hearing/index.md\`; \`#all?chamber=<chamber>\` -> \`${AGENT}chamber/index.md\`
- Text search (\`query=\`): filter \`data/bills.json\` on id, number, title, caption, member names, last action, topics, impacts and agency names.
- A shared list (\`#all?list=HB1,SB2\`): fetch each \`bills/<ID>.md\`.

## Feeds and saved lists

- Each bill has an RSS feed of its actions: \`${SITE}live/feeds/<ID>.xml\`
- [How saving, sharing and private sync links work](${AGENT}saving.md), including the read-only API for a shared watchlist

## About the data

- Bill histories: Texas Legislative Council bulk FTP, refreshed hourly.
- Members: Texas Legislature Online roster and the Legislative Reference Library; members-elect from the Secretary of State's unofficial 2026 general election results.
- Full-text tags: the Luna model reviewing each bill's text, with quotes verified against the text; unreviewed bills use caption rules.
- Source code: https://github.com/ctharvey/texas_bill_tracker
`;
}

const SAVING = `# Saving and sharing (Texas Bill Atlas)

There are no accounts. A person's watchlist and filters live in their browser; they can carry them in a link or file, or sync them with a private link.

- **Links to a view**: the tracker's address describes the view, e.g. \`${SITE}#all?topic=Water&bill=HB1\`.
- **Share links**: \`${SITE}#all?list=HB1,SB2\` opens a read-only list. For agents: fetch \`${AGENT}bills/<ID>.md\` for each id.
- **Export/import**: the watchlist file is JSON: \`{"format": "texas-bill-atlas-watchlist-v1", "session": "90R", "bills": ["HB1", "SB2"]}\`. Import also accepts any text listing bill numbers.
- **RSS**: \`${SITE}live/feeds/<ID>.xml\` per bill.

## Private sync links (read-only access for agents)

A sync list has an edit key and a view key (22 characters each). Never ask a person for their edit key; it lets anyone change the list. A view-only link looks like \`${SITE}#watchlist?sync=<view key>\`. With a view key:

- \`GET ${SITE}api/sync\` with header \`X-Sync-Key: <view key>\` returns \`{"mode": "view", "version": n, "data": {"watch": ["HB1", ...], "filters": {}}}\`
- \`GET ${SITE}api/sync/feed/<view key>.xml\` is an RSS feed of the latest actions on every bill in the list

Requests are rate limited per client address. The service stores only the bill numbers, a version and dates; keys are stored as one-way hashes. No names, emails or accounts.

---
${DISCLAIMER}
`;

export function writePages(outDir, files) {
  let written = 0, unchanged = 0, removed = 0;
  for (const [path, text] of files) {
    const target = join(outDir, ...path.split('/'));
    let current = null;
    try { current = readFileSync(target, 'utf8'); } catch { /* new file */ }
    if (current === text) { unchanged++; continue; }
    mkdirSync(dirname(target), {recursive: true, mode: 0o755});
    const temp = `${target}.tmp-${process.pid}`;
    writeFileSync(temp, text, {mode: 0o644});
    chmodSync(temp, 0o644);
    renameSync(temp, target);
    written++;
  }
  const keep = new Set([...files.keys()]);
  const walk = dir => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) { walk(full); continue; }
      const rel = relative(outDir, full).split(sep).join('/');
      if ((OWNED.test(rel) || /\.tmp-\d+$/.test(rel)) && !keep.has(rel)) { rmSync(full); removed++; }
    }
  };
  walk(outDir);
  return {written, unchanged, removed};
}

function readJson(path, optional = false) {
  try { return JSON.parse(readFileSync(path, 'utf8')); }
  catch (error) { if (optional) return null; throw error; }
}

function main(argv) {
  const args = Object.fromEntries(argv.reduce((acc, value, i, all) => value.startsWith('--') ? [...acc, [value.slice(2), all[i + 1]]] : acc, []));
  if (!args.snapshot || !args.out) throw new Error('Usage: build_agent.mjs --snapshot bills.json --out dir [--tags t.json] [--members m.json] [--status s.json]');
  const files = buildPages({snapshot: readJson(args.snapshot), tags: args.tags ? readJson(args.tags, true) : null,
    roster: args.members ? readJson(args.members, true) : null, status: args.status ? readJson(args.status, true) : null});
  mkdirSync(args.out, {recursive: true, mode: 0o755});
  const result = writePages(args.out, files);
  console.log(`Agent pages: ${files.size} total, ${result.written} written, ${result.unchanged} unchanged, ${result.removed} removed`);
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) main(process.argv.slice(2));
