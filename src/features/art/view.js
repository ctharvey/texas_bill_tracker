// Bill page banner: the bill's illustration from live/og/art.json (written by the hourly data run) while the operator
// flag in live/site-flags.json has "bill_art_banner": true. A missing or unreadable file means no banner.
import {esc} from '../../core/dom.js';
import {isBillId} from '../../prefs.js';

export const ART_FORMAT = 'texas-bill-art-v1';

export const bannerOn = flags => flags !== null && typeof flags === 'object' && flags.bill_art_banner === true;

// Bill id -> {v, alt} from art.json; entries with a bad id or version are dropped.
export function artEntries(data) {
  const out = {};
  if (!data || data.format !== ART_FORMAT || !data.bills || typeof data.bills !== 'object' || Array.isArray(data.bills)) return out;
  for (const [id, entry] of Object.entries(data.bills)) {
    if (!isBillId(id) || !entry || typeof entry.v !== 'string' || !/^[0-9a-f]{6,64}$/.test(entry.v)) continue;
    out[id] = {v: entry.v, alt: typeof entry.alt === 'string' ? entry.alt.trim() : ''};
  }
  return out;
}

export function artBanner(id, number, flags, art) {
  if (!bannerOn(flags) || !isBillId(id)) return '';
  const entry = art && Object.hasOwn(art, id) ? art[id] : null;
  if (!entry) return '';
  const alt = entry.alt || `Illustration for ${number || id}`;
  return `<figure class="bill-art"><img src="./live/og/art/${id}.jpg?v=${esc(entry.v)}" alt="${esc(alt)}" width="1216" height="640" decoding="async">`
    + '<figcaption>Illustration for this bill, made with a local image model.</figcaption></figure>';
}

// Wide screens put the pills, number and title on the banner's dark ground, but only when the title (less its number
// line) fits in two lines; a title not laid out yet (height 0) or a longer one stays under the banner.
export const HERO_MEDIA = '(min-width: 900px)';
export const heroFits = (titleH, numberH, lineH) => titleH > 0 && lineH > 0 && titleH - numberH <= lineH * 2.2;
