// The footer's colour picker. index.html applies the saved theme before first paint; this keeps it in step afterwards.
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

// The light or dark picker. 'Match device' follows the device as it changes (a phone's evening switch).
export function setupModePicker() {
  const saved = () => readJson(prefsKey)?.mode;
  applyMode(saved());
  DEVICE_DARK?.addEventListener?.('change', () => applyMode(saved()));
  const select = $('#mode-select');
  if (!select) return;
  const current = cleanMode(saved());
  select.innerHTML = MODES.map(m => `<option value="${esc(m.id)}"${m.id === current ? ' selected' : ''}>${esc(m.name)}</option>`).join('');
  select.addEventListener('change', () => {
    writeJson(prefsKey, withMode(readJson(prefsKey), select.value));
    applyMode(select.value);
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
