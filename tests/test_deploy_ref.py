"""refs/heads/main in the deploy repository (what the data, members and agent units run) moves only with the site."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
import deploy_static as deploy

COMMIT = 'a' * 40


class FakeGit:
    def __init__(self, files: dict[str, bytes]):
        self.files, self.calls = files, []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == 'rev-parse':
            return (COMMIT + '\n').encode()
        if args[0] == 'ls-tree':
            return b'\0'.join(name.encode() for name in self.files)
        if args[0] == 'show':
            return self.files[args[1].split(':', 1)[1]]
        return b''

    def moved_main(self):
        return [c for c in self.calls if c[:2] == ('update-ref', 'refs/heads/main')]


def commit_files(snapshot: dict) -> dict[str, bytes]:
    files = {name: b'x' for name in deploy.DATA_FILES}
    files |= {'index.html': b'<link rel="stylesheet" href="./src/styles.css"><script type="module" src="./src/app.js">',
              'src/app.js': b'export {};', 'src/styles.css': b'body{}', deploy.SNAPSHOT: json.dumps(snapshot).encode()}
    return files


class DeployRef(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        (base / 'state').mkdir(); (base / 'site').mkdir()
        for name, value in (('STATE', base / 'state'), ('ROOT', base / 'site'), ('REPOSITORY', base / 'state')):
            patcher = mock.patch.object(deploy, name, value); patcher.start(); self.addCleanup(patcher.stop)
        for name, value in (('flock', lambda *a: None), ('LOCK_EX', 2), ('LOCK_NB', 4)):  # Linux-only module
            patcher = mock.patch.object(deploy.fcntl, name, value, create=True); patcher.start(); self.addCleanup(patcher.stop)

    def test_github_main_is_fetched_to_the_candidate_ref_not_main(self):
        fake = FakeGit(commit_files({'session': '90R', 'data_mode': 'curated', 'generated_at': '2026-11-13T00:00:00Z'}))
        with mock.patch.object(deploy, 'git', fake), self.assertRaises(ValueError):
            deploy.main()
        fetch = next(c for c in fake.calls if c[0] == 'fetch')
        self.assertEqual(fetch[-1], f'+refs/heads/main:{deploy.CANDIDATE}')

    def test_a_refused_snapshot_leaves_main_where_it_was(self):
        fake = FakeGit(commit_files({'session': '90R', 'data_mode': 'official-ftp', 'generated_at': '2026-11-13T00:00:00Z',
                                     'bills': [{'id': 'HB1'}]}))  # far too few bills
        with mock.patch.object(deploy, 'git', fake), self.assertRaises(ValueError):
            deploy.main()
        self.assertEqual(fake.moved_main(), [])

    def test_an_already_published_commit_still_points_main_at_it(self):
        fake = FakeGit({})
        release = deploy.ROOT / 'releases' / COMMIT
        with mock.patch.object(deploy, 'git', fake), \
                mock.patch.object(Path, 'is_symlink', lambda self: True), \
                mock.patch.object(Path, 'resolve', lambda self, strict=False: release):
            deploy.main()
        self.assertEqual(fake.moved_main(), [('update-ref', 'refs/heads/main', COMMIT)])


if __name__ == '__main__':
    unittest.main()
