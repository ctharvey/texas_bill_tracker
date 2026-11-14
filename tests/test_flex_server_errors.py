"""Provider 5xx at the flex boundary: a proven-unprocessed 5xx is resent like capacity, a maybe-processed one never.

No network and no paid calls (the fake SDK from test_flex_boundary)."""
import unittest

from test_flex_boundary import OK, BoundaryCase, Err, ec, fb  # noqa: F401 - shared fakes
import review_pipeline as rp


class ServerErrors(BoundaryCase):
    def test_a_brief_500_is_resent_and_the_bill_is_not_parked(self):
        b = self.boundary([Err(500, "server_error"), OK])
        result = self.run_once(b)
        self.assertFalse(result.cache_hit)
        self.assertEqual(len(self.sdk.calls), 2)
        self.assertEqual(self.sleeps, [30])
        self.assertEqual(self.entry()["state"], "returned")

    def test_a_bill_that_always_gets_500_still_parks_after_three_sends(self):
        for status in (500, 502, 503):
            with self.subTest(status):
                self.setUp()
                b = self.boundary([Err(status, "server_error")] * 3)
                with self.assertRaises(ec.ApiRejected) as caught:
                    self.run_once(b)
                self.assertIsInstance(caught.exception, rp.PER_BILL_ERRORS)  # parked as before, now after 3 sends
                self.assertEqual(len(self.sdk.calls), 3)
                self.assertEqual(self.sleeps, [30, 60])
                self.assertEqual(self.entry()["state"], "not_submitted")
                self.assertNotIn("pending", self.states())

    def test_a_maybe_processed_5xx_is_held_and_never_resent(self):
        for status in (504, 520):
            with self.subTest(status):
                self.setUp()
                b = self.boundary([Err(status, "server_error")])
                with self.assertRaises(Exception) as caught:
                    self.run_once(b)
                self.assertTrue(getattr(caught.exception, "held", False), type(caught.exception))
                self.assertEqual(len(self.sdk.calls), 1)
                self.assertEqual(self.sleeps, [])

    def test_a_503_asking_for_a_long_wait_defers_like_capacity(self):
        b = self.boundary([Err(503, "server_error", {"retry-after": "3600"})])
        with self.assertRaises(ec.CapacityUnavailable):
            self.run_once(b)
        self.assertEqual(len(self.sdk.calls), 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.entry()["state"], "capacity_wait")
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
