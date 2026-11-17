// Compact bill rows (home) and topic colours (home, Today). A colour is a reading aid only: the topic's name is
// always in the text next to it.

// One hue per policy area, 15 degrees apart. The topics seen most often (local government, public safety,
// education, transportation, state spending, criminal justice) sit far apart on the wheel.
export const TOPIC_HUES = {
  'Medicaid': 5, 'Criminal justice': 20, 'Taxes': 35, 'Public safety': 50, 'Housing & property': 65,
  'Civil rights': 80, 'Elections': 95, 'Agriculture': 110, 'Parks & conservation': 125, 'Environment & water': 140,
  'Local government': 155, 'Energy & utilities': 170, 'Data centers': 185, 'Transportation': 200,
  'Technology & privacy': 215, 'Government operations': 230, 'Education': 245, 'School choice': 260,
  'Labor & workforce': 275, 'Business regulation': 290, 'Economic development': 305, 'Immigration': 320,
  'State spending': 335, 'Healthcare': 350,
};

export const topicHue = topic => typeof topic === 'string' && Object.hasOwn(TOPIC_HUES, topic) ? TOPIC_HUES[topic] : null;

// Inline style for a bill's main (first) topic colour, or '' when it has none.
export function topicStyle(topics) {
  const hue = Array.isArray(topics) ? topicHue(topics[0]) : null;
  return hue === null ? '' : ` style="--topic-h:${hue}"`;
}

// The row's one line of text: Luna's plain-language summary when there is one, else the caption without its
// "Relating to" opening.
export function plainTitle(bill) {
  if (typeof bill?.headline === 'string' && bill.headline.trim()) return bill.headline.trim();
  const title = String(bill?.title || '').trim().replace(/^relating to\s+(the\s+)?/i, '');
  return title ? title[0].toUpperCase() + title.slice(1) : '';
}

// Whole days from `day` (YYYY-MM-DD) until `target` (YYYY-MM-DD); 0 once it has passed or for a bad date.
export function daysUntil(day, target) {
  const a = Date.parse(`${day}T00:00:00Z`), b = Date.parse(`${target}T00:00:00Z`);
  return Number.isFinite(a) && Number.isFinite(b) ? Math.max(0, Math.round((b - a) / 864e5)) : 0;
}
