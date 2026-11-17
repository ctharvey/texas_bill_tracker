import test from 'node:test';
import assert from 'node:assert/strict';
import {ART_FORMAT, bannerOn, artEntries, artBanner} from '../src/features/art/view.js';

const ART = artEntries({format: ART_FORMAT, bills: {HB309: {v: '15f6772a2183', alt: 'A warbler'}, HB5: {v: 'abcdef12'}}});
const ON = {bill_art_banner: true};

test('the banner is off unless the server flag is exactly true', () => {
  for (const flags of [null, undefined, {}, {bill_art_banner: 'true'}, {bill_art_banner: 1}, [], 'on']) {
    assert.equal(bannerOn(flags), false, JSON.stringify(flags));
    assert.equal(artBanner('HB309', 'HB 309', flags, ART), '');
  }
  assert.equal(bannerOn(ON), true);
});

test('with the flag on, a bill with art gets its image, alt text and caption', () => {
  const html = artBanner('HB309', 'HB 309', ON, ART);
  assert.match(html, /^<figure class="bill-art"><img src="\.\/live\/og\/art\/HB309\.jpg\?v=15f6772a2183"/);
  assert.match(html, /alt="A warbler"/);
  assert.match(html, /<figcaption>Illustration for this bill, made with a local image model\.<\/figcaption><\/figure>$/);
  assert.match(artBanner('HB5', 'HB 5', ON, ART), /alt="Illustration for HB 5"/);
});

test('a bill without art, or with no art list, gets no banner', () => {
  assert.equal(artBanner('HB6', 'HB 6', ON, ART), '');
  assert.equal(artBanner('HB309', 'HB 309', ON, null), '');
  assert.equal(artBanner('toString', 'x', ON, ART), '');
  assert.equal(artBanner('constructor', 'x', ON, {}), '');
});

test('the art list drops a wrong format, bad ids and bad versions', () => {
  assert.deepEqual(artEntries(null), {});
  assert.deepEqual(artEntries({format: 'other', bills: {HB5: {v: 'abcdef12'}}}), {});
  assert.deepEqual(artEntries({format: ART_FORMAT, bills: []}), {});
  const got = artEntries({format: ART_FORMAT, bills: {
    HB5: {v: 'abcdef12', alt: 7}, '../x': {v: 'abcdef12'}, HB0: {v: 'abcdef12'}, HB6: {v: 'NOTHEX!'}, HB7: {v: 'abc'}, HB8: null}});
  assert.deepEqual(got, {HB5: {v: 'abcdef12', alt: ''}});
});

test('alt text is escaped', () => {
  const art = artEntries({format: ART_FORMAT, bills: {HB5: {v: 'abcdef12', alt: '"><script>x</script>'}}});
  const html = artBanner('HB5', 'HB 5', ON, art);
  assert.ok(!html.includes('<script>'));
  assert.match(html, /alt="&quot;&gt;&lt;script&gt;/);
});
