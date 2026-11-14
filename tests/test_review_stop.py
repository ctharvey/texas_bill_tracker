"""SIGTERM (systemctl stop, shutdown) stops the review worker gracefully: bills in flight finish and settle, nothing
new starts, no ledger row is left pending. Real main / FlexBoundary, fake SDK (test_flex_worker_loop's harness)."""
import signal
import unittest
from unittest.mock import patch

from test_flex_worker_loop import OK, FlexLoopCase, pipeline  # noqa: F401 - shared harness


class StopRequested(FlexLoopCase):
    def tearDown(self):
        pipeline.STOP_REQUESTED.clear()

    def stop_on_first_call(self):
        def handler(bill, n):
            pipeline.request_stop(signal.SIGTERM, None)  # what the signal handler does, mid-call
            return OK
        self.sdk.handler = handler

    def assert_settled(self, queue):
        self.assertNotIn('pending', [row['state'] for row in self.ledger_rows()])
        self.assertLessEqual(set(self.sdk.calls), set(queue['seen']))  # every bill that sent was recorded

    def test_a_stop_during_a_call_finishes_that_bill_and_starts_no_other(self):
        self.stop_on_first_call()
        queue = self.run_main()
        self.assertEqual(set(self.sdk.calls), {'HB1'})
        self.assertEqual(self.downloads, ['HB1'])
        self.assert_settled(queue)

    def test_with_several_workers_only_bills_already_in_flight_finish(self):
        self.stop_on_first_call()
        queue = self.run_main(None, '--workers', '3')
        self.assertLessEqual(len(set(self.sdk.calls)), 3)
        self.assertLess(len(self.downloads), len(self.ids))
        self.assert_settled(queue)

    def test_a_stopped_run_skips_later_passes_and_paid_publishing(self):
        self.stop_on_first_call()
        with patch.object(pipeline, 'suggest_topics') as topics, patch.object(pipeline, 'publish_luna') as publish:
            self.run_main(None, '--suggest-topics')
        topics.assert_not_called()
        self.assertEqual(publish.call_args.kwargs, {'network_ok': False})

    def test_the_handler_is_installed_for_the_run_and_restored_after(self):
        before, during = signal.getsignal(signal.SIGTERM), []
        self.sdk.handler = lambda bill, n: during.append(signal.getsignal(signal.SIGTERM)) or OK
        self.run_main()
        self.assertTrue(during)
        self.assertTrue(all(h is pipeline.request_stop for h in during))
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_a_stale_stop_from_an_earlier_run_does_not_stop_a_new_one(self):
        pipeline.STOP_REQUESTED.set()
        queue = self.run_main()
        self.assertEqual(set(self.sdk.calls), set(self.ids))
        self.assert_settled(queue)


if __name__ == '__main__':
    unittest.main()
