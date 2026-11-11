import test from 'node:test';
import assert from 'node:assert/strict';
import {aiPrompt, agentUrl, cardClickOpens, openLinkHtml, chicagoDate, activityOn, latestActivityDay, topicCounts, groupByActionType, pageAiText, AI_LIST_LIMIT, companionLabel, agencyViaCompanion, companionIndex} from '../src/taxonomy.js';
import {parseHash, buildHash, VIEWS} from '../src/prefs.js';

const bill = (id, extra = {}) => ({id, number: id.replace(/^([A-Z]+)/, '$1 '), title: `Title of ${id}`, topics: [], last_action: '11/10/2026 H Filed', last_action_date: '2026-11-10', ...extra});

test('aiPrompt names the bill, both URLs and one neutral instruction', () => {
  const text = aiPrompt(bill('HB5'));
  assert.match(text, /^Texas HB 5 \(90th Legislature\): Title of HB5/);
  assert.ok(text.includes('https://agent.bills.ctharvey.me/bills/HB5.md'));
  assert.ok(text.includes('https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill=HB5'));
  assert.ok(text.endsWith('Summarize what this bill does, who it affects, and its current status, citing the bill text.'));
  assert.equal(agentUrl(bill('SJR9')), 'https://agent.bills.ctharvey.me/bills/SJR9.md');
});

test('aiPrompt links the latest text version when there is one', () => {
  const versions = [{code: 'I', name: 'Introduced', html: 'https://tlc.example/HB00005I.HTM'}, {code: 'H', name: 'Committee Report', html: 'https://tlc.example/HB00005H.HTM'}];
  const text = aiPrompt(bill('HB5', {text_versions: versions}));
  assert.ok(text.includes('Official bill text (Committee Report): https://tlc.example/HB00005H.HTM'));
  assert.ok(!text.includes('History.aspx'));
  assert.ok(aiPrompt(bill('HB5', {text_versions: [{code: 'I', html: 'javascript:alert(1)'}]})).includes('History.aspx'));
  assert.ok(aiPrompt(bill('HB5', {text_versions: []})).includes('History.aspx'));
});

test('cardClickOpens ignores controls, selections and modified clicks', () => {
  assert.equal(cardClickOpens(), true);
  assert.equal(cardClickOpens({interactive: true}), false);
  assert.equal(cardClickOpens({selection: 'some words'}), false);
  assert.equal(cardClickOpens({selection: '  '}), true);
  assert.equal(cardClickOpens({button: 1}), false);
  for (const key of ['metaKey', 'ctrlKey', 'shiftKey', 'altKey']) assert.equal(cardClickOpens({[key]: true}), false);
});

test('openLinkHtml carries data-open and an escaped hash href', () => {
  const html = openLinkHtml('HB5', buildHash('all', {}, {bill: 'HB5'}), 'bill-title-link', 'Water <&> "rules"');
  assert.equal(html, '<a class="bill-title-link" href="#all?bill=HB5" data-open="HB5">Water &lt;&amp;&gt; &quot;rules&quot;</a>');
});

test('chicagoDate uses America/Chicago around midnight', () => {
  assert.equal(chicagoDate('2026-11-12T05:30:00Z'), '2026-11-11');
  assert.equal(chicagoDate('2026-11-12T06:30:00Z'), '2026-11-12');
  assert.equal(chicagoDate(new Date('2026-07-01T04:59:00Z')), '2026-06-30');  // CDT, UTC-5
  assert.equal(chicagoDate('2026-11-09'), '2026-11-09');
  assert.equal(chicagoDate('nonsense'), '');
});

test('activityOn uses action_dates when present, else last_action_date', () => {
  const dated = bill('HB1', {actions: ['Filed', 'Referred to State Affairs'], action_dates: ['2026-11-09', '2026-11-10'], last_action: '11/10/2026 H Referred to State Affairs', last_action_date: '2026-11-10'});
  const undated = bill('HB2', {actions: ['Filed', 'Referred to Calendars'], last_action: '11/10/2026 H Referred to Calendars'});
  const old = bill('HB3', {last_action: '11/01/2026 H Filed', last_action_date: '2026-11-01'});
  const on10 = activityOn([dated, undated, old], '2026-11-10');
  assert.deepEqual(on10.map(r => [r.bill.id, r.actions]), [['HB1', ['Referred to State Affairs']], ['HB2', ['Referred to Calendars']]]);
  assert.deepEqual(activityOn([dated, undated, old], '2026-11-09').map(r => [r.bill.id, r.actions]), [['HB1', ['Filed']]]);
  assert.deepEqual(activityOn([dated], '2026-11-08'), []);
  // action_dates that do not line up with actions are ignored.
  const skewed = bill('HB4', {actions: ['a', 'b'], action_dates: ['2026-11-01'], last_action_date: '2026-11-10'});
  assert.equal(activityOn([skewed], '2026-11-01').length, 0);
  assert.equal(activityOn([skewed], '2026-11-10').length, 1);
});

test('latestActivityDay falls back to the most recent day on or before today', () => {
  const bills = [bill('HB1', {last_action_date: '2026-11-05'}), bill('HB2', {last_action_date: '2026-11-09'}), bill('HB3', {last_action_date: '2026-11-20'})];
  assert.equal(latestActivityDay(bills, '2026-11-11'), '2026-11-09');
  assert.equal(latestActivityDay(bills, '2026-11-05'), '2026-11-05');
  assert.equal(latestActivityDay(bills, '2026-10-01'), null);
  assert.equal(latestActivityDay([], '2026-11-11'), null);
});

test('topicCounts sorts by count then name', () => {
  const bills = [bill('HB1', {topics: ['Taxes', 'Education']}), bill('HB2', {topics: ['Education', 'Education']}), bill('HB3', {topics: ['Healthcare']}), bill('HB4', {})];
  assert.deepEqual(topicCounts(bills), [{topic: 'Education', count: 2}, {topic: 'Healthcare', count: 1}, {topic: 'Taxes', count: 1}]);
});

test('groupByActionType groups by latest matched action, filed after referred', () => {
  const rows = [{bill: bill('HB1'), actions: ['Filed']}, {bill: bill('HB2'), actions: ['Filed', 'Referred to State Affairs']}, {bill: bill('HB3'), actions: ['Something odd']}];
  const groups = groupByActionType(rows);
  assert.deepEqual(groups.map(g => [g.key, g.rows.map(r => r.bill.id)]), [['referred', ['HB2']], ['filed', ['HB1']], ['other', ['HB3']]]);
});

test('the today view round-trips through the address', () => {
  assert.ok(VIEWS.includes('today'));
  assert.equal(parseHash('#today').view, 'today');
  assert.equal(buildHash('today', {}), '#today');
  const p = parseHash('#today?bill=hb5');
  assert.deepEqual([p.view, p.bill], ['today', 'HB5']);
  assert.equal(buildHash('today', {}, {bill: 'HB5'}), '#today?bill=HB5');
});

test('pageAiText: an open bill copies that bill', () => {
  assert.equal(pageAiText({view: 'all', bill: bill('HB5'), bills: [bill('SB1')]}), aiPrompt(bill('HB5')));
});

test('pageAiText: a filtered list names its filters, an equivalent search link and each bill', () => {
  const text = pageAiText({view: 'all', label: 'Bill explorer', pageUrl: 'https://bills.ctharvey.me/#all?topic=Taxes',
    bills: [bill('HB5', {headline: 'Cuts a tax.'})], filters: {topic: 'Taxes', agency: 'tea', chamber: ''}, agencyName: id => id.toUpperCase()});
  assert.match(text, /^Texas Bill Atlas \(90th Legislature\): Bill explorer \(topic Taxes, agency TEA\)/);
  assert.ok(text.includes('Page: https://bills.ctharvey.me/#all?topic=Taxes'));
  assert.ok(text.includes('Same list, AI-readable: https://agent.bills.ctharvey.me/search?topic=Taxes&agency=tea'));
  assert.ok(text.includes('- HB 5: Title of HB5 | In brief: Cuts a tax. | Last action:'));
  assert.ok(text.includes('https://agent.bills.ctharvey.me/bills/HB5.md'));
});

test('pageAiText: long lists are capped and point to the rest', () => {
  const bills = Array.from({length: AI_LIST_LIMIT + 3}, (_, i) => bill(`HB${i + 1}`));
  const text = pageAiText({view: 'today', label: 'Today', day: '2026-11-10', pageUrl: 'u', bills, filters: {}});
  assert.match(text, /Today for 2026-11-10/);
  assert.equal(text.split('\n').filter(l => l.startsWith('- HB')).length, AI_LIST_LIMIT);
  assert.ok(text.includes('...and 3 more (open the page link for the rest).'));
  assert.ok(!text.includes('search?'));
});

test('companions: label, agency-via-companion and both copy texts', () => {
  assert.equal(companionLabel({id: 'HB234', relation: 'Identical'}), 'HB 234 (identical)');
  const senate = bill('SB108', {agencies: [{id: 'ers'}], companions: [{id: 'HB234', author: 'Bucy', relation: 'Identical'}]});
  const house = bill('HB234', {agencies: []}), other = bill('HB690', {agencies: [{id: 'ers'}]});
  const index = companionIndex([senate, house, other]);
  const via = agencyViaCompanion([senate, house, other], 'ers', index);
  assert.deepEqual([...via], [['HB234', ['SB108']]]);
  assert.equal(agencyViaCompanion([senate, house, other], 'tea', index).size, 0);
  assert.ok(aiPrompt(senate, index.get('SB108')).includes('Companion bill HB 234 (identical): https://agent.bills.ctharvey.me/bills/HB234.md'));
  const text = pageAiText({view: 'all', label: 'Bill explorer', pageUrl: 'u', bills: [senate, house], filters: {agency: 'ers'},
    companions: id => index.get(id) || [], via});
  assert.ok(text.split('\n').find(l => l.startsWith('- SB 108')).includes('| Companion: HB 234 (identical) |'));
  assert.ok(text.split('\n').find(l => l.startsWith('- HB 234')).includes('| Listed because its companion SB 108 is tagged with this agency |'));
  assert.ok(text.includes('Bills tagged with this agency directly (companions not added), AI-readable: https://agent.bills.ctharvey.me/search?agency=ers'));
});

test('pageAiText: reference views link their agent page', () => {
  const text = pageAiText({view: 'agencies', pageUrl: 'u'});
  assert.ok(text.includes('AI-readable version: https://agent.bills.ctharvey.me/agencies/index.md'));
});
