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
  + '<svg viewBox="0 0 40 40" width="38" height="38" focusable="false"><g fill="none" stroke="#9c7a48" stroke-width="1.3" stroke-linecap="round">'
  + '<path d="M20 4q8-1 12.5 6q5 7 1.5 14q-3 9-12 11q-10 1-14.5-7q-4-8-.5-15q5-9 13-9zM35 13l3.5-2.5M4 26l-3.5 2M27 35.5l2 3.5M12 4.5l-2.5-3.5M36 26l3 1.5"/><path d="M6 16q14-10 28 2M7 26q12 8 26-4M14 5q-6 15 4 30M26 5q8 14-3 30M5 21q15-4 30 0M11 9q14 4 18 23M29 9q-15 5-17 24"/></g>'
  + '<path d="M10 13q10 2 20 14M30 13q-12 3-19 15M20 4v32" fill="none" stroke="#c4a06a" stroke-width=".8"/></svg></div></div>';

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
  sky.firstElementChild.style.left = `${Math.round(box.right - 8)}px`;
  sky.firstElementChild.style.top = `${Math.round(box.top + box.height / 2 - 28)}px`;
}

// The nine-banded armadillo, Texas's official small mammal, ambling along the bottom of the screen.
const ARMADILLO_SVG = '<svg viewBox="0 0 64 34" width="84" height="45" focusable="false">'
  + '<path d="M9 22q-6 1-9 5q5-1 10-2z" fill="#8b7d6b"/>'
  + '<g class="dillo-step" fill="#6f6355"><rect x="15" y="22" width="5" height="9" rx="2"/><rect x="39" y="22" width="5" height="9" rx="2"/></g>'
  + '<g class="dillo-step dillo-step-b" fill="#5d5347"><rect x="22" y="22" width="5" height="9" rx="2"/><rect x="45" y="22" width="5" height="9" rx="2"/></g>'
  + '<path d="M8 25q2-19 24-19q20 0 22 19z" fill="#a8977f"/>'
  + '<path d="M20 9.5v15M26 7.3v17.7M32 6.5v18.5M38 7.3v17.7M44 9.8v15M8 25h46" stroke="#857560" stroke-width="1.4"/>'
  + '<path d="M51 15q7-2 10 3q2 3-1 4.5l-10 1z" fill="#b9a891"/><path d="M51.5 15l1.2-6.5 3 6z" fill="#a8977f"/>'
  + '<circle cx="56" cy="17.6" r=".95" fill="#2b2620"/></svg>';
export function armadillo() {
  if (still() || document.querySelector('.dillo-sky')) return false;
  layer('dillo-sky', `<div class="dillo-walk"><div class="dillo-bob">${ARMADILLO_SVG}</div></div>`, 17000);
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
