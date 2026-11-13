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

export function setupThemePicker() {
  const select = $('#theme-select');
  if (!select) return;
  const current = applyTheme(readJson(prefsKey)?.theme);
  select.innerHTML = THEMES.map(t => `<option value="${esc(t.id)}"${t.id === current ? ' selected' : ''}>${esc(t.name)}</option>`).join('');
  select.addEventListener('change', () => writeJson(prefsKey, withTheme(readJson(prefsKey), applyTheme(select.value))));
}
