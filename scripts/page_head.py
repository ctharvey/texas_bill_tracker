"""Head tags and structured data for the static pages build_feeds.py writes (SEO chunk 6).

Every page builder passes its facts to head_html(); the JSON-LD builders here only describe facts the page itself
shows. The static head is the indexed head: the app leaves it alone on the page it takes over (src/core/head.js
writes the same title format only after in-app moves).
"""

import json
from xml.sax.saxutils import escape  # As build_feeds: &, < and > (and " in attributes); apostrophes stay as they are.

SITE_NAME = "Texas Bill Atlas"
CARD_SIZE = ("1200", "630")
# The icon links index.html keeps in its head slot (scripts/pages.py replaces the whole slot).
SHELL_ICONS = "\n".join(('<link rel="icon" href="/favicon.ico" sizes="32x32">',
                         '<link rel="icon" href="/icon.png" type="image/png" sizes="192x192">',
                         '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'))


def attr(value: object) -> str:
    return escape(str(value), {'"': "&quot;"})


def page_title(title: str) -> str:
    """'HB 5: Relating to ...' -> 'HB 5: Relating to ... · Texas Bill Atlas' (the app's document.title format)."""
    return f"{title} · {SITE_NAME}"


def meta_tags(*, title: str, description: str, og_url: str, image: str, image_alt: str = SITE_NAME,
              og_type: str = "website") -> str:
    """og, twitter and description meta tags, in a fixed order."""
    meta = [("property", "og:type", og_type), ("property", "og:site_name", SITE_NAME),
            ("property", "og:title", title), ("property", "og:description", description), ("property", "og:url", og_url),
            ("property", "og:image", image), ("property", "og:image:width", CARD_SIZE[0]),
            ("property", "og:image:height", CARD_SIZE[1]), ("property", "og:image:alt", image_alt),
            ("name", "twitter:card", "summary_large_image"), ("name", "twitter:title", title),
            ("name", "twitter:description", description), ("name", "twitter:image", image),
            ("name", "twitter:image:alt", image_alt), ("name", "description", description)]
    return "\n".join(f'<meta {kind}="{name}" content="{attr(value)}">' for kind, name, value in meta)


def jsonld_script(data: dict) -> str:
    # "<" escaped so no caption can close the script element; "&" so the page holds no raw ampersand.
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("&", "\\u0026")
    return f'<script type="application/ld+json">{text}</script>'


def head_html(*, title: str, description: str, url: str, image: str, image_alt: str = SITE_NAME,
              og_type: str = "website", og_url: str | None = None, links: tuple[str, ...] = (),
              jsonld: tuple[dict, ...] = (), icons: bool = True) -> str:
    """The head slot of a static page: title, self canonical, extra <link>s, icons, meta tags and JSON-LD.
    title is the page's own part (clipped by the caller); og_url defaults to the canonical."""
    parts = [f"<title>{escape(page_title(title))}</title>", f'<link rel="canonical" href="{attr(url)}">', *links]
    if icons:
        parts.append(SHELL_ICONS)
    parts.append(meta_tags(title=title, description=description, og_url=og_url or url, image=image,
                           image_alt=image_alt, og_type=og_type))
    parts += [jsonld_script(data) for data in jsonld]
    return "\n" + "\n".join(parts) + "\n"


# Structured data (schema.org). Each takes the page's own facts.

TEXAS = {"@type": "AdministrativeArea", "name": "Texas"}


def breadcrumbs(site: str, trail: list[tuple[str, str]]) -> dict:
    """BreadcrumbList from Home through `trail` [(name, absolute url), ...]; the last item is the page itself."""
    items = [("Home", site), *trail]
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i, "name": name, "item": url}
                                for i, (name, url) in enumerate(items, 1)]}


def law_section(*, name: str, label: str, url: str, official: str, chapter_name: str, chapter_url: str) -> dict:
    """A section of a Texas code: 'Penal Code § 46.06'."""
    return {"@context": "https://schema.org", "@type": "Legislation", "name": name, "legislationIdentifier": label,
            "legislationJurisdiction": TEXAS, "inLanguage": "en", "url": url, "sameAs": official,
            "isPartOf": {"@type": "Legislation", "name": chapter_name, "url": chapter_url}}


def law_chapter(*, name: str, label: str, url: str, official: str, sections: list[tuple[str, str]]) -> dict:
    """A chapter of a Texas code, with the sections the page lists as its parts [(name, url), ...]."""
    data = {"@context": "https://schema.org", "@type": "Legislation", "name": name, "legislationIdentifier": label,
            "legislationJurisdiction": TEXAS, "inLanguage": "en", "url": url, "sameAs": official}
    if sections:
        data["hasPart"] = [{"@type": "Legislation", "name": n, "url": u} for n, u in sections]
    return data


def member_profile(*, name: str, url: str, house: bool, district: str, party: str | None,
                   same_as: list[str]) -> dict:
    """ProfilePage about a legislator. party only when the page states it as recorded (not an unofficial ballot)."""
    person = {"@type": "Person", "name": name,
              "jobTitle": "State Representative" if house else "State Senator",
              "memberOf": {"@type": "GovernmentOrganization",
                           "name": "Texas House of Representatives" if house else "Texas Senate"}}
    if district:
        person["workLocation"] = {"@type": "AdministrativeArea",
                                  "name": f"Texas {'House' if house else 'Senate'} District {district}"}
    if party:
        person["affiliation"] = {"@type": "Organization", "name": party}
    if same_as:
        person["sameAs"] = same_as
    return {"@context": "https://schema.org", "@type": "ProfilePage", "url": url, "mainEntity": person}


def collection(*, name: str, url: str, description: str, about: dict | None = None,
               items: list[str] = ()) -> dict:
    """CollectionPage for a topic or agency list; items are the bill pages it lists."""
    data = {"@context": "https://schema.org", "@type": "CollectionPage", "name": name, "url": url,
            "description": description, "inLanguage": "en"}
    if about:
        data["about"] = about
    if items:
        data["mainEntity"] = {"@type": "ItemList", "numberOfItems": len(items),
                              "itemListElement": [{"@type": "ListItem", "position": i, "url": u}
                                                  for i, u in enumerate(items, 1)]}
    return data


def website(site: str) -> dict:
    """The home page's WebSite, with the explorer's text search as its SearchAction."""
    return {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": site, "inLanguage": "en",
            "potentialAction": {"@type": "SearchAction",
                                "target": {"@type": "EntryPoint", "urlTemplate": f"{site}explorer?query={{search_term_string}}"},
                                "query-input": "required name=search_term_string"}}
