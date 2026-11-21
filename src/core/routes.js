// Every view's address (SEO chunk 2). One table for reading and writing paths, kept as data so the gateway's list
// (chunk 3) and the sitemap (chunk 7) can be checked against it. `indexable` is for the canonical and robots meta:
// personal views and the filterable explorer are not. Names pending the roadmap's open question 1.
// `description` is the meta description of a view with none of its own (core/head.js; home keeps index.html's).
export const ROUTES = [
  {view: 'home', path: '/', indexable: true},
  {view: 'today', path: '/today', indexable: true, description: 'Every Texas bill with a recorded action today, by topic, from the official legislative record.'},
  {view: 'all', path: '/explorer', indexable: false, filters: true, description: 'Search and filter every bill filed in the 90th Texas Legislature by topic, agency, chamber, party and stage.'},
  {view: 'local', path: '/near-you', indexable: false, description: 'Find your Texas House and Senate members and the bills tied to your districts and county.'},
  {view: 'watchlist', path: '/watchlist', indexable: false, filters: true, description: 'Your watchlist of Texas bills, saved in this browser.'},
  {view: 'following', path: '/following', indexable: false, description: 'The legislators, laws and searches you follow, saved in this browser.'},
  {view: 'agencies', path: '/agencies', indexable: true, description: 'Texas state agencies and the bills in the 90th Legislature that could affect each one.'},
  {view: 'laws', path: '/law', indexable: true, description: 'The codes of Texas law, every chapter of each, and the chapters bills in the 90th Legislature would change.'},
  {view: 'review', path: '/review', indexable: true, description: 'How far the full-text reviews of Texas bills have progressed, and what they found.'},
  {view: 'method', path: '/about/method', indexable: true, description: 'How Texas Bill Atlas reads the official record, tags bills and shows hearing progress and author prominence.'},
  {view: 'data', path: '/about/data', indexable: true, description: 'The sources behind Texas Bill Atlas, how fresh they are, and how to import your own lists.'},
  {view: 'saving', path: '/about/saving', indexable: true, description: 'How Texas Bill Atlas saves your watchlist and follows without an account, and how sync links work.'},
  {view: 'export', path: '/about/export', indexable: false, description: 'Download or import your saved Texas Bill Atlas lists.'},
  // Views with a key in the path; `pattern` documents the shape and `match` is the server's test for the canonical
  // form the app writes (prefs.js parses more leniently).
  {view: 'bill', pattern: '/bill/<ID>', match: '^/bill/(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9][0-9]{0,4}$', indexable: true, description: 'A Texas bill in the 90th Legislature: its official history, text, the laws it changes and the agencies it affects.'},
  {view: 'statute', pattern: '/law/<CODE>/<section or chapter>', match: '^/law/[A-Z]{2}/[0-9]+[A-Z]?(\\.[0-9]+[A-Z]?)*$', indexable: true, description: 'A part of Texas law and the bills in the 90th Legislature that would change it.'},
  {view: 'lawcode', pattern: '/law/<CODE>', match: '^/law/[A-Z]{2}$', indexable: true, description: 'Every chapter of a Texas code, with the chapters bills in the 90th Legislature would change.'},
  {view: 'agency', pattern: '/agency/<id>', match: '^/agency/[a-z0-9][a-z0-9-]{0,40}$', indexable: true, description: 'A Texas state agency and the bills in the 90th Legislature that could affect it.'},
  {view: 'topic', pattern: '/topic/<slug>', match: '^/topic/[a-z0-9][a-z0-9-]{0,79}$', indexable: true, description: 'A policy topic and the Texas bills in the 90th Legislature about it.'},
  {view: 'member', pattern: '/member/<code>/<name-slug>', match: '^/member/A[0-9]{3,5}(/[a-z0-9-]{1,60})?$', indexable: true, description: 'A member of the 90th Texas Legislature and the bills they filed.'},
];

const BY_PATH = new Map(ROUTES.filter(r => r.path).map(r => [r.path, r]));
const BY_VIEW = new Map(ROUTES.map(r => [r.view, r]));

// The fixed-path route for a pathname ("/today/" and "/index.html" included), or null.
export function routeForPath(pathname) {
  const path = String(pathname || '');
  if (path === '/index.html') return BY_PATH.get('/');
  return BY_PATH.get(path.length > 1 ? path.replace(/\/$/, '') : path) || null;
}

export const routeForView = view => BY_VIEW.get(view) || null;

// A readable path segment from a name, accents dropped ("Jose Menendez" -> "jose-menendez"). Only for readability: the
// code is the key.
export function slugify(text) {
  return String(text || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60).replace(/-+$/, '');
}

// A topic's path segment ("Energy & utilities" -> "energy-and-utilities"), as the agent edition names its topic pages.
// Published in addresses, so it must not change; scripts/build_feeds.py does not recompute it (it reads the agent's list).
export const topicSlug = text => String(text || '').toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '').slice(0, 80);

// The canonical address, robots and description for a view at `url` (what buildUrl wrote). A personal or filterable
// view, a shared list and a keyed view without its key point at the home page and are not indexed.
const SITE = 'https://billatlas.org';
export function pageMeta(view, url, shared = false) {
  const route = routeForView(view);
  const indexable = Boolean(route?.indexable) && !String(url).startsWith('/#') && !shared;
  return {canonical: indexable ? SITE + String(url).split(/[?#]/)[0] : `${SITE}/`, robots: indexable ? null : 'noindex, follow',
    description: route?.description || null};
}

// The route list the deploy publishes as /routes.json (public/routes.json, written by scripts/routes_json.mjs): the
// gateway's matchers and the E2E server are checked against it. Every route has `match`, an anchored RE2-compatible
// pattern for the canonical path.
export function routeList() {
  return {format: 'texas-bill-atlas-routes-v1', routes: ROUTES.map(({view, path, pattern, match, indexable}) => ({view,
    path: path || pattern, match: match || `^${path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, indexable}))};
}
