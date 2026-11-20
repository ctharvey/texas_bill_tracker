"""Build one RSS feed per bill, and one per legislator, from the live snapshot, so people can follow bills and
legislators without an account. Also builds the statute index (live/statutes) from the bill text.

Stateless: item identity comes from (bill, date, action text), so readers see only new actions. A feed file
is rewritten only when its content changes. Standard library only (the data unit extracts it via git show).
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from xml.sax.saxutils import escape

import pages

BILL_ID = re.compile(r"(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}")
SITE = "https://billatlas.org/"


def rfc822(day: str | None) -> str | None:
    try:
        moment = dt.datetime.fromisoformat(str(day)[:10]).replace(hour=12, tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None
    return moment.strftime("%a, %d %b %Y %H:%M:%S +0000")


def bill_items(bill: dict) -> list[dict]:
    actions = [a for a in bill.get("actions") or [] if isinstance(a, str) and a.strip()]
    dates = bill.get("action_dates") if isinstance(bill.get("action_dates"), list) else []
    if len(dates) != len(actions):
        # Older snapshots: only the most recent action has a known date.
        dates = [None] * (len(actions) - 1) + [bill.get("last_action_date")] if actions else []
    seen, items = {}, []
    for text, day in zip(actions, dates):
        base = f"{bill['id']}|{day or ''}|{text}"
        seen[base] = seen.get(base, 0) + 1  # The same text can recur on one day; keep each distinct.
        digest = hashlib.sha256(f"{base}|{seen[base]}".encode("utf-8")).hexdigest()[:16]
        items.append({"bill": bill["id"], "text": text, "date": day, "guid": f"{bill['id']}-{digest}",
                      "caption": bill.get("caption") or bill.get("title") or ""})
    items.reverse()  # Newest first.
    return items


def review_items(bill: dict, review: dict | None) -> list[dict]:
    """One item per published Luna full-text review; a re-review (new reviewed_at or text version) is a new item."""
    if not isinstance(review, dict) or not review.get("reviewed_at"):
        return []
    stamp, version = str(review["reviewed_at"]), str(review.get("text_version") or "")
    digest = hashlib.sha256(f"{bill['id']}|review|{stamp}|{version}".encode("utf-8")).hexdigest()[:16]
    topics = [t.get("tag") if isinstance(t, dict) else t for t in review.get("policy_tags") or []]
    summary = str(review.get("summary") or "").strip()
    detail = " ".join(filter(None, [summary, f"Topics: {', '.join(str(t) for t in topics if t)}." if topics else "",
                                    "Automated tags from the bill's full text; confirm on Texas Legislature Online."]))
    return [{"bill": bill["id"], "text": f"Full-text review published{f' ({version} text)' if version else ''}",
             "date": stamp[:10], "guid": f"{bill['id']}-review-{digest}", "caption": detail}]


def load_reviews(path: Path | None) -> dict:
    """Published Luna tags keyed by bill id; missing or malformed files mean no review items, never an error."""
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("format") != "texas-bill-luna-tags-v1" or not isinstance(data.get("bills"), dict):
        return {}
    return {k: v for k, v in data["bills"].items() if isinstance(v, dict)}


def all_items(bill: dict, review: dict | None = None) -> list[dict]:
    items = bill_items(bill) + review_items(bill, review)
    items.sort(key=lambda i: i["date"] or "", reverse=True)  # Stable: same-day actions keep their order.
    return items


def render_rss(title: str, link: str, description: str, items: list[dict], site: str = SITE) -> str:
    newest =max(items, key=lambda i: i["date"] or "", default=None)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0">', "<channel>",
             f"<title>{escape(title)}</title>", f"<link>{escape(link)}</link>",
             f"<description>{escape(description)}</description>", "<language>en-us</language>",
             "<ttl>60</ttl>"]
    if newest and rfc822(newest["date"]):
        lines.append(f"<lastBuildDate>{rfc822(newest['date'])}</lastBuildDate>")
    for item in items:
        lines += ["<item>", f"<title>{escape(item['bill'] + ': ' + item['text'])}</title>",
                  f"<link>{escape(site + 'bill/' + item['bill'])}</link>",
                  f"<description>{escape(item['caption'])}</description>",
                  f'<guid isPermaLink="false">{escape(item["guid"])}</guid>']
        if rfc822(item["date"]):
            lines.append(f"<pubDate>{rfc822(item['date'])}</pubDate>")
        lines.append("</item>")
    lines += ["</channel>", "</rss>", ""]
    return "\n".join(lines)


def bill_feed(bill: dict, site: str = SITE, review: dict | None = None) -> str:
    return render_rss(f"{bill['id']} · Texas Bill Atlas", f"{site}bill/{bill['id']}",
                      (bill.get("caption") or bill.get("title") or "")[:500]
                      + " Unofficial; confirm on Texas Legislature Online.", all_items(bill, review), site)


MEMBER_CODE = re.compile(r"A\d{3,5}")
# Same join as the site (taxonomy.attachMembers): authors and coauthors serve in the bill's chamber, sponsors and
# cosponsors in the other one, matched by the roster's "<chamber>|<display name>" key.
ROLES = (("authors", "Author", "origin"), ("coauthors", "Coauthor", "origin"),
         ("sponsors", "Sponsor", "other"), ("cosponsors", "Cosponsor", "other"))
MEMBER_FEED_ITEMS = 200


def load_roster(path: Path | None) -> dict:
    """Roster entries keyed by "<chamber>|<name>"; a missing or malformed file means no member feeds, never an error."""
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    members = data.get("members") if isinstance(data, dict) else None
    return {k: v for k, v in members.items() if isinstance(v, dict)} if isinstance(members, dict) else {}


def names(value) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return [s.strip() for s in re.split(r"[;,]", value) if s.strip()] if isinstance(value, str) else []


def member_roles(bill: dict, roster: dict) -> dict[str, str]:
    """Member code -> first role (author before coauthor before sponsor before cosponsor) on this bill."""
    origin = "house" if str(bill.get("id", "")).upper().startswith("H") else "senate"
    other = "senate" if origin == "house" else "house"
    found: dict[str, str] = {}
    for key, role, side in ROLES:
        chamber = origin if side == "origin" else other
        for name in names(bill.get(key)):
            member = roster.get(f"{chamber}|{name}")
            code = member.get("code") if member else None
            if isinstance(code, str) and member.get("chamber") == chamber:
                found.setdefault(code, role)
    return found


def member_title(member: dict) -> str:
    return f"{'Rep.' if member.get('chamber') == 'house' else 'Sen.'} {member.get('full_name') or member.get('display_name')}"


def member_feed(member: dict, bills: list[tuple[dict, str]], site: str = SITE, reviews: dict | None = None) -> str:
    """Every action on the bills a legislator filed or signed onto, newest first, capped at MEMBER_FEED_ITEMS."""
    reviews = reviews or {}
    title = member_title(member)
    items = []
    for bill, role in bills:
        for item in all_items(bill, reviews.get(bill["id"])):
            items.append({**item, "caption": f"{title} · {role}. {item['caption']}"})
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return render_rss(f"{title} · Texas Bill Atlas", f"{site}#member?code={member['code']}",
                      f"Actions on bills {title} filed or signed onto in the 90th Legislature. "
                      "Unofficial; confirm on Texas Legislature Online.", items[:MEMBER_FEED_ITEMS], site)


def write_member_feeds(snapshot: dict, roster: dict, out_dir: Path, site: str = SITE,
                       reviews: dict | None = None) -> tuple[int, int]:
    """One feed per coded roster member (empty when they have no bills yet, so a feed link never breaks)."""
    by_code, bills = member_bills(snapshot, roster)
    if not by_code:
        return 0, 0
    out_dir.mkdir(parents=True, exist_ok=True)
    written = unchanged = 0
    for code, member in by_code.items():
        if write_if_changed(out_dir / f"{code}.xml", member_feed(member, bills[code], site, reviews)):
            written += 1
        else:
            unchanged += 1
    return written, unchanged


# Member pages (SEO chunk 5 phase 1): live/share/member/<code>.html, served at /member/<code>/<slug> inside the site
# shell, and taken over by the app's member view.
_MEMBER_PAGE_NAME = re.compile(r"A\d{3,5}\.html")
MEMBER_CAPTION_MAX = 160


def slugify(text: str) -> str:
    """As the app's slugify (src/core/routes.js): accents dropped, lower case, dashes, at most 60 characters."""
    import unicodedata
    folded = re.sub("[̀-ͯ]", "", unicodedata.normalize("NFKD", str(text or ""))).lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:60].rstrip("-")


def member_path(member: dict) -> str:
    """The member's address without the site: member/<code>/<slug>, or member/<code> when the name has no slug."""
    slug = slugify(member.get("full_name") or member.get("display_name") or "")
    return f"member/{member['code']}" + (f"/{slug}" if slug else "")


def _newest_action_first(bill: dict) -> tuple:
    """Newest last action first, then bill type and number (highest first), so the order never depends on input."""
    match = re.fullmatch(r"([A-Z]+)(\d+)", str(bill.get("id", "")))
    day = str(bill.get("last_action_date") or "")[:10]
    return (-int(day.replace("-", "")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else 0,
            match.group(1) if match else "", -int(match.group(2)) if match else 0)


def member_page(member: dict, bills: list[tuple[dict, str]], shell: str, site: str = SITE) -> str:
    """One legislator's page inside the site shell: who they are, where the party comes from, and every bill they
    author, coauthor or sponsor in the snapshot, newest action first."""
    a = lambda value: escape(str(value), {'"': "&quot;"})
    code, title = member["code"], member_title(member)
    url = f"{site}{member_path(member)}"
    feed = f"{site}live/feeds/members/{code}.xml"
    house = member.get("chamber") == "house"
    chamber = "Texas House" if house else "Texas Senate"
    district = str(member.get("district") or "")
    party = str(member.get("party") or "")
    if party and member.get("party_basis") == "election":
        party += " (2026 ballot, unofficial)"
    where = " · ".join([chamber, f"District {district}" if district else "district not recorded yet"]
                       + ([party] if party else []))
    groups: dict[str, list[dict]] = {role: [] for _, role, _ in ROLES}
    for bill, role in bills:
        groups.setdefault(role, []).append(bill)
    for rows in groups.values():
        rows.sort(key=_newest_action_first)
    total = sum(len(rows) for rows in groups.values())
    first = [b for rows in groups.values() for b in rows][:6]
    listed = ", ".join(bill_number(b["id"]) for b in first) + (f" and {total - 6} more" if total > 6 else "")
    description = clip(f"{title}, {where}. " + (f"{total} bill{'s' if total != 1 else ''} in the 90th Legislature: "
                                               f"{listed}." if total else "No bills in the 90th Legislature yet."),
                       SHARE_DESCRIPTION_MAX)
    image = f"{site}{SITE_CARD}"
    meta = [("property", "og:type", "profile"), ("property", "og:site_name", "Texas Bill Atlas"),
            ("property", "og:title", title), ("property", "og:description", description), ("property", "og:url", url),
            ("property", "og:image", image), ("property", "og:image:width", "1200"), ("property", "og:image:height", "630"),
            ("property", "og:image:alt", "Texas Bill Atlas"), ("name", "twitter:card", "summary_large_image"),
            ("name", "twitter:title", title), ("name", "twitter:description", description), ("name", "twitter:image", image),
            ("name", "twitter:image:alt", "Texas Bill Atlas"), ("name", "description", description)]
    tags = "\n".join(f'<meta {kind}="{n}" content="{a(value)}">' for kind, n, value in meta)
    head = f"""
<title>{escape(clip(title, SHARE_TITLE_MAX))} · Texas Bill Atlas</title>
<link rel="canonical" href="{a(url)}">
<link rel="alternate" type="application/rss+xml" title="{a(title)}" href="{a(feed)}">
{SHELL_ICONS}
{tags}
"""
    body = [f"<h1>{escape(title)}</h1>", f"<p>{escape(where)}</p>"]
    if member.get("party") and member.get("party_source"):
        body.append(f"<p>Party as recorded by {escape(str(member['party_source']))}.</p>")
    service = [s for s in member.get("service") or [] if isinstance(s, dict)]
    if service:
        stints = "\n".join(f"<li>{'House' if s.get('chamber') == 'house' else 'Senate'} District "
                           f"{escape(str(s.get('district') or '?'))}, {escape(str(s.get('years') or ''))}"
                           + (f" ({escape(re.sub(r'^(.+) - \1$', r'\1', str(s['legislatures'])))} Legislature)"
                              if s.get("legislatures") else "")
                           + "</li>" for s in service)
        body += ["<h2>Service</h2>", f"<ul>\n{stints}\n</ul>"]
    else:
        body.append("<p>Member-elect; no prior service on record.</p>")
    links = [f'<a href="{a(u)}" rel="noopener noreferrer">{label}</a>'
             for u, label in (((member.get("links") or {}).get("tlo"), "Texas Legislature Online"),
                              ((member.get("links") or {}).get("lrl"), "Legislative Reference Library"))
             if isinstance(u, str) and u.startswith("https://")]
    links.append(f'<a href="{a(feed)}">RSS feed of actions on their bills</a>')
    body.append(f"<p>{' · '.join(links)}</p>")
    body.append(f"<p>{'Representatives author and coauthor House bills and sponsor Senate bills that reach the House.' if house else 'Senators author and coauthor Senate bills and sponsor House bills that reach the Senate.'} "
                "Sponsors and cosponsors are listed once a bill crosses chambers, so early in the session most bills "
                "show authors only.</p>")
    for role, rows in groups.items():
        if not rows:
            continue
        items = "\n".join(
            f'<li><a href="{a(f"{site}bill/{b["id"]}")}">{escape(bill_number(b["id"]))}</a>'
            + (f": {escape(clip(b.get('caption') or b.get('title') or '', MEMBER_CAPTION_MAX))}"
               if b.get("caption") or b.get("title") else "")
            + (f" Last action {escape(str(b['last_action_date'])[:10])}." if b.get("last_action_date") else "")
            + "</li>" for b in rows)
        body += [f"<h2>{escape(role)} ({len(rows)})</h2>", f"<ul>\n{items}\n</ul>"]
    if not total:
        body.append("<p>No bills by this member in this snapshot yet.</p>")
    content = (f'\n<article class="member-page static-page" aria-label="{a(title)}">\n' + "\n".join(body)
               + "\n</article>\n")
    version = hashlib.sha256((head + content).encode()).hexdigest()[:12]
    return pages.render_page(shell, head=f'{head}<meta name="page-version" content="{version}">', content=content,
                             view=f"member:{code}")


def member_bills(snapshot: dict, roster: dict) -> tuple[dict[str, dict], dict[str, list]]:
    """Coded roster members by code, and each one's (bill, role) pairs: the join the member feeds use."""
    by_code = {m["code"]: m for m in roster.values() if MEMBER_CODE.fullmatch(str(m.get("code", "")))}
    bills: dict[str, list] = {code: [] for code in by_code}
    for bill in snapshot.get("bills") or []:
        if isinstance(bill, dict) and BILL_ID.fullmatch(str(bill.get("id", ""))):
            for code, role in member_roles(bill, roster).items():
                if code in bills:
                    bills[code].append((bill, role))
    return by_code, bills


def write_member_pages(snapshot: dict, roster: dict, out_dir: Path, site: str = SITE,
                       shell: str | None = None) -> tuple[int, int, int]:
    """One page per coded roster member, bills or not. Without the deployed shell nothing is written or removed: the
    gateway then serves the app, which draws the member itself. Pages for codes no longer in the roster are removed;
    an empty roster never empties the folder."""
    if shell is None:
        return 0, 0, 0
    by_code, bills = member_bills(snapshot, roster)
    if not by_code:
        return 0, 0, 0
    out_dir.mkdir(parents=True, exist_ok=True)
    written = unchanged = removed = 0
    for code, member in by_code.items():
        if write_if_changed(out_dir / f"{code}.html", member_page(member, bills[code], shell, site)):
            written += 1
        else:
            unchanged += 1
    for path in out_dir.iterdir():
        if _MEMBER_PAGE_NAME.fullmatch(path.name) and path.name[:-5] not in by_code:
            path.unlink(missing_ok=True)
            removed += 1
    return written, unchanged, removed


def write_if_changed(path: Path, text: str) -> bool:
    try:
        if path.read_text("utf-8") == text:
            return False
    except OSError:
        pass
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".feed-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


def write_feeds(snapshot: dict, out_dir: Path, site: str = SITE, reviews: dict | None = None) -> tuple[int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = unchanged = 0
    reviews = reviews or {}
    for bill in snapshot.get("bills") or []:
        if not isinstance(bill, dict) or not BILL_ID.fullmatch(str(bill.get("id", ""))):
            continue  # Never build a file name from an unexpected id.
        if write_if_changed(out_dir / f"{bill['id']}.xml", bill_feed(bill, site, reviews.get(bill["id"]))):
            written += 1
        else:
            unchanged += 1
    return written, unchanged


def sitemap(snapshot: dict, site: str = SITE, law_keys=(), members=()) -> str:
    """The home page, every bill's address (/bill/<ID>), each dated by its last action, every law section a bill
    changes (/law/<CODE>/<section>) and each member's page (/member/<code>/<slug>). robots.txt points here."""
    rows = [f"  <url><loc>{escape(site)}</loc></url>"]
    for bill in snapshot.get("bills") or []:
        if not isinstance(bill, dict) or not BILL_ID.fullmatch(str(bill.get("id", ""))):
            continue
        day = str(bill.get("last_action_date") or "")[:10]
        lastmod = f"<lastmod>{day}</lastmod>" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else ""
        rows.append(f"  <url><loc>{escape(site)}bill/{bill['id']}</loc>{lastmod}</url>")
    for key in sorted(k for k in law_keys if STATUTE_KEY.fullmatch(k) and k[:2] in CODE_NAME):
        code, number = key.split(" ")
        rows.append(f"  <url><loc>{escape(site)}law/{code}/{number}</loc></url>")
    for member in sorted((m for m in members if MEMBER_CODE.fullmatch(str(m.get("code", "")))), key=lambda m: m["code"]):
        rows.append(f"  <url><loc>{escape(site + member_path(member))}</loc></url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


API_DOCS = ("api-catalog.json", "openapi.json", "auth.md")


def write_api_docs(live_dir: Path, source: Path = Path(__file__).resolve().parent / "api") -> None:
    """Copy the RFC 9727 API catalog, the OpenAPI description and auth.md to live/. Cloudflare rules serve them at
    /.well-known/api-catalog (as application/linkset+json), /openapi.json and /auth.md. JSON files must parse."""
    for name in API_DOCS:
        text = (source / name).read_text("utf-8")
        if name.endswith(".json"):
            json.loads(text)
        write_if_changed(live_dir / name, text)


# ---------------------------------------------------------------------------------------------------------------
# Share pages: live/share/<ID>.html, served at /bill/<ID>. Link-preview crawlers (Discord, Facebook, X, Slack) drop
# the #fragment of a bill's app address, so each bill needs a real page carrying its own tags. People are sent on to
# the bill in the app; crawlers don't run scripts, so they keep the tags.

SHARE_TITLE_MAX, SHARE_DESCRIPTION_MAX = 70, 200
SITE_CARD = "social-card.png"
_SHARE_NAME = re.compile(r"(" + BILL_ID.pattern + r")\.html")


def bill_number(bill_id: str) -> str:
    return re.sub(r"^(HJR|SJR|HCR|SCR|HB|SB|HR|SR)", r"\1 ", bill_id)


def clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0] or text[:limit - 1]
    return cut.rstrip(" ,;:") + "…"


def load_headlines(path: Path | None) -> dict[str, str]:
    """Luna's "In brief" lines (texas-bill-luna-extras-v1) keyed by bill id; anything unreadable means none."""
    try:
        data = json.loads(path.read_text("utf-8")) if path else None
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("format") != "texas-bill-luna-extras-v1" or not isinstance(data.get("bills"), dict):
        return {}
    return {k: " ".join(v["headline"].split()) for k, v in data["bills"].items()
            if isinstance(v, dict) and isinstance(v.get("headline"), str) and v["headline"].strip()}


LEGISLATION_TYPES = (("HJR", "Joint resolution"), ("SJR", "Joint resolution"), ("HCR", "Concurrent resolution"),
                     ("SCR", "Concurrent resolution"), ("HB", "Bill"), ("SB", "Bill"), ("HR", "Resolution"), ("SR", "Resolution"))
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def legislation_jsonld(bill: dict, site: str = SITE) -> str:
    """schema.org Legislation for search engines: the official record only (no AI text), with where to check it."""
    bill_id = bill["id"]
    caption = " ".join(str(bill.get("caption") or bill.get("title") or "").split())
    official = f"https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill={bill_id}"
    data = {"@context": "https://schema.org", "@type": "Legislation", "name": f"{bill_number(bill_id)}: {caption}" if caption else bill_number(bill_id),
            "legislationIdentifier": bill_number(bill_id),
            "legislationType": next((kind for prefix, kind in LEGISLATION_TYPES if bill_id.startswith(prefix)), "Bill"),
            "legislationJurisdiction": {"@type": "AdministrativeArea", "name": "Texas"},
            "legislationResponsible": {"@type": "GovernmentOrganization", "name": "Texas Legislature", "url": "https://capitol.texas.gov/"},
            "inLanguage": "en", "url": f"{site}bill/{bill_id}", "sameAs": official, "isBasedOn": official,
            "publisher": {"@type": "Organization", "name": "Texas Bill Atlas", "url": site}}
    if caption:
        data["description"] = caption
    if DAY_RE.match(str(bill.get("filed_at") or "")):
        data["dateCreated"] = bill["filed_at"]
    if DAY_RE.match(str(bill.get("last_action_date") or "")):
        data["dateModified"] = bill["last_action_date"]
    authors = [str(a) for a in bill.get("authors") or [] if str(a).strip()]
    if authors:
        data["author"] = [{"@type": "Person", "name": a} for a in authors]
    subjects = [str(s) for s in bill.get("subjects") or [] if str(s).strip()]
    if subjects:
        data["keywords"] = subjects
    versions = [v for v in bill.get("text_versions") or [] if re.fullmatch(r"[A-Za-z0-9]{1,8}", str(v.get("code") or ""))]
    if versions:
        latest = versions[-1]
        data["workExample"] = {"@type": "LegislationObject", "name": str(latest.get("name") or latest["code"]),
                               "encodingFormat": "text/markdown", "contentUrl": f"{site}live/text/{bill_id}/{latest['code']}.md",
                               "legislationLegalValue": "https://schema.org/UnofficialLegalValue"}
    # "<" escaped so no caption can close the script element.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


SHARE_TEXT_MAX = 3000  # Characters of official text shown on a share page; the rest is a link to our full copy.
AGENT_SITE = "https://agent.billatlas.org/"
# Crawlers that read the share page as a page: its script must not send them to the app (whose canonical is the home
# page). Any user agent saying bot, crawler or spider, as search engines' renderers do.
_CRAWLER_JS = r"/bot|crawl|spider|slurp|Google-InspectionTool|BingPreview/i"
# The icon links index.html keeps in its head slot (scripts/pages.py replaces the whole slot).
SHELL_ICONS = "\n".join(('<link rel="icon" href="/favicon.ico" sizes="32x32">',
                         '<link rel="icon" href="/icon.png" type="image/png" sizes="192x192">',
                         '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'))
_PAGE_VERSION = re.compile(r'<meta name="page-version" content="([0-9a-f]+)">')


def _names(value: object) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []


def share_text_html(markdown: str, limit: int = SHARE_TEXT_MAX) -> tuple[str, bool]:
    """Our Markdown copy of the bill text as simple HTML, cut at a line once `limit` characters are shown.
    Returns (html, cut). Everything is escaped; only the bill's own <ins>/<del> marks are kept."""
    parts, shown = [], 0
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if lines and lines[0].startswith("# "):
        lines = lines[1:]  # "# HB 309 - Introduced": the page has its own heading.
    for index, line in enumerate(lines):
        if shown >= limit:
            return "\n".join(parts), True
        heading = line.startswith("#")
        text = re.sub(r"\\(.)", r"\1", line.lstrip("#").strip())
        body = escape(text)
        for tag in ("ins", "del"):
            body = body.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(f"&lt;/{tag}&gt;", f"</{tag}>")
        parts.append(f"<h3>{body}</h3>" if heading else f"<p>{body}</p>")
        shown += len(plain_text(text))
    return "\n".join(parts), False


def share_body(bill: dict, site: str, headline: str | None, text: tuple[dict, str] | None, in_app: bool = False) -> str:
    """The share page's visible content: the official record, a labelled AI line, the start of the bill text, links.
    in_app: the page is inside the site shell, where the app takes it over, so it has no "Open in" link."""
    bill_id = bill["id"]
    caption = " ".join(str(bill.get("caption") or bill.get("title") or "No caption available").split())
    official = f"https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill={bill_id}"
    a = lambda value: escape(value, {'"': "&quot;"})
    facts = [("Session", "90th Texas Legislature, Regular Session")]
    if bill.get("status"):
        facts.append(("Status", str(bill["status"])))
    if _long_date(bill.get("filed_at")):
        facts.append(("Filed", _long_date(bill["filed_at"])))
    if bill.get("last_action"):
        facts.append(("Most recent action", str(bill["last_action"])))
    for key, label in (("authors", "Authors"), ("coauthors", "Coauthors"), ("sponsors", "Sponsors"), ("cosponsors", "Cosponsors")):
        if _names(bill.get(key)):
            facts.append((label, ", ".join(_names(bill.get(key)))))
    if _names(bill.get("subjects")):
        facts.append(("Official subjects", "; ".join(_names(bill.get("subjects")))))
    rows = "\n".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in facts)
    out = [f"<h1>{escape(bill_number(bill_id))}: {escape(caption)}</h1>",
           *([] if in_app else
             [f'<p><a href="{a(f"{site}#bill?id={bill_id}")}">Open {escape(bill_number(bill_id))} in Texas Bill Atlas</a></p>']),
           f"<dl>\n{rows}\n</dl>"]
    if headline:
        out.append(f"<p><strong>AI summary (not official):</strong> {escape(headline)}</p>")
    links = []
    if text:
        version, markdown = text
        name = str(version.get("name") or version["code"])
        full = f"{site}live/text/{bill_id}/{version['code']}.md"
        body, cut = share_text_html(markdown)
        out += [f"<h2>Bill text ({escape(name)})</h2>", body]
        if cut:
            out.append(f'<p>The text continues: <a href="{a(full)}">full text of {escape(bill_number(bill_id))}</a>.</p>')
        links.append(f'<li><a href="{a(full)}">Full bill text ({escape(name)}), Markdown copy of the official file</a></li>')
    links += [f'<li><a href="{a(f"{AGENT_SITE}bills/{bill_id}.md")}">Record, history and review for AI agents</a></li>',
              f'<li><a href="{a(official)}">Official bill history on Texas Legislature Online</a></li>']
    out += ["<h2>Links</h2>", "<ul>\n" + "\n".join(links) + "\n</ul>",
            "<p>Texas Bill Atlas is an independent research tool, not an official state website.</p>"]
    return "\n".join(out)


def share_page(bill: dict, site: str = SITE, headline: str | None = None, image_v: str | None = None,
               text: tuple[dict, str] | None = None, shell: str | None = None) -> str:
    """The page at /bill/<ID>, served to everyone. With the deployed shell (scripts/pages.py) it is the whole site page
    and the app takes it over in place. Without one (no release has published it yet) it is the standalone page, whose
    script sends people to the app at the site root and lets crawlers stay."""
    bill_id = bill["id"]
    caption = " ".join(str(bill.get("caption") or bill.get("title") or "No caption available").split())
    url, target = f"{site}bill/{bill_id}", f"{site}#bill?id={bill_id}"
    title = clip(f"{bill_number(bill_id)}: {caption}", SHARE_TITLE_MAX)
    # The official caption is in the title; an AI-written line is labelled as one.
    description = clip(f"AI summary: {headline}" if headline else caption, SHARE_DESCRIPTION_MAX)
    # The bill's own card once the drawer has made it (the version in the URL is the one on disk), else the site card.
    image = f"{site}live/og/{bill_id}.png?v={image_v}" if image_v else f"{site}{SITE_CARD}"
    image_alt = clip(f"{bill_number(bill_id)}: {caption}", SHARE_DESCRIPTION_MAX) if image_v else "Texas Bill Atlas"
    # Previews are cached under og:url, so a redrawn card gets a new one; the app's Share button copies the same
    # /bill/<ID>?c=<version> address. The canonical link stays plain for search engines.
    og_url = f"{url}?c={image_v}" if image_v else url
    a = lambda value: escape(value, {'"': "&quot;"})
    meta = [("property", "og:type", "website"), ("property", "og:site_name", "Texas Bill Atlas"),
            ("property", "og:title", title), ("property", "og:description", description), ("property", "og:url", og_url),
            ("property", "og:image", image), ("property", "og:image:width", "1200"), ("property", "og:image:height", "630"),
            ("property", "og:image:alt", image_alt), ("name", "twitter:card", "summary_large_image"),
            ("name", "twitter:title", title), ("name", "twitter:description", description), ("name", "twitter:image", image),
            ("name", "twitter:image:alt", image_alt), ("name", "description", description)]
    tags = "\n".join(f'<meta {kind}="{name}" content="{a(value)}">' for kind, name, value in meta)
    if shell is not None:
        # The shell's head slot also holds the site icons, so the page brings its own.
        head = f"""
<title>{escape(title)} · Texas Bill Atlas</title>
<link rel="canonical" href="{a(url)}">
<link rel="alternate" type="text/markdown" href="{a(f"{AGENT_SITE}bills/{bill_id}.md")}">
{SHELL_ICONS}
{tags}
<script type="application/ld+json">{legislation_jsonld(bill, site)}</script>
"""
        content = f'\n<article class="bill-page static-page" aria-label="Bill details">\n{share_body(bill, site, headline, text, True)}\n</article>\n'
        # page-version covers only this bill's part, so a new shell alone is not a change to submit to IndexNow.
        version = hashlib.sha256((head + content).encode()).hexdigest()[:12]
        return pages.render_page(shell, head=f'{head}<meta name="page-version" content="{version}">',
                                 content=content, view=f"bill:{bill_id}")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#112136">
<title>{escape(title)} · Texas Bill Atlas</title>
<link rel="canonical" href="{a(url)}">
<link rel="alternate" type="text/markdown" href="{a(f"{AGENT_SITE}bills/{bill_id}.md")}">
<link rel="icon" href="/favicon.ico">
{tags}
<script type="application/ld+json">{legislation_jsonld(bill, site)}</script>
<script>if(!{_CRAWLER_JS}.test(navigator.userAgent))location.replace({json.dumps(target)})</script>
</head>
<body>
{share_body(bill, site, headline, text)}
</body>
</html>
"""


# Share card images: live/og/<ID>.png, drawn hourly by scripts/build_og.mjs (texas-bill-og.service) from
# live/og/cards.json. Each entry holds the display strings drawn on the card and `v`, a hash of them; the drawer
# redraws a card when `v` changes and lists what it drew in live/og/rendered.json. Official text only.

OG_CARDS_FORMAT, OG_RENDERED_FORMAT = "texas-bill-og-cards-v1", "texas-bill-og-rendered-v1"
OG_REVISION = "c2"  # Bump when the drawn wording changes for every bill (scripts/og_card.mjs layout changes too).
OG_SESSION = "90th Legislature \u00b7 Regular Session"
# Optional per-bill illustrations, scripts/og_art/<ID>.jpg; a card with one is drawn as a poster (og_card.mjs).
OG_ART_DIR = Path(__file__).resolve().parent / "og_art"


def _long_date(value: object) -> str:
    try:
        day = dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    return f"{day:%b} {day.day}, {day.year}"


def subject_labels(subjects: list) -> list[str]:
    """Short chip labels from official subjects ("Family--Juvenile Delinquency" -> "Juvenile Delinquency"): the
    specific part, or the category when the specific part is generic or repeats; all-caps subjects in title case."""
    pairs = []
    for subject in subjects:
        if not isinstance(subject, str) or not subject.strip():
            continue
        text = " ".join(subject.split())
        if text.isupper():
            text = text.title()
        parts = [part.strip() for part in text.split("--") if part.strip()]
        pairs.append((parts[0], parts[-1]))
    tails = Counter(tail for _head, tail in pairs)
    labels = []
    for head, tail in pairs:
        label = head if tail == "General" or tail.startswith("Other") or tails[tail] > 1 else tail
        if label not in labels:
            labels.append(label)
    return labels


def art_version(bill_id: str, art_dir: Path | None = None) -> str | None:
    """Hash of the bill's illustration file, so replacing the art redraws the card; None without one."""
    if not BILL_ID.fullmatch(str(bill_id)):
        return None
    try:
        data = ((art_dir or OG_ART_DIR) / f"{bill_id}.jpg").read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()[:12]


def card_model(bill: dict, art_dir: Path | None = None) -> dict:
    bill_id = bill["id"]
    authors = [a for a in bill.get("authors") or [] if isinstance(a, str) and a.strip()]
    # `author` joins every author with " | "; the first is the lead author.
    author = (authors[0] if authors else str(bill.get("author") or "").split("|")[0]).strip()
    others = max(0, len(authors) - 1)
    byline = " \u00b7 ".join(part for part in (
        f"Filed {_long_date(bill.get('filed_at'))}" if _long_date(bill.get("filed_at")) else "",
        f"By {author}" + (f" and {others} other{'s' if others > 1 else ''}" if others else "") if author else "",
    ) if part)
    subjects = subject_labels(bill.get("subjects") or [])[:3]
    model = {
        "number": bill_number(bill_id), "chamber": str(bill.get("chamber") or ""),
        "caption": " ".join(str(bill.get("caption") or bill.get("title") or "No caption available").split()),
        "status": str(bill.get("status") or ""), "byline": byline, "subjects": subjects, "session": OG_SESSION,
    }
    art = art_version(bill_id, art_dir)
    if art:  # Only cards with art get the key, so adding art to one bill leaves every other card's `v` alone.
        model["art"] = art
    return model


def card_version(model: dict) -> str:
    text = json.dumps([OG_REVISION, model], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def write_og_cards(snapshot: dict, out_dir: Path) -> tuple[int, bool]:
    """live/og/cards.json for the card drawer; `active` (last action date) orders a capped run and is not drawn."""
    cards = {}
    for bill in snapshot.get("bills") or []:
        if not isinstance(bill, dict) or not BILL_ID.fullmatch(str(bill.get("id", ""))):
            continue
        model = card_model(bill)
        cards[bill["id"]] = {"v": card_version(model), "active": str(bill.get("last_action_date") or ""), **model}
    if not cards:  # A broken snapshot leaves the last good file, so the drawer removes nothing.
        return 0, False
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"format": OG_CARDS_FORMAT, "bills": cards}, ensure_ascii=False, sort_keys=True) + "\n"
    return len(cards), write_if_changed(out_dir / "cards.json", text)


# Bill page banners: live/og/art/<ID>.jpg copies of the illustrations and live/og/art.json (bill -> version, alt
# text). The page shows a banner only while the operator flag in live/site-flags.json has "bill_art_banner": true.
ART_FORMAT = "texas-bill-art-v1"
ART_MAX_BYTES = 2_000_000  # build_og.mjs refuses larger files too
OG_ART_ALT = Path(__file__).resolve().parent / "og_art_alt.json"


def load_art_alt(path: Path | None) -> dict[str, str]:
    """Bill id -> alt text for its illustration (scripts/og_art_alt.json); anything unreadable means none."""
    try:
        data = json.loads(path.read_text("utf-8")) if path else None
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: " ".join(v.split()) for k, v in data.items()
            if BILL_ID.fullmatch(str(k)) and isinstance(v, str) and v.strip()}


def write_bill_art(out_dir: Path, art_dir: Path | None = None, alt_path: Path | None = None) -> tuple[int, bool]:
    """Copy each scripts/og_art/<ID>.jpg to out_dir/art/ and list them in out_dir/art.json.

    Images are written before the list and stale ones removed after it, so the page never lists a missing image."""
    alts = load_art_alt(alt_path or OG_ART_ALT)
    images = out_dir / "art"
    bills, changed = {}, False
    for source in sorted((art_dir or OG_ART_DIR).glob("*.jpg")):
        if not BILL_ID.fullmatch(source.stem):
            continue
        try:
            data = source.read_bytes()
        except OSError:
            continue
        if len(data) > ART_MAX_BYTES:
            continue
        images.mkdir(parents=True, exist_ok=True)
        target = images / source.name
        try:
            same = target.read_bytes() == data
        except OSError:
            same = False
        if not same:
            handle, temporary = tempfile.mkstemp(dir=images, prefix=".art-")
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(data)
                os.chmod(temporary, 0o644)
                os.replace(temporary, target)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
            changed = True
        entry = {"v": hashlib.sha256(data).hexdigest()[:12]}
        if source.stem in alts:
            entry["alt"] = alts[source.stem]
        bills[source.stem] = entry
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"format": ART_FORMAT, "bills": bills}, ensure_ascii=False, sort_keys=True) + "\n"
    changed = write_if_changed(out_dir / "art.json", text) or changed
    for old in images.glob("*.jpg") if images.is_dir() else ():
        if old.stem not in bills:
            old.unlink(missing_ok=True)
            changed = True
    return len(bills), changed


def load_rendered(path: Path | None) -> dict[str, str]:
    """Bill id -> `v` of the card image on disk (live/og/rendered.json); anything unreadable means none."""
    try:
        data = json.loads(path.read_text("utf-8")) if path else None
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("format") != OG_RENDERED_FORMAT or not isinstance(data.get("bills"), dict):
        return {}
    return {k: v for k, v in data["bills"].items()
            if BILL_ID.fullmatch(str(k)) and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{1,64}", v)}


def _page_version(page: Path | str) -> str | None:
    """A shell page's page-version (a path is read first); None for a standalone page or an unreadable file."""
    try:
        text = page.read_text("utf-8") if isinstance(page, Path) else page
    except OSError:
        return None
    match = _PAGE_VERSION.search(text)
    return match.group(1) if match else None


def write_share_pages(snapshot: dict, out_dir: Path, site: str = SITE, headlines: dict[str, str] | None = None,
                      rendered: dict[str, str] | None = None, text_dir: Path | None = None,
                      changed: list[str] | None = None, shell: str | None = None) -> tuple[int, int, int]:
    """One share page per bill, rewritten only when it changes; pages for bills no longer in the snapshot removed.
    With text_dir the page shows the start of the bill's latest text; with shell it is built inside the site shell.
    Rewritten bill ids are added to `changed`, except pages whose own part (page-version) is unchanged: a new shell
    rewrites every page, but no bill changed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    headlines, rendered, keep = headlines or {}, rendered or {}, set()
    written = unchanged = removed = 0
    for bill in snapshot.get("bills") or []:
        if not isinstance(bill, dict) or not BILL_ID.fullmatch(str(bill.get("id", ""))):
            continue  # Never build a file name from an unexpected id.
        keep.add(f"{bill['id']}.html")
        text = _latest_text(text_dir, bill["id"]) if text_dir else None
        path = out_dir / f"{bill['id']}.html"
        page = share_page(bill, site, headlines.get(bill["id"]), rendered.get(bill["id"]), text, shell)
        before = _page_version(path)
        if write_if_changed(path, page):
            written += 1
            if changed is not None and (before is None or before != _page_version(page)):
                changed.append(bill["id"])
        else:
            unchanged += 1
    if keep:  # An empty or broken snapshot never empties the folder.
        for path in out_dir.iterdir():
            if _SHARE_NAME.fullmatch(path.name) and path.name not in keep:
                path.unlink(missing_ok=True)
                removed += 1
    return written, unchanged, removed


# IndexNow: tell Bing and the engines sharing its submissions (Yandex, Seznam, Naver, Yep) which bill pages changed.
# The key is public by design; public/<key>.txt at the site root proves the site is ours.
INDEXNOW_KEY = "7b91498ed44f1a3d41b650238bfe5f85"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
INDEXNOW_MAX_URLS = 10000
# Only the server's data run submits: tests, golden runs and local builds never write here.
LIVE_SNAPSHOT = Path("/var/www/html/texas-bill-atlas/live/bills.json")


def indexnow_payload(bill_ids: list[str], site: str = SITE) -> dict:
    from urllib.parse import urlsplit
    return {"host": urlsplit(site).hostname, "key": INDEXNOW_KEY, "keyLocation": f"{site}{INDEXNOW_KEY}.txt",
            "urlList": [f"{site}bill/{bill_id}" for bill_id in bill_ids[:INDEXNOW_MAX_URLS]]}


def submit_indexnow(bill_ids: list[str], site: str = SITE, opener=None) -> str:
    """POST the changed bill pages; returns a status line. Never raises: search pings must not fail the data run."""
    if not bill_ids:
        return "nothing changed"
    import urllib.error
    import urllib.request
    payload = indexnow_payload(bill_ids, site)
    request = urllib.request.Request(INDEXNOW_ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            return f"HTTP {response.status} for {len(payload['urlList'])} pages"
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code} for {len(payload['urlList'])} pages (not accepted)"
    except (urllib.error.URLError, OSError, ValueError) as error:
        return f"failed: {type(error).__name__}"


# ---------------------------------------------------------------------------------------------------------------
# Statute index: which sections of Texas law each bill amends, adds or repeals, with the text it quotes.
# It lives here because the data unit fetches only sync_ftp.py and this file from main on every run.

STATUTE_FORMAT = "texas-bill-statutes-v1"
STATUTE_SECTION_FORMAT = "texas-bill-statute-section-v1"
KIND_LETTER = {"amend": "m", "add": "n", "repeal": "r"}  # In the index: amends, new section, repeals.
# Bill-text names -> statutes.capitol.texas.gov abbreviations (each checked against a real section there).
CODE_ABBR = {
    "Agriculture Code": "AG", "Alcoholic Beverage Code": "AL", "Business and Commerce Code": "BC",
    "Business Organizations Code": "BO", "Civil Practice and Remedies Code": "CP", "Code of Criminal Procedure": "CR",
    "Education Code": "ED", "Election Code": "EL", "Estates Code": "ES", "Family Code": "FA", "Finance Code": "FI",
    "Government Code": "GV", "Health and Safety Code": "HS", "Human Resources Code": "HR", "Insurance Code": "IN",
    "Labor Code": "LA", "Local Government Code": "LG", "Natural Resources Code": "NR", "Occupations Code": "OC",
    "Parks and Wildlife Code": "PW", "Penal Code": "PE", "Property Code": "PR", "Special District Local Laws Code": "SD",
    "Tax Code": "TX", "Transportation Code": "TN", "Utilities Code": "UT", "Water Code": "WA",
}
CODE_NAME = {abbr: name for name, abbr in CODE_ABBR.items()}
_CODE_RE = re.compile("(" + "|".join(sorted(map(re.escape, CODE_ABBR), key=len, reverse=True)) + ")")
SECTION_NUM = re.compile(r"\d+[A-Z]?(?:\.\d+[A-Z]?)+")      # 48.160, 42A.054, 2051.151; never a bare "1"
STATUTE_KEY = re.compile(r"([A-Z]{2}) (" + SECTION_NUM.pattern + r")")
_SUBSECTION = re.compile(r"\(([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\)")
# A list after "Section(s)": "123.001(b) and (c) and 126.001(b)", "1.01, 1.02(a), and 1.03".
_LIST = r" ((?:(?:[0-9A-Z.]+|\([A-Za-z0-9-]+\))(?:\([A-Za-z0-9-]+\))*(?:, and |, | and )?)+)"
_VERB = re.compile(r",? (?:is|are) (?:hereby )?(amended|repealed|added|reenacted|transferred|redesignated|renumbered)\b")
_HEADER = re.compile(r"^(?:Sec|Art)\. (" + SECTION_NUM.pattern + r")\.")
_ONLY_HEADING = re.compile(r"^The headings? (?:to|of) ")
_OTHER_LAW = re.compile(r"Acts of the|Revised Statutes|Vernon's|Constitution|General Appropriations|\(H\.B\.|\(S\.B\.")
_REPEALER = re.compile(r"^(?:The following|Effective [^,]+, the following)[^:]*(?:is|are) repealed")
_TAGS = re.compile(r"</?(?:ins|del)>")
_HEADING_LINE = re.compile(r"^### ")


def plain_text(markdown_line: str) -> str:
    """The bill text line without ins/del tags or Markdown escapes (both versions merged)."""
    return re.sub(r"\s+", " ", re.sub(r"\\(.)", r"\1", _TAGS.sub("", markdown_line))).strip()


def _numbers(text: str) -> list[str]:
    """Section numbers in a list such as "21.0031(b), 21.004, and 21.005(a) and (c)"; subsections are dropped."""
    return [m.group(0) for m in SECTION_NUM.finditer(_SUBSECTION.sub("", text))]


def _subsections(text: str) -> list[str]:
    return [m.group(1) for m in _SUBSECTION.finditer(text)]


def parse_clause(clause: str) -> dict:
    """Classify one SECTION's opening sentence.

    Returns {"kind": amend|add|repeal|chapter|heading|repealer|other_law|none|unparsed, "code": abbr or None,
    "targets": [section numbers], "subsections": [...], "from_body": bool}. from_body means the section numbers
    come from the "Sec. N." headers in the body (a chapter or subchapter being added) or, for a repealer, from the
    listed items."""
    text = plain_text(clause).replace(" & ", " and ")
    out = {"kind": "none", "code": None, "targets": [], "subsections": [], "from_body": False}
    if _REPEALER.match(text):
        code = _CODE_RE.search(text)
        return {**out, "kind": "repealer", "code": CODE_ABBR[code.group(1)] if code else None, "from_body": True}
    verb = _VERB.search(text)
    if not verb:
        return out
    path, rest, action = text[:verb.start()], text[verb.end():].strip(), verb.group(1)
    codes = list(_CODE_RE.finditer(path))
    if not codes:
        return {**out, "kind": "other_law" if _OTHER_LAW.search(text) else "unparsed"}
    code = CODE_ABBR[codes[-1].group(1)]
    before = path[:codes[-1].start()]
    out["code"] = code
    if _ONLY_HEADING.match(before) and not re.match(r"^The headings? (?:to|of) (?:Section|Article)", before):
        return {**out, "kind": "heading"}  # Chapter, subchapter or title headings: no section to track.
    # Code of Criminal Procedure: articles are the sections ("Section 1(c), Article 46.04" keys to Article 46.04).
    unit = r"Articles?" if code == "CR" else r"Sections?"
    named = [m for m in re.finditer(r"\b" + unit + _LIST, before)]
    targets = [n for m in named for n in _numbers(m.group(1))]
    subs = _subsections(before)
    if action == "repealed":
        return {**out, "kind": "repeal" if targets else "chapter", "targets": targets, "subsections": subs}
    if action == "added":
        return {**out, "kind": "add" if targets else "chapter", "targets": targets, "from_body": not targets}
    adding = re.match(r"by (?:amending [^,]*?(?:and )?)?adding (Sections?|Articles?|Subsections?|Subdivisions?|Subchapters?|Chapters?|Subtitles?|Titles?|Parts?) ([^,]*?)(?: to read|,|$)", rest)
    if targets:
        amending = re.search(r"by amending ((?:Subsections?|Subdivisions?) [^,]*?)(?: and adding|,| to read|$)", rest)
        if amending:
            subs += _subsections(amending.group(1))
        if adding and adding.group(1)[:6] in ("Subsec", "Subdiv"):
            subs += _subsections(adding.group(2))
        return {**out, "kind": "amend", "targets": targets, "subsections": list(dict.fromkeys(subs))}
    if adding and adding.group(1).startswith(("Section", "Article")):
        return {**out, "kind": "add", "targets": _numbers(adding.group(2))}
    if adding:
        return {**out, "kind": "add", "from_body": True}  # A new chapter or subchapter: its sections are in the body.
    return {**out, "kind": "chapter"}


def _split_body(body: list[str], targets: list[str], from_body: bool) -> dict[str, list[str]]:
    """Assign body paragraphs to sections by their "Sec. N." / "Art. N." headers."""
    parts: dict[str, list[str]] = {}
    current = targets[0] if len(targets) == 1 and not from_body else None
    for line in body:
        header = _HEADER.match(plain_text(line))
        if header and (from_body or header.group(1) in targets):
            current = header.group(1)
        if current is not None:
            parts.setdefault(current, []).append(line)
    return parts


def _repealed_items(body: list[str], code: str | None) -> list[tuple[str, str]]:
    found = []
    for line in body:
        text = plain_text(line).replace(" & ", " and ")
        named = _CODE_RE.search(text)
        item_code = CODE_ABBR[named.group(1)] if named else code
        unit = "Articles?" if item_code == "CR" else "Sections?"
        for m in re.finditer(r"\b" + unit + _LIST, text):
            found += [(item_code, n) for n in _numbers(m.group(1)) if item_code]
    return found


def bill_statutes(markdown: str) -> tuple[dict[str, dict], int]:
    """({key: {kind, subsections, partial, paragraphs}}, unparsed clause count) for one bill text."""
    lines = [line for line in markdown.split("\n") if line.strip()]
    sections: dict[str, dict] = {}
    unparsed = 0
    rank = {"amend": 3, "add": 2, "repeal": 1}

    def note(code: str, number: str, kind: str, subs: list[str], paragraphs: list[str]):
        key = f"{code} {number}"
        if not STATUTE_KEY.fullmatch(key) or len(number) > 16:
            return
        entry = sections.setdefault(key, {"kind": kind, "subsections": [], "partial": True, "paragraphs": []})
        if rank[kind] > rank[entry["kind"]]:
            entry["kind"] = kind
        if kind == "amend":
            entry["partial"] = entry["partial"] and bool(subs)
            entry["subsections"] = list(dict.fromkeys(entry["subsections"] + subs))
        elif kind == "add":
            entry["partial"] = False
        entry["paragraphs"] += paragraphs

    i = 0
    while i < len(lines):
        if not _HEADING_LINE.match(lines[i]) or i + 1 >= len(lines):
            i += 1
            continue
        clause = lines[i + 1]
        end = i + 2
        while end < len(lines) and not _HEADING_LINE.match(lines[end]):
            end += 1
        body = lines[i + 2:end]
        parsed = parse_clause(clause)
        kind = parsed["kind"]
        if kind == "unparsed":
            unparsed += 1
        elif kind == "repealer":
            for code, number in _repealed_items(body, parsed["code"]):
                note(code, number, "repeal", [], [])
        elif kind == "repeal":
            for number in parsed["targets"]:
                note(parsed["code"], number, "repeal", parsed["subsections"], [])
        elif kind in ("amend", "add"):
            parts = _split_body(body, parsed["targets"], parsed["from_body"])
            numbers = list(parts) if parsed["from_body"] else parsed["targets"]
            for number in numbers:
                note(parsed["code"], number, kind, parsed["subsections"] if kind == "amend" else [], parts.get(number, []))
        i = end
    return sections, unparsed


# Whole chapters a bill repeals, amends, adds or names. Not part of live/statutes/ (sections only); the review reads it.
CHAPTER_RANK = {"repeal": 4, "amend": 3, "add": 2, "cited": 1}
_CHAPTER_LIST = re.compile(r"\bChapters? ((?:\d+[A-Z]?(?:, and |, or |, | and | or )?)+)")
_CHAPTER_NUM = re.compile(r"\d+[A-Z]?")
_OTHER_CODE_AFTER = re.compile(r"^,? (?:of )?(?:the )?" + _CODE_RE.pattern)


_SESSION_LAW_AFTER = re.compile(r"^,? ?(?:\([HS]\.|Acts\b|of the Acts\b)")  # "Chapter 377 (H.B. 5), Acts of ..."
_PART_BEFORE = re.compile(r"(?:\b(?:Subchapters?|Subsections?|Subtitles?|Titles?|Parts?|Articles?) [0-9A-Z-]+"
                          r"(?:(?:, and |, or |, | and | or )[0-9A-Z-]+)*, |\bprovisions of (?:the )?)$")
_PART_AFTER = re.compile(r"^,? (?:Subchapters?|Subsections?|Parts?|Articles?) [0-9A-Z-]+")


def _chapter_refs(text: str, default_code: str | None, whole: bool = False) -> list[tuple[str, str, bool]]:
    """(code, chapter, part) for each "Chapter N" list in a line: the code named right after the list, else the
    default (an unqualified chapter in a code's own text is that code's chapter). `part` is True when the list names
    only part of the chapter ("Subchapter T, Chapter 403"). Session-law chapters ("Chapter 377 (H.B. 5), Acts of the
    88th Legislature") are not code chapters and are skipped."""
    found = []
    for m in _CHAPTER_LIST.finditer(text):
        listed = re.sub(r"(?:, and |, or |, | and | or )$", "", m.group(1))
        after = text[m.start(1) + len(listed):]
        if _SESSION_LAW_AFTER.match(after):
            continue
        part = bool(_PART_BEFORE.search(text[:m.start()]) or _PART_AFTER.match(after))
        after = _PART_AFTER.sub("", after)  # "Chapter 29, Subchapter J, Education Code"
        named = _OTHER_CODE_AFTER.match(after)
        code = CODE_ABBR[named.group(1)] if named else default_code
        if code:
            found += [(code, n.upper(), part) for n in _CHAPTER_NUM.findall(listed)]
    return found


def bill_chapters(markdown: str) -> dict[str, str]:
    """{"GV 2271": repeal|amend|add|cited} for the chapters one bill text repeals, amends or adds as a whole, or
    names: a SECTION clause on a chapter ("Chapter 2271, Government Code, is repealed"), the items of a repealer list
    ("The following chapters of the Government Code are repealed: (1) Chapter 2271; ..."), and "Chapter N" in an
    amended or added section's text (that code's chapter unless another code is named)."""
    lines = [line for line in markdown.split("\n") if line.strip()]
    chapters: dict[str, str] = {}

    def note(code: str, number: str, kind: str):
        key = f"{code} {number}"
        if CHAPTER_RANK[kind] > CHAPTER_RANK.get(chapters.get(key, ""), 0):
            chapters[key] = kind

    i = 0
    while i < len(lines):
        if not _HEADING_LINE.match(lines[i]) or i + 1 >= len(lines):
            i += 1
            continue
        end = i + 2
        while end < len(lines) and not _HEADING_LINE.match(lines[end]):
            end += 1
        clause, body = plain_text(lines[i + 1]).replace(" & ", " and "), lines[i + 2:end]
        parsed = parse_clause(lines[i + 1])
        kind, code = parsed["kind"], parsed["code"]
        if kind == "repealer":
            for line in body:
                for item_code, number, part in _chapter_refs(plain_text(line).replace(" & ", " and "), code):
                    note(item_code, number, "amend" if part else "repeal")
        elif code and kind in ("chapter", "amend", "add", "repeal"):
            verb = _VERB.search(clause)
            path = clause[:verb.start()] if verb else clause
            action = {"repealed": "repeal", "added": "add"}.get(verb.group(1) if verb else "", "amend")
            for item_code, number, part in _chapter_refs(path, code):
                note(item_code, number, "amend" if part and action == "repeal" else action)
            adding = re.search(r"\badding Chapters? ([0-9A-Z, and]+)", clause[verb.end():] if verb else "")
            for number in _CHAPTER_NUM.findall(adding.group(1)) if adding else []:
                note(code, number.upper(), "add")
            if kind != "repeal":
                for line in body:
                    proposed = plain_text(re.sub(r"\\\[<del>.*?</del>\\\]|<del>.*?</del>", "", line))
                    for item_code, number, _ in _chapter_refs(proposed, code):
                        note(item_code, number, "cited")
        i = end
    return chapters


def _latest_text(text_dir: Path, bill_id: str) -> tuple[dict, str] | None:
    try:
        index = json.loads((text_dir / bill_id / "index.json").read_text("utf-8"))
        versions = [v for v in index.get("versions", []) if isinstance(v, dict) and re.fullmatch(r"[A-Z0-9]{1,3}", str(v.get("code", "")))]
        if index.get("bill_id") != bill_id or not versions:
            return None
        version = versions[-1]
        return version, (text_dir / bill_id / f"{version['code']}.md").read_text("utf-8")
    except (OSError, ValueError, AttributeError):
        return None


def section_heading(paragraphs: list[str], current: bool = False) -> str:
    """"Sec. 48.160. FUNDING FOR X." -> "FUNDING FOR X": the heading as the bill would write it, or with current=True
    as it reads now (insertions dropped, deletions kept)."""
    for line in paragraphs:
        if current:
            line = re.sub(r"\\[\[\]]", "", re.sub(r"<ins>.*?</ins>", "", line))
        else:
            line = re.sub(r"\\\[<del>.*?</del>\\\]|<del>.*?</del>", "", line)
        proposed = re.sub(r"\s+", " ", plain_text(line)).strip()
        m = re.match(r"^(?:Sec|Art)\. " + SECTION_NUM.pattern + r"\.\s+([^a-z]{3,200}?)\.(?:\s|$)", proposed)
        if m:
            return m.group(1).strip()
    return ""


def section_headings(entries: list[dict]) -> tuple[str, dict[str, str]]:
    """(the section's heading, {adding bill: its own heading where it differs}).

    An existing section (any bill amends or repeals it) takes the current heading the first amending bill quotes, never
    an added section's: bills drafted separately can add unrelated sections under a number already in use. A section
    only bills add has a heading only when every bill gives it the same one."""
    adds = {e["bill"]: section_heading(e["paragraphs"]) for e in entries if e["kind"] == "add"}
    if len(adds) < len(entries):
        heading = next((h for e in entries if e["kind"] != "add" and (h := section_heading(e["paragraphs"], current=True))), "")
    else:
        found = set(adds.values())
        heading = found.pop() if len(found) == 1 else ""
    return heading, {bill: h for bill, h in adds.items() if h and h != heading}


CHAPTER_KEY = re.compile(r"[A-Z]{2} \d+[A-Z]?")
_CHAPTER_PREFIX = re.compile(r"^(?:CHAPTER|ARTICLE|SUBCHAPTER)\s+[0-9A-Za-z.\-]+?\.\s+", re.I)
CHAPTER_KIND = {"repeal": "r", "amend": "m", "add": "n"}  # "cited" chapters are never indexed.


def chapter_title(heading: str) -> str:
    """"CHAPTER 46. WEAPONS" -> "WEAPONS": the law copy's chapter heading without its number and trailing period."""
    return _CHAPTER_PREFIX.sub("", str(heading or "").strip()).strip().rstrip(".").strip()


def _open_law(law_dir: Path | None):
    """The law copy at law_dir, or None when it is absent or unreadable."""
    if law_dir is None or not (law_dir / "index.json").is_file():
        return None
    try:
        from law_context import LawCopy  # Imported here: law_context reads this module's statute parser.
        return LawCopy(law_dir)
    except (OSError, ValueError, ImportError):
        return None


def _law_chapter_title(law, code: str, chapter: str) -> str:
    if law is None:
        return ""
    try:
        found = law.chapter(code, chapter)
    except (OSError, ValueError, KeyError, AttributeError):
        return ""
    return chapter_title(found[1].get("heading") or "") if found else ""


def _bill_order(bill_id: str) -> tuple:
    return (bill_id[:2] != "HB", int(re.sub(r"\D", "", bill_id) or 0), bill_id)


def build_statutes(snapshot: dict, text_dir: Path, law_dir: Path | None = None) -> tuple[dict, dict[str, dict]]:
    """(index, {file name: section document}) from every bill's latest text version. `chapters` lists the whole
    chapters bills repeal, amend or add ("cited" ones are left out); `h` comes from the law copy at law_dir."""
    by_key: dict[str, list[dict]] = {}
    by_chapter: dict[str, dict[str, str]] = {}
    bills_meta: dict[str, dict] = {}
    for bill in snapshot.get("bills") or []:
        bill_id = str(bill.get("id", "")) if isinstance(bill, dict) else ""
        if not BILL_ID.fullmatch(bill_id):
            continue
        found = _latest_text(text_dir, bill_id)
        if not found:
            continue
        version, markdown = found
        sections, unparsed = bill_statutes(markdown)
        bills_meta[bill_id] = {"v": version["code"], "n": len(sections), "u": unparsed}
        for chapter_key, chapter_kind in bill_chapters(markdown).items():
            if chapter_kind in CHAPTER_KIND and CHAPTER_KEY.fullmatch(chapter_key) and chapter_key[:2] in CODE_NAME:
                by_chapter.setdefault(chapter_key, {})[bill_id] = CHAPTER_KIND[chapter_kind]
        for key, entry in sections.items():
            by_key.setdefault(key, []).append({"bill": bill_id, "version": version["code"],
                                               "version_name": str(version.get("name") or version["code"]), **entry})
    index = {"format": STATUTE_FORMAT, "codes": {abbr: CODE_NAME[abbr] for abbr in sorted({k[:2] for k in by_key})},
             "sections": {}, "bills": dict(sorted(bills_meta.items()))}
    law = _open_law(law_dir) if by_chapter else None
    index["chapters"] = {
        key: {"h": _law_chapter_title(law, key[:2], key[3:]),
              "b": [[bill, kind] for bill, kind in sorted(by_chapter[key].items(), key=lambda p: _bill_order(p[0]))]}
        for key in sorted(by_chapter)}
    files = {}
    for key in sorted(by_key):
        entries = sorted(by_key[key], key=lambda e: (e["bill"][:2] != "HB", int(re.sub(r"\D", "", e["bill"]) or 0), e["bill"]))
        heading, own = section_headings(entries)
        index["sections"][key] = {"h": heading, "b": [[e["bill"], KIND_LETTER[e["kind"]]] for e in entries]}
        if own:
            index["sections"][key]["hb"] = own
        code, number = key.split(" ")
        files[f"{code}-{number}.json"] = {"format": STATUTE_SECTION_FORMAT, "key": key, "code": code,
                                          "code_name": CODE_NAME[code], "section": number, "heading": heading,
                                          "entries": entries}
    return index, files


def chicago_today(now: dt.datetime | None = None) -> str:
    """This run's day in Chicago (the site's day)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("America/Chicago")
    except Exception:  # No tz database (some Windows Pythons): the US rule, so CDT does not give yesterday.
        zone = dt.timezone(dt.timedelta(hours=-5 if _us_central_dst(now) else -6))
    return now.astimezone(zone).date().isoformat()


def _us_central_dst(now: dt.datetime) -> bool:
    """Central daylight time: 2 a.m. CST on the second Sunday of March to 2 a.m. CDT on the first Sunday of November
    (08:00 and 07:00 UTC)."""
    utc = now.astimezone(dt.timezone.utc)

    def sunday(month: int, nth: int) -> dt.date:
        first = dt.date(utc.year, month, 1)
        return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (nth - 1))

    start = dt.datetime.combine(sunday(3, 2), dt.time(8), dt.timezone.utc)
    end = dt.datetime.combine(sunday(11, 1), dt.time(7), dt.timezone.utc)
    return start <= utc < end


_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
FIRST_SEEN_FORMAT = "texas-bill-statutes-first-seen-v1"
FIRST_SEEN_FILE = "first-seen.json"


# First-seen history: the day this job first indexed each bill as changing each section, kept in its own file that
# only grows. It is never rebuilt from the published index, so a bad run (no texts, a partial read, older code after a
# rollback) cannot erase it, and a pair that leaves and returns keeps its first day.
# {"format", "from": baseline day, "pairs": {key: {bill: day, or null when already indexed at the baseline}}}
def load_first_seen(path: Path) -> dict | None:
    """None when the file is absent; raises ValueError when it is present but not a valid history."""
    try:
        data = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(str(error)) from error
    if not (isinstance(data, dict) and data.get("format") == FIRST_SEEN_FORMAT
            and _DAY.fullmatch(str(data.get("from") or "")) and isinstance(data.get("pairs"), dict)):
        raise ValueError("not a first-seen history")
    for key, bills in data["pairs"].items():
        if not (isinstance(bills, dict) and all(isinstance(b, str) and (d is None or (isinstance(d, str) and _DAY.fullmatch(d)))
                                                 for b, d in bills.items())):
            raise ValueError(f"bad entry for {key!r}")
    return data


def merge_first_seen(history: dict | None, index: dict, day: str) -> dict:
    """The history plus every pair in the index it lacks, stamped `day`; nothing is ever removed or re-dated.
    Without a history the index's pairs are the baseline (null: present before first-seen days existed)."""
    pairs = {key: dict(bills) for key, bills in (history or {}).get("pairs", {}).items()}
    for key, entry in index["sections"].items():
        known = pairs.setdefault(key, {})
        for bill, _kind in entry["b"]:
            known.setdefault(bill, None if history is None else day)
    # Chapter pairs (keys have no dot, so they never meet a section key) join the same history. A history written
    # before chapters were indexed gets them as its baseline for them (null), so deploying this does not flood.
    chapters_from = (history or {}).get("chapters_from") or day
    stamp = day if (history or {}).get("chapters_from") else None
    for key, entry in (index.get("chapters") or {}).items():
        known = pairs.setdefault(key, {})
        for bill, _kind in entry["b"]:
            known.setdefault(bill, stamp)
    return {"format": FIRST_SEEN_FORMAT, "from": history["from"] if history else day, "chapters_from": chapters_from,
            "pairs": {key: dict(sorted(bills.items())) for key, bills in sorted(pairs.items())}}


def project_first_seen(index: dict, history: dict) -> None:
    """index.sections[key].f (and chapters[key].f) = {bill: day} for the index's pairs first seen after the baseline."""
    index["first_seen_from"] = history["from"]
    for group in ("sections", "chapters"):
        for key, entry in (index.get(group) or {}).items():
            known = history["pairs"].get(key, {})
            days = {bill: known[bill] for bill, _kind in entry["b"] if isinstance(known.get(bill), str)}
            if days:
                entry["f"] = days


def _index_has_sections(path: Path) -> bool:
    try:
        sections = json.loads(path.read_text("utf-8")).get("sections")
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(sections, dict) and bool(sections)


def write_statutes(snapshot: dict, text_dir: Path, out_dir: Path, today: str | None = None,
                   law_dir: Path | None = None) -> tuple[int, int, int]:
    """Writes out_dir/index.json and out_dir/sections/<CODE>-<section>.json; removes sections no bill touches now.
    Returns (written, unchanged, removed). Does nothing without a text directory, and keeps the previous index when
    this run found no section at all (an unreadable text folder). `today` is this run's day (tests pin it)."""
    if not text_dir.is_dir():
        return 0, 0, 0
    index, files = build_statutes(snapshot, text_dir, law_dir)
    if not index["sections"] and _index_has_sections(out_dir / "index.json"):
        print("Statute index: this run found no sections; keeping the previous index", file=sys.stderr, flush=True)
        return 0, 0, 0
    out_dir.mkdir(parents=True, exist_ok=True)
    day = today or chicago_today()
    try:
        history = load_first_seen(out_dir / FIRST_SEEN_FILE)
    except ValueError as error:
        # Never start over on top of a history we cannot read: that would mark every later pair old, or re-date them.
        print(f"Statute first-seen history unreadable ({error}); first-seen days not updated", file=sys.stderr, flush=True)
    else:
        if index["sections"] and _DAY.fullmatch(day):  # An empty index never becomes the baseline.
            history = merge_first_seen(history, index, day)
            # Before the index, so the index never names a day the history lacks.
            write_if_changed(out_dir / FIRST_SEEN_FILE, json.dumps(history, ensure_ascii=False, separators=(",", ":")) + "\n")
        if history is not None:  # Without a usable day the days already recorded still show.
            project_first_seen(index, history)
    sections_dir = out_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    written = unchanged = removed = 0
    for name, document in files.items():
        if write_if_changed(sections_dir / name, json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"):
            written += 1
        else:
            unchanged += 1
    for stale in sections_dir.glob("*.json"):
        if stale.name not in files and re.fullmatch(r"[A-Z]{2}-[0-9A-Z.]+\.json", stale.name):
            stale.unlink()
            removed += 1
    # The index goes last, so it never names a section file that is not there yet.
    write_if_changed(out_dir / "index.json", json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n")
    return written, unchanged, removed


# Law pages: live/share/law/<CODE>/<section>.html for every section a bill changes, served at /law/<CODE>/<section>
# by the gateway to search and link-preview crawlers (people get the app, which reads the path). Same rules as bill
# share pages: plain HTML, its own canonical address, the site card, and people sent on to the app.
LAW_KIND_WORDS = {"m": "amends", "n": "adds", "r": "repeals"}
LAW_TEXT_MAX = 3000  # Characters of the section's current text on its page; the rest is a link to our chapter copy.
_LAW_PAGE_NAME = re.compile(r"\d+[A-Z]?(?:\.\d+[A-Z]?)+\.html")


def _current_law(law, code: str, number: str) -> tuple[str, str, str] | None:
    """(heading line, text, chapter copy URL path) of a section in our copy of current law, or None."""
    if law is None:
        return None
    found = law.section_chapter(code, number)
    if not found:
        return None
    chapter, entry = found
    text = law.section_texts(code, chapter).get(number) or ""
    heading = next((s[1] for s in entry.get("sections", []) if s[0] == number), "")
    return heading, text, f"live/law/{code}/{chapter}.md"


def _law_shell_page(shell: str, *, title: str, url: str, label: str, feed: str, tags: str, body: list[str],
                    view: str, aria: str) -> str:
    """A law section or chapter page inside the site shell (SEO chunk 4 phase 5): the app takes it over in place."""
    a = lambda value: escape(value, {'"': "&quot;"})
    head = f"""
<title>{escape(title)} · Texas Bill Atlas</title>
<link rel="canonical" href="{a(url)}">
<link rel="alternate" type="application/rss+xml" title="{a(label)}" href="{a(feed)}">
{SHELL_ICONS}
{tags}
"""
    content = f'\n<article class="law-page static-page" aria-label="{a(aria)}">\n{chr(10).join(body)}\n</article>\n'
    version = hashlib.sha256((head + content).encode()).hexdigest()[:12]
    return pages.render_page(shell, head=f'{head}<meta name="page-version" content="{version}">', content=content,
                             view=view)


def law_page(key: str, entry: dict, code_name: str, current: tuple[str, str, str] | None, site: str = SITE,
             shell: str | None = None) -> str:
    """The page at /law/<CODE>/<section>. With the deployed shell it is the whole site page and the app takes it over;
    without one it is the standalone page, whose script sends people to the app."""
    code, number = key.split(" ")
    url, target = f"{site}law/{code}/{number}", f"{site}#statute?law={code}&sec={number}"
    feed = f"{site}live/feeds/law/{code}-{number}.xml"
    heading = (current[0] if current else "") or (f"Sec. {number}. {entry['h']}." if entry.get("h") else "")
    name = re.sub(r"^(?:Sec|Art)\.\s+\S+\.\s*", "", heading).rstrip(".").strip()
    label = law_label(code, number, code_name)
    title = clip(f"{label}: {name}" if name else label, SHARE_TITLE_MAX)
    bills = [b for b in entry.get("b") or [] if isinstance(b, list) and len(b) == 2 and BILL_ID.fullmatch(str(b[0]))]
    listed = ", ".join(f"{bill_number(b)} ({LAW_KIND_WORDS.get(k, 'changes')})" for b, k in bills[:6])
    more = f" and {len(bills) - 6} more" if len(bills) > 6 else ""
    count = f"{len(bills)} bill{'s' if len(bills) != 1 else ''} in the 90th Legislature would change this section"
    # Only bills add it and current law has no such section: a proposed new section, nothing to compare against.
    proposed = bool(bills) and all(k == "n" for _, k in bills) and not current
    what = ("A proposed new section, not in current law yet: read each bill's version." if proposed
            else "See each bill's wording next to today's law.")
    description = clip(f"{count}: {listed}{more}. {what}", SHARE_DESCRIPTION_MAX)
    image = f"{site}{SITE_CARD}"
    a = lambda value: escape(value, {'"': "&quot;"})
    meta = [("property", "og:type", "website"), ("property", "og:site_name", "Texas Bill Atlas"),
            ("property", "og:title", title), ("property", "og:description", description), ("property", "og:url", url),
            ("property", "og:image", image), ("property", "og:image:width", "1200"), ("property", "og:image:height", "630"),
            ("property", "og:image:alt", "Texas Bill Atlas"), ("name", "twitter:card", "summary_large_image"),
            ("name", "twitter:title", title), ("name", "twitter:description", description), ("name", "twitter:image", image),
            ("name", "twitter:image:alt", "Texas Bill Atlas"), ("name", "description", description)]
    tags = "\n".join(f'<meta {kind}="{n}" content="{a(value)}">' for kind, n, value in meta)
    items = "\n".join(f'<li><a href="{a(f"{site}bill/{b}")}">{escape(bill_number(b))}</a> '
                      f'{LAW_KIND_WORDS.get(k, "changes")} this section</li>' for b, k in bills)
    body = [f"<h1>{escape(label)}{': ' + escape(name) if name else ''}</h1>",
            f'<p><a href="{a(target)}">Open {escape(label)} in Texas Bill Atlas</a> '
            + ("to read each proposal.</p>" if proposed else "to compare each bill's wording with current law.</p>"),
            f"<h2>{escape(count[0].upper() + count[1:])}</h2>", f"<ul>\n{items}\n</ul>",
            "<p>Bills are matched to sections automatically from their text and can be missed, for example when a bill "
            "changes a whole chapter at once or renumbers sections. No bill listed here does not mean no bill changes "
            "this section.</p>"]
    # As the app's officialStatuteUrl (checked for every code the index uses).
    official = (f"https://statutes.capitol.texas.gov/?tab=1&code={code}&chapter={code}.{number.split('.')[0]}"
                f"&artSec={number}")
    links = []
    if current and current[1]:
        shown, cut = current[1][:LAW_TEXT_MAX], len(current[1]) > LAW_TEXT_MAX
        paragraphs = "\n".join(f"<p>{escape(p.strip())}</p>" for p in shown.split("\n") if p.strip())
        body += ["<h2>Current law</h2>", paragraphs]
        if cut:
            body.append(f'<p>The section continues: <a href="{a(site + current[2])}">whole chapter</a>.</p>')
        links.append(f'<li><a href="{a(site + current[2])}">This chapter as it stands now, Markdown copy of the '
                     f"Texas Legislative Council's statute files</a></li>")
    links.append(f'<li><a href="{a(official)}">Official text on statutes.capitol.texas.gov</a></li>')
    links.append(f'<li><a href="{a(feed)}">RSS feed of actions on these bills</a></li>')
    body += ["<h2>Links</h2>", "<ul>\n" + "\n".join(links) + "\n</ul>",
             "<p>Texas Bill Atlas is an independent research tool, not an official state website.</p>"]
    if shell is not None:  # The page is the app: no "Open in" link.
        return _law_shell_page(shell, title=title, url=url, label=label, feed=feed, tags=tags,
                               body=body[:1] + body[2:], view=f"law:{code} {number}", aria="Law section")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#112136">
<title>{escape(title)} · Texas Bill Atlas</title>
<link rel="canonical" href="{a(url)}">
<link rel="icon" href="/favicon.ico">
<link rel="alternate" type="application/rss+xml" title="{a(label)}" href="{a(feed)}">
{tags}
<script>if(!{_CRAWLER_JS}.test(navigator.userAgent))location.replace({json.dumps(target)})</script>
</head>
<body>
{chr(10).join(body)}
</body>
</html>
"""


LAW_LIMITS = ("Bills are matched to sections automatically from their text and can be missed: changes to a whole "
              "chapter at once, renumbering and unusual wording. No item here does not mean no bill changes this "
              "section.")
_LAW_FEED_NAME = re.compile(r"([A-Z]{2})-(\d+[A-Z]?(?:\.\d+[A-Z]?)+)\.xml")


def law_label(code: str, number: str, code_name: str | None = None) -> str:
    """"Penal Code § 46.06", or "Code of Criminal Procedure Art. 42.12", as the app's statuteLabel."""
    return f"{code_name or CODE_NAME.get(code, code)} {'Art.' if code == 'CR' else chr(0xa7)} {number}"


def law_feed(key: str, bills: list[tuple[dict, str]], site: str = SITE, reviews: dict | None = None,
             since: dict | None = None) -> str:
    """Every action on the bills that change one law section, newest first, capped like a member feed. A bill that
    started changing the section after the index began recording it (since = {bill: day}) also gets a dated
    "Now amends ..." item, so the change itself is news even when the bill's own actions are older."""
    reviews, since = reviews or {}, since or {}
    code, number = key.split(" ")
    label = law_label(code, number)
    official = (f"https://statutes.capitol.texas.gov/?tab=1&code={code}&chapter={code}.{number.split('.')[0]}"
                f"&artSec={number}")
    items = []
    for bill, kind in bills:
        verb = LAW_KIND_WORDS.get(kind, "changes")
        caption = bill.get("caption") or bill.get("title") or ""
        day = since.get(bill["id"])
        if isinstance(day, str) and _DAY.fullmatch(day):
            items.append({"bill": bill["id"], "text": f"Now {verb} {label}", "date": day,
                          "guid": f"{bill['id']}-law-{code}-{number}-{day}",
                          "caption": f"{bill_number(bill['id'])} {verb} {label}. {caption}"})
        for item in all_items(bill, reviews.get(bill["id"])):
            items.append({**item, "caption": f"{bill_number(bill['id'])} {verb} {label}. {item['caption']}"})
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return render_rss(f"{label} · Texas Bill Atlas", f"{site}law/{code}/{number}",
                      f"Actions on bills in the 90th Legislature that would change {label}. {LAW_LIMITS} "
                      f"Official text: {official} Unofficial; confirm on Texas Legislature Online.",
                      items[:MEMBER_FEED_ITEMS], site)


def write_law_feeds(snapshot: dict, index: dict, out_dir: Path, site: str = SITE,
                    reviews: dict | None = None) -> tuple[int, int]:
    """live/feeds/law/<CODE>-<section>.xml per section in the statute index. A feed whose section no bill changes now
    is rewritten empty, never removed, so a followed feed link keeps working."""
    by_id = {b["id"]: b for b in snapshot.get("bills") or []
             if isinstance(b, dict) and BILL_ID.fullmatch(str(b.get("id", "")))}
    feeds: dict[str, tuple[list, dict]] = {}
    for key, entry in (index.get("sections") or {}).items():
        if not STATUTE_KEY.fullmatch(key) or key[:2] not in CODE_NAME or not isinstance(entry, dict):
            continue  # Never build a file name from an unexpected key.
        pairs = entry.get("b") if isinstance(entry.get("b"), list) else []
        since = entry.get("f") if isinstance(entry.get("f"), dict) else {}
        feeds[key] = ([(by_id[x[0]], x[1]) for x in pairs
                       if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and x[0] in by_id], since)
    if not feeds:
        return 0, 0  # An empty or missing index never empties every feed.
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in out_dir.iterdir():
        found = _LAW_FEED_NAME.fullmatch(path.name)
        if found and found.group(1) in CODE_NAME:
            feeds.setdefault(f"{found.group(1)} {found.group(2)}", ([], {}))
    written = unchanged = 0
    for key, (bills, since) in feeds.items():
        if write_if_changed(out_dir / f"{key.replace(' ', '-')}.xml", law_feed(key, bills, site, reviews, since)):
            written += 1
        else:
            unchanged += 1
    return written, unchanged


def write_law_pages(index: dict, out_dir: Path, site: str = SITE, law_dir: Path | None = None,
                    shell: str | None = None) -> tuple[int, int, int]:
    """One page per section in the statute index (live/share/law/<CODE>/<section>.html), rewritten only when it
    changes; pages for sections no bill changes now are removed. Current text comes from live/law when present."""
    law = None
    if law_dir is not None and (law_dir / "index.json").is_file():
        from law_context import LawCopy  # Imported here: law_context reads this module's statute parser.
        law = LawCopy(law_dir)
    sections = index.get("sections") or {}
    written = unchanged = removed = 0
    keep: dict[str, set[str]] = {}
    for key, entry in sections.items():
        if not STATUTE_KEY.fullmatch(key) or key[:2] not in CODE_NAME or not isinstance(entry, dict):
            continue  # Never build a file name from an unexpected key.
        code, number = key.split(" ")
        keep.setdefault(code, set()).add(f"{number}.html")
        folder = out_dir / code
        folder.mkdir(parents=True, exist_ok=True)
        try:
            current = _current_law(law, code, number)
        except (OSError, ValueError, KeyError):
            current = None
        if write_if_changed(folder / f"{number}.html", law_page(key, entry, CODE_NAME[code], current, site, shell)):
            written += 1
        else:
            unchanged += 1
    if keep and out_dir.is_dir():  # An empty index never empties the folder.
        for folder in out_dir.iterdir():
            if not (folder.is_dir() and re.fullmatch(r"[A-Z]{2}", folder.name)):
                continue
            for path in folder.iterdir():
                if _LAW_PAGE_NAME.fullmatch(path.name) and path.name not in keep.get(folder.name, set()):
                    path.unlink(missing_ok=True)
                    removed += 1
    return written, unchanged, removed


# Chapter feeds and share pages. A chapter has bills when the index lists it (whole-chapter changes) or lists any
# section in it (the number before the first dot). Pages are not in the sitemap: the gateway serves /law/<CODE>/<section>
# only, so /law/PE/46 would 404 on reload; the app address is #chapter?law=PE&ch=46.
_LAW_CHAPTER_FEED_NAME = re.compile(r"([A-Z]{2})-(\d+[A-Z]?)\.xml")
_LAW_CHAPTER_PAGE_NAME = re.compile(r"\d+[A-Z]?\.html")
_SMALL_WORDS = {"of", "and", "the", "for", "to", "in", "by", "or", "a", "an", "on", "with", "under", "from", "as", "at"}


def title_case(heading: str) -> str:
    """"WEAPONS" -> "Weapons", "OFFENSES AGAINST THE PERSON" -> "Offenses Against the Person"."""
    words = re.sub(r"\s+", " ", heading or "").strip().split(" ")
    return " ".join(w.lower() if i and w.lower() in _SMALL_WORDS else re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), w)
                    for i, w in enumerate(words) if w)


def chapter_of(key: str) -> str:
    code, number = key.split(" ")
    return f"{code} {number.split('.')[0].upper()}"


def _valid_pairs(entry: dict) -> list[tuple[str, str]]:
    pairs = entry.get("b") if isinstance(entry.get("b"), list) else []
    return [(x[0], x[1]) for x in pairs if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str)
            and BILL_ID.fullmatch(x[0]) and isinstance(x[1], str)]


def chapter_groups(index: dict) -> dict[str, dict]:
    """{"PE 46": {"h", "whole": [(bill, kind)], "since": {bill: day}, "sections": {"PE 46.06": ([(bill, kind)], {bill: day}, heading)}}}
    for every chapter with a whole-chapter entry or a section in the index. Unexpected keys are skipped."""
    groups: dict[str, dict] = {}

    def group(key: str) -> dict:
        return groups.setdefault(key, {"h": "", "whole": [], "since": {}, "sections": {}})

    for key, entry in (index.get("chapters") or {}).items():
        if not (isinstance(key, str) and CHAPTER_KEY.fullmatch(key) and key[:2] in CODE_NAME and isinstance(entry, dict)):
            continue
        g = group(key)
        g["h"] = entry["h"] if isinstance(entry.get("h"), str) else ""
        g["whole"] = _valid_pairs(entry)
        g["since"] = {b: d for b, d in (entry.get("f") if isinstance(entry.get("f"), dict) else {}).items()
                      if isinstance(d, str)}
    for key, entry in (index.get("sections") or {}).items():
        if not (isinstance(key, str) and STATUTE_KEY.fullmatch(key) and key[:2] in CODE_NAME and isinstance(entry, dict)):
            continue
        since = {b: d for b, d in (entry.get("f") if isinstance(entry.get("f"), dict) else {}).items() if isinstance(d, str)}
        group(chapter_of(key))["sections"][key] = (_valid_pairs(entry), since,
                                                   entry["h"] if isinstance(entry.get("h"), str) else "")
    return groups


def chapter_label(code: str, chapter: str, heading: str = "") -> str:
    """"Penal Code chapter 46 (Weapons)"."""
    return f"{CODE_NAME.get(code, code)} chapter {chapter}" + (f" ({title_case(heading)})" if heading else "")


def _chapter_heading(g: dict, law, code: str, chapter: str) -> str:
    return g["h"] or _law_chapter_title(law, code, chapter)


def _section_short(code: str, number: str) -> str:
    return f"{'Art.' if code == 'CR' else chr(0xa7)} {number}"


def chapter_feed(key: str, g: dict, by_id: dict[str, dict], heading: str = "", site: str = SITE,
                 reviews: dict | None = None) -> str:
    """Every action on the bills that change a whole chapter or any section in it, newest first. Each bill's actions
    appear once; a "Now amends § 46.06" / "Now repeals the whole chapter" item is added for each pair first seen
    after the index began recording (its date from the pair's first-seen day)."""
    reviews = reviews or {}
    code, chapter = key.split(" ")
    label = chapter_label(code, chapter, heading)
    items, subjects = [], {}
    pairs = [(b, k, None, g["since"].get(b)) for b, k in g["whole"] if b in by_id]
    for skey, (spairs, since, _h) in sorted(g["sections"].items()):
        pairs += [(b, k, skey.split(" ")[1], since.get(b)) for b, k in spairs if b in by_id]
    for bill_id, kind, number, day in pairs:
        verb = LAW_KIND_WORDS.get(kind, "changes")
        what = "the whole chapter" if number is None else _section_short(code, number)
        subjects.setdefault(bill_id, []).append(f"{verb} {label if number is None else law_label(code, number)}")
        if isinstance(day, str) and _DAY.fullmatch(day):
            guid = f"{bill_id}-law-{code}-{chapter if number is None else number}-{day}"
            items.append({"bill": bill_id, "text": f"Now {verb} {what}", "date": day, "guid": guid,
                          "caption": f"{bill_number(bill_id)} {verb} {label if number is None else law_label(code, number)}. "
                                     f"{by_id[bill_id].get('caption') or by_id[bill_id].get('title') or ''}"})
    for bill_id, parts in subjects.items():
        shown = " and ".join(parts[:3]) + (f" and {len(parts) - 3} more" if len(parts) > 3 else "")
        for item in all_items(by_id[bill_id], reviews.get(bill_id)):
            items.append({**item, "caption": f"{bill_number(bill_id)} {shown}. {item['caption']}"})
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    official = f"https://statutes.capitol.texas.gov/?tab=1&code={code}&chapter={code}.{chapter}"
    return render_rss(f"{label} · Texas Bill Atlas", f"{site}#chapter?law={code}&ch={chapter}",
                      f"Actions on bills in the 90th Legislature that would change {label}, as a whole or in any of its "
                      f"sections. {LAW_LIMITS.replace('this section', 'this chapter')} Official text: {official} "
                      f"Unofficial; confirm on Texas Legislature Online.", items[:MEMBER_FEED_ITEMS], site)


def write_law_chapter_feeds(snapshot: dict, index: dict, out_dir: Path, site: str = SITE, reviews: dict | None = None,
                            law_dir: Path | None = None) -> tuple[int, int]:
    """live/feeds/law/<CODE>-<chapter>.xml per chapter with a bill. A chapter that loses its bills is rewritten empty,
    never removed. An index with no chapters writes nothing."""
    groups = chapter_groups(index)
    if not groups:
        return 0, 0
    by_id = {b["id"]: b for b in snapshot.get("bills") or []
             if isinstance(b, dict) and BILL_ID.fullmatch(str(b.get("id", "")))}
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in out_dir.iterdir():
        found = _LAW_CHAPTER_FEED_NAME.fullmatch(path.name)
        if found and found.group(1) in CODE_NAME:
            groups.setdefault(f"{found.group(1)} {found.group(2)}", {"h": "", "whole": [], "since": {}, "sections": {}})
    law = _open_law(law_dir)
    written = unchanged = 0
    for key, g in groups.items():
        code, chapter = key.split(" ")
        text = chapter_feed(key, g, by_id, _chapter_heading(g, law, code, chapter), site, reviews)
        if write_if_changed(out_dir / f"{code}-{chapter}.xml", text):
            written += 1
        else:
            unchanged += 1
    return written, unchanged


def law_chapter_page(key: str, g: dict, heading: str = "", site: str = SITE, shell: str | None = None) -> str:
    """The page at /law/<CODE>/<chapter>, built like law_page. The standalone page still sends people to the old
    #chapter address: pointed at its own path, it would reload itself once the gateway serves it to everyone."""
    code, chapter = key.split(" ")
    code_name = CODE_NAME[code]
    url, target = f"{site}law/{code}/{chapter}", f"{site}#chapter?law={code}&ch={chapter}"
    feed = f"{site}live/feeds/law/{code}-{chapter}.xml"
    name = title_case(heading)
    label = f"{code_name} Chapter {chapter}"
    title = clip(f"{label}: {name}" if name else label, SHARE_TITLE_MAX)
    whole = g["whole"]
    sections = {k: v for k, v in sorted(g["sections"].items()) if v[0]}
    bill_ids = sorted({b for b, _ in whole} | {b for pairs, _s, _h in sections.values() for b, _ in pairs},
                      key=_bill_order)
    count = (f"{len(bill_ids)} bill{'s' if len(bill_ids) != 1 else ''} in the 90th Legislature would change something "
             f"in this chapter")
    description = clip(f"{count}. Follow it in Texas Bill Atlas to see when another bill does.", SHARE_DESCRIPTION_MAX)
    image = f"{site}{SITE_CARD}"
    a = lambda value: escape(value, {'"': "&quot;"})
    meta = [("property", "og:type", "website"), ("property", "og:site_name", "Texas Bill Atlas"),
            ("property", "og:title", title), ("property", "og:description", description), ("property", "og:url", url),
            ("property", "og:image", image), ("property", "og:image:width", "1200"), ("property", "og:image:height", "630"),
            ("property", "og:image:alt", "Texas Bill Atlas"), ("name", "twitter:card", "summary_large_image"),
            ("name", "twitter:title", title), ("name", "twitter:description", description), ("name", "twitter:image", image),
            ("name", "twitter:image:alt", "Texas Bill Atlas"), ("name", "description", description)]
    tags = "\n".join(f'<meta {kind}="{n}" content="{a(value)}">' for kind, n, value in meta)
    body = [f"<h1>{escape(label)}{': ' + escape(name) if name else ''}</h1>",
            f'<p><a href="{a(target)}">Open {escape(label)} in Texas Bill Atlas</a> to follow it: anything a bill '
            f"changes in this chapter shows up as new.</p>",
            f"<h2>{escape(count[0].upper() + count[1:])}</h2>"]
    if whole:
        body += ["<h3>Bills that change the whole chapter</h3>", "<ul>\n" + "\n".join(
            f'<li><a href="{a(f"{site}bill/{b}")}">{escape(bill_number(b))}</a> {LAW_KIND_WORDS.get(k, "changes")} '
            f"the whole chapter</li>" for b, k in whole) + "\n</ul>"]
    if sections:
        rows = []
        for skey, (pairs, _since, shead) in sections.items():
            number = skey.split(" ")[1]
            who = ", ".join(f'<a href="{a(f"{site}bill/{b}")}">{escape(bill_number(b))}</a> '
                            f'({LAW_KIND_WORDS.get(k, "changes")})' for b, k in pairs)
            rows.append(f'<li><a href="{a(f"{site}law/{code}/{number}")}">{escape(_section_short(code, number))}</a>'
                        f"{': ' + escape(shead) if shead else ''}: {who}</li>")
        body += ["<h3>Sections bills change</h3>", "<ul>\n" + "\n".join(rows) + "\n</ul>"]
    body += ["<p>Bills are matched to sections automatically from their text and can be missed, for example when a bill "
             "renumbers sections or uses unusual wording. No bill listed here does not mean no bill changes this "
             "chapter.</p>"]
    official = f"https://statutes.capitol.texas.gov/?tab=1&code={code}&chapter={code}.{chapter}"
    body += ["<h2>Links</h2>", "<ul>\n" + "\n".join([
        f'<li><a href="{a(official)}">Official text on statutes.capitol.texas.gov</a></li>',
        f'<li><a href="{a(feed)}">RSS feed of actions on these bills</a></li>']) + "\n</ul>",
        "<p>Texas Bill Atlas is an independent research tool, not an official state website.</p>"]
    if shell is not None:  # The page is the app: no "Open in" link.
        return _law_shell_page(shell, title=title, url=url, label=label, feed=feed, tags=tags,
                               body=body[:1] + body[2:], view=f"chapter:{code} {chapter}", aria="Law chapter")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#112136">
<title>{escape(title)} · Texas Bill Atlas</title>
<link rel="canonical" href="{a(url)}">
<link rel="icon" href="/favicon.ico">
<link rel="alternate" type="application/rss+xml" title="{a(label)}" href="{a(feed)}">
{tags}
<script>if(!{_CRAWLER_JS}.test(navigator.userAgent))location.replace({json.dumps(target)})</script>
</head>
<body>
{chr(10).join(body)}
</body>
</html>
"""


def write_law_chapter_pages(index: dict, out_dir: Path, site: str = SITE,
                            law_dir: Path | None = None, shell: str | None = None) -> tuple[int, int, int]:
    """live/share/law/<CODE>/<chapter>.html per chapter with a bill, rewritten only when it changes; pages of chapters
    with none now are removed (section pages in the same folders are never touched). An index with no chapters
    removes nothing."""
    groups = chapter_groups(index)
    law = _open_law(law_dir)
    written = unchanged = removed = 0
    keep: dict[str, set[str]] = {}
    for key, g in groups.items():
        code, chapter = key.split(" ")
        keep.setdefault(code, set()).add(f"{chapter}.html")
        folder = out_dir / code
        folder.mkdir(parents=True, exist_ok=True)
        if write_if_changed(folder / f"{chapter}.html", law_chapter_page(key, g, _chapter_heading(g, law, code, chapter), site, shell)):
            written += 1
        else:
            unchanged += 1
    if keep and out_dir.is_dir():
        for folder in out_dir.iterdir():
            if not (folder.is_dir() and re.fullmatch(r"[A-Z]{2}", folder.name)):
                continue
            for path in folder.iterdir():
                if _LAW_CHAPTER_PAGE_NAME.fullmatch(path.name) and path.name not in keep.get(folder.name, set()):
                    path.unlink(missing_ok=True)
                    removed += 1
    return written, unchanged, removed


# Population brackets live in atlas/feeds/brackets/. They are imported on first use, because that package reads the
# statute helpers above; every bracket name stays reachable here (build_feeds.bill_brackets and so on).
def __getattr__(name: str):
    if not name.startswith("__"):
        from atlas.feeds.brackets import index, parse
        for module in (index, parse):
            if name in vars(module):
                return vars(module)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Public feeds directory, e.g. live/feeds")
    parser.add_argument("--site", default=SITE)
    parser.add_argument("--tags", type=Path, default=None,
                        help="Published Luna tags; defaults to luna/tags.json beside the snapshot when present")
    parser.add_argument("--members", type=Path, default=None,
                        help="Legislator roster for per-member feeds; defaults to members.json beside the snapshot")
    parser.add_argument("--extras", type=Path, default=None,
                        help="Luna extras (In brief lines); defaults to extras.json beside the tags")
    parser.add_argument("--share", type=Path, default=None,
                        help="Share page output (served at /bill/<ID>); defaults to share/ beside the snapshot")
    parser.add_argument("--sitemap", type=Path, default=None,
                        help="Sitemap output (served at /live/sitemap.xml); defaults to sitemap.xml beside the snapshot")
    parser.add_argument("--og", type=Path, default=None,
                        help="Share card folder (cards.json out, rendered.json in); defaults to og/ beside the snapshot")
    parser.add_argument("--text", type=Path, default=None, help="Bill text directory; defaults to text/ beside the snapshot")
    parser.add_argument("--statutes", type=Path, default=None,
                        help="Statute index output; defaults to statutes/ beside the snapshot")
    parser.add_argument("--today", default=None,
                        help="This run's day (YYYY-MM-DD) for statute first-seen days; defaults to today in Chicago")
    parser.add_argument("--census", type=Path, default=None,
                        help="2020 population table (scripts/census_places.py); defaults to one beside this script")
    parser.add_argument("--brackets", type=Path, default=None,
                        help="Population bracket output; defaults to brackets/ beside the snapshot")
    parser.add_argument("--shell", type=Path, default=pages.SHELL_PATH,
                        help="The deployed page shell (shell.html in the current release); bill and law pages are "
                             "standalone without one")
    parser.add_argument("--no-indexnow", action="store_true",
                        help="Don't submit changed bill pages to IndexNow (only the server's live run submits anyway)")
    args = parser.parse_args()
    tags = args.tags or args.snapshot.parent / "luna" / "tags.json"
    snapshot, reviews = json.loads(args.snapshot.read_text("utf-8")), load_reviews(tags)
    written, unchanged = write_feeds(snapshot, args.out, args.site, reviews)
    print(f"Feeds: {written} written, {unchanged} unchanged", flush=True)
    headlines = load_headlines(args.extras or tags.parent / "extras.json")
    og_dir = args.og or args.snapshot.parent / "og"
    count, changed = write_og_cards(snapshot, og_dir)
    print(f"Share cards: {count} listed{', changed' if changed else ''}", flush=True)
    write_bill_art(og_dir)  # No output line: the golden run pins this script's stdout.
    text_dir = args.text or args.snapshot.parent / "text"
    changed: list[str] = []
    shell = pages.load_shell(args.shell)
    written, unchanged, removed = write_share_pages(snapshot, args.share or args.snapshot.parent / "share", args.site,
                                                    headlines, load_rendered(og_dir / "rendered.json"), text_dir, changed,
                                                    shell)
    print(f"Share pages: {written} written, {unchanged} unchanged, {removed} removed", flush=True)
    if not args.no_indexnow and args.site == SITE and args.snapshot == LIVE_SNAPSHOT:
        print(f"IndexNow: {submit_indexnow(changed, args.site)}", flush=True)
    write_api_docs(args.snapshot.parent)
    roster = load_roster(args.members or args.snapshot.parent / "members.json")
    written, unchanged = write_member_feeds(snapshot, roster, args.out / "members", args.site, reviews)
    print(f"Member feeds: {written} written, {unchanged} unchanged", flush=True)
    statutes_dir = args.statutes or args.snapshot.parent / "statutes"
    written, unchanged, removed = write_statutes(snapshot, text_dir, statutes_dir, args.today, args.snapshot.parent / "law")
    print(f"Statute sections: {written} written, {unchanged} unchanged, {removed} removed", flush=True)
    # Quiet from here to the brackets (golden stdout): law and member pages, then the sitemap that lists them.
    try:
        statute_index = json.loads((statutes_dir / "index.json").read_text("utf-8"))
    except (OSError, ValueError):
        statute_index = {}
    law_keys = list((statute_index.get("sections") or {}) if isinstance(statute_index, dict) else {})
    if law_keys:
        write_law_pages(statute_index, (args.share or args.snapshot.parent / "share") / "law", args.site,
                        args.snapshot.parent / "law", shell)
        write_law_feeds(snapshot, statute_index, args.out / "law", args.site, reviews)
    if law_keys or (isinstance(statute_index, dict) and statute_index.get("chapters")):
        write_law_chapter_pages(statute_index, (args.share or args.snapshot.parent / "share") / "law", args.site,
                                args.snapshot.parent / "law", shell)
        write_law_chapter_feeds(snapshot, statute_index, args.out / "law", args.site, reviews, args.snapshot.parent / "law")
    write_member_pages(snapshot, roster, (args.share or args.snapshot.parent / "share") / "member", args.site, shell)
    # Members are listed only with their pages: without the shell the address would serve the bare app.
    members = [m for m in roster.values() if isinstance(m, dict)] if shell else []
    write_if_changed(args.sitemap or args.snapshot.parent / "sitemap.xml",
                     sitemap(snapshot, args.site, law_keys, members))
    from atlas.feeds.brackets import default_census, write_brackets
    status = write_brackets(snapshot, text_dir, args.census or default_census(), args.brackets or args.snapshot.parent / "brackets")
    print(f"Population brackets: {status}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
