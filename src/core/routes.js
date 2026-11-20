// Every view's address (SEO chunk 2). One table for reading and writing paths, kept as data so the gateway's list
// (chunk 3) and the sitemap (chunk 7) can be checked against it. `indexable` is for the canonical and robots meta:
// personal views and the filterable explorer are not. Names pending the roadmap's open question 1.
export const ROUTES = [
  {view: 'home', path: '/', indexable: true},
  {view: 'today', path: '/today', indexable: true},
  {view: 'all', path: '/explorer', indexable: false, filters: true},
  {view: 'local', path: '/near-you', indexable: false},
  {view: 'watchlist', path: '/watchlist', indexable: false, filters: true},
  {view: 'following', path: '/following', indexable: false},
  {view: 'agencies', path: '/agencies', indexable: true},
  {view: 'review', path: '/review', indexable: true},
  {view: 'method', path: '/about/method', indexable: true},
  {view: 'data', path: '/about/data', indexable: true},
  {view: 'saving', path: '/about/saving', indexable: true},
  {view: 'export', path: '/about/export', indexable: false},
  // Views with a key in the path; `pattern` documents the shape, prefs.js parses it.
  {view: 'bill', pattern: '/bill/<ID>', indexable: true},
  {view: 'statute', pattern: '/law/<CODE>/<section or chapter>', indexable: true},
  {view: 'member', pattern: '/member/<code>/<name-slug>', indexable: true},
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
  return String(text || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60).replace(/-+$/, '');
}
