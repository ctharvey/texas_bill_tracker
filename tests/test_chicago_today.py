"""N10: without a tz database, chicago_today follows US Central daylight time instead of fixed UTC-6."""
import builtins
import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_feeds as bf

UTC = dt.timezone.utc
real_import = builtins.__import__


def no_zoneinfo(name, *args, **kwargs):
    if name == 'zoneinfo':
        raise ImportError('no tz database')
    return real_import(name, *args, **kwargs)


class ChicagoTodayFallback(unittest.TestCase):
    def fallback(self, when: dt.datetime) -> str:
        with mock.patch('builtins.__import__', no_zoneinfo):
            return bf.chicago_today(when)

    def test_the_cdt_hour_that_fixed_utc_minus_6_got_wrong(self):
        # 2026-07-01 05:30 UTC is 00:30 CDT on July 1 (fixed UTC-6 said June 30).
        self.assertEqual(self.fallback(dt.datetime(2026, 7, 1, 5, 30, tzinfo=UTC)), '2026-07-01')

    def test_matches_the_tz_database_around_both_changes_and_midnight(self):
        chicago = ZoneInfo('America/Chicago')
        start = dt.datetime(2026, 3, 7, 0, 0, tzinfo=UTC)
        moments = [start + dt.timedelta(minutes=30 * i) for i in range(4 * 48)]
        start = dt.datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
        moments += [start + dt.timedelta(minutes=30 * i) for i in range(6 * 48)]
        moments += [dt.datetime(2027, m, 15, h, tzinfo=UTC) for m in range(1, 13) for h in (4, 5, 6, 7)]
        for when in moments:
            with self.subTest(when=when.isoformat()):
                self.assertEqual(self.fallback(when), when.astimezone(chicago).date().isoformat())


if __name__ == '__main__':
    unittest.main()
