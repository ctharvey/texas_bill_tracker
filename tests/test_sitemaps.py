"""Sitemap index and typed children (SEO chunk 7, phase 1): shape, lastmod sources, empty children, the URL limit."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_feeds as bf  # noqa: E402

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SITE = "https://billatlas.org/"
BILLS = {"bills": [{"id": "HB1", "last_action_date": "2026-11-10T09:00:00", "authors": ["Alders"]},
                   {"id": "HB2", "last_action_date": "2026-11-12", "authors": ["Alders"]},
                   {"id": "SB3", "last_action_date": "bad"}]}
MEMBER = {"chamber": "house", "code": "A4395", "full_name": "Daniel Alders"}
ROSTER = {"house|Alders": MEMBER}
INDEX = {"chapters": {"PE 46": {"h": "WEAPONS", "b": [["HB1", "r"]], "f": {"HB1": "2026-11-05"}}},
         "sections": {"PE 46.06": {"h": "X", "b": [["HB1", "m"]], "f": {"HB1": "2026-11-08"}},
                      "PE 12.01": {"h": "Y", "b": [["HB2", "m"]]}}}
PAGES = {"topics": [{"slug": "water", "name": "Water", "bills": ["HB1", "SB3"]}],
         "agencies": [{"id": "txdot", "name": "TxDOT", "bills": ["HB2"]}]}


def locs(rows):
    return dict(rows)


class Lastmod(unittest.TestCase):
    def test_bill_is_newest_of_last_action_and_review(self):
        self.assertEqual(bf.bill_lastmod({"last_action_date": "2026-11-10T09:00"}), "2026-11-10")
        self.assertEqual(bf.bill_lastmod({"last_action_date": "2026-11-10"}, {"reviewed_at": "2026-11-15T01:00:00Z"}), "2026-11-15")
        self.assertEqual(bf.bill_lastmod({"last_action_date": "2026-11-10"}, {"reviewed_at": "2026-11-01"}), "2026-11-10")
        self.assertIsNone(bf.bill_lastmod({"last_action_date": "soon"}, {"reviewed_at": "x"}))
        self.assertIsNone(bf.bill_lastmod({}))

    def test_section_is_newest_of_first_seen_days_and_copy_day(self):
        self.assertEqual(bf.section_lastmod({"f": {"A": "2026-11-08", "B": "2026-11-02"}}, "PE", {}), "2026-11-08")
        self.assertEqual(bf.section_lastmod({"f": {"A": "2026-11-08"}}, "PE", {"PE": "2026-11-20"}), "2026-11-20")
        self.assertEqual(bf.section_lastmod({}, "PE", {"PE": "2026-11-20"}), "2026-11-20")
        self.assertIsNone(bf.section_lastmod({}, "PE", {}))
        self.assertIsNone(bf.section_lastmod(None, "PE", {}))

    def test_chapter_is_newest_over_itself_its_sections_and_the_copy(self):
        g = bf.chapter_groups(INDEX)["PE 46"]
        self.assertEqual(bf.chapter_lastmod(g, "PE", {}), "2026-11-08")
        self.assertEqual(bf.chapter_lastmod(g, "PE", {"PE": "2026-11-09"}), "2026-11-09")
        self.assertEqual(bf.chapter_lastmod({"since": {"X": "2026-11-12"}, "sections": {}}, "PE", {}), "2026-11-12")

    def test_copied_days_are_read_defensively(self):
        with tempfile.TemporaryDirectory() as tmp:
            law = Path(tmp)
            self.assertEqual(bf.law_copied_days(law), {})
            self.assertEqual(bf.law_copied_days(None), {})
            (law / "index.json").write_text("{", "utf-8")
            self.assertEqual(bf.law_copied_days(law), {})
            (law / "index.json").write_text(json.dumps({"codes": {"PE": {"copied_at": "2026-11-18T10:00:00+00:00"},
                                                                  "GV": {"copied_at": "never"}, "ED": 5}}), "utf-8")
            self.assertEqual(bf.law_copied_days(law), {"PE": "2026-11-18"})
            (law / "index.json").write_text("[]", "utf-8")
            self.assertEqual(bf.law_copied_days(law), {})

    def test_entries_by_type(self):
        reviews = {"HB1": {"reviewed_at": "2026-11-14T00:00:00Z"}}
        e = bf.sitemap_entries(BILLS, law_keys=list(INDEX["sections"]), members=[MEMBER, {"code": "x"}],
                               paths=["topic/water", "agency/txdot", "today", "about/method"], reviews=reviews,
                               index=INDEX, copied={"PE": "2026-11-01"}, roster=ROSTER, pages_data=PAGES)
        self.assertEqual(locs(e["bills"]), {SITE + "bill/HB1": "2026-11-14", SITE + "bill/HB2": "2026-11-12",
                                            SITE + "bill/SB3": None})
        self.assertEqual(locs(e["laws"]), {SITE + "law/PE/12.01": "2026-11-01", SITE + "law/PE/46.06": "2026-11-08",
                                           SITE + "law/PE/46": "2026-11-08", SITE + "law/PE/12": "2026-11-01"})
        self.assertEqual(locs(e["members"]), {SITE + "member/A4395/daniel-alders": "2026-11-14"})
        self.assertEqual(locs(e["groups"]), {SITE + "topic/water": "2026-11-14", SITE + "agency/txdot": "2026-11-12"})
        self.assertEqual(locs(e["pages"]), {SITE: "2026-11-14", SITE + "today": "2026-11-14", SITE + "about/method": None})
        for rows in e.values():
            self.assertEqual(rows, sorted(rows))

    def test_member_without_bills_or_roster_has_no_lastmod(self):
        self.assertEqual(bf.sitemap_entries(BILLS, members=[MEMBER])["members"], [(SITE + "member/A4395/daniel-alders", None)])
        self.assertEqual(bf.sitemap_entries({"bills": []}, members=[MEMBER], roster=ROSTER)["members"][0][1], None)


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "sitemap.xml"

    def tearDown(self):
        self.tmp.cleanup()

    def children(self):
        return sorted(p.name for p in (self.root / "sitemaps").iterdir()) if (self.root / "sitemaps").exists() else []

    def test_index_shape_and_child_lastmod(self):
        bf.write_sitemaps(self.path, BILLS, SITE, ["PE 46.06"], [MEMBER], ["topic/water"], index=INDEX, roster=ROSTER,
                          pages_data=PAGES)
        root = ET.fromstring(self.path.read_text("utf-8"))
        self.assertEqual(root.tag, "{%s}sitemapindex" % NS["s"])
        entries = {e.findtext("s:loc", namespaces=NS): e.findtext("s:lastmod", namespaces=NS) for e in root.findall("s:sitemap", NS)}
        self.assertEqual(entries, {SITE + "live/sitemaps/bills.xml": "2026-11-12", SITE + "live/sitemaps/groups.xml": "2026-11-10",
                                   SITE + "live/sitemaps/laws.xml": "2026-11-08", SITE + "live/sitemaps/members.xml": "2026-11-12",
                                   SITE + "live/sitemaps/pages.xml": "2026-11-12"})
        self.assertEqual(self.children(), ["bills.xml", "groups.xml", "laws.xml", "members.xml", "pages.xml"])
        child = ET.fromstring((self.root / "sitemaps" / "bills.xml").read_text("utf-8"))
        self.assertEqual(child.tag, "{%s}urlset" % NS["s"])
        self.assertEqual([u.findtext("s:loc", namespaces=NS) for u in child.findall("s:url", NS)],
                         [SITE + "bill/HB1", SITE + "bill/HB2", SITE + "bill/SB3"])
        self.assertEqual([u.findtext("s:lastmod", namespaces=NS) for u in child.findall("s:url", NS)],
                         ["2026-11-10", "2026-11-12", None])

    def test_index_omits_lastmod_when_a_child_has_none_and_lists_only_existing_children(self):
        bf.write_sitemaps(self.path, {"bills": [{"id": "HB1"}]}, SITE)
        root = ET.fromstring(self.path.read_text("utf-8"))
        entries = root.findall("s:sitemap", NS)
        self.assertEqual([e.findtext("s:loc", namespaces=NS) for e in entries],
                         [SITE + "live/sitemaps/bills.xml", SITE + "live/sitemaps/pages.xml"])
        self.assertEqual([e.find("s:lastmod", NS) for e in entries], [None, None])
        self.assertEqual(self.children(), ["bills.xml", "pages.xml"])

    def test_empty_child_is_not_written_and_a_stale_one_is_removed(self):
        folder = self.root / "sitemaps"
        folder.mkdir()
        (folder / "members.xml").write_text("old", "utf-8")
        (folder / "other.xml").write_text("keep", "utf-8")
        bf.write_sitemaps(self.path, BILLS, SITE)
        self.assertEqual(self.children(), ["bills.xml", "other.xml", "pages.xml"])
        self.assertNotIn("members.xml", self.path.read_text("utf-8"))

    def test_unchanged_run_rewrites_nothing(self):
        bf.write_sitemaps(self.path, BILLS, SITE)
        before = {p: p.stat().st_mtime_ns for p in [self.path, *(self.root / "sitemaps").iterdir()]}
        bf.write_sitemaps(self.path, BILLS, SITE)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})

    def test_a_child_over_the_url_limit_is_refused(self):
        rows = [(f"{SITE}bill/HB{i}", None) for i in range(bf.SITEMAP_MAX_URLS)]
        self.assertIn("</urlset>", bf.render_urlset(rows))
        with self.assertRaises(ValueError):
            bf.render_urlset(rows + [(SITE + "bill/HB0", None)])


if __name__ == "__main__":
    unittest.main()
