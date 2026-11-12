// Explorer search: how a typed query is read (searchTerms) and how it survives the address bar (buildHash/parseHash).
import test from 'node:test';
import assert from 'node:assert/strict';
import {searchTerms, foldText, textMatches} from '../src/taxonomy.js';
import {buildHash, parseHash, cleanFilters} from '../src/prefs.js';

test('an empty or missing query has no terms', () => {
  for (const empty of ['', '   ', null, undefined, '\t\n', '\u200b', '\u00ad', '\ufeff'])
    assert.deepEqual(searchTerms(empty), {q: '', compact: ''}, JSON.stringify(empty));
});

test('a non-string query is read as its text', () => {
  assert.deepEqual(searchTerms(110), {q: '110', compact: '110'});
});

test('text is lower-cased, trimmed and single-spaced', () => {
  assert.equal(searchTerms('  Minimum   WAGE ').q, 'minimum wage');
  assert.equal(searchTerms('minimum\twage\nincrease').q, 'minimum wage increase');
  assert.equal(searchTerms('minimum\u00a0wage').q, 'minimum wage');  // non-breaking space
  assert.equal(searchTerms('minimum wage').compact, 'minimumwage');
});

test('invisible characters inside a word are dropped', () => {
  assert.equal(searchTerms('wa\u00adter').q, 'water');        // soft hyphen
  assert.equal(searchTerms('wa\u200bter').q, 'water');        // zero-width space
  assert.equal(searchTerms('\u202awater\u202c').q, 'water');  // direction marks
});

test('punctuation in ordinary text is kept', () => {
  assert.equal(searchTerms('A&M').q, 'a&m');
  assert.equal(searchTerms("children's").q, "children's");
  assert.equal(searchTerms('work-related').q, 'work-related');
  assert.equal(searchTerms('62.051').q, '62.051');
});

test('every bill type is read in its short form', () => {
  for (const type of ['hb', 'sb', 'hjr', 'sjr', 'hcr', 'scr', 'hr', 'sr']) {
    assert.equal(searchTerms(`${type.toUpperCase()} 12`).compact, `${type}12`);
    assert.equal(searchTerms(`${type}12`).compact, `${type}12`);
  }
});

test('every bill type is read in its long form', () => {
  const long = {'House Bill': 'hb', 'Senate Bill': 'sb', 'House Joint Resolution': 'hjr', 'Senate Joint Resolution': 'sjr',
    'House Concurrent Resolution': 'hcr', 'Senate Concurrent Resolution': 'scr', 'House Resolution': 'hr', 'Senate Resolution': 'sr'};
  for (const [words, type] of Object.entries(long)) {
    assert.equal(searchTerms(`${words} 34`).compact, `${type}34`, words);
    assert.equal(searchTerms(`${words.toLowerCase()} no. 34`).compact, `${type}34`, words);
  }
});

test('official punctuation around a bill number is ignored', () => {
  for (const form of ['S.B. 5', 'S.B. No. 5', 'SB No 5', 'SB No.5', 's. b. 5', 'S.B.5'])
    assert.equal(searchTerms(form).compact, 'sb5', form);
});

test('the typed text is kept beside the compact bill number', () => {
  assert.deepEqual(searchTerms('H.B. No. 267'), {q: 'h.b. no. 267', compact: 'hb267'});
});

test('text that only looks like a bill number is not treated as one', () => {
  assert.equal(searchTerms('hb').compact, 'hb');
  assert.equal(searchTerms('house bill').compact, 'housebill');
  assert.equal(searchTerms('bill 110').compact, 'bill110');
  assert.equal(searchTerms('hb 123456').compact, 'hb123456');  // six digits: no such bill number
  assert.equal(searchTerms('hb 110 school').compact, 'hb110school');
  assert.equal(searchTerms('xb 110').compact, 'xb110');
});

test('a bare number stays a bare number', () => {
  assert.deepEqual(searchTerms('110'), {q: '110', compact: '110'});
});

test('a bill number with leading zeros reads as the same bill', () => {
  assert.equal(searchTerms('hb0110').compact, 'hb110');
  assert.equal(searchTerms('HB 00110').compact, 'hb110');
});

test('a curly apostrophe reads like a straight one', () => {
  assert.equal(searchTerms('children\u2019s').q, "children's");
});

// ---- Matching text ----

const found = (text, query) => textMatches(text, searchTerms(query).q);

test('accents are ignored in the query and in the text', () => {
  assert.equal(foldText('Men\u00e9ndez'), 'menendez');
  assert.equal(foldText('ANCH\u00cdA'), 'anchia');
  assert.equal(foldText('Pe\u00f1a'), 'pena');
  assert.ok(found('Men\u00e9ndez', 'Menendez'));
  assert.ok(found('Menendez', 'men\u00e9ndez'));
  assert.ok(found('Mene\u0301ndez', 'Menendez'));  // accent as a separate combining mark
});

test('curly and straight quotes are the same', () => {
  assert.ok(found("children's health", 'children\u2019s'));
  assert.ok(found('children\u2019s health', "children's"));
  assert.equal(foldText('\u201cquoted\u201d'), '"quoted"');
});

test('an ampersand matches with or without spaces around it', () => {
  for (const query of ['A&M', 'A & M', 'a &m', 'A&  M'])
    for (const text of ['Texas A&M University', 'Texas A & M University'])
      assert.ok(found(text, query), `${query} in ${text}`);
});

test('every word must appear, in any order', () => {
  assert.ok(found('Cook, Molly', 'Molly Cook'));
  assert.ok(found('Relating to a school district tax', 'district school'));
  assert.ok(found('Relating to a school district tax', 'tax school'));
  assert.ok(!found('Relating to a school district tax', 'school water'));
  assert.ok(!found('Relating to a school district tax', 'water'));
});

test('double quotes keep words together and in order', () => {
  assert.ok(found('a school district tax', '"school district"'));
  assert.ok(!found('a school district tax', '"district school"'));
  assert.ok(found('a school district tax', '"school district" tax'));
  assert.ok(!found('a school district tax', '"school district" water'));
  assert.ok(found('a school district tax', '\u201cschool district\u201d'));  // curly double quotes work too
});

test('a quote still being typed does not blank the results', () => {
  assert.ok(found('abc', ''));
  assert.ok(found('abc', '"'));
  assert.ok(found('abc', '""'));
  assert.ok(found('a school district tax', '"school'));
  assert.ok(found('a school district tax', '"school dist'));
  assert.ok(!found('a school district tax', '"district sch'));
  assert.ok(found('a school district tax', 'tax "school dist'));
});

test('a plural also finds its singular', () => {
  assert.ok(found('the minimum wage', 'wages'));
  assert.ok(found('a public school', 'schools'));
  assert.ok(found('a property tax', 'taxes'));
  assert.ok(found('one county', 'counties'));
  assert.ok(found('a church', 'churches'));
  assert.ok(found('school buses', 'bus'));     // a singular finds its plural because it is inside it
  assert.ok(!found('a glass door', 'class'));  // "ss" is not a plural ending
  assert.ok(!found('the state', 'status'));    // nor is "us"
  assert.ok(!found('gas', 'has'));             // short words are left alone
});

test('matching is plain text, never a pattern', () => {
  assert.ok(!found('wage school', 'wage|school'));
  assert.ok(!found('anything', '.*'));
  assert.ok(found('Sec. 62.051(a)', '62.051(a)'));
});

// ---- The query in the address bar ----

const TRICKY = ['minimum wage', 'A&M', '50%', 'a+b', '#', '?', '=', '&', '%20', '%', "children's", 'children\u2019s',
  'Men\u00e9ndez', '<img src=x onerror=alert(1)>', '"quoted"', 'a/b', 'a\\b', 'Cook, Molly', 'H.B. No. 110', '  padded  '];

test('a query survives the address bar unchanged', () => {
  for (const query of TRICKY) {
    const hash = buildHash('all', {query});
    assert.equal(parseHash(hash).filters.query, query, hash);
    assert.equal(parseHash(hash).view, 'all');
  }
});

test('a query never leaks into another parameter', () => {
  const parsed = parseHash(buildHash('all', {query: 'x&chamber=Senate&bill=HB1&list=HB2'}));
  assert.equal(parsed.filters.query, 'x&chamber=Senate&bill=HB1&list=HB2');
  assert.equal(parsed.filters.chamber, undefined);
  assert.equal(parsed.bill, null);
  assert.equal(parsed.list, null);
});

test('an empty query is left out of the address', () => {
  assert.equal(buildHash('all', {query: ''}), '#all');
  assert.equal(parseHash('#all').filters.query, undefined);
  assert.equal(parseHash('#all').hasFilters, false);
});

test('the query is kept beside other filters and an open bill', () => {
  const hash = buildHash('all', {query: 'wage', chamber: 'House', sort: 'number'}, {bill: 'HB110'});
  const parsed = parseHash(hash);
  assert.deepEqual(parsed.filters, {query: 'wage', chamber: 'House', sort: 'number'});
  assert.equal(parsed.bill, 'HB110');
});

test('the watchlist carries its own query; other views carry none', () => {
  assert.equal(buildHash('watchlist', {query: 'wage'}), '#watchlist?query=wage');
  for (const view of ['today', 'following', 'local', 'agencies', 'review', 'method', 'saving', 'data'])
    assert.equal(buildHash(view, {query: 'wage'}), `#${view}`);
});

test('a query from the address is cut at 200 characters', () => {
  const parsed = parseHash(`#all?query=${'x'.repeat(250)}`);
  assert.equal(parsed.filters.query.length, 200);
});

test('a remembered query longer than 200 characters is dropped, not cut', () => {
  assert.deepEqual(cleanFilters({query: 'x'.repeat(201)}), {});
  assert.deepEqual(cleanFilters({query: 'x'.repeat(200)}), {query: 'x'.repeat(200)});
  assert.deepEqual(cleanFilters({query: 42}), {});
});

test('a plus sign or a pre-encoded space in a hand-written address reads as a space', () => {
  assert.equal(parseHash('#all?query=minimum+wage').filters.query, 'minimum wage');
  assert.equal(parseHash('#all?query=minimum%20wage').filters.query, 'minimum wage');
});
