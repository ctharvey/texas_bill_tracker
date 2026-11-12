// "Near you": find a visitor's Texas House and Senate districts and county, and the bills tied to them.
// Everything here runs in the browser. A location is turned into district numbers and a county name, and only those
// are kept (in this device's storage); coordinates and addresses are never stored or put in a URL.

export const NEAR_KEY = 'texas-bill-atlas-near-you-v1';
export const HOUSE_COUNT = 150;
export const SENATE_COUNT = 31;
export const CENSUS_GEOCODER = 'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress';

const R = 6371008.8;
const rad = d => d * Math.PI / 180;

// Ray casting over one ring of [lon, lat] points.
function inRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function polygons(geometry) {
  if (!geometry) return [];
  if (geometry.type === 'Polygon') return [geometry.coordinates];
  if (geometry.type === 'MultiPolygon') return geometry.coordinates;
  return [];
}

export function contains(geometry, lon, lat) {
  return polygons(geometry).some(([outer, ...holes]) => inRing(lon, lat, outer) && !holes.some(h => inRing(lon, lat, h)));
}

// Metres from the point to the nearest edge of the geometry (local equirectangular approximation; fine at a few km).
export function edgeDistance(geometry, lon, lat) {
  const kx = Math.cos(rad(lat)) * rad(1) * R, ky = rad(1) * R;
  let best = Infinity;
  for (const polygon of polygons(geometry)) for (const ring of polygon) {
    for (let i = 1; i < ring.length; i++) {
      const ax = (ring[i - 1][0] - lon) * kx, ay = (ring[i - 1][1] - lat) * ky;
      const bx = (ring[i][0] - lon) * kx, by = (ring[i][1] - lat) * ky;
      const dx = bx - ax, dy = by - ay, len = dx * dx + dy * dy;
      const t = len ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len)) : 0;
      best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
    }
  }
  return best;
}

// The feature containing the point, by its `key` property, and how close the point is to that feature's edge.
// Simplified outlines can leave a point in no feature or two near a shared line; both cases report `near`.
export function locate(layer, key, lon, lat, margin) {
  const hits = (layer?.features || []).filter(f => contains(f.geometry, lon, lat));
  if (hits.length !== 1) {
    const nearest = (layer?.features || []).map(f => ({f, d: edgeDistance(f.geometry, lon, lat)})).sort((a, b) => a.d - b.d)[0];
    return nearest && nearest.d <= margin * 4 ? {id: String(nearest.f.properties[key]), near: true} : null;
  }
  const d = edgeDistance(hits[0].geometry, lon, lat);
  return {id: String(hits[0].properties[key]), near: d <= margin};
}

export function inTexasBox(lon, lat) {
  return Number.isFinite(lon) && Number.isFinite(lat) && lon > -107 && lon < -93.4 && lat > 25.7 && lat < 36.6;
}

// Districts and county for a point. `geo` = {house, senate, counties, tables}; margin in metres.
export function placeFromPoint(geo, lon, lat, {accuracy = 0} = {}) {
  if (!inTexasBox(lon, lat)) return {error: 'outside'};
  const margin = (geo.tables?.simplified_m?.districts || 100) + Math.min(Math.max(accuracy, 0), 2000) + 100;
  const cmargin = (geo.tables?.simplified_m?.counties || 250) + Math.min(Math.max(accuracy, 0), 2000) + 100;
  const house = locate(geo.house, 'district', lon, lat, margin);
  const senate = locate(geo.senate, 'district', lon, lat, margin);
  const county = locate(geo.counties, 'county', lon, lat, cmargin);
  if (!house || !senate) return {error: 'outside'};
  return {house: house.id, senate: senate.id, county: county?.id || null,
    near: Boolean(house.near || senate.near), countyNear: Boolean(county?.near), source: 'location'};
}

// Districts a county falls in, largest share first.
export function countyDistricts(tables, county) {
  const entry = tables?.counties?.[county];
  if (!entry) return null;
  const order = m => Object.entries(m || {}).sort((a, b) => b[1] - a[1] || Number(a[0]) - Number(b[0])).map(([d, share]) => ({district: d, share}));
  return {house: order(entry.house), senate: order(entry.senate)};
}

export function countiesOf(tables, chamber, district) {
  return Object.keys(tables?.districts?.[chamber]?.[district]?.counties || {}).sort();
}

const validDistrict = (value, count) => {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1 && n <= count ? String(n) : null;
};

// What may be saved: district numbers, a county name from the table, and how they were chosen. Never coordinates.
export function cleanNear(raw, tables) {
  if (!raw || typeof raw !== 'object') return null;
  const house = validDistrict(raw.house, HOUSE_COUNT), senate = validDistrict(raw.senate, SENATE_COUNT);
  if (!house && !senate) return null;
  const county = typeof raw.county === 'string' && (!tables || tables.counties?.[raw.county]) ? raw.county : null;
  const source = ['location', 'address', 'county', 'district'].includes(raw.source) ? raw.source : 'district';
  return {house, senate, county, source, near: raw.near === true};
}

// Roster members holding a district (normally one; none while a seat is vacant or a member-elect's district is unknown).
export function membersFor(roster, chamber, district) {
  if (!district) return [];
  return Object.entries(roster?.members || {}).filter(([, m]) => m?.chamber === chamber && String(m.district) === String(district))
    .map(([key, m]) => ({key, ...m}));
}

// One roster member by Texas Legislature Online code, or null. Codes are unique across both chambers.
export function memberByCode(roster, code) {
  if (!code) return null;
  const found = Object.entries(roster?.members || {}).find(([, m]) => m?.code === code);
  return found ? {key: found[0], ...found[1]} : null;
}

export const ROLES = [['authors', 'Author'], ['coauthors', 'Coauthor'], ['sponsors', 'Sponsor'], ['cosponsors', 'Cosponsor']];

// Bills a member filed or signed onto, with the member's role. Matches the roster entry attached to each bill
// (attachMembers joins by chamber and display name), so a same-name member of the other chamber never matches.
export function billsByMember(bills, member) {
  if (!member?.code) return [];
  const out = [];
  for (const bill of bills) {
    for (const [key, role] of ROLES) {
      if ((bill.people?.[key] || []).some(p => p.member?.code === member.code && p.member?.chamber === member.chamber)) {
        out.push({bill, role}); break;
      }
    }
  }
  return out;
}

const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const CAPTION_COUNTY = /\b([A-Z][A-Za-z]+(?:[ -][A-Z][A-Za-z]+)?) County\b/g;

export function gazetteer(tables) {
  const counties = new Map(Object.keys(tables?.counties || {}).map(c => [norm(c), c]));
  const places = new Map(Object.entries(tables?.places || {}).map(([name, p]) => [norm(name), {name, counties: p.counties || []}]));
  return {counties, places};
}

// A place name as the review wrote it -> {county} or {place, counties}. "X County" is a county; a bare name is a city or
// CDP only (so "Austin" is the city, never Austin County). No fuzzy matching.
export function resolvePlace(name, gaz) {
  const text = norm(name).replace(/^(?:the )?(?:city|town|village) of /, '');
  const county = text.match(/^(.*) county(?: texas)?$/);
  if (county) {
    const found = gaz.counties.get(county[1]);
    return found ? {county: found} : null;
  }
  const place = gaz.places.get(text.replace(/ texas$/, ''));
  return place ? {place: place.name, counties: place.counties} : null;
}

// Why a bill names the visitor's area, or null. `area` = {counties: [...], exact: bool}: exact when the visitor's own
// county is known, otherwise every county of their district. Statewide bills never match.
export function areaReasons(bill, area, gaz) {
  const wanted = new Set(area?.counties || []);
  if (!wanted.size) return null;
  const reasons = [];
  const seen = new Set();
  const add = (text, county) => { if (!seen.has(text)) { seen.add(text); reasons.push({text, county}); } };
  for (const loc of bill.locations || []) {
    if (loc?.kind !== 'named_place') continue;
    const hit = resolvePlace(loc.name, gaz);
    if (hit?.county && wanted.has(hit.county)) add(`Names ${hit.county} County`, hit.county);
    else if (hit?.place) {
      const inside = hit.counties.filter(c => wanted.has(c));
      if (inside.length) add(`Names ${hit.place} (${inside.join(', ')} County)`, inside[0]);
    }
  }
  for (const m of String(bill.caption || '').matchAll(CAPTION_COUNTY)) {
    const county = gaz.counties.get(norm(m[1]));
    if (county && wanted.has(county)) add(`Names ${county} County`, county);
  }
  return reasons.length ? reasons : null;
}

export function areaFor(near, tables) {
  if (!near) return null;
  if (near.county) return {counties: [near.county], exact: true};
  const fromHouse = near.house ? countiesOf(tables, 'house', near.house) : [];
  return {counties: fromHouse.length ? fromHouse : (near.senate ? countiesOf(tables, 'senate', near.senate) : []), exact: false};
}

export function censusUrl(address, callback) {
  const params = new URLSearchParams({address: String(address).slice(0, 200), benchmark: 'Public_AR_Current',
    format: 'jsonp', callback});
  return `${CENSUS_GEOCODER}?${params}`;
}

// First match's coordinates from a Census geocoder reply, or null.
export function censusPoint(reply) {
  const match = reply?.result?.addressMatches?.[0];
  const x = Number(match?.coordinates?.x), y = Number(match?.coordinates?.y);
  return Number.isFinite(x) && Number.isFinite(y) ? {lon: x, lat: y, matched: String(match.matchedAddress || '')} : null;
}
