from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build_feeds  # noqa: E402
from test_law_context import write_law  # noqa: E402

INDEX = {"sections": {
    "GV 2271.002": {"h": "PROVISION REQUIRED IN CONTRACT", "b": [["HB1094", "r"], ["SB12", "m"]]},
    "GV 403.606": {"h": "CERTAIN PERSONS INELIGIBLE", "b": [["HB1094", "m"]]},
    "GV 9999.001": {"h": "NEW <script>alert(1)</script> RULE", "b": [["HB7", "n"], ["../x", "n"]]},
    "../GV 1.1": {"h": "x", "b": [["HB1", "m"]]},
    "ZZ 1.1": {"h": "x", "b": [["HB1", "m"]]},
}}


class LawPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.law = write_law(self.root)
        self.out = self.root / "share" / "law"

    def tearDown(self):
        self.tmp.cleanup()

    def test_page_has_its_address_bills_and_current_law(self):
        build_feeds.write_law_pages(INDEX, self.out, law_dir=self.law)
        page = (self.out / "GV" / "403.606.html").read_text("utf-8")
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/GV/403.606">', page)
        self.assertIn("<title>Government Code §403.606: CERTAIN PERSONS INELIGIBLE · Texas Bill Atlas</title>", page)
        self.assertIn('content="https://billatlas.org/social-card.png"', page)
        self.assertIn('<a href="https://billatlas.org/bill/HB1094">HB 1094</a> amends this section', page)
        self.assertIn("<h2>Current law</h2>", page)
        self.assertIn("A person is not eligible to submit an application.", page)
        self.assertIn('href="https://billatlas.org/live/law/GV/403.md"', page)
        self.assertIn("artSec=403.606", page)
        self.assertNotIn("&artSec", page)  # The official link's ampersands are escaped.
        self.assertIn('location.replace("https://billatlas.org/#statute?law=GV&sec=403.606")', page)
        self.assertIn("can be missed", page)

    def test_long_section_is_clipped_with_a_link_to_the_chapter(self):
        build_feeds.write_law_pages(INDEX, self.out, law_dir=self.law)
        page = (self.out / "GV" / "2271.002.html").read_text("utf-8")
        self.assertIn("repeals this section", page)
        self.assertIn("The section continues", page)
        self.assertLess(page.count("More words."), 300)

    def test_new_section_has_no_current_law_and_everything_is_escaped(self):
        build_feeds.write_law_pages(INDEX, self.out, law_dir=self.law)
        page = (self.out / "GV" / "9999.001.html").read_text("utf-8")
        self.assertNotIn("<h2>Current law</h2>", page)
        self.assertNotIn("<script>alert", page)
        self.assertIn("adds this section", page)
        self.assertNotIn("../x", page)
        self.assertIn("1 bill in the 90th Legislature", page)

    def test_without_a_law_copy_pages_use_the_index_heading(self):
        build_feeds.write_law_pages(INDEX, self.out, law_dir=self.root / "missing")
        page = (self.out / "GV" / "403.606.html").read_text("utf-8")
        self.assertIn("Government Code §403.606: CERTAIN PERSONS INELIGIBLE", page)
        self.assertNotIn("<h2>Current law</h2>", page)

    def test_rewrites_only_changes_removes_stale_pages_and_ignores_bad_keys(self):
        self.assertEqual(build_feeds.write_law_pages(INDEX, self.out, law_dir=self.law), (3, 0, 0))
        self.assertEqual(build_feeds.write_law_pages(INDEX, self.out, law_dir=self.law), (0, 3, 0))
        self.assertEqual(sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()),
                         ["GV/2271.002.html", "GV/403.606.html", "GV/9999.001.html"])
        (self.out / "GV" / "notes.txt").write_text("keep", "utf-8")
        smaller = {"sections": {k: v for k, v in INDEX["sections"].items() if k != "GV 9999.001"}}
        self.assertEqual(build_feeds.write_law_pages(smaller, self.out, law_dir=self.law), (0, 2, 1))
        self.assertFalse((self.out / "GV" / "9999.001.html").exists())
        self.assertTrue((self.out / "GV" / "notes.txt").exists())
        self.assertEqual(build_feeds.write_law_pages({"sections": {}}, self.out, law_dir=self.law), (0, 0, 0))
        self.assertTrue((self.out / "GV" / "403.606.html").exists())  # An empty index never empties the folder.

    def test_code_of_criminal_procedure_reads_article(self):
        index = {"sections": {"CR 42.12": {"h": "COMMUNITY SUPERVISION", "b": [["SB3", "m"]]}}}
        build_feeds.write_law_pages(index, self.out)
        page = (self.out / "CR" / "42.12.html").read_text("utf-8")
        self.assertIn("Art. 42.12: COMMUNITY SUPERVISION", page)

    def test_page_links_its_feed(self):
        build_feeds.write_law_pages(INDEX, self.out, law_dir=self.law)
        page = (self.out / "GV" / "403.606.html").read_text("utf-8")
        self.assertIn('<link rel="alternate" type="application/rss+xml" title="Government Code §403.606" '
                      'href="https://billatlas.org/live/feeds/law/GV-403.606.xml">', page)

    def test_law_feeds_list_actions_and_keep_followed_links_working(self):
        snapshot = {"bills": [
            {"id": "HB1094", "caption": "Relating to contracts.", "actions": ["Filed", "Referred to State Affairs"],
             "action_dates": ["2026-11-10", "2026-11-12"]},
            {"id": "SB12", "caption": "Relating to boycotts.", "actions": ["Filed"], "action_dates": ["2026-11-11"]},
            {"id": "HB7", "caption": "Relating to rules.", "actions": []}]}
        feeds = self.root / "feeds" / "law"
        self.assertEqual(build_feeds.write_law_feeds(snapshot, INDEX, feeds), (3, 0))
        self.assertEqual(sorted(p.name for p in feeds.iterdir()), ["GV-2271.002.xml", "GV-403.606.xml", "GV-9999.001.xml"])
        root = ET.fromstring((feeds / "GV-2271.002.xml").read_text("utf-8"))
        self.assertEqual(root.findtext("channel/link"), "https://billatlas.org/law/GV/2271.002")
        self.assertIn("can be missed", root.findtext("channel/description"))
        self.assertIn("artSec=2271.002", root.findtext("channel/description"))
        captions = [i.findtext("description") for i in root.findall("channel/item")]
        self.assertTrue(captions and all(c.startswith(("HB 1094 repeals", "SB 12 amends")) for c in captions), captions)
        dates = [i.findtext("pubDate") for i in root.findall("channel/item")]
        self.assertEqual(len(dates), len(captions))
        self.assertEqual(build_feeds.write_law_feeds(snapshot, INDEX, feeds), (0, 3))
        # A section no bill changes any more keeps an empty feed, so a follower's link still works.
        smaller = {"sections": {"GV 403.606": INDEX["sections"]["GV 403.606"]}}
        build_feeds.write_law_feeds(snapshot, smaller, feeds)
        empty = ET.fromstring((feeds / "GV-9999.001.xml").read_text("utf-8"))
        self.assertEqual(empty.findall("channel/item"), [])
        self.assertEqual(empty.findtext("channel/link"), "https://billatlas.org/law/GV/9999.001")
        # An empty index writes nothing.
        before = {p.name: p.read_text("utf-8") for p in feeds.iterdir()}
        self.assertEqual(build_feeds.write_law_feeds(snapshot, {"sections": {}}, feeds), (0, 0))
        self.assertEqual(before, {p.name: p.read_text("utf-8") for p in feeds.iterdir()})

    def test_sitemap_lists_law_addresses(self):
        text = build_feeds.sitemap({"bills": [{"id": "HB1"}]}, law_keys=list(INDEX["sections"]))
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [e.text for e in ET.fromstring(text).findall("s:url/s:loc", ns)]
        self.assertEqual(locs, ["https://billatlas.org/", "https://billatlas.org/bill/HB1",
                                "https://billatlas.org/law/GV/2271.002", "https://billatlas.org/law/GV/403.606",
                                "https://billatlas.org/law/GV/9999.001"])
        self.assertEqual(build_feeds.sitemap({"bills": []}), build_feeds.sitemap({"bills": []}, law_keys=[]))


if __name__ == "__main__":
    unittest.main()
