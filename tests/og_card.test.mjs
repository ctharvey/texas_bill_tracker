import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {clip, captionStyle, chipLabels, planRun, cardTree, posterCaption, WIDTH, HEIGHT} from '../scripts/og_card.mjs';
import {WARBLER_SVG} from '../scripts/og_warbler.mjs';

const words = n => Array.from({length: n}, (_, i) => `word${i}`).join(' ');

test('clip leaves short text alone and collapses whitespace', () => {
  assert.equal(clip('  hello \n  world\t!  ', 50), 'hello world !');
  assert.equal(clip(undefined, 10), '');
});

test('clip cuts long text at a word boundary with an ellipsis within the limit', () => {
  const out = clip('alpha beta, gamma; delta epsilon zeta', 20);
  assert.ok(out.endsWith('…'));
  assert.ok(out.length <= 20);
  assert.equal(out, 'alpha beta, gamma…');
  assert.ok(!/[ ,;:]…$/.test(out), 'trailing separators are stripped before the ellipsis');
  const long = clip(words(100), 60);
  assert.ok(long.length <= 60);
  assert.match(long, /word\d+…$/);
  assert.ok(words(100).startsWith(long.slice(0, -1)), 'cut is a prefix');
  assert.equal(words(100)[long.length - 1], ' ', 'cut falls on a word boundary');
});

test('clip strips trailing separators', () => {
  assert.equal(clip('aaaa, bbbb cccc', 8), 'aaaa…');
});

test('captionStyle picks the size by caption length', () => {
  const size = n => captionStyle('x'.repeat(n)).size;
  assert.equal(size(40), 60);
  assert.equal(size(80), 50);
  assert.equal(size(140), 42);
  assert.equal(size(220), 36);
  assert.equal(size(300), 31);
});

test('captionStyle clips an over-long caption and uses the smallest size', () => {
  const {text, size} = captionStyle(words(120));
  assert.ok(words(120).length > 500);
  assert.ok(text.length <= 330);
  assert.ok(text.endsWith('…'));
  assert.equal(size, 31);
  const exact = captionStyle('y'.repeat(530));
  assert.ok(exact.text.length <= 330);
  assert.equal(exact.size, 31);
});

test('chipLabels keeps whole labels in order while label + 4 fits 84', () => {
  const a = 'a'.repeat(40), b = 'b'.repeat(36);
  assert.deepEqual(chipLabels([a, b]), [a, b]); // 44 + 40 = 84 fits
});

test('chipLabels drops later labels that do not fit instead of clipping them', () => {
  const a = 'a'.repeat(40), b = 'b'.repeat(37), c = 'c';
  assert.deepEqual(chipLabels([a, b, c]), [a]); // 44 + 41 = 85 > 84, and nothing after it is added either
});

test('chipLabels clips a lone over-long first label', () => {
  const out = chipLabels(['z'.repeat(100), 'Tax']);
  assert.equal(out.length, 1);
  assert.ok(out[0].length <= 80);
  assert.ok(out[0].endsWith('…'));
});

test('chipLabels allows at most three labels and tolerates empty input', () => {
  assert.deepEqual(chipLabels(['a', 'b', 'c', 'd', 'e']), ['a', 'b', 'c']);
  assert.deepEqual(chipLabels([]), []);
  assert.deepEqual(chipLabels(undefined), []);
});

const card = (v, active = '') => ({v, active});

test('planRun draws changed and missing cards, most recently active first then by id', () => {
  const cards = {
    HB1: card('n1', '2027-01-01'), HB2: card('same', '2027-03-01'), SB3: card('n3', '2027-03-01'),
    HB4: card('n4', '2027-02-01'), SB1: card('new', '2027-03-01'),
  };
  const rendered = {HB1: 'old', HB2: 'same', SB3: 'old', HB4: 'old'};
  const plan = planRun(cards, rendered);
  assert.deepEqual(plan.draw, ['SB1', 'SB3', 'HB4', 'HB1']);
  assert.equal(plan.waiting, 0);
  assert.deepEqual(plan.remove, []);
});

test('planRun respects max and reports how many are waiting', () => {
  const cards = {HB1: card('a', '2027-01-01'), HB2: card('a', '2027-02-01'), HB3: card('a', '2027-03-01')};
  const plan = planRun(cards, {}, 2);
  assert.deepEqual(plan.draw, ['HB3', 'HB2']);
  assert.equal(plan.waiting, 1);
});

test('planRun removes rendered ids that are no longer cards', () => {
  const plan = planRun({HB1: card('a')}, {HB1: 'a', HB9: 'x', SB2: 'y'});
  assert.deepEqual(plan.draw, []);
  assert.deepEqual(plan.remove.sort(), ['HB9', 'SB2']);
});

test('planRun never wipes when cards is empty', () => {
  assert.deepEqual(planRun({}, {HB1: 'a', SB2: 'b'}).remove, []);
  assert.deepEqual(planRun(undefined, {HB1: 'a'}).remove, []);
});

test('planRun ignores invalid ids and non-string versions', () => {
  const cards = {'../x': card('a'), HB0: card('a'), XX1: card('a'), HB5: {v: 3}, SB6: {}, HB7: card('ok')};
  const plan = planRun(cards, {});
  assert.deepEqual(plan.draw, ['HB7']);
  assert.equal(plan.waiting, 0);
});

test('cardTree carries the card fields at 1200x630', () => {
  const model = {number: 'HB 1234', chamber: 'House', status: 'Referred to committee', byline: 'Filed Nov 9, 2026 · By Smith',
    caption: 'Relating to the unique zebra crossing rules.', subjects: ['Highways'], session: '90th Legislature'};
  const tree = cardTree(model);
  assert.equal(typeof tree, 'object');
  assert.equal(tree.props.style.width, 1200);
  assert.equal(tree.props.style.height, 630);
  assert.equal(WIDTH, 1200);
  assert.equal(HEIGHT, 630);
  const json = JSON.stringify(tree);
  for (const value of [model.number, model.status, model.chamber, model.byline, model.caption, 'Highways']) {
    assert.ok(json.includes(JSON.stringify(value).slice(1, -1)), `tree should contain ${value}`);
  }
});

const POSTER = {number: 'HB 486', chamber: 'House', status: 'Filed', byline: 'Filed Nov 9, 2026 · By Wilson',
  caption: 'Relating to wildlife.', subjects: ['Animals'], session: '90th Legislature'};
const ART = 'data:image/jpeg;base64,AAAA';
const nodes = tree => [tree, ...[tree?.props?.children ?? []].flat().flatMap(c => typeof c === 'object' ? nodes(c) : [])];
// Images on a card: the bill's illustration (a JPEG) and the warbler mark (an SVG).
const MARK = 'data:image/svg+xml;base64,';
const artImages = tree => nodes(tree).filter(n => n.type === 'img' && !n.props.src.startsWith(MARK));
const markImages = tree => nodes(tree).filter(n => n.type === 'img' && n.props.src.startsWith(MARK));

test('posterCaption shrinks longer captions and clips past 150 characters', () => {
  assert.equal(posterCaption('Short.').size, 40);
  assert.equal(posterCaption('x '.repeat(50)).size, 35);
  const long = posterCaption('word '.repeat(80));
  assert.ok(long.text.length <= 150 && long.text.endsWith('…'));
  assert.equal(long.size, 31);
});

test('cardTree with art draws the poster over the image', () => {
  const tree = cardTree(POSTER, ART);
  const imgs = artImages(tree);
  assert.equal(imgs.length, 1);
  assert.equal(imgs[0].props.src, ART);
  const json = JSON.stringify(tree);
  for (const value of ['HB 486', 'Filed', 'Relating to wildlife.', 'billatlas.org', 'Filed Nov 9, 2026']) {
    assert.ok(json.includes(value), `poster should contain ${value}`);
  }
  assert.equal(tree.props.style.width, WIDTH);
  assert.equal(tree.props.style.height, HEIGHT);
});

test('cardTree without art is the plain card, with no illustration', () => {
  assert.deepEqual(cardTree(POSTER, null), cardTree(POSTER));
  assert.equal(artImages(cardTree(POSTER)).length, 0);
});

test('both cards show the warbler mark, the same SVG as design/brand/warbler.svg', () => {
  const brand = readFileSync(new URL('../design/brand/warbler.svg', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
  assert.equal(WARBLER_SVG.replace(/\r\n/g, '\n'), brand);
  for (const tree of [cardTree(POSTER), cardTree(POSTER, ART)]) {
    const marks = markImages(tree);
    assert.equal(marks.length, 1);
    assert.equal(Buffer.from(marks[0].props.src.slice(MARK.length), 'base64').toString('utf8'), WARBLER_SVG);
  }
});
