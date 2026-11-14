// Easter eggs: a tumbleweed on empty results, sine die petals, the gavel on the star, a visiting armadillo and spring
// bluebonnets. Every one is decoration: aria-hidden, never takes clicks or focus, and stays still under reduced motion.
import {isSineDieDay, asksSineDie, isBluebonnetSeason, gavelPress, armadilloVisits, armadilloDelayMs} from './model.js';
import {toast} from '../../core/dom.js';

const REDUCED_MOTION = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
const still = () => !!REDUCED_MOTION?.matches;
const seen = key => { try { return sessionStorage.getItem(key) === '1'; } catch { return false; } };
const mark = key => { try { sessionStorage.setItem(key, '1'); } catch { /* it may show again next load */ } };

// A fixed, clipped layer that removes itself after `ms`, so nothing it holds can widen the page.
function layer(className, html, ms) {
  const el = document.createElement('div');
  el.className = className;
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = html;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), ms);
  return el;
}

// Rolls once across the explorer's "Nothing matches" box (CSS only; app.js adds it to the empty state).
export const TUMBLEWEED = '<div class="tumbleweed-lane" aria-hidden="true"><div class="tumbleweed">'
  + '<svg viewBox="0 0 48 48" width="46" height="46" focusable="false"><g fill="none" stroke-linecap="round">'
  + '<path d="M24 5q10-1 15 7q6 9 2 18q-3 11-15 13q-12 2-18-8q-5-9-1-18q5-11 17-12z" stroke="#8a6a3c" stroke-width="1.6"/>'
  + '<path d="M7 18q17-12 34 3M8 31q15 10 32-5M16 6q-8 18 5 37M31 6q10 17-4 37M5 25q19-6 38 0M12 11q17 5 22 28M36 11q-18 6-21 29M10 37q12-24 30-27M14 9q18 2 27 29" stroke="#9c7a48" stroke-width="1.2"/>'
  + '<path d="M18 15q8 4 12 18M30 16q-9 5-13 16M24 9q3 15-2 30M12 24q12 3 25-4" stroke="#c9a56d" stroke-width=".9"/>'
  + '<path d="M41 15l4-3M44 27l3.5 1.5M33 42l2.5 4M14 42l-2 4M4 30l-3.5 1.5M6 14l-3.5-2.5M18 5l-1.5-4M31 4.5l2-4" stroke="#8a6a3c" stroke-width="1.1"/>'
  + '</g></svg></div><span class="tumble-dust"></span></div>';

// Sine die: bluebonnet petals drift down the screen and the session says goodbye.
const PETALS = ['#2f4fb0', '#3d63c9', '#5274d8', '#2a3f8f', '#f4f3ee'];
export function sineDie() {
  toast('Adjourned sine die. See you next session.');
  if (still() || document.querySelector('.petal-sky')) return;
  const petals = Array.from({length: 36}, (_, i) => {
    const vars = `--x:${(Math.random() * 100).toFixed(1)}vw;--d:${(Math.random() * 1.6).toFixed(2)}s;`
      + `--t:${(3.2 + Math.random() * 2).toFixed(2)}s;--dx:${Math.round(Math.random() * 120 - 60)}px;--r:${Math.round(Math.random() * 720 - 360)}deg`;
    return `<span class="petal" style="${vars};background:${PETALS[i % PETALS.length]}"></span>`;
  });
  layer('petal-sky', petals.join(''), 7500);
}

// Fires once each time the search box turns into "sine die", not on every re-render while it stays that way.
let askedSineDie = false;
export function noticeSearch(query) {
  const asked = asksSineDie(query);
  if (asked && !askedSineDie) sineDie();
  askedSineDie = asked;
}

// Five quick presses on the star: the gavel comes down beside it.
const GAVEL_SVG = '<svg viewBox="0 0 48 48" width="56" height="56" focusable="false"><g transform="rotate(-40 24 24)">'
  + '<rect x="21.8" y="15" width="4.5" height="28" rx="2" fill="#8a5a2b"/><rect x="11" y="6" width="26" height="11" rx="3" fill="#6b4220"/>'
  + '<rect x="9" y="7.5" width="3" height="8" rx="1" fill="#c9a26a"/><rect x="36" y="7.5" width="3" height="8" rx="1" fill="#c9a26a"/></g></svg>';
function gavel(near) {
  toast('Order! The chair recognizes the gentle reader.');
  if (still() || document.querySelector('.gavel-sky')) return;
  const sky = layer('gavel-sky', `<div class="gavel-at"><span class="gavel-thud"></span><span class="gavel">${GAVEL_SVG}</span></div>`, 2200);
  const box = near.getBoundingClientRect();
  // Centred above the star so the head comes down on it, clear of the TEXAS BILL ATLAS text beside it.
  sky.firstElementChild.style.left = `${Math.round(box.left + box.width / 2 - 20)}px`;
  sky.firstElementChild.style.top = `${Math.round(Math.max(box.top - 26, 2))}px`;
}

// The nine-banded armadillo, Texas's official small mammal, ambling along the bottom of the screen.
const ARMADILLO_SVG = '<svg viewBox="0 0 64 34" width="84" height="45" focusable="false">'
  + '<path d="M9 22q-6 1-9 5q5-1 10-2z" fill="#8b7d6b"/>'
  + '<g class="dillo-step" fill="#6f6355"><rect x="15" y="22" width="5" height="9" rx="2"/><rect x="39" y="22" width="5" height="9" rx="2"/></g>'
  + '<g class="dillo-step dillo-step-b" fill="#5d5347"><rect x="22" y="22" width="5" height="9" rx="2"/><rect x="45" y="22" width="5" height="9" rx="2"/></g>'
  + '<path d="M8 25q2-19 24-19q20 0 22 19z" fill="#a8977f" stroke="#5d5347" stroke-width="1"/>'
  + '<path d="M20 9.5v15M26 7.3v17.7M32 6.5v18.5M38 7.3v17.7M44 9.8v15M8 25h46" stroke="#857560" stroke-width="1.4"/>'
  + '<path d="M51 15q7-2 10 3q2 3-1 4.5l-10 1z" fill="#b9a891"/><path d="M51.5 15l1.2-6.5 3 6z" fill="#a8977f"/>'
  + '<circle cx="56" cy="17.6" r=".95" fill="#2b2620"/></svg>';
export function armadillo() {
  if (still() || document.querySelector('.dillo-sky')) return false;
  layer('dillo-sky', `<div class="dillo-walk"><div class="dillo-bob">${ARMADILLO_SVG}</div></div>`, 10000);
  return true;
}

const DILLO_KEY = 'tx-bill-atlas-armadillo-seen';
export function setupEasterEggs() {
  if (isBluebonnetSeason()) document.documentElement.dataset.season = 'bluebonnet';
  const SINE_KEY = 'tx-bill-atlas-sine-die-seen';
  if (isSineDieDay() && !seen(SINE_KEY)) { mark(SINE_KEY); setTimeout(sineDie, 1200); }
  let presses = [];
  for (const star of document.querySelectorAll('.brand-mark, .mobile-logo')) {
    star.addEventListener('click', () => {
      const before = presses.length;
      presses = gavelPress(presses, Date.now());
      if (before && !presses.length) gavel(star);
    });
  }
  if (armadilloVisits(Math.random(), seen(DILLO_KEY))) {
    mark(DILLO_KEY);
    setTimeout(() => { if (document.visibilityState !== 'hidden') armadillo(); }, armadilloDelayMs(Math.random()));
  }
}
