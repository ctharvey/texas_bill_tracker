"""Statute index: clause parsing (real 90R wording), section attribution, and the files written for the site."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_feeds as b  # noqa: E402


def clause(text):
    r = b.parse_clause(text)
    return r["kind"], r["code"], r["targets"], r["subsections"]


class ParseClauseTests(unittest.TestCase):
    def test_whole_section_amendment(self):
        self.assertEqual(clause("Section 526.0056, Government Code, is amended to read as follows:"),
                         ("amend", "GV", ["526.0056"], []))

    def test_subsection_lists(self):
        self.assertEqual(clause("Sections 101A.258(a), (a-1), and (b), Human Resources Code, are amended to read as follows:"),
                         ("amend", "HR", ["101A.258"], ["a", "a-1", "b"]))
        self.assertEqual(clause("Sections 1455.001(1-b) and (2), Insurance Code, are amended to read as follows:"),
                         ("amend", "IN", ["1455.001"], ["1-b", "2"]))
        self.assertEqual(clause("Subsection (b), Section 502.360, Transportation Code, is amended to read as follows:"),
                         ("amend", "TN", ["502.360"], ["b"]))

    def test_bare_subsection_inside_a_section_list(self):
        self.assertEqual(clause("Sections 123.001(b) and (c) and 126.001(b), Government Code, are repealed."),
                         ("repeal", "GV", ["123.001", "126.001"], ["b", "c", "b"]))

    def test_amending_and_adding_subsections(self):
        self.assertEqual(clause("Section 37.0832, Education Code, is amended by amending Subsection (a) and adding "
                                "Subsections (a-1) and (b-2) to read as follows:"),
                         ("amend", "ED", ["37.0832"], ["a", "a-1", "b-2"]))
        self.assertEqual(clause("Section 21.0031, Education Code, is amended by adding Subsection (c) to read as follows:"),
                         ("amend", "ED", ["21.0031"], ["c"]))

    def test_section_heading_is_the_section(self):
        self.assertEqual(clause("The heading to Section 372.053, Transportation Code, is amended to read as follows:"),
                         ("amend", "TN", ["372.053"], []))
        self.assertEqual(clause("The heading to Chapter 92A, Civil Practice and Remedies Code, is amended to read as follows:")[0],
                         "heading")
        self.assertEqual(clause("The heading to Subchapter B, Chapter 158, Tax Code, is amended to read as follows:")[0], "heading")

    def test_criminal_procedure_keys_to_the_article(self):
        self.assertEqual(clause("Section 1(c), Article 46.04, Code of Criminal Procedure, is amended to read as follows:"),
                         ("amend", "CR", ["46.04"], ["c"]))
        self.assertEqual(clause("Sections 4(a) and (b), Article 37.07, Code of Criminal Procedure, are amended to read as follows:")[:3],
                         ("amend", "CR", ["37.07"]))
        self.assertEqual(clause("Chapter 2, Code of Criminal Procedure, is amended by adding Article 2.33 to read as follows:"),
                         ("add", "CR", ["2.33"], []))

    def test_adding_sections_and_chapters(self):
        self.assertEqual(clause("Subchapter A, Chapter 21, Education Code, is amended by adding Section 21.0045 to read as follows:"),
                         ("add", "ED", ["21.0045"], []))
        self.assertEqual(clause("Section 12.061, Utilities Code, is added to read as follows:"), ("add", "UT", ["12.061"], []))
        chapter = b.parse_clause("Subtitle D, Title 2, Labor Code, is amended by adding Chapter 83 to read as follows: CHAPTER 83.")
        self.assertEqual((chapter["kind"], chapter["code"], chapter["from_body"]), ("add", "LA", True))
        amp = b.parse_clause("Subtitle A, Title 16, Business &amp; Commerce Code, is amended by adding Chapter 722".replace("&amp;", "&"))
        self.assertEqual((amp["kind"], amp["code"]), ("add", "BC"))

    def test_effective_date_and_transfers(self):
        self.assertEqual(clause("Section 2116.102, Government Code, as effective May 1, 2027, is amended to read as follows:"),
                         ("amend", "GV", ["2116.102"], []))
        moved = clause("Sections 466.201, 466.202, and 466.203, Government Code, are transferred to Subchapter B, Chapter 2001, "
                       "Occupations Code, redesignated as Sections 2001.0502, 2001.0503, and 2001.0504, Occupations Code")
        self.assertEqual(moved[:3], ("amend", "GV", ["466.201", "466.202", "466.203"]))

    def test_chapter_repeal_and_other_laws_are_not_sections(self):
        self.assertEqual(clause("Chapter 753, Government Code, is repealed.")[0], "chapter")
        self.assertEqual(clause("Section 1, Article 2688d, Vernon's Texas Civil Statutes, is amended to read as follows:")[0], "other_law")
        self.assertEqual(clause("The following temporary provision is added to the Texas Constitution:")[0], "other_law")
        self.assertEqual(clause("This Act takes effect September 1, 2027.")[0], "none")

    def test_markup_and_escapes_are_ignored(self):
        self.assertEqual(clause(r"Section 48.160, Education Code, is amended to read as follows:")[2], ["48.160"])
        self.assertEqual(clause(r"Section <ins>48.160</ins>, Education Code, is amended to read as follows:")[2], ["48.160"])


BILL = """# HB 9 - Introduced

AN ACT

### SECTION 1.

Sections 1.01 and 1.02, Election Code, are amended to read as follows:

Sec. 1.01. FIRST. Text <ins>new</ins> \\[<del>old</del>\\].

(a) More of 1.01.

Sec. 1.02. SECOND \\[<del>OLD NAME</del>\\]. Body of 1.02.

### SECTION 2.

Section 1.01(a), Election Code, is amended to read as follows:

(a) Again.

### SECTION 3.

Section 1.01, Election Code, is amended by adding Subsection (c) to read as follows:

(c) Added.

### SECTION 4.

Chapter 2, Code of Criminal Procedure, is amended by adding Articles 2.33 and 2.34 to read as follows:

Art. 2.33. NEW ARTICLE. Sec. 1. Not a new article.

Sec. 2. Still Article 2.33.

Art. 2.34. ANOTHER. Body.

### SECTION 5.

Subtitle D, Title 2, Labor Code, is amended by adding Chapter 83 to read as follows:

CHAPTER 83. TIME OFF

Sec. 83.001. DEFINITIONS. Words.

Sec. 83.002. LEAVE. More words.

### SECTION 6.

The following provisions of the Education Code are repealed:

(1) Section 29.153(b);

(2) Sections 29.154 and 29.155; and

(3) Section 11.01, Election Code.

### SECTION 7.

Something, Unknown Statute, is amended to read as follows:

### SECTION 8.

This Act takes effect September 1, 2027.
"""


class BillStatutesTests(unittest.TestCase):
    def setUp(self):
        self.sections, self.unparsed = b.bill_statutes(BILL)

    def test_keys(self):
        self.assertEqual(sorted(self.sections), ["CR 2.33", "CR 2.34", "ED 29.153", "ED 29.154", "ED 29.155",
                                                 "EL 1.01", "EL 1.02", "EL 11.01", "LA 83.001", "LA 83.002"])
        self.assertEqual(self.unparsed, 1)

    def test_multi_section_body_split_by_headers(self):
        self.assertEqual(self.sections["EL 1.02"]["paragraphs"], [r"Sec. 1.02. SECOND \[<del>OLD NAME</del>\]. Body of 1.02."])
        self.assertTrue(self.sections["EL 1.01"]["paragraphs"][0].startswith("Sec. 1.01. FIRST."))

    def test_clauses_on_one_section_merge(self):
        e = self.sections["EL 1.01"]
        self.assertEqual(e["kind"], "amend")
        self.assertEqual(e["paragraphs"][1:], ["(a) More of 1.01.", "(a) Again.", "(c) Added."])
        self.assertFalse(e["partial"])  # Section 1 quoted it whole.
        self.assertEqual(e["subsections"], ["a", "c"])

    def test_articles_do_not_split_on_inner_sections(self):
        self.assertEqual(len(self.sections["CR 2.33"]["paragraphs"]), 2)
        self.assertEqual(self.sections["CR 2.33"]["kind"], "add")

    def test_new_chapter_sections_come_from_the_body(self):
        self.assertEqual(self.sections["LA 83.001"]["kind"], "add")
        self.assertEqual(self.sections["LA 83.002"]["paragraphs"], ["Sec. 83.002. LEAVE. More words."])

    def test_repealer_list_with_another_code(self):
        self.assertEqual({k: self.sections[k]["kind"] for k in ("ED 29.153", "ED 29.155", "EL 11.01")},
                         {"ED 29.153": "repeal", "ED 29.155": "repeal", "EL 11.01": "repeal"})

    def test_partial_when_only_subsections_are_quoted(self):
        sections, _ = b.bill_statutes("### SECTION 1.\n\nSection 9.01(b), Penal Code, is amended to read as follows:\n\n(b) New.\n")
        self.assertTrue(sections["PE 9.01"]["partial"])
        self.assertEqual(sections["PE 9.01"]["subsections"], ["b"])

    def test_heading_is_the_proposed_wording(self):
        self.assertEqual(b.section_heading(self.sections["EL 1.02"]["paragraphs"]), "SECOND")
        self.assertEqual(b.section_heading(["(a) No heading here."]), "")


def write_bill(text_dir, bill_id, versions, body):
    d = text_dir / bill_id
    d.mkdir(parents=True)
    (d / "index.json").write_text(json.dumps({"format": "texas-bill-text-index-v1", "bill_id": bill_id,
                                              "versions": [{"code": c, "name": n} for c, n in versions]}), "utf-8")
    (d / f"{versions[-1][0]}.md").write_text(body, "utf-8")


class WriteStatutesTests(unittest.TestCase):
    def test_files_index_and_updates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            text = root / "text"
            write_bill(text, "HB9", [("I", "Introduced"), ("E", "Engrossed")], BILL)
            write_bill(text, "SB2", [("I", "Introduced")],
                       "### SECTION 1.\n\nSection 1.01, Election Code, is amended to read as follows:\n\nSec. 1.01. FIRST. Other.\n")
            (text / "SB3").mkdir()  # A bill whose text is not posted yet.
            snapshot = {"bills": [{"id": "HB9"}, {"id": "SB2"}, {"id": "SB3"}, {"id": "../etc"}]}
            out = root / "statutes"
            written, unchanged, removed = b.write_statutes(snapshot, text, out)
            self.assertEqual((written, unchanged, removed), (10, 0, 0))
            index = json.loads((out / "index.json").read_text("utf-8"))
            self.assertEqual(index["format"], "texas-bill-statutes-v1")
            self.assertEqual(index["sections"]["EL 1.01"], {"h": "FIRST", "b": [["HB9", "m"], ["SB2", "m"]]})
            self.assertEqual(index["sections"]["LA 83.001"]["b"], [["HB9", "n"]])
            self.assertEqual(index["sections"]["ED 29.154"]["b"], [["HB9", "r"]])
            self.assertEqual(index["bills"]["HB9"], {"v": "E", "n": 10, "u": 1})
            self.assertNotIn("SB3", index["bills"])
            self.assertEqual(index["codes"]["CR"], "Code of Criminal Procedure")
            doc = json.loads((out / "sections" / "EL-1.01.json").read_text("utf-8"))
            self.assertEqual(doc["format"], "texas-bill-statute-section-v1")
            self.assertEqual([(e["bill"], e["version"], e["version_name"]) for e in doc["entries"]],
                             [("HB9", "E", "Engrossed"), ("SB2", "I", "Introduced")])
            self.assertEqual(b.write_statutes(snapshot, text, out), (0, 10, 0))
            (out / "sections" / "notes.txt").write_text("keep", "utf-8")
            # HB9 left: its nine sections go, and EL 1.01 is rewritten with SB2 alone; other files are left alone.
            self.assertEqual(b.write_statutes({"bills": [{"id": "SB2"}]}, text, out), (1, 0, 9))
            self.assertEqual(sorted(p.name for p in (out / "sections").iterdir()), ["EL-1.01.json", "notes.txt"])

    def test_unsafe_version_codes_and_missing_text(self):
        with tempfile.TemporaryDirectory() as temp:
            text = Path(temp) / "text"
            d = text / "HB1"
            d.mkdir(parents=True)
            (d / "index.json").write_text(json.dumps({"bill_id": "HB1", "versions": [{"code": "../../x"}]}), "utf-8")
            index, files = b.build_statutes({"bills": [{"id": "HB1"}]}, text)
            self.assertEqual((index["bills"], files), ({}, {}))
            self.assertEqual(b.write_statutes({"bills": []}, Path(temp) / "missing", Path(temp) / "out"), (0, 0, 0))
            self.assertFalse((Path(temp) / "out").exists())

    def test_keys_never_become_unsafe_file_names(self):
        sections, _ = b.bill_statutes("### SECTION 1.\n\nSection 1.01/../x, Penal Code, is amended to read as follows:\n\nx\n")
        self.assertTrue(all(b.STATUTE_KEY.fullmatch(k) for k in sections))
        long_number, _ = b.bill_statutes("### SECTION 1.\n\nSection 12345678.123456789, Penal Code, is amended to read as follows:\n\nx\n")
        self.assertEqual(long_number, {})

    def test_a_header_for_another_section_stays_with_the_named_one(self):
        sections, _ = b.bill_statutes("### SECTION 1.\n\nSection 1.01, Election Code, is amended to read as follows:\n\n"
                                      "Sec. 1.01. X. Text.\n\nSec. 2.02. Quoted inside 1.01.\n")
        self.assertEqual(list(sections), ["EL 1.01"])
        self.assertEqual(len(sections["EL 1.01"]["paragraphs"]), 2)

    def test_a_version_code_cannot_point_outside_the_bill(self):
        with tempfile.TemporaryDirectory() as temp:
            text = Path(temp) / "text"
            (text / "HB1").mkdir(parents=True)
            (text / "HB1" / "index.json").write_text(json.dumps({"bill_id": "HB1", "versions": [{"code": "../../x"}]}), "utf-8")
            # The file that path would reach exists and would parse; it must still not be read.
            (Path(temp) / "x.md").write_text("### SECTION 1.\n\nSection 1.01, Penal Code, is amended to read as follows:\n\nx\n", "utf-8")
            index, files = b.build_statutes({"bills": [{"id": "HB1"}]}, text)
            self.assertEqual((index["bills"], files), ({}, {}))


if __name__ == "__main__":
    unittest.main()
