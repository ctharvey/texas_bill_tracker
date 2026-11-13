// The dashboard (home view): what changed since the last visit, newest reviews, scheduled hearings. No DOM.
import {latestActivityDay} from '../../taxonomy.js';

const DAY = /^\d{4}-\d{2}-\d{2}$/;

// The last-visit stamp, kept as {day, prev}: `day` is the Texas day of the latest visit, `prev` the visit before it.
// A reload on the same day keeps `prev`, so "since your last visit" does not empty itself on a second look.
// Returns the previous visit day (null on a first visit) and the stamp to store.
export function nextVisit(stored, today) {
  const day = DAY.test(stored?.day || '') ? stored.day : null;
  const prev = day === today ? (DAY.test(stored?.prev || '') ? stored.prev : null) : day;
  return {prev, store: {day: today, prev}};
}

// Bills with an action on or after `since` (and not after `today`), newest activity first: [{bill, day}].
// On or after, not after: activity is dated by day only, so a change later on the day of the last visit still counts.
// With no `since` (a first visit), every bill with dated activity.
export function changedSince(bills, since, today) {
  const rows = [];
  for (const bill of bills) {
    const day = latestActivityDay([bill], today);
    if (day && (!since || day >= since)) rows.push({bill, day});
  }
  return rows.sort((a, b) => b.day.localeCompare(a.day) || a.bill.id.localeCompare(b.bill.id, undefined, {numeric: true}));
}

// Bills Luna reviewed, most recent review first.
export function newestReviewed(bills) {
  return bills.filter(b => typeof b.luna?.reviewed_at === 'string' && b.luna.reviewed_at)
    .sort((a, b) => b.luna.reviewed_at.localeCompare(a.luna.reviewed_at) || a.id.localeCompare(b.id, undefined, {numeric: true}));
}
