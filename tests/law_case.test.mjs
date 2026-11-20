// #22: the law copy stores two Code of Criminal Procedure articles with a lower-case letter ("42.04a", "47.01a");
// keys and addresses are upper case, and the app finds the article's text and links it at its upper-case address.
import test from 'node:test';
import assert from 'node:assert/strict';
import {lawCopyUnits} from '../src/features/statutes/model.js';
import {state} from '../src/core/state.js';
import {statuteMarkup} from '../src/features/statutes/view.js';

const tick = () => new Promise(r => setTimeout(r, 0));
const CHAPTER = '# Code of Criminal Procedure, CHAPTER 42. JUDGMENT AND SENTENCE\n\n'
  + '## Art. 42.04. RESTRICTIONS ON PROBATION.\n\nOld article.\n\n'
  + '## Art. 42.04a. ISSUANCE OF MANDATE; JUDGMENTS FINAL.\n\nThe mandate issues when the judgment is final.';
const index = () => ({format: 'texas-bill-statutes-v1', codes: {CR: 'Code of Criminal Procedure'}, sections: {}, chapters: {}, bills: {}});

test('the upper-case key finds the article stored with a lower-case letter, heading and text', () => {
  const units = lawCopyUnits(CHAPTER, '42.04A');
  assert.deepEqual(units.map(u => u.label), ['head', '']);
  assert.equal(units[0].text, 'Art. 42.04a. ISSUANCE OF MANDATE; JUDGMENTS FINAL.');
  assert.match(units[1].text, /The mandate issues/);
  assert.match(lawCopyUnits(CHAPTER, '42.04')[1].text, /Old article/, 'the article without the letter is its own');
});

test('the article page shows its text and the chapter page links it at the upper-case address', async () => {
  state.statutes = index();
  state.searches = [];
  const real = globalThis.fetch;
  globalThis.fetch = async url => String(url).endsWith('/live/law/CR/42.md')
    ? {ok: true, text: async () => CHAPTER, headers: {get: () => ''}} : {ok: false, status: 404};
  try {
    state.view = 'home';
    state.statuteKey = 'CR 42.04A';
    statuteMarkup();
    for (let i = 0; i < 5; i++) await tick();
    assert.match(statuteMarkup(), /The mandate issues when the judgment is final\./);

    state.statuteKey = 'CR 42';
    statuteMarkup();
    for (let i = 0; i < 5; i++) await tick();
    const html = statuteMarkup();
    assert.match(html, /href="\/law\/CR\/42\.04A">Art\. 42\.04a<\/a>/);
    assert.match(html, /href="\/law\/CR\/42\.04">Art\. 42\.04<\/a>/);
  } finally {
    globalThis.fetch = real;
  }
});
