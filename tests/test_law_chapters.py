"""Follow-a-law phase 3 data: chapter changes in the statute index, chapter feeds and pages, heading search shards."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build_feeds  # noqa: E402
import sync_law  # noqa: E402
from test_law_context import BILL as HB1094, write_law  # noqa: E402
from test_statutes import write_bill  # noqa: E402

SB5 = """### SECTION 1.

Section 2271.002, Government Code, is amended to read as follows:

Sec. 2271.002. PROVISION REQUIRED IN CONTRACT. Other words.
"""


class ChapterIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.text, self.out = self.root / "text", self.root / "statutes"
        write_bill(self.text, "HB1094", [("I", "Introduced")], HB1094)

    def tearDown(self):
        self.tmp.cleanup()

    def index(self):
        return json.loads((self.out / "index.json").read_text("utf-8"))

    def test_whole_chapter_repeal_is_indexed_with_heading_and_first_seen_pair(self):
        law = write_law(self.root)
        build_feeds.write_statutes({"bills": [{"id": "HB1094"}]}, self.text, self.out, "2026-11-10", law)
        chapters = self.index()["chapters"]
        self.assertEqual(chapters["GV 2271"], {"h": "PROHIBITION ON CONTRACTS WITH COMPANIES BOYCOTTING ISRAEL",
                                               "b": [["HB1094", "r"]]})
        self.assertEqual(chapters["GV 2274"], {"h": "", "b": [["HB1094", "r"]]})  # not in the law copy
        self.assertEqual(chapters["GV 403"]["b"], [["HB1094", "m"]])  # Subchapter T only: an amendment
        self.assertEqual(build_feeds.CHAPTER_KEY.pattern, r"[A-Z]{2} \d+[A-Z]?")
        history = json.loads((self.out / "first-seen.json").read_text("utf-8"))
        self.assertEqual(history["pairs"]["GV 2271"], {"HB1094": None})

    def test_cited_chapters_and_other_keys_stay_out_and_sections_are_unchanged(self):
        build_feeds.write_statutes({"bills": [{"id": "HB1094"}]}, self.text, self.out, "2026-11-10")
        index = self.index()
        for cited in ("GV 808", "GV 809", "GV 2270", "GV 2275"):
            self.assertNotIn(cited, index["chapters"])
        self.assertTrue(all(build_feeds.CHAPTER_KEY.fullmatch(k) and k[:2] in build_feeds.CODE_NAME for k in index["chapters"]))
        self.assertEqual(sorted(index["sections"]), ["GV 2271.002", "GV 403.606"])
        self.assertEqual(index["sections"]["GV 403.606"], {"h": "CERTAIN PERSONS INELIGIBLE", "b": [["HB1094", "m"]]})
        sections, _ = build_feeds.build_statutes({"bills": [{"id": "HB1094"}]}, self.text)
        self.assertEqual(json.dumps(sections["sections"], sort_keys=True), json.dumps(index["sections"], sort_keys=True))

    def test_chapter_bills_sort_like_section_bills_and_a_later_bill_is_new(self):
        write_bill(self.text, "SB5", [("I", "Introduced")], "### SECTION 1.\n\nChapter 2271, Government Code, is repealed.\n")
        write_bill(self.text, "HB2", [("I", "Introduced")], "### SECTION 1.\n\nChapter 2271, Government Code, is repealed.\n")
        both = {"bills": [{"id": "HB1094"}, {"id": "SB5"}]}
        build_feeds.write_statutes(both, self.text, self.out, "2026-11-10")
        self.assertEqual(self.index()["chapters"]["GV 2271"]["b"], [["HB1094", "r"], ["SB5", "r"]])
        self.assertNotIn("f", self.index()["chapters"]["GV 2271"])  # all baseline
        build_feeds.write_statutes({"bills": [{"id": "HB1094"}, {"id": "SB5"}, {"id": "HB2"}]}, self.text, self.out, "2026-11-12")
        entry = self.index()["chapters"]["GV 2271"]
        self.assertEqual(entry["b"], [["HB2", "r"], ["HB1094", "r"], ["SB5", "r"]])
        self.assertEqual(entry["f"], {"HB2": "2026-11-12"})

    def test_history_keeps_chapter_pairs_when_a_later_run_finds_none(self):
        build_feeds.write_statutes({"bills": [{"id": "HB1094"}]}, self.text, self.out, "2026-11-10")
        shutil.rmtree(self.text / "HB1094")
        write_bill(self.text, "HB1094", [("I", "Introduced")],
                   "### SECTION 1.\n\nSection 403.606, Government Code, is amended to read as follows:\n\n"
                   "Sec. 403.606. CERTAIN PERSONS INELIGIBLE. Words.\n")
        build_feeds.write_statutes({"bills": [{"id": "HB1094"}]}, self.text, self.out, "2026-11-11")
        self.assertEqual(self.index()["chapters"], {})
        history = json.loads((self.out / "first-seen.json").read_text("utf-8"))
        self.assertEqual(history["pairs"]["GV 2271"], {"HB1094": None})
        shutil.rmtree(self.text / "HB1094")
        write_bill(self.text, "HB1094", [("I", "Introduced")], HB1094)
        build_feeds.write_statutes({"bills": [{"id": "HB1094"}]}, self.text, self.out, "2026-11-12")
        self.assertNotIn("f", self.index()["chapters"]["GV 2271"])  # the pair returns with its old day, not today

    def test_a_history_from_before_chapters_does_not_flood_and_chapter_keys_never_meet_section_keys(self):
        build_feeds.write_statutes({"bills": [{"id": "HB1094"}]}, self.text, self.out, "2026-11-10")
        old = json.loads((self.out / "first-seen.json").read_text("utf-8"))
        del old["chapters_from"]
        old["pairs"] = {k: v for k, v in old["pairs"].items() if "." in k}
        (self.out / "first-seen.json").write_text(json.dumps(old), "utf-8")
        build_feeds.write_statutes({"bills": [{"id": "HB1094"}]}, self.text, self.out, "2026-11-12")
        self.assertNotIn("f", self.index()["chapters"]["GV 2271"])
        self.assertEqual(json.loads((self.out / "first-seen.json").read_text("utf-8"))["chapters_from"], "2026-11-12")


SNAPSHOT = {"bills": [
    {"id": "HB1094", "caption": "Relating to contracts.", "actions": ["Filed"], "action_dates": ["2026-11-10"]},
    {"id": "SB12", "caption": "Relating to guns.", "actions": ["Filed"], "action_dates": ["2026-11-11"]}]}
INDEX = {"chapters": {"PE 46": {"h": "WEAPONS", "b": [["HB1094", "r"]], "f": {"HB1094": "2026-11-19"}},
                      "ED 12A": {"h": "", "b": [["HB1094", "n"]]}},
         "sections": {"PE 46.06": {"h": "UNLAWFUL SALE OF FIREARMS", "b": [["SB12", "m"]], "f": {"SB12": "2026-11-18"}},
                      "PE 12.01": {"h": "OTHER", "b": [["SB12", "m"]]}}}


class ChapterFeedAndPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.feeds, self.pages = self.root / "feeds" / "law", self.root / "share" / "law"

    def tearDown(self):
        self.tmp.cleanup()

    def test_feed_combines_whole_chapter_and_section_bills_and_is_emptied_never_removed(self):
        self.assertEqual(build_feeds.write_law_chapter_feeds(SNAPSHOT, INDEX, self.feeds), (3, 0))
        self.assertEqual(build_feeds.write_law_chapter_feeds(SNAPSHOT, INDEX, self.feeds), (0, 3))
        root = ET.fromstring((self.feeds / "PE-46.xml").read_text("utf-8"))
        self.assertEqual(root.findtext("channel/title"), "Penal Code chapter 46 (Weapons) · Texas Bill Atlas")
        self.assertEqual(root.findtext("channel/link"), "https://billatlas.org/#chapter?law=PE&ch=46")
        titles = [i.findtext("title") for i in root.findall("channel/item")]
        self.assertIn("HB1094: Now repeals the whole chapter", titles)
        self.assertIn("SB12: Now amends § 46.06", titles)
        self.assertEqual(len(titles), 4)  # two "Now" items and one action item per bill
        self.assertFalse((self.feeds / "PE-12.xml").read_text("utf-8").count("HB1094"))
        self.assertTrue((self.feeds / "ED-12A.xml").exists())
        self.assertEqual(sorted(p.name for p in self.feeds.iterdir()), ["ED-12A.xml", "PE-12.xml", "PE-46.xml"])
        # PE 46 loses everything: still there, empty.
        smaller = {"chapters": {}, "sections": {"PE 12.01": INDEX["sections"]["PE 12.01"]}}
        build_feeds.write_law_chapter_feeds(SNAPSHOT, smaller, self.feeds)
        self.assertEqual(ET.fromstring((self.feeds / "PE-46.xml").read_text("utf-8")).findall("channel/item"), [])
        self.assertEqual(ET.fromstring((self.feeds / "ED-12A.xml").read_text("utf-8")).findall("channel/item"), [])
        # An index with no chapters writes nothing.
        before = {p.name: p.read_text("utf-8") for p in self.feeds.iterdir()}
        self.assertEqual(build_feeds.write_law_chapter_feeds(SNAPSHOT, {"sections": {}}, self.feeds), (0, 0))
        self.assertEqual(before, {p.name: p.read_text("utf-8") for p in self.feeds.iterdir()})

    def test_section_feeds_and_chapter_feeds_do_not_touch_each_other(self):
        build_feeds.write_law_chapter_feeds(SNAPSHOT, INDEX, self.feeds)
        build_feeds.write_law_feeds(SNAPSHOT, INDEX, self.feeds)
        self.assertEqual(sorted(p.name for p in self.feeds.iterdir()),
                         ["ED-12A.xml", "PE-12.01.xml", "PE-12.xml", "PE-46.06.xml", "PE-46.xml"])
        build_feeds.write_law_chapter_feeds(SNAPSHOT, {"sections": {"PE 12.01": INDEX["sections"]["PE 12.01"]}}, self.feeds)
        self.assertTrue((self.feeds / "PE-46.06.xml").exists())

    def test_pages_are_app_addressed_skip_unchanged_and_remove_only_stale_chapter_pages(self):
        self.assertEqual(build_feeds.write_law_chapter_pages(INDEX, self.pages), (3, 0, 0))
        self.assertEqual(build_feeds.write_law_chapter_pages(INDEX, self.pages), (0, 3, 0))
        page = (self.pages / "PE" / "46.html").read_text("utf-8")
        self.assertIn("<title>Penal Code Chapter 46: Weapons · Texas Bill Atlas</title>", page)
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/PE/46">', page)
        self.assertIn("2 bills in the 90th Legislature would change something in this chapter", page)
        self.assertIn('<a href="https://billatlas.org/bill/HB1094">HB 1094</a> repeals the whole chapter', page)
        self.assertIn('href="https://billatlas.org/law/PE/46.06">§ 46.06</a>: UNLAWFUL SALE OF FIREARMS', page)
        self.assertIn('location.replace("https://billatlas.org/#chapter?law=PE&ch=46")', page)
        self.assertIn("Follow it", page)
        # A section page lives in the same folder; only the stale chapter page goes.
        build_feeds.write_law_pages(INDEX, self.pages)
        self.assertTrue((self.pages / "PE" / "46.06.html").exists())
        smaller = {"chapters": {}, "sections": {"PE 12.01": INDEX["sections"]["PE 12.01"]}}
        self.assertEqual(build_feeds.write_law_chapter_pages(smaller, self.pages), (0, 1, 2))  # PE 12 stays; PE 46, ED 12A go
        self.assertFalse((self.pages / "PE" / "46.html").exists())
        self.assertTrue((self.pages / "PE" / "46.06.html").exists())
        self.assertTrue((self.pages / "PE" / "12.01.html").exists())
        # The section pass never removes a chapter page either.
        build_feeds.write_law_pages(smaller, self.pages)
        self.assertTrue((self.pages / "PE" / "12.html").exists())
        self.assertEqual(build_feeds.write_law_chapter_pages({"sections": {}}, self.pages), (0, 0, 0))
        self.assertTrue((self.pages / "PE" / "12.html").exists())

    def test_chapter_pages_are_not_in_the_sitemap(self):
        locs = ET.fromstring(build_feeds.sitemap({"bills": []}, law_keys=list(INDEX["sections"]) + list(INDEX["chapters"]))
                             ).findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        urls = [e.text for e in locs]
        self.assertEqual(urls, ["https://billatlas.org/", "https://billatlas.org/law/PE/12.01",
                                "https://billatlas.org/law/PE/46.06"])

    def test_heading_comes_from_the_law_copy_when_the_index_has_none(self):
        law = write_law(self.root)
        index = {"sections": {"GV 403.606": {"h": "CERTAIN PERSONS INELIGIBLE", "b": [["HB1094", "m"]]}}}
        build_feeds.write_law_chapter_pages(index, self.pages, law_dir=law)
        self.assertIn("Government Code Chapter 403: Comptroller of Public Accounts",
                      (self.pages / "GV" / "403.html").read_text("utf-8"))
        build_feeds.write_law_chapter_feeds(SNAPSHOT, index, self.feeds, law_dir=law)
        self.assertIn("Government Code chapter 403 (Comptroller of Public Accounts)",
                      (self.feeds / "GV-403.xml").read_text("utf-8"))


def write_code_index(out: Path, code: str, chapters: dict) -> None:
    (out / code).mkdir(parents=True, exist_ok=True)
    entries = {c: {"heading": h, "file": f"{code}/{c}.md", "sections": [[s, t] for s, t in secs]}
               for c, (h, secs) in chapters.items()}
    (out / code / "index.json").write_text(json.dumps({"code": code, "chapters": entries}), "utf-8")


class SearchShardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        write_code_index(self.out, "PE", {"46": ("CHAPTER 46. WEAPONS", [
            ("46.02", "Sec. 46.02. UNLAWFUL CARRYING WEAPONS."), ("46.06", "Sec. 46.06. UNLAWFUL TRANSFER OF FIREARMS.")])})
        write_code_index(self.out, "CN", {"1": ("ARTICLE 1. BILL OF RIGHTS", [("1.01", "Sec. 1.01. WEAPONS RIGHTS.")])})

    def tearDown(self):
        self.tmp.cleanup()

    def shard(self, prefix):
        return json.loads((self.out / "search" / f"{prefix}.json").read_text("utf-8"))

    def test_tracked_codes_match_the_site_list(self):
        self.assertEqual(set(sync_law.SEARCH_CODES), set(build_feeds.CODE_ABBR.values()))
        self.assertEqual(len(sync_law.SEARCH_CODES), 27)

    def test_entry_is_in_each_word_prefix_shard_and_not_in_stop_word_shards(self):
        result = sync_law.write_search(self.out)
        for prefix in ("unl", "car", "wea"):
            self.assertIn(["PE 46.02", "UNLAWFUL CARRYING WEAPONS"], self.shard(prefix))
        self.assertIn(["PE 46", "WEAPONS"], self.shard("wea"))
        self.assertEqual(self.shard("tra"), [["PE 46.06", "UNLAWFUL TRANSFER OF FIREARMS"]])
        for stop in ("of", "the", "for"):
            self.assertFalse((self.out / "search" / f"{stop}.json").exists())
        self.assertEqual(sync_law.search_prefixes("Certain Other Persons OF the 2nd A"), {"per", "2nd"})
        index = json.loads((self.out / "search" / "index.json").read_text("utf-8"))
        self.assertEqual(index["format"], "texas-bill-law-search-v1")
        self.assertEqual(index["prefixes"], {p: len(self.shard(p)) for p in index["prefixes"]})
        self.assertEqual(index["prefixes"]["wea"], 2)  # the chapter and 46.02
        self.assertEqual(result["shards"], len(index["prefixes"]))
        self.assertEqual(sorted(p.name for p in (self.out / "search").glob("*.json") if p.name != "index.json"),
                         sorted(f"{p}.json" for p in index["prefixes"]))

    def test_untracked_codes_are_excluded(self):
        sync_law.write_search(self.out)
        everything = [e for p in (self.out / "search").glob("???.json") for e in json.loads(p.read_text("utf-8"))]
        self.assertTrue(everything and all(k.startswith("PE ") for k, _ in everything))
        self.assertFalse(any(k.startswith("CN") for k, _ in everything))

    def test_unchanged_shards_are_not_rewritten_and_a_vanished_prefix_is_removed(self):
        sync_law.write_search(self.out)
        stamp = (self.out / "search" / "index.json").read_text("utf-8")
        again = sync_law.write_search(self.out)
        self.assertEqual((again["written"], again["removed"]), (0, 0))
        self.assertEqual((self.out / "search" / "index.json").read_text("utf-8"), stamp)
        write_code_index(self.out, "PE", {"46": ("CHAPTER 46. WEAPONS", [("46.02", "Sec. 46.02. UNLAWFUL CARRYING WEAPONS.")])})
        result = sync_law.write_search(self.out)
        self.assertFalse((self.out / "search" / "tra.json").exists())
        self.assertGreaterEqual(result["removed"], 1)
        index = json.loads((self.out / "search" / "index.json").read_text("utf-8"))
        self.assertNotIn("tra", index["prefixes"])
        self.assertEqual(index["prefixes"]["wea"], 2)

    def test_nothing_published_changes_nothing(self):
        sync_law.write_search(self.out)
        for path in self.out.glob("*/index.json"):
            if path.parent.name != "search":
                path.unlink()
        self.assertEqual(sync_law.write_search(self.out)["entries"], 0)
        self.assertTrue((self.out / "search" / "wea.json").exists())


if __name__ == "__main__":
    unittest.main()
