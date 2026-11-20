// The page head the app writes after in-app moves (SEO chunk 6), in the format scripts/page_head.py and
// scripts/build_feeds.py give the static pages: tests/fixtures/page_heads.json holds cases both sides must produce.
// The static head is the indexed one, so the app leaves the head of the page it took over alone (holdHead) until the
// reader moves to another address. Pure apart from writeHead, so the node tests can import this file directly.

export const SITE_NAME = 'Texas Bill Atlas';
// index.html's <title> and description, which are home's head (tests/head.test.mjs keeps them equal).
export const HOME_TITLE = 'Texas Bill Atlas · 90th Legislature';
export const HOME_DESCRIPTION = 'An independent, source-linked tracker for Texas\'s 90th Legislature, with policy and agency impacts and transparent advancement signals.';
export const SITE_CARD = 'https://billatlas.org/social-card.png';
const TITLE_MAX = 70, DESCRIPTION_MAX = 200;  // build_feeds SHARE_TITLE_MAX, SHARE_DESCRIPTION_MAX.
const SMALL_WORDS = new Set(['of', 'and', 'the', 'for', 'to', 'in', 'by', 'or', 'a', 'an', 'on', 'with', 'under', 'from', 'as', 'at']);

const squash = text => String(text ?? '').split(/\s+/).filter(Boolean).join(' ');

// build_feeds.clip: cut at a word before `limit`, with an ellipsis.
export function clip(text, limit) {
  const s = squash(text);
  if (s.length <= limit) return s;
  const head = s.slice(0, limit - 1), space = head.lastIndexOf(' ');
  return (space > 0 ? head.slice(0, space) : head).replace(/[ ,;:]+$/, '') + '…';
}

// build_feeds.title_case: "OFFENSES AGAINST THE PERSON" -> "Offenses Against the Person".
export const titleCase = heading => squash(heading).split(' ').filter(Boolean)
  .map((w, i) => i && SMALL_WORDS.has(w.toLowerCase()) ? w.toLowerCase()
    : w.replace(/[A-Za-z]+/g, m => m[0].toUpperCase() + m.slice(1).toLowerCase())).join(' ');

export const fullTitle = title => `${title} · ${SITE_NAME}`;

// Each returns {title, description} (description null: the caller keeps the route's).
export function billHead(number, caption, headline) {
  const c = squash(caption) || 'No caption available';
  return {title: clip(`${number}: ${c}`, TITLE_MAX), description: clip(headline ? `AI summary: ${squash(headline)}` : c, DESCRIPTION_MAX)};
}
export const memberHead = name => ({title: clip(name, TITLE_MAX), description: null});
export function groupHead(kind, name) {
  return {title: kind === 'topic' ? `${name}: Texas bills` : clip(`${name}: Texas bills that could affect it`, TITLE_MAX), description: null};
}
// A section: `heading` is the index's heading ("CERTAIN PERSONS INELIGIBLE"), as build_feeds.law_page uses it.
export function lawHead(codeName, code, number, heading) {
  const label = `${codeName} ${code === 'CR' ? 'Art.' : '§'} ${number}`;
  const name = squash(heading).replace(/\.+$/, '').trim();
  return {title: clip(name ? `${label}: ${name}` : label, TITLE_MAX), description: null};
}
export function chapterHead(codeName, chapter, heading) {
  const label = `${codeName} Chapter ${chapter}`, name = titleCase(heading);
  return {title: clip(name ? `${label}: ${name}` : label, TITLE_MAX), description: null};
}
// About pages and Today: the page heading without its full stop.
export const headingHead = heading => ({title: String(heading || '').replace(/\.+$/, ''), description: null});

// The head stays the static page's while the reader is at the address it was served for.
export const holdHead = (heldPath, url) => heldPath !== null && new URL(url, 'https://billatlas.org').pathname === heldPath;

// Title, description, canonical, robots, og and twitter. og:url is the canonical; the card is the site's (a bill's own
// card version is only known to the static page).
export function writeHead(doc, {title, description, canonical, robots}) {
  const meta = (attr, key, content) => {
    let el = doc.querySelector(`meta[${attr}="${key}"]`);
    if (content === null) { el?.remove(); return; }
    if (!el) { el = doc.createElement('meta'); el.setAttribute(attr, key); doc.head.append(el); }
    el.setAttribute('content', content);
  };
  doc.title = title === HOME_TITLE ? title : fullTitle(title);
  const link = doc.querySelector('link[rel="canonical"]');
  if (link) link.href = canonical;
  meta('name', 'robots', robots);
  for (const [attr, key, value] of [['name', 'description', description], ['property', 'og:title', title],
    ['property', 'og:description', description], ['property', 'og:url', canonical], ['property', 'og:image', SITE_CARD],
    ['property', 'og:image:alt', SITE_NAME], ['name', 'twitter:title', title], ['name', 'twitter:description', description],
    ['name', 'twitter:image', SITE_CARD]])
    if (value !== null) meta(attr, key, value);
}
