import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from extraction_cache import (
    CacheBusy, CacheCoolingDown, CapacityUnavailable, NotSubmitted, ResponseCache, UnresolvedCall,
)


class ResponseCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bill-cache-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.cache = ResponseCache(self.directory)
        self.request = {"model": "test", "input": "full source", "reasoning": {"effort": "high"}}

    def test_persistent_replay_does_not_send(self):
        original = self.cache.execute(self.request, lambda: {"status": "completed", "output": "saved"})
        other = ResponseCache(self.directory)
        replay = other.execute(dict(reversed(list(self.request.items()))),
                               lambda: self.fail("Identical request must not be submitted"))
        self.assertFalse(original.cache_hit)
        self.assertTrue(replay.cache_hit)
        self.assertEqual(original.response, replay.response)

    def test_semantic_changes_have_distinct_keys(self):
        key = self.cache.key(self.request)
        for field, value in (("input", "changed source"), ("model", "other-model"),
                             ("reasoning", {"effort": "low"}), ("text", {"format": "changed schema"}),
                             ("instructions", "new vocabulary or instructions")):
            with self.subTest(field=field):
                self.assertNotEqual(key, self.cache.key({**self.request, field: value}))

    def test_timeout_blocks_duplicate_and_does_not_store_exception_contents(self):
        def uncertain():
            raise TimeoutError("SECRET must never be logged")
        with self.assertRaises(TimeoutError):
            self.cache.execute(self.request, uncertain)
        with self.assertRaises(UnresolvedCall):
            self.cache.execute(self.request, lambda: self.fail("Uncertain call must not be repeated"))
        self.assertNotIn("SECRET", (self.directory / (self.cache.key(self.request) + ".json")).read_text())

    def test_known_not_submitted_can_be_retried(self):
        def not_sent():
            raise NotSubmitted("No credential")
        with self.assertRaises(NotSubmitted):
            self.cache.execute(self.request, not_sent)
        self.assertFalse(self.cache.execute(self.request, lambda: {"status": "completed"}).cache_hit)

    def test_capacity_cooldown_prevents_an_immediate_request(self):
        def capacity():
            raise CapacityUnavailable(60)
        with self.assertRaises(CapacityUnavailable):
            self.cache.execute(self.request, capacity)
        with self.assertRaises(CacheCoolingDown):
            self.cache.execute(self.request, lambda: self.fail("Cooldown must suppress provider calls"))

    def test_capacity_expiry_allows_retry(self):
        def capacity():
            raise CapacityUnavailable(0)
        with self.assertRaises(CapacityUnavailable):
            self.cache.execute(self.request, capacity)
        self.cache.execute(self.request, lambda: {"status": "completed"})

    def test_crash_and_corruption_do_not_trigger_a_new_call(self):
        path = self.directory / (self.cache.key(self.request) + ".json")
        for contents in ("invalid JSON", json.dumps({"cache_format": 1,
                         "request_key": self.cache.key(self.request), "state": "pending"})):
            with self.subTest(contents=contents):
                path.write_text(contents, encoding="utf-8")
                with self.assertRaises(UnresolvedCall):
                    self.cache.execute(self.request, lambda: self.fail("Corrupt/pending entry must stop"))

    def test_returned_incomplete_or_invalid_response_is_replayed_for_validation(self):
        raw = {"status": "incomplete", "output": "not valid extraction JSON"}
        self.cache.execute(self.request, lambda: raw)
        self.assertEqual(self.cache.execute(self.request, lambda: self.fail("Do not pay twice")).response, raw)

    def test_os_lock_blocks_other_process_then_replays_its_response(self):
        ready, release = self.directory / "ready", self.directory / "release"
        child = """
import json,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from extraction_cache import ResponseCache
root=Path(sys.argv[2])
def send():
    (root/'ready').write_text('ready')
    deadline=time.monotonic()+10
    while not (root/'release').exists():
        if time.monotonic()>deadline: raise TimeoutError('test deadline')
        time.sleep(.02)
    return {'status':'completed','from':'child'}
ResponseCache(root).execute(json.loads(sys.argv[3]),send)
"""
        process = subprocess.Popen([sys.executable, "-c", child, str(SCRIPTS), str(self.directory),
                                    json.dumps(self.request)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists())
            with self.assertRaises(CacheBusy):
                self.cache.execute(self.request, lambda: self.fail("Duplicate process acquired the lock"))
        finally:
            release.write_text("release", encoding="utf-8")
            stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, (stdout, stderr))
        replay = self.cache.execute(self.request, lambda: self.fail("Child response must persist"))
        self.assertTrue(replay.cache_hit)
        self.assertEqual(replay.response["from"], "child")


if __name__ == "__main__":
    unittest.main()
