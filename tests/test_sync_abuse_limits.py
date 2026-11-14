"""Limits that stop one visitor from closing sync for everyone."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import search_bills
import sync_service as svc


class DailyCreateBudget(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.store = svc.Store(Path(folder.name) / 'sync.db'); self.addCleanup(self.store.close)

    def test_new_links_stop_at_the_daily_budget_and_reopen_a_day_later(self):
        now = 1_800_000_000.0
        with mock.patch.object(svc, 'DAILY_CREATES', 3), mock.patch('sys.stderr'):
            for i in range(3):
                self.store.create({'watch': []}, now + i)
            with self.assertRaises(svc.Rejected) as refused:
                self.store.create({'watch': []}, now + 10)
            self.assertEqual(refused.exception.status, 503)
            self.assertIn('retry_after', refused.exception.extra)
            self.store.create({'watch': []}, now + 86400 + 3)  # the first three have aged out of the window

    def test_existing_links_keep_working_when_creation_is_closed(self):
        now = 1_800_000_000.0
        with mock.patch.object(svc, 'DAILY_CREATES', 1), mock.patch('sys.stderr'):
            key = self.store.create({'watch': ['HB1']}, now)
            with self.assertRaises(svc.Rejected):
                self.store.create({'watch': []}, now + 1)
            mode, data, version = self.store.lookup(key, now + 2)
            self.assertEqual((mode, data['watch']), ('edit', ['HB1']))
            self.assertEqual(self.store.update(key, version, {'watch': ['HB2']}, now + 3)[0], version + 1)


class SearchCost(unittest.TestCase):
    def test_more_than_eight_alternatives_is_refused_before_any_scan(self):
        allowed = ' OR '.join(f'word{i}' for i in range(search_bills.MAX_ALTERNATIVES))
        self.assertEqual(search_bills.parse_params(f'q={allowed}')['q'], allowed)
        with self.assertRaises(search_bills.BadQuery):
            search_bills.parse_params(f'q={allowed} OR one-more')

    def test_quoted_or_is_not_counted_as_an_alternative(self):
        quoted = '"' + ' OR '.join(f'w{i}' for i in range(12)) + '"'
        self.assertEqual(search_bills.parse_params('q=' + quoted)['q'], quoted)


if __name__ == '__main__':
    unittest.main()
