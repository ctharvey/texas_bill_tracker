"""Sharded Luna maps: shard files are named by their content and never rewritten, an index only names shards that
exist, an index an edge cache still serves keeps resolving to exactly its own map, and a failed publish withdraws
the index so the site reads the single file."""
from pathlib import Path
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import luna_shards
import review_pipeline
import topic_suggestions


def payload(n=200, stamp="2026-11-15T00:00:00Z"):
    return {"format": "texas-bill-luna-tags-v1", "model": "m", "generated_at": stamp, "agencies": {"A": "Agency"},
            "bills": {f"HB{i}": {"topics": [f"t{i % 9}"], "summary": f"Bill {i}"} for i in range(n)}}


def files(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*.json"))}


def resolve(root: Path, index: dict) -> dict:
    """What the site builds from an index (as loadShardedMap does)."""
    bills = {}
    for n, digest in enumerate(index["shards"]):
        data = (root / "shards" / f"tags-{digest}.json").read_bytes()
        assert hashlib.sha256(data).hexdigest()[:20] == digest
        part = json.loads(data)
        assert part["shard"] == n and part["of"] == index["of"]
        bills.update(part["bills"])
    rest = {k: v for k, v in index.items() if k not in ("shards", "of", "format")}
    return {**rest, "format": index["of"], "bills": bills}


def current(root: Path, name="tags") -> dict:
    return json.loads((root / f"{name}-index.json").read_text("utf-8"))


class Shards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_equals_single_map(self):
        data = payload()
        luna_shards.publish(self.root, "tags", data, 32)
        self.assertEqual(resolve(self.root, current(self.root)), data)

    def test_unchanged_writes_nothing(self):
        luna_shards.publish(self.root, "tags", payload(), 32)
        before = files(self.root)
        self.assertEqual(luna_shards.publish(self.root, "tags", payload(), 32), 0)
        self.assertEqual(files(self.root), before)

    def test_one_bill_change_adds_one_shard_and_rewrites_index(self):
        luna_shards.publish(self.root, "tags", payload(), 32)
        before = files(self.root)
        changed = payload(stamp="2026-11-15T01:00:00Z")
        changed["bills"]["HB7"]["summary"] = "New summary"
        luna_shards.publish(self.root, "tags", changed, 32)
        after = files(self.root)
        rewritten = {k for k in before if k in after and after[k] != before[k]}
        self.assertEqual(rewritten, {"tags-index.json"})  # no shard file is ever rewritten
        self.assertEqual(len(set(after) - set(before)), 1)
        self.assertEqual(resolve(self.root, current(self.root)), changed)

    def test_old_index_still_resolves_to_its_own_map(self):
        # Cloudflare can serve the previous index for minutes after a publish: it must still name its own bytes.
        first = payload()
        luna_shards.publish(self.root, "tags", first, 32)
        old_index = current(self.root)
        second = payload(stamp="2026-11-15T01:00:00Z")
        second["bills"]["HB7"]["summary"] = "New summary"
        del second["bills"]["HB3"]
        luna_shards.publish(self.root, "tags", second, 32)
        self.assertEqual(resolve(self.root, old_index), first)
        self.assertEqual(resolve(self.root, current(self.root)), second)

    def test_shard_count_change_keeps_both_indexes_exact(self):
        luna_shards.publish(self.root, "tags", payload(), 4)
        old_index = current(self.root)
        luna_shards.publish(self.root, "tags", payload(stamp="2026-11-15T02:00:00Z"), 2)
        self.assertEqual(resolve(self.root, old_index), payload())
        self.assertEqual(resolve(self.root, current(self.root)), payload(stamp="2026-11-15T02:00:00Z"))

    def test_prunes_only_unreferenced_shards_past_the_grace_period(self):
        clock = [1_000_000.0]
        now = lambda: clock[0]
        luna_shards.publish(self.root, "tags", payload(), 8, now=now)
        first = set(current(self.root)["shards"])
        two = payload(stamp="b"); two["bills"]["HB1"]["summary"] = "two"
        luna_shards.publish(self.root, "tags", two, 8, now=now)
        second = set(current(self.root)["shards"])
        three = payload(stamp="c"); three["bills"]["HB1"]["summary"] = "three"
        for path in (self.root / "shards").iterdir():
            os.utime(path, (clock[0] - luna_shards.PRUNE_AFTER_S - 10,) * 2)
        luna_shards.publish(self.root, "tags", three, 8, now=now)
        present = {p.name[len("tags-"):-len(".json")] for p in (self.root / "shards").iterdir()}
        # The previous index's shards stay (an edge may still serve it); the one before that is gone.
        self.assertTrue(second <= present)
        self.assertTrue(set(current(self.root)["shards"]) <= present)
        self.assertFalse((first - second) & present)

    def test_recent_unreferenced_shards_are_kept(self):
        luna_shards.publish(self.root, "tags", payload(), 8)
        first = set(current(self.root)["shards"])
        for stamp in ("b", "c"):
            p = payload(stamp=stamp); p["bills"]["HB1"]["summary"] = stamp
            luna_shards.publish(self.root, "tags", p, 8)
        present = {p.name[len("tags-"):-len(".json")] for p in (self.root / "shards").iterdir()}
        self.assertTrue(first <= present)

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_folder_and_files_are_world_readable_under_a_strict_umask(self):
        old = os.umask(0o077)
        try:
            luna_shards.publish(self.root, "tags", payload(), 4)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE((self.root / "shards").stat().st_mode), 0o755)
        for path in [self.root / "tags-index.json", *(self.root / "shards").iterdir()]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644, path)

    def test_existing_folder_mode_is_repaired(self):
        (self.root / "shards").mkdir()
        with mock.patch.object(luna_shards.os, "chmod") as chmod:
            luna_shards.publish(self.root, "tags", payload(), 4)
        self.assertIn(mock.call(self.root / "shards", 0o755), chmod.call_args_list)

    def test_shard_of_is_stable(self):
        # Pinned values: a change would move every bill to a new shard (one full refetch per visitor).
        self.assertEqual([luna_shards.shard_of(b, 32) for b in ("HB1", "SB2", "HJR45")],
                         [int.from_bytes(hashlib.sha256(b.encode()).digest()[:4], "big") % 32
                          for b in ("HB1", "SB2", "HJR45")])
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
        self.assertEqual(resolve(out.parent, current(out.parent)), single)
        (out.parent / "tags-index.json").unlink()
        review_pipeline.publish_tags(self.cache, out, [{"id": "A1", "name": "Agency"}])  # unchanged map
        self.assertEqual(resolve(out.parent, current(out.parent)), single)

    def test_extras_shards_match_extras_file(self):
        out = self.root / "luna" / "extras.json"
        topic_suggestions.publish_extras([], self.cache, out)
        index = current(out.parent, "extras")
        bills = {}
        for digest in index["shards"]:
            bills.update(json.loads((out.parent / "shards" / f"extras-{digest}.json").read_text("utf-8"))["bills"])
        self.assertEqual(bills, json.loads(out.read_text("utf-8"))["bills"])

    def test_failed_tags_shards_withdraw_the_index(self):
        # Old index + old shards agree with each other; left in place they would outrank the newer tags.json.
        out = self.root / "luna" / "tags.json"
        review_pipeline.publish_tags(self.cache, out, [{"id": "A1", "name": "Agency"}])
        self.assertTrue((out.parent / "tags-index.json").is_file())
        review_pipeline.RUN_TROUBLE.clear()
        with mock.patch("luna_shards.publish", side_effect=OSError("disk full")):
            review_pipeline.publish_tags(self.cache, out, [{"id": "A1", "name": "Renamed"}])
        self.assertEqual(json.loads(out.read_text("utf-8"))["agencies"], {"A1": "Renamed"})
        self.assertFalse((out.parent / "tags-index.json").exists())
        self.assertTrue(review_pipeline.RUN_TROUBLE.is_set())
        review_pipeline.RUN_TROUBLE.clear()

    def test_failed_extras_shards_withdraw_the_index_and_report(self):
        out = self.root / "luna" / "extras.json"
        topic_suggestions.publish_extras([], self.cache, out)
        with mock.patch("luna_shards.publish", side_effect=OSError("disk full")), self.assertRaises(OSError):
            topic_suggestions.publish_extras([], self.cache, out)
        self.assertFalse((out.parent / "extras-index.json").exists())
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
