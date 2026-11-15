"""Idle wait: a timer start after a $0, unchanged run waits for new inputs, but never past IDLE_MAX_S, never on
unknown code, and never after a run that changed output, spent, or deferred work."""
from pathlib import Path
import argparse
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import review_pipeline as rp


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class IdleGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        live = root / "live"
        (live / "text" / "HB1").mkdir(parents=True)
        (live / "history" / "HB1").mkdir(parents=True)
        (live / "luna").mkdir()
        (live / "bills.json").write_text("{}", "utf-8")
        (live / "text" / "HB1" / "index.json").write_text("{}", "utf-8")
        (live / "history" / "HB1" / "documents.json").write_text("{}", "utf-8")
        (live / "luna" / "tags.json").write_text("{}", "utf-8")
        self.args = argparse.Namespace(cache_dir=root / "cache", snapshot=live / "bills.json", text_dir=None,
                                       history_dir=None, publish_tags=live / "luna" / "tags.json")
        self.args.cache_dir.mkdir()
        self.live = live
        self.head = mock.patch.object(rp, "git_head", return_value="abc123")
        self.head.start()

    def tearDown(self):
        self.head.stop()
        self.tmp.cleanup()

    def touch(self, path: Path, ns: int):
        os.utime(path, ns=(ns, ns))

    def marker(self, at, inputs=None):
        (self.args.cache_dir / rp.IDLE_MARKER).write_text(
            json.dumps({"at": at, "inputs": inputs or rp.inputs_signature(self.args)}), "utf-8")

    # inputs_signature

    def test_signature_moves_with_each_input(self):
        base = rp.inputs_signature(self.args)
        for path in (self.args.snapshot, self.live / "text" / "HB1" / "index.json",
                     self.live / "history" / "HB1" / "documents.json"):
            self.touch(path, 5_000_000_000)
            moved = rp.inputs_signature(self.args)
            self.assertNotEqual(moved, base, path)
            base = moved
        (self.live / "text" / "HB2").mkdir()
        (self.live / "text" / "HB2" / "index.json").write_text("{}", "utf-8")
        self.assertNotEqual(rp.inputs_signature(self.args), base)

    def test_signature_moves_with_code_and_account_stop(self):
        base = rp.inputs_signature(self.args)
        with mock.patch.object(rp, "git_head", return_value="def456"):
            self.assertNotEqual(rp.inputs_signature(self.args), base)
        (self.args.cache_dir / rp.ACCOUNT_STOP).parent.mkdir(parents=True, exist_ok=True)
        (self.args.cache_dir / rp.ACCOUNT_STOP).write_text("{}", "utf-8")
        self.assertNotEqual(rp.inputs_signature(self.args), base)

    def test_unknown_code_is_never_idle(self):
        with mock.patch.object(rp, "git_head", return_value=None):
            self.assertIsNone(rp.inputs_signature(self.args))

    def test_git_head_reads_this_checkout(self):
        self.head.stop()
        try:
            head = rp.git_head(rp.ROOT)
            if (rp.ROOT / ".git").is_dir():
                self.assertRegex(head or "", r"^[0-9a-f]{40}$")
        finally:
            self.head.start()

    def test_output_signature_ignores_status_only(self):
        luna = self.live / "luna"
        base = rp.output_signature(luna)
        (luna / "status.json").write_text("{}", "utf-8")
        self.assertEqual(rp.output_signature(luna), base)
        self.touch(luna / "tags.json", 7_000_000_000)
        self.assertNotEqual(rp.output_signature(luna), base)

    # wait_while_idle

    def test_no_marker_no_wait(self):
        clock = Clock()
        self.assertEqual(rp.wait_while_idle(self.args, clock=clock, sleep=clock.sleep), 0)

    def test_waits_until_marker_expires(self):
        clock = Clock()
        self.marker(clock.now - 60)
        waited = rp.wait_while_idle(self.args, clock=clock, sleep=clock.sleep)
        self.assertAlmostEqual(waited, rp.IDLE_MAX_S - 60)
        self.assertTrue(all(s <= rp.IDLE_POLL_S for s in clock.sleeps))

    def test_input_change_ends_wait(self):
        clock = Clock()
        self.marker(clock.now)

        def sleep(seconds):
            clock.sleep(seconds)
            if len(clock.sleeps) == 3:
                self.touch(self.args.snapshot, 9_000_000_000)

        waited = rp.wait_while_idle(self.args, clock=clock, sleep=sleep)
        self.assertEqual(waited, 3 * rp.IDLE_POLL_S)

    def test_marker_removed_ends_wait(self):
        clock = Clock()
        self.marker(clock.now)

        def sleep(seconds):
            clock.sleep(seconds)
            (self.args.cache_dir / rp.IDLE_MARKER).unlink()

        self.assertEqual(rp.wait_while_idle(self.args, clock=clock, sleep=sleep), rp.IDLE_POLL_S)

    def test_stale_or_mismatched_or_corrupt_marker_no_wait(self):
        clock = Clock()
        self.marker(clock.now - rp.IDLE_MAX_S - 1)
        self.assertEqual(rp.wait_while_idle(self.args, clock=clock, sleep=clock.sleep), 0)
        self.marker(clock.now, inputs="other")
        self.assertEqual(rp.wait_while_idle(self.args, clock=clock, sleep=clock.sleep), 0)
        (self.args.cache_dir / rp.IDLE_MARKER).write_text("not json", "utf-8")
        self.assertEqual(rp.wait_while_idle(self.args, clock=clock, sleep=clock.sleep), 0)
        self.marker(clock.now)
        with mock.patch.object(rp, "git_head", return_value=None):
            self.assertEqual(rp.wait_while_idle(self.args, clock=clock, sleep=clock.sleep), 0)

    def test_future_dated_marker_is_still_bounded(self):
        clock = Clock()
        self.marker(clock.now + 10 * 24 * 3600)
        # A marker's age bound is what limits a wait; a far-future time must not hold the service for days.
        waited = rp.wait_while_idle(self.args, clock=clock, sleep=clock.sleep)
        self.assertLessEqual(waited, rp.IDLE_MAX_S)

    def test_frozen_clock_still_ends(self):
        clock = Clock()
        self.marker(clock.now)
        calls = []
        rp.wait_while_idle(self.args, clock=clock, sleep=calls.append)  # time never advances
        self.assertLessEqual(len(calls), rp.IDLE_MAX_S // rp.IDLE_POLL_S + 2)

    def test_only_systemd_timer_runs_wait(self):
        argv = ['review_pipeline.py', '--cache-dir', str(self.args.cache_dir), '--snapshot', str(self.args.snapshot),
                '--publish-tags', str(self.args.publish_tags), '--execute']
        for env, bill, expected in (({}, [], 0), ({"INVOCATION_ID": "x"}, ['--bill-id', 'HB1'], 0),
                                    ({"INVOCATION_ID": "x"}, [], 1)):
            with mock.patch.object(sys, "argv", argv + bill), mock.patch.dict(os.environ, env, clear=False), \
                    mock.patch.object(rp, "wait_while_idle") as wait, \
                    mock.patch.object(rp, "ResponseCache", side_effect=RuntimeError("stop here")):
                if "INVOCATION_ID" not in env:
                    os.environ.pop("INVOCATION_ID", None)
                with self.assertRaises(RuntimeError):
                    rp.main()
                self.assertEqual(wait.call_count, expected, (env, bill))

    def test_stop_during_wait_ends_it_at_once(self):
        clock = Clock()
        self.marker(clock.now)

        def sleep(seconds):
            clock.sleep(1)
            rp.STOP_REQUESTED.set()

        try:
            self.assertEqual(rp.wait_while_idle(self.args, clock=clock, sleep=sleep), 1)
        finally:
            rp.STOP_REQUESTED.clear()

    def test_stop_during_wait_exits_zero_without_taking_the_lock(self):
        argv = ['review_pipeline.py', '--cache-dir', str(self.args.cache_dir), '--snapshot', str(self.args.snapshot),
                '--publish-tags', str(self.args.publish_tags), '--execute']
        with mock.patch.object(sys, "argv", argv), mock.patch.dict(os.environ, {"INVOCATION_ID": "x"}), \
                mock.patch.object(rp, "wait_while_idle", side_effect=lambda a: rp.STOP_REQUESTED.set()), \
                mock.patch.object(rp, "ResponseCache") as cache:
            try:
                self.assertEqual(rp.main(), 0)
            finally:
                rp.STOP_REQUESTED.clear()
        cache.assert_not_called()

    def test_operator_release_or_hold_clears_the_marker(self):
        import flex_boundary
        self.assertEqual(rp.IDLE_MARKER, "idle.json")  # the name flex_boundary removes
        for flag in ("--release", "--hold"):
            self.marker(1.0)
            with mock.patch.object(flex_boundary, "FlexBoundary") as boundary:
                boundary.return_value.release_held.return_value = "$0"
                boundary.return_value.hold_pending.return_value = 0.0
                boundary.return_value.pending_rows.return_value = []
                boundary.return_value.held.return_value = []
                flex_boundary.main(["--cache-dir", str(self.args.cache_dir), flag, "K"])
            self.assertFalse((self.args.cache_dir / rp.IDLE_MARKER).exists(), flag)

    # settle_idle_marker

    def test_settle_writes_only_for_idle_unchanged_runs(self):
        luna = self.live / "luna"
        inputs, before = rp.inputs_signature(self.args), rp.output_signature(luna)
        path = self.args.cache_dir / rp.IDLE_MARKER
        rp.settle_idle_marker(self.args, inputs, before, idle=True)
        self.assertEqual(json.loads(path.read_text("utf-8"))["inputs"], inputs)
        rp.settle_idle_marker(self.args, inputs, before, idle=False)
        self.assertFalse(path.exists())
        rp.settle_idle_marker(self.args, None, before, idle=True)
        self.assertFalse(path.exists())
        self.touch(luna / "tags.json", 8_000_000_000)
        rp.settle_idle_marker(self.args, inputs, before, idle=True)
        self.assertFalse(path.exists())

    def test_marker_keeps_run_start_inputs(self):
        # Data that lands during an idle run must wake the next start, not be folded into the marker.
        luna = self.live / "luna"
        inputs, before = rp.inputs_signature(self.args), rp.output_signature(luna)
        self.touch(self.args.snapshot, 6_000_000_000)
        rp.settle_idle_marker(self.args, inputs, before, idle=True)
        clock = Clock()
        with mock.patch.object(rp.time, "time", clock):
            rp.settle_idle_marker(self.args, inputs, before, idle=True)
        self.assertEqual(rp.wait_while_idle(self.args, clock=clock, sleep=clock.sleep), 0)


if __name__ == "__main__":
    unittest.main()
