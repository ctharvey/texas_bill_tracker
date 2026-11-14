// Easter eggs: the pure parts (dates, odds, triggers). No DOM, so tests can import it.

// Day 140 of the 90th regular session, which convenes Jan 12, 2027: the day it adjourns sine die.
export const SINE_DIE = '2027-05-31';

// The date in Austin as YYYY-MM-DD, whatever the reader's own time zone.
export const austinDate = (now = new Date()) =>
  new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Chicago', year: 'numeric', month: '2-digit', day: '2-digit'}).format(now);
export const isSineDieDay = (now = new Date()) => austinDate(now) === SINE_DIE;
// A search for "sine die" (any case, spacing or hyphen) and nothing else.
export const asksSineDie = query => /^\s*sine[\s-]*die\s*$/i.test(String(query ?? ''));

// Bluebonnets bloom in March and April.
export const isBluebonnetSeason = (now = new Date()) => [3, 4].includes(Number(austinDate(now).slice(5, 7)));

// Five presses on the star inside two seconds bring the gavel down. Returns the presses still counting, or [] when
// this press is the fifth (the gavel falls and the count starts over).
export const GAVEL_PRESSES = 5;
export const GAVEL_WINDOW_MS = 2000;
export const gavelPress = (presses, now) => {
  const recent = [...presses.filter(t => now - t < GAVEL_WINDOW_MS), now];
  return recent.length >= GAVEL_PRESSES ? [] : recent;
};

// The armadillo visits about one page load in eight, at most once per browser session, 15 to 60 seconds in.
export const ARMADILLO_ODDS = 1 / 8;
export const armadilloVisits = (random, seenThisSession) => !seenThisSession && random < ARMADILLO_ODDS;
export const armadilloDelayMs = random => Math.round(15000 + Math.min(Math.max(Number(random) || 0, 0), 1) * 45000);

// Holding the theme dot this long releases a mockingbird instead of a warbler.
export const MOCKINGBIRD_HOLD_MS = 550;
