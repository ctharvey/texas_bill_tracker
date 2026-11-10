import assert from 'node:assert/strict';
import test from 'node:test';
import {parseBillMarkdown, paragraphSegments, validHighlights, sha256Hex, renderBillText} from '../src/billtext.js';

const md = [
    '# HB 1001 - Introduced',
    '90R1865 MP\\-D',
    '### SECTION 1\\.',
    'Sec. 5\\. The board \\[<del>X</del>\\] shall <ins>act \\*now\\*</ins> today\\.',
    '😀 emoji <ins>added</ins> end',
    'Text \\<script\\>alert\\(1\\)\\</script\\> stays.',
].join('\n\n') + '\n';

test('parses title, headings, marks, escapes and plain projection', () => {
    const p = parseBillMarkdown(md);
    assert.equal(p.title, 'HB 1001 - Introduced');
    assert.deepEqual([p.paragraphs[0].heading, p.paragraphs[0].level], [true, 1]);
    assert.deepEqual([p.paragraphs[2].heading, p.paragraphs[2].level, p.paragraphs[2].plain], [true, 3, 'SECTION 1.']);
    assert.equal(p.paragraphs[1].plain, '90R1865 MP-D');
    const body = p.paragraphs[3];
    assert.equal(body.plain, 'Sec. 5. The board [X] shall act *now* today.');
    assert.equal(body.segments.map(s => s.text).join(''), body.plain);
    assert.deepEqual(body.segments.filter(s => s.mark).map(s => [s.mark, s.text]), [['del', 'X'], ['ins', 'act *now*']]);
});

test('bracket projection example', () => {
    const p = parseBillMarkdown('# T\n\n\\[<del>X</del>\\]\n');
    assert.equal(p.paragraphs[1].plain, '[X]');
});

test('script-looking text stays literal text', () => {
    const p = parseBillMarkdown(md);
    assert.equal(p.paragraphs[5].plain, 'Text <script>alert(1)</script> stays.');
    assert.ok(p.paragraphs[5].segments.every(s => s.mark === null));
});

test('nested or unbalanced tags throw', () => {
    assert.throws(() => parseBillMarkdown('# T\n\n<ins>a<del>b</del></ins>\n'));
    assert.throws(() => parseBillMarkdown('# T\n\n<ins>a\n'));
    assert.throws(() => parseBillMarkdown('# T\n\na</del>\n'));
    assert.throws(() => parseBillMarkdown('# T\n\n<ins>a</del>\n'));
});

test('input over 8 MB is rejected', () => {
    assert.throws(() => parseBillMarkdown('a'.repeat(8 * 1024 * 1024 + 1)));
});

test('paragraphSegments splits at mark and range boundaries and keeps ids', () => {
    const p = parseBillMarkdown('# T\n\nab<ins>cdef</ins>gh\n').paragraphs[1];
    const segs = paragraphSegments(p, [{start: 1, end: 4, id: 'a'}, {start: 3, end: 7, id: 'b'}, {start: 5, end: 99, id: 'bad'}]);
    assert.equal(segs.map(s => s.text).join(''), 'abcdefgh');
    assert.deepEqual(segs.map(s => [s.text, s.mark, s.ids]), [
        ['a', null, []], ['b', null, ['a']], ['c', 'ins', ['a']], ['d', 'ins', ['a', 'b']],
        ['ef', 'ins', ['b']], ['g', null, ['b']], ['h', null, []]]);
});

test('non-BMP characters count as one code point', () => {
    const p = parseBillMarkdown('# T\n\n😀a😀b\n').paragraphs[1];
    const segs = paragraphSegments(p, [{start: 1, end: 3, id: 'x'}]);
    assert.deepEqual(segs.map(s => [s.text, s.ids]), [['😀', []], ['a😀', ['x']], ['b', []]]);
});

test('validHighlights checks format, bill, version and sha', () => {
    const h = {format: 'texas-bill-luna-highlights-v1', bill_id: 'HB1', text_version: 'I', text_sha256: 'abc', claims: []};
    assert.equal(validHighlights(h, 'HB1', 'I', 'abc'), true);
    assert.equal(validHighlights({...h, format: 'x'}, 'HB1', 'I', 'abc'), false);
    assert.equal(validHighlights(h, 'HB2', 'I', 'abc'), false);
    assert.equal(validHighlights(h, 'HB1', 'H', 'abc'), false);
    assert.equal(validHighlights(h, 'HB1', 'I', 'def'), false);
    assert.equal(validHighlights(null, 'HB1', 'I', 'abc'), false);
});

test('sha256Hex matches a known digest', async () => {
    assert.equal(await sha256Hex('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
});

test('renderBillText builds DOM without interpreting text', {skip: typeof document === 'undefined'}, () => {
    const root = document.createElement('div');
    renderBillText(root, parseBillMarkdown(md), null);
    assert.equal(root.querySelector('script'), null);
});
