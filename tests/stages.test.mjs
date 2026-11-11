import assert from 'node:assert/strict';
import test from 'node:test';

// Minimal DOM so the render helpers run under plain node.
class El {
    constructor(tag) { this.tag = tag; this.children = []; this.className = ''; this._text = ''; }
    set textContent(v) { this._text = String(v); this.children = []; }
    get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
    append(...items) { items.forEach(i => this.children.push(typeof i === 'string' ? {textContent: i, tag: '#text', children: []} : i)); }
    all(tag) { return this.children.flatMap(c => [...(c.tag === tag ? [c] : []), ...(c.all ? c.all(tag) : [])]); }
}
globalThis.document = {createElement: tag => new El(tag)};

const {validChanges, renderChanges, witnessSummary, renderHearing, validFiscal, renderFiscal} = await import('../src/review.js');

const index = {bill_id: 'HB1', versions: [{code: 'I', name: 'Introduced', sha256: 'aaa'}, {code: 'E', name: 'Engrossed', sha256: 'bbb'}]};
const changes = {format: 'texas-bill-luna-changes-v1', bill_id: 'HB1', from_version: 'I', to_version: 'E', text_sha256: 'bbb',
    changes: [{kind: 'added', label: 'New fee', explanation: 'Adds a fee.', quotes: ['a fee']}]};

test('validChanges accepts matching and rejects wrong format, bill, sha, version', () => {
    assert.equal(validChanges(changes, 'HB1', index), true);
    assert.equal(validChanges({...changes, format: 'x'}, 'HB1', index), false);
    assert.equal(validChanges({...changes, bill_id: 'HB2'}, 'HB1', index), false);
    assert.equal(validChanges({...changes, text_sha256: 'aaa'}, 'HB1', index), false);
    assert.equal(validChanges({...changes, to_version: 'I'}, 'HB1', index), false);
    assert.equal(validChanges(changes, 'HB1', null), false);
});

test('renderChanges names versions and shows badge', () => {
    const el = renderChanges(changes, index);
    assert.match(el.textContent, /Changes from Introduced to Engrossed/);
    assert.match(el.textContent, /Added/);
    assert.equal(el.all('details').length, 1);
});

const w = (position, testified, name = 'N', organization = '') => ({name, organization, position, testified, hearing: ''});

test('witnessSummary counts positions and testified/registered separately', () => {
    const s = witnessSummary([w('for', true), w('for', false), w('against', true), w('on', false), {position: 'bad'}]);
    assert.deepEqual([s.for, s.against, s.on, s.testified, s.registered], [2, 1, 1, 2, 2]);
});

const payload = (chamber, extra = {}) => ({format: 'texas-bill-witnesses-v1', bill: 'HB1', chamber, source: 'ftp://ftp.legis.state.tx.us/x.xml',
    committee: 'Finance', hearing: 'Mar 1', hearings: [], witnesses: [w('for', true, 'Ann', 'Acme'), w('against', false, 'Bob')], ...extra});

test('renderHearing with only S payload', () => {
    const el = renderHearing([null, payload('S')]);
    assert.match(el.textContent, /Senate · Finance/);
    assert.match(el.textContent, /1 for · 1 against · 0 on/);
    assert.match(el.textContent, /1 testified, 1 registered/);
    assert.match(el.textContent, /Ann — Acme/);
    assert.match(el.textContent, /Registered, not testifying \(1\)/);
    assert.match(el.textContent, /Testimony content is not recorded/);
    assert.equal(el.all('a').length, 1);
});

test('renderHearing returns null with no valid payload and rejects non-legis link', () => {
    assert.equal(renderHearing([null, null]), null);
    assert.equal(renderHearing([{...payload('H'), format: 'bad'}]), null);
    const el = renderHearing([payload('H', {source: 'https://evil.example/x'})]);
    assert.equal(el.all('a').length, 0);
});

const current = {text_version: 'E', text_sha256: 'bbb'};
const fiscal = {format: 'texas-bill-luna-fiscal-v1', bill_id: 'HB1', text_version: 'E', text_sha256: 'bbb',
    documents: [{id: 'd', type: 'fiscal_note', code: 'E', sha256: 'z'}], no_fiscal_implication: false, agencies: [], disagreements: []};

test('validFiscal rejects stale version, sha, bill and missing current', () => {
    assert.equal(validFiscal(fiscal, 'HB1', current), true);
    assert.equal(validFiscal(fiscal, 'HB1', {...current, text_version: 'I'}), false);
    assert.equal(validFiscal(fiscal, 'HB1', {...current, text_sha256: 'zzz'}), false);
    assert.equal(validFiscal(fiscal, 'HB2', current), false);
    assert.equal(validFiscal(fiscal, 'HB1', null), false);
});

test('renderFiscal omits absent summary, shows no-implication text, marks in_review false', () => {
    const bare = renderFiscal(fiscal, 'HB1');
    assert.doesNotMatch(bare.textContent, /no significant/);
    assert.match(bare.textContent, /not an official finding/);
    assert.match(bare.textContent, /Fiscal note \(text\)/);
    const none = renderFiscal({...fiscal, no_fiscal_implication: true}, 'HB1');
    assert.match(none.textContent, /The fiscal note reports no significant fiscal implication\./);
    const full = renderFiscal({...fiscal, summary: {text: 'Costs $1.', quotes: []},
        agencies: [{name: 'TxDOT', registry_id: 'x', in_review: false, fiscal_effect: 'Cost', quotes: []}],
        disagreements: [{claim: 'Claim', note: 'n', quotes: []}]}, 'HB1');
    assert.match(full.textContent, /Costs \$1\./);
    assert.match(full.textContent, /not in Luna's review/);
    assert.match(full.textContent, /Fiscal note differs: Claim/);
});
