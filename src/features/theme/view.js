// The footer's colour picker. index.html applies the saved theme before first paint; this keeps it in step afterwards.
import {THEMES, DEFAULT_THEME, cleanTheme, withTheme} from './model.js';
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
