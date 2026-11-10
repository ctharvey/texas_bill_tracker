import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import classify_bill as classification
import extract_bill as detailed
import review_pipeline as pipeline
import sync_ftp

FIXTURE = ROOT / 'tests' / 'fixtures' / 'HB01001I.HTM'
TAGS = re.compile(r"</?(?:ins|del)>")
NOTE = (ROOT / 'scripts/markdown_input_note.txt').read_text('utf-8')

HAND = ("# H.B. No. 1 - Introduced\n\n### SECTION 1.\n\n"
        "Section 1.01, Water Code, is amended to read as follows: <del>The \\(old\\) board</del> "
        "<ins>The commission</ins> shall publish maps and <ins>shall</ins> report.\n\n"
        + ("<ins>Long inserted clause </ins>" + "plain words " * 80 + "\n\n")
        + "Trailing \\\\ paragraph.\n")


def fixture_markdown():
    html = sync_ftp._decode_html(FIXTURE.read_bytes())
    return sync_ftp.bill_text_markdown(html, "H.B. No. 1001", "Introduced")


class MarkdownDocumentTests(unittest.TestCase):
    def test_plain_projection_matches_pipeline(self):
        for markdown in (fixture_markdown(), HAND):
            self.assertEqual(detailed.plain_paragraphs(markdown), pipeline.plain_paragraphs(markdown))

    def check_document(self, markdown):
        doc = detailed.document_from_markdown("HB1001", "90R", "introduced", markdown)
        plain = pipeline.plain_paragraphs(markdown)
        self.assertEqual(doc["pages"], plain)
        self.assertEqual(doc["input_format"], "markdown")
        for span_id, span in doc["spans"].items():
            self.assertRegex(span_id, r"^P\d{3}S\d{3}$")
            self.assertEqual(span_id[1:4], f"{span['page']:03d}")
            self.assertEqual(plain[span["page"] - 1][span["start"]:span["end"]], span["text"])
            self.assertEqual(TAGS.sub("", span["marked"]), span["text"])
        return doc

    def test_fixture_document(self):
        doc = self.check_document(fixture_markdown())
        self.assertTrue(any("<ins>" in s["marked"] for s in doc["spans"].values()))

    def test_hand_document_escapes_split_and_tags(self):
        doc = self.check_document(HAND)
        marked = " ".join(s["marked"] for s in doc["spans"].values())
        self.assertIn("<del>The (old) board</del>", marked)
        self.assertIn("<ins>The commission</ins>", marked)
        self.assertIn("Trailing \\ paragraph.", marked)
        self.assertGreater(len([s for s in doc["spans"].values() if s["page"] == 4]), 1)

    def test_markup_only_change_changes_hash(self):
        a = detailed.document_from_markdown("HB1", "90R", "introduced", "# T\n\n<ins>word</ins> text\n")
        b = detailed.document_from_markdown("HB1", "90R", "introduced", "# T\n\nword text\n")
        self.assertEqual(a["pages"], b["pages"])
        self.assertNotEqual(a["text_hash"], b["text_hash"])

    def test_empty_document_rejected(self):
        for markdown in ("", "\n\n \n\n"):
            with self.assertRaises(ValueError):
                detailed.document_from_markdown("HB1", "90R", "introduced", markdown)

    def test_resolve_quote_with_and_without_tags(self):
        doc = detailed.document_from_markdown("HB1", "90R", "introduced", HAND)
        span_id = next(k for k, s in doc["spans"].items() if "commission" in s["text"])
        for quote in ("The commission shall publish maps", "<ins>The commission</ins> shall publish maps"):
            resolved = classification.resolve_quote(quote, span_id, doc)
            self.assertEqual(resolved["status"], "resolved")
            self.assertIn(span_id, resolved["parts"][0]["span_ids"])
        pdf = detailed.document_from_pages("HB1", "90R", "introduced", ["The <ins>x</ins> board"])
        self.assertEqual(classification.resolve_quote("The <ins>x</ins> board", "P001S001", pdf)["status"], "resolved")
        self.assertEqual(classification.resolve_quote("The x board", "P001S001", pdf)["status"], "not_found")

    def test_requests(self):
        registry = detailed.load_registry()
        md = detailed.document_from_markdown("HB1", "90R", "introduced", HAND)
        request = classification.build_request(md, registry)
        developer = request["input"][0]["content"][0]["text"]
        user = request["input"][1]["content"][0]["text"]
        self.assertIn(NOTE, developer)
        self.assertIn("<ins>The commission</ins>", user)
        pdf = detailed.document_from_pages("HB1", "90R", "introduced", ["The commission shall publish maps."])
        request = classification.build_request(pdf, registry)
        developer = request["input"][0]["content"][0]["text"]
        user = request["input"][1]["content"][0]["text"]
        self.assertNotIn(NOTE, developer)
        self.assertNotIn("<ins>", developer + user)
        self.assertIn("[P001S001; PDF page 1]\nThe commission shall publish maps.", user)
        self.assertNotIn("paragraph 1]", user)

    def write_text(self, root, sha=None, code="I"):
        folder = root / "HB1"
        folder.mkdir()
        data = HAND.encode("utf-8")
        (folder / (code + ".md")).write_bytes(data)
        (folder / "index.json").write_text(json.dumps({
            "format": "texas-bill-text-index-v1", "bill_id": "HB1",
            "versions": [{"code": code, "sha256": sha or hashlib.sha256(data).hexdigest()}]}), "utf-8")

    def test_load_markdown_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_text(root)
            doc = pipeline.load_markdown_document("HB1", root)
            self.assertEqual(doc["input_format"], "markdown")
            self.assertEqual(doc["version"], "introduced")

    def test_load_failures_are_download_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_text(root, sha="0" * 64)
            with self.assertRaises(pipeline.DOWNLOAD_ERRORS):
                pipeline.load_markdown_document("HB1", root)
            with self.assertRaises(pipeline.DOWNLOAD_ERRORS):
                pipeline.load_markdown_document("HB1", root, version="E")
            with self.assertRaises(pipeline.DOWNLOAD_ERRORS):
                pipeline.load_markdown_document("HB2", root)

    def test_cli_defaults(self):
        args = pipeline.build_parser().parse_args(["--cache-dir", "x"])
        self.assertEqual((args.input, args.text_dir, args.question_effort), ("pdf", None, "medium"))

    def test_question_effort(self):
        doc = detailed.document_from_pages("HB1", "90R", "introduced", ["The commission shall publish maps."])
        question = {"id": "q", "question": "?", "affected_claims": ["summary"], "span_ids": ["P001S001"]}
        result = {"summary": {"text": "x", "evidence": []}}
        self.assertEqual(pipeline.resolution_request(question, result, doc, [], "medium")["reasoning"],
                         {"effort": "medium"})
        self.assertEqual(pipeline.resolution_request(question, result, doc, [])["reasoning"], {"effort": "high"})
        first = classification.build_request(doc, detailed.load_registry())
        self.assertEqual(first["reasoning"], {"effort": "high"})


if __name__ == "__main__":
    unittest.main()
