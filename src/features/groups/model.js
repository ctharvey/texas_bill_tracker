// Agency and topic pages: which bills a page lists, newest action first. No DOM or state, so node tests import it.
import {SCOPE_AGENCY_ID, POLICY_AREAS, lastActionInfo, newestFirst} from '../../taxonomy.js';
import {topicSlug} from '../../core/routes.js';

function sorted(bills) {
  const day = new Map(bills.map(b => [b.id, String(lastActionInfo(b).date || '').slice(0, 10)]));
  return [...bills].sort((a, b) => day.get(b.id).localeCompare(day.get(a.id)) || newestFirst(a.id, b.id));
}

export const agencyBills = (bills, id) => sorted(bills.filter(b => (b.agencies || []).some(a => a.id !== SCOPE_AGENCY_ID && a.id === id)));
export const topicName = slug => POLICY_AREAS.find(t => topicSlug(t.name) === slug)?.name || null;
export const topicBills = (bills, name) => sorted(bills.filter(b => (b.topics || []).includes(name)));
