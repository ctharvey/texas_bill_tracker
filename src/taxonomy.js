// Curated vocabulary: add agency aliases and topic rules as new legislation arrives.
// 'direct' means explicitly named in verified material; 'related' is an editorial inference.
export function memberNames(value){
  const names=Array.isArray(value)?value:typeof value==='string'?value.split('|'):[];
  return [...new Set(names.filter(name=>typeof name==='string').map(name=>name.trim()).filter(Boolean))];
}

export const SCOPE_AGENCY_ID = 'all-state-agencies';

export function snapshotAgeHours(generatedAt, now = Date.now()) {
  const then = generatedAt ? new Date(generatedAt).getTime() : NaN;
  const current = now instanceof Date ? now.getTime() : Number(now);
  if (!Number.isFinite(then) || !Number.isFinite(current)) return null;
  return Math.max(0, (current - then) / 3600000);
}

const NAME_SUFFIXES = new Set(['jr','sr','ii','iii','iv','v']);
const surnameKeys = name => {
  const tokens = String(name || '').replace(/,/g, ' ').split(/\s+/).filter(Boolean);
  while (tokens.length > 1 && NAME_SUFFIXES.has(tokens[tokens.length - 1].toLowerCase().replace(/\./g, ''))) tokens.pop();
  if (!tokens.length) return [];
  const keys = [tokens[tokens.length - 1]];
  if (tokens.length >= 3) keys.push(tokens.slice(-2).join(' '));
  return keys.map(k => k.toLowerCase());
};

// Bill authors are surnames ("Zaffirini", possibly "A | B"); profiles are keyed by full name.
export function matchAuthorProfile(author, profiles) {
  if (!profiles || typeof profiles !== 'object' || typeof author !== 'string') return undefined;
  const first = author.split('|')[0].trim();
  if (!first) return undefined;
  if (Object.hasOwn(profiles, first)) return profiles[first];
  const index = new Map();
  for (const key of Object.keys(profiles)) for (const s of new Set(surnameKeys(key))) index.set(s, [...(index.get(s) || []), key]);
  const wanted = surnameKeys(first);
  for (const s of [wanted.length > 1 ? wanted[1] : null, wanted[0]].filter(Boolean)) {
    const hits = index.get(s);
    if (hits && hits.length === 1) return profiles[hits[0]];
    if (hits && hits.length > 1) return undefined;
  }
  return undefined;
}

const toArray = value => Array.isArray(value) ? value : typeof value === 'string' ? value.split(/[;,]/).map(s => s.trim()).filter(Boolean) : [];

export const AGENCIES = [
  // Virtual scope tag, not a single agency. Keep it in the same filter vocabulary.
  ['all-state-agencies','All state agencies (cross-cutting)'],
  ['ag','Texas Department of Agriculture'],
  ['attorney-general','Office of the Attorney General'], ['comptroller','Texas Comptroller of Public Accounts'],
  ['dps','Texas Department of Public Safety'], ['dshs','Department of State Health Services'],
  ['ers','Employees Retirement System of Texas'], ['glo','General Land Office'],
  ['hhsc','Health and Human Services Commission'],
  ['oca','Office of Court Administration'], ['puc','Public Utility Commission of Texas'],
  ['rrc','Railroad Commission of Texas'], ['sos','Texas Secretary of State'],
  ['sboe','State Board of Education'], ['tceq','Texas Commission on Environmental Quality'],
  ['tdcj','Texas Department of Criminal Justice'], ['tdem','Texas Division of Emergency Management'],
  ['tdi','Texas Department of Insurance'], ['tdlr','Texas Department of Licensing and Regulation'],
  ['tea','Texas Education Agency'], ['thc','Texas Historical Commission'],
  ['thecb','Texas Higher Education Coordinating Board'],
  ['tmb','Texas Medical Board'], ['tob','Texas Optometry Board'],
  ['tpwd','Texas Parks and Wildlife Department'], ['trs','Teacher Retirement System of Texas'],
  ['tsc','Texas State Securities Board'], ['tss','Texas State Library and Archives Commission'],
  ['twc','Texas Workforce Commission'], ['twdb','Texas Water Development Board'],
  ['txdmv','Texas Department of Motor Vehicles'], ['txdot','Texas Department of Transportation'],
  ['tdhca','Texas Department of Housing and Community Affairs'], ['tvc','Texas Veterans Commission'],
  ['tcole','Texas Commission on Law Enforcement'],
  ['texas-ethics','Texas Ethics Commission'], ['tac','Texas Animal Health Commission'],
  ['twc-civil-rights','TWC Civil Rights Division'], ['tbpe','Texas Board of Professional Engineers and Land Surveyors'],
  ['sbec','State Board for Educator Certification'], ['tbc','Texas Bond Review Board'],
  ['tsbvi','Texas School for the Blind and Visually Impaired'], ['tsd','Texas School for the Deaf'],
  ['tsbp','Texas State Board of Pharmacy'], ['tbn','Texas Board of Nursing'],
  ['tsbpa','Texas State Board of Public Accountancy'],
  ['tba','Texas Alcoholic Beverage Commission'], ['tfc','Texas Facilities Commission'],
  ['veterans-land','Texas Veterans Land Board'],
  ['ut-system','University of Texas System'], ['tamu-system','Texas A&M University System'],
  ['tx-juvenile','Texas Juvenile Justice Department'], ['tpfa','Texas Public Finance Authority'],
  ['tx-courts','Texas Judicial Branch'], ['tswcb','Texas State Soil and Water Conservation Board']
].filter((v, i, a) => a.findIndex(x => x[0] === v[0]) === i).map(([id,name]) => ({id,name}));

export const AGENCY_NAME = Object.fromEntries(AGENCIES.map(a => [a.id, a.name]));

export const POLICY_AREAS = [
  {name:'Education', pattern:/\b(school|student|teacher|education|curricul|voucher|scholarship|classroom)\b/i},
  {name:'School choice', pattern:/education savings account|school voucher|charter school|school choice/i},
  {name:'Healthcare', pattern:/medicaid|medicare|health care|healthcare|hospital|patient|physician|nurs(e|ing)/i},
  {name:'Medicaid', pattern:/medicaid/i},
  {name:'Elections', pattern:/vot(er|ing)|election|ballot|candidate|campaign finance|registration application/i},
  {name:'Taxes', pattern:/\btax(es|ation)?\b|appraisal|property valuation|exemption|ad valorem/i},
  {name:'State spending', pattern:/appropriat|state fund|education savings account|medicaid expansion/i},
  {name:'Energy & utilities', pattern:/electric|utility|utilities|grid|power generation|energy|transmission/i},
  {name:'Data centers', pattern:/data cent(er|re)|large electricity users|large load/i},
  {name:'Technology & privacy', pattern:/artificial intelligence|data privacy|cybersecurity|digital identit|electronic voter/i},
  {name:'Housing & property', pattern:/housing|landlord|tenant|zoning|homeowner|property owner/i},
  {name:'Local government', pattern:/county|municipal|city council|special district|sheriff|local government/i},
  {name:'Public safety', pattern:/polic(e|ing)|firearm|sheriff|criminal|law enforcement|emergency/i},
  {name:'Immigration', pattern:/immigra|border security|ice agreements|e-verify/i},
  {name:'Labor & workforce', pattern:/worker|employment|employer|wage|labor|e-verify/i},
  {name:'Business regulation', pattern:/business|license|contractor|employer|commercial/i},
  {name:'Environment & water', pattern:/water|waste|air quality|environment|flood|aquifer|groundwater/i},
  {name:'Transportation', pattern:/highway|transportation|airport|motor vehicle|roadway|road safety/i},
  {name:'Parks & conservation', pattern:/state park|wildlife|public land|habitat|conservation/i},
  {name:'Agriculture', pattern:/agricultur|livestock|crop|farm|\branch(es|ing)?\b/i},
  {name:'Civil rights', pattern:/discriminat|voter registration rejection|civil right|equal protection/i},
  {name:'Criminal justice', pattern:/prison|probation|criminal offense|sentenc|correctional|jail/i},
  {name:'Economic development', pattern:/incentive|economic development|investment|job creation/i},
  {name:'Government operations', pattern:/state agenc(?:y|ies)|public procurement|government contract|administrative procedure|agency report/i}
];

const AGENCY_SIGNALS = [
  {id:'hhsc', related:/\bmedicaid|chip program|human services|eligibility for health coverage/i, explicit:/health and human services commission|\bHHSC\b/i},
  {id:'comptroller', related:/education savings account|sales tax|state tax incentive|franchise tax/i, explicit:/\bcomptroller\b/i},
  {id:'tea', related:/public school|school district|teacher certification|education savings account/i, explicit:/texas education agency|\bTEA\b/i},
  {id:'sos', related:/voter registration|election administration|ballot access/i, explicit:/secretary of state|\bSOS\b/i},
  {id:'dps', related:/border security|immigration enforcement|driver licen[cs]e|state police/i, explicit:/department of public safety|\bDPS\b/i},
  {id:'puc', related:/electric|power grid|large load|data center/i, explicit:/public utility commission|\bPUCT?\b/i},
  {id:'tceq', related:/water discharge|air permit|environmental quality|water use/i, explicit:/commission on environmental quality|\bTCEQ\b/i},
  {id:'tpwd', related:/state park|wildlife|state park land/i, explicit:/parks and wildlife department|\bTPWD\b/i},
  {id:'twc', related:/employer|unemployment|job training|workforce/i, explicit:/texas workforce commission|\bTWC\b/i},
  {id:'tdlr', related:/occupational licens|professional licens|licensing enforcement/i, explicit:/department of licensing and regulation|\bTDLR\b/i},
  {id:'dshs', related:/public health|disease surveillance|border healthcare|health care professionals/i, explicit:/department of state health services|\bDSHS\b/i},
  {id:'txdot', related:/highway|road construction|transportation infrastructure|airport safety/i, explicit:/department of transportation|\bTxDOT\b/i},
  {id:'twdb', related:/water infrastructure|water supply|reservoir|aquifer/i, explicit:/water development board|\bTWDB\b/i},
  {id:'tdi', related:/health insurance|insurance coverage|insurance company/i, explicit:/department of insurance|\bTDI\b/i},
  {id:'tdcj', related:/prison|parole|correctional/i, explicit:/department of criminal justice|\bTDCJ\b/i},
  {id:'glo', related:/public land|coastal property|state-owned land/i, explicit:/general land office|\bGLO\b/i},
  {id:'thecb', related:/university|higher education|student financial aid/i, explicit:/higher education coordinating board|\bTHECB\b/i},
  {id:'tcole', related:/peace officer training|law enforcement licens/i, explicit:/commission on law enforcement|\bTCOLE\b/i},
  {id:'rrc', related:/natural gas|oil and gas|pipeline safety/i, explicit:/railroad commission|\bRRC\b/i},
  {id:'tdhca', related:/affordable housing|housing tax credit|housing assistance/i, explicit:/department of housing and community affairs|\bTDHCA\b/i},
  {id:'tsbpa', related:/\bCPAs?\b|certified public accountant|public accountancy|public accounting firm|accountant licens/i, explicit:/texas state board of public accountancy|\bTSBPA\b|state board of public accountancy/i}
];

// A scope tag cannot be inferred merely because an individual agency is named.
// Broad wording is required, and uncertain application stays marked 'related'.
const ALL_AGENCIES_EXPLICIT = /\b(?:all|each|every)\s+(?:texas\s+)?state\s+agenc(?:y|ies)\b|\bany\s+(?:texas\s+)?state\s+agency\b|\bstate\s+agencies\s+(?:shall|must|are required|may not)\b/i;
const ALL_AGENCIES_POSSIBLE = /\bstate\s+agenc(?:y|ies)\b/i;
const CROSS_AGENCY_CHANGE = /\b(?:shall|must|may not|required|prohibited|compliance|comply|procurement|contracting|cybersecurity|data security|audit|reporting|records retention|ethics|standards|administrative procedures)\b/i;
const LIMITED_AGENCIES = /\b(?:certain|specified|designated|selected|some|particular|one)\s+state\s+agenc(?:y|ies)\b|\bstate\s+agency\s+(?:that|which|responsible for)\b/i;

const EFFECT_SIGNALS = [
  ['Funding & appropriations', /appropriat|grant program|state fund|budget|funding/i],
  ['Taxes & incentives', /\btax(es|ation)?\b|incentive|abatement|exemption/i],
  ['Rulemaking', /rulemaking|adopt rules|promulgate/i],
  ['Enforcement & penalties', /penalt|offense|punish|enforce|license suspension/i],
  ['Reporting & oversight', /annual report|audit|reporting requirement|oversight/i],
  ['Local preemption', /preempt|local government may not|municipality may not/i],
  ['Data & privacy', /privacy|data retention|data collection|personal information/i],
  ['Eligibility & benefits', /eligib|benefit|medicaid|assistance/i]
];

export function autoTagBill(bill) {
  const text = [bill.title, bill.caption, bill.description, bill.full_text_excerpt].filter(Boolean).join(' ');
  const topics = [...new Set([...toArray(bill.topics), ...POLICY_AREAS.filter(t => t.pattern.test(text)).map(t => t.name)])];
  const agencies = toArray(bill.agencies).filter(a => a && (typeof a === 'string' || typeof a.id === 'string')).map(a => typeof a === 'string' ? {id:a, relationship:'related', reason:'Imported tag; review evidence'} : a);
  const known = new Set(agencies.map(a => a.id));
  for (const signal of AGENCY_SIGNALS) {
    if (known.has(signal.id)) continue;
    const explicit = signal.explicit.test(text);
    if (explicit || signal.related.test(text)) {
      agencies.push({id:signal.id, relationship:explicit ? 'direct' : 'related', reason:explicit ? 'Agency named in supplied text' : 'Keyword-based possible impact — verify against bill text'});
      known.add(signal.id);
    }
  }
  if (!known.has('all-state-agencies') && !LIMITED_AGENCIES.test(text)) {
    const explicit = ALL_AGENCIES_EXPLICIT.test(text);
    if (explicit || (ALL_AGENCIES_POSSIBLE.test(text) && CROSS_AGENCY_CHANGE.test(text))) {
      agencies.push({
        id:'all-state-agencies',
        relationship:explicit ? 'direct' : 'related',
        reason:explicit
          ? 'The supplied wording applies to state agencies as a class; check exceptions in the bill text'
          : 'Possible statewide agency compliance or operations impact; scope requires full-text review'
      });
    }
  }
  const impacts = [...new Set([...toArray(bill.impacts), ...EFFECT_SIGNALS.filter(([,pattern])=>pattern.test(text)).map(([name])=>name)])];
  if (agencies.some(a=>a.id==='all-state-agencies') && !impacts.includes('Cross-agency scope')) impacts.push('Cross-agency scope');
  return {...bill, topics, agencies, impacts, ...(bill.constituencies == null ? {} : {constituencies: toArray(bill.constituencies)})};
}

// Overlay Luna's full-text review (tags.json entry) on a bill; an absent key keeps the caption-inferred value, an empty array means "none found".
export function applyLunaTags(bill, entry, registryNames = {}) {
  if (!entry || typeof entry !== 'object') return bill;
  const has = k => Array.isArray(entry[k]);
  const col = (k, f) => entry[k].map(f).filter(v => typeof v === 'string' && v);
  const out = {...bill, locations: Array.isArray(bill.locations) ? bill.locations : []};
  const fields = [];
  if (has('policy_tags')) { out.topics = col('policy_tags', x => x?.tag); fields.push('topics'); }
  const scope = entry.all_state_agencies?.applies === true;
  if (has('agencies') || entry.all_state_agencies != null) {
    const list = has('agencies') ? entry.agencies.filter(a => a && typeof a.id === 'string' && a.id !== SCOPE_AGENCY_ID).map(a => ({id:a.id, name:a.name || registryNames[a.id] || AGENCY_NAME[a.id] || a.id, relationship:a.impact === 'direct' ? 'direct' : 'inferred', reason:a.explanation || '', source:'luna'})) : (bill.agencies || []).filter(a => a.id !== SCOPE_AGENCY_ID);
    if (scope) list.push({id:SCOPE_AGENCY_ID, name:AGENCY_NAME[SCOPE_AGENCY_ID], relationship:'direct', reason:entry.all_state_agencies.explanation || '', source:'luna'});
    out.agencies = list; fields.push('agencies');
  }
  if (has('major_effects')) { out.impacts = col('major_effects', x => x?.label); fields.push('impacts'); }
  if (has('affected_groups')) { out.constituencies = col('affected_groups', x => x?.group); fields.push('constituencies'); }
  if (has('locations')) { out.locations = entry.locations.filter(l => l && typeof l.name === 'string'); fields.push('locations'); }
  out.luna = {reviewed_at:entry.reviewed_at, status:entry.status, summary:entry.summary, text_version:entry.text_version, unverified_omitted:entry.unverified_omitted || 0, fields};
  return out;
}

// Optional Luna extras (texas-bill-luna-extras-v1): plain-language headline plus extra search terms.
export function applyLunaExtras(bill, entry) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return bill;
  const out = {...bill};
  if (typeof entry.headline === 'string' && entry.headline.trim()) out.headline = entry.headline.trim().slice(0, 300);
  const terms = [];
  for (const key of ['search_terms', 'opposing_terms']) {
    if (!Array.isArray(entry[key])) continue;
    for (const t of entry[key]) {
      if (typeof t !== 'string') continue;
      const s = t.trim().slice(0, 60);
      if (s && !terms.includes(s)) terms.push(s);
    }
  }
  if (terms.length) out.search_terms = terms.slice(0, 20);
  return out;
}

// Related bills (texas-bill-related-v1): up to 5 known ids for a bill.
export function relatedFor(id, related, knownIds) {
  const bills = related && typeof related.bills === 'object' && related.bills && !Array.isArray(related.bills) ? related.bills : null;
  if (!bills || !Object.hasOwn(bills, id) || !Array.isArray(bills[id]) || !(knownIds instanceof Set)) return [];
  const out = [];
  for (const e of bills[id]) {
    const rid = e && typeof e === 'object' ? e.id : null;
    if (typeof rid === 'string' && rid !== id && knownIds.has(rid) && !out.includes(rid)) out.push(rid);
    if (out.length >= 5) break;
  }
  return out;
}

// Spot-check audit (texas-bill-luna-audit-v1) as one sentence, or null.
export function auditLine(audit) {
  if (!audit || typeof audit !== 'object') return null;
  const n = v => Number.isInteger(v) && v >= 0 ? v : null;
  const checked = n(audit.checked), agree = n(audit.agree);
  if (checked === null || checked < 1 || agree === null) return null;
  const minor = n(audit.minor_issues) || 0, major = n(audit.major_issues) || 0;
  const parts = [`Spot check: ${checked} ${checked === 1 ? 'review' : 'reviews'} re-checked independently`, `${agree} agreed`];
  if (minor) parts.push(`${minor} with minor issues`);
  if (major) parts.push(`${major} with major issues`);
  return parts.join(' · ');
}

// Member roster (texas-bill-members-v1): identity is the exact (chamber, TLO display name) pair; no surname guessing.
const ROLE_GROUPS = [['authors', 'origin'], ['coauthors', 'origin'], ['sponsors', 'other'], ['cosponsors', 'other']];
export function billChamber(bill) { return /^H/i.test(bill.id || '') ? 'house' : 'senate'; }

export function attachMembers(bill, roster) {
  const members = roster && typeof roster.members === 'object' && roster.members ? roster.members : null;
  if (!members) return bill;
  const origin = billChamber(bill), other = origin === 'house' ? 'senate' : 'house';
  const people = {};
  for (const [key, side] of ROLE_GROUPS) {
    const chamber = side === 'origin' ? origin : other;
    people[key] = bill[key] == null ? null : toArray(bill[key]).map(name => {
      const m = members[`${chamber}|${name}`];
      return {name, member: m && typeof m === 'object' ? m : null};
    });
  }
  const out = {...bill, people};
  const primary = people.authors?.[0]?.member;
  if (primary && !(bill.author_profile && Object.keys(bill.author_profile).length) && primary.years_served > 0) {
    out.author_profile = {seniority_years: primary.years_served, source: primary.links?.lrl || primary.links?.tlo};
  }
  return out;
}

function partyCounts(list) {
  const counts = {}; let unknown = 0;
  for (const p of list || []) { const party = p.member?.party; if (party) counts[party] = (counts[party] || 0) + 1; else unknown++; }
  return {counts, unknown};
}

// Tint by authorship party: blue/red for the primary author, purple when authors and coauthors span both parties.
export function authorshipParty(bill) {
  const people = bill.people;
  if (!people) return {tint:'unknown', label:'Author party unknown', detail:'Member roster not loaded.', authors:null, coauthors:null};
  const authors = partyCounts(people.authors), coauthors = partyCounts(people.coauthors);
  const known = new Set([...Object.keys(authors.counts), ...Object.keys(coauthors.counts)]);
  const unknown = authors.unknown + coauthors.unknown;
  const primary = people.authors?.[0]?.member?.party || null;
  let tint = 'unknown', label = 'Author party unknown';
  if (known.has('Democratic') && known.has('Republican')) { tint = 'bipartisan'; label = unknown ? 'Bipartisan authors · party data incomplete' : 'Bipartisan authors'; }
  else if (primary === 'Democratic') { tint = 'dem'; label = 'Democratic author'; }
  else if (primary === 'Republican') { tint = 'rep'; label = 'Republican author'; }
  else if (primary) { label = `${primary} author`; }
  const describe = (name, c) => {
    const parts = Object.entries(c.counts).map(([party, n]) => `${n} ${party}`);
    if (c.unknown) parts.push(`${c.unknown} unknown`);
    return parts.length ? `${name}: ${parts.join(', ')}` : '';
  };
  const detail = [describe('Authors', authors), describe('Coauthors', coauthors)].filter(Boolean).join(' · ') || 'No authors listed.';
  return {tint, label, detail, authors, coauthors};
}

export function memberSummary(member) {
  if (!member) return 'Not matched to the 90th Legislature roster';
  const bits = [];
  if (member.party) bits.push(member.party_basis === 'election' ? `${member.party} (2026 ballot, unofficial)` : member.party);
  if (member.district) bits.push(`${member.chamber === 'house' ? 'HD' : 'SD'} ${member.district}`);
  else if (member.new_to_chamber && member.service?.length) bits.push(`new to the ${member.chamber === 'house' ? 'House' : 'Senate'}`);
  if (member.years_served > 0) bits.push(`${member.years_served} ${member.years_served === 1 ? 'year' : 'years'} served`);
  if (member.first_year) bits.push(`since ${member.first_year}`);
  if (!member.service?.length) bits.push('member-elect; no prior service on record');
  return bits.join(' · ');
}

// Last action: TLO writes "MM/DD/YYYY H|S|E description". Rules are ordered most specific first; rank orders
// categories along the legislative path (withdrawn/vetoed rank by where they stop, not as progress).
export const LAST_ACTION_TYPES = [
  {key:'vetoed', label:'Vetoed', rank:9, test:/vetoed/},
  {key:'law', label:'Signed or effective', rank:10, test:/signed by the governor|^effective|filed without the governor|became law/},
  {key:'governor', label:'Sent to governor', rank:9, test:/sent to the governor|enrolled/},
  {key:'other_chamber', label:'Received in other chamber', rank:7, test:/received from the (house|senate)/},
  {key:'passed', label:'Passed chamber', rank:6, test:/^passed(?! to)|reported engrossed|^adopted/},
  {key:'withdrawn', label:'Withdrawn or failed', rank:0, test:/withdrawn|^failed|^died|^not again placed/},
  {key:'floor', label:'Floor action', rank:5, test:/read (2nd|second|3rd|third) time|passed to (engrossment|third)|laid on the table|postponed|^amended|amendment\(s\) (offered|adopted)/},
  {key:'calendar', label:'Placed on calendar', rank:4, test:/placed on|calendar|set on the/},
  {key:'reported', label:'Reported from committee', rank:3, test:/reported (favorably|unfavorably|from)|committee report|recommended for/},
  {key:'heard', label:'Heard in committee', rank:2.5, test:/considered in (public hearing|formal meeting)|testimony taken|left pending|heard in committee|hearing held/},
  {key:'scheduled', label:'Hearing scheduled', rank:2, test:/scheduled for (public )?hearing|hearing scheduled|meeting cancelled/},
  {key:'referred', label:'Referred to committee', rank:1, test:/referred to|read first time|recommitted/},
  {key:'filed', label:'Filed', rank:0.5, test:/^filed$|received by the secretary|^introduced|^filed\b/},
];
const ACTION_CHAMBER = {H:'House', S:'Senate', E:'Governor'};

// Splits bill ids into review states. Precedence: current > failed > in progress (retry) > reviewed.
// Without a worker status file, bills with published Luna tags count as reviewed.
export function reviewProgress(ids, status, taggedIds = []) {
  const list = v => Array.isArray(v) ? v.filter(x => typeof x === 'string') : [];
  const failedMap = status?.failed && typeof status.failed === 'object' && !Array.isArray(status.failed) ? status.failed : {};
  const current = status?.running && typeof status.current === 'string' ? status.current : null;
  const retry = new Set(list(status?.retry));
  const seen = new Set([...list(status?.reviewed), ...taggedIds]);
  const known = new Set(ids);
  const out = {current: known.has(current) ? current : null, upcoming: list(status?.upcoming).filter(id => known.has(id)),
    reviewed: [], inProgress: [], failed: [], notStarted: []};
  for (const id of ids) {
    if (id === out.current) continue;
    if (Object.hasOwn(failedMap, id)) out.failed.push({id, stage: typeof failedMap[id] === 'string' ? failedMap[id] : null});
    else if (retry.has(id)) out.inProgress.push(id);
    else if (seen.has(id)) out.reviewed.push(id);
    else out.notStarted.push(id);
  }
  return out;
}

// What the progress page shows. A bill on the retry list already has a published first-pass review and only
// waits for follow-up questions, so it counts as reviewed. A download failure means no text is posted yet.
export function reviewSummary(p) {
  const noText = p.failed.filter(f => f.stage === 'download').map(f => f.id);
  return {current: p.current, upcoming: p.upcoming, reviewed: [...p.reviewed, ...p.inProgress],
    questionsQueued: [...p.inProgress], noText, failed: p.failed.filter(f => f.stage !== 'download'),
    notStarted: [...p.notStarted]};
}

export function lastActionInfo(bill) {
  const raw = String(bill.last_action || '').trim();
  const m = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})\s+([HSE])\s+(.*)$/);
  const text = (m ? m[5] : raw).trim() || 'Filed';
  const date = m ? `${m[3]}-${m[1].padStart(2, '0')}-${m[2].padStart(2, '0')}` : (bill.last_action_date || bill.filed_at || '');
  const lower = text.toLowerCase();
  const type = LAST_ACTION_TYPES.find(t => t.test.test(lower)) || {key:'other', label:'Other action', rank:0.5};
  return {key:type.key, label:type.label, rank:type.rank, chamber:m ? ACTION_CHAMBER[m[4]] || null : null, date, text};
}

// Evidence-based procedural outlook, not a probability of enactment.
export function assessHearing(bill) {
  const a = toArray(bill.actions).filter(a => a != null).map(a => typeof a === 'string' ? a : a.description || '').join(' ').toLowerCase();
  const committee = bill.committee || (bill.status || '').match(/referred to (.+)/i)?.[1];
  const hearing = !!bill.hearing_date || /scheduled for (public )?hearing|hearing scheduled/.test(a);
  const held = /public hearing held|hearing conducted|testimony taken/.test(a);
  if (held) return {label:'Heard', level:4, detail:'A committee hearing is recorded in the supplied action history.', facts:['Hearing recorded']};
  if (hearing) return {label:'Scheduled', level:3, detail:'A hearing date or scheduled-hearing action is recorded.', facts:['Hearing scheduled']};
  if (committee) return {label:'Referred', level:2, detail:'Committee referral is confirmed; no hearing date is in the supplied data.', facts:['Committee referral']};
  return {label:'Not rated', level:0, detail:'No committee referral or hearing has been verified. A likelihood estimate would be premature.', facts:['Prefiling stage','Committee leadership not yet established']};
}

export function authorInfluence(bill) {
  const p = bill.author_profile || {};
  const factors = [];
  if (p.leadership_position) factors.push(p.leadership_position);
  if (p.committee_chair) factors.push('Committee chair');
  if (p.seniority_title) factors.push(p.seniority_title);
  if (p.seniority_years > 0) factors.push(`Approximately ${p.seniority_years} years of legislative service`);
  if (p.historical_bills_passed) factors.push(`${p.historical_bills_passed.toLocaleString()} bills passed (historical record)`);
  if (p.prior_role) factors.push(p.prior_role+' (prior session, not confirmed for 90R)');
  if (p.relevant_committee_member) factors.push('Relevant committee assignment');
  if (!factors.length) return {label:'Unassessed', factors:['Awaiting verified 90R committee and leadership assignments'],level:0};
  return {label:p.leadership_position || p.committee_chair ? 'High institutional access' : p.seniority_years >= 12 ? 'Established member' : 'Tenure documented', factors,level:p.leadership_position || p.committee_chair ? 3 : p.seniority_years >= 12 ? 2 : 1};
}

// One snapshot row -> the bill shape the tracker and the agent pages use; null for an invalid bill id.
export function normalizeBill(raw, profiles) {
  const key = String(raw.id || raw.number || raw.bill_number || '').replace(/\s/g, '').toUpperCase();
  if (!/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(key)) return null;
  const number = key.replace(/^(HJR|SJR|HCR|SCR|HB|SB|HR|SR)/, '$1 ');
  const chamber = key.startsWith('H') ? 'House' : 'Senate';
  const bill = {...raw, id:key, number, chamber,
    title:raw.title || raw.description || raw.caption || 'No caption available',
    caption:raw.caption || raw.description || raw.title || '',
    author:raw.author || raw.primary_author || 'Author not yet available',
    authors:memberNames(raw.authors ?? (typeof raw.author === 'string' && !raw.author.startsWith('Author not') ? raw.author : raw.primary_author)),
    coauthors:raw.coauthors == null ? null : memberNames(raw.coauthors),
    sponsors:raw.sponsors == null ? null : memberNames(raw.sponsors),
    cosponsors:raw.cosponsors == null ? null : memberNames(raw.cosponsors),
    author_profile:raw.author_profile || matchAuthorProfile(raw.author || raw.primary_author, profiles) || {},
    filed_at:raw.filed_at || raw.status_date || '',
    last_action:raw.last_action || raw.status || 'Filed',
    status:raw.status || 'Filed',
    last_action_date:raw.last_action_date || raw.filed_at || '',
    companions:normalizeCompanions(raw.companions, key),
    // Official Legislative Council subject index; null when the source does not report it (older snapshots).
    subjects:Array.isArray(raw.subjects)?[...new Set(raw.subjects.filter(s=>typeof s==='string'&&s.trim()).map(s=>s.trim().slice(0,120)))]:null};
  return autoTagBill(bill);
}

// Pasted text can carry invisible format characters (zero-width spaces, soft hyphens) or the official style
// "H.B. No. 267" / "House Bill 267"; both used to match nothing until the number was retyped by hand.
const BILL_WORDS = {'house bill': 'hb', 'senate bill': 'sb', 'house joint resolution': 'hjr', 'senate joint resolution': 'sjr',
  'house concurrent resolution': 'hcr', 'senate concurrent resolution': 'scr', 'house resolution': 'hr', 'senate resolution': 'sr'};
export function searchTerms(query) {
  const q = String(query || '').normalize('NFKC').replace(/[­᠎​-‏‪-‮⁠-⁤﻿]/g, '')
    .replace(/\s+/g, ' ').trim().toLowerCase();
  const ref = q.replace(/^(house|senate) (joint resolution|concurrent resolution|bill|resolution)\b/, m => BILL_WORDS[m] || m)
    .replace(/\bno\.?\s*(?=\d)/, '').replace(/[.\s]/g, '');
  return {q, compact: /^(hb|sb|hjr|sjr|hcr|scr|hr|sr)\d{1,5}$/.test(ref) ? ref : q.replace(/\s+/g, '')};
}

// Same-day order for "newest": bill type A-Z (HB, HCR, HJR, HR, SB, ...), then the higher number first, since
// numbers are assigned in filing order and the source has no filing time.
export function newestFirst(a, b) {
  const pa = String(a).match(/^([A-Z]+)(\d+)$/), pb = String(b).match(/^([A-Z]+)(\d+)$/);
  if (!pa || !pb) return String(a).localeCompare(String(b));
  return pa[1].localeCompare(pb[1]) || Number(pb[2]) - Number(pa[2]);
}

const BILL_KEY = /^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/;
const billNumber = id => id.replace(/^(HJR|SJR|HCR|SCR|HB|SB|HR|SR)/, '$1 ');

// Companions as the source lists them: [{id, author, relation}]. Malformed entries and self-references are dropped.
export function normalizeCompanions(value, selfId = '') {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value.flatMap(c => {
    const id = String(c?.id || '').replace(/\s/g, '').toUpperCase();
    if (!BILL_KEY.test(id) || id === selfId || seen.has(id)) return [];
    seen.add(id);
    return [{id, number: billNumber(id), author: typeof c.author === 'string' ? c.author.slice(0, 80) : '',
      relation: typeof c.relation === 'string' ? c.relation.slice(0, 40) : ''}];
  });
}

// Companion links in both directions: a bill lists its companion, and the companion may not list it back yet.
// Returns Map(id -> [{id, number, author, relation}]), sorted by id.
export function companionIndex(bills) {
  const byId = new Map(bills.map(b => [b.id, b]));
  const links = new Map();
  const add = (from, to) => {
    if (!links.has(from)) links.set(from, new Map());
    const known = links.get(from).get(to.id);
    // Prefer what the bill itself lists; fill gaps from the other side.
    links.get(from).set(to.id, known ? {...to, ...Object.fromEntries(Object.entries(known).filter(([, v]) => v))} : to);
  };
  // Own listings first, so a reverse link only fills fields the bill's own listing left empty.
  for (const b of bills) for (const c of b.companions || []) add(b.id, c);
  for (const b of bills) for (const c of b.companions || []) {
    const author = byId.get(b.id)?.authors?.[0] || '';
    add(c.id, {id: b.id, number: billNumber(b.id), author, relation: c.relation});
  }
  return new Map([...links].map(([id, m]) => [id, [...m.values()].sort((a, b) => a.id.localeCompare(b.id, 'en', {numeric: true}))]));
}

// Pull companions that are both in a list together: each bill plus every companion (and their companions) also in
// the list, placed where the first of them sits in the list's order. Returns [[b], [c, d], ...]; every bill once.
export function companionGroups(list, index) {
  const pos = new Map(list.map((b, i) => [b.id, i]));
  const placed = new Set(), groups = [];
  for (const b of list) {
    if (placed.has(b.id)) continue;
    const group = [], queue = [b];
    placed.add(b.id);
    while (queue.length) {
      const x = queue.shift();
      group.push(x);
      for (const c of index.get(x.id) || []) if (pos.has(c.id) && !placed.has(c.id)) { placed.add(c.id); queue.push(list[pos.get(c.id)]); }
    }
    groups.push(group.sort((x, y) => pos.get(x.id) - pos.get(y.id)));
  }
  return groups;
}

export function officialUrl(bill) {
  const number = (bill.id || bill.number || '').replace(/\s+/g,'').toUpperCase();
  return `https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill=${encodeURIComponent(number)}`;
}

// ---- Opening a bill from its card, and "Copy for AI" ----
// (Kept in this file: the static deployer ships a fixed list of src files.)
export const AGENT_BASE = 'https://agent.bills.ctharvey.me/';
export const agentUrl = bill => `${AGENT_BASE}bills/${encodeURIComponent(bill.id || String(bill.number || '').replace(/\s+/g, ''))}.md`;
const httpsUrl = value => { try { const u = new URL(String(value)); return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : ''; } catch { return ''; } };

// Text for pasting into an AI assistant: where to read the bill, and one neutral instruction.
export function aiPrompt(bill) {
  const versions = Array.isArray(bill.text_versions) ? bill.text_versions.filter(v => v && httpsUrl(v.html)) : [];
  const latest = versions[versions.length - 1];
  const textLine = latest
    ? `Official bill text${latest.name ? ` (${latest.name})` : ''}: ${httpsUrl(latest.html)}`
    : `Official bill history and text: ${officialUrl(bill)}`;
  return [`Texas ${bill.number} (90th Legislature): ${bill.title}`, '',
    `AI-readable version with history and review: ${agentUrl(bill)}`, textLine, '',
    'Summarize what this bill does, who it affects, and its current status, citing the bill text.'].join('\n');
}

// A plain left-click on empty card space opens the drawer; controls, links, selections and modified clicks do not.
export function cardClickOpens({interactive = false, selection = '', button = 0, metaKey = false, ctrlKey = false, shiftKey = false, altKey = false} = {}) {
  return !interactive && !String(selection).trim() && button === 0 && !metaKey && !ctrlKey && !shiftKey && !altKey;
}

const escText = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// A real link that opens the bill drawer on a plain click and keeps native behaviour for middle/ctrl-click.
export const openLinkHtml = (id, href, className, label) => `<a class="${escText(className)}" href="${escText(href)}" data-open="${escText(id)}">${escText(label)}</a>`;

// ---- Today view: activity by day, in America/Chicago ----
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const CHICAGO_DAY = new Intl.DateTimeFormat('sv-SE', {timeZone: 'America/Chicago'});

// 'YYYY-MM-DD' in America/Chicago for a Date or ISO timestamp; a bare date string is already a day.
export function chicagoDate(value) {
  if (typeof value === 'string' && DAY.test(value)) return value;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? '' : CHICAGO_DAY.format(date);
}

// Dated actions as [{day, text}]. action_dates only counts when it lines up with actions one for one.
function datedActions(bill) {
  const actions = toArray(bill.actions).filter(a => a != null).map(a => typeof a === 'string' ? a : a.description || '');
  const dates = Array.isArray(bill.action_dates) ? bill.action_dates : [];
  if (actions.length && dates.length === actions.length) {
    return actions.map((text, i) => ({day: String(dates[i] || '').slice(0, 10), text})).filter(a => DAY.test(a.day));
  }
  const day = String(bill.last_action_date || lastActionInfo(bill).date || '').slice(0, 10);
  return DAY.test(day) ? [{day, text: lastActionInfo(bill).text}] : [];
}

// Bills with an action dated `day`: [{bill, actions: [text, ...]}], in the order given.
export function activityOn(bills, day) {
  const out = [];
  for (const bill of bills) {
    const actions = datedActions(bill).filter(a => a.day === day).map(a => a.text);
    if (actions.length) out.push({bill, actions});
  }
  return out;
}

// The most recent day on or before `today` that has any activity, or null.
export function latestActivityDay(bills, today) {
  let best = null;
  for (const bill of bills) for (const {day} of datedActions(bill)) if (day <= today && (best === null || day > best)) best = day;
  return best;
}

export function topicCounts(bills) {
  const counts = new Map();
  for (const bill of bills) for (const topic of new Set(bill.topics || [])) counts.set(topic, (counts.get(topic) || 0) + 1);
  return [...counts].map(([topic, count]) => ({topic, count})).sort((a, b) => b.count - a.count || a.topic.localeCompare(b.topic));
}

// Groups activity rows by the type of their latest matched action, in the order of LAST_ACTION_TYPES, "Other" last.
export function groupByActionType(rows) {
  const groups = new Map();
  for (const row of rows) {
    const info = lastActionInfo({last_action: row.actions[row.actions.length - 1]});
    if (!groups.has(info.key)) groups.set(info.key, {key: info.key, label: info.label, rows: []});
    groups.get(info.key).rows.push(row);
  }
  const order = key => { const i = LAST_ACTION_TYPES.findIndex(t => t.key === key); return i < 0 ? LAST_ACTION_TYPES.length : i; };
  return [...groups.values()].sort((a, b) => order(a.key) - order(b.key));
}

// ---- "Copy page for AI": the view on screen as text an AI assistant can follow ----
export const AI_LIST_LIMIT = 50;
const VIEW_PAGES = {agencies: ['Agency index', 'agencies/index.md'], review: ['Full-text review progress', 'review-progress.md'],
  method: ['Scoring method', 'llms.txt'], saving: ['Saving your info', 'saving.md'], data: ['Data & imports', 'llms.txt']};

// ctx: {view, label, pageUrl, bill, bills, filters:{query,topic,agency,chamber}, agencyName, day}
export function pageAiText(ctx) {
  if (ctx.bill) return aiPrompt(ctx.bill);
  const f = ctx.filters || {};
  const lines = [];
  if (VIEW_PAGES[ctx.view]) {
    const [title, path] = VIEW_PAGES[ctx.view];
    lines.push(`Texas Bill Atlas (90th Legislature): ${title}`, `Page: ${ctx.pageUrl}`, '',
      `AI-readable version: ${AGENT_BASE}${path}`, `Everything available: ${AGENT_BASE}llms.txt`, '',
      'Use these links to answer my questions about Texas bills; open a bill\'s page for its details.');
    return lines.join('\n');
  }
  const described = [f.query && `search "${f.query}"`, f.topic && `topic ${f.topic}`,
    f.agency && `agency ${ctx.agencyName ? ctx.agencyName(f.agency) : f.agency}`, f.chamber && `chamber ${f.chamber}`].filter(Boolean);
  const params = new URLSearchParams();
  if (f.query) params.set('q', f.query);
  if (f.topic) params.set('topic', f.topic);
  if (f.agency) params.set('agency', f.agency);
  if (f.chamber) params.set('chamber', f.chamber);
  const search = [...params].length ? `${AGENT_BASE}search?${params}` : null;
  const bills = ctx.bills || [];
  lines.push(`Texas Bill Atlas (90th Legislature): ${ctx.label}${ctx.day ? ` for ${ctx.day}` : ''}${described.length ? ` (${described.join(', ')})` : ''}`,
    `Page: ${ctx.pageUrl}`, `${bills.length} ${bills.length === 1 ? 'bill' : 'bills'} shown.`, '');
  if (search) lines.push(`Same list, AI-readable: ${search}`);
  lines.push(`Everything available: ${AGENT_BASE}llms.txt`, '');
  for (const b of bills.slice(0, AI_LIST_LIMIT)) {
    const last = lastActionInfo(b);
    lines.push(`- ${b.number}: ${b.title}${b.headline ? ` | In brief: ${b.headline}` : ''} | Last action: ${last.text || last.label}${last.date ? ` (${last.date})` : ''} | ${agentUrl(b)}`);
  }
  if (bills.length > AI_LIST_LIMIT) lines.push(`- ...and ${bills.length - AI_LIST_LIMIT} more${search ? `; the full list is at ${search}` : ' (open the page link for the rest)'}.`);
  lines.push('', 'Use these links to answer my questions about these bills; open a bill\'s page for its full details.');
  return lines.join('\n');
}
