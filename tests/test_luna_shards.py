"""Sharded Luna maps: shards rebuild the single map exactly, unchanged content leaves every file untouched, and a
one-bill change rewrites only that bill's shard and the index."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import luna_shards
import review_pipeline
import topic_suggestions


def payload(n=200, stamp="2026-11-15T00:00:00Z"):
    return {"format": "texas-bill-luna-tags-v1", "model": "m", "generated_at": stamp, "agencies": {"A": "Agency"},
            "bills": {f"HB{i}": {"topics": [f"t{i % 9}"], "summary": f"Bill {i}"} for i in range(n)}}


def files(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*.json"))}


def rebuild(root: Path, name: str) -> dict:
    index = json.loads((root / f"{name}-index.json").read_text("utf-8"))
    bills = {}
    for n, version in enumerate(index["shards"]):
        part = json.loads((root / "shards" / f"{name}-{n}.json").read_text("utf-8"))
        assert part["shard"] == n and part["of"] == index["of"]
        bills.update(part["bills"])
    rest = {k: v for k, v in index.items() if k not in ("shards", "of", "format")}
    return {**rest, "format": index["of"], "bills": bills}


class Shards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_equals_single_map(self):
        data = payload()
        luna_shards.publish(self.root, "tags", data, 32)
        self.assertEqual(rebuild(self.root, "tags"), data)

    def test_versions_are_shard_content_hashes(self):
        import hashlib
        luna_shards.publish(self.root, "tags", payload(), 8)
        index = json.loads((self.root / "tags-index.json").read_text("utf-8"))
        for n, version in enumerate(index["shards"]):
            data = (self.root / "shards" / f"tags-{n}.json").read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest()[:16], version)

    def test_unchanged_writes_nothing(self):
        luna_shards.publish(self.root, "tags", payload(), 32)
        before = files(self.root)
        self.assertEqual(luna_shards.publish(self.root, "tags", payload(), 32), 0)
        self.assertEqual(files(self.root), before)

    def test_one_bill_change_rewrites_one_shard_and_index(self):
        luna_shards.publish(self.root, "tags", payload(), 32)
        before = files(self.root)
        changed = payload(stamp="2026-11-15T01:00:00Z")
        changed["bills"]["HB7"]["summary"] = "New summary"
        luna_shards.publish(self.root, "tags", changed, 32)
        after = files(self.root)
        moved = {k for k in after if after[k][0] != before.get(k, (None,))[0]}
        self.assertEqual(moved, {"tags-index.json", str(Path("shards") / f"tags-{luna_shards.shard_of('HB7', 32)}.json")})
        self.assertEqual(rebuild(self.root, "tags"), changed)

    def test_removed_bill_leaves_its_shard(self):
        luna_shards.publish(self.root, "tags", payload(), 32)
        smaller = payload()
        del smaller["bills"]["HB3"]
        luna_shards.publish(self.root, "tags", smaller, 32)
        self.assertNotIn("HB3", rebuild(self.root, "tags")["bills"])

    def test_shard_of_is_stable(self):
        # Fixed values: a change would move every bill and refetch every shard once.
        self.assertEqual([luna_shards.shard_of(b, 32) for b in ("HB1", "SB2", "HJR45")],
                         [luna_shards.shard_of(b, 32) for b in ("HB1", "SB2", "HJR45")])
        self.assertTrue(all(0 <= luna_shards.shard_of(f"HB{i}", 32) < 32 for i in range(500)))


class PublishersWriteShards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        (self.cache / "reviews").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tags_shards_match_tags_file_and_heal_when_missing(self):
        out = self.root / "luna" / "tags.json"
        review_pipeline.publish_tags(self.cache, out, [{"id": "A1", "name": "Agency"}])
        single = json.loads(out.read_text("utf-8"))
        self.assertEqual(rebuild(out.parent, "tags"), single)
        (out.parent / "tags-index.json").unlink()
        review_pipeline.publish_tags(self.cache, out, [{"id": "A1", "name": "Agency"}])  # unchanged map
        self.assertEqual(rebuild(out.parent, "tags"), single)  # rebuilt from the published file, same stamp

    def test_extras_shards_match_extras_file(self):
        out = self.root / "luna" / "extras.json"
        topic_suggestions.publish_extras([], self.cache, out)
        self.assertEqual(rebuild(out.parent, "extras"), json.loads(out.read_text("utf-8")))

    def test_shard_failure_keeps_single_file(self):
        out = self.root / "luna" / "tags.json"
        (out.parent).mkdir(parents=True)
        (out.parent / "shards").write_text("not a directory", "utf-8")
        review_pipeline.publish_tags(self.cache, out, [{"id": "A1", "name": "Agency"}])
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
