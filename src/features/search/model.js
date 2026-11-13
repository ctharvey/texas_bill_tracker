// What the explorer's search reads, and why a result matched. No DOM.
import {textMatches} from '../../taxonomy.js';

// The fields search reads, in the order the explorer joins them into one text. `label` names the field in a match
// reason and in the "What search looks at" list; `example` is shown there.
export const SEARCH_FIELDS = [
  {key: 'number', label: 'bill number', example: 'HB 110'},
  {key: 'title', label: 'title'},
  {key: 'caption', label: 'caption'},
  {key: 'people', label: 'author or sponsor'},
  {key: 'action', label: 'last action'},
  {key: 'topics', label: 'policy area'},
  {key: 'subjects', label: 'official subject'},
  {key: 'terms', label: 'Luna search term'},
  {key: 'effects', label: 'Luna effect'},
  {key: 'groups', label: 'affected group', example: 'teachers'},
  {key: 'agencies', label: 'agency'},
  {key: 'party', label: 'party', example: 'Democrat'},
  {key: 'dates', label: 'date'},
];

// A bill's searchable values per field, as [key, values]. `ctx`: {agencyName, partyWords, shortDate}.
export function searchFields(b, {agencyName, partyWords, shortDate}) {
  return [
    ['number', [b.id, b.number]],
    ['title', [b.title]],
    ['caption', [b.caption]],
    ['people', [b.author, ...b.authors, ...(b.coauthors || []), ...(b.sponsors || []), ...(b.cosponsors || [])]],
    ['action', [b.last_action]],
    ['topics', [...b.topics]],
    ['subjects', [...(b.subjects || [])]],
    ['terms', [...(b.search_terms || [])]],
    ['effects', [...b.impacts]],
    ['groups', [...(b.constituencies || [])]],
    ['agencies', b.agencies.map(a => agencyName(a.id))],
    ['party', partyWords(b)],
    ['dates', [shortDate(b.filed_at), shortDate(b.last_action_date)]],
  ];
}

// The one text the explorer's filter matches against: every field's values, in order, joined by spaces.
export const searchText = fields => fields.flatMap(([, values]) => values).join(' ');

const LABEL = Object.fromEntries(SEARCH_FIELDS.map(f => [f.key, f.label]));

// Why a bill matched the folded query `q`: [{label, term}] for each search word, naming the first field that holds it
// (or "several fields" when the word only appears across a field boundary). `how` is 'number' or 'law' when the bill
// matched by its number or by a section of law it changes; then that is the one reason.
export function matchReasons(fields, q, how = '') {
  if (how === 'number') return [{label: LABEL.number, term: ''}];
  if (how === 'law') return [{label: 'changes this section of law', term: ''}];
  const out = [];
  for (const term of q.match(/"[^"]*"?|\S+/g) || []) {
    const word = term.replace(/^"|"$/g, '').trim();
    if (!word) continue;
    const hit = fields.find(([, values]) => textMatches(values.join(' '), term));
    const label = hit ? LABEL[hit[0]] : 'several fields';
    const same = out.find(r => r.label === label);
    if (same) same.term += ` ${word}`;
    else out.push({label, term: word});
  }
  return out;
}
