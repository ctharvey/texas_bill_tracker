import test from 'node:test';
import assert from 'node:assert/strict';
import {SEARCH_FIELDS, searchFields, searchText, matchReasons} from '../src/features/search/model.js';
import {searchTerms} from '../src/taxonomy.js';

const ctx = {agencyName: id => ({tea: 'Texas Education Agency'})[id] || id, partyWords: () => ['Democratic author', 'All authors are Democrats'],
  shortDate: iso => (iso ? `d:${iso}` : '')};
const bill = {id: 'HB110', number: 'HB 110', title: 'Relating to the minimum wage.', caption: 'Relating to wages.', author: 'Ramos',
  authors: ['Ramos'], coauthors: null, sponsors: ['Cook'], cosponsors: undefined, last_action: 'Filed', topics: ['Labor'],
  subjects: ['Wages'], search_terms: ['pay floor'], impacts: ['raises pay'], constituencies: ['teachers', 'hourly workers'],
  agencies: [{id: 'tea'}], filed_at: '2026-11-09', last_action_date: '2026-11-10'};

test('the joined search text is exactly what the explorer matched before the field table', () => {
  const b = bill, agencyName = ctx.agencyName, shortDate = ctx.shortDate, partyWords = ctx.partyWords;
  const before = [b.id, b.number, b.title, b.caption, b.author, ...b.authors, ...(b.coauthors || []), ...(b.sponsors || []), ...(b.cosponsors || []),
    b.last_action, ...b.topics, ...(b.subjects || []), ...(b.search_terms || []), ...b.impacts, ...(b.constituencies || []),
    ...b.agencies.map(a => agencyName(a.id)), ...partyWords(b), shortDate(b.filed_at), shortDate(b.last_action_date)].join(' ');
  assert.equal(searchText(searchFields(b, ctx)), before);
  const bare = {...b, subjects: undefined, search_terms: undefined, constituencies: undefined, author: undefined};
  const bareBefore = [bare.id, bare.number, bare.title, bare.caption, bare.author, ...bare.authors, ...bare.sponsors, bare.last_action, ...bare.topics,
    ...bare.impacts, agencyName('tea'), ...partyWords(), shortDate(bare.filed_at), shortDate(bare.last_action_date)].join(' ');
  assert.equal(searchText(searchFields(bare, ctx)), bareBefore);
});

test('the field table and the fields line up one for one', () => {
  assert.deepEqual(searchFields(bill, ctx).map(([key]) => key), SEARCH_FIELDS.map(f => f.key));
});

const why = (query, how) => matchReasons(searchFields(bill, ctx), searchTerms(query).q, how);

test('each word names the first field that holds it; words in the same field are listed together', () => {
  assert.deepEqual(why('teachers'), [{label: 'affected group', term: 'teachers'}]);
  assert.deepEqual(why('hourly teachers'), [{label: 'affected group', term: 'hourly teachers'}]);
  assert.deepEqual(why('minimum teachers'), [{label: 'title', term: 'minimum'}, {label: 'affected group', term: 'teachers'}]);
  assert.deepEqual(why('floor'), [{label: 'Luna search term', term: 'floor'}]);
  assert.deepEqual(why('Democrat'), [{label: 'party', term: 'democrat'}]);
  assert.deepEqual(why('education agency'), [{label: 'agency', term: 'education agency'}]);
});

test('a quoted phrase stays one term, and a plural finds its singular', () => {
  assert.deepEqual(why('"hourly workers"'), [{label: 'affected group', term: 'hourly workers'}]);
  assert.deepEqual(why('floors'), [{label: 'Luna search term', term: 'floors'}]);
});

test('a phrase that only exists across two fields says so; bill numbers and sections of law are their own reasons', () => {
  assert.deepEqual(why('"wage. relating"'), [{label: 'several fields', term: 'wage. relating'}]);
  assert.deepEqual(why('HB 110', 'number'), [{label: 'bill number', term: ''}]);
  assert.deepEqual(why('Labor Code 62.051', 'law'), [{label: 'changes this section of law', term: ''}]);
});
