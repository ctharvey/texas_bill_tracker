// Draw share card PNGs (live/og/<ID>.png) for bills whose card changed. Run hourly by texas-bill-og.service after
// the data run writes live/og/cards.json; the share pages (build_feeds.py) link an image only once
// live/og/rendered.json lists it, so a link never points at a file that is not there.
//   node scripts/build_og.mjs --cards live/og/cards.json --out live/og [--max 2000] [--only HB1,SB2]
import {readFileSync, writeFileSync, renameSync, unlinkSync, mkdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {BILL_ID, WIDTH, cardTree, planRun} from './og_card.mjs';

const RENDERED_FORMAT = 'texas-bill-og-rendered-v1', CARDS_FORMAT = 'texas-bill-og-cards-v1';
// Illustrations ship with the code (both units archive scripts/); build_feeds.py puts their hash in a card's `art`.
const ART_DIR = join(dirname(fileURLToPath(import.meta.url)), 'og_art'), ART_MAX_BYTES = 2_000_000;

// The bill's illustration as a data: URL, or null (navy card) when the card has none or the file is not in this
// commit; a missing file heals on the next data run, whose `art` then disappears and changes `v`.
function artFor(id, card) {
  if (!card.art || !BILL_ID.test(id)) return null;
  try {
    const data = readFileSync(join(ART_DIR, `${id}.jpg`));
    if (data.length > ART_MAX_BYTES) throw Error(`${id}.jpg is over ${ART_MAX_BYTES} bytes`);
    return 'data:image/jpeg;base64,' + data.toString('base64');
  } catch (e) {
    if (e.code !== 'ENOENT') throw e;
    console.error(`${id}: card names art but ${id}.jpg is missing; drawing the plain card`);
    return null;
  }
}

function args(argv) {
  const out = {max: 2000, only: null};
  for (let i = 0; i < argv.length; i += 2) {
    const [k, v] = [argv[i], argv[i + 1]];
    if (k === '--cards') out.cards = v; else if (k === '--out') out.out = v;
    else if (k === '--max') out.max = Number(v); else if (k === '--only') out.only = new Set(v.split(','));
    else throw Error(`Unknown argument ${k}`);
  }
  if (!out.cards || !out.out || !(out.max >= 0)) throw Error('Usage: build_og.mjs --cards FILE --out DIR [--max N] [--only IDS]');
  return out;
}

const readJson = path => { try { return JSON.parse(readFileSync(path, 'utf8')); } catch { return null; } };
// Temp file + rename: the gateway never serves a half-written file.
function writeAtomic(path, data) {
  const tmp = `${path}.tmp-${process.pid}`;
  writeFileSync(tmp, data);
  renameSync(tmp, path);
}

function fonts() {
  const require = createRequire(import.meta.url);
  const file = (pkg, name) => readFileSync(join(dirname(require.resolve(`${pkg}/package.json`)), 'files', name));
  return [
    {name: 'Manrope', weight: 800, style: 'normal', data: file('@fontsource/manrope', 'manrope-latin-800-normal.woff')},
    {name: 'DM Sans', weight: 400, style: 'normal', data: file('@fontsource/dm-sans', 'dm-sans-latin-400-normal.woff')},
    {name: 'DM Sans', weight: 500, style: 'normal', data: file('@fontsource/dm-sans', 'dm-sans-latin-500-normal.woff')},
    {name: 'DM Sans', weight: 600, style: 'normal', data: file('@fontsource/dm-sans', 'dm-sans-latin-600-normal.woff')},
  ];
}

async function main() {
  const opt = args(process.argv.slice(2));
  const doc = readJson(opt.cards);
  if (doc?.format !== CARDS_FORMAT || !doc.bills || typeof doc.bills !== 'object') throw Error(`${opt.cards}: not ${CARDS_FORMAT}`);
  mkdirSync(opt.out, {recursive: true});
  const manifestPath = join(opt.out, 'rendered.json');
  const prior = readJson(manifestPath);
  const rendered = prior?.format === RENDERED_FORMAT && prior.bills && typeof prior.bills === 'object' ? {...prior.bills} : {};
  const cards = opt.only ? Object.fromEntries(Object.entries(doc.bills).filter(([id]) => opt.only.has(id))) : doc.bills;
  const plan = planRun(cards, rendered, opt.max);
  if (opt.only) plan.remove = [];  // A partial run never removes anything.
  const save = () => writeAtomic(manifestPath, JSON.stringify({format: RENDERED_FORMAT, bills: rendered}) + '\n');

  for (const id of plan.remove) {
    if (!BILL_ID.test(id)) continue;
    try { unlinkSync(join(opt.out, `${id}.png`)); } catch (e) { if (e.code !== 'ENOENT') throw e; }
    delete rendered[id];
  }
  let drawn = 0;
  if (plan.draw.length) {
    // resvg's WASM build, freed after each card: the native @resvg/resvg-js 2.6.2 kept about 3.5 MB per render
    // until the process ended, which a GC did not release (the VPS run was killed at 512 MB after ~290 cards).
    const [{default: satori}, {initWasm, Resvg}] = await Promise.all([import('satori'), import('@resvg/resvg-wasm')]);
    const require = createRequire(import.meta.url);
    await initWasm(readFileSync(require.resolve('@resvg/resvg-wasm/index_bg.wasm')));
    const fontList = fonts(), started = Date.now();
    for (const id of plan.draw) {
      const card = cards[id];
      const svg = await satori(cardTree(card, artFor(id, card)), {width: WIDTH, height: 630, fonts: fontList});
      // Satori draws glyphs as paths, so resvg needs no fonts.
      const resvg = new Resvg(svg, {fitTo: {mode: 'width', value: WIDTH}});
      const image = resvg.render();
      const png = image.asPng();
      image.free();
      resvg.free();
      writeAtomic(join(opt.out, `${id}.png`), png);
      rendered[id] = card.v;
      if (++drawn % 100 === 0) save();  // A killed run keeps what it drew.
    }
    console.log(`Drew ${drawn} cards in ${((Date.now() - started) / 1000).toFixed(1)} s`);
  }
  save();
  console.log(`Share cards: ${drawn} drawn, ${plan.waiting} waiting for the next run, ${plan.remove.length} removed`);
}

main().catch(error => { console.error(error.message); process.exit(1); });
