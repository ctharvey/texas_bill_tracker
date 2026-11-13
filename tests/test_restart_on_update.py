"""--restart-on-update: newer upstream code stops new bills; in-flight bills finish; the run exits cleanly."""
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import test_review_worker_loop as loop
from test_review_worker_loop import bundle, pipeline

HEAD, NEWER, OTHER = 'a' * 40, 'b' * 40, 'c' * 40


class FakeGit:
    def __init__(self, upstream=NEWER, ancestor=True, fetch_ok=True, missing=False):
        self.upstream, self.ancestor, self.fetch_ok, self.missing, self.calls = upstream, ancestor, fetch_ok, missing, []

    def __call__(self, argv, **kwargs):
        if self.missing:
            raise FileNotFoundError('git')
        args = argv[3:]
        self.calls.append(args[0])
        done = lambda code, out='': subprocess.CompletedProcess(argv, code, out, '')
        if args == ['rev-parse', 'HEAD']:
            return done(0, HEAD + '\n')
        if args[0] == 'fetch':
            return done(0 if self.fetch_ok else 128)
        if args == ['rev-parse', '@{u}']:
            return done(0, self.upstream + '\n')
        if args[0] == 'merge-base':
            return done(0 if self.ancestor else 1)
        raise AssertionError(args)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class CodeUpdateTests(unittest.TestCase):
    def check(self, git, advance=301):
        clock = Clock()
        update = pipeline.CodeUpdate(Path('.'), interval=300, run=git, clock=clock)
        clock.now += advance
        return update.available()

    def test_newer_fast_forward_code_is_an_update(self):
        self.assertEqual(self.check(FakeGit()), NEWER[:7])

    def test_no_check_until_the_interval_passes(self):
        git = FakeGit()
        self.assertIsNone(self.check(git, advance=10))
        self.assertNotIn('fetch', git.calls)

    def test_same_diverged_or_unreachable_code_is_not_an_update(self):
        for git in (FakeGit(upstream=HEAD), FakeGit(upstream=OTHER, ancestor=False), FakeGit(fetch_ok=False),
                    FakeGit(missing=True)):
            self.assertIsNone(self.check(git))

    def test_checks_again_only_after_another_interval(self):
        git, clock = FakeGit(upstream=HEAD), Clock()
        update = pipeline.CodeUpdate(Path('.'), interval=300, run=git, clock=clock)
        clock.now += 301
        update.available(); update.available()
        self.assertEqual(git.calls.count('fetch'), 1)
        clock.now += 301
        update.available()
        self.assertEqual(git.calls.count('fetch'), 2)


class StopsAt:
    """A CodeUpdate whose `available` reports newer code from the n-th check on."""
    made = []

    def __init__(self, n):
        self.n, self.checks = n, 0

    def __call__(self, root):
        StopsAt.made.append(self)
        return self

    def available(self):
        self.checks += 1
        return 'bbbbbbb' if self.checks >= self.n else None


class RestartOnUpdateRunTests(unittest.TestCase):
    def setUp(self):
        # The worker-loop harness, used without inheriting (and re-running) its tests.
        self.harness = loop.WorkerLoopTests('run_main'); self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.ids, self.run_main = self.harness.ids, self.harness.run_main

    def run_until_update(self, n, *extra):
        out = []
        with patch.object(pipeline, 'CodeUpdate', StopsAt(n)), \
                patch.object(pipeline, 'suggest_topics', side_effect=AssertionError('second pass after an update')), \
                patch('builtins.print', side_effect=lambda *a, **k: out.append(' '.join(map(str, a)))):
            queue = self.run_main(lambda b, r: {'bill_id': b}, lambda doc, *a, **k: bundle(doc['bill_id']),
                                  '--restart-on-update', '--suggest-topics', *extra)
        return queue, out

    def test_serial_run_starts_no_bill_after_an_update_and_skips_later_passes(self):
        queue, out = self.run_until_update(3)
        self.assertEqual(queue['seen'], ['HB1', 'HB2'])
        self.assertTrue(any(line.startswith('Stopped: new code bbbbbbb') for line in out))

    def test_parallel_run_finishes_bills_in_flight_then_stops(self):
        queue, out = self.run_until_update(3, '--transport', 'flex', '--workers', '2')
        self.assertEqual(sorted(queue['seen']), ['HB1', 'HB2'])  # both were in flight when the update was seen
        self.assertFalse(any('not started' in line for line in out))

    def test_without_the_flag_nothing_is_fetched(self):
        with patch.object(pipeline, 'CodeUpdate', side_effect=AssertionError('checked without the flag')):
            queue = self.run_main(lambda b, r: {'bill_id': b}, lambda doc, *a, **k: bundle(doc['bill_id']))
        self.assertEqual(queue['seen'], self.ids)


if __name__ == '__main__':
    unittest.main()
