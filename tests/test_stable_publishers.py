"""Publishing unchanged content keeps the public file (and its ETag) untouched; a real change still rewrites it."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import review_audit
import review_pipeline
import topic_suggestions


def age(path: Path) -> None:
    # Push the mtime back so a rewrite would be visible even on coarse clocks.
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))


class SameButStamp(unittest.TestCase):
    def test_ignores_only_the_stamp(self):
        self.assertTrue(review_pipeline.same_but_stamp({"a": 1, "generated_at": "x"}, {"a": 1, "generated_at": "y"}))
        self.assertFalse(review_pipeline.same_but_stamp({"a": 1, "generated_at": "x"}, {"a": 2, "generated_at": "x"}))
        self.assertFalse(review_pipeline.same_but_stamp(None, {"a": 1}))


class PublishersKeepUnchangedFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        (self.cache / "reviews").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tags_unchanged_skips_write_and_change_log(self):
        out = self.root / "tags.json"
        registry = [{"id": "A1", "name": "Agency"}]
        review_pipeline.publish_tags(self.cache, out, registry)
        age(out)
        before = out.read_bytes()
        with mock.patch("luna_updates.record") as record:
            review_pipeline.publish_tags(self.cache, out, registry)
        self.assertEqual(out.stat().st_mtime_ns, 1_000_000_000)
        self.assertEqual(out.read_bytes(), before)
        record.assert_not_called()

    def test_tags_change_rewrites_and_logs(self):
        out = self.root / "tags.json"
        review_pipeline.publish_tags(self.cache, out, [{"id": "A1", "name": "Agency"}])
        age(out)
        with mock.patch("luna_updates.record") as record:
            review_pipeline.publish_tags(self.cache, out, [{"id": "A1", "name": "Renamed agency"}])
        self.assertNotEqual(out.stat().st_mtime_ns, 1_000_000_000)
        self.assertEqual(json.loads(out.read_text("utf-8"))["agencies"], {"A1": "Renamed agency"})
        record.assert_called_once()

    def test_extras_unchanged_keeps_file(self):
        out = self.root / "extras.json"
        topic_suggestions.publish_extras([], self.cache, out)
        age(out)
        topic_suggestions.publish_extras([], self.cache, out)
        self.assertEqual(out.stat().st_mtime_ns, 1_000_000_000)

    def test_audit_unchanged_keeps_file_and_change_rewrites(self):
        out = self.root / "audit.json"
        review_audit.publish([], self.cache, out)
        age(out)
        review_audit.publish([], self.cache, out)
        self.assertEqual(out.stat().st_mtime_ns, 1_000_000_000)
        data = json.loads(out.read_text("utf-8"))
        data["checked"] = 99
        out.write_text(json.dumps(data), "utf-8")
        age(out)
        review_audit.publish([], self.cache, out)
        self.assertEqual(json.loads(out.read_text("utf-8"))["checked"], 0)


if __name__ == "__main__":
    unittest.main()
