"""What a browser and a crawler receive for each address, with no JavaScript (SEO chunk 1).

Network mode (run by hand, never in CI): fetches each address as a desktop browser, a phone browser, Googlebot and
Discordbot, one request per second by default, and reports status, final URL, title, description, canonical, og:url,
robots, JSON-LD types, the main content's text length and whether the HTML differs between user agents.
    python scripts/check_pages.py                      # fixed addresses plus a sample of the live sitemap
    python scripts/check_pages.py /bill/HB1094 /law/PE/46.06 --sample 0
Fixture mode (CI): the same rules over a folder of generated share pages, mapped to the addresses the gateway serves.
    python scripts/check_pages.py --fixtures live/share

Exits 1 when an indexable page (200, no noindex) has no title or description, a fragment canonical or one that is
not its own address, when user agents get different HTML, or when a not-found page served as 200 (a soft 404: an
element marked data-not-found, as the app's not-found views are) is indexable or names itself as canonical."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

SITE = "https://billatlas.org/"
CHECKER = "billatlas-check/1 (+https://billatlas.org/)"
AGENTS = {
    "desktop": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36 {CHECKER}",
    "phone": f"Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36 {CHECKER}",
    "googlebot": f"Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) {CHECKER}",
    "discordbot": f"Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com) {CHECKER}",
}
# One address per page type; the sitemap sample adds more.
FIXED = ["/", "/bill/HB1094", "/law/PE/46.06", "/law", "/law/PE"]
SITEMAP = "live/sitemap.xml"
MEMBER_FILE = re.compile(r"A\d{3,5}")  # member/<code>.html, served at /member/<code>/<slug>.
MEMBER_SLUG = re.compile(r"/[a-z0-9-]{1,60}")
GROUP_FILE = {"topic": re.compile(r"[a-z0-9][a-z0-9-]{0,79}"), "agency": re.compile(r"[a-z0-9][a-z0-9-]{0,40}"),
              "about": re.compile(r"method|saving|data")}


class PageParser(HTMLParser):
    """Collects the head facts and the text inside <main> (or <body> when there is none)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.canonical, self.ld = None, {}, None, []
        self.not_found = False  # An element marked data-not-found: the app's "no such bill/agency/..." view.
        self._in_title = self._in_ld = False
        self._skip = 0  # Inside <script> or <style> (not counted as text).
        self._main_depth = 0
        self.main_text, self.body_text, self.has_main = [], [], False
        self._in_body = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if "data-not-found" in a:
            self.not_found = True
        if tag == "title" and self.title is None:
            self._in_title, self._buf = True, []
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = a.get("content", "")
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split() and self.canonical is None:
            self.canonical = a.get("href", "")
        elif tag == "script":
            self._skip += 1
            if a.get("type", "").lower() == "application/ld+json":
                self._in_ld, self._buf = True, []
        elif tag == "style":
            self._skip += 1
        elif tag == "body":
            self._in_body = True
        elif tag == "main":
            self.has_main = True
            self._main_depth += 1

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title, self.title = False, " ".join("".join(self._buf).split())
        elif tag == "script":
            self._skip = max(0, self._skip - 1)
            if self._in_ld:
                self._in_ld = False
                self.ld.append("".join(self._buf))
        elif tag == "style":
            self._skip = max(0, self._skip - 1)
        elif tag == "main":
            self._main_depth = max(0, self._main_depth - 1)

    def handle_data(self, data):
        if self._in_title or self._in_ld:
            self._buf.append(data)
        elif not self._skip:
            if self._main_depth:
                self.main_text.append(data)
            if self._in_body:
                self.body_text.append(data)


def ld_types(blocks: list[str]) -> list[str]:
    types: list[str] = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            t = node.get("@type")
            types.extend(t if isinstance(t, list) else [t] if t else [])
            walk(node.get("@graph"))
    for block in blocks:
        try:
            walk(json.loads(block))
        except ValueError:
            types.append("(invalid JSON-LD)")
    return [str(t) for t in types]


# JSON-LD each kind of static page must carry (SEO chunk 6), by the address's first path segment.
EXPECTED_LD = {"bill": ("Legislation", "BreadcrumbList"), "law": ("Legislation", "BreadcrumbList"),
               "member": ("ProfilePage", "BreadcrumbList"), "topic": ("CollectionPage", "BreadcrumbList"),
               "agency": ("CollectionPage", "BreadcrumbList"), "about": ("BreadcrumbList",),
               "today": ("BreadcrumbList",), "": ("WebSite",)}


def expected_ld(url: str) -> tuple[str, ...]:
    path = urlsplit(url).path.strip("/")
    if path == "law":  # The code index (/law) lists the codes; /law/<CODE> and below are Legislation.
        return ("CollectionPage", "BreadcrumbList")
    return EXPECTED_LD.get(path.split("/")[0], ())


def normalized_hash(page: str) -> str:
    """Whitespace collapsed and nonces dropped, so only a real difference between user agents counts."""
    page = re.sub(r'\snonce="[^"]*"', "", page)
    page = re.sub(r">\s+<", "><", page)
    return hashlib.sha256(" ".join(page.split()).encode()).hexdigest()[:12]


def plain_url(url: str) -> str:
    """Scheme and host lowercased, no query or fragment: what a canonical is compared on."""
    p = urlsplit(url)
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path or '/'}"


def inspect(page: str, url: str, status: int = 200, robots_header: str = "") -> dict:
    """The facts and rule failures for one response. `url` is the address the page is served at (final URL)."""
    parser = PageParser()
    parser.feed(page)
    parser.close()
    text = parser.main_text if parser.has_main else parser.body_text
    robots = ",".join(filter(None, [parser.meta.get("robots", ""), parser.meta.get("googlebot", ""), robots_header])).lower()
    canonical = urljoin(url, parser.canonical) if parser.canonical else None
    facts = {"status": status, "url": url, "title": parser.title, "description": parser.meta.get("description"),
             "canonical": canonical, "og_url": parser.meta.get("og:url"), "robots": robots or None,
             "jsonld": ld_types(parser.ld), "text_length": len(" ".join(" ".join(text).split())),
             "hash": normalized_hash(page), "not_found": parser.not_found}
    failures = []
    if parser.not_found and status == 200:  # A soft 404: never indexable, and never its own canonical.
        if "noindex" not in robots:
            failures.append("not-found page is indexable")
        if canonical and plain_url(canonical) == plain_url(url):
            failures.append("not-found page names itself as canonical")
    if status == 200 and "noindex" not in robots:  # Indexable: the rules apply.
        if not facts["title"]:
            failures.append("no title")
        if not (facts["description"] or "").strip():
            failures.append("no description")
        if canonical and "#" in parser.canonical:
            failures.append(f"fragment canonical {parser.canonical}")
        elif canonical and plain_url(canonical) != plain_url(url):
            failures.append(f"canonical is {canonical}, not this address")
        if "(invalid JSON-LD)" in facts["jsonld"]:
            failures.append("invalid JSON-LD")
        missing = [t for t in expected_ld(url) if t not in facts["jsonld"]]
        if missing:
            failures.append("no JSON-LD " + ", ".join(missing))
    facts["failures"] = failures
    return facts


def compare_agents(results: dict[str, dict]) -> list[str]:
    """A failure when user agents were served different HTML for one address."""
    hashes = {name: r["hash"] for name, r in results.items() if r.get("hash")}
    if len(set(hashes.values())) > 1:
        groups: dict[str, list[str]] = {}
        for name, h in hashes.items():
            groups.setdefault(h, []).append(name)
        return ["different HTML per user agent: " + " vs ".join("+".join(v) for v in groups.values())]
    return []


# Network mode.

def fetch(url: str, agent: str, timeout: float = 20) -> tuple[int, str, str, str]:
    """(status, final URL, body, X-Robots-Tag). Follows redirects; an HTTP error still returns its body."""
    request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "text/html,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, response.geturl(), body, response.headers.get("X-Robots-Tag", "")
    except urllib.error.HTTPError as error:
        return error.code, error.geturl() or url, error.read().decode("utf-8", "replace"), error.headers.get("X-Robots-Tag", "")


def _spread(locs: list[str], count: int) -> list[str]:
    if count <= 0 or not locs:
        return []
    step = max(1, len(locs) // count)
    return locs[step // 2::step][:count]  # Off the first entry, which is the home page.


def sitemap_sample(xml: str, count: int, load=None) -> list[str]:
    """`count` addresses spread evenly through the sitemap (the same ones each run while it is unchanged). An index is
    followed into its children (fetched with load(url) -> xml), the count shared between them."""
    def pages(text: str) -> list[str]:
        return [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text) if "/live/" not in urlsplit(u).path]

    if "<sitemapindex" not in xml:
        return _spread(pages(xml), count)
    children = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    if load is None or count <= 0 or not children:
        return []
    out = []
    for i, child in enumerate(children):
        try:
            locs = pages(load(child))
        except (OSError, ValueError):
            continue  # An unreadable child is skipped; the others still sample.
        out += _spread(locs, count // len(children) + (1 if i < count % len(children) else 0))
    return out


def check_network(addresses: list[str], site: str, delay: float, getter=fetch, sleep=time.sleep) -> list[dict]:
    reports, first = [], True
    for address in addresses:
        url = urljoin(site, address)
        if "/live/" in urlsplit(url).path:
            continue  # Data files, not pages.
        per_agent = {}
        for name, agent in AGENTS.items():
            if not first:
                sleep(delay)
            first = False
            try:
                status, final, body, robots = getter(url, agent)
            except (OSError, ValueError) as error:
                per_agent[name] = {"status": None, "url": url, "failures": [f"fetch failed: {error}"], "hash": None}
                continue
            per_agent[name] = inspect(body, final, status, robots)
            per_agent[name]["final_url"] = final
        reports.append({"address": url, "agents": per_agent, "failures": compare_agents(per_agent)})
    return reports


# Fixture mode.

def fixture_address(path: Path, root: Path, site: str) -> str | None:
    """The address the gateway serves a share page at, or None for a page it does not serve."""
    rel = path.relative_to(root).with_suffix("").as_posix()
    parts = rel.split("/")
    if rel == "home":
        return site
    if rel == "today":
        return f"{site}today"
    if len(parts) == 1:
        return f"{site}bill/{parts[0]}"
    if len(parts) == 3 and parts[0] == "law" and parts[1] == "CN" and "." in parts[2]:  # A Constitution section.
        return f"{site}law/CN/{parts[2].replace('.', '/', 1)}"
    if len(parts) == 3 and parts[0] == "law":  # A section or a chapter: the gateway serves both.
        return f"{site}law/{parts[1]}/{parts[2]}"
    if rel == "law/index":
        return f"{site}law"
    if len(parts) == 2 and parts[0] == "law" and re.fullmatch(r"[A-Z]{2}", parts[1]):  # A code page.
        return f"{site}law/{parts[1]}"
    if len(parts) == 2 and parts[0] in GROUP_FILE and GROUP_FILE[parts[0]].fullmatch(parts[1]):
        return f"{site}{parts[0]}/{parts[1]}"
    if len(parts) == 2 and parts[0] == "member" and MEMBER_FILE.fullmatch(parts[1]):
        # Served at /member/<code>/<any slug>: the address is the page's own canonical when it is one of those.
        base = f"{site}member/{parts[1]}"
        parser = PageParser()
        parser.feed(path.read_text(encoding="utf-8"))
        canonical = parser.canonical or ""
        own = canonical.startswith(base) and (canonical == base or MEMBER_SLUG.fullmatch(canonical[len(base):]))
        return canonical if own else base
    return None


def check_fixtures(root: Path, site: str) -> tuple[list[dict], list[str]]:
    reports, skipped = [], []
    for path in sorted(root.rglob("*.html")):
        url = fixture_address(path, root, site)
        if url is None:
            skipped.append(path.relative_to(root).as_posix())
            continue
        facts = inspect(path.read_text(encoding="utf-8"), url)
        reports.append({"address": url, "agents": {"file": facts}, "failures": []})
    return reports, skipped


def all_failures(report: dict) -> list[str]:
    out = list(report["failures"])
    for name, facts in report["agents"].items():
        out += [f"{name}: {f}" for f in facts.get("failures", [])]
    return out


def print_report(reports: list[dict], out=None, only_failing: bool = False) -> None:
    out = out or sys.stdout
    for report in reports:
        failures = all_failures(report)
        if only_failing and not failures:
            continue
        print(f"{'FAIL' if failures else 'ok  '} {report['address']}", file=out)
        for name, f in report["agents"].items():
            print(f"     {name:<10} {f.get('status')} {f.get('final_url', f.get('url'))} title={f.get('title')!r} "
                  f"desc={'yes' if f.get('description') else 'no'} canonical={f.get('canonical')} og:url={f.get('og_url')} "
                  f"robots={f.get('robots')} ld={','.join(f.get('jsonld') or []) or '-'} text={f.get('text_length')} "
                  f"hash={f.get('hash')}", file=out)
        for failure in failures:
            print(f"     ! {failure}", file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("addresses", nargs="*", help=f"Paths or URLs; default {' '.join(FIXED)} plus the sitemap sample")
    parser.add_argument("--site", default=SITE)
    parser.add_argument("--sample", type=int, default=5, help="Sitemap addresses to add (0: none)")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests (default 1)")
    parser.add_argument("--fixtures", type=Path, help="Check a folder of share pages instead of the network")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args(argv)
    skipped: list[str] = []
    if args.fixtures:
        reports, skipped = check_fixtures(args.fixtures, args.site)
    else:
        addresses = list(args.addresses) or list(FIXED)
        if args.sample > 0:
            _, _, xml, _ = fetch(urljoin(args.site, SITEMAP), AGENTS["desktop"])
            def load_child(url: str) -> str:
                time.sleep(args.delay)
                return fetch(url, AGENTS["desktop"])[2]
            addresses += sitemap_sample(xml, args.sample, load_child)
            time.sleep(args.delay)
        urls = list(dict.fromkeys(urljoin(args.site, a) for a in addresses))
        reports = check_network(urls, args.site, args.delay)
    failed = [r for r in reports if all_failures(r)]
    if args.json:
        print(json.dumps({"reports": reports, "skipped": skipped, "failed": len(failed)}, indent=1))
    else:
        print_report(reports, only_failing=bool(args.fixtures))  # Thousands of fixture pages: failures only.
        if skipped:
            print(f"skipped {len(skipped)} page(s) the gateway does not serve (e.g. {skipped[0]})")
        print(f"{len(reports)} address(es), {len(failed)} failing")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
