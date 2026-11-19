// Shared display formatters: dates in Texas time and plain helpers used across views. No DOM, no app state.

// One formatter each, remembered per day: search formats two dates for every bill on every keystroke, and building a
// formatter per call (toLocaleDateString with options) was most of the typing cost on a slow CPU.
export const dayFormat = (options, empty) => {
  const format = new Intl.DateTimeFormat('en-US', {...options, timeZone: 'UTC'}), seen = new Map();
  return iso => {
    if (!iso) return empty;
    const day = String(iso).slice(0,10);
    let text = seen.get(day);
    if (text === undefined) {
      const date = new Date(`${day}T12:00:00Z`);  // a malformed day ("2026-13-45") shows as empty, not a thrown RangeError
      text = Number.isNaN(date.getTime()) ? empty : format.format(date); seen.set(day, text);
    }
    return text;
  };
};
export const shortDate = dayFormat({month:'short',day:'numeric'}, '');
export const dateText = dayFormat({month:'short',day:'numeric',year:'numeric'}, 'Not available');
export const stampText = iso => iso ? new Date(iso).toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short',timeZone:'America/Chicago'})+' CT' : 'Unknown';
export const unique = a => [...new Set(a)];
export const safeHref = value => {try{const u=new URL(String(value));return u.protocol==='https:'||u.protocol==='http:'?u.href:''}catch{return ''}};
