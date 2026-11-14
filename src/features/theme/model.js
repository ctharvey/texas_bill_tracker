// Colour themes: one id per palette in styles.css (:root[data-palette="..."]). No DOM, so tests and build_agent can import it.
export const DEFAULT_THEME = 'current';
export const THEMES = [
  {id: 'current', name: 'Atlas'},
  {id: 'granite', name: 'Capitol granite'},
  {id: 'lone-star', name: 'Lone Star'},
  {id: 'bluebonnet', name: 'Bluebonnet'},
  {id: 'ranch', name: 'Ranch'},
  {id: 'warbler', name: 'Golden-cheeked warbler'},
];
const IDS = new Set(THEMES.map(t => t.id));

// A saved theme id, or the default for anything else (a removed theme, a hand-edited value, a missing field).
export const cleanTheme = value => (typeof value === 'string' && IDS.has(value) ? value : DEFAULT_THEME);

// Light or dark: the reader's choice, or 'system' to follow the device. Light until a reader chooses, so nobody's
// page turns dark without asking. Device-only; it is not synced or exported.
export const DEFAULT_MODE = 'light';
export const MODES = [
  {id: 'light', name: 'Light'},
  {id: 'dark', name: 'Dark'},
  {id: 'system', name: 'Match device'},
];
export const cleanMode = value => (MODES.some(m => m.id === value) ? value : DEFAULT_MODE);
// The mode the page shows: 'light' or 'dark'.
export const shownMode = (mode, deviceDark) => { const m = cleanMode(mode); return m === 'system' ? (deviceDark ? 'dark' : 'light') : m; };
const asPrefs = prefs => (prefs && typeof prefs === 'object' && !Array.isArray(prefs) ? prefs : {});
export const withMode = (prefs, mode) => ({...asPrefs(prefs), mode: cleanMode(mode)});

// The warbler theme's easter egg: a golden-cheeked warbler crosses the screen when the reader picks the theme, and on
// the first page load of a browser session with it saved; never under reduced motion.
export const fliesAcross = (theme, reducedMotion, {picked = true, flewThisSession = false} = {}) =>
  cleanTheme(theme) === 'warbler' && !reducedMotion && (picked || !flewThisSession);

// prefs-v1 with its theme set; other fields (remembered filters) are kept.
export const withTheme = (prefs, theme) => ({...(prefs && typeof prefs === 'object' && !Array.isArray(prefs) ? prefs : {}), theme: cleanTheme(theme)});
