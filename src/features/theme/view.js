// The top bar's colour and light-or-dark pickers. index.html applies the saved theme before first paint; this keeps it in step afterwards.
import {THEMES, DEFAULT_THEME, cleanTheme, withTheme, MODES, cleanMode, shownMode, withMode} from './model.js';
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

// `onChange(id)` runs when the reader picks a theme (the app syncs it).
export function setupThemePicker(onChange = () => {}) {
  const select = $('#theme-select');
  if (!select) return;
  const current = applyTheme(readJson(prefsKey)?.theme);
  select.innerHTML = THEMES.map(t => `<option value="${esc(t.id)}"${t.id === current ? ' selected' : ''}>${esc(t.name)}</option>`).join('');
  select.addEventListener('change', () => {
    const id = applyTheme(select.value);
    writeJson(prefsKey, withTheme(readJson(prefsKey), id));
    onChange(id);
  });
}
