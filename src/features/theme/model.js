// Colour themes: one id per palette in styles.css (:root[data-palette="..."]). No DOM, so tests and build_agent can import it.
export const DEFAULT_THEME = 'current';
export const THEMES = [
  {id: 'current', name: 'Atlas'},
  {id: 'granite', name: 'Capitol granite'},
  {id: 'lone-star', name: 'Lone Star'},
  {id: 'bluebonnet', name: 'Bluebonnet'},
  {id: 'ranch', name: 'Ranch'},
];
const IDS = new Set(THEMES.map(t => t.id));

// A saved theme id, or the default for anything else (a removed theme, a hand-edited value, a missing field).
export const cleanTheme = value => (typeof value === 'string' && IDS.has(value) ? value : DEFAULT_THEME);

// prefs-v1 with its theme set; other fields (remembered filters) are kept.
export const withTheme = (prefs, theme) => ({...(prefs && typeof prefs === 'object' && !Array.isArray(prefs) ? prefs : {}), theme: cleanTheme(theme)});
