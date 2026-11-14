// The top bar's colour and light-or-dark pickers. index.html applies the saved theme before first paint; this keeps it in step afterwards.
import {THEMES, DEFAULT_THEME, cleanTheme, withTheme, MODES, cleanMode, shownMode, withMode, fliesAcross, skyTop} from './model.js';
import {MOCKINGBIRD_HOLD_MS} from '../easter/model.js';
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
const WING = '<path d="M39 19q-9-14-23-16q7 10 15 20z"/><path d="M34 15.5l-8-5.5M31.5 18l-7-4.5" stroke="#f4f1e6" stroke-width="1.1" stroke-linecap="round"/>';
const WARBLER_SVG = '<svg viewBox="6 0 54 40" width="106" height="78" aria-hidden="true" focusable="false">'
  + '<g class="warbler-wing warbler-far" fill="#1b1d1a">' + WING + '</g>'
  + '<path d="M8 18.8l15 .4-1 4.6-14 1.4 4-3.2z" fill="#1b1d1a"/>'
  + '<path d="M22 22q3-6 12-6q8 0 11 5q-3 7-12 7q-8 0-11-6z" fill="#454842"/>'
  + '<path d="M23.5 24q9 6 20.5-2q-2 6-11 6q-7 0-9.5-4z" fill="#f4f1e6"/>'
  + '<path d="M27 24.6l2.6-1.4M31 25.5l2.6-1.5M35 25.4l2.6-1.7" stroke="#2b2d29" stroke-width=".8" stroke-linecap="round"/>'
  + '<circle cx="46" cy="18" r="6.5" fill="#1b1d1a"/>'
  + '<path d="M41 16.5q4-5.5 10-1q.5 5-4 6.5q-5 .5-6-5.5z" fill="#f2c230"/>'
  + '<path d="M43 17.2h7.5" stroke="#1b1d1a" stroke-width="1"/><circle cx="47.6" cy="17.2" r="1" fill="#1b1d1a"/>'
  + '<path d="M52 17l6.5 1.6-6.5 1.4z" fill="#1b1d1a"/>'
  + '<g class="warbler-wing" fill="#2b2d29" stroke="#f4f1e6" stroke-width=".7">' + WING + '</g>'
  + '</svg>';
const REDUCED_MOTION = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
const FLEW_KEY = 'tx-bill-atlas-warbler-flew';
const flewThisSession = () => { try { return sessionStorage.getItem(FLEW_KEY) === '1'; } catch { return false; } };

// One warbler crosses the screen at `topPercent` of its height, then is removed. It never takes clicks or focus.
function launchWarbler(topPercent, svg = WARBLER_SVG) {
  const sky = document.createElement('div');
  sky.className = 'warbler-sky';
  sky.setAttribute('aria-hidden', 'true');
  sky.innerHTML = `<div class="warbler-flight"><div class="warbler-bob">${svg}</div></div>`;
  sky.firstElementChild.style.top = `${topPercent}%`;
  sky.firstElementChild.addEventListener('animationend', event => {
    if (event.animationName === 'warbler-cross') sky.remove();
  });
  document.body.appendChild(sky);
}

// The warbler theme's easter egg: one bird across the middle of the screen.
export function warblerFlight(theme, picked = false) {
  if (!fliesAcross(theme, REDUCED_MOTION?.matches, {picked, flewThisSession: flewThisSession()})
      || document.querySelector('.warbler-sky')) return false;
  try { sessionStorage.setItem(FLEW_KEY, '1'); } catch { /* still flies; it may fly again next load */ }
  launchWarbler(42);
  return true;
}

// The yellow dot in the theme pill, in any theme: each press sends a warbler from the left at a random height.
const MAX_BIRDS = 6;
export function releaseWarbler(random = Math.random, svg = WARBLER_SVG) {
  if (REDUCED_MOTION?.matches || document.querySelectorAll('.warbler-sky').length >= MAX_BIRDS) return false;
  launchWarbler(skyTop(random()), svg);
  return true;
}

// The northern mockingbird, today's state bird, which the warbler bills would like a word with: grey back, pale belly,
// white wing patches, a long dark tail with white edges and a pale yellow eye.
const MOCK_WING = '<path d="M39 19q-9-14-23-16q7 10 15 20z"/><path d="M30 12.5q-4-2-7-5.5q3 4 4.5 7z" fill="#f4f1e6" stroke="none"/>';
const MOCKINGBIRD_SVG = '<svg viewBox="0 0 60 40" width="117" height="78" aria-hidden="true" focusable="false">'
  + '<g class="warbler-wing warbler-far" fill="#3f4244">' + MOCK_WING + '</g>'
  + '<path d="M1 18l22 1-1 4.6-21 2.4 5-4z" fill="#3f4244"/><path d="M1 18l5 4-5 4" fill="none" stroke="#f4f1e6" stroke-width=".9"/>'
  + '<path d="M22 22q3-6 12-6q8 0 11 5q-3 7-12 7q-8 0-11-6z" fill="#8a8d8f"/>'
  + '<path d="M23.5 24q9 6 20.5-2q-2 6-11 6q-7 0-9.5-4z" fill="#ecebe6"/>'
  + '<circle cx="46" cy="18" r="6.2" fill="#8a8d8f"/>'
  + '<path d="M43.5 17.4h6" stroke="#3f4244" stroke-width=".8"/><circle cx="47.6" cy="17.2" r="1" fill="#e8d27a"/><circle cx="47.6" cy="17.2" r=".45" fill="#1b1d1a"/>'
  + '<path d="M51.8 17.2l7.5 1.2-7.5 1.2z" fill="#2b2d29"/>'
  + '<g class="warbler-wing" fill="#4d5052" stroke="#ecebe6" stroke-width=".6">' + MOCK_WING + '</g>'
  + '</svg>';

// The theme dot: a press sends a warbler; holding it (or Shift with a press) sends a mockingbird instead.
function setupWarblerDot() {
  const dot = $('#warbler-dot');
  if (!dot) return;
  let hold = null, held = false;
  const cancel = () => { clearTimeout(hold); hold = null; };
  dot.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    held = false;
    cancel();
    hold = setTimeout(() => { held = true; releaseWarbler(Math.random, MOCKINGBIRD_SVG); }, MOCKINGBIRD_HOLD_MS);
  });
  for (const type of ['pointerup', 'pointerleave', 'pointercancel']) dot.addEventListener(type, cancel);
  dot.addEventListener('contextmenu', event => event.preventDefault());  // a phone's long press would open a menu
  dot.addEventListener('click', event => {
    if (held) { held = false; return; }  // the hold already sent its bird
    releaseWarbler(Math.random, event.shiftKey ? MOCKINGBIRD_SVG : WARBLER_SVG);
  });
}

// `onChange(id)` runs when the reader picks a theme (the app syncs it).
export function setupThemePicker(onChange = () => {}) {
  const select = $('#theme-select');
  if (!select) return;
  setupWarblerDot();
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
