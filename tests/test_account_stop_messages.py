"""An account stop says what the provider refused (out of credits, spending limit, API key) and what to do, in the
stop line and in every backoff line after it, and never prints anything but a short provider code token."""
import contextlib
import io
import json
import unittest

from test_flex_worker_loop import Err, FlexLoopCase, pipeline  # noqa: F401 - shared harness
from extraction_cache import ApiStopped


class Messages(unittest.TestCase):
    def step(self, code):
        return pipeline.next_step(ApiStopped(code))

    def test_each_code_names_the_problem_and_the_code(self):
        for code, phrase in (("insufficient_quota", "OUT OF CREDITS"),
                             ("credit_balance_depleted", "OUT OF CREDITS"),
                             ("billing_hard_limit_reached", "SPENDING LIMIT REACHED"),
                             ("provider_quota_exhausted", "PROVIDER QUOTA USED UP"),
                             ("quota", "QUOTA OR BILLING REFUSED"),
                             ("invalid_api_key", "API KEY REFUSED"),
                             ("auth", "API KEY OR PERMISSIONS REFUSED"),
                             ("something_new", "ACCOUNT REFUSED")):
            with self.subTest(code):
                text = self.step(code)
                self.assertIn(phrase, text)
                self.assertIn("provider code " + code, text)
                self.assertIn("Nothing was billed", text)
                self.assertIn(pipeline.ACCOUNT_STOP, text)

    def test_text_that_is_not_a_code_token_is_never_printed(self):
        for unsafe in ("You exceeded your quota, see sk-abc", "UPPER", "", "x" * 80, None):
            with self.subTest(unsafe):
                self.assertIsNone(pipeline.account_code(unsafe))
        self.assertIn('ACCOUNT REFUSED', self.step("Has Spaces and a sk-secret"))
        self.assertNotIn("sk-secret", self.step("Has Spaces and a sk-secret"))


class OutOfCredits(FlexLoopCase):
    def run_capture(self):
        out = io.StringIO()
        code = None
        with contextlib.redirect_stdout(out):
            try:
                self.run_main()
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue()

    def test_the_stop_and_every_later_start_say_out_of_credits(self):
        self.sdk.handler = lambda bill, n: Err(429, 'insufficient_quota')
        code, out = self.run_capture()
        self.assertEqual(code, 2)
        self.assertIn('OUT OF CREDITS (provider code insufficient_quota); add credits to the OpenAI account', out)
        marker = json.loads((self.cache / pipeline.ACCOUNT_STOP).read_text('utf-8'))
        self.assertEqual((marker['reason'], marker['code']), ('ApiStopped', 'insufficient_quota'))
        self.assertNotIn('pending', [row['state'] for row in self.ledger_rows()])

        calls = len(self.sdk.calls)
        code, out = self.run_capture()
        self.assertIsNone(code)
        self.assertEqual(len(self.sdk.calls), calls)  # backing off: no call
        self.assertIn('stopped a run 0 minutes ago: OUT OF CREDITS (provider code insufficient_quota); add credits to '
                      'the OpenAI account. Not starting', out)

    def test_a_marker_written_before_codes_were_stored_still_reads(self):
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / pipeline.ACCOUNT_STOP).write_text(
            json.dumps({'stopped_at': pipeline.time.time(), 'reason': 'ApiStopped'}), 'utf-8')
        code, out = self.run_capture()
        self.assertIsNone(code)
        self.assertIn('stopped a run 0 minutes ago: ApiStopped.', out)
        self.assertEqual(self.sdk.calls, [])


if __name__ == '__main__':
    unittest.main()
