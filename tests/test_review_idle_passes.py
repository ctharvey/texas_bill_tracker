"""A later pass that leaves any work for a later run marks the run as not idle; only a pass that saved every job
it was given leaves the idle check open."""
from pathlib import Path
import argparse
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import review_pipeline as rp
from extraction_cache import CacheCoolingDown


def job(bill, outcome):
    saved = []

    def call():
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return (bill, call, saved.append)


class LaterPassesAndIdle(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(execute=True, cache_dir=Path("."))
        rp.RUN_TROUBLE.clear()

    def tearDown(self):
        rp.RUN_TROUBLE.clear()

    def second(self, jobs, deadline=float("inf")):
        return rp._second_pass("Topic suggestions", iter(jobs), self.args, deadline)

    def slot(self, jobs, deadline=float("inf")):
        units = [(bill, iter([(call, save)])) for bill, call, save in jobs]
        return rp._slot_pass("Topic suggestions", iter(units), self.args, deadline, 2)

    def test_all_saved_is_clean(self):
        for run in (self.second, self.slot):
            rp.RUN_TROUBLE.clear()
            run([job("HB1", {"action": "sent"}), job("HB2", {"action": "cached"})])
            self.assertFalse(rp.RUN_TROUBLE.is_set(), run.__name__)

    def test_per_bill_obstacle_is_clean(self):
        # A too-long bill hits LongContext every run: counting it would mean no run is ever idle.
        for run in (self.second, self.slot):
            rp.RUN_TROUBLE.clear()
            run([job("HB1", {"action": "not_submitted", "reason_type": "LongContext"})])
            self.assertFalse(rp.RUN_TROUBLE.is_set(), run.__name__)

    def test_not_submitted_stop_is_not_idle(self):
        for run in (self.second, self.slot):
            rp.RUN_TROUBLE.clear()
            run([job("HB1", {"action": "not_submitted", "reason_type": "OutcomeUnresolved"}),
                 job("HB2", {"action": "sent"})])
            self.assertTrue(rp.RUN_TROUBLE.is_set(), run.__name__)

    def test_cooling_down_skip_is_not_idle(self):
        for run in (self.second, self.slot):
            rp.RUN_TROUBLE.clear()
            run([job("HB1", CacheCoolingDown("cooling"))])
            self.assertTrue(rp.RUN_TROUBLE.is_set(), run.__name__)

    def test_time_limit_is_not_idle(self):
        for run in (self.second, self.slot):
            rp.RUN_TROUBLE.clear()
            run([job("HB1", {"action": "sent"})], deadline=0)
            self.assertTrue(rp.RUN_TROUBLE.is_set(), run.__name__)


if __name__ == "__main__":
    unittest.main()
