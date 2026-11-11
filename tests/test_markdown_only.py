"""Only the official Markdown is reviewed, and only reviews of the exact Markdown the site serves are published.
End to end through review_pipeline.py with only the OpenAI SDK faked. No network, no paid calls."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_topic_suggestions import SuggestionCase, pipeline  # noqa: E402
from test_review_stages_pipeline import md_i  # noqa: E402

import classify_bill  # noqa: E402
import extract_bill  # noqa: E402


class LiveMarkdownTests(SuggestionCase):
    def published(self):
        return json.loads(self.tags_path().read_text('utf-8'))['bills']

    def tags_path(self):
        return self.live / 'luna' / 'tags.json'

    def publish_only(self):
        # A later run that reviews nothing (so the changed text is not re-reviewed) and only publishes.
        with patch.object(pipeline, 'queue_candidates', lambda *a, **k: []), \
                patch.object(pipeline, 'suggest_topics', lambda *a, **k: 0):
            return self.run_once()

    def test_a_review_whose_live_text_changed_is_withheld_from_every_output(self):
        self.seed(['HB1', 'HB2'])
        self.run_once()
        luna = self.live / 'luna'
        self.assertEqual(sorted(self.published()), ['HB1', 'HB2'])
        self.assertTrue((luna / 'highlights' / 'HB1.json').exists())
        self.assertIn('HB1', json.loads((luna / 'extras.json').read_text('utf-8'))['bills'])
        self.put('HB1', 'I', md_i('HB1') + '\nA paragraph the live text now has.\n')
        out = self.publish_only()
        self.assertIn('Withheld 1 reviews whose text is not the live Markdown, e.g. HB1', out)
        self.assertEqual(sorted(self.published()), ['HB2'])
        self.assertFalse((luna / 'highlights' / 'HB1.json').exists())  # the stale file is removed
        self.assertTrue((luna / 'highlights' / 'HB2.json').exists())
        self.assertNotIn('HB1', json.loads((luna / 'extras.json').read_text('utf-8'))['bills'])

    def test_a_review_not_read_from_markdown_is_never_published(self):
        self.seed(['HB1', 'HB2'])
        self.run_once()
        review = self.cache / 'reviews' / 'HB2.json'
        bundle = json.loads(review.read_text('utf-8'))
        bundle['document']['input_format'] = 'pdf'
        review.write_text(json.dumps(bundle), 'utf-8')
        self.publish_only()
        self.assertEqual(sorted(self.published()), ['HB1'])

    def test_an_index_that_disagrees_with_the_served_file_withholds_the_review(self):
        self.seed()
        self.run_once()
        index = self.text / 'HB1' / 'index.json'
        data = json.loads(index.read_text('utf-8'))
        data['versions'][0]['sha256'] = '0' * 64
        index.write_text(json.dumps(data), 'utf-8')
        self.publish_only()
        self.assertEqual(self.published(), {})

    def test_a_review_of_an_older_version_still_served_stays_published(self):
        self.seed()
        self.run_once()
        self.put('HB1', 'H', md_i('HB1') + '\nHouse committee text.\n')
        self.publish_only()
        self.assertEqual(sorted(self.published()), ['HB1'])

    def test_a_text_dir_other_than_the_served_one_is_refused(self):
        self.seed()
        other = self.live.parent / 'elsewhere'
        other.mkdir()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            self.run_once('--text-dir', str(other))
        self.assertEqual(stop.exception.code, 2)
        self.assertEqual(self.sdk.requests, [])


class PdfRetiredTests(SuggestionCase):
    def test_the_pdf_path_stops_the_run_before_any_connection_or_call(self):
        self.seed()
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--snapshot', str(self.snap), '--execute',
                '--transport', 'flex', '--input', 'pdf']
        make = lambda cache_dir, daily, run: pipeline_boundary(self, cache_dir, daily, run)
        out = io.StringIO()
        with patch.object(sys, 'argv', argv), patch.object(pipeline.ftplib, 'FTP', side_effect=AssertionError('FTP')), \
                patch('flex_boundary.FlexBoundary', side_effect=make), contextlib.redirect_stdout(out), \
                self.assertRaises(SystemExit) as stop:
            pipeline.main()
        self.assertEqual(stop.exception.code, 2)
        self.assertIn('stopped MarkdownOnly', out.getvalue())
        self.assertEqual(self.sdk.requests, [])
        queue = self.cache / 'queue.json'
        self.assertTrue(not queue.exists() or json.loads(queue.read_text('utf-8')).get('failed') in ({}, None))

    def test_the_manual_pdf_tools_refuse_a_paid_call(self):
        for module in (classify_bill, extract_bill):
            argv = [module.__name__, '--pdf', 'x.pdf', '--bill-id', 'HB1', '--version', 'introduced',
                    '--source-url', 'ftp://ftp.legis.state.tx.us/bills/x', '--execute']
            with patch.object(sys, 'argv', argv), contextlib.redirect_stderr(io.StringIO()) as err, \
                    self.assertRaises(SystemExit):
                module.main()
            self.assertIn('PDF reviews are retired', err.getvalue())


def pipeline_boundary(case, cache_dir, daily, run):
    import test_review_stages_pipeline as harness
    return harness.REAL_BOUNDARY(cache_dir, daily, run, openai_factory=lambda: case.sdk, sleep=lambda s: None,
                                 log=lambda t: None)


if __name__ == '__main__':
    unittest.main()
