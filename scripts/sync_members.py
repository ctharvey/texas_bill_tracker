"""Build the 90R member roster: Texas Legislature Online identity joined to Legislative Reference Library history.

Identity and display names come from capitol.texas.gov (the names bill histories use). Party, district and
service history come from lrl.texas.gov records through the 89th Legislature. Members-elect with no LRL
record keep party and district unknown; nothing is inferred from names, districts or bill content.
Standard library only, so the server can run it from the deployer's bare repository.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import http.cookiejar
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'members.json'
LEGISLATURE = '90'
SESSION_START_YEAR = 2027
TLO = 'https://capitol.texas.gov/Members/'
LRL = 'https://lrl.texas.gov/legeLeaders/members/'
UA = {'User-Agent': 'Mozilla/5.0 (compatible; texas-bill-atlas roster import; +https://bills.ctharvey.me)'}
SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv'}
PARTY = {'D': 'Democratic', 'R': 'Republican'}
LINK = re.compile(r"MemberInfo\.aspx\?Leg=(\d+)&(?:amp;)?Chamber=([HS])&(?:amp;)?Code=(\w+)'>\s*([^<]+?)\s*</a>")


class Fetcher:
    def __init__(self, delay: float = 1.0):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.delay, self.last = delay, 0.0

    def __call__(self, url: str, data: dict | None = None) -> str:
        wait = self.last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        try:
            with self.opener.open(urllib.request.Request(url, data=body, headers=UA), timeout=60) as response:
                return response.read().decode('utf-8', 'replace')
        finally:
            self.last = time.monotonic()


def tokens(name: str) -> list[str]:
    plain = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    plain = re.sub(r'"[^"]*"', ' ', plain)
    return [t for t in re.sub(r"[^a-z' ]", ' ', plain.replace('-', ' ')).replace("'", '').split()
            if t not in SUFFIXES and len(t) > 1]


def nickname(name: str) -> str | None:
    found = re.search(r'"([^"]+)"', name or '')
    return tokens(found.group(1))[0] if found and tokens(found.group(1)) else None


def same_person(full_name: str, display_name: str, lrl_name: str) -> bool:
    """Surname must equal the TLO display surname; the given name must agree (nickname or prefix allowed)."""
    surname = tokens(display_name.split(',')[0])
    theirs = tokens(lrl_name)
    if not surname or theirs[-len(surname):] != surname or len(theirs) <= len(surname):
        return False
    mine = tokens(full_name)
    given = {g for g in (mine[0] if mine else None, nickname(full_name)) if g}
    if ',' in display_name:
        given |= set(tokens(display_name.split(',', 1)[1])[:1])
    other = theirs[0]
    return any(g == other or (min(len(g), len(other)) >= 3 and (g.startswith(other) or other.startswith(g))) for g in given)


def tlo_roster(fetch: Fetcher) -> list[dict]:
    members = []
    for chamber in 'HS':
        url = f'{TLO}Members.aspx?Chamber={chamber}'
        page = fetch(url)
        form = dict(re.findall(r'name="(__[A-Z]+)" id="__[A-Z]+" value="([^"]*)"', page))
        page = fetch(url, {**form, 'ddlLegislature': LEGISLATURE, 'btnGo': 'Go'})
        rows = [(code, html.unescape(name).strip()) for leg, ch, code, name in LINK.findall(page) if leg == LEGISLATURE]
        if not rows:
            raise RuntimeError(f'No {LEGISLATURE}th Legislature members listed for chamber {chamber}')
        for code, display in rows:
            info = fetch(f'{TLO}MemberInfo.aspx?Leg={LEGISLATURE}&Chamber={chamber}&Code={code}')
            title = re.search(r'<h1>Information for (Rep\.|Sen\.|Lt\. Gov\.)\s*(.*?)</h1>', info, re.S)
            members.append({'chamber': 'house' if chamber == 'H' else 'senate', 'code': code, 'display_name': display,
                            'full_name': html.unescape(title.group(2)).strip() if title else None,
                            'role': {'Rep.': 'representative', 'Sen.': 'senator', 'Lt. Gov.': 'lieutenant_governor'}
                            .get(title.group(1)) if title else None})
    return members


def cells(cell: str) -> list[str]:
    return [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', part))).strip()
            for part in re.split(r'<br\s*/?>', cell) if re.sub(r'<[^>]+>|\s', '', part)]


def lrl_rows(page: str) -> list[dict]:
    found = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', page, re.S)[1:]:
        # The link text, not the img alt: a quoted nickname ("Chuy") ends the alt attribute early.
        anchor = re.search(r'<a [^>]*memberID=(\d+)[^>]*>(.*?)</a>', row, re.S)
        member_id = re.search(r'memberID=(\d+)', row)
        full = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', anchor.group(2))).split()) if anchor else ''
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if not (full and member_id and len(tds) >= 8):
            continue
        district, chambers, years, sessions, parties = (cells(c) for c in tds[1:6])
        # LRL can list fewer districts than stints (one district for a House-then-Senate career), so align on
        # chambers and only attach a district when the counts agree.
        at = lambda values, i: values[i] if len(values) == len(chambers) else None
        stints = [{'chamber': {'H': 'house', 'S': 'senate'}.get(c, c), 'district': at(district, i),
                   'years': at(years, i) or '', 'legislatures': at(sessions, i), 'party': at(parties, i)}
                  for i, c in enumerate(chambers)]
        if len(district) == 1 and stints:
            stints[0]['district'] = district[0]  # A single listed district is the current one.
        found.append({'lrl_id': member_id.group(1), 'name': full, 'stints': stints})
    return found


def service_years(stints: list[dict]) -> int | None:
    total, seen = 0, False
    for stint in stints:
        span = re.fullmatch(r'(\d{4})\s*-\s*(\d{4})', stint['years'])
        if span:
            seen = True
            total += max(0, min(int(span.group(2)), SESSION_START_YEAR) - int(span.group(1)))
    return total if seen else None


def build(fetch: Fetcher) -> dict:
    members = tlo_roster(fetch)
    pool = {}
    for chamber in 'HS':
        for row in lrl_rows(fetch(LRL + 'membersearch.cfm?' + urllib.parse.urlencode({'leg': '89', 'chamber': chamber}))):
            pool[row['lrl_id']] = row

    def resolve(member: dict, candidates: list[dict]) -> dict | None:
        exact = [r for r in candidates if tokens(r['name']) == tokens(member['full_name'])]
        hits = exact or [r for r in candidates if same_person(member['full_name'], member['display_name'], r['name'])]
        return hits[0] if len(hits) == 1 else None

    roster, unresolved = {}, []
    for member in members:
        if member['role'] == 'lieutenant_governor' or not member['full_name']:
            continue
        record = resolve(member, list(pool.values()))
        if record is None:
            surname = member['display_name'].split(',')[0]
            history = lrl_rows(fetch(LRL + 'membersearch.cfm?' + urllib.parse.urlencode({'last': surname})))
            record = resolve(member, history)
        latest = record['stints'][0] if record and record['stints'] else None
        same_chamber = bool(latest and latest['chamber'] == member['chamber'])
        party = latest['party'] if latest else None
        roster[f"{member['chamber']}|{member['display_name']}"] = {
            **{k: member[k] for k in ('chamber', 'code', 'display_name', 'full_name')},
            'party': PARTY.get(party, party) if party else None,
            'party_source': 'Texas Legislative Reference Library, latest recorded service' if party else None,
            'district': latest['district'] if same_chamber else None,
            'service': record['stints'] if record else [],
            'first_year': min((int(s['years'][:4]) for s in record['stints'] if s['years'][:4].isdigit()), default=None) if record else None,
            'years_served': service_years(record['stints']) if record else None,
            'new_to_chamber': not same_chamber,
            'lrl_id': record['lrl_id'] if record else None,
            'links': {'tlo': f"{TLO}MemberInfo.aspx?Leg={LEGISLATURE}&Chamber={member['chamber'][0].upper()}&Code={member['code']}",
                      **({'lrl': f"{LRL}memberDisplay.cfm?memberID={record['lrl_id']}"} if record else {})},
        }
        if record is None:
            unresolved.append(member['display_name'])
    counts = {c: sum(1 for m in roster.values() if m['chamber'] == c) for c in ('house', 'senate')}
    if counts['house'] < 140 or counts['senate'] < 25:
        raise RuntimeError(f'Roster looks incomplete: {counts}')
    return {'format': 'texas-bill-members-v1', 'session': '90R',
            'generated_at': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
            'sources': [TLO + 'Members.aspx', LRL + 'lrlhome.cfm'], 'counts': counts,
            'without_service_record': sorted(unresolved), 'members': dict(sorted(roster.items()))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    roster = build(Fetcher())
    temp = args.out.with_suffix('.json.tmp')
    temp.write_text(json.dumps(roster, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(temp, args.out)
    print(json.dumps({'counts': roster['counts'], 'without_service_record': len(roster['without_service_record'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
