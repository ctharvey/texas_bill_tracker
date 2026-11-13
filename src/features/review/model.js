// The review progress page: the live run, each pass's backlog, and one bill's review state. No DOM.

export const RUN_LIMIT_MINUTES = 55;  // the worker's --max-minutes
export const RUN_MINUTE = 35;         // the hourly timer starts runs at :35 (whole-hour zones, so :35 UTC too)

// Passes in run order. `review` is the first pass; the rest come from status.passes, published from 13 Nov 2026.
export const PASSES = [
  {key: 'review', label: 'Full review', note: 'reads each bill in full'},
  {key: 'entities', label: 'Agencies', note: 'agencies and other bodies the review did not list'},
  {key: 'topics', label: 'Topics and scope votes', note: 'headline, search terms and the all-agencies vote'},
  {key: 'audit', label: 'Spot check', note: 'an independent re-check of a small sample'},
];

const minutesBetween = (later, earlier) => (later - earlier) / 60000;
const time = s => (typeof s === 'string' && s ? Date.parse(s) : NaN);

// The next run start after `now` (ms): the next :35 past the hour. The timer may add up to 2 minutes.
export function nextRunAt(now) {
  const d = new Date(now);
  d.setUTCMinutes(RUN_MINUTE, 0, 0);
  if (d.getTime() <= now) d.setUTCHours(d.getUTCHours() + 1);
  return d.getTime();
}

// What the worker is doing: {kind, pass, startedAt, minutesUsed, updatedAt, waitingUntil, nextRun}.
// kind: unavailable (no status file), stale (running but silent for 90 min), quiet (idle and no run for 75 min),
// waiting (capacity retry pending), running, idle. `pass` is null on status files from before passes were published.
export function runState(status, now) {
  const nextRun = nextRunAt(now);
  if (!status) return {kind: 'unavailable', pass: null, startedAt: null, minutesUsed: null, updatedAt: null, waitingUntil: null, nextRun};
  const updated = time(status.updated_at), started = time(status.run_started_at), waiting = time(status.waiting_until);
  const silent = Number.isFinite(updated) ? minutesBetween(now, updated) : Infinity;
  const running = Boolean(status.running);
  const kind = running && silent > 90 ? 'stale' : !running && silent > 75 ? 'quiet'
    : running && waiting > now ? 'waiting' : running ? 'running' : 'idle';
  const live = kind === 'running' || kind === 'waiting';
  return {kind, pass: live && typeof status.pass === 'string' ? status.pass : null,
    startedAt: live && Number.isFinite(started) ? started : null,
    minutesUsed: live && Number.isFinite(started) ? Math.max(0, Math.round(minutesBetween(now, started))) : null,
    updatedAt: Number.isFinite(updated) ? updated : null, waitingUntil: kind === 'waiting' ? waiting : null, nextRun};
}

// One row per pass: {key, label, note, due, checked, now, known, estimate}. `due` is what the status reports: for
// the full review, every bill still owed a first pass (new bills, new versions, and reviews redone after a prompt
// change). A status file without that count falls back to the bills not yet picked up (`estimate`: true). Later
// passes are null when the status file has no count for them.
export function passRows(status, summary, run) {
  const passes = status?.passes && typeof status.passes === 'object' ? status.passes : {};
  return PASSES.map(p => {
    const reported = passes[p.key] && Number.isFinite(passes[p.key].due) ? passes[p.key] : null;
    const estimate = p.key === 'review' && !reported;
    const counted = estimate ? {due: summary.notStarted.length, checked: null} : reported;
    const known = Boolean(counted);
    return {...p, known, estimate, due: known ? counted.due : null,
      checked: known && Number.isFinite(counted.checked) ? counted.checked : null,
      now: run.pass === p.key};
  });
}

// Bill numbers as people type them: "hb 474", "HB474", "H.B. 474" -> "HB474".
export function billKey(text) {
  const m = String(text || '').toUpperCase().replace(/[.\s]/g, '').match(/^([A-Z]{2,3})0*(\d{1,5})$/);
  return m ? m[1] + m[2] : null;
}

// One bill's review state on this page: {id, state, label} or null when the text names no known bill.
// state: active, questions, reviewed, notext, failed, notstarted. `summary` is reviewSummary(reviewProgress(...)).
export function lookup(text, summary, ids) {
  const id = billKey(text);
  if (!id || !ids.includes(id)) return id ? {id, state: 'unknown', label: 'Not a bill in this session’s list'} : null;
  const failed = summary.failed.find(f => f.id === id);
  if (summary.active.includes(id)) return {id, state: 'active', label: 'Being reviewed now'};
  if (summary.questionsQueued.includes(id)) return {id, state: 'questions', label: 'Reviewed; follow-up questions queued'};
  if (summary.reviewed.includes(id)) return {id, state: 'reviewed', label: 'Reviewed'};
  if (summary.noText.includes(id)) return {id, state: 'notext', label: 'Waiting for the legislature to post its text'};
  if (failed) return {id, state: 'failed', label: failed.stage ? `Review failed at ${failed.stage}; retried next run` : 'Review failed; retried next run'};
  return {id, state: 'notstarted', label: 'Not started yet'};
}
