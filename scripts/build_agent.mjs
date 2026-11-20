// Agent pages for agent.billatlas.org: what the tracker shows, as Markdown and JSON, with no JavaScript.
// Reuses the tracker's own bill pipeline (src/taxonomy.js) and link format (src/prefs.js), so tags, hearing
// status, last-action categories and author party match the human site. Output is deterministic: a file is
// rewritten only when its content changes, and pages for bills or groups that disappear are removed.
import {mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync, chmodSync} from 'node:fs';
import {dirname, join, relative, sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {AGENCY_NAME, NO_HEARING, applyLunaExtras, applyLunaTags, assessHearing, attachMembers, authorInfluence, authorshipParty,
  companionIndex, lastActionInfo, memberSummary, newestFirst, normalizeBill, officialUrl, POLICY_AREAS, reviewProgress,
  SCOPE_AGENCY_ID} from '../src/taxonomy.js';
import {buildHash} from '../src/prefs.js';
import {routeForView, topicSlug} from '../src/core/routes.js';
import {state} from '../src/core/state.js';
import {stampText} from '../src/core/format.js';
import {methodMarkup} from '../src/features/pages/method.js';
import {savingMarkup} from '../src/features/pages/saving.js';
import {dataMarkup} from '../src/features/pages/data.js';
import {ABOUT_HEADINGS, PAGE_HEADINGS} from '../src/features/pages/headings.js';
import {homeMarkup, todayRow} from '../src/features/home/view.js';
import {todayMarkup} from '../src/features/today/view.js';
import {reviewParts} from '../src/features/review/view.js';

export const SITE = 'https://billatlas.org/';
export const AGENT = 'https://agent.billatlas.org/';
export const DISCLAIMER = 'Unofficial, independent open-source project; not a state website. Bill data comes from the '
  + 'Texas Legislative Council bulk files and can lag or contain errors. Topic, agency and impact tags are automated '
  + '(caption rules or the Luna model reading the full text) and can be wrong. Not legal advice. Confirm on Texas '
  + 'Legislature Online before relying on anything here.';
// Bill pages separate the copied record from what this site computes and what the AI writes, so the footer says so.
export const BILL_DISCLAIMER = 'Unofficial, independent open-source project; not a state website. The official record '
  + 'and bill text on this page are copied unchanged from the Texas Legislative Council bill files, refreshed hourly, so '
  + 'they can trail the Legislature by up to an hour or two. Computed fields and the AI analysis can be wrong. Not legal '
  + 'advice. For anything that matters, confirm on Texas Legislature Online.';
const OWNED = /\.(md|json|txt)$/;
const HEARING_ORDER = ['Heard', 'Scheduled', 'Referred', NO_HEARING];
const HEARD = new Set(['Heard', 'Scheduled']);
const PAGE = 150;
const FILED_NOTE = '"Filed" is the filing date in the Legislative Council data. Bills filed before the session opens in '
  + 'January 2027 are prefiled; prefiling opened on 2026-11-09, so early dates cluster there.';
const textUrl = id => `https://capitol.texas.gov/BillLookup/Text.aspx?LegSess=90R&Bill=${id}`;
// Our copy of each text version (sync_ftp.py writes live/text/<ID>/<code>.md from the Legislative Council's files).
export const TEXT_INLINE_MAX = 12000; // characters; longer bills are linked, not copied into the page
const VERSION_CODE = /^[A-Za-z0-9]{1,8}$/;
const SHA256 = /^[0-9a-f]{64}$/;
// FTP MDTM stamps (RFC 3659) are UTC: 20261109160644 -> 2026-11-09 16:06:44 UTC.
const mdtmText = stamp => /^\d{14}/.test(stamp || '') ? `${stamp.slice(0, 4)}-${stamp.slice(4, 6)}-${stamp.slice(6, 8)} ${stamp.slice(8, 10)}:${stamp.slice(10, 12)}:${stamp.slice(12, 14)} UTC` : null;

// id -> {versions: [{code, name, url, source_url}], body, chars} from live/text, or null when the folder is absent.
export function loadTexts(textDir, ids) {
  try { if (!statSync(textDir).isDirectory()) return null; } catch { return null; }
  const texts = new Map();
  for (const id of ids) {
    let index;
    try { index = JSON.parse(readFileSync(join(textDir, id, 'index.json'), 'utf8')); } catch { continue; }
    if (index?.format !== 'texas-bill-text-index-v1' || !Array.isArray(index.versions)) continue;
    const versions = index.versions.filter(v => v && VERSION_CODE.test(String(v.code)) && v.path === `${v.code}.md`)
      .map(v => ({code: v.code, name: String(v.name || v.code), url: `${SITE}live/text/${id}/${v.code}.md`,
        source_url: typeof v.source_url === 'string' ? v.source_url : null,
        source_modified: mdtmText(v.source_modified), source_sha256: SHA256.test(v.source_sha256 || '') ? v.source_sha256 : null,
        copied_at: typeof v.generated_at === 'string' ? v.generated_at : null, copy_sha256: SHA256.test(v.sha256 || '') ? v.sha256 : null}));
    if (!versions.length) continue;
    let body = null, chars = 0;
    try {
      body = readFileSync(join(textDir, id, `${versions.at(-1).code}.md`), 'utf8').trim();
      chars = body.length;
      if (chars > TEXT_INLINE_MAX) body = null;
    } catch { body = null; }
    texts.set(id, {versions, body, chars});
  }
  return texts;
}

// Current law (sync_law.py writes live/law/<CODE>/<chapter>.md and indexes) for each section a bill changes (the
// statute index build_feeds.py writes). id -> [{code, code_name, section, action, heading, url, official, text}], or
// null when either folder is absent, so the page then leaves the section out.
export const LAW_INLINE_MAX = 4000;      // characters per section copied into the page
export const LAW_PAGE_MAX = 20000;       // characters of current law per bill page; the rest are links
const LAW_CODE = /^[A-Z][A-Z0-9]$/;
const LAW_SECTION = /^[0-9A-Za-z][0-9A-Za-z.()\-]{0,40}$/;
const LAW_CHAPTER = /^[0-9a-z]+(?:\.[0-9a-z]+)*$/;
const LAW_ACTION = {m: 'amended', n: 'added (new section)', a: 'added (new section)', r: 'repealed'};

export function loadLaw(liveDir, ids) {
  let statutes, law;
  try {
    statutes = JSON.parse(readFileSync(join(liveDir, 'statutes', 'index.json'), 'utf8'));
    law = JSON.parse(readFileSync(join(liveDir, 'law', 'index.json'), 'utf8'));
  } catch { return null; }
  if (statutes?.format !== 'texas-bill-statutes-v1' || law?.format !== 'texas-bill-law-v1' || !law.codes) return null;
  const wanted = new Set(ids), perBill = new Map(), needed = new Map(); // chapter file -> Set(section)
  const chapterOf = new Map(); // code -> Map(section -> {chapter, file, sha256})
  const codeIndex = code => {
    if (chapterOf.has(code)) return chapterOf.get(code);
    let index = null;
    try { index = JSON.parse(readFileSync(join(liveDir, 'law', code, 'index.json'), 'utf8')); } catch { /* no copy */ }
    const sections = new Map();
    for (const [chapter, entry] of Object.entries(index?.format === 'texas-bill-law-v1' ? index.chapters || {} : {})) {
      if (!LAW_CHAPTER.test(chapter) || entry?.file !== `${code}/${chapter}.md`) continue;
      for (const [section, heading] of entry.sections || []) {
        if (!sections.has(section)) sections.set(section, {chapter, file: entry.file, sha256: entry.sha256, heading});
      }
    }
    chapterOf.set(code, sections);
    return sections;
  };
  for (const [key, entry] of Object.entries(statutes.sections || {})) {
    const [code, section] = key.split(' ');
    if (!LAW_CODE.test(code || '') || !LAW_SECTION.test(section || '')) continue;
    for (const [id, action] of entry?.b || []) {
      if (!wanted.has(id)) continue;
      const found = action === 'n' || action === 'a' ? null : codeIndex(code).get(section);
      const item = {code, code_name: law.codes[code]?.name || code, section, action: LAW_ACTION[action] || String(action),
        heading: found?.heading || null, url: found ? `${SITE}live/law/${found.file}` : null,
        official: found ? `https://statutes.capitol.texas.gov/Docs/${code}/htm/${code}.${found.chapter}.htm` : null,
        copy_sha256: SHA256.test(found?.sha256 || '') ? found.sha256 : null,
        copied_at: law.codes[code]?.copied_at || null, text: null, file: found?.file || null};
      if (!perBill.has(id)) perBill.set(id, []);
      perBill.get(id).push(item);
      if (found) {
        if (!needed.has(found.file)) needed.set(found.file, new Set());
        needed.get(found.file).add(section);
      }
    }
  }
  // Each needed chapter file is read once; only the cited sections' text is kept.
  const texts = new Map();
  for (const [file, sections] of needed) {
    let body;
    try { body = readFileSync(join(liveDir, 'law', ...file.split('/')), 'utf8'); } catch { continue; }
    for (const part of body.split('\n## ').slice(1)) {
      const match = /^(?:Sec|Art)\.\s+([0-9A-Za-z][0-9A-Za-z.()\-]*?)\.(?:\s|$)/.exec(part);
      if (match && sections.has(match[1]) && !texts.has(`${file} ${match[1]}`)) texts.set(`${file} ${match[1]}`, part.trim());
    }
  }
  for (const items of perBill.values()) {
    let budget = LAW_PAGE_MAX;
    items.sort((a, b) => `${a.code} ${a.section}`.localeCompare(`${b.code} ${b.section}`, 'en', {numeric: true}));
    for (const item of items) {
      const text = item.file ? texts.get(`${item.file} ${item.section}`) : null;
      if (text && text.length <= LAW_INLINE_MAX && text.length <= budget) { item.text = text; budget -= text.length; }
      delete item.file;
    }
  }
  return perBill;
}

function lawSection(items) {
  if (items === undefined) return '';
  if (!items?.length) return '';
  const fence = '````';
  return `\n### Current law this bill changes

Each section as it stands now, from this site's copy of the Texas Legislative Council's statute files (wording unchanged); the official page is the authority. Sections are matched automatically from the bill text and can be missed, for example when a bill changes a whole chapter at once.

${items.map(i => [`- ${cell(i.code_name)} §${cell(i.section)} (${i.action})${i.heading ? `: ${cell(i.heading)}` : ''}`,
  i.url ? `  - This copy (whole chapter): ${i.url}${i.copied_at ? `, copied ${i.copied_at}` : ''}${i.copy_sha256 ? `, SHA-256 of the Markdown ${i.copy_sha256}` : ''}` : '',
  i.official ? `  - Official: ${i.official}` : '',
  !i.url && i.action.startsWith('added') ? '  - New section: no current text.' : '',
  !i.url && !i.action.startsWith('added') ? '  - Not found in this site\'s copy of current law.' : '',
  i.text ? `\n${fence}markdown\n${i.text}\n${fence}\n` : '',
].filter(Boolean).join('\n')).join('\n')}
`;
}

export const slug = text => String(text).toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '').slice(0, 80) || 'unnamed';
const cell = value => String(value ?? '').replace(/\r?\n/g, ' ').replace(/\|/g, '\\|').trim();
const linkText = value => cell(value).replace(/([[\]])/g, '\\$1');
const tracker = (filters = {}, extra = {}) => SITE + buildHash('all', filters, extra);
// Newest last action first; on the same day the newer bill (higher number) first, as the app orders lists.
const byRecent = (a, b) => (b.lastAction.date || '').localeCompare(a.lastAction.date || '') || newestFirst(a.id, b.id);

export function loadBills({snapshot, tags = null, extras = null, roster = null, minBills = 1000}) {
  if (snapshot?.session !== '90R' || snapshot.data_mode !== 'official-ftp' || !Array.isArray(snapshot.bills)
      || snapshot.bills.length < minBills) throw new Error('Refusing an incomplete or unofficial snapshot');
  let bills = snapshot.bills.map(raw => normalizeBill(raw, snapshot.author_profiles)).filter(Boolean);
  const tagged = tags?.format === 'texas-bill-luna-tags-v1' && tags.bills && typeof tags.bills === 'object' && !Array.isArray(tags.bills);
  const lunaNames = tagged && tags.agencies && typeof tags.agencies === 'object' ? tags.agencies : {};
  if (tagged) bills = bills.map(b => Object.hasOwn(tags.bills, b.id) && tags.bills[b.id] && typeof tags.bills[b.id] === 'object'
    ? applyLunaTags(b, tags.bills[b.id], lunaNames) : b);
  // Luna's extra search terms, as the site applies them, so agent search finds "roadkill" for a bill whose text says
  // "wildlife killed in an unintentional motor vehicle collision".
  if (extras?.format === 'texas-bill-luna-extras-v1' && extras.bills && typeof extras.bills === 'object' && !Array.isArray(extras.bills))
    bills = bills.map(b => Object.hasOwn(extras.bills, b.id) ? applyLunaExtras(b, extras.bills[b.id]) : b);
  if (roster?.format === 'texas-bill-members-v1' && roster.members && typeof roster.members === 'object' && !Array.isArray(roster.members))
    bills = bills.map(b => attachMembers(b, roster));
  const agencyName = a => a.name || AGENCY_NAME[a.id] || lunaNames[a.id] || a.id;
  const companions = companionIndex(bills), byId = new Map(bills.map(b => [b.id, b]));
  return bills.map(b => ({...b, companionLinks: (companions.get(b.id) || []).map(c => ({...c, title: byId.get(c.id)?.title || null})),
    agencyNames: Object.fromEntries(b.agencies.map(a => [a.id, agencyName(a)])),
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
    companions: (b.companionLinks || []).map(c => ({id: c.id, number: c.number, author: c.author || null,
      relation: c.relation || null, in_snapshot: Boolean(c.title), title: c.title,
      markdown: c.title ? `${AGENT}bills/${c.id}.md` : null})),
    subjects: b.subjects,
    record_updated: typeof b.source_updated === 'string' ? b.source_updated : null,
    topics: b.topics,
    agencies: b.agencies.map(a => ({id: a.id, name: b.agencyNames[a.id], relationship: a.relationship,
      source: a.source === 'luna' ? 'luna-full-text' : 'caption-rules', reason: a.reason || ''})),
    impacts: b.impacts,
    search_terms: b.search_terms || [],
    affected_groups: b.constituencies || [],
    locations: (b.locations || []).map(l => ({name: l.name, kind: l.kind || null, explanation: l.explanation || null})),
    full_text_review: b.luna ? {reviewed_at: b.luna.reviewed_at || null, text_version: b.luna.text_version || null,
      summary: b.luna.summary || null, fields_from_full_text: b.luna.fields || []} : null,
    links: {tracker: `${SITE}bill/${b.id}`, official: officialUrl(b), text: textUrl(b.id), rss: `${SITE}live/feeds/${b.id}.xml`,
      markdown: `${AGENT}bills/${b.id}.md`, json: `${AGENT}bills/${b.id}.json`},
  };
}

// text: undefined when no text folder was given (no section), null when this bill has no text copied yet.
function textSection(r, text) {
  if (text === undefined) return '';
  if (!text) return `\n### Bill text\n\n_No text has been copied here yet: the Legislature may not have published it. Official text: ${r.links.text}_\n`;
  const latest = text.versions.at(-1), fence = '````';
  return `\n### Bill text

The official wording of each version, copied from the Texas Legislative Council's bill text files and converted to Markdown with the wording unchanged. Language the bill adds is marked <ins>like this</ins>; language it removes is in [<del>brackets</del>]. To check a copy, fetch the official file and compare its SHA-256 with the one listed; the copy's own SHA-256 confirms you received it unaltered.

${text.versions.map(v => [`- ${cell(v.name)}: ${v.url}`,
  v.source_url ? `  - Official file: ${v.source_url}${[v.source_modified && `last modified ${v.source_modified}`, v.source_sha256 && `SHA-256 ${v.source_sha256}`].filter(Boolean).map(x => `, ${x}`).join('')}` : '',
  v.copied_at || v.copy_sha256 ? `  - This copy:${[v.copied_at && ` made ${v.copied_at}`, v.copy_sha256 && ` SHA-256 of the Markdown ${v.copy_sha256}`].filter(Boolean).join(',')}` : '',
].filter(Boolean).join('\n')).join('\n')}

${text.body ? `#### Text of the latest version (${cell(latest.name)})

${fence}markdown
${text.body}
${fence}` : `The latest version (${cell(latest.name)}) is ${text.chars.toLocaleString('en-US')} characters, too long to copy into this page; read it at ${latest.url}`}
`;
}

function billMarkdown(b, coverage, reviewState = '', queueNote = '', text = undefined, copiedAt = '', law = undefined) {
  const r = billRecord(b), last = r.last_action, pending = !r.full_text_review;
  if (text) r.links.full_text = text.versions.at(-1).url;
  // Say whether an empty field is a finding or data we do not have yet.
  const empty = noun => pending ? `_No ${noun} tagged yet: the full-text review is pending (${reviewState || 'not started'}), and caption rules found none._`
    : `_The full-text review identified no ${noun}._`;
  const list = (items, noun) => items.length ? items.map(t => `- ${cell(t)}`).join('\n') : empty(noun);
  const people = key => {
    const rows = r.people[key];
    if (rows === null) return '_Not reported in this dataset._';
    if (!rows.length) return coverage?.[`with_${key}`] === 0
      ? `_None listed. No bill in this snapshot lists any ${key} yet, so this reflects the stage of the source data, not this bill._`
      : '_None listed in the source snapshot._';
    return rows.map(p => `- ${cell(p.full_name || p.name)}${p.matched ? ` (${cell(p.summary)})` : ' (not matched to the 90th Legislature roster)'}`
      + ` · [bills](${AGENT}authors/${authorKey(p, key, b)}.md)`).join('\n');
  };
  // Roles no bill in the snapshot lists yet share one note instead of an empty section each.
  const roles = keys => {
    const absent = keys.filter(k => Array.isArray(r.people[k]) && !r.people[k].length && coverage?.[`with_${k}`] === 0);
    const shown = keys.filter(k => !absent.includes(k)).map(k => `\n#### ${k[0].toUpperCase()}${k.slice(1)}\n\n${people(k)}\n`).join('');
    const names = absent.length > 1 ? `${absent.slice(0, -1).join(', ')} or ${absent.at(-1)}` : absent[0];
    return shown + (absent.length ? `\n_No ${names} listed: no bill in this snapshot lists any yet, so this reflects the stage of the source data, not this bill._\n` : '');
  };
  const dated = r.action_dates && r.action_dates.length === r.actions.length;
  const actions = r.actions.length ? r.actions.map((a, i) => `${i + 1}. ${dated ? `${r.action_dates[i]}: ` : ''}${cell(a)}`).join('\n') : '_No actions recorded._';
  const agencies = r.agencies.length ? r.agencies.map(a => `- **${cell(a.name)}** (${a.relationship}, ${a.source}): ${cell(a.reason) || (a.source === 'caption-rules' ? 'Inferred from the caption; no explanation until the full-text review' : 'No explanation recorded')}`).join('\n')
    : pending ? `_No agency tagged yet: the full-text review is pending (${reviewState || 'not started'}). This does not establish that none are affected._`
      : '_The full-text review tagged no state agency. This does not establish that none are affected._';
  const review = r.full_text_review;
  const fresh = [r.record_updated ? `the Legislative Council last updated this bill's record ${cell(r.record_updated)}` : '',
    copiedAt ? `this site copied it ${copiedAt}` : ''].filter(Boolean).join('; ');
  return `# ${r.number}: ${cell(r.title)}

90th Legislature (90R) · ${r.chamber} · Status: ${cell(r.status)}
${fresh ? `\nRecord current as of: ${fresh}.\n` : ''}
How to read this page: **Official record** is copied unchanged from the Texas Legislative Council's bill files, the data behind Texas Legislature Online. **Computed by this site** is worked out by fixed rules from that record. **AI analysis (Luna)** is written by an AI model that read the bill text; it can be wrong, so check it against the bill text.

## Official record

Source: Texas Legislative Council bill files (ftp.legis.state.tx.us), copied unchanged.

- Filed: ${r.filed_at || 'not in the source data'}
- Most recent action: ${last.date || 'date unknown'}${last.chamber ? ` · ${last.chamber}` : ''}: ${cell(last.text)}
- Official subjects (Legislative Council index): ${r.subjects === null ? 'not in this snapshot yet' : r.subjects.length ? r.subjects.map(cell).join('; ') : 'none listed'}
- Companion bills: ${r.companions.length ? r.companions.map(c => `${c.in_snapshot ? `[${c.number}](${c.markdown})` : `${c.number} (not in this snapshot yet)`}${c.relation ? `, ${cell(c.relation).toLowerCase()}` : ''}${c.author ? `, by ${cell(c.author)}` : ''}`).join('; ') : 'none listed in the source data'}

### Caption

${cell(r.caption) || '_No caption available._'}
${textSection(r, text)}${lawSection(law)}
### Authors and sponsors

Authors and coauthors serve in the originating chamber; sponsors and cosponsors in the other chamber. Authorship does not indicate a vote or caucus position.

#### Authors

${people('authors')}
${roles(['coauthors', 'sponsors', 'cosponsors'])}
### Recorded actions

${actions}

## Computed by this site

Worked out by fixed rules from the official record above; not a statement by the Legislature.

- Status: ${cell(r.status)}
- Most recent action type: ${cell(last.category)}
- Hearing status: ${r.hearing.status}. ${cell(r.hearing.detail)}
- Authorship: ${cell(r.authorship_party.label)}. ${cell(r.authorship_party.detail)}
- Author prominence: ${cell(r.author_prominence.label)}. ${r.author_prominence.factors.map(cell).join('; ')}

## AI analysis (Luna)

Written by Luna, an AI model that reads the full bill text. It can be wrong; the bill text above is the authority. Tags marked caption-rules come from keyword rules applied to the caption, not from the AI.

### Summary

${review ? `Reviewed ${review.reviewed_at || 'date unknown'}${review.text_version ? ` · ${cell(review.text_version)} text` : ''}. Fields from the full text: ${review.fields_from_full_text.join(', ') || 'none'}; other fields use caption inference.

${cell(review.summary) || '_The review published no summary._'}${reviewState && reviewState !== 'reviewed' ? `\n\nA newer review is pending (${reviewState}); this one stays until it publishes.` : ''}` : `_Pending: ${reviewState || 'not started'}${queueNote ? `; ${queueNote}` : ''}${coverage ? `. ${coverage.full_text_reviewed} of ${coverage.bills} bills have a published review so far; see ${AGENT}review-progress.md` : ''}. Until then, tags below come from rules applied to the caption._`}

### Topics

${list(r.topics, 'topics')}

### Potentially affected agencies

Possible links are rule or model inferences, not confirmed legal obligations.

${agencies}

### Types of impact

${list(r.impacts, 'types of impact')}

### People and institutions affected

${list(r.affected_groups, 'affected people or institutions')}
${r.locations.length ? `\n### Locations\n\n${r.locations.map(l => `- ${cell(l.name)}${l.kind ? ` (${cell(l.kind)})` : ''}${l.explanation ? `: ${cell(l.explanation)}` : ''}`).join('\n')}\n` : ''}
## Links
${r.links.full_text ? `\n- Full bill text (official wording, Markdown): ${r.links.full_text}` : ''}
- Official bill history: ${r.links.official}
- Official bill text (every version, HTML/PDF/Word): ${r.links.text}
- Open in the tracker: ${r.links.tracker}
- RSS feed of actions: ${r.links.rss}
- This page as JSON: ${r.links.json}
- Search all bills: ${AGENT}search?q= followed by your words${r.topics.length ? `, e.g. ${AGENT}search?q=${encodeURIComponent(r.topics[0])}` : ''}

---
${BILL_DISCLAIMER}
`;
}

function authorKey(p, role, b) {
  const origin = b.chamber.toLowerCase(), other = origin === 'house' ? 'senate' : 'house';
  return `${role === 'authors' || role === 'coauthors' ? origin : other}-${slug(p.name)}`;
}

function table(bills) {
  if (!bills.length) return '_No bills._\n';
  return '| Bill | Title | Topics | Agencies | Review | Last action | Date |\n|---|---|---|---|---|---|---|\n' + [...bills].sort(byRecent).map(b =>
    `| [${b.number}](${AGENT}bills/${b.id}.md) | ${cell(b.title)} | ${cell(b.topics.join('; ')) || (b.luna ? 'none found' : 'none yet')} | ${cell(b.agencies.map(a => b.agencyNames[a.id]).join('; ')) || (b.luna ? 'none found' : 'none yet')} | ${b.luna ? 'full text' : 'caption'} | ${cell(b.lastAction.label)} | ${b.lastAction.date || ''} |`).join('\n') + '\n';
}

function groupPage(title, intro, bills, humanLink, total = bills.length) {
  return `# ${cell(title)}\n\n${intro}\n\n${total} ${total === 1 ? 'bill' : 'bills'}, most recent action first. Review: "full text" means Luna read the bill; "caption" means tags come from caption rules.`
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

// The lists behind the data run's static topic and agency pages (scripts/build_feeds.py, SEO chunk 5). Topics and
// agencies come from the app's own taxonomy and Luna tags, which only Node applies, so the data run reads this file
// (live/agent/data/pages.json) instead of recomputing them. Every topic is listed, bills or not; agencies only with bills.
const AGENCY_PAGE_ID = /^[a-z0-9][a-z0-9-]{0,40}$/;
// The indexable about pages as the app draws them, for the data run's static copies: the same view functions, given
// the state a fresh visitor's app would have (this snapshot, its tags and roster; no sync link; sync available).
export function aboutPages({bills, snapshot, tags = null, roster = null, status = null}) {
  const keys = ['bills', 'meta', 'luna', 'roster', 'reviewStatus'], saved = Object.fromEntries(keys.map(k => [k, state[k]]));
  const tagged = tags?.format === 'texas-bill-luna-tags-v1' && tags.bills && typeof tags.bills === 'object';
  Object.assign(state, {bills, meta: {...snapshot, bills: undefined, loaded_from: 'Live server snapshot'},
    luna: tagged ? {...tags, agencies: tags.agencies && typeof tags.agencies === 'object' ? tags.agencies : {}} : null,
    roster: roster?.format === 'texas-bill-members-v1' ? roster : null, reviewStatus: status});
  try {
    const page = (view, html) => ({view, path: routeForView(view).path, heading: ABOUT_HEADINGS[view],
      description: routeForView(view).description || '', html});
    return [page('method', methodMarkup()), page('saving', savingMarkup({linked: null, syncAvailable: true})),
      page('data', dataMarkup({stampText, reviewParts}))];
  } finally { Object.assign(state, saved); }
}

// Runs draw() with the clock stopped at `iso`, so pages that say "today" or count days describe the snapshot's own
// moment (and the build stays reproducible); an unreadable time leaves the clock alone.
export function atTime(iso, draw) {
  const at = Date.parse(iso || ''), Real = globalThis.Date;
  if (Number.isNaN(at)) return draw();
  class Stopped extends Real {
    constructor(...args) { if (args.length) super(...args); else super(at); }
    static now() { return at; }
  }
  globalThis.Date = Stopped;
  try { return draw(); } finally { globalThis.Date = Real; }
}

// Home and Today as a first-time visitor's app draws them at the snapshot's time (nothing watched or followed).
export function viewPages({bills, snapshot, tags = null, roster = null, status = null}) {
  const keys = ['bills', 'meta', 'luna', 'roster', 'reviewStatus', 'todayTopic', 'todayLimit', 'todayAllTopics'];
  const saved = Object.fromEntries(keys.map(k => [k, state[k]]));
  const tagged = tags?.format === 'texas-bill-luna-tags-v1' && tags.bills && typeof tags.bills === 'object';
  Object.assign(state, {bills, meta: {...snapshot, bills: undefined, loaded_from: 'Live server snapshot'},
    luna: tagged ? {...tags, agencies: tags.agencies && typeof tags.agencies === 'object' ? tags.agencies : {}} : null,
    roster: roster?.format === 'texas-bill-members-v1' ? roster : null, reviewStatus: status,
    todayTopic: '', todayLimit: 100, todayAllTopics: false});
  try {
    const page = (view, html) => ({view, path: view === 'home' ? '/' : routeForView(view).path, heading: PAGE_HEADINGS[view],
      description: routeForView(view).description || '', html});
    return atTime(snapshot.generated_at, () => [page('home', homeMarkup()), page('today', todayMarkup({todayRow}))]);
  } finally { Object.assign(state, saved); }
}

export function sitePages(bills, asOf, about = [], views = []) {
  const ids = list => [...list].sort(byRecent).map(b => b.id);
  const topics = POLICY_AREAS.map(a => ({slug: topicSlug(a.name), name: a.name, bills: ids(bills.filter(b => b.topics.includes(a.name)))}));
  const agencies = [...groupBy(bills, b => b.agencies.map(a => a.id).filter(id => id !== SCOPE_AGENCY_ID))]
    .filter(([id]) => AGENCY_PAGE_ID.test(id)).sort((a, b) => a[0].localeCompare(b[0]))
    .map(([id, list]) => ({id, name: list.find(b => b.agencyNames[id])?.agencyNames[id] || AGENCY_NAME[id] || id, bills: ids(list)}));
  return JSON.stringify({format: 'texas-bill-atlas-site-pages-v1', bill_data_as_of: asOf || null, topics, agencies, about, views}) + '\n';
}

// One page per Texas House and Senate district: its member, their bills, and bills naming its counties or cities.
// Same matching as the tracker's "Near you" view (src/geo.js). `geo` is that module, passed in so the build still
// runs where geo.js is not deployed.
function districtPages({bills, roster, tables, geo, put, files, indexes, asOf}) {
  const gaz = geo.gazetteer(tables);
  const rows = [];
  const billRow = (b, why) => `| [${b.number}](${AGENT}bills/${b.id}.md) | ${cell(why)} | ${cell(b.title)} | ${cell(b.lastAction.label)} | ${b.lastAction.date || ''} |`;
  const head = '| Bill | Why listed | Title | Last action | Date |\n|---|---|---|---|---|\n';
  for (const [chamber, count, name, title] of [['house', geo.HOUSE_COUNT, 'House', 'Rep.'], ['senate', geo.SENATE_COUNT, 'Senate', 'Sen.']]) {
    for (let n = 1; n <= count; n++) {
      const d = String(n), counties = geo.countiesOf(tables, chamber, d);
      const split = c => Object.keys(tables.counties?.[c]?.[chamber] || {}).length > 1;
      const members = geo.membersFor(roster, chamber, d);
      const memberLines = members.length ? members.map(m => {
        const authorPage = `authors/${chamber}-${slug(m.display_name || '')}.md`;
        const links = [files.has(authorPage) ? `[their bills](${AGENT}${authorPage})` : null,
          typeof m.links?.tlo === 'string' && /^https?:/.test(m.links.tlo) ? `[Texas Legislature Online](${m.links.tlo})` : null].filter(Boolean);
        return `- ${title} ${cell(m.full_name || m.display_name)}: ${cell(memberSummary(m))}${links.length ? ` (${links.join(', ')})` : ''}`;
      }).join('\n') : '- No member with a known district is listed for this district yet (a new member\'s district may not be recorded, or results are not posted). Check Texas Legislature Online.';
      const byMember = new Map();
      for (const m of members) for (const {bill, role} of geo.billsByMember(bills, m)) {
        const entry = byMember.get(bill.id) || {bill, notes: []};
        entry.notes.push(`${title} ${m.display_name}: ${role}`);
        byMember.set(bill.id, entry);
      }
      const area = {counties, exact: false};
      const local = bills.map(b => ({bill: b, notes: (geo.areaReasons(b, area, gaz) || []).map(r => r.text)})).filter(x => x.notes.length);
      const list = entries => entries.length ? head + [...entries].sort((a, b) => byRecent(a.bill, b.bill)).map(e => billRow(e.bill, e.notes.join('; '))).join('\n') + '\n' : '_None in this snapshot._\n';
      const path = `districts/${chamber}-${d}.md`;
      put(path, `# Texas ${name} District ${d}\n\n${asOf} Districts are the ${tables.plans?.[chamber] || ''} plan used for the 90th Legislature.\n\n`
        + `Counties: ${counties.map(c => `${c}${split(c) ? ' (part)' : ''}`).join(', ') || 'unknown'}.\n\n## Member\n\n${memberLines}\n\n`
        + `## Filed or signed by this district's member (${byMember.size})\n\n${list([...byMember.values()])}\n`
        + `## Bills that name this district's counties or cities (${local.length})\n\nListed when the full-text review names a county, city or CDP in these counties, or the caption names the county. A county marked "(part)" is split between districts, so its bills appear on every district it touches. Bills written for areas by population size are not matched yet; statewide bills are not listed.\n\n${list(local)}\n---\n${DISCLAIMER}\n`);
      rows.push([`${name} District ${d}${members.length ? ` (${members.map(m => m.display_name).join(', ')})` : ''}`, path, byMember.size + local.length]);
    }
  }
  put('districts/index.md', `# Bills by legislative district\n\nOne page per Texas House (150) and Senate (31) district: the member, the bills they filed or signed onto, and bills naming the district's counties or cities. To find a district from an address, use the official lookup: https://wrm.capitol.texas.gov/home (this site takes no location). The Bills column counts both lists, so a bill can count twice.\n\n| District | Bills |\n|---|---|\n`
    + rows.map(([label, href, n]) => `| [${linkText(label)}](${AGENT}${href}) | ${n} |`).join('\n') + `\n\n---\n${DISCLAIMER}\n`);
  indexes.push(['Bills by legislative district', 'districts/index.md', rows.length]);
}

export function buildPages({snapshot, tags = null, extras = null, roster = null, status = null, minBills = 1000, districts = null, geo = null, texts = null, law = null}) {
  const bills = loadBills({snapshot, tags, extras, roster, minBills});
  const files = new Map();
  const put = (path, text) => files.set(path, text);
  const dataDate = snapshot.generated_at;
  const asOf = `Bill data as of ${dataDate}${tags?.generated_at ? `; full-text tags as of ${tags.generated_at}` : ''}${roster?.generated_at ? `; member roster as of ${roster.generated_at}` : ''}.`;
  // Pages that list many bills point to the overview for freshness instead of carrying the stamps: a stamp that
  // moved without a bill changing (the tags stamp once moved every review run) rewrote all of them.
  const freshness = `How current this is: see the [overview](${AGENT}index.md).`;
  const records = new Map(bills.map(b => [b.id, billRecord(b)]));
  const listed = role => bills.filter(b => records.get(b.id).people[role]?.length).length;
  const coverage = {bills: bills.length, full_text_reviewed: bills.filter(b => b.luna).length,
    with_coauthors: listed('coauthors'), with_sponsors: listed('sponsors'), with_cosponsors: listed('cosponsors'),
    with_hearing: bills.filter(b => HEARD.has(b.hearing.label)).length, as_of: dataDate};

  // One review state per bill. "Reviewed" always means a published full-text review (b.luna), the same count
  // the tables, coverage and search use; the worker's own queue only explains what is pending.
  const progress = reviewProgress(bills.map(b => b.id), status, Object.keys(tags?.bills || {}));
  const published = new Set(bills.filter(b => b.luna).map(b => b.id));
  const reviewState = new Map();
  for (const id of progress.active) reviewState.set(id, published.has(id) ? 're-review under way now' : 'under review now');
  for (const f of progress.failed) reviewState.set(f.id, `${published.has(f.id) ? 'last re-review' : 'review'} failed${f.stage ? ` at ${f.stage}` : ''}; it will be retried`);
  for (const id of progress.inProgress) reviewState.set(id, published.has(id) ? 're-review queued' : 'queued for a retry');
  for (const id of progress.reviewed) reviewState.set(id, published.has(id) ? 'reviewed' : 'reviewed, but nothing could be verified against the text to publish');
  for (const id of progress.notStarted) reviewState.set(id, status ? 'queued, not started yet' : 'review status not available');

  // Queue position for bills never reviewed. The worker takes up to three retries, then never-reviewed bills in
  // snapshot order, forward or reversed (a deploy setting); the worker's own "upcoming" list shows which. With no
  // clear direction, no position is claimed.
  const neverReviewed = progress.notStarted.filter(id => !published.has(id));
  const at = new Map(neverReviewed.map((id, i) => [id, i]));
  const next = progress.upcoming.filter(id => at.has(id)).map(id => at.get(id));
  const rising = next.length > 1 && next.every((v, i) => !i || v > next[i - 1]);
  const falling = next.length > 1 && next.every((v, i) => !i || v < next[i - 1]);
  const queueOrder = rising ? neverReviewed : falling ? [...neverReviewed].reverse() : null;
  const ahead = Math.min(3, progress.inProgress.length) + progress.active.length;
  // Pace window: the worker's own status time when there is one (it moves every run), else the tags time. The tags
  // stamp alone now moves only when tags change, so on quiet days it would keep counting an old busy day.
  const statusAt = Date.parse(status?.updated_at || '');
  const tagsAt = Number.isNaN(statusAt) ? Date.parse(tags?.generated_at || '') : statusAt;
  const paceFrom = Number.isNaN(statusAt) ? 'the tags were published' : "the worker's latest status";
  const lastDay = Number.isNaN(tagsAt) ? 0 : bills.filter(b => Date.parse(b.luna?.reviewed_at || '') >= tagsAt - 86400000).length;
  const queueNote = new Map((queueOrder || []).map((id, i) => {
    const position = ahead + i + 1;
    return [id, `about number ${position} in the review queue${lastDay ? `, roughly ${Math.max(1, Math.ceil(position / lastDay))} ${Math.ceil(position / lastDay) > 1 ? 'days' : 'day'} away at the recent pace (an estimate)` : ''}`];
  }));
  for (const b of bills) {
    const text = texts ? texts.get(b.id) || null : undefined, record = records.get(b.id);
    const current = law ? law.get(b.id) || [] : undefined;
    put(`bills/${b.id}.md`, billMarkdown(b, coverage, reviewState.get(b.id), queueNote.get(b.id), text, dataDate, current));
    let json = text ? {...record, links: {full_text: text.versions.at(-1).url, ...record.links}, text_versions: text.versions} : record;
    if (current?.length) json = {...json, current_law: current};
    put(`bills/${b.id}.json`, JSON.stringify(json, null, 1) + '\n');
  }

  // Group pages are split into pages of PAGE bills so each stays small enough for page-reading tools.
  const pagedGroup = (base, title, intro, list, humanLink) => {
    const sorted = [...list].sort(byRecent), pages = Math.max(1, Math.ceil(sorted.length / PAGE));
    const href = i => `${base}${i ? `--page-${i + 1}` : ''}.md`;
    for (let i = 0; i < pages; i++) {
      const chunk = sorted.slice(i * PAGE, (i + 1) * PAGE);
      const nav = pages > 1 ? `\n\nPage ${i + 1} of ${pages} (bills ${i * PAGE + 1}-${i * PAGE + chunk.length} of ${sorted.length}). Pages: `
        + Array.from({length: pages}, (_, j) => j === i ? `${j + 1}` : `[${j + 1}](${AGENT}${href(j)})`).join(' · ') : '';
      put(href(i), groupPage(title, intro + nav, chunk, humanLink, sorted.length));
    }
  };
  pagedGroup('bills/index', 'All bills', `${freshness} Also by [filing date](${AGENT}filed/index.md), or [search](${AGENT}search).`,
    bills, SITE + '#all');

  const indexes = [];
  const byCount = label => (a, b) => b[1].length - a[1].length || String(label(a[0])).localeCompare(String(label(b[0])));
  const addGroups = (dir, title, intro, groups, label, human, {order = null, note = ''} = {}) => {
    const entries = [...groups].sort(order ? (a, b) => order(a[0], b[0]) : byCount(label));
    const single = entries.length === 1 && entries[0][1].length === bills.length
      ? ` ${note ? 'All' : `As of ${dataDate}, all`} ${bills.length} bills are in one group ("${cell(label(entries[0][0]))}"), so this view does not tell bills apart yet.` : '';
    const rows = entries.map(([key, list]) => {
      pagedGroup(`${dir}/${slug(key)}`, label(key), intro, list, human ? human(key) : null);
      return [label(key), `${dir}/${slug(key)}.md`, list.length];
    });
    put(`${dir}/index.md`, indexPage(title, `${intro}${note ? ` ${note}` : ''}${single}`, rows));
    indexes.push([title, `${dir}/index.md`, rows.length]);
  };
  addGroups('topics', 'Bills by topic', 'Policy topics, from the Luna full-text review where available and caption rules otherwise.',
    groupBy(bills, b => b.topics), k => k, k => tracker({topic: k}));
  addGroups('agencies', 'Bills by potentially affected agency', 'Possible links are inferences, not confirmed legal obligations.',
    groupBy(bills, b => b.agencies.map(a => a.id)), k => bills.find(b => b.agencyNames[k])?.agencyNames[k] || k, k => tracker({agency: k}));
  addGroups('last-action', 'Bills by most recent action', 'Categories of the most recent recorded action, along the legislative path.',
    groupBy(bills, b => [b.lastAction.label]), k => k, k => tracker({action: k}));
  addGroups('hearing', 'Bills by hearing status', 'Procedural evidence from recorded actions; not a prediction.',
    groupBy(bills, b => [b.hearing.label]), k => k, k => tracker({outlook: k}),
    {order: (a, b) => HEARING_ORDER.indexOf(a) - HEARING_ORDER.indexOf(b),
      note: coverage.with_hearing ? `${coverage.with_hearing} of ${bills.length} bills have a committee hearing recorded or scheduled as of ${dataDate}.`
        : `No bill has a committee hearing recorded or scheduled as of ${dataDate}.`});
  addGroups('chamber', 'Bills by chamber', 'The chamber where the bill was filed.', groupBy(bills, b => [b.chamber]), k => k,
    k => tracker({chamber: k}));
  addGroups('filed', 'Bills by filing date', `The date each bill was filed, newest first. ${FILED_NOTE}`, groupBy(bills, b => [b.filed_at || 'unknown']),
    k => k, null, {order: (a, b) => b.localeCompare(a)});
  addGroups('authorship', 'Bills by authorship party', 'Party of the bill\'s authors and coauthors, from the member roster. Not a vote or caucus position.',
    groupBy(bills, b => [records.get(b.id).authorship_party.label]), k => k, null);
  addGroups('full-text-review', 'Bills by full-text review', `Whether Luna has read the bill's full text (${coverage.full_text_reviewed} of ${bills.length} so far). Unreviewed bills use caption rules.`,
    groupBy(bills, b => [b.luna ? 'Full text reviewed' : 'Caption rules only']), k => k, null);

  // Authors: every named member and the bills they author, coauthor or sponsor.
  const people = new Map();
  const missingRoles = ['coauthors', 'sponsors', 'cosponsors'].filter(role => coverage[`with_${role}`] === 0);
  const roleNote = missingRoles.length ? ` As of ${dataDate} no bill lists any ${missingRoles.join(' or ')} yet, so only author roles appear.` : '';
  for (const b of bills) for (const role of ['authors', 'coauthors', 'sponsors', 'cosponsors']) for (const p of records.get(b.id).people[role] || []) {
    const key = authorKey(p, role, b);
    if (!people.has(key)) people.set(key, {name: p.full_name || p.name, summary: p.matched ? p.summary : 'Not matched to the 90th Legislature roster', roles: new Map()});
    people.get(key).roles.set(b, [...(people.get(key).roles.get(b) || []), role.replace(/s$/, '')]);
  }
  const personRows = [...people].sort((a, b) => a[1].name.localeCompare(b[1].name)).map(([key, p]) => {
    const rows = [...p.roles].sort((x, y) => byRecent(x[0], y[0]));
    put(`authors/${key}.md`, `# ${cell(p.name)}\n\n${cell(p.summary)}\n\n${rows.length} ${rows.length === 1 ? 'bill' : 'bills'}.${roleNote}\n\n| Bill | Role | Title | Last action | Date |\n|---|---|---|---|---|\n`
      + rows.map(([b, roles]) => `| [${b.number}](${AGENT}bills/${b.id}.md) | ${roles.join(', ')} | ${cell(b.title)} | ${cell(b.lastAction.label)} | ${b.lastAction.date || ''} |`).join('\n')
      + `\n\n---\n${DISCLAIMER}\n`);
    return [`${p.name} (${key.split('-')[0]})`, `authors/${key}.md`, rows.length];
  });
  // Member pages are keyed by the name the bill lists (usually a last name). A full-name address such as
  // authors/house-ann-johnson.md points to the real page instead of 404ing.
  for (const [key, p] of people) {
    const alias = `${key.split('-')[0]}-${slug(p.name)}`;
    if (alias !== key && !people.has(alias) && !files.has(`authors/${alias}.md`))
      put(`authors/${alias}.md`, `# ${cell(p.name)}\n\nThis member's bills are listed at [authors/${key}.md](${AGENT}authors/${key}.md).\n`);
  }
  put('authors/index.md', indexPage('Bills by member', `Authors and coauthors serve in the originating chamber; sponsors and cosponsors in the other.${roleNote}`, personRows));
  indexes.push(['Bills by member', 'authors/index.md', personRows.length]);

  if (districts && geo) districtPages({bills, roster, tables: districts, geo, put, files, indexes, asOf: freshness});

  put('recent.md', groupPage('Most recent actions', `The 100 bills with the most recent recorded actions, so not every bill acted on in a period. For everything filed since a date use ${AGENT}search?filed_from=YYYY-MM-DD or [bills by filing date](${AGENT}filed/index.md); for one action type see [bills by most recent action](${AGENT}last-action/index.md). ${asOf}`,
    [...bills].sort(byRecent).slice(0, 100), tracker({sort: 'latest'})));

  const ids = list => list.length ? list.map(id => `[${id}](${AGENT}bills/${id}.md)`).join(', ') : '_None._';
  const inState = test => bills.filter(b => test(reviewState.get(b.id) || '', published.has(b.id))).map(b => b.id);
  const again = inState((s, p) => p && s !== 'reviewed');
  const unpublished = inState((s, p) => !p);
  const pendingBy = test => unpublished.filter(id => test(reviewState.get(id) || ''));
  const running = pendingBy(s => s.startsWith('under review') || s.startsWith('queued for a retry'));
  const failedNew = pendingBy(s => s.includes('failed'));
  const unverified = pendingBy(s => s.startsWith('reviewed'));
  // Exclusive buckets: "queued for a retry" is counted in running only, so the four add up to unpublished.
  const queued = pendingBy(s => s.startsWith('queued, not started') || s.includes('not available') || !s);
  // Throughput from published review dates; an estimate only.
  const pace = Number.isNaN(tagsAt) ? '' : lastDay
    ? `In the 24 hours before ${paceFrom}, ${lastDay} ${lastDay === 1 ? 'review was' : 'reviews were'} published; at that pace the ${unpublished.length} unpublished ${unpublished.length === 1 ? 'bill' : 'bills'} would take about ${Math.ceil(unpublished.length / lastDay)} ${Math.ceil(unpublished.length / lastDay) === 1 ? 'day' : 'days'}. An estimate, not a schedule.`
    : `No review was published in the 24 hours before ${paceFrom}, so there is no pace to estimate from.`;
  const order = 'Order: the worker takes up to three retries first, then bills never reviewed, then failed bills, then re-reviews of the rest. Only the next five are listed under Up next; a bill not listed there is still queued.'
    + (queueOrder ? ' Each unreviewed bill\'s page gives its approximate place in the queue.' : ' The worker\'s order is not clear from its status right now, so bill pages give no queue position.');
  put('review-progress.md', `# Full-text review progress\n\nLuna reads each bill's full text and publishes citation-verified tags. ${status?.updated_at ? `Worker status as of ${status.updated_at}.` : 'Worker status is not available right now; counts below come from published tags only.'} Published tags as of ${tags?.generated_at || 'not available yet'}.\n\n`
    + `- Reviewed, with published tags: ${published.size} of ${bills.length} (the count used everywhere on this site)\n`
    + `  - Queued for a re-review: ${again.filter(id => !reviewState.get(id).includes('failed')).length}; last re-review failed (earlier tags still shown): ${again.filter(id => reviewState.get(id).includes('failed')).length}\n`
    + `- Not yet published: ${unpublished.length}\n`
    + `  - Under review now or queued for a retry: ${running.length}; failed, will be retried: ${failedNew.length}; reviewed with nothing verifiable to publish: ${unverified.length}; queued, not started: ${queued.length}\n\n`
    + `${pace ? `${pace}\n\n` : ''}${order}\n\n`
    + `## Under review now\n\n${progress.active.length ? ids(progress.active) : '_Nothing right now._'}\n\n## Up next\n\n${ids(progress.upcoming)}\n\n`
    + `## Reviewed, with published tags\n\n${ids([...published])}\n\n## Queued for a retry (not yet published)\n\n${ids(running)}\n\n`
    + `## Failed, will be retried\n\n${ids(progress.failed.map(f => f.id))}\n\n---\n${DISCLAIMER}\n`);

  put('saving.md', SAVING);
  put('data/pages.json', sitePages(bills, snapshot.generated_at, aboutPages({bills, snapshot, tags, roster, status}),
    viewPages({bills, snapshot, tags, roster, status})));
  put('data/bills.json', JSON.stringify({format: 'texas-bill-atlas-agent-v1', session: '90R', disclaimer: DISCLAIMER,
    bill_data_as_of: snapshot.generated_at, tags_as_of: tags?.generated_at || null, roster_as_of: roster?.generated_at || null,
    coverage_note: snapshot.coverage_note || null, sources: snapshot.sources || null, count: bills.length, coverage,
    bills: [...bills].sort((a, b) => a.id.localeCompare(b.id, 'en', {numeric: true})).map(b => records.get(b.id))}) + '\n');

  // Served by the gateway for any missing path: say what exists instead of a bare 404.
  const ranges = [...groupBy(bills, b => [b.id.replace(/\d+$/, '')])].sort((a, b) => b[1].length - a[1].length).map(([prefix, list]) => {
    const nums = list.map(b => Number(b.id.slice(prefix.length))).sort((x, y) => x - y);
    return `- ${prefix}: ${list.length} bills between ${prefix}${nums[0]} and ${prefix}${nums.at(-1)}${nums.at(-1) - nums[0] + 1 > list.length ? ` (${nums.at(-1) - nums[0] + 1 - list.length} numbers in that range have no page yet)` : ''}`;
  });
  put('404.md', `# Not found\n\nThere is no page at this address.\n\n`
    + `- **Looking for a bill?** It is not in the data yet: a bill appears here within about an hour of the Texas Legislative Council publishing it in its bulk files. ${asOf} Bill pages are \`${AGENT}bills/<ID>.md\` with no spaces (HB5, SB12).\n`
    + `- **Looking for a word or topic?** Use search: \`${AGENT}search?q=<words>\` matches word forms, synonyms, phrases and members. (The old \`words/<word>.md\` keyword pages were replaced by search.)\n`
    + `- **Looking for a member?** Pages are \`authors/<chamber>-<name>.md\` as the bill lists the name, usually the last name (\`authors/house-johnson.md\`); full names also work. All members: ${AGENT}authors/index.md, or search by name: \`${AGENT}search?q=<name>\`.\n`
    + `- Start at ${AGENT}llms.txt for everything available.\n\nBill numbers in the data now:\n\n${ranges.join('\n')}\n\n---\n${DISCLAIMER}\n`);

  const example = [...bills].sort(byRecent)[0];
  const overview = overviewPage(bills.length, asOf, indexes, example, coverage);
  put('index.md', overview);
  put('llms.txt', overview);
  // Crawler discovery: OpenAI's agents open a link on their own only once a crawler has seen that exact URL,
  // so the pages need to be findable from robots.txt, a sitemap and a plain HTML page.
  put('robots.txt', ROBOTS);
  put('index.html', discoveryPage(bills, asOf, indexes));
  put('sitemap.xml', sitemap([...files.keys()]));  // Last, so it lists every page above.
  return files;
}

const ROBOTS = `# Texas Bill Atlas, agent edition: Markdown and JSON pages for ${SITE}
# Search crawlers and AI agents are welcome. Search results (/search?...) are live, rate-limited queries:
# crawlers please don't crawl them (they are also marked noindex). Agents fetching for a person may use them.
User-agent: OAI-SearchBot
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Claude-SearchBot
User-agent: PerplexityBot
User-agent: Googlebot
User-agent: Bingbot
User-agent: Applebot
User-agent: DuckDuckBot
User-agent: YandexBot
User-agent: Baiduspider
User-agent: Amazonbot
User-agent: Bytespider
User-agent: CCBot
User-agent: meta-externalagent
Allow: /
Disallow: /search?
Disallow: /search.md?
Disallow: /search.json?

User-agent: *
Allow: /

Sitemap: ${AGENT}sitemap.xml
`;

const html = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

// Every Markdown page (the bill pages above all) plus the HTML entry point; JSON twins and the 404 page are left out.
export function sitemap(paths) {
  const pages = ['index.html', ...paths.filter(p => p.endsWith('.md') && p !== '404.md').sort((a, b) => a.localeCompare(b, 'en', {numeric: true}))];
  const loc = p => html(p === 'index.md' ? AGENT : AGENT + p);
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n`
    + pages.map(p => `  <url><loc>${loc(p)}</loc></url>`).join('\n') + '\n</urlset>\n';
}

// An ordinary crawlable page for crawlers and browsers that won't follow Markdown; the Markdown stays the API.
function discoveryPage(bills, asOf, indexes) {
  const list = [...bills].sort((a, b) => a.id.localeCompare(b.id, 'en', {numeric: true}))
    .map(b => `<li><a href="${AGENT}bills/${html(b.id)}.md">${html(b.number)}</a> ${html(b.title)}</li>`).join('\n');
  const groups = indexes.map(([title, href, n]) => `<li><a href="${AGENT}${html(href)}">${html(title)}</a> (${n} groups)</li>`).join('\n');
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Texas Bill Atlas agent edition: 90th Texas Legislature bills as Markdown and JSON</title>
<meta name="description" content="Plain-text and JSON pages for all ${bills.length} bills the Texas Bill Atlas tracks in the 90th Texas Legislature: captions, authors, actions, hearings, topics, agencies and full-text reviews.">
<link rel="canonical" href="${AGENT}index.html">
<link rel="alternate" type="text/markdown" href="${AGENT}index.md">
</head>
<body>
<h1>Texas Bill Atlas (agent edition)</h1>
<p>Plain-text and JSON pages for everything the <a href="${SITE}">Texas Bill Atlas</a> tracker shows for the 90th Texas Legislature: ${bills.length} bills with captions, authors and sponsors, recorded actions, hearing status, topics, potentially affected agencies and full-text reviews. No JavaScript, login or API key needed. ${html(asOf)}</p>
<p>Start with the <a href="${AGENT}index.md">Markdown overview</a> or <a href="${AGENT}llms.txt">llms.txt</a>. Search: <a href="${AGENT}search">${AGENT}search</a>. One bill: <code>${AGENT}bills/&lt;ID&gt;.md</code> or <code>.json</code>.</p>
<h2>Browse</h2>
<ul>
<li><a href="${AGENT}bills/index.md">All bills</a></li>
<li><a href="${AGENT}recent.md">Most recent actions</a></li>
${groups}
<li><a href="${AGENT}review-progress.md">Full-text review progress</a></li>
<li><a href="${AGENT}data/bills.json">Everything as one JSON file</a> (large)</li>
</ul>
<h2>Every bill (${bills.length})</h2>
<ul>
${list}
</ul>
<p><small>${html(DISCLAIMER)}</small></p>
</body>
</html>
`;
}

function overviewPage(count, asOf, indexes, example, coverage) {
  const zeroNote = 'A zero means the source has none yet (bills are early in the session), not that data is missing.';
  return `# Texas Bill Atlas (agent edition)

> Plain-text and JSON access to everything the Texas Bill Atlas tracker (${SITE}) shows for the 90th Texas Legislature: ${count} bills with captions, authors and sponsors (party, district, tenure), recorded actions, hearing status, most recent action, topics, potentially affected agencies, impacts, affected groups and Luna full-text reviews. No JavaScript, login or API key needed.

Updated hourly from the Texas Legislative Council bulk FTP. ${asOf} ${FILED_NOTE}

## Quick reference

- Search: ${AGENT}search?q=<words> (Markdown; add &format=json). Every word must match; join alternatives with OR (q=hemp OR marijuana). Filters: chamber, topic, agency, location, party, reviewed, filed_from, filed_to. Usage: ${AGENT}search
- Recently filed: ${AGENT}search?filed_from=YYYY-MM-DD lists every bill filed since a date
- One bill: ${AGENT}bills/<ID>.md or .json (IDs like HB5, SB12; no spaces)
- Lists: ${AGENT}topics/index.md · ${AGENT}agencies/index.md · ${AGENT}authors/index.md (members) · ${AGENT}filed/index.md · ${AGENT}recent.md
- Coverage: ${coverage.full_text_reviewed} of ${coverage.bills} bills have a full-text review; ${coverage.with_hearing} have a hearing recorded; ${coverage.with_coauthors} list coauthors. Missing or pending data is labelled as such on each page.

${DISCLAIMER}

## Start here

- [Search](${AGENT}search): words, phrases, bill numbers and member names across titles, captions, topics, agencies, full-text summaries, affected groups, locations and actions, with filters
- [All bills](${AGENT}bills/index.md): one row per bill with topics, agencies and review status, most recent action first, ${PAGE} per page
- [Most recent actions](${AGENT}recent.md)
- One bill: \`${AGENT}bills/<ID>.md\` or \`.json\`, for example [${example.number}](${AGENT}bills/${example.id}.md). IDs have no spaces (HB5, SB12, HJR5, SCR3); a bill that has not been filed has no page. Each links its official history and full text.
- [Everything as one JSON file](${AGENT}data/bills.json) (large): the same records as the per-bill JSON, for your own filtering

Group tables show each bill's topics and agencies, so a topic page can be read for a single agency (or the reverse) without opening every bill.

## Coverage

As of ${coverage.as_of}:

- Full-text reviewed: ${coverage.full_text_reviewed} of ${coverage.bills} bills
- Bills listing coauthors: ${coverage.with_coauthors}; sponsors: ${coverage.with_sponsors}; cosponsors: ${coverage.with_cosponsors}
- Bills with a committee hearing recorded or scheduled: ${coverage.with_hearing}

${zeroNote}

## Browse like the tracker's filters

${indexes.map(([title, href, n]) => `- [${title}](${AGENT}${href}) (${n} groups)`).join('\n')}
- [Full-text review progress](${AGENT}review-progress.md)

## Mapping tracker links

A bill's tracker page is \`${SITE}bill/<ID>\`; other views keep their state after \`#\` in the address. Equivalents here:

- \`${SITE}bill/${example.id}\` (or the older \`${SITE}#all?bill=${example.id}\`) -> \`${AGENT}bills/${example.id}.md\`
- \`#all?topic=<topic>\` -> \`${AGENT}topics/index.md\`; \`#all?agency=<id>\` -> \`${AGENT}agencies/index.md\`; \`#all?action=<category>\` -> \`${AGENT}last-action/index.md\`; \`#all?outlook=<status>\` -> \`${AGENT}hearing/index.md\`; \`#all?chamber=<chamber>\` -> \`${AGENT}chamber/index.md\`
- Text search (\`query=<words>\`) -> \`${AGENT}search?q=<words>\`.
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

- **Links to a view**: the tracker's address describes the view, e.g. \`${SITE}#all?topic=Water\`; a bill's page is \`${SITE}bill/HB1\`.
- **Share links**: \`${SITE}#all?list=HB1,SB2\` opens a read-only list. For agents: fetch \`${AGENT}bills/<ID>.md\` for each id.
- **Export/import**: the watchlist file is JSON: \`{"format": "texas-bill-atlas-watchlist-v1", "session": "90R", "bills": ["HB1", "SB2"]}\`. Import also accepts any text listing bill numbers.
- **RSS**: \`${SITE}live/feeds/<ID>.xml\` per bill.

## Private sync links (read-only access for agents)

A sync list has an edit key and a view key (22 characters each). Never ask a person for their edit key; it lets anyone change the list. A view-only link looks like \`${SITE}#watchlist?sync=<view key>\`. With a view key:

- \`GET ${SITE}api/sync\` with header \`X-Sync-Key: <view key>\` returns \`{"mode": "view", "version": n, "data": {"watch": ["HB1", ...], "filters": {}}}\`
- \`GET ${SITE}api/sync/feed/<view key>.xml\` is an RSS feed of the latest actions on every bill in the list

Requests are rate limited per client address, per rolling hour: 1200 reads (including feeds), 300 writes and 10 new lists; agent search allows 1200 searches. Over the limit the service returns 429 with a \`Retry-After\` header in seconds. The service stores only the bill numbers, followed legislators' member codes, saved searches (names, search words and filters), a version and dates; keys are stored as one-way hashes. No names, emails or accounts.

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

async function main(argv) {
  const args = Object.fromEntries(argv.reduce((acc, value, i, all) => value.startsWith('--') ? [...acc, [value.slice(2), all[i + 1]]] : acc, []));
  if (!args.snapshot || !args.out) throw new Error('Usage: build_agent.mjs --snapshot bills.json --out dir [--tags t.json] [--extras e.json] [--members m.json] [--status s.json] [--districts districts.json] [--text live/text]');
  // District pages only when the district tables are given; geo.js is loaded only then, so older deployments
  // that copy just taxonomy.js and prefs.js keep building.
  const districts = args.districts ? readJson(args.districts) : null;
  if (districts && districts.format !== 'texas-bill-districts-v1') throw new Error('Unknown districts format');
  const geo = districts ? await import('../src/geo.js') : null;
  // live/text sits beside bills.json, so the installed unit needs no new flag; --text overrides it.
  const snapshot = readJson(args.snapshot);
  const texts = loadTexts(args.text || join(dirname(args.snapshot), 'text'), (snapshot.bills || []).map(b => String(b?.id || '')).filter(Boolean));
  // live/statutes and live/law sit beside bills.json too: the agent unit needs no new flag or mount.
  const law = loadLaw(dirname(args.snapshot), (snapshot.bills || []).map(b => String(b?.id || '')).filter(Boolean));
  // extras.json sits beside tags.json in live/luna; finding it there needs no change to the installed unit's flags.
  const extrasPath = args.extras || (args.tags ? join(dirname(args.tags), 'extras.json') : null);
  const files = buildPages({snapshot, tags: args.tags ? readJson(args.tags, true) : null,
    extras: extrasPath ? readJson(extrasPath, true) : null,
    roster: args.members ? readJson(args.members, true) : null, status: args.status ? readJson(args.status, true) : null,
    districts, geo, texts, law});
  mkdirSync(args.out, {recursive: true, mode: 0o755});
  const result = writePages(args.out, files);
  console.log(`Agent pages: ${files.size} total, ${result.written} written, ${result.unchanged} unchanged, ${result.removed} removed`);
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) await main(process.argv.slice(2));
