import test from 'node:test';
import assert from 'node:assert/strict';
import {shareUrl, parseLocation} from '../src/prefs.js';

const ORIGIN = 'https://billatlas.org';

test('shareUrl adds the drawn card version so a redrawn card is a new address', () => {
  assert.equal(shareUrl(ORIGIN, 'HB486', '52c122380bfa'), 'https://billatlas.org/bill/HB486?c=52c122380bfa');
});

test('shareUrl falls back to the plain link without a usable version', () => {
  for (const v of [undefined, null, '', 'abc', 'NOT-HEX!', 42, '52c1<script>']) {
    assert.equal(shareUrl(ORIGIN, 'HB486', v), 'https://billatlas.org/bill/HB486');
  }
});

test('shareUrl refuses anything that is not a bill id', () => {
  assert.equal(shareUrl(ORIGIN, '../evil', '52c122380bfa'), null);
  assert.equal(shareUrl(ORIGIN, undefined, '52c122380bfa'), null);
});

test('the app opens the bill from a versioned share link (the query is ignored)', () => {
  const url = new URL(shareUrl(ORIGIN, 'HB486', '52c122380bfa'));
  assert.equal(parseLocation(url.pathname, url.hash).bill, 'HB486');
});
