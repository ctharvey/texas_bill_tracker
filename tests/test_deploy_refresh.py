"""A publish that changes a server job's code asks texas-bill-refresh to rerun that job, after main has moved."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
import deploy_static as deploy

OLD, NEW = 'b' * 40, 'a' * 40


class FakeGit:
    def __init__(self, main: str | None, changed: list[str] | None):
        self.main, self.changed, self.calls = main, changed, []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == 'rev-parse':
            if 'refs/heads/main^{commit}' in args:
                if self.main is None:
                    raise subprocess.CalledProcessError(1, 'git')
                return (self.main + '\n').encode()
            return (NEW + '\n').encode()
        if args[0] == 'update-ref':
            self.main = args[2]
        if args[0] == 'diff':
            if self.changed is None:
                raise subprocess.CalledProcessError(128, 'git')
            return '\n'.join(self.changed).encode()
        return b''


class JobsFor(unittest.TestCase):
    def test_each_job_follows_its_own_inputs(self):
        self.assertEqual(deploy.jobs_for(['scripts/sync_ftp.py']), ['data'])
        self.assertEqual(deploy.jobs_for(['scripts/atlas/feeds/brackets.py']), ['data'])
        self.assertEqual(deploy.jobs_for(['src/taxonomy.js']), ['agent'])
        self.assertEqual(deploy.jobs_for(['scripts/og_warbler.mjs']), ['og'])
        self.assertEqual(deploy.jobs_for(['data/members_elect_2026.json']), ['members'])
        self.assertEqual(deploy.jobs_for(['scripts/og_art/HB1.jpg']), ['data', 'og'])

    def test_site_only_changes_rerun_nothing(self):
        self.assertEqual(deploy.jobs_for(['src/app.js', 'src/styles.css', 'index.html', 'CHANGELOG.md', 'tests/x.py']), [])

    def test_a_folder_prefix_does_not_match_a_sibling_name(self):
        self.assertEqual(deploy.jobs_for(['scripts/atlas_notes.md', 'data/census.md']), [])

    def test_the_review_unit_is_never_a_job(self):
        self.assertNotIn('review', deploy.JOB_INPUTS)


class RequestRefresh(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.state = Path(folder.name)
        patcher = mock.patch.object(deploy, 'STATE', self.state); patcher.start(); self.addCleanup(patcher.stop)

    def markers(self):
        folder = self.state / 'refresh'
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def test_changed_job_code_leaves_a_marker_per_job(self):
        with mock.patch.object(deploy, 'git', FakeGit(OLD, ['scripts/build_agent.mjs', 'scripts/sync_ftp.py'])):
            deploy.request_refresh(OLD, NEW)
        self.assertEqual(self.markers(), ['agent', 'data'])

    def test_the_same_commit_requests_nothing(self):
        fake = FakeGit(NEW, [])
        with mock.patch.object(deploy, 'git', fake):
            deploy.request_refresh(NEW, NEW)
        self.assertEqual(self.markers(), [])
        self.assertFalse([c for c in fake.calls if c[0] == 'diff'])

    def test_an_unknown_or_unreadable_old_commit_refreshes_every_job(self):
        for previous, changed in ((None, []), (OLD, None)):
            shutil.rmtree(self.state / 'refresh', ignore_errors=True)
            with mock.patch.object(deploy, 'git', FakeGit(previous, changed)):
                deploy.request_refresh(previous, NEW)
            self.assertEqual(self.markers(), sorted(deploy.JOB_INPUTS))

    def test_a_marker_failure_never_fails_the_publish(self):
        (self.state / 'refresh').write_text('not a folder')
        with mock.patch.object(deploy, 'git', FakeGit(OLD, ['scripts/sync_ftp.py'])):
            deploy.request_refresh(OLD, NEW)  # no exception


class MainOrdering(unittest.TestCase):
    """Markers appear only once refs/heads/main names the new commit, so a refreshed job runs the new code."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        (base / 'state').mkdir(); (base / 'site').mkdir()
        for name, value in (('STATE', base / 'state'), ('ROOT', base / 'site'), ('REPOSITORY', base / 'state')):
            patcher = mock.patch.object(deploy, name, value); patcher.start(); self.addCleanup(patcher.stop)
        for name, value in (('flock', lambda *a: None), ('LOCK_EX', 2), ('LOCK_NB', 4)):
            patcher = mock.patch.object(deploy.fcntl, name, value, create=True); patcher.start(); self.addCleanup(patcher.stop)
        self.release = base / 'site' / 'releases' / NEW

    def run_already_current(self, fake):
        seen, real, release = [], deploy.request_refresh, self.release

        def spy(previous, commit):
            seen.append(fake.main)  # where main points when the marker is written
            real(previous, commit)
        with mock.patch.object(deploy, 'git', fake), mock.patch.object(deploy, 'request_refresh', spy), \
                mock.patch.object(Path, 'is_symlink', lambda self: True), \
                mock.patch.object(Path, 'resolve', lambda self, strict=False: release):
            deploy.main()
        return seen

    def test_healing_a_crash_after_publishing_still_requests_the_refresh(self):
        fake = FakeGit(OLD, ['scripts/sync_ftp.py'])
        self.assertEqual(self.run_already_current(fake), [NEW])
        self.assertTrue((deploy.STATE / 'refresh' / 'data').exists())

    def test_a_routine_no_change_run_requests_nothing(self):
        fake = FakeGit(NEW, ['scripts/sync_ftp.py'])
        self.run_already_current(fake)
        self.assertFalse((deploy.STATE / 'refresh').exists())


SH = shutil.which('sh')


@unittest.skipUnless(SH, 'needs a POSIX sh')
class RefreshScript(unittest.TestCase):
    """refresh_jobs.sh against a fake systemctl that logs each call."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        self.markers, self.bin, self.log = base / 'refresh', base / 'bin', base / 'log'
        self.markers.mkdir(); self.bin.mkdir()
        self.fake_systemctl('inactive', 0)

    def fake_systemctl(self, state: str, start_status: int):
        script = self.bin / 'systemctl'
        script.write_text(
            '#!/bin/sh\n'
            f'echo "$*" >> "{self.log.as_posix()}"\n'
            f'if [ "$1" = show ]; then echo {state}; exit 0; fi\n'
            f'exit {start_status}\n', newline='\n')
        script.chmod(0o755)

    def run_script(self, *jobs):
        for job in jobs:
            (self.markers / job).touch()
        env = {**os.environ, 'TBA_REFRESH_DIR': self.markers.as_posix(),
               'PATH': f'{self.bin.as_posix()}{os.pathsep}{os.environ.get("PATH", "")}'}
        result = subprocess.run([SH, (ROOT / 'scripts' / 'refresh_jobs.sh').as_posix()], env=env,
                                capture_output=True, text=True, timeout=30)
        starts = [line for line in self.log.read_text().splitlines() if line.startswith('start')] if self.log.exists() else []
        return result, starts

    def test_jobs_start_in_order_and_markers_are_cleared(self):
        result, starts = self.run_script('og', 'agent', 'data', 'members')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(starts, [f'start texas-bill-{j}.service' for j in ('members', 'data', 'agent', 'og')])
        self.assertEqual(list(self.markers.iterdir()), [])

    def test_unknown_marker_names_are_ignored(self):
        result, starts = self.run_script('review', 'agent')
        self.assertEqual(starts, ['start texas-bill-agent.service'])
        self.assertTrue((self.markers / 'review').exists())

    def test_a_running_job_is_waited_for_then_run_again(self):
        self.fake_systemctl('activating', 0)
        result, starts = self.run_script('data')
        self.assertEqual(starts, ['start texas-bill-data.service'] * 2)

    def test_a_failed_job_fails_the_refresh_but_the_rest_still_run(self):
        self.fake_systemctl('inactive', 1)
        result, starts = self.run_script('data', 'agent')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(starts), 2)


if __name__ == '__main__':
    unittest.main()
