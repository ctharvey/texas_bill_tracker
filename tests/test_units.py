"""systemd units: every service reports failure, the review pull is bounded, the data unit fails after publishing."""
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
SERVICES = sorted(p for p in SCRIPTS.glob('texas-bill-*.service') if '@' not in p.name)


def directives(path: Path) -> list[tuple[str, str]]:
    text = path.read_text('utf-8').replace('\\\n', ' ')
    return [tuple(part.strip() for part in line.split('=', 1)) for line in text.splitlines()
            if '=' in line and not line.lstrip().startswith('#')]


class Units(unittest.TestCase):
    def test_services_found(self):
        self.assertGreaterEqual(len(SERVICES), 5, SERVICES)

    def test_every_service_alerts_on_failure(self):
        for path in SERVICES:
            with self.subTest(path.name):
                self.assertIn(('OnFailure', 'texas-bill-alert@%n.service'), directives(path))
        self.assertTrue((SCRIPTS / 'texas-bill-alert@.service').is_file())

    def test_alert_unit_does_not_alert_on_itself(self):
        self.assertNotIn('OnFailure', dict(directives(SCRIPTS / 'texas-bill-alert@.service')))

    def test_review_pull_is_bounded_and_fast_forward_only(self):
        pulls = [v for k, v in directives(SCRIPTS / 'texas-bill-review.service') if k == 'ExecStartPre' and 'git' in v]
        self.assertEqual(len(pulls), 1)
        self.assertTrue(pulls[0].startswith('/usr/bin/timeout '), pulls[0])
        self.assertIn('pull --ff-only', pulls[0])
        self.assertIn('GIT_TERMINAL_PROMPT=0', pulls[0])

    def test_data_unit_fails_on_secondary_stages_only_after_snapshot_and_feeds(self):
        starts = [v for k, v in directives(SCRIPTS / 'texas-bill-data.service') if k == 'ExecStart']
        self.assertEqual(len(starts), 3)
        self.assertIn('sync_ftp.py', starts[0])
        self.assertIn('--failures-file "$RUNTIME_DIRECTORY/failures"', starts[0])
        self.assertIn('build_feeds.py', starts[1])
        self.assertIn('-s "$RUNTIME_DIRECTORY/failures"', starts[2])
        self.assertIn('exit 1', starts[2])


if __name__ == '__main__':
    unittest.main()
