// The top bar's colour and light-or-dark pickers. index.html applies the saved theme before first paint; this keeps it in step afterwards.
import {THEMES, DEFAULT_THEME, cleanTheme, withTheme, MODES, cleanMode, shownMode, withMode, fliesAcross} from './model.js';
import {$, esc} from '../../core/dom.js';
import {prefsKey, readJson, writeJson} from '../../core/storage.js';

export function applyTheme(theme) {
  const id = cleanTheme(theme);
  if (id === DEFAULT_THEME) delete document.documentElement.dataset.palette;
  else document.documentElement.dataset.palette = id;
  return id;
}

// The saved theme id, or null when this device never chose one.
export const savedTheme = () => { const t = readJson(prefsKey)?.theme; return typeof t === 'string' ? cleanTheme(t) : null; };

// Applies and saves a theme that came from elsewhere (sync, a profile file); keeps the picker in step.
export function setTheme(theme) {
  const id = applyTheme(theme);
  if (savedTheme() !== id) writeJson(prefsKey, withTheme(readJson(prefsKey), id));
  const select = $('#theme-select');
  if (select) select.value = id;
  return id;
}

const DEVICE_DARK = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)') : null;
const THEME_COLOR = {light: '#112136', dark: '#0b1422'};

export function applyMode(mode) {
  const shown = shownMode(mode, DEVICE_DARK?.matches);
  document.documentElement.dataset.mode = shown;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[shown]);
  return shown;
}

const MODE_ICON = {light: '\u2600', dark: '\u263E', system: '\u25D0'};  // sun, moon, half circle

// The light or dark button: each press moves to the next of Light, Dark and Match device. 'Match device' follows
// the device as it changes (a phone's evening switch).
export function setupModePicker() {
  const saved = () => readJson(prefsKey)?.mode;
  applyMode(saved());
  DEVICE_DARK?.addEventListener?.('change', () => applyMode(saved()));
  const button = $('#mode-toggle');
  if (!button) return;
  const show = mode => {
    const id = cleanMode(mode), at = MODES.findIndex(m => m.id === id), next = MODES[(at + 1) % MODES.length];
    button.textContent = MODE_ICON[id];
    button.title = `${MODES[at].name}, press for ${next.name.toLowerCase()}`;
    button.setAttribute('aria-label', `Light or dark: ${MODES[at].name}. Switch to ${next.name}`);
    return next.id;
  };
  let next = show(saved());
  button.addEventListener('click', () => {
    writeJson(prefsKey, withMode(readJson(prefsKey), next));
    applyMode(next);
    next = show(next);
  });
}

// A side-on golden-cheeked warbler: black crown, back and notched tail, golden cheek crossed by a black eye line,
// white belly, and dark wings with the species' two white wing bars. The far wing flaps behind the body.
const WING = '<path d="M38 19q-11-15-27-17q8 10 18 21z"/><path d="M33 15.5l-9-6M30 18l-8-5" stroke="#f4f1e6" stroke-width="1.1" stroke-linecap="round"/>';
const WARBLER_SVG = '<svg viewBox="0 0 64 40" width="124" height="78" aria-hidden="true" focusable="false">'
  + '<g class="warbler-wing warbler-far" fill="#1b1d1a">' + WING + '</g>'
  + '<path d="M1 18.5l18 .5-1 5-17 1.5 5-3.5z" fill="#1b1d1a"/>'
  + '<path d="M17 22q4-6 16-6q9 0 12 5q-3 7-14 7q-10 0-14-6z" fill="#454842"/>'
  + '<path d="M19 24q11 7 25-2q-2 6-13 6q-8 0-12-4z" fill="#f4f1e6"/>'
  + '<path d="M24 24.5l3-1.5M29 25.5l3-1.6M34 25.4l3-1.8" stroke="#2b2d29" stroke-width=".8" stroke-linecap="round"/>'
  + '<circle cx="46" cy="18" r="6.5" fill="#1b1d1a"/>'
  + '<path d="M41 16.5q4-5.5 10-1q.5 5-4 6.5q-5 .5-6-5.5z" fill="#f2c230"/>'
  + '<path d="M43 17.2h7.5" stroke="#1b1d1a" stroke-width="1"/><circle cx="47.6" cy="17.2" r="1" fill="#1b1d1a"/>'
  + '<path d="M52 17l6.5 1.6-6.5 1.4z" fill="#1b1d1a"/>'
  + '<g class="warbler-wing" fill="#2b2d29" stroke="#f4f1e6" stroke-width=".7">' + WING + '</g>'
  + '</svg>';
const REDUCED_MOTION = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
const FLEW_KEY = 'tx-bill-atlas-warbler-flew';
const flewThisSession = () => { try { return sessionStorage.getItem(FLEW_KEY) === '1'; } catch { return false; } };

// The easter egg: one warbler crosses the middle of the screen, then is removed. It never takes clicks or focus.
export function warblerFlight(theme, picked = false) {
  if (!fliesAcross(theme, REDUCED_MOTION?.matches, {picked, flewThisSession: flewThisSession()})
      || document.querySelector('.warbler-sky')) return false;
  try { sessionStorage.setItem(FLEW_KEY, '1'); } catch { /* still flies; it may fly again next load */ }
  const sky = document.createElement('div');
  sky.className = 'warbler-sky';
  sky.setAttribute('aria-hidden', 'true');
  sky.innerHTML = `<div class="warbler-flight"><div class="warbler-bob">${WARBLER_SVG}</div></div>`;
  sky.firstElementChild.addEventListener('animationend', event => {
    if (event.animationName === 'warbler-cross') sky.remove();
  });
  document.body.appendChild(sky);
  return true;
}

// `onChange(id)` runs when the reader picks a theme (the app syncs it).
export function setupThemePicker(onChange = () => {}) {
  const select = $('#theme-select');
  if (!select) return;
  const current = applyTheme(readJson(prefsKey)?.theme);
  warblerFlight(current);
  select.innerHTML = THEMES.map(t => `<option value="${esc(t.id)}"${t.id === current ? ' selected' : ''}>${esc(t.name)}</option>`).join('');
  select.addEventListener('change', () => {
    const id = applyTheme(select.value);
    writeJson(prefsKey, withTheme(readJson(prefsKey), id));
    warblerFlight(id, true);
    onChange(id);
  });
}
