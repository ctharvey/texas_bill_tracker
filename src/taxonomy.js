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
    last_action_date:raw.last_action_date || raw.filed_at || ''};
  return autoTagBill(bill);
}

export function officialUrl(bill) {
  const number = (bill.id || bill.number || '').replace(/\s+/g,'').toUpperCase();
  return `https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill=${encodeURIComponent(number)}`;
}
