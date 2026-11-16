"""Session-wide test environment.

systemd sets INVOCATION_ID for every process it starts, including CI runners (GitHub's hosted runner jobs run under
it). review_pipeline.main treats INVOCATION_ID as "started by the review timer" and then waits up to 30 minutes on an
idle marker, so inherited, it hangs any test that runs main twice on one cache. Tests that need a timer-shaped run set
it themselves (tests/test_review_idle.py)."""
import os

os.environ.pop("INVOCATION_ID", None)
