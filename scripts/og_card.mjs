// Share card layout and run planning for scripts/build_og.mjs. No dependencies, so CI tests it without npm packages.
// A card is drawn from one entry of live/og/cards.json (build_feeds.py write_og_cards): display strings only, so the
// fields and their wording live in one place, and `v` changes exactly when the drawn fields do.

export const WIDTH = 1200, HEIGHT = 630;
export const BILL_ID = /^(?:HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9][0-9]{0,4}$/;
const NAVY = '#14243a', GOLD = '#ba822d', TEAL = '#5fc7c2', WHITE = '#ffffff', MUTED = '#9fb0c4', LINE = '#2a3d57';
// The old brand-mark star (viewBox 0 0 24 24), as in design/social/make_images.py; the site's mark is now the warbler.
const STAR = '12,1.6 14.9,8.7 22.5,9.2 16.7,14.1 18.6,21.5 12,17.4 5.4,21.5 7.3,14.1 1.5,9.2 9.1,8.7';

const h = (type, style, ...children) => ({type, props: {style, children: children.flat().filter(c => c !== null && c !== '')}});

export function clip(text, limit) {
  text = String(text ?? '').split(/\s+/).filter(Boolean).join(' ');
  if (text.length <= limit) return text;
  const cut = text.slice(0, limit - 1);
  const word = cut.slice(0, cut.lastIndexOf(' ')) || cut;
  return word.replace(/[ ,;:]+$/, '') + '…';
}

// Caption size by length; each tier fits its character budget in the caption box (checked with real captions).
const CAPTION_TIERS = [[45, 60], [90, 50], [150, 42], [230, 36], [330, 31]];
const CAPTION_MAX = 330;
export function captionStyle(caption) {
  const text = clip(caption, CAPTION_MAX);
  const size = (CAPTION_TIERS.find(([max]) => text.length <= max) || CAPTION_TIERS.at(-1))[1];
  return {text, size};
}

// Chip labels come shortened from build_feeds.py subject_labels. The chip row holds about CHIP_BUDGET characters
// (label plus padding); whole labels are kept in order while they fit, and only a lone over-long first one is clipped.
const CHIP_BUDGET = 84, CHIP_PAD = 4;
export function chipLabels(subjects) {
  const labels = [];
  let used = 0;
  for (const s of (subjects || []).slice(0, 3)) {
    const label = String(s);
    if (used + label.length + CHIP_PAD > CHIP_BUDGET) {
      if (!labels.length) labels.push(clip(label, CHIP_BUDGET - CHIP_PAD));
      break;
    }
    labels.push(label);
    used += label.length + CHIP_PAD;
  }
  return labels;
}

// Poster caption: one wide box on the dark road at the bottom of the art, so a smaller budget than the navy card.
const POSTER_TIERS = [[60, 40], [110, 35], [150, 31]];
const POSTER_MAX = 150;
export function posterCaption(caption) {
  const text = clip(caption, POSTER_MAX);
  const size = (POSTER_TIERS.find(([max]) => text.length <= max) || POSTER_TIERS.at(-1))[1];
  return {text, size};
}

// A bill with an illustration (scripts/og_art/<ID>.jpg, 16:9 print with a light sky and a dark road along the
// bottom): the art fills the card, brand and number sit on the sky, the caption on the road under a dark fade.
function posterTree(card, art) {
  const {text, size} = posterCaption(card.caption);
  const PAPER = '#f6f0dc', INK = '#0e0e0e';
  return h('div', {display: 'flex', width: WIDTH, height: HEIGHT, background: PAPER, fontFamily: 'DM Sans', position: 'relative'},
    {type: 'img', props: {src: art, style: {position: 'absolute', left: -8, top: -5, width: 1216, height: 640}}},
    h('div', {display: 'flex', position: 'absolute', left: 0, top: 0, width: WIDTH, height: HEIGHT,
      backgroundImage: `linear-gradient(180deg, rgba(14,14,14,0) 0%, rgba(14,14,14,0) 52%, rgba(14,14,14,0.75) 70%, ${INK} 84%)`}),
    h('div', {display: 'flex', position: 'absolute', left: 50, top: 40, right: 50, justifyContent: 'space-between', alignItems: 'center'},
      h('div', {display: 'flex', alignItems: 'center'},
        h('div', {display: 'flex', width: 38, height: 38, borderRadius: 8, background: GOLD, alignItems: 'center', justifyContent: 'center'},
          {type: 'svg', props: {width: 26, height: 26, viewBox: '0 0 24 24', children: {type: 'polygon', props: {points: STAR, fill: NAVY}}}}),
        h('div', {display: 'flex', marginLeft: 14, fontFamily: 'Manrope', fontWeight: 800, fontSize: 20, letterSpacing: 4, color: NAVY}, 'TEXAS BILL ATLAS')),
      h('div', {display: 'flex', alignItems: 'center'},
        h('div', {display: 'flex', fontFamily: 'Manrope', fontWeight: 800, fontSize: 64, lineHeight: 1, color: NAVY, letterSpacing: -2}, card.number),
        card.status ? h('div', {display: 'flex', marginLeft: 16, padding: '5px 14px', borderRadius: 999, background: NAVY, color: PAPER,
          fontFamily: 'DM Sans', fontWeight: 600, fontSize: 20, letterSpacing: 0.5}, card.status) : null)),
    h('div', {display: 'flex', flexDirection: 'column', position: 'absolute', left: 50, right: 50, bottom: 34},
      h('div', {display: 'flex', color: PAPER, fontWeight: 500, fontSize: size, lineHeight: 1.22}, text),
      h('div', {display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14},
        h('div', {display: 'flex', color: '#cfc6ad', fontSize: 20}, clip(card.byline, 70)),
        h('div', {display: 'flex', color: '#e2b35a', fontFamily: 'Manrope', fontWeight: 800, fontSize: 28}, 'billatlas.org'))));
}

// `art`: the bill's illustration as a data: URL when it has one (build_og.mjs reads it), else the navy card.
export function cardTree(card, art = null) {
  if (art) return posterTree(card, art);
  const {text, size} = captionStyle(card.caption);
  const pill = (label, bg, fg) => h('div', {display: 'flex', padding: '6px 16px', borderRadius: 999, background: bg, color: fg,
    fontFamily: 'DM Sans', fontWeight: 600, fontSize: 22, letterSpacing: 0.5}, label);
  const chips = chipLabels(card.subjects).map(s => h('div', {display: 'flex', padding: '5px 14px', borderRadius: 8,
    border: `1.5px solid ${LINE}`, color: MUTED, fontFamily: 'DM Sans', fontWeight: 500, fontSize: 21}, s));
  return h('div', {display: 'flex', width: WIDTH, height: HEIGHT, background: NAVY, fontFamily: 'DM Sans'},
    h('div', {display: 'flex', width: 14, height: HEIGHT, background: GOLD}),
    h('div', {display: 'flex', flexDirection: 'column', flexGrow: 1, padding: '52px 70px 40px 70px'},
      h('div', {display: 'flex', alignItems: 'center', justifyContent: 'space-between'},
        h('div', {display: 'flex', alignItems: 'center'},
          h('div', {display: 'flex', width: 46, height: 46, borderRadius: 9, background: GOLD, alignItems: 'center', justifyContent: 'center'},
            {type: 'svg', props: {width: 32, height: 32, viewBox: '0 0 24 24', children: {type: 'polygon', props: {points: STAR, fill: NAVY}}}}),
          h('div', {display: 'flex', marginLeft: 16, fontFamily: 'Manrope', fontWeight: 800, fontSize: 24, letterSpacing: 4, color: GOLD}, 'TEXAS BILL ATLAS')),
        h('div', {display: 'flex', color: MUTED, fontSize: 22}, card.session || '90th Legislature')),
      h('div', {display: 'flex', alignItems: 'center', marginTop: 34},
        h('div', {display: 'flex', fontFamily: 'Manrope', fontWeight: 800, fontSize: 84, lineHeight: 1, color: WHITE, letterSpacing: -2}, card.number),
        h('div', {display: 'flex', marginLeft: 28}, pill(card.chamber, LINE, WHITE)),
        h('div', {display: 'flex', marginLeft: 12}, pill(card.status, TEAL, NAVY))),
      h('div', {display: 'flex', flexGrow: 1, marginTop: 26, color: WHITE, fontWeight: 500, fontSize: size, lineHeight: 1.28}, text),
      chips.length ? h('div', {display: 'flex', gap: 10, marginTop: 18}, chips) : null,
      h('div', {display: 'flex', height: 2, background: LINE, marginTop: 24}),
      h('div', {display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 20},
        h('div', {display: 'flex', color: MUTED, fontSize: 24}, clip(card.byline, 70)),
        h('div', {display: 'flex', color: TEAL, fontFamily: 'Manrope', fontWeight: 800, fontSize: 30}, 'billatlas.org'))));
}

// Which cards to draw this run and which images to remove. Cards whose `v` differs from the last render are drawn,
// most recently active first, at most `max` of them; images of bills no longer in cards.json are removed, but never
// when cards.json is empty (a broken data run must not wipe the folder).
export function planRun(cards, rendered, max = Infinity) {
  const ids = Object.keys(cards || {}).filter(id => BILL_ID.test(id) && typeof cards[id]?.v === 'string');
  const stale = ids.filter(id => rendered?.[id] !== cards[id].v)
    .sort((a, b) => String(cards[b].active || '').localeCompare(String(cards[a].active || '')) || a.localeCompare(b));
  const remove = ids.length ? Object.keys(rendered || {}).filter(id => !(id in cards)) : [];
  return {draw: stale.slice(0, Math.max(0, max)), waiting: Math.max(0, stale.length - Math.max(0, max)), remove};
}
